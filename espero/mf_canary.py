"""Rule 8's plumbing canary, the sleeve `mf-canary` (research/CANARY_MF.md), on rung 1: the testnet.

One `Canary.step()` per call, each idempotent, so a loop can call it every few minutes and a restart picks up where
the journal stands:

1. take the operator's replies from the approvals inbox and apply them to the ledger; lapse what has timed out;
2. once Sunday's daily bar is complete, decide the week with `espero.mf.decide` fed the shadow book's holdings, and
   write the legs: exits for coins rule 8 dropped, entries for coins it added. An entry passes `risk.check` (the
   testnet's play capital, and beside it the holder's own capital, journaled) and becomes a proposal; a decision
   made after the budget is `late` and proposes nothing;
3. buy every approved entry with an IOC order, and sell every due exit, exactly the canary's own size, with IOC
   orders that cross further on each unfilled try (not reduce-only: the account is shared and netted, see
   REDUCE_ONLY_EXITS); an order with no answer is looked up by its client id before anything is resent;
4. match every filled leg to the venue's fills by order id, and count round trips only when both legs match.

The testnet account is shared with #59's executor, so the canary reads its holdings from its own journal, never from
the venue's totals, and never cancels or closes anything it did not open.
"""

from __future__ import annotations

import hashlib
import json
import math
import sqlite3
import time
from dataclasses import replace
from pathlib import Path
from typing import Callable, Dict, List, Optional, Sequence, Tuple

from . import approvals, latency, risk, rungs
from .hl_exchange import round_price, round_size
from .hlp_testnet import ENTRY_SLIP, EXIT_SLIPS, MIN_NOTIONAL

SLEEVE = rungs.CANARY_MF
RULE = "8"
VENUE = "hyperliquid"
DB = "mf-canary.db"
STOP = "mf-canary.stop"
KILL = "KILL"
TESTNET_CAPITAL = 1_000.0  # the play capital the gate sizes against on the testnet (research/CANARY_MF.md)
ENTRY_USD = 12.0  # Hyperliquid's $10 minimum with room for rounding
ASSUMED_ROUND_TRIP_BPS = 18.0  # for a coin #39/#41 did not measure: the house's assumed round trip
ENTRY_TRIES = 3  # an IOC entry that finds no liquidity is tried again, then left unfilled
EXIT_TRIES = 8
# The testnet account is shared with #59's executor and carry-maker's mirror, whose perp leg is short, and Hyperliquid
# nets one position per coin per account: a reduce-only sell on an account that is net short is refused. So, as #59's
# executor does, an exit sells exactly the canary's own size with a plain IOC (docs/RUNBOOK.md, "#59 on testnet").
REDUCE_ONLY_EXITS = False
DAY_S = 86_400
ANSWER_WINDOW_S = approvals.MAX_WAIT_S - approvals.EXECUTION_ALLOWANCE_S   # the holder's amendment

SCHEMA = """
CREATE TABLE IF NOT EXISTS weeks (
    sunday TEXT PRIMARY KEY, decided INTEGER, held_in TEXT, picks TEXT, shadow TEXT, status TEXT, note TEXT
);
CREATE TABLE IF NOT EXISTS legs (
    id INTEGER PRIMARY KEY AUTOINCREMENT, sunday TEXT NOT NULL, coin TEXT NOT NULL, kind TEXT NOT NULL,
    side TEXT NOT NULL, usd REAL, size REAL, decision_px REAL, proposal TEXT, status TEXT NOT NULL,
    tries INTEGER DEFAULT 0, cloid TEXT, inflight TEXT, oid INTEGER, filled REAL DEFAULT 0, avg_px REAL,
    ruling_testnet TEXT, ruling_holder TEXT, created INTEGER, done INTEGER, note TEXT,
    UNIQUE(sunday, coin, kind)
);
"""


LIVE_EXITS = "('due', 'retry', 'dust', 'unlisted')"   # an exit still owed: at most one per coin

# ------------------------------------------------------------------------------------------------------- pure
def cloid(sunday: str, coin: str, kind: str, n: int) -> str:
    """A client order id fixed by the week, the coin, the leg and the try: 0x + 32 hex, the canary's own prefix."""
    return "0x" + hashlib.sha256(f"espero-mfcanary|{sunday}|{coin}|{kind}|{n}".encode()).hexdigest()[:32]


def monday_of(now: int) -> int:
    """00:00 UTC of the Monday on or before `now`: the moment rule 8's Sunday bar completes."""
    days = now // DAY_S
    return (days - (days + 3) % 7) * DAY_S  # 1970-01-01 was a Thursday


def deadline(monday: int) -> int:
    """The last moment an entry may still be approved: Monday 00:00 UTC plus the canary's answer window, a day less the
    execution allowance, by the holder's signed amendment of 2026-11-03 (research/CANARY_MF.md): 23:55 UTC, 6:55 p.m.
    Eastern in winter. #8's own budget of 8.4 hours closed before the holder's Monday morning; a plumbing canary proves
    the order path, so it waits for the holder, as no sleeve trading for an edge may."""
    return int(monday + ANSWER_WINDOW_S)


def plan(picks: Sequence[str], held: Dict[str, float]) -> Tuple[List[str], List[str]]:
    """(entries, exits): coins rule 8 added, and coins the canary holds that rule 8 dropped."""
    return sorted(set(picks) - set(held)), sorted(set(held) - set(picks))


def round_trip_bps(coin: str) -> float:
    """The registered round trip for the coin: #39/#41's measured cost, or the assumed 18 bps where none was."""
    from . import costs

    try:
        return float(costs.round_trip(VENUE, coin))
    except costs.NotMeasured:
        return ASSUMED_ROUND_TRIP_BPS


def matched(legs: Sequence[dict], fills: Sequence[dict], step: Dict[str, float]) -> Dict[int, bool]:
    """Each filled leg (by id): does the venue's record of its order id carry the same size, within the coin's step?"""
    from . import reconcile

    theirs = reconcile.by_oid(fills)
    out = {}
    for leg in legs:
        if not leg.get("filled"):
            continue
        ids = leg_oids(leg)
        got = [theirs[i] for i in ids if i in theirs]
        out[leg["id"]] = (bool(ids) and len(got) == len(ids)
                          and abs(sum(g["sz"] for g in got) - float(leg["filled"])) <= step.get(leg["coin"], 1e-9) / 2)
    return out


def leg_oids(leg: dict) -> List[int]:
    """Every venue order id the leg filled on: an exit can fill over several IOC tries, each its own order. A leg
    journaled before `oids` existed has only its last one."""
    try:
        ids = [int(i) for i in json.loads(leg.get("oids") or "[]")]
    except (ValueError, TypeError):
        ids = []
    if not ids and leg.get("oid") is not None:
        ids = [int(leg["oid"])]
    return ids


def round_trips(legs: Sequence[dict], ok: Dict[int, bool]) -> int:
    """Completed round trips: a filled entry and the next filled exit of the same coin, both matched to the venue."""
    n = 0
    by_coin: Dict[str, List[dict]] = {}
    for leg in sorted(legs, key=lambda g: (g["sunday"], g["kind"] != "entry")):
        by_coin.setdefault(leg["coin"], []).append(leg)
    for coin_legs in by_coin.values():
        entry = None
        for leg in coin_legs:
            if leg["status"] != "filled":
                continue
            if leg["kind"] == "entry":
                entry = leg
            elif entry is not None:
                n += int(ok.get(entry["id"], False) and ok.get(leg["id"], False))
                entry = None
    return n


# ----------------------------------------------------------------------------------------------------- runner
class Canary:
    """The canary's state and one step. `exchange` is a TestnetExchange (or a fake): `meta`, `book(coin)`,
    `limit(coin, side, size, price, tif, reduce_only, cloid)`, `order_status(cloid)`, `fills(since)`.
    `decide(sunday)` returns (rule 8's picks, the shadow book's held coins it was fed, the Sunday closes), or None
    when the week cannot be decided (too few coins loaded)."""

    def __init__(
        self,
        state: Path,
        exchange,
        decide: Callable[[str], Optional[Tuple[List[str], List[str], Dict[str, float]]]],
        key: Optional[bytes] = None,
        holder_capital: float = 0.0,
        notify: Callable[[str, str], None] = lambda title, msg: None,
        log: Callable[[str], None] = print,
        rows: Optional[Sequence[latency.Row]] = None,
    ):
        self.state = Path(state)
        self.state.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(self.state / DB)
        self.db.row_factory = sqlite3.Row
        self.db.executescript(SCHEMA)
        if "oids" not in {r[1] for r in self.db.execute("PRAGMA table_info(legs)")}:
            self.db.execute("ALTER TABLE legs ADD COLUMN oids TEXT")     # journals from before 2026-11-09
        self.db.commit()
        self.ledger = approvals.Ledger.open(self.state / approvals.LEDGER)
        self.ex, self.decide, self.key = exchange, decide, key
        self.holder_capital = holder_capital
        self.notify, self.log, self.rows = notify, log, rows

    def close(self) -> None:
        self.db.close()
        self.ledger.db.close()

    # -------------------------------------------------------------- reads
    def legs(self, where: str = "1", args: tuple = ()) -> List[dict]:
        return [dict(r) for r in self.db.execute(f"SELECT * FROM legs WHERE {where} ORDER BY id", args)]

    def held(self) -> Dict[str, float]:
        """What the canary holds, from its own journal: filled entries less what their exits have sold."""
        out: Dict[str, float] = {}
        for leg in self.legs("filled > 0"):
            out[leg["coin"]] = out.get(leg["coin"], 0.0) + (leg["filled"] if leg["kind"] == "entry" else -leg["filled"])
        return {c: s for c, s in out.items() if s > 1e-12}

    def stopped(self) -> bool:
        return (self.state / STOP).exists() or (self.state / KILL).exists()

    def _set(self, leg_id: int, **cols) -> None:
        self.db.execute(f"UPDATE legs SET {', '.join(f'{k}=?' for k in cols)} WHERE id=?", (*cols.values(), leg_id))

    # -------------------------------------------------------------- one step
    def step(self, now: Optional[int] = None) -> List[str]:
        now = int(time.time()) if now is None else int(now)
        out: List[str] = []
        self._answers(now, out)
        self._decide(now, out)
        self._sync(now, out)
        self._enter(now, out)
        self._exit(now, out)
        self.db.commit()
        for line in out:
            self.log(line)
        return out

    def _answers(self, now: int, out: List[str]) -> None:
        for item in approvals.take(self.state):
            if isinstance(item, approvals.Reply):
                o = self.ledger.answer(item, self.key, now)
                out.append(f"answer to {o.proposal}: {o.event} ({o.reason})")
        for o in self.ledger.expire(now):
            out.append(f"{o.proposal}: {o.reason}")

    def _decide(self, now: int, out: List[str]) -> None:
        monday = monday_of(now)
        sunday = time.strftime("%Y-%m-%d", time.gmtime(monday - DAY_S))
        if self.db.execute("SELECT 1 FROM weeks WHERE sunday=?", (sunday,)).fetchone():
            return
        late = now >= deadline(monday)
        held = self.held()
        if late and not held:  # nothing to sell, and too late to buy: no decision is needed
            self.db.execute(
                "INSERT INTO weeks (sunday, decided, status, note) VALUES (?,?,?,?)",
                (sunday, now, "late", "decided after the budget: nothing proposed"),
            )
            out.append(f"#8 canary {sunday}: late, nothing proposed")
            return
        got = self.decide(sunday)
        if got is None:  # the Sunday bar or too many coins missing: tried again next step
            return
        picks, shadow_held, px = got
        entries, exits = plan(picks, held)
        exits = self._exits_to_write(exits, picks, now, out)
        if late:  # exits never wait (research/CANARY_MF.md): a late week proposes nothing and still sells
            self.db.execute(
                "INSERT INTO weeks (sunday, decided, held_in, picks, shadow, status, note) VALUES (?,?,?,?,?,?,?)",
                (sunday, now, json.dumps(sorted(held)), json.dumps(sorted(picks)), json.dumps(sorted(shadow_held)),
                 "late", "decided after the budget: nothing proposed"),
            )
            for coin in exits:
                self.db.execute(
                    "INSERT INTO legs (sunday, coin, kind, side, size, status, created) VALUES (?,?,?,?,?,?,?)",
                    (sunday, coin, "exit", "sell", held[coin], "due", now),
                )
            out.append(f"#8 canary {sunday}: late, nothing proposed, exits {len(exits)}")
            return
        self.db.execute(
            "INSERT INTO weeks (sunday, decided, held_in, picks, shadow, status, note) VALUES (?,?,?,?,?,?,?)",
            (
                sunday,
                now,
                json.dumps(sorted(held)),
                json.dumps(sorted(picks)),
                json.dumps(sorted(shadow_held)),
                "decided",
                ""
                if set(held) == set(shadow_held)
                else f"the canary holds {sorted(held)}, the shadow book {sorted(shadow_held)}",
            ),
        )
        for coin in exits:
            self.db.execute(
                "INSERT INTO legs (sunday, coin, kind, side, size, status, created) VALUES (?,?,?,?,?,?,?)",
                (sunday, coin, "exit", "sell", held[coin], "due", now),
            )
        made = []
        for coin in entries:
            status, note, pid = self._propose(sunday, coin, px.get(coin), monday, now)
            self.db.execute(
                "INSERT INTO legs (sunday, coin, kind, side, usd, decision_px, proposal, status, created, "
                "ruling_testnet, ruling_holder, note) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                (sunday, coin, "entry", "buy", ENTRY_USD, px.get(coin), pid, status, now, *self._rulings(coin), note),
            )
            if pid:
                made.append(approvals.describe(self.ledger.proposal(pid)))
        out.append(f"#8 canary {sunday}: picks {len(picks)}, entries {len(entries)}, exits {len(exits)}")
        if made:
            self.notify(
                f"espero: {len(made)} canary proposal(s) for your answer",
                "\n".join(made) + f"\nanswer by {time.strftime('%H:%M UTC', time.gmtime(deadline(monday)))}"
                f" ({time.strftime('%a %H:%M %Z', time.localtime(deadline(monday)))} here)",
            )

    def _exits_to_write(self, exits: Sequence[str], picks: Sequence[str], now: int, out: List[str]) -> List[str]:
        """The dropped coins that need a new exit leg. A coin whose earlier exit is still live (waiting on an empty
        book, under the venue's minimum, or unlisted) keeps that one leg: two legs for one holding would sell it
        twice, on an account shared with other sleeves. And a live exit for a coin rule 8 picked again is withdrawn,
        so last week's sell cannot go out in a week the rule holds the coin."""
        live = {leg["coin"]: leg for leg in self.legs(f"kind='exit' AND status IN {LIVE_EXITS}")}
        for coin, leg in live.items():
            if coin in picks:
                self._set(leg["id"], status="withdrawn", done=now, note="rule 8 picked the coin again before it sold")
                out.append(f"#8 canary {coin}: its pending exit is withdrawn, rule 8 picked it again")
        return [c for c in exits if c not in live]

    def _gate(self, coin: str, capital: float) -> risk.Ruling:
        held = self.held()
        positions = tuple(risk.Position(VENUE, c, SLEEVE, 1, s * self._mark(c, s)) for c, s in held.items())
        acct = risk.Account(
            capital=capital,
            equity=capital,
            equity_by_venue={VENUE: capital},
            positions=positions,
            sleeve_scale={SLEEVE: 1.0},
            paused=self.stopped(),
        )
        return risk.check(risk.Order(SLEEVE, RULE, VENUE, coin, 1, ENTRY_USD, min_notional=MIN_NOTIONAL), acct)

    def _mark(self, coin: str, size: float) -> float:
        for leg in reversed(self.legs("coin=? AND kind='entry' AND filled > 0", (coin,))):
            return float(leg["avg_px"] or 0.0)
        return 0.0

    def _rulings(self, coin: str) -> Tuple[str, str]:
        def text(r: risk.Ruling) -> str:
            return json.dumps({"allowed": r.allowed, "notional": r.notional, "reasons": list(r.reasons)})

        return text(self._gate(coin, TESTNET_CAPITAL)), text(self._gate(coin, self.holder_capital))

    def _propose(
        self, sunday: str, coin: str, px: Optional[float], monday: int, now: int
    ) -> Tuple[str, str, Optional[str]]:
        """(status, note, proposal id) for one entry."""
        if self.stopped():
            return "stopped", "the stop or KILL file is set", None
        if coin not in self.ex.meta:
            return "not_on_testnet", "the testnet does not list it", None
        if not px or not math.isfinite(px) or px <= 0:
            return "no_price", "no Sunday close", None
        ruling = self._gate(coin, TESTNET_CAPITAL)
        if not ruling.allowed:
            return "refused_gate", "; ".join(ruling.reasons), None
        p = approvals.propose(
            RULE,
            SLEEVE,
            coin,
            "buy",
            min(ENTRY_USD, ruling.notional),
            px,
            round_trip_bps(coin),
            None,
            now,
            event_ts=monday,
            note=f"rule 8's plumbing canary, week of {sunday}",
            rows=self.rows,
        )
        p = replace(p, expires=deadline(monday))
        self.ledger.record(p)
        return "proposed", "", p.id

    def _sync(self, now: int, out: List[str]) -> None:
        """Proposals the operator has answered, or that lapsed, become approved, rejected or silence legs."""
        for leg in self.legs("kind='entry' AND status='proposed'"):
            st = self.ledger.status(leg["proposal"])
            if st in ("approved", "modified"):
                usd = self._answered_usd(leg["proposal"], leg["usd"])
                self._set(leg["id"], status="approved", usd=usd)
                out.append(f"#8 canary {leg['coin']}: {st}, ${usd:,.2f}")
            elif st in ("rejected", "silence"):
                self._set(leg["id"], status=st, done=now)
                out.append(f"#8 canary {leg['coin']}: {st}, not taken")

    def _answered_usd(self, pid: str, proposed: float) -> float:
        for e in reversed(self.ledger.events()):
            if e["proposal"] == pid and e["event"] == "modified":
                try:
                    return min(proposed, float(json.loads(e["body"]).get("notional") or proposed))
                except ValueError:
                    return proposed
        return proposed

    # -------------------------------------------------------------- orders
    def _known(self, leg: dict) -> Optional[dict]:
        """An order sent and not answered: the venue's record of it by client id, or None if it never arrived."""
        if not leg.get("inflight"):
            return None
        st = self.ex.order_status(leg["inflight"])
        order = st.get("order") if isinstance(st, dict) else None
        return order if isinstance(st, dict) and st.get("status") == "order" and order else None

    def _resolve(self, leg: dict, known: dict) -> float:
        """Record what an order found by client id did: its size filled, its average price from the venue's fills."""
        inner = known.get("order", {})
        oid = int(inner["oid"]) if inner.get("oid") is not None else None
        filled = max(0.0, float(inner.get("origSz", 0) or 0) - float(inner.get("sz", 0) or 0))
        self._set(leg["id"], inflight=None)
        if filled <= 0 or oid is None:
            return float(leg["filled"] or 0.0)
        fills = [f for f in self.ex.fills(int(leg["created"] or 0)) if int(f.get("oid", -1)) == oid]
        sz = sum(float(f["sz"]) for f in fills)
        avg = sum(float(f["px"]) * float(f["sz"]) for f in fills) / sz if sz else None
        return self._record_fill(leg, filled, avg, oid)

    def _send(
        self, leg: dict, size: float, px: float, reduce_only: bool
    ) -> Tuple[float, Optional[float], Optional[int], Optional[str]]:
        """One IOC order for the leg, journaled as in flight before it is sent. (filled, avg_px, oid, error)."""
        cid = cloid(leg["sunday"], leg["coin"], leg["kind"], int(leg["tries"]))
        self._set(leg["id"], inflight=cid, tries=int(leg["tries"]) + 1)
        self.db.commit()
        r = self.ex.limit(leg["coin"], leg["side"], size, px, tif="Ioc", reduce_only=reduce_only, cloid=cid)
        self._set(leg["id"], inflight=None)
        return float(r.filled or 0.0), r.avg_px, r.oid, r.error

    def _record_fill(self, leg: dict, filled: float, avg_px: Optional[float], oid: Optional[int]) -> float:
        total = float(leg["filled"] or 0.0) + filled
        avg = (
            avg_px if not leg["filled"] else ((leg["avg_px"] or 0.0) * leg["filled"] + (avg_px or 0.0) * filled) / total
        )
        ids = leg_oids(leg)
        if oid is not None and int(oid) not in ids:
            ids.append(int(oid))
        self._set(leg["id"], filled=total, avg_px=avg, oid=oid if oid is not None else leg["oid"], oids=json.dumps(ids))
        return total

    def _enter(self, now: int, out: List[str]) -> None:
        for leg in self.legs("kind='entry' AND status='approved'"):
            if self.stopped():
                self._set(leg["id"], status="stopped", done=now)
                continue
            known = self._known(leg)
            if known is not None:  # sent before a restart: never sent twice
                total = self._resolve(leg, known)
                self._set(
                    leg["id"],
                    status="filled" if total > 0 else "unfilled",
                    done=now,
                    note="resolved by client id after a restart",
                )
                continue
            if leg["inflight"]:
                self._set(leg["id"], inflight=None)  # it never reached the venue: safe to send again
                leg = self.legs("id=?", (leg["id"],))[0]
            if now >= deadline(monday_of(int(leg["created"]))):
                self._set(leg["id"], status="late", done=now, note="approved, but past the budget before it filled")
                continue
            try:
                bid, ask = self.ex.book(leg["coin"])
            except ValueError as exc:
                self._set(leg["id"], note=str(exc))
                continue
            sd = self.ex.meta[leg["coin"]]
            px = round_price(ask * (1 + ENTRY_SLIP), sd, "buy")
            size = round_size(float(leg["usd"]) / ask, sd)
            if size * ask < MIN_NOTIONAL:
                self._set(leg["id"], status="too_small", done=now)
                continue
            filled, avg, oid, err = self._send(leg, size, px, reduce_only=False)
            if filled > 0:
                self._record_fill(leg, filled, avg, oid)
                self._set(leg["id"], status="filled", size=size, done=now)
                out.append(f"#8 canary bought {filled:g} {leg['coin']} at {avg:g}")
            elif int(leg["tries"]) + 1 >= ENTRY_TRIES:
                self._set(leg["id"], status="unfilled", done=now, note=err or "no fill")
                out.append(f"#8 canary {leg['coin']}: entry unfilled after {ENTRY_TRIES} tries")

    def _exit(self, now: int, out: List[str]) -> None:
        if self.stopped():  # sell everything the canary holds, nothing else
            sunday = time.strftime("%Y-%m-%d", time.gmtime(now))
            for coin, size in self.held().items():
                if not self.legs(f"coin=? AND kind='exit' AND status IN {LIVE_EXITS}", (coin,)):
                    self.db.execute(
                        "INSERT OR IGNORE INTO legs (sunday, coin, kind, side, size, status, created, note) "
                        "VALUES (?,?,?,?,?,?,?,?)",
                        (f"stop-{sunday}", coin, "exit", "sell", size, "due", now, "the stop file"),
                    )
        for leg in self.legs(f"kind='exit' AND status IN {LIVE_EXITS}"):
            sd = self.ex.meta.get(leg["coin"])
            if sd is None:  # the testnet dropped the coin: nothing can be sold, and it is not called sold
                self._wait(leg, "unlisted", "the testnet no longer lists it: still held, nothing sold")
                continue
            known = self._known(leg)
            if known is not None:
                self._resolve(leg, known)
            elif leg["inflight"]:
                self._set(leg["id"], inflight=None)
            leg = self.legs("id=?", (leg["id"],))[0]
            left = float(leg["size"]) - float(leg["filled"] or 0.0)
            if left <= 10**-sd / 2:
                self._set(leg["id"], status="filled", done=now)
                continue
            try:
                bid, ask = self.ex.book(leg["coin"])
            except ValueError as exc:
                self._set(leg["id"], note=str(exc))
                continue
            if round_size(left, sd) * bid < MIN_NOTIONAL:  # the venue refuses it; it waits for a higher price
                self._wait(leg, "dust", f"{left:g} left is under the venue's ${MIN_NOTIONAL:.0f} minimum at {bid:g}: "
                                        "still held, waiting for a higher price")
                continue
            slip = EXIT_SLIPS[min(int(leg["tries"]), len(EXIT_SLIPS) - 1)]
            filled, avg, oid, err = self._send(
                leg, round_size(left, sd), round_price(bid * (1 - slip), sd, "sell"), reduce_only=REDUCE_ONLY_EXITS
            )
            total = self._record_fill(leg, filled, avg, oid) if filled > 0 else float(leg["filled"] or 0.0)
            if float(leg["size"]) - total <= 10**-sd / 2:
                self._set(leg["id"], status="filled", done=now)
                out.append(f"#8 canary sold {leg['coin']}")
            elif int(leg["tries"]) + 1 >= EXIT_TRIES:
                self._set(leg["id"], status="stuck", note=err or "unfilled after every try")
                out.append(f"#8 canary {leg['coin']}: exit STUCK after {EXIT_TRIES} tries; the operator is needed")
                self.notify("espero: a canary exit is stuck", f"{leg['coin']}: {err or 'no fill'}")
            else:
                self._set(leg["id"], status="retry")

    def _wait(self, leg: dict, status: str, note: str) -> None:
        """An exit that cannot be sent now stays live under a status that says why; the operator is told once."""
        if leg["status"] != status:
            self._set(leg["id"], status=status, note=note)
            self.notify("espero: a canary exit is waiting", f"{leg['coin']}: {note}")
            self.log(f"#8 canary {leg['coin']}: exit waiting, {note}")

    # -------------------------------------------------------------- the rung
    def rung(self, since: int = 0) -> dict:
        """Round trips matched to the venue's fills, against this sleeve's bar."""
        legs = self.legs()
        step = {c: 10**-sd for c, sd in self.ex.meta.items()}
        ok = matched(legs, self.ex.fills(since), step)
        breaks = [leg["id"] for leg in legs if leg["id"] in ok and not ok[leg["id"]]]
        return {
            "round_trips": round_trips(legs, ok),
            "needed": rungs.testnet_round_trips(SLEEVE),
            "breaks": breaks,
            "held": self.held(),
        }


def summary(state: Path) -> List[str]:
    """The canary's journal, read only."""
    p = Path(state) / DB
    if not p.exists():
        return ["#8 canary: no journal yet"]
    db = sqlite3.connect(f"file:{p}?mode=ro", uri=True)
    db.row_factory = sqlite3.Row
    try:
        out = []
        for w in db.execute("SELECT * FROM weeks ORDER BY sunday DESC LIMIT 4"):
            out.append(f"week of {w['sunday']}: {w['status']}" + (f" ({w['note']})" if w["note"] else ""))
        for r in db.execute("SELECT kind, status, COUNT(*) n FROM legs GROUP BY kind, status ORDER BY kind, status"):
            out.append(f"  {r['kind']} {r['status']}: {r['n']}")
        return out
    finally:
        db.close()


# ------------------------------------------------------------------------------------- the live decision
def shadow_held(db: Path, monday: int) -> List[str]:
    """The coins the shadow book `mf-hl` held going into this Sunday's decision: its last rebalance before `monday`.
    Read only; an absent book holds nothing."""
    p = Path(db)
    if not p.exists():
        return []
    con = sqlite3.connect(f"file:{p}?mode=ro", uri=True)
    try:
        row = con.execute(
            "SELECT weights FROM mf_account WHERE ts < ? AND note LIKE 'rebalance%' ORDER BY ts DESC, id DESC LIMIT 1",
            (monday,),
        ).fetchone()
    except sqlite3.OperationalError:
        return []
    finally:
        con.close()
    if not row or not row[0]:
        return []
    return sorted(c for c, w in json.loads(row[0]).items() if w and float(w) > 0)


def hl_decide(state: Path, fetch=None) -> Callable[[str], Optional[Tuple[List[str], List[str], Dict[str, float]]]]:
    """Rule 8's decision on Hyperliquid's daily bars, as the shadow book makes it, fed the shadow book's holdings.
    None when the Sunday bar is missing or fewer than `mf.MIN_UNIVERSE` coins closed that day."""
    import pandas as pd

    from . import hyperliquid as hl
    from . import mf, panel

    def decide(sunday: str):
        p = panel.build(mf.UNIVERSE, span=mf.SPAN, fetch=fetch or hl.daily)
        sun = pd.Timestamp(sunday)
        if sun not in p.index or int(p.close.loc[sun].notna().sum()) < mf.MIN_UNIVERSE:
            return None
        held = shadow_held(Path(state) / "mf-hl.db", int((sun + pd.Timedelta(days=1)).timestamp()))
        w = mf.decide(p, sun, held)
        picks = sorted(c for c, v in w.items() if v > 0)
        return picks, held, {c: float(v) for c, v in p.close.loc[sun].dropna().items()}

    return decide
