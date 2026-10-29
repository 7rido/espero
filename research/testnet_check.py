"""Hypothesis #40 — the fill-reconciliation plumbing, run once on Hyperliquid's testnet.

    python research/testnet_check.py          # sends testnet orders; about 30 minutes

Frozen in research/PREREGISTRATION_TESTNET.md. Testnet only: espero/hl_exchange.py's guards refuse
anything else. No key is printed or written; the session log holds orders, acknowledgements and fills.
"""
from __future__ import annotations

import json
import math
import statistics
import sys
import time
from pathlib import Path
from typing import Dict, List

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from espero import reconcile as rc  # noqa: E402
from espero.broker import load_env  # noqa: E402
from espero.hl_exchange import MAX_DECIMALS_PERP, MAX_SIG_FIGS, TestnetExchange  # noqa: E402

COINS = ["BTC", "ETH", "SOL"]
NOTIONAL = 12.0
TRANSFER = 200.0
CROSS_EACH = 5
MAKER_ROUNDS = 10
MAKER_WAIT_S = 60
TAKER_ROUNDS = 3
THROUGH = 0.005
POLL_S = 2.0
LOG = ROOT / "research" / "testnet_session.json"


def now_ms() -> int:
    return int(time.time() * 1000)


def price_tick(px: float, sd: int) -> float:
    return 10 ** -min(MAX_DECIMALS_PERP - sd, max(0, MAX_SIG_FIGS - 1 - int(math.floor(math.log10(px)))))


class Session:
    def __init__(self, ex: TestnetExchange):
        self.ex = ex
        self.events: List[dict] = []
        self.ours: Dict[int, dict] = {}
        self.step: Dict[int, float] = {}
        self.tick: Dict[int, float] = {}
        self.mids: List[tuple] = []
        self.cross: List[dict] = []
        self.latency: Dict[str, List[float]] = {"Alo": [], "Ioc": []}

    def book(self, coin):
        bid, ask = self.ex.book(coin)
        self.mids.append((now_ms(), coin, (bid + ask) / 2))
        return bid, ask

    def send(self, coin, side, size, price, tif, reduce_only=False, kind=""):
        t0 = now_ms()
        r = self.ex.limit(coin, side, size, price, tif=tif, reduce_only=reduce_only)
        t1 = now_ms()
        self.latency[tif].append(t1 - t0)
        ev = {"kind": kind, "coin": coin, "side": side, "size": r.size, "price": r.price, "tif": tif,
              "reduce_only": reduce_only, "sent": t0, "ack": t1, "status": r.status, "oid": r.oid,
              "filled": r.filled, "avg_px": r.avg_px, "error": r.error}
        self.events.append(ev)
        if r.oid is not None:
            sd = self.ex.meta[coin]
            self.step[r.oid] = 10 ** -sd
            self.tick[r.oid] = price_tick(r.price, sd)
        return ev

    def order_state(self, oid):
        """(status, filled size) from the exchange's order-status endpoint."""
        q = self.ex.info.query_order_by_oid(self.ex.address, int(oid))
        o = q.get("order", {}) if isinstance(q, dict) else {}
        inner = o.get("order", {})
        orig, left = float(inner.get("origSz", 0) or 0), float(inner.get("sz", 0) or 0)
        return o.get("status", q.get("status") if isinstance(q, dict) else None), max(0.0, orig - left)

    def flatten(self, coin, size):
        bid, _ = self.book(coin)
        ev = self.send(coin, "sell", size, bid * (1 - THROUGH), "Ioc", reduce_only=True, kind="flatten")
        if ev["oid"] is not None:
            self.ours[ev["oid"]] = {"tif": "Ioc", "filled": ev["filled"], "avg_px": ev["avg_px"]}
        return ev

    def size(self, coin):
        sd = self.ex.meta[coin]
        bid, ask = self.book(coin)
        return math.ceil(NOTIONAL / ((bid + ask) / 2) * 10 ** sd) / 10 ** sd

    def run(self) -> int:
        start = now_ms()
        self.events.append({"kind": "transfer", "amount": TRANSFER,
                            "resp": str(self.ex.ex.usd_class_transfer(TRANSFER, True))[:200], "t": start})
        fees = self.ex.info.user_fees(self.ex.address)
        maker, taker = float(fees["userAddRate"]), float(fees["userCrossRate"])
        print(f"session start {start}; fees maker {maker} taker {taker}", flush=True)

        for coin in COINS:                                   # 1. post-only must refuse to cross
            sz = self.size(coin)
            for _ in range(CROSS_EACH):
                bid, ask = self.book(coin)
                self.cross.append(self.send(coin, "buy", sz, ask, "Alo", kind="cross"))
                self.cross.append(self.send(coin, "sell", sz, bid, "Alo", kind="cross"))
                time.sleep(0.3)
            for ev in self.cross[-2 * CROSS_EACH:]:          # anything that rested is cancelled at once
                if ev["status"] == "resting":
                    self.ex.cancel(coin, ev["oid"])
        print(f"post-only: {sum(e['status'] == 'error' for e in self.cross)} of {len(self.cross)} refused", flush=True)

        for coin in COINS:                                   # 2. maker fills
            sz = self.size(coin)
            for k in range(MAKER_ROUNDS):
                bid, _ = self.book(coin)
                ev = self.send(coin, "buy", sz, bid, "Alo", kind="maker")
                if ev["oid"] is None:
                    continue
                status, filled = "resting", 0.0
                t_end = time.time() + MAKER_WAIT_S
                while time.time() < t_end:
                    time.sleep(POLL_S)
                    self.book(coin)
                    status, filled = self.order_state(ev["oid"])
                    if status == "filled":
                        break
                if status != "filled":
                    self.ex.cancel(coin, ev["oid"])
                    time.sleep(1.0)
                    status, filled = self.order_state(ev["oid"])
                ev["final_status"], ev["final_filled"] = status, filled
                self.ours[ev["oid"]] = {"tif": "Alo", "filled": filled, "avg_px": None}
                print(f"{coin} maker {k + 1}: {status}, filled {filled}", flush=True)
                if filled > 0:
                    self.flatten(coin, filled)

        for coin in COINS:                                   # 3. taker fills
            sz = self.size(coin)
            for _ in range(TAKER_ROUNDS):
                _, ask = self.book(coin)
                ev = self.send(coin, "buy", sz, ask * (1 + THROUGH), "Ioc", kind="taker")
                if ev["oid"] is not None:
                    self.ours[ev["oid"]] = {"tif": "Ioc", "filled": ev["filled"], "avg_px": ev["avg_px"]}
                if ev["filled"]:
                    self.flatten(coin, ev["filled"])

        for o in self.ex.open_orders():                      # end flat
            self.ex.cancel(o["coin"], o["oid"])
        pos = self.ex.positions()
        print("positions at the end:", pos, flush=True)

        time.sleep(60)
        fills = [f for f in self.ex.info.user_fills_by_time(self.ex.address, start) if int(f["time"]) >= start]
        return self.verdict(start, fills, maker, taker, pos)

    def verdict(self, start, fills, maker, taker, pos) -> int:
        crit = {
            "1 post-only refuses": rc.post_only_refused(self.cross, fills),
            "2 every fill reconciles": rc.fills_match(self.ours, fills, self.step, self.tick),
            "3 fees are the schedule's": rc.fees_match(fills, maker, taker),
            "4 flags agree with the order type": rc.flags_match(self.ours, fills),
        }
        print(f"\n#40 — {len(fills)} exchange fills since {start}; {len(self.ours)} orders in our record")
        for name, breaks in crit.items():
            print(f"  {name}: {'met' if not breaks else f'NOT met ({len(breaks)} breaks)'}")
            for b in breaks[:20]:
                print("     ", b)
        verdict = "PASS" if not any(crit.values()) else "FAIL"
        print("VERDICT:", verdict)

        print("\ninformation only:")
        for tif, xs in self.latency.items():
            if xs:
                xs = sorted(xs)
                print(f"  send → ack latency {tif}: median {statistics.median(xs):.0f} ms, "
                      f"p90 {xs[int(0.9 * (len(xs) - 1))]:.0f} ms, n {len(xs)}")
        makers = [e for e in self.events if e.get("kind") == "maker" and e.get("oid") is not None]
        filled = [e for e in makers if e.get("final_filled", 0) > 0]
        print(f"  maker fill rate within {MAKER_WAIT_S} s: {len(filled)} of {len(makers)}")
        mk = []
        for f in fills:
            o = self.ours.get(int(f["oid"]))
            if o and o["tif"] == "Alo":
                later = [m for t, c, m in self.mids if c == f["coin"] and t >= int(f["time"]) + 60_000]
                if later:
                    s = 1 if f["side"] == "B" else -1
                    mk.append(s * (later[0] / float(f["px"]) - 1) * 1e4)
        if mk:
            print(f"  testnet 60 s maker markout (NOT representative of mainnet): {statistics.mean(mk):+.2f} bps, "
                  f"n {len(mk)}")
        LOG.write_text(json.dumps({"start": start, "maker_rate": maker, "taker_rate": taker, "events": self.events,
                                   "fills": fills, "ours": {str(k): v for k, v in self.ours.items()},
                                   "breaks": crit, "positions_end": pos, "verdict": verdict}, indent=1, default=str))
        print(f"-> {LOG}")
        return 0 if verdict == "PASS" else 1


if __name__ == "__main__":
    load_env()
    raise SystemExit(Session(TestnetExchange()).run())
