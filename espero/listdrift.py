"""#67: short a new Binance USD-M perp the day after it lists, long BTC, and hold: does the listing drift down?

research/PREREGISTRATION_LISTDRIFT.md. Pure: frames in, numbers out, no I/O; research/listdrift.py reads the
point-in-time store, fetches funding from Binance's archive and prints.

A position is one unit of notional on each leg, opened at the open of the day after the listing day and closed at
the open of the day H days later. Its daily P&L is the price move over the day divided by the entry price, funding
as settled, and the costs on its first and last day. The daily series averages every open position's P&L on each
day (calendar time), so overlapping listings and their shared market moves are one observation a day.
"""
from __future__ import annotations

import math
import re
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

import numpy as np
import pandas as pd

from .factor_eval import newey_west_t

DAY_MS = 86_400_000
HOLDS = (7, 14, 30)                 # days; the design window picks one, the other two are information
CHOSEN_HOLD: Optional[int] = None   # set from the design run, committed with the pre-registration
FEE_BPS = 5.0                       # Binance USD-M taker, espero.costs.FEES_BPS
LISTING_HALF_SPREAD_BPS = 10.0      # assumed: a coin in its first month is unmeasured (see the pre-registration)
SETTLE_SLACK_MS = 60_000            # the archive stamps settlements a few ms after the hour
PASS_T = 3.0
MIN_EVENTS = 100
MIN_DAYS = 100
BASKET_N = 30
BASKET_AGE_DAYS = 365
BASKET_LOOKBACK = 30
MAJORS = {"BTCUSDT", "ETHUSDT"}
PEGGED = {"USDCUSDT", "FDUSDUSDT", "TUSDUSDT", "USDPUSDT", "USD1USDT", "PAXGUSDT", "XAUTUSDT"}
INDEX = {"DEFIUSDT", "BTCDOMUSDT", "FOOTBALLUSDT", "BLUEBIRDUSDT", "ALLUSDT"}

DESIGN = (pd.Timestamp("2023-01-01"), pd.Timestamp("2024-12-31"))
HOLDOUT = (pd.Timestamp("2025-01-01"), pd.Timestamp("2026-09-30"))
DESIGN_LAST_MONTH = "2024-12"
HOLDOUT_LAST_MONTH = "2026-09"

PASS = "PASS"
FAIL = "FAIL"
INCONCLUSIVE = "INCONCLUSIVE"


# ---------------------------------------------------------------------------------------------- events
def base(symbol: str) -> str:
    """The asset under a USDT perp, without Binance's 1000-style multiplier."""
    return re.sub(r"^(1000000|100000|10000|1000|1M)", "", symbol[:-4])


def classify(symbols: Dict[str, dict], first_month: Dict[str, str], since: str = "2023-01") -> pd.DataFrame:
    """Every USDT perp first traded in `since` or later, with its listing day and why it is in or out.

    `symbols`: symbol -> {"type": underlyingType, "onboard_ms": onboardDate} from the newest exchangeInfo
    capture that lists it. `first_month`: symbol -> the month of its first daily bar in the store."""
    old = {base(s) for s, m in first_month.items() if m < since and s.endswith("USDT") and "_" not in s}
    rows, seen = [], set(old)
    for s, m in sorted(first_month.items(), key=lambda kv: (kv[1], kv[0])):
        if m < since or not s.endswith("USDT") or "_" in s:
            continue
        info = symbols.get(s, {})
        kind, on = info.get("type"), info.get("onboard_ms")
        listing = pd.Timestamp(int(on) // DAY_MS * DAY_MS, unit="ms") if on else None
        b = base(s)
        if s in INDEX:
            why = "index"
        elif kind != "COIN":
            why = f"type {kind}"
        elif listing is None:
            why = "no listing time"
        elif listing.strftime("%Y-%m") != m:
            why = "listing month differs from the first bar's"
        elif b in seen:
            why = "base listed before"
        else:
            why = ""
        seen.add(b)
        rows.append({"symbol": s, "first_month": m, "type": kind, "listing_day": listing, "excluded": why})
    return pd.DataFrame(rows)


def dated(events: pd.DataFrame, first_bar: Dict[str, pd.Timestamp]) -> pd.DataFrame:
    """The events with the listing day moved to the day of the symbol's first daily bar, when trading began.
    Binance's onboardDate, which decided which events exist, stays as `onboard_day`: it falls one to four days
    before the first trade for about one event in seven. An event with no bar in the files read is dropped."""
    out = events.copy()
    out["onboard_day"] = out["listing_day"]
    out["listing_day"] = out["symbol"].map(first_bar)
    return out[out["listing_day"].notna()]


def window(listing_day: pd.Timestamp, hold: int, entry_lag: int = 1) -> Tuple[pd.Timestamp, pd.Timestamp]:
    """Entry at the open of the day `entry_lag` after the listing day; exit at the open `hold` days later."""
    entry = listing_day + pd.Timedelta(days=entry_lag)
    return entry, entry + pd.Timedelta(days=hold)


def inside(entry: pd.Timestamp, exit_: pd.Timestamp, span: Tuple[pd.Timestamp, pd.Timestamp]) -> bool:
    """The whole position, entry to exit, falls inside the span, so no day of it belongs to the other span."""
    return span[0] <= entry and exit_ <= span[1]


# ---------------------------------------------------------------------------------------------- one leg
def leg(bars: pd.DataFrame, entry: pd.Timestamp, exit_: pd.Timestamp, side: int) -> pd.DataFrame:
    """Daily P&L of one unit of notional, `side` +1 long or -1 short, from entry's open to exit's open.

    `bars`: daily `open` and `close` by day. Day E carries close(E) - open(E), each later day its close's change,
    the exit day open(X) - close(X-1), all over open(E). A coin whose bars stop before X exits at its last close.
    Returns `pnl` and `ratio` (close over entry price, for funding) by day; empty when the entry bar is missing."""
    if entry not in bars.index:
        return pd.DataFrame(columns=["pnl", "ratio"])
    o = float(bars.at[entry, "open"])
    held = bars.loc[(bars.index >= entry) & (bars.index < exit_), "close"]
    days = pd.date_range(entry, exit_ - pd.Timedelta(days=1), freq="D")
    close = held.reindex(days)
    last_day = close.last_valid_index()
    if last_day is None or not o > 0:
        return pd.DataFrame(columns=["pnl", "ratio"])
    close = close.loc[:last_day].ffill()
    prev = close.shift(1).fillna(o)
    pnl = (close - prev) / o
    out = pd.DataFrame({"pnl": side * pnl, "ratio": close / o})
    if last_day == days[-1] and exit_ in bars.index:
        out.loc[exit_] = {"pnl": side * (float(bars.at[exit_, "open"]) - float(close.iloc[-1])) / o,
                          "ratio": float(close.iloc[-1]) / o}
    return out


def funding(rates: pd.Series, path: pd.DataFrame, entry: pd.Timestamp, exit_: pd.Timestamp, side: int) -> pd.Series:
    """Funding by day for a position on `path` (from `leg`). `rates`: the settled rate by settlement time in ms; a
    positive rate is paid by longs to shorts. A settlement counts when it falls after the entry and at or before
    the exit, and is booked on the day that ends at it, scaled by that day's close over the entry price."""
    if path.empty or rates.empty:
        return pd.Series(dtype=float)
    lo = entry.value // 1_000_000 + SETTLE_SLACK_MS
    hi = exit_.value // 1_000_000 + SETTLE_SLACK_MS
    t = rates.index.to_numpy(dtype="int64")
    keep = (t > lo) & (t <= hi)
    if not keep.any():
        return pd.Series(dtype=float)
    r = rates.to_numpy(dtype=float)[keep]
    day = pd.to_datetime((t[keep] - SETTLE_SLACK_MS) // DAY_MS * DAY_MS, unit="ms")
    ratio = path["ratio"].reindex(day).to_numpy(dtype=float)
    booked = pd.Series(-side * r * ratio, index=day)
    return booked[np.isfinite(booked.to_numpy())].groupby(level=0).sum()


def cost_per_side(listing_half_spread_bps: float = LISTING_HALF_SPREAD_BPS, fee_bps: float = FEE_BPS) -> float:
    return (fee_bps + listing_half_spread_bps) / 1e4


def close_of(short: pd.DataFrame, exit_: pd.Timestamp) -> pd.Timestamp:
    """When the pair closes: the planned exit, or, if the listing's bars stop early, the open after its last day,
    which is its last close."""
    last = short.index[-1]
    return exit_ if last == exit_ else last + pd.Timedelta(days=1)


def hedge_leg(bars: pd.DataFrame, entry: pd.Timestamp, short: pd.DataFrame, exit_: pd.Timestamp) -> pd.DataFrame:
    """A long hedge over the listing's own days: it closes when the listing closes, at the same close if early."""
    stop = close_of(short, exit_)
    h = leg(bars, entry, stop, +1)
    if stop != exit_:
        h = h.loc[h.index <= short.index[-1]]
    return h


# ---------------------------------------------------------------------------------------------- one event
def event(listing: pd.DataFrame, hedge: pd.DataFrame, entry: pd.Timestamp, exit_: pd.Timestamp,
          listing_rates: pd.Series, hedge_rates: pd.Series, listing_cost: float, hedge_cost: float,
          with_funding: bool = True) -> pd.DataFrame:
    """Daily P&L of short the listing, long the hedge, one unit each, net of funding and costs.
    Columns: short, long, funding, cost, net."""
    s = leg(listing, entry, exit_, -1)
    if s.empty:
        return pd.DataFrame(columns=["short", "long", "funding", "cost", "net"])
    h = hedge_leg(hedge, entry, s, exit_)
    stop = close_of(s, exit_)
    f = pd.Series(0.0, index=s.index)
    if with_funding:
        f = f.add(funding(listing_rates, s, entry, stop, -1), fill_value=0.0)
        f = f.add(funding(hedge_rates, h, entry, stop, +1), fill_value=0.0)
        f = f.reindex(s.index).fillna(0.0)
    c = pd.Series(0.0, index=s.index)
    c.iloc[0] -= listing_cost + hedge_cost
    c.iloc[-1] -= listing_cost + hedge_cost
    out = pd.DataFrame({"short": s["pnl"], "long": h["pnl"].reindex(s.index).fillna(0.0), "funding": f, "cost": c})
    out["net"] = out.sum(axis=1)
    return out


def abnormal(listing: pd.DataFrame, members: Dict[str, pd.DataFrame], entry: pd.Timestamp,
             exit_: pd.Timestamp) -> pd.DataFrame:
    """Short the listing, long an equal-weight basket of `members`, price only: no funding, no costs.
    Column: net."""
    s = leg(listing, entry, exit_, -1)
    if s.empty or not members:
        return pd.DataFrame(columns=["net"])
    b = basket([hedge_leg(m, entry, s, exit_) for m in members.values()])
    return pd.DataFrame({"net": s["pnl"] + b["pnl"].reindex(s.index).fillna(0.0)})


def basket(paths: Sequence[pd.DataFrame]) -> pd.DataFrame:
    """An equal-weight long basket: the mean of its members' daily P&L, a member that stops contributing nothing."""
    if not paths:
        return pd.DataFrame(columns=["pnl"])
    p = pd.concat([x["pnl"] for x in paths], axis=1)
    return pd.DataFrame({"pnl": p.fillna(0.0).sum(axis=1) / len(paths)})


def basket_members(volume: pd.DataFrame, first_day: Dict[str, pd.Timestamp], entry: pd.Timestamp,
                   excluded: Iterable[str], n: int = BASKET_N, age_days: int = BASKET_AGE_DAYS,
                   lookback: int = BASKET_LOOKBACK) -> List[str]:
    """The `n` established coins by quote volume over the `lookback` days before entry: first traded at least
    `age_days` before it, a bar on every one of those days, nothing from the entry day on."""
    days = pd.date_range(entry - pd.Timedelta(days=lookback), entry - pd.Timedelta(days=1), freq="D")
    v = volume.reindex(days)
    cut = entry - pd.Timedelta(days=age_days)
    bad = set(excluded)
    cols = [c for c in v.columns if c not in bad and c in first_day and first_day[c] <= cut and v[c].notna().all()]
    return list(v[cols].sum().sort_values(ascending=False).index[:n])


# ---------------------------------------------------------------------------------------------- the series
def calendar(events: Dict[str, pd.DataFrame], column: str = "net") -> pd.DataFrame:
    """Each day's mean P&L over the positions open that day, and how many were open."""
    if not events:
        return pd.DataFrame(columns=["mean", "open"])
    p = pd.concat({k: v[column] for k, v in events.items() if len(v)}, axis=1)
    return pd.DataFrame({"mean": p.mean(axis=1), "open": p.notna().sum(axis=1)}).sort_index()


def totals(events: Dict[str, pd.DataFrame], column: str = "net") -> pd.Series:
    """Each position's whole P&L."""
    return pd.Series({k: float(v[column].sum()) for k, v in events.items() if len(v)}, dtype=float)


def nw_lags(n: int) -> int:
    """research/FDR_STANDARD.md's lag count."""
    return int(math.floor(4 * (n / 100) ** (2 / 9))) if n > 0 else 0


def t_of(x: pd.Series) -> float:
    v = x.dropna()
    return newey_west_t(v.to_numpy(dtype=float), nw_lags(len(v))) if len(v) >= 3 else float("nan")


def p_two_sided(t: float) -> float:
    return math.erfc(abs(t) / math.sqrt(2)) if math.isfinite(t) else float("nan")


def halves(x: pd.Series) -> Tuple[float, float]:
    v = x.dropna()
    k = (len(v) + 1) // 2
    return float(v.iloc[:k].mean()), float(v.iloc[k:].mean())


def evaluate(net: Dict[str, pd.DataFrame], abnormal: Dict[str, pd.DataFrame], q: Optional[float] = None) -> dict:
    """The registered criteria. `net`: short listing, long BTC, net of funding and costs; `abnormal`: short listing,
    long the established basket, price only. `q` is #67's Benjamini-Hochberg q over the ledger at judgment."""
    cal = calendar(net)["mean"]
    ab = calendar(abnormal, "net")["mean"]
    per = totals(net)
    n_days = int(cal.notna().sum())
    t = t_of(cal)
    first, second = halves(cal) if n_days else (float("nan"), float("nan"))
    res = {"events": int(len(per)), "days": n_days, "mean": float(cal.mean()) if n_days else float("nan"),
           "t": t, "lags": nw_lags(n_days), "p": p_two_sided(t), "q": q, "first_half": first, "second_half": second,
           "median_event": float(per.median()) if len(per) else float("nan"),
           "mean_event": float(per.mean()) if len(per) else float("nan"),
           "abnormal_mean": float(ab.mean()) if len(ab) else float("nan"), "abnormal_t": t_of(ab)}
    if res["events"] < MIN_EVENTS or n_days < MIN_DAYS:
        res["outcome"] = INCONCLUSIVE
        return res
    checks = {"t": math.isfinite(t) and t >= PASS_T and res["mean"] > 0,
              "halves": first > 0 and second > 0,
              "median": res["median_event"] > 0,
              "abnormal": res["abnormal_mean"] > 0,
              "fdr": q is not None and q < 0.05}
    res["checks"] = checks
    if not (checks["t"] and checks["halves"] and checks["median"] and checks["abnormal"]):
        res["outcome"] = FAIL
    elif q is None:
        res["outcome"] = "criteria met but the FDR bar, read from the ledger at judgment"
    else:
        res["outcome"] = PASS if checks["fdr"] else FAIL
    return res


def break_even_bps(events: Dict[str, pd.DataFrame], listing_cost: float) -> float:
    """The listing leg's cost per side, in bps, at which the mean position's net would be zero."""
    per = totals(events)
    if not len(per):
        return float("nan")
    return float((per.mean() + 2 * listing_cost) / 2 * 1e4)
