"""#83: funding carry on BTC and ETH, both legs on Hyperliquid, forward on paper.

The contract is research/PREREGISTRATION_SPOTCARRY.md.

The contract is frozen. This module is its book: the accounting and the six criteria as pure functions (arrays in,
numbers out), then a thin I/O layer that reads Hyperliquid's public endpoints, records each pass before using it, and
keeps the book in SQLite under state/. Nothing here signs anything or sends an order.

    espero spotcarry --once     one pass: read the four books and the new funding, record them, update the book
    espero spotcarry            print the book from the last pass

Before the window opens (Monday 2026-11-23 00:00 UTC) a pass only records. The book enters at the first good pass
at or after that time, and exits at the last pass that can fall inside the window (the first good pass whose next
scheduled pass would be past 2027-03-31 23:59 UTC).
"""
from __future__ import annotations

import datetime as dt
import json
import math
import os
import sqlite3
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Dict, List, Optional, Sequence, Set, Tuple

import numpy as np

from . import cascade, trials, volf
from .lock import JournalLock
from .trendstock import two_sided_p

UTC = dt.timezone.utc
COINS = ("BTC", "ETH")
TOKEN = {"BTC": "UBTC", "ETH": "UETH"}            # the spot token whose pair Hyperliquid lists against USDC
PAIR_HINT = {"BTC": "@142", "ETH": "@151"}         # where the pairs were on 2026-11-16; spotMeta resolves them
NOTIONAL = 100.0                                   # $ of spot bought per coin (the holder's figure)
CAPITAL = 150.0                                    # per coin: the spot in full and half again as the perp's margin
BOOK_CAPITAL = CAPITAL * len(COINS)
REBALANCE = 0.05                                   # perp notional vs spot value, as a share of the spot value
HEDGE_MAX = 0.01                                   # criterion 4: spot mid never more than this from perp mid
RATE_MIN = 0.03                                    # criterion 2: annualised on 365 days, simple, at or above
MIN_WEEKS = 12                                     # fewer complete weeks: INCONCLUSIVE
MIN_RECORD = 0.95                                  # criterion 6
BH_Q = 0.05
T_MIN = 3.0                                        # criterion 3's t, in the registered direction

# Rule 5. Hyperliquid's published fee schedule, Tier 0 (no volume), read at
# https://hyperliquid.gitbook.io/hyperliquid-docs/trading/fees on 2026-11-16: taker 0.070% spot, 0.045% perp, one
# tier across perps and spot. Those are the contract's 7 and 4.5 bps, not higher, so they are charged. A published
# figure above these would replace them; a lower one would be reported and not used.
FEE_SPOT = 0.0007
FEE_PERP = 0.00045

PASS_MINUTE = 33
QUIET_MINUTES = range(19, 28)                      # the collector's sweep and the shared rate limit
GAP_S = 2.0                                        # at least this between calls
INFO_URL = "https://api.hyperliquid.xyz/info"


def _utc(y: int, m: int, d: int, hh: int = 0, mm: int = 0) -> int:
    return int(dt.datetime(y, m, d, hh, mm, tzinfo=UTC).timestamp())


WINDOW_START = _utc(2026, 11, 23, 0, 0)            # a Monday
WINDOW_END = _utc(2027, 3, 31, 23, 59)
HOURS_IN_WINDOW = (WINDOW_END + 60 - WINDOW_START) // 3600
MONDAYS = [WINDOW_START + 7 * 86400 * k for k in range(0, (WINDOW_END - WINDOW_START) // (7 * 86400) + 1)]
MONDAYS = [m for m in MONDAYS if m <= WINDOW_END]


# ------------------------------------------------------------------ pure: the books
Level = Tuple[float, float]                        # (price, size in coins), best first


def parse_book(raw: dict) -> Tuple[List[Level], List[Level]]:
    """Hyperliquid's l2Book: levels[0] the bids (highest first), levels[1] the asks (lowest first)."""
    bids = [(float(x["px"]), float(x["sz"])) for x in raw["levels"][0]]
    asks = [(float(x["px"]), float(x["sz"])) for x in raw["levels"][1]]
    return bids, asks


def mid(bids: Sequence[Level], asks: Sequence[Level]) -> float:
    return (bids[0][0] + asks[0][0]) / 2.0


def fill_qty(levels: Sequence[Level], qty: float) -> float:
    """The value of buying or selling `qty` coins, walking the levels best first. A thin book raises: a pass
    never trades on a fill it cannot see."""
    if qty <= 0:
        return 0.0
    left, value = qty, 0.0
    for px, sz in levels:
        take = min(sz, left)
        value += take * px
        left -= take
        if left <= 1e-12:
            return value
    raise ValueError(f"book too thin: {left:.6g} coins unfilled")


def fill_usd(asks: Sequence[Level], usd: float) -> Tuple[float, float]:
    """Coins bought for `usd` dollars, walking the asks. Returns (coins, dollars spent) = (qty, usd)."""
    left, qty = usd, 0.0
    for px, sz in asks:
        take = min(sz, left / px)
        qty += take
        left -= take * px
        if left <= 1e-9:
            return qty, usd
    raise ValueError(f"book too thin: ${left:.4f} unfilled")


# ------------------------------------------------------------------ pure: one coin's leg
@dataclass
class Leg:
    """One coin's position. `cash` moves only with principal (spot paid, perp proceeds, the walks at exit and
    rebalance). Funding and fees are kept apart, so equity is cash + spot - perp + funding - fees (rule 7)."""
    coin: str
    cash: float = CAPITAL
    spot: float = 0.0                              # coins held
    perp: float = 0.0                              # coins short
    funding: float = 0.0
    fees: float = 0.0
    entry_ts: Optional[int] = None
    exit_ts: Optional[int] = None

    @property
    def entered(self) -> bool:
        return self.entry_ts is not None

    @property
    def exited(self) -> bool:
        return self.exit_ts is not None

    def held_at(self, ts: int) -> bool:
        """An hour settled at `ts` is paid to this leg only after entry, and no later than the exit."""
        return self.entered and ts > self.entry_ts and (self.exit_ts is None or ts <= self.exit_ts)

    def credit(self, hour_ts: int, rate: float, perp_mid: float) -> float:
        """Funding for one settled hour: rate x the perp's notional at the mark. Positive rate pays the short."""
        if not self.held_at(hour_ts):
            return 0.0
        amount = rate * self.perp * perp_mid
        self.funding += amount
        return amount

    def enter(self, ts: int, spot_asks: Sequence[Level], perp_bids: Sequence[Level]) -> None:
        if self.entered:
            raise ValueError(f"{self.coin} already entered")
        qty, spent = fill_usd(spot_asks, NOTIONAL)
        proceeds = fill_qty(perp_bids, qty)
        self.cash += proceeds - spent
        self.fees += spent * FEE_SPOT + proceeds * FEE_PERP
        self.spot = self.perp = qty
        self.entry_ts = ts

    def rebalance(self, spot_mid: float, perp_mid: float, perp_bids: Sequence[Level],
                  perp_asks: Sequence[Level]) -> float:
        """If the perp's notional and the spot's value differ by more than REBALANCE of the spot's value, trade the perp
        alone back to the spot's quantity at the book. Returns the coins traded (signed: + added to the short)."""
        spot_value = self.spot * spot_mid
        if spot_value <= 0 or abs(self.perp * perp_mid - spot_value) <= REBALANCE * spot_value:
            return 0.0
        delta = self.spot - self.perp
        if delta > 0:
            proceeds = fill_qty(perp_bids, delta)
            self.cash += proceeds
            self.fees += proceeds * FEE_PERP
        elif delta < 0:
            cost = fill_qty(perp_asks, -delta)
            self.cash -= cost
            self.fees += cost * FEE_PERP
        self.perp = self.spot
        return delta

    def exit(self, ts: int, spot_bids: Sequence[Level], perp_asks: Sequence[Level]) -> None:
        proceeds = fill_qty(spot_bids, self.spot)
        cost = fill_qty(perp_asks, self.perp)
        self.cash += proceeds - cost
        self.fees += proceeds * FEE_SPOT + cost * FEE_PERP
        self.spot = self.perp = 0.0
        self.exit_ts = ts

    def equity(self, spot_mid: float, perp_mid: float) -> float:
        return self.cash + self.spot * spot_mid - self.perp * perp_mid + self.funding - self.fees


# ------------------------------------------------------------------ pure: one pass
# coin -> (spot bids, spot asks, perp bids, perp asks)
Books = Dict[str, Tuple[List[Level], List[Level], List[Level], List[Level]]]


def apply_pass(legs: Dict[str, Leg], ts: int, books: Books, funding: Dict[str, List[Tuple[int, float]]],
               seen: Set[Tuple[str, int]]) -> Tuple[List[str], List[Tuple[str, int, float, bool]]]:
    """One good pass, in the contract's order: fund the hours settled since the last pass (each once: `seen` holds
    the hours already in the book), then exit, enter or rebalance, and return what happened. `seen` is updated in
    place. Returns (events, credits) where a credit is (coin, hour, amount, held)."""
    events: List[str] = []
    credits: List[Tuple[str, int, float, bool]] = []
    for coin, leg in legs.items():
        perp_mid = mid(books[coin][2], books[coin][3])
        for hour, rate in sorted(funding.get(coin, [])):
            if hour > ts or (coin, hour) in seen:
                continue
            seen.add((coin, hour))
            amount = leg.credit(hour, rate, perp_mid)
            credits.append((coin, hour, amount, leg.held_at(hour)))
    final = ts + 3600 > WINDOW_END                  # the next scheduled pass would fall outside the window
    for coin, leg in legs.items():
        sb, sa, pb, pa = books[coin]
        spot_mid, perp_mid = mid(sb, sa), mid(pb, pa)
        if leg.entered and not leg.exited and final:
            leg.exit(ts, sb, pa)
            events.append(f"{coin}: exit at {_iso(ts)}: spot sold {fill_note(sb, leg.spot)}, perp bought back")
        elif not leg.entered and WINDOW_START <= ts <= WINDOW_END:
            leg.enter(ts, sa, pb)
            events.append(f"{coin}: entry at {_iso(ts)}: {leg.spot:.6g} coins, spot at ask, perp at bid")
        elif leg.entered and not leg.exited:
            moved = leg.rebalance(spot_mid, perp_mid, pb, pa)
            if moved:
                events.append(f"{coin}: rebalance {moved:+.6g} coins on the perp at {_iso(ts)}")
    return events, credits


def fill_note(levels: Sequence[Level], qty: float) -> str:
    return f"{qty:.6g} coins"


def marks(legs: Dict[str, Leg], books: Books) -> Dict[str, Tuple[float, float, float, bool]]:
    """Per coin at one pass: (spot mid, perp mid, equity, held). Held means entered and not yet exited."""
    out = {}
    for coin, leg in legs.items():
        sb, sa, pb, pa = books[coin]
        s, p = mid(sb, sa), mid(pb, pa)
        out[coin] = (s, p, leg.equity(s, p), leg.entered and not leg.exited)
    return out


def _iso(ts: int) -> str:
    return dt.datetime.fromtimestamp(ts, UTC).strftime("%Y-%m-%d %H:%M UTC")


# ------------------------------------------------------------------ pure: the verdict
def book_at(points: Sequence[Tuple[int, float]], t: int) -> Optional[float]:
    """The last recorded value at or before `t`; points are sorted by time."""
    v = None
    for ts, e in points:
        if ts <= t:
            v = e
        else:
            break
    return v


def week_returns(points: Sequence[Tuple[int, float]], now_ts: int, end_ts: int = WINDOW_END,
                 base: float = BOOK_CAPITAL) -> Tuple[List[float], int]:
    """Weekly net returns of the book on its capital: Monday 00:00 UTC to Monday, the last week to `end_ts` (the exit).
    Returns (returns, complete weeks observed by `now_ts`). A week with no mark before its start starts at `base`."""
    bounds = [m for m in MONDAYS if m <= end_ts]
    values = [book_at(points, b) for b in bounds] + [book_at(points, end_ts)]
    values = [base if v is None else v for v in values]
    rets = [(values[k + 1] - values[k]) / base for k in range(len(values) - 1)]
    complete = sum(1 for b in bounds[1:] if b <= now_ts)
    return rets, complete


def p_of_t(x: Sequence[float]) -> Tuple[float, float]:
    """Newey-West t of the mean (espero.volf's lag count) and its two-sided p from Student's t at n - 1 df."""
    arr = np.asarray(x, dtype=float)
    n = len(arr)
    if n < 2:
        return float("nan"), float("nan")
    t = cascade.nw_t(arr, volf.nw_lags(n))
    return t, two_sided_p(t, n) if math.isfinite(t) else float("nan")


def judge(*, weekly: Sequence[float], complete: int, book_return: float, days: float,
          coin_returns: Dict[str, float], hedge_gap: float, ok_slots: int, slots: int,
          family_p: Sequence[float], closed: bool) -> dict:
    """The six criteria and the verdict. `closed` is false until the window has ended; until then the verdict is
    'running' and nothing is judged. Criterion 3 needs t >= 3 AND Benjamini-Hochberg q < 0.05 over `family_p` with
    this test's own p included."""
    t, p = p_of_t(weekly)
    fam = [1.0 if (x is None or not math.isfinite(x)) else float(x) for x in family_p]
    q = float(trials.bh(np.append(np.asarray(fam, dtype=float), 1.0 if not math.isfinite(p) else p))[-1]) \
        if math.isfinite(p) else float("nan")
    annual = book_return * 365.0 / days if days > 0 else float("nan")
    crit = {
        "1_pays": book_return > 0,
        "2_rate": math.isfinite(annual) and annual >= RATE_MIN,
        "3_stat": math.isfinite(t) and t >= T_MIN and math.isfinite(q) and q < BH_Q,
        "4_hedge": hedge_gap <= HEDGE_MAX,
        "5_both": bool(coin_returns) and all(r > 0 for r in coin_returns.values()),
        "6_record": slots > 0 and ok_slots / slots >= MIN_RECORD,
    }
    if not closed:
        verdict = "running"
    elif complete < MIN_WEEKS:
        verdict = "INCONCLUSIVE"
    else:
        verdict = "PASS" if all(crit.values()) else "FAIL"
    return {"verdict": verdict, "criteria": crit, "t": t, "p": p, "bh_q": q, "annual": annual,
            "book_return": book_return, "weeks": len(weekly), "complete_weeks": complete,
            "coin_returns": coin_returns, "hedge_gap": hedge_gap, "ok_slots": ok_slots, "slots": slots}


# ------------------------------------------------------------------ I/O: the store
SCHEMA = """
CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT);
CREATE TABLE IF NOT EXISTS legs (coin TEXT PRIMARY KEY, cash REAL, spot REAL, perp REAL, funding REAL, fees REAL,
    entry_ts INTEGER, exit_ts INTEGER);
CREATE TABLE IF NOT EXISTS passes (ts INTEGER PRIMARY KEY, ok INTEGER NOT NULL, errors TEXT);
CREATE TABLE IF NOT EXISTS marks (ts INTEGER NOT NULL, coin TEXT NOT NULL, spot_mid REAL, perp_mid REAL,
    equity REAL, held INTEGER, PRIMARY KEY (ts, coin));
CREATE TABLE IF NOT EXISTS credits (coin TEXT NOT NULL, hour INTEGER NOT NULL, amount REAL, held INTEGER,
    PRIMARY KEY (coin, hour));
CREATE TABLE IF NOT EXISTS events (ts INTEGER NOT NULL, text TEXT NOT NULL);
"""


class Store:
    def __init__(self, path: Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(str(self.path))
        self.db.row_factory = sqlite3.Row
        self.db.executescript(SCHEMA)

    def close(self) -> None:
        self.db.close()

    def meta(self, key: str, default=None):
        r = self.db.execute("SELECT value FROM meta WHERE key=?", (key,)).fetchone()
        return default if r is None else json.loads(r["value"])

    def legs(self) -> Dict[str, Leg]:
        out = {c: Leg(c) for c in COINS}
        for r in self.db.execute("SELECT * FROM legs"):
            out[r["coin"]] = Leg(r["coin"], r["cash"], r["spot"], r["perp"], r["funding"], r["fees"],
                                 r["entry_ts"], r["exit_ts"])
        return out

    def seen(self) -> Set[Tuple[str, int]]:
        return {(r["coin"], r["hour"]) for r in self.db.execute("SELECT coin, hour FROM credits")}

    def points(self) -> List[Tuple[int, float]]:
        rows = self.db.execute("SELECT ts, SUM(equity) AS e FROM marks GROUP BY ts ORDER BY ts").fetchall()
        return [(int(r["ts"]), float(r["e"])) for r in rows]

    def commit(self, *, ts: int, legs: Dict[str, Leg], books: Optional[Books], held: Dict[str, bool],
               credits: Sequence, events: Sequence[str], ok: bool, errors: dict, cursor: Dict[str, int],
               pairs: Optional[dict]) -> None:
        with self.db:
            self.db.execute("INSERT OR REPLACE INTO passes VALUES (?,?,?)", (ts, int(ok), json.dumps(errors)))
            if pairs is not None:
                self.db.execute("INSERT OR REPLACE INTO meta VALUES ('pairs', ?)", (json.dumps(pairs),))
            self.db.execute("INSERT OR REPLACE INTO meta VALUES ('cursor', ?)", (json.dumps(cursor),))
            if not ok:
                return
            for coin, leg in legs.items():
                self.db.execute("INSERT OR REPLACE INTO legs VALUES (?,?,?,?,?,?,?,?)",
                                (coin, leg.cash, leg.spot, leg.perp, leg.funding, leg.fees, leg.entry_ts, leg.exit_ts))
            for coin, (s, p, e, h) in marks(legs, books).items():
                self.db.execute("INSERT OR REPLACE INTO marks VALUES (?,?,?,?,?,?)", (ts, coin, s, p, e, int(h)))
            for coin, hour, amount, h in credits:
                self.db.execute("INSERT OR IGNORE INTO credits VALUES (?,?,?,?)", (coin, hour, amount, int(h)))
            for text in events:
                self.db.execute("INSERT INTO events VALUES (?,?)", (ts, text))


# ------------------------------------------------------------------ I/O: reading the endpoints
class Pacer:
    """Every call at least GAP_S after the last, and never in the quiet minutes (the collector's sweep and the rate
    limit it shares with the recorders on this Mac). Checked before every call, not once a pass."""

    def __init__(self, post: Callable[[dict], object], sleep=time.sleep, clock=time.time):
        self.post, self.sleep, self.clock = post, sleep, clock
        self.last: Optional[float] = None

    def __call__(self, body: dict):
        while time.gmtime(self.clock()).tm_min in QUIET_MINUTES:
            self.sleep(20)
        if self.last is not None:
            wait = self.last + GAP_S - self.clock()
            if wait > 0:
                self.sleep(wait)
        self.last = self.clock()
        return self.post(body)


def default_post(body: dict):
    from . import hyperliquid as hl
    return hl.post(body, url=INFO_URL)


def resolve_pairs(spot_meta: dict) -> Dict[str, str]:
    """The name of each spot pair (UBTC/USDC, UETH/USDC) as Hyperliquid lists it now. The book follows the token."""
    toks = {t["index"]: t["name"] for t in spot_meta["tokens"]}
    out = {}
    for coin in COINS:
        for u in spot_meta["universe"]:
            names = [toks.get(i) for i in u["tokens"]]
            if names == [TOKEN[coin], "USDC"]:
                out[coin] = u["name"]
                break
        else:
            raise ValueError(f"no {TOKEN[coin]}/USDC pair in spotMeta")
    return out


def _raw_line(path: Path, record: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a", encoding="utf-8") as fh:
        fh.write(json.dumps(record, sort_keys=True) + "\n")
        fh.flush()
        os.fsync(fh.fileno())


def run_pass(state: Path, post: Optional[Callable[[dict], object]] = None, sleep=time.sleep,
             clock=time.time) -> dict:
    """One pass: read, record raw, then update the book. A pass that cannot read everything is a gap: it is recorded,
    and the book does not trade, credit or mark on it."""
    state = Path(state)
    now = int(clock())
    db_path = state / "spotcarry.db"
    with JournalLock(db_path):
        store = Store(db_path)
        try:
            pacer = Pacer(post or default_post, sleep, clock)
            errors: Dict[str, str] = {}
            raw: Dict[str, object] = {}

            def read(key, body):
                try:
                    raw[key] = pacer(body)
                except Exception as e:  # noqa: BLE001 - a read that fails is a gap, recorded as such
                    errors[key] = f"{type(e).__name__}: {e}"
                    raw[key] = None

            pairs = store.meta("pairs")
            if pairs is None:
                read("spotMeta", {"type": "spotMeta"})
                if raw.get("spotMeta") is not None:
                    try:
                        pairs = resolve_pairs(raw["spotMeta"])
                    except ValueError as e:
                        errors["pairs"] = str(e)
            cursor = store.meta("cursor", {c: WINDOW_START * 1000 for c in COINS})
            for coin in COINS:
                read(f"l2:{coin}", {"type": "l2Book", "coin": coin})
            for coin in COINS:
                read(f"l2:{TOKEN[coin]}", {"type": "l2Book", "coin": (pairs or PAIR_HINT)[coin]})
            for coin in COINS:
                read(f"funding:{coin}", {"type": "fundingHistory", "coin": coin, "startTime": int(cursor[coin])})

            _raw_line(state / "spotcarry" / f"{dt.datetime.fromtimestamp(now, UTC):%Y-%m-%d}.jsonl",
                      {"at": now, "pairs": pairs, "errors": errors, "raw": raw})

            legs = store.legs()
            ok = not errors and pairs is not None
            if not ok:
                store.commit(ts=now, legs=legs, books=None, held={}, credits=[], events=[], ok=False,
                             errors=errors, cursor=cursor, pairs=pairs)
                return {"at": now, "ok": False, "errors": errors, "events": [], "legs": legs}

            books: Books = {}
            for coin in COINS:
                sp = parse_book(raw[f"l2:{TOKEN[coin]}"])
                pp = parse_book(raw[f"l2:{coin}"])
                books[coin] = (sp[0], sp[1], pp[0], pp[1])
            funding: Dict[str, List[Tuple[int, float]]] = {}
            new_cursor = dict(cursor)
            for coin in COINS:
                rows = raw[f"funding:{coin}"] or []
                funding[coin] = [((int(r["time"]) // 1000) // 3600 * 3600, float(r["fundingRate"])) for r in rows]
                if rows:
                    new_cursor[coin] = max(int(r["time"]) for r in rows) + 1
            seen = store.seen()
            events, credits = apply_pass(legs, now, books, funding, seen)
            store.commit(ts=now, legs=legs, books=books, held={}, credits=credits, events=events, ok=True,
                         errors={}, cursor=new_cursor, pairs=pairs)
            return {"at": now, "ok": True, "errors": {}, "events": events, "legs": legs}
        finally:
            store.close()


# ------------------------------------------------------------------ I/O: the report
def trial_family(path: Path) -> List[float]:
    """Every judged test's p from research/trials.csv (the statuses FDR_STANDARD judges), NaN counted as 1."""
    import pandas as pd
    d = pd.read_csv(path, dtype={"test": str})
    judged = d[d["status"].isin(("fail", "pass", "provisional", "exploratory"))]
    return pd.to_numeric(judged["p_from_t"], errors="coerce").fillna(1.0).astype(float).tolist()


def report(state: Path, now: Optional[int] = None, root: Optional[Path] = None) -> dict:
    """The whole book: legs, marks, passes, the criteria. Read-only."""
    now = int(time.time()) if now is None else now
    state = Path(state)
    db_path = state / "spotcarry.db"
    if not db_path.exists():
        return {"at": now, "started": False}
    store = Store(db_path)
    try:
        legs = store.legs()
        pairs = store.meta("pairs")
        passes = store.db.execute("SELECT ts, ok, errors FROM passes ORDER BY ts").fetchall()
        points = store.points()
        good = [p for p in passes if p["ok"]]
        marks_rows = store.db.execute("SELECT * FROM marks ORDER BY ts, coin").fetchall()
        events = store.db.execute("SELECT ts, text FROM events ORDER BY ts DESC, rowid DESC LIMIT 30").fetchall()
    finally:
        store.close()
    closed = now > WINDOW_END + 60
    end_ts = WINDOW_END
    rets, complete = week_returns(points, now, end_ts)
    ends = [e for ts, e in points if ts <= end_ts]
    book_end = ends[-1] if ends else BOOK_CAPITAL
    entered = [l for l in legs.values() if l.entered]
    entry = min((l.entry_ts for l in entered), default=None)
    exit_ = max((l.exit_ts for l in entered if l.exit_ts), default=None)
    span_end = exit_ if exit_ is not None else (now if entry else WINDOW_START)
    days = (span_end - entry) / 86400.0 if entry else 0.0
    coin_returns = {}
    for coin in COINS:
        cvals = [r["equity"] for r in marks_rows if r["coin"] == coin and r["ts"] <= end_ts]
        coin_returns[coin] = ((cvals[-1] if cvals else CAPITAL) - CAPITAL) / CAPITAL
    gap = 0.0
    for r in marks_rows:
        if r["held"] and r["perp_mid"]:
            gap = max(gap, abs(r["spot_mid"] - r["perp_mid"]) / r["perp_mid"])
    slots = {int(r["ts"]) // 3600 for r in good if WINDOW_START <= r["ts"] <= WINDOW_END}
    family = trial_family(root / "research" / "trials.csv") if root else []
    if not family:
        family = [1.0]
    result = judge(weekly=rets, complete=complete, book_return=(book_end - BOOK_CAPITAL) / BOOK_CAPITAL,
                   days=days, coin_returns=coin_returns, hedge_gap=gap, ok_slots=len(slots),
                   slots=HOURS_IN_WINDOW, family_p=family, closed=closed) if entry else \
        {"verdict": "running" if not closed else "INCONCLUSIVE", "criteria": {}, "complete_weeks": complete,
         "weeks": len(rets), "ok_slots": len(slots), "slots": HOURS_IN_WINDOW}
    return {"at": now, "started": True, "pairs": pairs, "window": [WINDOW_START, WINDOW_END],
            "fees": {"spot": FEE_SPOT, "perp": FEE_PERP},
            "passes": {"total": len(passes), "ok": len(good)},
            "legs": {c: {"cash": l.cash, "spot": l.spot, "perp": l.perp, "funding": l.funding, "fees": l.fees,
                         "entry_ts": l.entry_ts, "exit_ts": l.exit_ts} for c, l in legs.items()},
            "book_equity": book_end, "weekly": rets, "result": result,
            "worst_week": min(rets) if rets else None,
            "events": [{"ts": int(r["ts"]), "text": r["text"]} for r in events]}


def write_state(state: Path, rep: dict) -> Path:
    path = Path(state) / "spotcarry.json"
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(rep, indent=1, default=float))
    tmp.replace(path)
    return path


def render(rep: dict) -> str:
    if not rep.get("started"):
        return ("no spot carry book yet: espero spotcarry --once "
                "(records before the window; enters 2026-11-23 00:00 UTC)")
    r = rep["result"]
    now = dt.datetime.fromtimestamp(rep["at"], UTC).strftime("%Y-%m-%d %H:%M UTC")
    lines = [f"#83 spot carry, paper: as of {now}. Verdict: {r['verdict']} "
             "(judged once, when the window ends 2027-03-31 23:59 UTC; until then nothing is judged)."]
    lines.append(f"passes {rep['passes']['ok']} good of {rep['passes']['total']} recorded; "
                 f"pairs {rep['pairs'] or 'not yet resolved'}")
    for c, l in rep["legs"].items():
        state_txt = ("waiting for the window" if l["entry_ts"] is None else
                     "exited" if l["exit_ts"] else "held")
        lines.append(f"  {c}: {state_txt}; spot {l['spot']:.6g}, perp short {l['perp']:.6g}, "
                     f"funding {l['funding']:+.4f}, fees {l['fees']:.4f}")
    lines.append(f"  book equity ${rep['book_equity']:.2f} on ${BOOK_CAPITAL:.0f}")
    if r.get("criteria"):
        lines.append("  criteria: " + ", ".join(f"{k} {'ok' if v else 'miss'}" for k, v in r["criteria"].items()))
        lines.append(f"  complete weeks {r['complete_weeks']} (needs {MIN_WEEKS}); "
                     f"hedge gap {r['hedge_gap']:.3%}; record {r['ok_slots']}/{r['slots']} hours")
    for e in rep.get("events", [])[:8]:
        lines.append(f"  {dt.datetime.fromtimestamp(e['ts'], UTC):%m-%d %H:%M} {e['text']}")
    return "\n".join(lines)


def main(argv=None) -> int:
    import argparse
    ap = argparse.ArgumentParser(prog="espero spotcarry")
    ap.add_argument("--once", action="store_true", help="one pass: read, record, update the book")
    ap.add_argument("--status", action="store_true", help="print the book (the default)")
    ap.add_argument("--state-dir", default=str(Path(__file__).resolve().parents[1] / "state"))
    a = ap.parse_args(argv)
    state = Path(a.state_dir)
    root = Path(__file__).resolve().parents[1]
    if a.once:
        try:
            res = run_pass(state)
        except Exception as e:  # noqa: BLE001 - a second pass is refused by the lock: say so, do not crash the agent
            print(f"pass not run: {type(e).__name__}: {e}")
            return 1
        print("pass ok" if res["ok"] else f"pass recorded as a gap: {res['errors']}")
        for ev in res["events"]:
            print("  " + ev)
    rep = report(state, root=root)
    if rep.get("started"):
        write_state(state, rep)
    print(render(rep))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
