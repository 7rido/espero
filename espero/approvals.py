"""The operator's protocol in code: proposals, replies with a one-time code, timeouts, every answer journaled.

docs/OPERATOR.md is the protocol; this is its machinery. Two modes. The machine proposes and the operator
approves, for operator-paced rules only (research/LIVE_LATENCY.md). The operator proposes and the machine
checks, for an instance of a registered rule's live event inside its budget, or an early exit; never a trade no
rule supports. A reply counts only with a valid one-time code (RFC 6238 TOTP) from the secret the account holder
keeps under ESPERO_OPERATOR_TOTP; nothing here prints it. Every proposal, answer, override, silence and refusal
is an event in an append-only, hash-chained table, with its reason. Exits never wait: the rule's own exit is
executed without asking, and an operator may only exit earlier.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import math
import os
import secrets
import sqlite3
import struct
import time
from contextlib import contextmanager
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Iterable, List, Optional, Sequence, Union

from . import latency

SECRET_ENV = "ESPERO_OPERATOR_TOTP"
TOTP_STEP_S = 30
TOTP_DIGITS = 6
TOTP_WINDOWS = 1               # the current 30-second window's code, or the one before it
REPLY_MAX_AGE_S = 600          # a reply waits in the inbox until the sleeve's next step (every five minutes);
                               # its code is checked at the moment it was typed, and a reply older than this is refused
MAX_WRONG_CODES = 5            # this many wrong codes inside WRONG_CODE_WINDOW_S and no code is looked at until the
WRONG_CODE_WINDOW_S = 600      # window has passed: a million guesses would take years, where they took one batch
EXECUTION_ALLOWANCE_S = 300    # an approved order still has to be placed and filled inside the budget
MAX_WAIT_S = 24 * 3600         # no proposal waits longer than a day
LEDGER = "approvals.db"        # in the state folder: one ledger for every operator-paced sleeve
INBOX = "approvals.inbox"      # replies left by `espero approve` and the home screen, consumed by the sleeve runner
ANSWERS = ("approve", "reject", "modify", "exit")
OVERRIDES = ("reject", "modify", "exit")     # an answer other than "approve as proposed" needs a reason
GENESIS = "0" * 64

SCHEMA = """
CREATE TABLE IF NOT EXISTS proposals (
    id TEXT PRIMARY KEY, created INTEGER, expires INTEGER, rule TEXT, body TEXT, digest TEXT,
    status TEXT DEFAULT 'open'
);
CREATE TABLE IF NOT EXISTS approval_events (
    n INTEGER PRIMARY KEY AUTOINCREMENT, ts INTEGER, event TEXT, proposal TEXT, body TEXT, reason TEXT,
    prev TEXT, hash TEXT
);
CREATE TABLE IF NOT EXISTS used_codes (step INTEGER PRIMARY KEY, ts INTEGER);
CREATE TRIGGER IF NOT EXISTS approval_events_no_update BEFORE UPDATE ON approval_events
    BEGIN SELECT RAISE(ABORT, 'approval_events is append-only'); END;
CREATE TRIGGER IF NOT EXISTS approval_events_no_delete BEFORE DELETE ON approval_events
    BEGIN SELECT RAISE(ABORT, 'approval_events is append-only'); END;
CREATE TRIGGER IF NOT EXISTS approval_events_no_replace BEFORE INSERT ON approval_events
    WHEN NEW.n > 0 AND EXISTS (SELECT 1 FROM approval_events WHERE n >= NEW.n)
    BEGIN SELECT RAISE(ABORT, 'approval_events is append-only'); END;
"""


class NoSecret(RuntimeError):
    """No operator secret in the environment: no reply can be authenticated, so none counts."""


class NotOperatorPaced(ValueError):
    """The rule's budget is shorter than an operator's answer: it is auto-only or not traded, never proposed."""


# ------------------------------------------------------------------ one-time codes (RFC 4226, RFC 6238)
def hotp(key: bytes, counter: int, digits: int = TOTP_DIGITS, digest=hashlib.sha1) -> str:
    mac = hmac.new(key, struct.pack(">Q", counter), digest).digest()
    off = mac[-1] & 0x0F
    code = (struct.unpack(">I", mac[off:off + 4])[0] & 0x7FFFFFFF) % 10 ** digits
    return str(code).zfill(digits)


def totp(key: bytes, t: float, step: int = TOTP_STEP_S, digits: int = TOTP_DIGITS, digest=hashlib.sha1) -> str:
    """The code an authenticator app shows at time t for this key."""
    return hotp(key, int(t // step), digits, digest)


def secret(env: Optional[dict] = None) -> bytes:
    """The operator's secret, base32 as authenticator apps take it, from the environment only. Never printed."""
    env = os.environ if env is None else env
    raw = (env.get(SECRET_ENV) or "").strip().replace(" ", "").upper()
    if not raw:
        raise NoSecret(f"{SECRET_ENV} is not set: no reply can be authenticated (docs/OPERATOR.md, set-up)")
    try:
        key = base64.b32decode(raw + "=" * (-len(raw) % 8))
    except ValueError:
        raise NoSecret(f"{SECRET_ENV} is not base32") from None
    if len(key) < 10:
        raise NoSecret(f"{SECRET_ENV} is shorter than 80 bits")
    return key


def matching_step(key: bytes, code: str, t: float, used: Iterable[int] = (), windows: int = TOTP_WINDOWS
                  ) -> Optional[int]:
    """The 30-second step whose code this is, among the current one and the `windows` before it, unless that
    step's code was already used once."""
    code = (code or "").strip()
    if not (code.isdigit() and len(code) == TOTP_DIGITS):
        return None
    now = int(t // TOTP_STEP_S)
    taken = set(used)
    for s in range(now, now - windows - 1, -1):
        if s not in taken and hmac.compare_digest(hotp(key, s), code):
            return s
    return None


# ------------------------------------------------------------------ what is proposed and answered
@dataclass(frozen=True)
class Proposal:
    id: str
    mode: str                  # "machine": the rule's own entry; "operator": the operator's, checked here
    rule: str                  # the test number
    sleeve: str
    coin: str
    side: str                  # "buy" or "sell"
    kind: str                  # "entry", or "exit" (an operator's early exit)
    notional: float            # the risk gate's size (risk.check), never more
    decision_px: float
    cost_bps: float            # the registered round trip (espero.costs)
    stop_px: Optional[float]
    klass: str                 # the rule's class in espero.latency
    created: int
    expires: int
    event_ts: Optional[int] = None
    note: str = ""

    def body(self) -> str:
        return json.dumps(asdict(self), sort_keys=True, separators=(",", ":"))

    def digest(self) -> str:
        return hashlib.sha256(self.body().encode()).hexdigest()


@dataclass(frozen=True)
class Reply:
    proposal: str              # the proposal's id
    answer: str                # one of ANSWERS
    code: str
    reason: str = ""
    notional: Optional[float] = None     # "modify": the smaller size
    channel: str = "cli"
    at: int = 0


@dataclass(frozen=True)
class OperatorOrder:
    """Mode B: the operator proposes, the machine checks."""
    rule: str
    sleeve: str
    coin: str
    side: str
    kind: str                  # "entry" (an instance of the rule's live event) or "exit" (early)
    notional: float
    reason: str
    code: str
    channel: str = "cli"
    at: int = 0


@dataclass(frozen=True)
class LiveEvent:
    """What a rule's live evaluator emitted: the only thing an operator's entry may follow."""
    rule: str
    coin: str
    side: str
    ts: int


@dataclass(frozen=True)
class Outcome:
    proposal: str
    event: str                 # proposed, approved, rejected, modified, exit, operator, silence, refused
    notional: float            # what may be sent now: 0 unless approved, modified or an accepted operator order
    reason: str


def wait_s(test: str, rows: Optional[Sequence[latency.Row]] = None) -> Optional[int]:
    """How long a machine proposal for this rule waits for an answer: its budget less the feed's delay and the
    execution allowance, at most a day. None when the rule may not wait for a person."""
    r = latency.by_test(latency.ROWS if rows is None else rows).get(test)
    if r is None or r.klass != latency.OPERATOR_PACED:
        return None
    left = r.budget_s - r.feed_s - EXECUTION_ALLOWANCE_S
    return int(min(left, MAX_WAIT_S)) if left > 0 else None


def on_silence(kind: str) -> str:
    """An entry that waits unanswered is not taken. An exit never waits: it is the rule's own and is executed."""
    return "executed" if kind == "exit" else "not taken"


def propose(rule: str, sleeve: str, coin: str, side: str, notional: float, decision_px: float, cost_bps: float,
            stop_px: Optional[float], now: int, event_ts: Optional[int] = None, note: str = "",
            rows: Optional[Sequence[latency.Row]] = None) -> Proposal:
    """A machine proposal for a rule's entry. Refused for a rule that may not wait for a person, and for no size."""
    wait = wait_s(rule, rows)
    if wait is None:
        raise NotOperatorPaced(f"#{rule} is not operator-paced (research/LIVE_LATENCY.md): it is never proposed")
    if not notional > 0:
        raise ValueError("the risk gate gave no size: nothing to propose")
    if side not in ("buy", "sell"):
        raise ValueError("side must be buy or sell")
    return Proposal(secrets.token_hex(4), "machine", rule, sleeve, coin, side, "entry", float(notional),
                    float(decision_px), float(cost_bps), stop_px, latency.OPERATOR_PACED, int(now),
                    int(now) + wait, event_ts, note)


def supporting(order: OperatorOrder, live: Sequence[LiveEvent], now: int,
               rows: Optional[Sequence[latency.Row]] = None) -> Optional[LiveEvent]:
    """The rule's live event an operator's entry follows: same rule, coin and side, still inside the budget."""
    r = latency.by_test(latency.ROWS if rows is None else rows).get(order.rule)
    if r is None or r.klass not in (latency.OPERATOR_PACED, latency.LIVE_FROM_TAPE) or r.budget_s is None:
        return None
    ok = [e for e in live if e.rule == order.rule and e.coin == order.coin and e.side == order.side
          and 0 <= now - e.ts <= r.budget_s]
    return max(ok, key=lambda e: e.ts) if ok else None


def chain_hash(prev: str, ts: int, event: str, proposal: str, body: str, reason: str) -> str:
    text = json.dumps([prev, ts, event, proposal, body, reason], separators=(",", ":"))
    return hashlib.sha256(text.encode()).hexdigest()


# ------------------------------------------------------------------ the ledger
class Ledger:
    """Proposals and the append-only, hash-chained record of everything that happened to them."""

    def __init__(self, db: sqlite3.Connection, create: bool = True):
        self.db = db
        self.db.isolation_level = None            # transactions are explicit: BEGIN IMMEDIATE
        self.db.row_factory = sqlite3.Row
        if create:
            self.db.executescript(SCHEMA)

    @classmethod
    def open(cls, path: Union[str, Path]) -> "Ledger":
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        return cls(sqlite3.connect(str(path), timeout=5, isolation_level=None))

    @classmethod
    def read_only(cls, path: Union[str, Path]) -> "Ledger":
        """For the screens: reads the ledger, can write nothing to it."""
        return cls(sqlite3.connect(f"file:{Path(path)}?mode=ro", uri=True, timeout=5), create=False)

    @contextmanager
    def _tx(self):
        self.db.execute("BEGIN IMMEDIATE")
        try:
            yield
        except BaseException:
            self.db.execute("ROLLBACK")
            raise
        self.db.execute("COMMIT")

    def _append(self, ts: int, event: str, proposal: str, body: str, reason: str) -> None:
        last = self.db.execute("SELECT hash FROM approval_events ORDER BY n DESC LIMIT 1").fetchone()
        prev = last["hash"] if last else GENESIS
        self.db.execute("INSERT INTO approval_events (ts, event, proposal, body, reason, prev, hash) "
                        "VALUES (?,?,?,?,?,?,?)",
                        (ts, event, proposal, body, reason, prev, chain_hash(prev, ts, event, proposal, body, reason)))

    def _used(self) -> List[int]:
        return [r["step"] for r in self.db.execute("SELECT step FROM used_codes")]

    def _authenticate(self, key: Optional[bytes], code: str, now: int) -> Optional[int]:
        if key is None:
            return None
        step = matching_step(key, code, now, self._used())
        if step is not None:
            self.db.execute("INSERT INTO used_codes (step, ts) VALUES (?, ?)", (step, now))
        return step

    def _locked(self, now: int) -> bool:
        """Too many wrong codes lately: no code is looked at until the window has passed. Counted from the journal,
        so a batch of replies read in one step is limited like replies spread over time."""
        n = self.db.execute("SELECT COUNT(*) FROM approval_events WHERE event='refused' AND reason LIKE "
                            "'unauthenticated%' AND ts > ?", (now - WRONG_CODE_WINDOW_S,)).fetchone()[0]
        return n >= MAX_WRONG_CODES

    def outcome(self, pid: str) -> Optional[str]:
        """What the journal says became of a proposal: approved, modified, rejected or silence, or None while it is
        open. A sleeve trades on this, never on the proposals table's status column, which no hash covers."""
        row = self.db.execute("SELECT event FROM approval_events WHERE proposal=? AND event IN "
                              "('approved', 'modified', 'rejected', 'silence') ORDER BY n DESC LIMIT 1",
                              (pid,)).fetchone()
        return row["event"] if row else None

    def record(self, p: Proposal) -> Outcome:
        with self._tx():
            self.db.execute("INSERT INTO proposals (id, created, expires, rule, body, digest) VALUES (?,?,?,?,?,?)",
                            (p.id, p.created, p.expires, p.rule, p.body(), p.digest()))
            self._append(p.created, "proposed", p.id, p.body(), p.note or "the rule's entry")
        return Outcome(p.id, "proposed", 0.0, f"waits until {p.expires}")

    def proposal(self, pid: str) -> Optional[Proposal]:
        row = self.db.execute("SELECT body, digest FROM proposals WHERE id=?", (pid,)).fetchone()
        if row is None:
            return None
        p = Proposal(**json.loads(row["body"]))
        if p.digest() != row["digest"]:
            raise RuntimeError(f"proposal {pid}: its body no longer matches the digest recorded with it")
        return p

    def status(self, pid: str) -> Optional[str]:
        row = self.db.execute("SELECT status FROM proposals WHERE id=?", (pid,)).fetchone()
        return row["status"] if row else None

    def _refuse(self, now: int, pid: str, body: str, reason: str) -> Outcome:
        self._append(now, "refused", pid, body, reason)
        return Outcome(pid, "refused", 0.0, reason)

    def answer(self, reply: Reply, key: Optional[bytes], now: int) -> Outcome:
        """Apply an operator's reply. A refused reply leaves the proposal open: it can still be answered, or lapse."""
        body = json.dumps({k: v for k, v in asdict(reply).items() if k != "code"}, sort_keys=True)
        with self._tx():
            # the code is looked at first and spent whatever becomes of the reply: one typed against a mistyped id,
            # or for a proposal already answered, is not left good for whoever reads it next. It is checked against
            # the moment the reply was made, not the moment the sleeve reads it: a sleeve that steps every five
            # minutes would otherwise find every code expired (2026-11-09, the canary)
            locked = self._locked(now)
            too_old = bool(reply.at) and now - reply.at > REPLY_MAX_AGE_S
            step = None if locked else self._authenticate(key, reply.code, min(reply.at, now) if reply.at else now)
            p = self.proposal(reply.proposal)
            if p is None:
                return self._refuse(now, reply.proposal, body, "no such proposal")
            if self.status(p.id) != "open":
                return self._refuse(now, p.id, body, f"already {self.status(p.id)}")
            if now >= p.expires:
                return self._refuse(now, p.id, body, "too late: the proposal had lapsed")
            if reply.answer not in ANSWERS or reply.answer == "exit":
                return self._refuse(now, p.id, body, f"{reply.answer!r} is not an answer to an entry")
            if reply.answer in OVERRIDES and not reply.reason.strip():
                return self._refuse(now, p.id, body, "an override needs a reason")
            if reply.answer == "modify" and not (reply.notional is not None and 0 < reply.notional < p.notional):
                return self._refuse(now, p.id, body, "modify only sizes down, to more than zero")
            if too_old:
                return self._refuse(now, p.id, body, f"too old: the reply waited over {REPLY_MAX_AGE_S // 60} minutes "
                                                     "in the inbox; counts as silence")
            if locked:
                return self._refuse(now, p.id, body, f"locked: {MAX_WRONG_CODES} wrong codes in "
                                                     f"{WRONG_CODE_WINDOW_S // 60} minutes; counts as silence")
            if step is None:
                return self._refuse(now, p.id, body, "unauthenticated: no valid one-time code; counts as silence")
            event, notional = {"approve": ("approved", p.notional), "reject": ("rejected", 0.0),
                               "modify": ("modified", float(reply.notional or 0.0))}[reply.answer]
            self.db.execute("UPDATE proposals SET status=? WHERE id=?", (event, p.id))
            self._append(now, event, p.id, body, reply.reason or "approved as proposed")
        return Outcome(p.id, event, notional, reply.reason or "approved as proposed")

    def operator(self, order: OperatorOrder, live: Sequence[LiveEvent], key: Optional[bytes], now: int,
                 gate_notional: Optional[float], rows: Optional[Sequence[latency.Row]] = None) -> Outcome:
        """Mode B. An early exit is always accepted (it only reduces risk); an entry must follow a live event of
        its registered rule inside the budget, at no more than the risk gate's size."""
        body = json.dumps({k: v for k, v in asdict(order).items() if k != "code"}, sort_keys=True)
        pid = "op-" + hashlib.sha256(body.encode()).hexdigest()[:8]
        with self._tx():
            if order.kind not in ("entry", "exit"):
                return self._refuse(now, pid, body, f"{order.kind!r} is neither an entry nor an exit")
            if not order.reason.strip():
                return self._refuse(now, pid, body, "an operator's order is an override and needs a reason")
            if order.kind == "entry":
                event = supporting(order, live, now, rows)
                if event is None:
                    return self._refuse(now, pid, body, "no live event of a registered rule supports this entry")
                if not (gate_notional and gate_notional > 0):
                    return self._refuse(now, pid, body, "the risk gate gave no size")
                if order.notional > gate_notional:
                    return self._refuse(now, pid, body, f"above the risk gate's size ({gate_notional:.2f})")
            if self._locked(now):
                return self._refuse(now, pid, body, f"locked: {MAX_WRONG_CODES} wrong codes in "
                                                    f"{WRONG_CODE_WINDOW_S // 60} minutes")
            if self._authenticate(key, order.code, now) is None:
                return self._refuse(now, pid, body, "unauthenticated: no valid one-time code")
            kind = "exit" if order.kind == "exit" else "operator"
            self._append(now, kind, pid, body, order.reason)
        return Outcome(pid, kind, float(order.notional), order.reason)

    def expire(self, now: int) -> List[Outcome]:
        """Every open proposal past its time lapses into silence: an entry not taken."""
        out = []
        with self._tx():
            rows = self.db.execute("SELECT id, body FROM proposals WHERE status='open' AND expires<=? ORDER BY id",
                                   (now,)).fetchall()
            for r in rows:
                p = Proposal(**json.loads(r["body"]))
                why = f"no answer by {p.expires}: entry {on_silence(p.kind)}"
                self.db.execute("UPDATE proposals SET status='silence' WHERE id=?", (p.id,))
                self._append(now, "silence", p.id, r["body"], why)
                out.append(Outcome(p.id, "silence", 0.0, why))
        return out

    def pending(self, now: int) -> List[Proposal]:
        rows = self.db.execute("SELECT id FROM proposals WHERE status='open' AND expires>? ORDER BY created",
                               (now,)).fetchall()
        return [p for p in (self.proposal(r["id"]) for r in rows) if p is not None]

    def events(self) -> List[sqlite3.Row]:
        return self.db.execute("SELECT * FROM approval_events ORDER BY n").fetchall()

    def verify(self) -> List[str]:
        """Breaks in the hash chain: a row whose hash, or whose link to the row before, is not what it was."""
        out, prev = [], GENESIS
        for r in self.events():
            if r["prev"] != prev:
                out.append(f"event {r['n']}: does not follow the event before it")
            if r["hash"] != chain_hash(r["prev"], r["ts"], r["event"], r["proposal"], r["body"], r["reason"]):
                out.append(f"event {r['n']}: its content no longer matches its hash")
            prev = r["hash"]
        return out


# ------------------------------------------------------------------ the inbox: replies left by other processes
def inbox(state: Union[str, Path]) -> Path:
    return Path(state) / INBOX


def post(state: Union[str, Path], item: Union[Reply, OperatorOrder]) -> Path:
    """Leave a reply or an operator's order for the sleeve runner, atomically (written, then renamed)."""
    box = inbox(state)
    box.mkdir(parents=True, exist_ok=True)
    kind = "reply" if isinstance(item, Reply) else "order"
    name = f"{item.at:012d}-{kind}-{secrets.token_hex(3)}.json"
    tmp = box / (name + ".tmp")
    # the file carries a live one-time code until the runner takes it: readable by its owner only
    with os.fdopen(os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), "w", encoding="utf-8") as fh:
        fh.write(json.dumps({"type": kind, **asdict(item)}))                     # "kind" is an order's field
    os.replace(tmp, box / name)
    return box / name


def take(state: Union[str, Path]) -> List[Union[Reply, OperatorOrder]]:
    """Everything waiting in the inbox, oldest first, removed from it. The ledger is what records them."""
    box = inbox(state)
    out: List[Union[Reply, OperatorOrder]] = []
    if not box.is_dir():
        return out
    for f in sorted(box.glob("*.json")):
        d = None
        try:
            d = json.loads(f.read_text(encoding="utf-8"))
            if not isinstance(d, dict):
                raise ValueError("not an object")
            fields = dict(d)
            kind = fields.pop("type")
            out.append(_checked(Reply(**fields) if kind == "reply" else OperatorOrder(**fields)))
        except (ValueError, TypeError, KeyError, OSError):   # OSError: a file the runner may not read
            _set_aside(f, d)
            continue
        f.unlink()
    return out


def _checked(item: Union[Reply, OperatorOrder]) -> Union[Reply, OperatorOrder]:
    """A reply or order whose fields are what the ledger expects, or ValueError: one odd file (a text `at`, a
    number for a code) is set aside here, and cannot stop the step that also carries the holder's real answer."""
    texts = ("proposal", "answer", "code", "reason", "channel") if isinstance(item, Reply) else (
        "rule", "sleeve", "coin", "side", "kind", "reason", "code", "channel")
    for name in texts:
        if not isinstance(getattr(item, name), str):
            raise ValueError(f"{name} is not text")
    if not (item.code.isascii() and item.code.isdigit() and len(item.code) == TOTP_DIGITS):
        raise ValueError("the code is not six digits")
    if isinstance(item.at, bool) or not isinstance(item.at, int) or item.at < 0:
        raise ValueError("at is not a time")
    n = item.notional
    if isinstance(item, OperatorOrder) or n is not None:
        if isinstance(n, bool) or not isinstance(n, (int, float)) or not math.isfinite(n) or n <= 0:
            raise ValueError("notional is not a positive number")
    return item


def _set_aside(f: Path, d) -> None:
    """Keep a file the runner could not use, for the operator to look at, without the one-time code it carried."""
    try:
        if isinstance(d, dict) and "code" in d:
            f.write_text(json.dumps({**d, "code": "(removed)"}), encoding="utf-8")
        f.rename(f.with_suffix(".unreadable"))
    except OSError:
        pass


def describe(p: Proposal) -> str:
    """One proposal as the operator reads it, on the home screen or in the webhook."""
    stop = f", stop {p.stop_px:g}" if p.stop_px else ""
    by = time.strftime("%Y-%m-%d %H:%M UTC", time.gmtime(p.expires))
    return (f"{p.id}: #{p.rule} {p.side} {p.coin} ${p.notional:,.2f} at {p.decision_px:g} "
            f"(costs {p.cost_bps:.1f} bps{stop}), answer by {by}: espero approve {p.id} approve CODE")
