"""Cross-asset TSMOM, run as a paper account.

The pre-registered rule, applied to a real $100 balance and written to SQLite so
the track record exists independently of anyone's memory:

    at the first trading day of each month, hold equal weight in every asset
    whose 252-day return is positive (max 1/6 each); the rest stays in cash.

    espero tsmom --state tsmom.db --cash 100        # daily mark, rebalance when due
    espero tsmom --force                            # rebalance now regardless
    espero tsmom --report                           # history

Fills are simulated at the latest close with 10 bps per side. No keys, no orders.

Holdings earn total return: before each run marks or trades, every position's
value at the last run is rolled forward by its dividend- and split-adjusted
close, then turned back into shares at today's price. Dividends are reinvested
on the ex-date, and a split Yahoo restates into the history cannot multiply a
share count (USO did a 1:8 reverse split in 2020). The signal still reads raw
closes, as the rule was registered (research/ERRATA.md, 2026-10-29).
"""
from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Dict, Optional

import pandas as pd

from . import cash as treasury
from . import data

UNIVERSE = {
    "SPY": "SPY", "TLT": "TLT", "GLD": "GLD",
    "USO": "USO", "BTC-USD": "BTC", "ETH-USD": "ETH",
}
LOOKBACK = 252
MAX_WEIGHT = 1 / 6
COST = 0.001

SCHEMA = """
CREATE TABLE IF NOT EXISTS account (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts INTEGER NOT NULL, cash REAL, units TEXT, equity REAL, weights TEXT, note TEXT,
    positions TEXT, signals TEXT, deposit REAL, vehicle TEXT, carry REAL, traded REAL,
    UNIQUE(ts, note)   -- one mark per day, but a deposit and a mark can share a day
);
"""


def load_series(span: str = "2y") -> Dict[str, pd.Series]:
    """Each asset on its own calendar. Crypto trades weekends, ETFs do not, so a
    lookback must be counted in the asset's own rows or 252 rows silently becomes
    seven months."""
    out = {}
    for symbol, name in UNIVERSE.items():
        df = data.yahoo_daily(symbol, span)
        out[name] = df.set_index("dt")["close"].sort_index()
    return out


def load_frames(span: str = "2y", fetch: Callable[[str, str], pd.DataFrame] = None) -> Dict[str, pd.DataFrame]:
    """Each asset's raw close (the signal) and adjusted close (the P&L), from one fetch."""
    fetch = fetch or (lambda symbol, sp: data.yahoo_daily(symbol, sp, adjusted=True))
    return {name: fetch(symbol, span).set_index("dt")[["close", "adj_close"]].sort_index()
            for symbol, name in UNIVERSE.items()}


def closes(series: Dict[str, pd.Series]) -> pd.DataFrame:
    return pd.DataFrame(series).sort_index().ffill()


LOOKBACK_DAYS = 364   # 52 weeks: uniform across assets that trade 5 days and 7


def signals(series: Dict[str, pd.Series]) -> Dict[str, float]:
    """Look back 52 weeks on the calendar, not 252 rows.

    252 rows is a year for an ETF (5 sessions/week) and eight months for crypto
    (7 sessions/week). The backtest reindexed every asset to the SPY calendar,
    so it meant ~12 months; the live account must mean the same thing.
    """
    out = {}
    for name, s in series.items():
        s = s.dropna()
        if len(s) < 2:
            continue
        cutoff = s.index[-1] - pd.Timedelta(days=LOOKBACK_DAYS)
        past = s[s.index <= cutoff]
        if past.empty:
            continue
        out[name] = float(s.iloc[-1] / past.iloc[-1] - 1)
    return out


def target_weights(sig: Dict[str, float]) -> tuple[Dict[str, float], float]:
    picks = [a for a, v in sig.items() if v > 0]
    w = min(1.0 / len(picks), MAX_WEIGHT) if picks else 0.0
    weights = {a: (w if a in picks else 0.0) for a in sig}
    return weights, 1.0 - w * len(picks)


@dataclass
class Account:
    path: Path
    cash: float = 0.0
    units: Dict[str, float] = field(default_factory=dict)
    vehicle: str = "USD"
    carry_total: float = 0.0

    def __post_init__(self):
        self.db = sqlite3.connect(self.path, timeout=5.0)
        self.db.row_factory = sqlite3.Row
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.executescript(SCHEMA)
        cols = {r["name"] for r in self.db.execute("PRAGMA table_info(account)")}
        for col in ("positions", "signals", "deposit", "vehicle", "carry", "traded", "closes"):  # old databases
            if col not in cols:
                self.db.execute(f"ALTER TABLE account ADD COLUMN {col} TEXT")
                self.db.commit()
        row = self.db.execute("SELECT * FROM account ORDER BY ts DESC, id DESC LIMIT 1").fetchone()
        if row:
            self.cash = row["cash"]
            self.units = json.loads(row["units"])
            self.vehicle = row["vehicle"] or "USD"
            self.carry_total = float(row["carry"] or 0.0)

    def roll_forward(self, frames: Dict[str, pd.DataFrame], latest: pd.Series) -> None:
        """Dividends and restatements since the last run, applied to the share counts before any mark.

        Anchored on a bar that was already closed at the last run (`anchor_closes`, stored with that run): the
        share count is scaled by the restatement of that bar's raw close since (a split moves every past price,
        so the stored close against today's fetch of the same bar gives the factor) and by the dividend factor
        between that bar and now, (adj/close now) / (adj/close then), both from today's fetch. The bar the last
        run marked at is not used: Yahoo serves the current day's bar while it is still forming, and a count
        rolled from that bar's price drifted by (partial / final) every run with no trade (docs/AUDIT_PROD.md).
        A row written before the anchor existed falls back to the old roll from the marked dollar value."""
        prev = self.last()
        if not prev or not self.units:
            return
        anchors = json.loads(prev.get("closes") or "{}")
        then = pd.Timestamp(int(prev["ts"]), unit="s", tz="UTC")
        marked = json.loads(prev.get("positions") or "{}")
        for a in list(self.units):
            f = frames.get(a)
            if f is None or a not in latest or pd.isna(latest[a]):
                continue
            adj, close = f["adj_close"], f["close"]
            anchor = anchors.get(a)
            if anchor:
                at = pd.Timestamp(int(anchor["ts"]), unit="s", tz="UTC")
                if at not in f.index or pd.isna(adj.loc[at]) or pd.isna(close.loc[at]) or not close.loc[at]:
                    continue
                restated = float(close.loc[at]) / float(anchor["close"])
                dividends = (float(adj.iloc[-1]) / float(close.iloc[-1])) / (float(adj.loc[at]) / float(close.loc[at]))
                self.units[a] = self.units[a] / restated * dividends
                continue
            value = marked.get(a)
            old = adj.dropna()
            old = old[old.index <= then]
            if value is None or old.empty:
                continue
            self.units[a] = value * float(adj.dropna().iloc[-1] / old.iloc[-1]) / float(latest[a])

    @staticmethod
    def anchor_closes(frames: Dict[str, pd.DataFrame], today: datetime) -> Dict[str, dict]:
        """Per asset, the last bar dated before today's UTC date and its raw close: a bar that has closed, so a
        later fetch returns the same number unless the history is restated."""
        day = pd.Timestamp(today.astimezone(timezone.utc).date(), tz="UTC")
        out = {}
        for a, f in frames.items():
            done = f["close"].dropna()
            done = done[done.index < day]
            if not done.empty and done.iloc[-1]:
                out[a] = {"ts": int(done.index[-1].timestamp()), "close": float(done.iloc[-1])}
        return out

    def last(self) -> Optional[dict]:
        row = self.db.execute("SELECT * FROM account ORDER BY ts DESC, id DESC LIMIT 1").fetchone()
        return dict(row) if row else None

    def equity(self, prices: pd.Series) -> float:
        return self.cash + sum(u * float(prices[a]) for a, u in self.units.items())

    def rebalance(self, prices: pd.Series, weights: Dict[str, float]) -> float:
        """Two passes: estimate turnover, then size targets on the post-cost budget.

        The one-pass version invested the full equity and then subtracted the
        fees from cash, so cash went negative by exactly the cost of the trade
        -- the same bug `xs.py` fixed. Pinned by `test_no_leverage`.
        """
        total = self.equity(prices)
        tradable = {a: w for a, w in weights.items() if a in prices and pd.notna(prices[a])}
        traded = sum(abs(total * w - self.units.get(a, 0.0) * float(prices[a]))
                     for a, w in tradable.items())
        budget = max(total - traded * COST, 0.0)
        for a, w in tradable.items():
            self.units[a] = (budget * w) / float(prices[a])
        invested = sum(u * float(prices[a]) for a, u in self.units.items())
        self.cash = budget - invested
        return traded

    def rebalanced_in_month(self, year: int, month: int) -> bool:
        """True when a rebalance (or the opening trade) already happened this month."""
        for row in self.db.execute(
            "SELECT ts FROM account WHERE note IN ('init', 'rebalance', 'deposit')"
            " ORDER BY ts DESC LIMIT 12"
        ):
            d = datetime.fromtimestamp(int(row["ts"]), timezone.utc)
            if (d.year, d.month) == (year, month):
                return True
        return False

    def save(self, ts: int, equity: float, weights: Dict[str, float], note: str,
             positions: Optional[Dict[str, float]] = None,
             signals: Optional[Dict[str, float]] = None,
             deposit: float = 0.0, carry_this: float = 0.0, traded: float = 0.0,
             closes: Optional[Dict[str, dict]] = None) -> None:
        """`signals` is what the bot SAW when it decided, kept separately from the
        weights so a later viewer can audit the decision instead of re-deriving it.
        `closes` are the anchor bars the next run rolls the share counts from."""
        self.db.execute(
            "INSERT OR REPLACE INTO account(ts, cash, units, equity, weights, note, positions,"
            " signals, deposit, vehicle, carry, traded, closes) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (ts, self.cash, json.dumps(self.units), equity, json.dumps(weights), note,
             json.dumps(positions or {}), json.dumps(signals or {}), deposit,
             self.vehicle, carry_this, traded, json.dumps(closes or {})),
        )
        self.db.commit()

    def history(self, limit: int = 400) -> list[sqlite3.Row]:
        return self.db.execute("SELECT * FROM account ORDER BY ts DESC, id DESC LIMIT ?", (limit,)).fetchall()


def first_trading_day(now: Optional[datetime] = None) -> bool:
    """A weekday in the first three calendar days: the window in which the
    monthly rebalance may happen. The account itself makes sure it happens
    once, via `rebalanced_in_month`, not once per day of the window."""
    now = now or datetime.now(timezone.utc)
    return now.weekday() < 5 and now.day <= 3


def rebalance_due(acc: Account, now: Optional[datetime] = None) -> bool:
    now = now or datetime.now(timezone.utc)
    return first_trading_day(now) and not acc.rebalanced_in_month(now.year, now.month)


def run(state: str, cash: float, force: bool = False, span: str = "2y",
        deposit: float = 0.0, now: Optional[datetime] = None,
        fetch: Callable[[str, str], pd.DataFrame] = None) -> dict:
    frames = load_frames(span, fetch)
    series = {name: f["close"] for name, f in frames.items()}
    px = closes(series)
    latest = px.iloc[-1]
    ts = int(px.index[-1].timestamp())
    acc = Account(Path(state))
    acc.roll_forward(frames, latest)       # dividends and splits since the last run, before any mark
    fresh = acc.cash == 0.0 and not acc.units
    if fresh:
        acc.cash = cash
        deposit += cash          # opening capital counts as contributed, not as profit
    elif deposit:
        acc.cash += deposit

    sig = signals(series)
    weights, cash_w = target_weights(sig)

    due = fresh or force or rebalance_due(acc, now) or deposit > 0
    traded = 0.0
    note = "mark"
    if due:
        traded = acc.rebalance(latest, weights)
        note = "init" if fresh else ("deposit" if deposit else "rebalance")
    else:
        # a mark must not rewrite the decision it is marking: keep the snapshot
        prev = acc.last()
        if prev:
            weights = json.loads(prev.get("weights") or "{}") or weights
        prev_sig = json.loads((prev or {}).get("signals") or "{}") if prev else {}
        if prev_sig:
            sig = prev_sig

    # accrue interest on idle cash for the time since the last run
    prev_row = acc.last()
    carry_this = 0.0
    if prev_row and prev_row.get("vehicle"):
        days = max(0.0, (ts - int(prev_row["ts"])) / 86400.0)
        apy = next((v.apy for v in treasury.DEFAULT_VEHICLES if v.name == prev_row["vehicle"]), 0.0)
        carry_this = treasury.carry(acc.cash, apy, days)
        acc.cash += carry_this
        acc.carry_total += carry_this

    # decide where the uninvested cash lives
    decision = treasury.choose(acc.cash)
    acc.vehicle = decision.vehicle

    equity = acc.equity(latest)
    marked = {a: u * float(latest[a]) for a, u in acc.units.items()}
    anchors = Account.anchor_closes(frames, now or datetime.now(timezone.utc))
    acc.save(ts, equity, weights, note, positions=marked, signals=sig, deposit=deposit,
             carry_this=carry_this, traded=traded, closes=anchors)
    return {
        "ts": px.index[-1], "signals": sig, "weights": weights, "cash_weight": cash_w,
        "equity": equity, "traded": traded, "note": note,
        "positions": {a: u * float(latest[a]) for a, u in acc.units.items()},
        "account": acc, "cash_decision": decision, "carry_total": acc.carry_total,
    }


def format_report(res: dict) -> str:
    lines = [f"as of {res['ts'].date()}  equity ${res['equity']:.2f}  ({res['note']})", ""]
    lines.append(f"{'asset':6s} {'12m return':>11s} {'target':>8s} {'current $':>10s}")
    for a in res["signals"]:
        pos = res["positions"].get(a, 0.0)
        lines.append(f"{a:6s} {100*res['signals'][a]:+10.1f}% {100*res['weights'][a]:7.0f}% {pos:10.2f}")
    idle = res['equity'] - sum(res['positions'].values())
    lines.append(f"{'cash':6s} {'':11s} {100*res['cash_weight']:7.0f}% {idle:10.2f}")
    d = res.get("cash_decision")
    if d:
        lines.append(f"\ncash ${d.amount + d.reserve:,.2f}: keep ${d.reserve:,.2f} liquid, "
                     f"sweep ${d.amount:,.2f} -> {d.vehicle}  ({d.reason})")
    if res.get("carry_total"):
        lines.append(f"carry accrued to date: ${res['carry_total']:+.2f}")
    if res["traded"]:
        lines.append(f"traded ${res['traded']:.2f} at {COST*1e4:.0f} bps a side")
    return "\n".join(lines)
