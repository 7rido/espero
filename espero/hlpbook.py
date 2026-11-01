"""#58: HLP's absorbed inventory, as a rule, a ledger and a paper book (research/FORWARD_HLP.md).

The rule reads `data/hlcollect/`: HLP's positions every 15 minutes and Hyperliquid's 1-minute candles.
The book applies it to each new slot and records simulated fills in its own journal. It holds no key
and signs nothing. Before the window opens it opens no recorded file, only lists their names.

The verdict comes from `ledger`, rebuilt from the recordings once the window has closed, and never
from the book's running numbers.
"""
from __future__ import annotations

import datetime as dt
import math
import sqlite3
import time
from collections import Counter, deque
from pathlib import Path
from typing import Callable, Dict, List, NamedTuple, Optional

import numpy as np
import pandas as pd

from . import hyperliquid as hl
from .audit import trade_weighted_nw
from .hlcollect import DATA


def _utc(*ymd) -> int:
    return int(dt.datetime(*ymd, tzinfo=dt.timezone.utc).timestamp())


COINS = ("BTC", "ETH", "SOL", "XRP", "DOGE", "LINK", "ADA", "AVAX", "BNB", "TRX", "LTC", "XLM", "HBAR", "kSHIB")
LARGEST = ("BTC", "ETH", "SOL", "XRP", "DOGE", "LINK")
WINDOW_START = _utc(2026, 11, 5)
WINDOW_END = _utc(2027, 4, 1)       # exclusive: signals through 2027-03-31 23:59 UTC
SECOND_HALF = _utc(2027, 1, 17)
SLOT_S = 900
HISTORY_SLOTS = 672
MIN_HISTORY = 336
JUMP_PCT = 99.0
RET_PCT = 10.0
ENTRY_DELAY_S = 60
HOLD_S = 4 * 3600
FILL_TOLERANCE_S = 300
COST_BPS = 18.0
MIN_TRADES = 100
MIN_COIN_TRADES = 10
PASS_T = 3.0
BOOK_USD = 1000.0
PENDING, MISSING = "pending", "missing"

Fetch = Callable[[dict], object]


class Slot(NamedTuple):
    slot: int                   # the 15-minute slot, from the file's path
    ts: int                     # when it was read: the rule's t
    addresses: frozenset
    net: Dict[str, float]


class Signal(NamedTuple):
    coin: str
    ts: int
    jump: float
    ret: float


# ----------------------------------------------------------------- the recordings
def slot_paths(data: Path = DATA) -> List[Path]:
    return sorted(Path(data).glob("hlp/*/*.csv.gz"))


def slot_of(path: Path) -> int:
    day, hhmm = path.parent.name, path.name.split(".")[0]
    return int(pd.Timestamp(f"{day} {hhmm[:2]}:{hhmm[2:]}", tz="UTC").timestamp())


def read_slot(path: Path) -> Slot:
    """One HLP file. A coin with no row has net size 0."""
    df = pd.read_csv(path, usecols=["ts", "address", "coin", "szi"])
    slot = slot_of(path)
    if df.empty:
        return Slot(slot, slot, frozenset(), {})
    ours = df[df["coin"].isin(COINS)]
    return Slot(slot, int(df["ts"].iloc[0]), frozenset(df["address"]), ours.groupby("coin")["szi"].sum().to_dict())


class Prices:
    """1-minute candles per coin, the first copy of a candle kept: files before the API."""

    def __init__(self):
        self.frames: Dict[str, List[pd.DataFrame]] = {}
        self.columns: Dict[str, tuple] = {}

    def add(self, coin: str, frame: pd.DataFrame) -> None:
        if not frame.empty:
            self.frames.setdefault(coin, []).append(frame[["ts", "open", "close"]])
            self.columns.pop(coin, None)

    def _arrays(self, coin: str) -> tuple:
        if coin not in self.columns:
            if coin not in self.frames:
                self.columns[coin] = (np.array([], dtype=np.int64), np.array([]), np.array([]))
            else:
                f = pd.concat(self.frames[coin]).drop_duplicates("ts", keep="first").sort_values("ts")
                self.columns[coin] = (f["ts"].to_numpy(dtype=np.int64), f["open"].to_numpy(dtype=float),
                                      f["close"].to_numpy(dtype=float))
        return self.columns[coin]

    def last_end(self, coin: str) -> int:
        """When the coin's newest candle ended, or 0 with none."""
        starts = self._arrays(coin)[0]
        return int(starts[-1]) + 60 if starts.size else 0

    def close_at(self, coin: str, ts: int) -> float:
        """C(s): the close of the last candle that ended at or before ts."""
        starts, _, closes = self._arrays(coin)
        k = int(np.searchsorted(starts, ts - 60, side="right")) - 1
        return float(closes[k]) if k >= 0 else math.nan

    def first_open(self, coin: str, earliest: int, final: bool = False):
        """(start, open) of the first candle starting at or after `earliest`. MISSING if that candle
        is past the tolerance, PENDING if it may still arrive (always MISSING when `final`)."""
        starts, opens, _ = self._arrays(coin)
        k = int(np.searchsorted(starts, earliest, side="left"))
        if k == starts.size:
            return MISSING if final else PENDING
        return (int(starts[k]), float(opens[k])) if starts[k] - earliest <= FILL_TOLERANCE_S else MISSING


def load_candle_file(path: Path, prices: Prices) -> None:
    df = pd.read_csv(path, usecols=["ts", "coin", "open", "close"])
    for coin, part in df[df["coin"].isin(COINS)].groupby("coin"):
        prices.add(coin, part)


def fetch_recent(prices: Prices, now: int, fetch: Optional[Fetch] = None, pace: float = 0.5,
                 sleep=time.sleep) -> int:
    """Candles the daily files don't hold yet, from Hyperliquid's mainnet API. Returns how many rows."""
    rows = 0
    for coin in COINS:
        since = max(prices.last_end(coin), WINDOW_START - 8 * 86400)
        got = hl.candles(coin, "1m", since * 1000, now * 1000, fetch=fetch)
        if not got.empty:
            got = got.assign(ts=[int(pd.Timestamp(x).timestamp()) for x in got["time"]])
            closed = got[got["ts"] + 60 <= now]
            prices.add(coin, closed)
            rows += len(closed)
        if pace:
            sleep(pace)
    return rows


# ----------------------------------------------------------------- the rule
def walk(slots: List[Slot], prices: Prices, final: bool = False) -> Dict:
    """Every signal in the window, from adjacent slots with the same accounts. Unless `final`, a coin
    stops at the first slot its candles don't reach yet, so a late candle can't change a price."""
    signals: List[Signal] = []
    counts: Counter = Counter()
    history: Dict[str, deque] = {c: deque() for c in COINS}
    waiting: set = set()
    for prev, cur in zip(slots, slots[1:]):
        if cur.slot - prev.slot != SLOT_S:
            counts["gaps"] += 1
            continue
        if prev.addresses != cur.addresses:
            counts["invalid_pairs"] += 1
            continue
        counts["pairs"] += 1
        for coin in COINS:
            if coin in waiting:
                continue
            if not final and prices.last_end(coin) < cur.ts:
                waiting.add(coin)
                continue
            before, now = prices.close_at(coin, prev.ts), prices.close_at(coin, cur.ts)
            if not (before > 0 and now > 0):
                counts["no_price"] += 1
                continue
            ret = now / before - 1
            jump = (cur.net.get(coin, 0.0) - prev.net.get(coin, 0.0)) * now
            past = history[coin]
            while past and past[0][0] < cur.slot - HISTORY_SLOTS * SLOT_S:
                past.popleft()
            if WINDOW_START <= cur.slot < WINDOW_END and len(past) >= MIN_HISTORY and jump > 0 and ret < 0:
                jumps = [p[1] for p in past]
                rets = [p[2] for p in past]
                if jump > np.percentile(jumps, JUMP_PCT) and ret <= np.percentile(rets, RET_PCT):
                    signals.append(Signal(coin, cur.ts, jump, ret))
            past.append((cur.slot, jump, ret))
    return {"signals": signals, "counts": counts}


def trades(signals: List[Signal], prices: Prices, final: bool = False) -> List[dict]:
    """Each signal's trade. One at a time per coin: a signal during a hold is recorded as ignored."""
    out, held_until = [], {}
    for s in sorted(signals, key=lambda x: x.ts):
        t = {"coin": s.coin, "signal_ts": s.ts, "entry_ts": None, "entry_px": None, "exit_ts": None, "exit_px": None}
        if s.ts < held_until.get(s.coin, 0):
            out.append({**t, "status": "ignored"})
            continue
        entry = prices.first_open(s.coin, s.ts + ENTRY_DELAY_S, final)
        if entry == PENDING:
            held_until[s.coin] = math.inf
            out.append({**t, "status": "pending"})
            continue
        if entry == MISSING:
            out.append({**t, "status": "dropped_entry"})
            continue
        if entry[0] - s.ts > FILL_TOLERANCE_S:
            out.append({**t, "status": "dropped_entry"})
            continue
        t.update(entry_ts=entry[0], entry_px=entry[1])
        due = entry[0] + HOLD_S
        leave = prices.first_open(s.coin, due, final)
        if leave == PENDING:
            held_until[s.coin] = math.inf
            out.append({**t, "status": "open"})
        elif leave == MISSING:
            held_until[s.coin] = due
            out.append({**t, "status": "dropped_exit"})
        elif leave[0] >= WINDOW_END:
            held_until[s.coin] = leave[0]
            out.append({**t, "status": "dropped_after_window"})
        else:
            held_until[s.coin] = leave[0]
            out.append({**t, "exit_ts": leave[0], "exit_px": leave[1], "status": "closed"})
    return out


def funding_bps(coin: str, entry_ts: int, exit_ts: int, fetch: Optional[Fetch] = None) -> float:
    """Hourly rates settled in (entry, exit], in bps. A long pays a positive rate."""
    df = hl.funding_history(coin, entry_ts * 1000, exit_ts * 1000, fetch=fetch)
    if df.empty:
        return 0.0
    return 1e4 * float(df.loc[(df["ts"] > entry_ts) & (df["ts"] <= exit_ts), "funding"].sum())


def net_bps(entry_px: float, exit_px: float, funding: float) -> float:
    return 1e4 * (exit_px / entry_px - 1) - COST_BPS - funding


def evaluate(closed: pd.DataFrame) -> Dict:
    """The registered verdict, from closed trades with `coin`, `entry_ts` and `net_bps`."""
    n = len(closed)
    if n < MIN_TRADES:
        return {"verdict": "INCONCLUSIVE", "n": n, "mean": math.nan, "t": math.nan, "checks": {}}
    x = closed["net_bps"].astype(float)
    day = pd.to_datetime(closed["entry_ts"], unit="s").dt.normalize()
    head = trade_weighted_nw(x, day, lags=1)
    early = closed["entry_ts"] < SECOND_HALF
    enough = closed.groupby("coin")["coin"].transform("size") >= MIN_COIN_TRADES
    by_coin = closed[enough].groupby("coin")["net_bps"].mean()
    checks = {
        "pays": bool(head["mean"] > 0 and head["t"] >= PASS_T),
        "both_halves": bool(early.any() and (~early).any() and x[early].mean() > 0 and x[~early].mean() > 0),
        "coins": bool(by_coin.size and (by_coin > 0).sum() > by_coin.size / 2),
        "largest": bool(closed["coin"].isin(LARGEST).any() and x[closed["coin"].isin(LARGEST)].mean() > 0),
    }
    return {"verdict": "PASS" if all(checks.values()) else "FAIL", "n": n, "mean": head["mean"], "t": head["t"],
            "checks": checks}


def ledger(data: Path = DATA, fetch: Optional[Fetch] = None) -> Dict:
    """The verdict's ledger, rebuilt from the recordings once the window has closed."""
    prices = Prices()
    for path in sorted(Path(data).glob("candles/*.csv.gz")):
        load_candle_file(path, prices)
    slots = [read_slot(p) for p in slot_paths(data)]
    w = walk(slots, prices, final=True)
    rows = trades(w["signals"], prices, final=True)
    for r in rows:
        if r["status"] == "closed":
            f = funding_bps(r["coin"], r["entry_ts"], r["exit_ts"], fetch)
            r.update(funding_bps=f, net_bps=net_bps(r["entry_px"], r["exit_px"], f))
    closed = pd.DataFrame([r for r in rows if r["status"] == "closed"], columns=list(rows[0]) if rows else None)
    return {"rows": rows, "counts": w["counts"], "result": evaluate(closed) if rows else evaluate(pd.DataFrame())}


# ----------------------------------------------------------------- the paper book
SCHEMA = """CREATE TABLE IF NOT EXISTS trades (
    coin TEXT, signal_ts INTEGER, status TEXT, entry_ts INTEGER, entry_px REAL, exit_ts INTEGER, exit_px REAL,
    funding_bps REAL, net_bps REAL, usd_pnl REAL, recorded_ts INTEGER, PRIMARY KEY (coin, signal_ts))"""
DONE = ("closed", "ignored", "dropped_entry", "dropped_exit", "dropped_after_window")


class Book:
    """Applies the rule to each new slot. Each trade's first decision stays in the journal, so the book
    can later be compared with the ledger. `now`, `fetch` and `sleep` are injected in tests."""

    def __init__(self, state, data: Path = DATA, fetch: Optional[Fetch] = None, pace: float = 0.5, log=print):
        self.db = sqlite3.connect(state)
        self.db.row_factory = sqlite3.Row
        self.db.execute(SCHEMA)
        self.db.commit()
        self.data, self.fetch, self.pace, self.log = Path(data), fetch, pace, log
        self.slots: Dict[Path, Slot] = {}
        self.candle_files: set = set()
        self.prices = Prices()
        self.said = ""

    def close(self) -> None:
        self.db.close()

    def _say_once(self, text: str) -> None:
        if text != self.said:
            self.log(text)
            self.said = text

    def step(self, now: Optional[int] = None) -> int:
        """Returns how many trades were written. Before the window it reads no recorded value."""
        now = int(time.time()) if now is None else now
        if now < WINDOW_START:
            self._say_once(f"#58 waiting: the window opens {pd.Timestamp(WINDOW_START, unit='s')} UTC; no value read")
            return 0
        if now >= WINDOW_END + 2 * HOLD_S and not self._unfinished():
            self._say_once("#58's window has closed and every trade is settled; run espero hlp --verdict")
            return 0
        fresh = [p for p in slot_paths(self.data) if p not in self.slots]
        if not fresh:
            return 0
        for p in fresh:
            self.slots[p] = read_slot(p)
        for p in sorted(self.data.glob("candles/*.csv.gz")):
            if p not in self.candle_files:
                load_candle_file(p, self.prices)
                self.candle_files.add(p)
        fetch_recent(self.prices, now, self.fetch, self.pace)
        slots = [self.slots[p] for p in sorted(self.slots)]
        rows = trades(walk(slots, self.prices)["signals"], self.prices)
        return self._record(rows, now)

    def _unfinished(self) -> bool:
        marks = ",".join("?" for _ in DONE)
        return bool(self.db.execute(f"SELECT 1 FROM trades WHERE status NOT IN ({marks}) LIMIT 1", DONE).fetchone())

    def _record(self, rows: List[dict], now: int) -> int:
        """Finished trades are never rewritten: the journal keeps what the book decided at the time."""
        done = {(r["coin"], r["signal_ts"]) for r in self.db.execute(
            f"SELECT coin, signal_ts FROM trades WHERE status IN ({','.join('?' for _ in DONE)})", DONE)}
        wrote = 0
        for r in rows:
            if (r["coin"], r["signal_ts"]) in done:
                continue
            funding = net = pnl = None
            if r["status"] == "closed":
                funding = funding_bps(r["coin"], r["entry_ts"], r["exit_ts"], self.fetch)
                net = net_bps(r["entry_px"], r["exit_px"], funding)
                pnl = BOOK_USD * net / 1e4
            self.db.execute("INSERT OR REPLACE INTO trades VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                            (r["coin"], r["signal_ts"], r["status"], r["entry_ts"], r["entry_px"], r["exit_ts"],
                             r["exit_px"], funding, net, pnl, now))
            wrote += 1
            self.log(f"#58 {r['coin']} {r['status']}" + (f" net {net:+.1f} bps" if net is not None else ""))
        self.db.commit()
        return wrote


def status(state, data: Path = DATA) -> List[str]:
    """What the book holds. Running numbers are for watching and are not a result."""
    paths = slot_paths(data)
    now = int(time.time())
    lines = [f"#58 paper book: window {pd.Timestamp(WINDOW_START, unit='s').date()} to "
             f"{pd.Timestamp(WINDOW_END - 1, unit='s').date()}; "
             + ("not open yet" if now < WINDOW_START else "open" if now < WINDOW_END else "closed"),
             f"HLP slots on disk: {len(paths)}"]
    if not Path(state).exists():
        return lines + ["no journal yet"]
    db = sqlite3.connect(state)
    db.row_factory = sqlite3.Row
    db.execute(SCHEMA)
    counts = {r["status"]: r["n"] for r in db.execute("SELECT status, COUNT(*) n FROM trades GROUP BY status")}
    lines.append("trades: " + (", ".join(f"{k} {v}" for k, v in sorted(counts.items())) or "none yet"))
    pnl = db.execute("SELECT SUM(usd_pnl) s, AVG(net_bps) m, COUNT(*) n FROM trades WHERE status='closed'").fetchone()
    if pnl["n"]:
        lines.append(f"closed: {pnl['n']} trades, {pnl['s']:+.2f} USD at ${BOOK_USD:,.0f} each, "
                     f"mean net {pnl['m']:+.1f} bps (running numbers, not a result)")
    db.close()
    return lines
