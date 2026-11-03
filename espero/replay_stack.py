"""Full-stack replay with faults: a signal through the risk gate to a fill on the recorded book, journaled.

`FAULTS` says what each injected fault must do, written before the tests that hold it (tests/test_replay_stack.py
runs one test per row). The stack is the live path in miniature, built from the pieces that will run it: the latency
budgets (`espero.latency`), the clock check (`watchdog.clock_ok`), startup reconciliation (`reconcile.startup`), the
account gate (`risk.check`), client order ids fixed by the event and journaled before the send (`hlp_testnet`'s
idiom), and market orders walking the recorded whole book at arrival (`replaysim.book_at`, `replaysim.walk`). Resting
orders are out of scope here: #62 replays them. Everything is injected (clock, venue, faults), and the tests assert
behaviour, never P&L.

    espero replay-stack --day DAY     # #71's events on a recorded day through the stack: orders and refusals only
"""
from __future__ import annotations

import bisect
import hashlib
import sqlite3
from dataclasses import dataclass, field
from typing import Callable, Dict, Iterable, List, Mapping, Optional, Sequence, Set, Tuple

from . import latency, reconcile, replaysim, risk, watchdog

FAULTS: Dict[str, str] = {
    "dropped_frames": "a book older than the rule's budget at the decision is never traded on: the order is refused as "
                      "stale. Hyperliquid's l2Book frames are whole books with no sequence, so a dropped frame shows "
                      "only as the book's age; OKX's books carry a sequence, which tapewatch checks.",
    "venue_silent": "a venue with no frame for longer than 120 s takes no entry; the silence is journaled once, and "
                    "open positions are left to their registered exits, never closed blind.",
    "partial_fill": "a fill short of the order leaves the position at exactly what filled; the rest is not chased, and "
                    "the exit sells what was bought.",
    "restart": "a restart between sending an order and recording its fill sends no second order: the client order "
               "id is fixed by the event and journaled before the send, and the venue is asked for it first.",
    "unknown_position": "a position at the venue that the journal does not know refuses every entry until it is "
                        "resolved (reconcile.startup), and the break is journaled.",
    "clock_skew": "a clock more than a second off the time server's (watchdog.clock_ok) refuses every order.",
    "stale_input": "an event older than its rule's latency budget (research/LIVE_LATENCY.md) is refused, never traded "
                   "late.",
}
SILENCE_MS = int(watchdog.RAW_MAX_AGE_S * 1000)
LATENCY_MS = replaysim.LATENCY_MS

SCHEMA = """
CREATE TABLE IF NOT EXISTS stack_orders (
    cloid TEXT PRIMARY KEY, rule TEXT, coin TEXT, side INTEGER, leg TEXT, qty REAL, filled REAL DEFAULT 0,
    avg_px REAL, status TEXT, sent_ms INTEGER
);
CREATE TABLE IF NOT EXISTS stack_events (
    n INTEGER PRIMARY KEY AUTOINCREMENT, ms INTEGER, kind TEXT, rule TEXT, coin TEXT, detail TEXT
);
"""


@dataclass(frozen=True)
class Signal:
    rule: str
    sleeve: str
    coin: str
    side: int                     # +1 buy, -1 sell
    ts: int                       # the event's time, unix seconds
    notional: float               # what the sleeve asks for; the gate decides


def cloid(rule: str, coin: str, ts: int, leg: str) -> str:
    """Fixed by the event and the leg, so a resend after a restart is the same order: 0x + 32 hex."""
    return "0x" + hashlib.sha256(f"espero-stack|{rule}|{coin}|{ts}|{leg}".encode()).hexdigest()[:32]


class VenueSilent(TimeoutError):
    """The venue did not answer."""


@dataclass
class RecordedVenue:
    """The recorded whole book as a venue: a market order walks the book `latency_ms` after it is sent. Faults are
    set on it: a silent window, a fill share below one, positions it holds that no journal placed."""
    books: Dict[str, List[dict]]
    latency_ms: int = LATENCY_MS
    fill_share: float = 1.0
    silent: Optional[Tuple[int, int]] = None
    positions: Dict[str, float] = field(default_factory=dict)
    orders: Dict[str, dict] = field(default_factory=dict)
    sent: List[str] = field(default_factory=list)

    def last_frame_ms(self, coin: str, now_ms: int) -> Optional[int]:
        ts = [b["t"] for b in self.books.get(coin, []) if b["t"] <= now_ms]
        return max(ts) if ts else None

    def _quiet(self, now_ms: int) -> bool:
        return self.silent is not None and self.silent[0] <= now_ms < self.silent[1]

    def market(self, coin: str, side: int, qty: float, cid: str, now_ms: int) -> dict:
        self.sent.append(cid)
        if self._quiet(now_ms):
            raise VenueSilent(f"no answer at {now_ms}")
        book = replaysim.book_at(self.books.get(coin, []), now_ms + self.latency_ms)
        if book is None:
            out = {"status": "rejected", "filled": 0.0, "avg_px": None}
        else:
            px, share, _ = replaysim.walk(book, side, qty)
            done = qty * min(share, self.fill_share)
            out = {"status": "filled" if done > 0 else "rejected", "filled": done, "avg_px": px if done > 0 else None}
            self.positions[coin] = self.positions.get(coin, 0.0) + side * done
        self.orders[cid] = out
        return out

    def order_status(self, cid: str, now_ms: int) -> dict:
        if self._quiet(now_ms):
            raise VenueSilent(f"no answer at {now_ms}")
        return self.orders.get(cid, {"status": "unknownOid"})


class Stack:
    """One sleeve's live path, replayed: `startup` before the first order, `step` per signal, `exit` per hold."""

    def __init__(self, db: sqlite3.Connection, venue: RecordedVenue, account: Callable[[], risk.Account],
                 clock_offset_s: Callable[[], float] = lambda: 0.0, policy: risk.Policy = risk.POLICY):
        self.db, self.venue, self.account, self.offset, self.policy = db, venue, account, clock_offset_s, policy
        self.db.row_factory = sqlite3.Row
        self.db.executescript(SCHEMA)
        self.breaks: List[str] = []
        self._silence_logged: set = set()

    def _event(self, ms: int, kind: str, rule: str, coin: str, detail: str) -> None:
        self.db.execute("INSERT INTO stack_events (ms, kind, rule, coin, detail) VALUES (?,?,?,?,?)",
                        (ms, kind, rule, coin, detail))
        self.db.commit()

    def journal_positions(self) -> Dict[str, float]:
        out: Dict[str, float] = {}
        for r in self.db.execute("SELECT coin, side, filled FROM stack_orders WHERE filled > 0"):
            out[r["coin"]] = out.get(r["coin"], 0.0) + r["side"] * r["filled"]
        return out

    def startup(self, now_ms: int, step: Optional[Dict[str, float]] = None) -> List[str]:
        """First every order left in flight is looked up by its client id and its fill recorded, then the journal's
        positions are reconciled against the venue's (reconcile.startup); any break blocks entries and is journaled.
        An order the venue did not answer for leaves the journal's positions unknown, so the reconciliation waits:
        entries stay refused, and the next step asks again before anything else (a reconciliation run on a fill not
        yet recorded would report the venue's position as one the journal does not know, for ever)."""
        self._startup_step = step or {}
        unresolved = 0
        for r in self.db.execute("SELECT * FROM stack_orders WHERE status='inflight'").fetchall():
            try:
                st = self.venue.order_status(r["cloid"], now_ms)
            except VenueSilent:
                unresolved += 1                            # still unknown: asked again before any entry
                continue
            if st["status"] != "unknownOid":
                s = Signal(r["rule"], "", r["coin"], r["side"], 0, 0.0)
                self._record(r["cloid"], st, now_ms, s, "found filled at startup")
        self._startup_pending = unresolved > 0
        if self._startup_pending:
            self.breaks = [f"{unresolved} order(s) in flight and the venue silent: reconciled once it answers"]
            self._event(now_ms, "break", "", "", self.breaks[0])
            return self.breaks
        self.breaks = reconcile.startup(self.journal_positions(), dict(self.venue.positions), [], [],
                                        self._startup_step, owns_account=True)
        for b in self.breaks:
            self._event(now_ms, "break", "", "", b)
        return self.breaks

    def _refuse(self, s: Signal, now_ms: int, why: str) -> dict:
        self._event(now_ms, "refused", s.rule, s.coin, why)
        return {"placed": False, "reason": why}

    def _send(self, s: Signal, leg: str, side: int, qty: float, now_ms: int) -> dict:
        cid = cloid(s.rule, s.coin, s.ts, leg)
        row = self.db.execute("SELECT * FROM stack_orders WHERE cloid=?", (cid,)).fetchone()
        if row is not None:                               # sent before: ask the venue, never send twice
            try:
                st = self.venue.order_status(cid, now_ms)
            except VenueSilent as exc:                     # still unknown: nothing is resent on a silent venue
                self._event(now_ms, "no answer", s.rule, s.coin,
                            f"{leg} {cid}: {exc}; sent before, asked again before any resend")
                return {"placed": False, "reason": "sent before, no answer yet", "filled": 0.0}
            if st["status"] == "unknownOid":
                return self._fresh_send(s, cid, leg, side, row["qty"], now_ms, again=True)
            self._record(cid, st, now_ms, s, "recovered after a restart")
            return {"placed": False, "reason": "already sent: recovered from the venue", "filled": st["filled"]}
        self.db.execute("INSERT INTO stack_orders (cloid, rule, coin, side, leg, qty, status, sent_ms) "
                        "VALUES (?,?,?,?,?,?, 'inflight', ?)", (cid, s.rule, s.coin, side, leg, qty, now_ms))
        self.db.commit()                                  # journaled before the send
        return self._fresh_send(s, cid, leg, side, qty, now_ms)

    def _fresh_send(self, s: Signal, cid: str, leg: str, side: int, qty: float, now_ms: int, again=False) -> dict:
        try:
            out = self.venue.market(s.coin, side, qty, cid, now_ms)
        except VenueSilent as exc:
            self._event(now_ms, "no answer", s.rule, s.coin, f"{leg} {cid}: {exc}; asked again before any resend")
            return {"placed": True, "reason": "sent, no answer yet", "filled": 0.0}
        self._record(cid, out, now_ms, s, "sent again: the venue had never seen it" if again else "sent")
        return {"placed": True, "reason": out["status"], "filled": out["filled"]}

    def _record(self, cid: str, out: dict, now_ms: int, s: Signal, note: str) -> None:
        self.db.execute("UPDATE stack_orders SET filled=?, avg_px=?, status=? WHERE cloid=?",
                        (out["filled"], out["avg_px"], out["status"], cid))
        self.db.commit()
        self._event(now_ms, out["status"], s.rule, s.coin, f"{cid}: {note}, filled {out['filled']:.8g}")

    def step(self, s: Signal, now_ms: int) -> dict:
        """An entry, in the order the live path checks: clock, breaks, staleness, the venue's silence, the book's age,
        the risk gate, then the send."""
        if not watchdog.clock_ok(self.offset()):
            return self._refuse(s, now_ms, f"clock off by {self.offset():+.2f} s")
        if getattr(self, "_startup_pending", False):
            self.startup(now_ms, self._startup_step)       # the venue may answer now: finish the startup first
        if self.breaks:
            return self._refuse(s, now_ms, f"an open break: {self.breaks[0]}")
        row = latency.by_test().get(s.rule)
        if row is None or not row.budget_s:
            return self._refuse(s, now_ms, f"no latency budget for #{s.rule} (research/LIVE_LATENCY.md): not traded")
        budget_ms = int(row.budget_s * 1000)
        if now_ms - s.ts * 1000 > budget_ms:
            return self._refuse(s, now_ms, f"stale: {now_ms - s.ts * 1000} ms after the event, budget {budget_ms} ms")
        last = self.venue.last_frame_ms(s.coin, now_ms)
        if last is None or now_ms - last > SILENCE_MS:
            if s.coin not in self._silence_logged:
                self._silence_logged.add(s.coin)
                self._event(now_ms, "silence", s.rule, s.coin, "no frame from the venue for over 120 s")
            return self._refuse(s, now_ms, "venue silent")
        if now_ms - last > budget_ms:
            return self._refuse(s, now_ms, f"stale book: {now_ms - last} ms old, budget {budget_ms} ms")
        book = replaysim.book_at(self.venue.books[s.coin], now_ms, max_age_ms=max(budget_ms, 1))
        if book is None or not book["bids"] or not book["asks"]:
            return self._refuse(s, now_ms, "no usable book: none inside the budget, or one side empty")
        mid = (book["bids"][0][0] + book["asks"][0][0]) / 2
        ruling = risk.check(risk.Order(s.sleeve, s.rule, "replay", s.coin, s.side, s.notional), self.account(),
                            self.policy)
        if not ruling.allowed:
            return self._refuse(s, now_ms, "risk: " + ruling.reasons[0])
        return self._send(s, "entry", s.side, ruling.notional / mid, now_ms)

    def exit(self, s: Signal, now_ms: int) -> dict:
        """The registered exit: sells exactly what the entry bought (a partial fill exits partially). The clock check
        holds here too: an order on a clock a second off the time server's is refused, entry or exit."""
        if not watchdog.clock_ok(self.offset()):
            return self._refuse(s, now_ms, f"clock off by {self.offset():+.2f} s")
        entry = self.db.execute("SELECT filled FROM stack_orders WHERE cloid=?",
                                (cloid(s.rule, s.coin, s.ts, "entry"),)).fetchone()
        if entry is None or not entry["filled"]:
            return {"placed": False, "reason": "nothing to exit"}
        return self._send(s, "exit", -s.side, float(entry["filled"]), now_ms)

    def events(self) -> List[sqlite3.Row]:
        return self.db.execute("SELECT * FROM stack_events ORDER BY n").fetchall()


def replay_account(capital: float = 10_000.0, sleeve: str = "replay") -> Callable[[], risk.Account]:
    """A replay's account: capital the replay assumes, labelled so, never the holder's (theirs is 0 until answered)."""
    return lambda: risk.Account(capital=capital, equity=capital, equity_by_venue={"replay": capital},
                                day_start=capital, week_start=capital, peak=capital, sleeve_scale={sleeve: 1.0})


def summary(events: Sequence[sqlite3.Row]) -> Dict[str, int]:
    """Orders and refusals by reason, for the CLI: counts only."""
    out: Dict[str, int] = {}
    for e in events:
        key = e["kind"] if e["kind"] != "refused" else "refused: " + e["detail"].split(":")[0]
        out[key] = out.get(key, 0) + 1
    return out


def recorded_books(frames: Iterable[dict], at: Mapping[str, Sequence[int]], before_ms: int = SILENCE_MS + 1_000,
                   after_ms: int = 60_000) -> Tuple[Dict[str, List[dict]], Set[str]]:
    """Each coin's recorded `l2Book` frames from `before_ms` before to `after_ms` after any of its decision times
    `at`, in one pass, so a day of tape is never held whole (Hyperliquid's is gigabytes as dicts); and every coin
    the tape holds a book for at all. The window covers what a decision reads: the book's age back to the silence
    limit, and the book its order meets."""
    times = {c: sorted(v) for c, v in at.items()}
    keep: Dict[str, List[dict]] = {c: [] for c in times}
    seen: Set[str] = set()
    for rec in frames:
        if rec.get("ch") != "l2Book" or not isinstance(rec.get("d"), dict):
            continue
        coin = rec.get("s")
        seen.add(coin)
        ts = times.get(coin)
        if not ts:
            continue
        t = int(rec["d"]["data"]["time"])
        i = bisect.bisect_left(ts, t - after_ms)          # the first decision at or after t - after_ms ...
        if i < len(ts) and ts[i] <= t + before_ms:        # ... and not later than t + before_ms
            keep[coin].append(rec)
    return {c: replaysim.books_and_trades(v, c)[0] for c, v in keep.items()}, seen


def main(argv=None) -> int:
    """#71's events on a recorded day through the stack, against the recorded Hyperliquid book: counts only. Each
    event is an entry decided when the engine emitted it and sized against the replay's empty account; exits are
    not replayed, so the per-coin and per-venue caps never bind here."""
    import argparse
    import json
    import os

    from . import livesig, rawrec

    ap = argparse.ArgumentParser(prog="espero replay-stack")
    ap.add_argument("--day", required=True)
    ap.add_argument("--capital", type=float, default=10_000.0, help="the replay's assumed capital, not the holder's")
    a = ap.parse_args(argv)
    raw = rawrec.raw_dir(os.environ)
    events, _ = livesig.replay(raw, a.day)

    def decided(e) -> int:
        return int(e.emitted_ms or e.ts * 1000)

    at: Dict[str, List[int]] = {}
    for e in events:
        at.setdefault(e.coin, []).append(decided(e))
    books, seen = recorded_books(rawrec.read_day(raw, "hyperliquid", a.day), at)
    stack = Stack(sqlite3.connect(":memory:"), RecordedVenue(books), replay_account(a.capital))
    stack.startup(0)
    for e in sorted(events, key=decided):
        stack.step(Signal(e.rule, "replay", e.coin, 1 if e.side == "buy" else -1, e.ts, 1_000.0), decided(e))
    print(json.dumps({"day": a.day, "events": len(events), "by_outcome": summary(stack.events()),
                      "no_hyperliquid_book": sorted(set(at) - seen)}, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
