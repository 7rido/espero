"""#59's signals placed as real orders on Hyperliquid's testnet, to prove the order path, never the edge.

It reads #59's paper journal (`hlp2-book.db`) and never writes to it. A signal the book has just found is
bought with a crossing IOC at the testnet ask; four hours after that fill, the same quantity is sold with
a crossing IOC at the testnet bid, retried and pushed further through the book until it is gone.

What it measures is mechanics: how late the order is after the signal, whether it fills, slippage against
the testnet mid, and fees. Testnet prices and depth aren't mainnet's, so no P&L here is a result; #59's
verdict comes only from its ledger (research/FORWARD_HLP2.md).

The testnet account is shared with carry-maker's mirror, and Hyperliquid nets one position per coin per
account. So nothing here reads the account's positions or sends a reduce-only order: every trade is
tracked by its own client order ids and filled quantities, and its exit sells exactly what its entry bought.

A file named like the journal with `.stop` (`hlp2-testnet.stop`) is the kill switch: while it exists, new
signals are skipped and every open trade is sold at once.
"""
from __future__ import annotations

import hashlib
import sqlite3
import time
from pathlib import Path
from typing import Callable, List, Optional

from .hl_exchange import TestnetExchange, round_size
from .hlpbook import FILL_TOLERANCE_S, HOLD_S

MIN_NOTIONAL = 10.0             # Hyperliquid rejects an order worth less
ENTRY_SLIP = 0.005              # the IOC buy may pay up to 50 bps over the testnet ask
EXIT_SLIPS = (0.005, 0.02, 0.05, 0.10)   # each unfilled exit try crosses further; the last repeats
LATE_S = FILL_TOLERANCE_S       # a signal seen later than the rule's own fill tolerance is not traded
ENTERABLE = ("pending", "open", "closed")   # the paper book's statuses that mean it took the trade

SCHEMA = """CREATE TABLE IF NOT EXISTS hlp_testnet (
    coin TEXT, signal_ts INTEGER, status TEXT, paper_status TEXT,
    entry_cloid TEXT, entry_oid INTEGER, entry_ts INTEGER, entry_mid REAL, entry_px REAL, qty REAL DEFAULT 0,
    entry_fee REAL,
    exit_due INTEGER, exit_oid INTEGER, exit_ts INTEGER, exit_mid REAL, exit_px REAL, exited REAL DEFAULT 0,
    exit_tries INTEGER DEFAULT 0, exit_fee REAL,
    inflight TEXT, inflight_leg TEXT, note TEXT,
    PRIMARY KEY (coin, signal_ts))"""


def cloid(coin: str, signal_ts: int, leg: str, n: int = 0) -> str:
    """A client order id fixed by the trade, the leg and the try: 0x + 32 hex."""
    return "0x" + hashlib.sha256(f"espero-hlp59|{coin}|{signal_ts}|{leg}|{n}".encode()).hexdigest()[:32]


class Executor:
    """One step per call: resolve orders whose outcome is unknown, enter new signals, exit what is due,
    and fill in fees. `now` is injected in tests; the exchange is a TestnetExchange (or a fake one)."""

    def __init__(self, state, book, exchange: TestnetExchange, usd: float = 100.0, log: Callable = print):
        if usd < MIN_NOTIONAL * 1.1:
            raise ValueError(f"--usd {usd} is under Hyperliquid's ${MIN_NOTIONAL:.0f} minimum with room to spare")
        self.db = sqlite3.connect(state)
        self.db.row_factory = sqlite3.Row
        self.db.execute(SCHEMA)
        self.db.commit()
        self.book, self.ex, self.usd, self.log = Path(book), exchange, usd, log
        self.stop_file = Path(state).with_suffix(".stop")
        self.said = ""

    def close(self) -> None:
        self.db.close()

    def _say_once(self, text: str) -> None:
        if text != self.said:
            self.log(text)
            self.said = text

    def rows(self, where: str = "1", args: tuple = ()) -> List[sqlite3.Row]:
        return self.db.execute(f"SELECT * FROM hlp_testnet WHERE {where} ORDER BY signal_ts, coin", args).fetchall()

    def _set(self, r, **cols) -> None:
        sets = ", ".join(f"{k}=?" for k in cols)
        self.db.execute(f"UPDATE hlp_testnet SET {sets} WHERE coin=? AND signal_ts=?",
                        (*cols.values(), r["coin"], r["signal_ts"]))

    def _note(self, r, text: str) -> None:
        self.db.execute("UPDATE hlp_testnet SET note=COALESCE(note || '; ', '') || ? WHERE coin=? AND signal_ts=?",
                        (text, r["coin"], r["signal_ts"]))

    # ------------------------------------------------------------------ the paper journal
    def paper(self) -> List[sqlite3.Row]:
        """#59's journal, read-only. Empty until the book has written one."""
        if not self.book.exists():
            return []
        db = sqlite3.connect(f"file:{self.book}?mode=ro", uri=True)
        db.row_factory = sqlite3.Row
        try:
            return db.execute("SELECT coin, signal_ts, status FROM trades ORDER BY signal_ts, coin").fetchall()
        except sqlite3.OperationalError:            # the book hasn't made its table yet
            return []
        finally:
            db.close()

    # ------------------------------------------------------------------ one step
    def step(self, now: Optional[int] = None) -> List[str]:
        now = int(time.time()) if now is None else now
        out: List[str] = []
        stop = self.stop_file.exists()
        if stop:
            self._say_once(f"kill switch {self.stop_file} is set: no new entries, every open trade is sold")
        self._resolve(out)
        self._enter(now, stop, out)
        self._exit(now, stop, out)
        self._fees()
        self.db.commit()
        for line in out:
            self.log(line)
        return out

    def _enter(self, now: int, stop: bool, out: List[str]) -> None:
        known = {(r["coin"], r["signal_ts"]) for r in self.rows()}
        holding = {r["coin"] for r in self.rows("status IN ('open', 'entering')")}
        for p in self.paper():
            key = (p["coin"], p["signal_ts"])
            if key in known:
                continue
            status = ("paper_skip" if p["status"] not in ENTERABLE else
                      "late" if now - p["signal_ts"] > LATE_S else
                      "not_on_testnet" if p["coin"] not in self.ex.meta else
                      "held" if p["coin"] in holding else "entering")
            self.db.execute("INSERT INTO hlp_testnet (coin, signal_ts, status, paper_status) VALUES (?,?,?,?)",
                            (*key, status, p["status"]))
            known.add(key)
            if status == "entering":
                holding.add(p["coin"])
            else:
                out.append(f"#59 testnet {p['coin']} {p['signal_ts']}: {status}")
        # new signals, and those whose last try found no book or never reached the venue
        for r in self.rows("status='entering' AND inflight IS NULL"):
            if now - r["signal_ts"] > LATE_S:
                self._set(r, status="late")
                self._note(r, "no order sent within the rule's 5 minutes")
                out.append(f"#59 testnet {r['coin']}: no entry within 5 minutes of the signal")
            elif stop:
                self._set(r, status="stopped")
            else:
                self._buy(r, now, out)

    def _buy(self, r, now: int, out: List[str]) -> None:
        coin = r["coin"]
        try:
            bid, ask = self.ex.book(coin)
        except Exception as exc:  # noqa: BLE001 - retried next step while the signal is fresh
            out.append(f"#59 testnet {coin}: no book ({exc}); retried next step while the signal is fresh")
            return
        mid, cid = (bid + ask) / 2, cloid(coin, r["signal_ts"], "entry")
        self._set(r, entry_cloid=cid, entry_ts=now, entry_mid=mid, inflight=cid, inflight_leg="entry")
        self.db.commit()                            # the cloid is on disk before the order leaves
        try:
            res = self.ex.limit(coin, "buy", self.usd / ask, ask * (1 + ENTRY_SLIP), tif="Ioc", cloid=cid)
        except Exception as exc:  # noqa: BLE001 - the outcome is looked up by cloid next step
            self._note(r, f"entry call failed: {str(exc)[:120]}")
            out.append(f"#59 testnet {coin}: entry sent, outcome unknown ({exc}); looked up next step")
            return
        self._entered(r, res.oid, res.filled, res.avg_px, now, res.error)
        out.append(f"#59 testnet {coin}: buy {res.size} IOC <= {res.price} -> {res.status}"
                   + (f" {res.filled} @ {res.avg_px} (mid {mid:.6g})" if res.filled else "")
                   + (f" ({res.error})" if res.error else ""))

    def _entered(self, r, oid, filled: float, px, now: int, error=None) -> None:
        if filled and filled > 0:
            self._set(r, status="open", entry_oid=oid, entry_px=px, qty=filled, exit_due=now + HOLD_S,
                      inflight=None, inflight_leg=None)
        else:
            self._set(r, status="unfilled", entry_oid=oid, inflight=None, inflight_leg=None)
            if error:
                self._note(r, f"entry: {error}")

    def _exit(self, now: int, stop: bool, out: List[str]) -> None:
        for r in self.rows("status='open' AND inflight IS NULL"):
            if now < r["exit_due"] and not stop:
                continue
            self._sell(r, now, out)

    def _sell(self, r, now: int, out: List[str]) -> None:
        coin, left = r["coin"], r["qty"] - r["exited"]
        if round_size(left, self.ex.meta[coin]) <= 0:
            self._set(r, status="closed")
            return
        try:
            bid, ask = self.ex.book(coin)
        except Exception as exc:  # noqa: BLE001 - retried next step
            out.append(f"#59 testnet {coin}: no book for the exit ({exc}); retried next step")
            return
        tries = r["exit_tries"]
        slip = EXIT_SLIPS[min(tries, len(EXIT_SLIPS) - 1)]
        mid, cid = (bid + ask) / 2, cloid(coin, r["signal_ts"], "exit", tries)
        if left * bid < MIN_NOTIONAL:
            # under the venue's minimum the sell is refused; a shared account can't be flattened by
            # reduce-only either, so the dust stays and is noted
            self._set(r, status="closed")
            self._note(r, f"{left:g} {coin} left under the ${MIN_NOTIONAL:.0f} minimum")
            out.append(f"#59 testnet {coin}: {left:g} left is under ${MIN_NOTIONAL:.0f}; closed with dust noted")
            return
        self._set(r, exit_tries=tries + 1, exit_ts=now, exit_mid=r["exit_mid"] or mid, inflight=cid,
                  inflight_leg="exit")
        self.db.commit()
        try:
            res = self.ex.limit(coin, "sell", left, bid * (1 - slip), tif="Ioc", cloid=cid)
        except Exception as exc:  # noqa: BLE001
            self._note(r, f"exit call failed: {str(exc)[:120]}")
            out.append(f"#59 testnet {coin}: exit sent, outcome unknown ({exc}); looked up next step")
            return
        self._exited(r, res.oid, res.filled, res.avg_px, res.error)
        out.append(f"#59 testnet {coin}: sell {res.size} IOC >= {res.price} (try {tries + 1}) -> {res.status}"
                   + (f" {res.filled} @ {res.avg_px}" if res.filled else "")
                   + (f" ({res.error})" if res.error else ""))

    def _exited(self, r, oid, filled: float, px, error=None) -> None:
        r = self.rows("coin=? AND signal_ts=?", (r["coin"], r["signal_ts"]))[0]
        filled = filled or 0.0
        done = r["exited"] + filled
        avg = r["exit_px"]
        if filled > 0 and px:
            avg = px if not r["exited"] else (r["exit_px"] * r["exited"] + px * filled) / done
        flat = done >= r["qty"] * (1 - 1e-6)
        self._set(r, exited=done, exit_px=avg, exit_oid=oid or r["exit_oid"], inflight=None, inflight_leg=None,
                  status="closed" if flat else "open")
        if error:
            self._note(r, f"exit try {r['exit_tries']}: {error}")

    # ------------------------------------------------------------------ after a lost call
    def _resolve(self, out: List[str]) -> None:
        """An order whose call failed is looked up by its cloid. Never seen by the venue: the entry is
        sent again while the signal is fresh, the exit with its next try."""
        for r in self.rows("inflight IS NOT NULL"):
            try:
                st = self.ex.order_status(r["inflight"])
            except Exception as exc:  # noqa: BLE001 - stays inflight; nothing new is sent for it
                out.append(f"#59 testnet {r['coin']}: lookup of {r['inflight_leg']} failed ({exc})")
                continue
            if not isinstance(st, dict) or st.get("status") != "order":
                self._set(r, inflight=None, inflight_leg=None)
                self._note(r, f"{r['inflight_leg']} never reached the venue")
                out.append(f"#59 testnet {r['coin']}: {r['inflight_leg']} never reached the venue")
                continue
            o = st["order"]["order"]
            oid = int(o["oid"])
            filled = float(o.get("origSz", 0)) - float(o.get("sz", 0))
            px = self._avg_px(oid)
            if r["inflight_leg"] == "entry":
                self._entered(r, oid, filled, px, r["entry_ts"])
            else:
                self._exited(r, oid, filled, px)
            out.append(f"#59 testnet {r['coin']}: {r['inflight_leg']} found by cloid, {filled:g} filled")

    def _avg_px(self, oid: int) -> Optional[float]:
        fills = [f for f in self.ex.fills() if int(f.get("oid", -1)) == oid]
        qty = sum(float(f["sz"]) for f in fills)
        return sum(float(f["sz"]) * float(f["px"]) for f in fills) / qty if qty else None

    def _fees(self) -> None:
        """Fees from the venue's fills, once both legs' orders are known."""
        need = self.rows("(entry_oid IS NOT NULL AND entry_fee IS NULL AND qty > 0) "
                         "OR (status='closed' AND exit_oid IS NOT NULL AND exit_fee IS NULL)")
        if not need:
            return
        try:
            fills = self.ex.fills()
        except Exception:  # noqa: BLE001 - fees wait for the next step
            return
        fee = {}
        for f in fills:
            fee[int(f.get("oid", -1))] = fee.get(int(f.get("oid", -1)), 0.0) + float(f.get("fee", 0) or 0)
        for r in need:
            if r["entry_fee"] is None and r["entry_oid"] in fee:
                self._set(r, entry_fee=fee[r["entry_oid"]])
            if r["status"] == "closed" and r["exit_fee"] is None and r["exit_oid"] in fee:
                self._set(r, exit_fee=fee[r["exit_oid"]])


def summary(state) -> List[str]:
    """What the executor did. Mechanics only: testnet prices are not mainnet's, and this is not #59's result."""
    if not Path(state).exists():
        return ["#59 testnet: no journal yet"]
    db = sqlite3.connect(state)
    db.row_factory = sqlite3.Row
    db.execute(SCHEMA)
    rows = db.execute("SELECT * FROM hlp_testnet").fetchall()
    db.close()
    counts: dict = {}
    for r in rows:
        counts[r["status"]] = counts.get(r["status"], 0) + 1
    lines = ["#59 testnet: " + (", ".join(f"{k} {v}" for k, v in sorted(counts.items())) or "no signals yet")]
    filled = [r for r in rows if r["qty"] and r["entry_px"] and r["entry_mid"]]
    if filled:
        lag = sorted(r["entry_ts"] - r["signal_ts"] for r in filled)[len(filled) // 2]
        slip_in = sum(1e4 * (r["entry_px"] / r["entry_mid"] - 1) for r in filled) / len(filled)
        lines.append(f"entries filled {len(filled)}: median {lag}s after the signal, "
                     f"paid {slip_in:+.1f} bps over the testnet mid on average")
    out = [r for r in rows if r["status"] == "closed" and r["exit_px"] and r["exit_mid"]]
    if out:
        slip_out = sum(1e4 * (1 - r["exit_px"] / r["exit_mid"]) for r in out) / len(out)
        tries = sum(r["exit_tries"] for r in out) / len(out)
        lines.append(f"exits {len(out)}: gave up {slip_out:+.1f} bps under the testnet mid, {tries:.1f} tries each")
    for r in rows:
        if r["status"] == "open" or r["inflight"]:
            lines.append(f"  open {r['coin']} {r['qty'] - r['exited']:g} since {r['entry_ts']}, "
                         f"sell due {r['exit_due']}"
                         + (f", {r['inflight_leg']} outcome unknown" if r["inflight"] else ""))
    lines.append("mechanics only: testnet prices and depth are not mainnet's; #59's result is its ledger")
    return lines
