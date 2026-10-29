"""Hypothesis #42 — dress rehearsal of the real-fill test, run once on Hyperliquid's testnet.

    python research/rehearsal.py          # sends testnet orders; about 30-40 minutes

Frozen in research/PREREGISTRATION_REHEARSAL.md. One loop places and polls orders for all coins
(signed requests stay sequential, so nonces never collide); a reader thread records the book.
"""
from __future__ import annotations

import json
import math
import statistics
import sys
import threading
import time
import urllib.request
from pathlib import Path
from typing import Dict, List

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "research"))
from testnet_check import price_tick  # noqa: E402

from espero import reconcile as rc  # noqa: E402
from espero.broker import load_env  # noqa: E402
from espero.hl_exchange import TestnetExchange  # noqa: E402

N_COINS = 5
MAX_GAP = 0.01
MAX_SPREAD_BPS = 50
NOTIONAL = 12.0
ORDERS_EACH = 20
REST_S = 60
TAIL_S = 360
POLL_S = 2.0
HORIZONS = (1, 10, 60, 300)
MAJORS_CONS = {"BTC": {1: -0.60, 10: -1.31, 60: -1.42, 300: -1.24},      # #39, Hyperliquid, conservative
               "ETH": {1: -1.14, 10: -1.83, 60: -1.81, 300: -1.55}}
LOG = ROOT / "research" / "rehearsal_session.json"


def now_ms() -> int:
    return int(time.time() * 1000)


def post(url: str, body: dict):
    r = urllib.request.Request(url + "/info", data=json.dumps(body).encode(), headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(r, timeout=30) as f:
        return json.load(f)


def choose_coins() -> List[str]:
    mm, mc = post("https://api.hyperliquid.xyz", {"type": "metaAndAssetCtxs"})
    ranked = [u["name"] for _, u in sorted(((float(c["dayNtlVlm"]), u) for u, c in zip(mm["universe"], mc)
                                            if not u.get("isDelisted")), key=lambda x: -x[0])]
    tm, tc = post("https://api.hyperliquid-testnet.xyz", {"type": "metaAndAssetCtxs"})
    ctx = {u["name"]: c for u, c in zip(tm["universe"], tc)}
    chosen = []
    for n in ranked:
        if n not in ctx:
            continue
        lv = post("https://api.hyperliquid-testnet.xyz", {"type": "l2Book", "coin": n})["levels"]
        if not lv[0] or not lv[1]:
            continue
        bid, ask = float(lv[0][0]["px"]), float(lv[1][0]["px"])
        oracle = float(ctx[n]["oraclePx"])
        if abs((bid + ask) / 2 / oracle - 1) <= MAX_GAP and (ask - bid) / bid * 1e4 < MAX_SPREAD_BPS:
            chosen.append(n)
        if len(chosen) == N_COINS:
            break
    return chosen


class Recorder(threading.Thread):
    """Best bid and ask of each coin, once a second, with the local receive time."""

    def __init__(self, ex: TestnetExchange, coins: List[str]):
        super().__init__(daemon=True)
        self.ex, self.coins, self.rows, self.errors = ex, coins, [], 0
        self.stop = threading.Event()

    def run(self):
        while not self.stop.is_set():
            t0 = time.time()
            for c in self.coins:
                try:
                    lv = self.ex.info.l2_snapshot(c)["levels"]
                    bid, ask = float(lv[0][0]["px"]), float(lv[1][0]["px"])
                    self.rows.append((now_ms(), c, (bid + ask) / 2))
                except Exception:
                    self.errors += 1
            self.stop.wait(max(0.0, 1.0 - (time.time() - t0)))


class Rehearsal:
    def __init__(self, ex: TestnetExchange, coins: List[str]):
        self.ex, self.coins = ex, coins
        self.events: List[dict] = []
        self.ours: Dict[int, dict] = {}
        self.intended = {c: 0.0 for c in coins}
        self.pos_breaks: List[str] = []
        self.latency: List[float] = []
        self.step = {c: 10 ** -ex.meta[c] for c in coins}

    def send(self, coin, side, size, price, tif, reduce_only=False, kind=""):
        t0 = now_ms()
        r = self.ex.limit(coin, side, size, price, tif=tif, reduce_only=reduce_only)
        self.latency.append(now_ms() - t0)
        ev = {"kind": kind, "coin": coin, "side": side, "size": r.size, "price": r.price, "tif": tif,
              "sent": t0, "status": r.status, "oid": r.oid, "filled": r.filled, "avg_px": r.avg_px, "error": r.error}
        self.events.append(ev)
        return ev

    def order_state(self, oid):
        q = self.ex.info.query_order_by_oid(self.ex.address, int(oid))
        o = q.get("order", {}) if isinstance(q, dict) else {}
        inner = o.get("order", {})
        return o.get("status"), max(0.0, float(inner.get("origSz", 0) or 0) - float(inner.get("sz", 0) or 0))

    def actual(self) -> Dict[str, float]:
        out = {}
        for p in self.ex.positions().get("positions", []):
            out[p["coin"]] = p["size"] if p["side"] == "long" else -p["size"]
        return out

    def flatten(self, coin, when):
        q = self.intended[coin]
        if abs(q) < self.step[coin] / 2:
            return
        bid, ask = self.ex.book(coin)
        side = "sell" if q > 0 else "buy"
        px = bid * 0.995 if side == "sell" else ask * 1.005
        ev = self.send(coin, side, abs(q), px, "Ioc", reduce_only=True, kind="flatten")
        if ev["oid"] is not None:
            self.ours[ev["oid"]] = {"tif": "Ioc", "filled": ev["filled"], "avg_px": ev["avg_px"]}
            self.intended[coin] += -ev["filled"] if side == "sell" else ev["filled"]
        time.sleep(1.0)
        b = rc.positions_match({coin: self.intended[coin]}, {coin: self.actual().get(coin, 0.0)}, self.step)
        self.pos_breaks += [f"{when}: {x}" for x in b]

    def run(self) -> int:
        start = now_ms()
        print(f"session start {start}; coins (by rule): {self.coins}", flush=True)
        fees = self.ex.info.user_fees(self.ex.address)
        maker, taker = float(fees["userAddRate"]), float(fees["userCrossRate"])
        rec = Recorder(self.ex, self.coins)
        rec.start()
        time.sleep(3)
        size = {}
        for c in self.coins:
            bid, ask = self.ex.book(c)
            sd = self.ex.meta[c]
            size[c] = math.ceil(NOTIONAL / ((bid + ask) / 2) * 10 ** sd) / 10 ** sd
        placed = {c: 0 for c in self.coins}
        resting: Dict[str, dict] = {}
        while any(placed[c] < ORDERS_EACH for c in self.coins) or resting:
            for c in self.coins:
                r = resting.get(c)
                if r is None:
                    if placed[c] >= ORDERS_EACH:
                        continue
                    bid, ask = self.ex.book(c)
                    side = "buy" if placed[c] % 2 == 0 else "sell"
                    ev = self.send(c, side, size[c], bid if side == "buy" else ask, "Alo", kind="maker")
                    placed[c] += 1
                    if ev["oid"] is not None:
                        resting[c] = {"ev": ev, "t": time.time()}
                    continue
                status, filled = self.order_state(r["ev"]["oid"])
                if status != "filled" and time.time() - r["t"] < REST_S:
                    continue
                if status != "filled":
                    self.ex.cancel(c, r["ev"]["oid"])
                    time.sleep(0.5)
                    status, filled = self.order_state(r["ev"]["oid"])
                ev = r["ev"]
                ev["final_status"], ev["final_filled"] = status, filled
                self.ours[ev["oid"]] = {"tif": "Alo", "filled": filled, "avg_px": None}
                self.intended[c] += filled if ev["side"] == "buy" else -filled
                del resting[c]
                print(f"{c} {ev['side']} {placed[c]}/{ORDERS_EACH}: {status} {filled}", flush=True)
                if abs(self.intended[c]) > 2 * size[c] + self.step[c] / 2:
                    self.flatten(c, f"{c} after order {placed[c]}")
            time.sleep(POLL_S)
        last_order = now_ms()
        for c in self.coins:
            self.flatten(c, f"{c} at the end")
        for o in self.ex.open_orders():
            if o["coin"] in self.coins:
                self.ex.cancel(o["coin"], o["oid"])
        time.sleep(2)
        orphans = [o for o in self.ex.open_orders() if o["coin"] in self.coins]
        end_breaks = rc.positions_match(self.intended, {c: v for c, v in self.actual().items() if c in self.coins},
                                        self.step)
        if any(abs(v) >= self.step[c] / 2 for c, v in self.intended.items()):
            end_breaks.append(f"not flat by our own record: {self.intended}")
        print(f"orders done; recording the book for {TAIL_S} s more", flush=True)
        time.sleep(TAIL_S)
        rec.stop.set()
        rec.join(5)
        fills = [f for f in self.ex.info.user_fills_by_time(self.ex.address, start)
                 if int(f["time"]) >= start and f["coin"] in self.coins]
        return self.verdict(start, last_order, fills, maker, taker, rec, orphans, end_breaks)

    def verdict(self, start, last_order, fills, maker, taker, rec, orphans, end_breaks) -> int:
        steps = {e["oid"]: self.step[e["coin"]] for e in self.events if e["oid"] is not None}
        ticks = {e["oid"]: price_tick(e["price"], self.ex.meta[e["coin"]]) for e in self.events if e["oid"] is not None}
        took = [f"oid {f['oid']}: ALO filled as taker" for f in fills
                if self.ours.get(int(f["oid"]), {}).get("tif") == "Alo" and f["crossed"]]
        maker_fills = [f for f in fills if not f["crossed"]]
        marks = rc.fill_markouts(maker_fills, rec.rows, HORIZONS)
        unmarked = [f"oid {m['oid']} +{h}s" for m in marks for h in HORIZONS if m[h] is None]
        crit = {
            "1a post-only never takes": took,
            "1b every fill reconciles": rc.fills_match(self.ours, fills, steps, ticks),
            "1c fees are the schedule's": rc.fees_match(fills, maker, taker),
            "1d flags agree with the order type": rc.flags_match(self.ours, fills),
            "2 position holds what was intended": self.pos_breaks + end_breaks,
            "3 every maker fill is marked": unmarked,
            "4 no orphan orders": [f"{o['coin']} oid {o['oid']}" for o in orphans],
            "5 the rule chose five coins": [] if len(self.coins) == N_COINS else [f"only {self.coins}"],
        }
        print(f"\n#42 — {len(fills)} exchange fills ({len(maker_fills)} maker); {len(rec.rows)} book rows "
              f"({rec.errors} read errors)")
        for name, b in crit.items():
            print(f"  {name}: {'met' if not b else f'NOT met ({len(b)})'}")
            for x in b[:15]:
                print("     ", x)
        verdict = "PASS" if not any(crit.values()) else "FAIL"
        print("VERDICT:", verdict)

        print("\ninformation only — testnet, NOT representative of mainnet:")
        for c in self.coins:
            mk = [e for e in self.events if e["coin"] == c and e["kind"] == "maker" and e["oid"] is not None]
            nf = sum(1 for e in mk if e.get("final_filled", 0) > 0)
            row = [m for m in marks if m["coin"] == c]
            hs = "  ".join(f"+{h}s {statistics.mean([m[h] for m in row if m[h] is not None]):+.2f}"
                           if any(m[h] is not None for m in row) else f"+{h}s —" for h in HORIZONS)
            ref = MAJORS_CONS.get(c)
            refs = ("   #39 mainnet conservative: " + "  ".join(f"+{h}s {ref[h]:+.2f}" for h in HORIZONS)) if ref else ""
            print(f"  {c}: filled {nf} of {len(mk)} within {REST_S} s; markout bps {hs}{refs}")
        if self.latency:
            xs = sorted(self.latency)
            print(f"  send → ack: median {statistics.median(xs):.0f} ms, p90 {xs[int(0.9 * (len(xs) - 1))]:.0f} ms")
        LOG.write_text(json.dumps({"start": start, "last_order": last_order, "coins": self.coins, "events": self.events,
                                   "fills": fills, "intended_end": self.intended, "breaks": crit, "marks": marks,
                                   "book_rows": len(rec.rows), "verdict": verdict}, indent=1, default=str))
        print(f"-> {LOG}")
        return 0 if verdict == "PASS" else 1


if __name__ == "__main__":
    load_env()
    coins = choose_coins()
    raise SystemExit(Rehearsal(TestnetExchange(), coins).run())
