"""At which holding period do the repo's real signals pay? (#43, research/PREREGISTRATION_HORIZONS.md)

Pure: bars, events and settled funding in; trades and statistics out. Times are seconds UTC.

* entry at the open of the bar starting at the entry time; exit at the close of the
  bar that ends at entry + h. A missing bar drops the trade.
* one position per coin at a time: an entry inside the previous kept hold is skipped.
* net = side x price return - round trip - side x the settled funding in (entry, exit].
* each entry day's mean net is one observation; t is Newey-West, lags max(1, ceil(h days)).
"""
from __future__ import annotations

import math
from statistics import NormalDist
from typing import Dict, List, Optional, Sequence

import numpy as np
import pandas as pd

from .factor_eval import newey_west_t

BAR_S = 300
DAY_S = 86_400
HORIZONS = {"1h": 3600, "4h": 4 * 3600, "12h": 12 * 3600, "1d": DAY_S, "3d": 3 * DAY_S, "7d": 7 * DAY_S,
            "14d": 14 * DAY_S}
SELECT_END = "2024-12-31"
HOLDOUT_START = "2025-01-01"
HOLDOUT_SPLIT = "2025-12-01"
DATA_END = "2026-10-27"
CARRY_T = 2.0
SHRINK = 1 / 3
ALPHA = 0.05
MDE_Z = 2.49                 # 80% power at one-sided 5%
PRIOR_TESTS = 43
CELLS = 5 * 7
BAR = 4.087
SHORTS_PAY = -0.0005
CARRY_EDGE = 0.0001
SEEN = {("S1", "1h"), ("S1", "4h"), ("S2", "1h")}


def prices(bars: pd.DataFrame, entry: np.ndarray, h: int):
    """(entry open, exit close) per entry time; nan where either bar is missing."""
    ts = bars.index.to_numpy(dtype="int64")
    o, c = bars["open"].to_numpy(float), bars["close"].to_numpy(float)
    entry = np.asarray(entry, dtype="int64")

    def at(t, col):
        i = np.searchsorted(ts, t)
        ok = (i < len(ts)) & (ts[np.minimum(i, len(ts) - 1)] == t)
        return np.where(ok, col[np.minimum(i, len(ts) - 1)], np.nan)
    return at(entry, o), at(entry + h - BAR_S, c)


def funding_over(entry: np.ndarray, h: int, settle_ts: np.ndarray, rates: np.ndarray) -> np.ndarray:
    """Sum of settled rates with entry < settlement <= entry + h."""
    order = np.argsort(settle_ts)
    st, cs = np.asarray(settle_ts, dtype="int64")[order], np.r_[0.0, np.cumsum(np.asarray(rates, float)[order])]
    lo = np.searchsorted(st, np.asarray(entry, dtype="int64"), side="right")
    hi = np.searchsorted(st, np.asarray(entry, dtype="int64") + h, side="right")
    return cs[hi] - cs[lo]


def one_per_coin(entry: np.ndarray, h: int) -> np.ndarray:
    """Mask of entries a single position could take: each after the last kept one's exit."""
    keep = np.zeros(len(entry), dtype=bool)
    free = -np.inf
    for k in np.argsort(entry, kind="stable"):
        if entry[k] >= free:
            keep[k] = True
            free = entry[k] + h
    return keep


def trades(events: pd.DataFrame, bars: pd.DataFrame, h: int, round_trip: float,
           settle_ts: np.ndarray, rates: np.ndarray, one: bool = True) -> pd.DataFrame:
    """One coin's events (columns ts, side) at horizon h -> trades with gross, funding, net."""
    ev = events.sort_values("ts", kind="stable").reset_index(drop=True)
    e = ev["ts"].to_numpy(dtype="int64")
    p0, p1 = prices(bars, e, h)
    ok = np.isfinite(p0) & np.isfinite(p1)
    ev, e, p0, p1 = ev[ok].reset_index(drop=True), e[ok], p0[ok], p1[ok]
    if one and len(e):
        m = one_per_coin(e, h)
        ev, e, p0, p1 = ev[m].reset_index(drop=True), e[m], p0[m], p1[m]
    side = ev["side"].to_numpy(float)
    fund = funding_over(e, h, settle_ts, rates)
    gross = side * (p1 / p0 - 1)
    out = ev.assign(day=pd.to_datetime(e, unit="s", utc=True).strftime("%Y-%m-%d"),
                    exit=e + h, gross=gross, funding=-side * fund)
    out["net"] = out["gross"] - round_trip + out["funding"]
    out["net_spot"] = out["gross"] - round_trip
    return out


def stats(tr: pd.DataFrame, h: int, col: str = "net") -> dict:
    """Day-mean series of `col` -> mean (bps), Newey-West t, days, trades, hit rate."""
    if not len(tr):
        return {"mean": math.nan, "t": math.nan, "days": 0, "trades": 0, "hit": math.nan}
    g = tr.groupby("day")[col].mean().sort_index()
    lags = max(1, math.ceil(h / DAY_S))
    return {"mean": 1e4 * float(g.mean()), "t": newey_west_t(g, lags), "days": int(len(g)),
            "trades": int(len(tr)), "hit": float((tr["gross"] > 0).mean())}


def windows(tr: pd.DataFrame):
    """(selection, holdout) trades: whole hold ends by SELECT_END / enters on or after HOLDOUT_START."""
    end = pd.Timestamp(SELECT_END, tz="UTC").value // 10 ** 9 + DAY_S
    last = pd.Timestamp(DATA_END, tz="UTC").value // 10 ** 9 + DAY_S
    sel = tr[tr["exit"] <= end]
    hold = tr[(tr["day"] >= HOLDOUT_START) & (tr["exit"] <= last)]
    return sel, hold


def choose(cells: Dict[str, dict]) -> Optional[str]:
    """The horizon with the largest t among net > 0 and t >= CARRY_T, else None."""
    ok = {h: c for h, c in cells.items() if c["mean"] > 0 and np.isfinite(c["t"]) and c["t"] >= CARRY_T}
    return max(ok, key=lambda h: ok[h]["t"]) if ok else None


def holm(pvals: Dict[str, float], alpha: float = ALPHA) -> Dict[str, bool]:
    """Holm step-down: sort ascending, the i-th (0-based) must be <= alpha / (k - i); stop at the first miss."""
    out = {k: False for k in pvals}
    k = len(pvals)
    for i, (name, p) in enumerate(sorted(pvals.items(), key=lambda x: x[1])):
        if p <= alpha / (k - i):
            out[name] = True
        else:
            break
    return out


def p_one_sided(t: float) -> float:
    return 1.0 - NormalDist().cdf(t) if np.isfinite(t) else 1.0


def confirm(signal: str, h: str, sel: dict, hold: dict, half1: dict, half2: dict, holm_ok: bool) -> Dict[str, bool]:
    return {"holm": bool(hold["mean"] > 0 and holm_ok),
            "halves": bool(half1["mean"] > 0 and half2["mean"] > 0),
            "no_collapse": bool(hold["mean"] >= SHRINK * sel["mean"]),
            "unseen": (signal, h) not in SEEN}


def mde(sd: float, n: float) -> float:
    return MDE_Z * sd / math.sqrt(n) if n > 0 else math.nan


def trend_events(bars: pd.DataFrame, lookbacks: Sequence[int] = (28, 91, 364)) -> pd.DataFrame:
    """S4: at each 00:00 UTC close, all lookback returns positive -> a long entry at the next bar's open."""
    c = bars["close"]
    t = c.index.to_numpy(dtype="int64")
    daily = c[(t + BAR_S) % DAY_S == 0]                      # bars closing at 00:00
    dts = daily.index.to_numpy(dtype="int64") + BAR_S
    s = pd.Series(daily.to_numpy(float), index=dts)
    up = np.ones(len(s), dtype=bool)
    for lb in lookbacks:
        past = s.reindex(dts - lb * DAY_S).to_numpy()
        up &= np.isfinite(past) & (s.to_numpy() > past)
    return pd.DataFrame({"ts": dts[up], "side": 1.0})


def settlement_events(settle: pd.DataFrame, rule: str) -> pd.DataFrame:
    """S2 / S3 from #33's settlements (ts, rate8), 00/08/16 UTC only."""
    s = settle[(settle["ts"] % (8 * 3600)) == 0]
    if rule == "S2":
        s = s[s["rate8"] <= SHORTS_PAY]
        return pd.DataFrame({"ts": s["ts"].to_numpy(dtype="int64"), "side": -1.0})
    s = s[s["rate8"].abs() > CARRY_EDGE]
    return pd.DataFrame({"ts": s["ts"].to_numpy(dtype="int64"), "side": -np.sign(s["rate8"].to_numpy())})


def unconditional_sd(bars: pd.DataFrame, h: int, end_ts: int) -> tuple:
    """(sd of h-returns on a non-overlapping grid, count) before end_ts: for the MDE."""
    ts = bars.index.to_numpy(dtype="int64")
    grid = np.arange(ts[0] - ts[0] % h + h, end_ts - h, h)
    p0, p1 = prices(bars, grid, h)
    r = (p1 / p0 - 1)[np.isfinite(p0) & np.isfinite(p1)]
    return (float(r.std(ddof=1)) if len(r) > 1 else math.nan), int(len(r))


def fmt_list(xs: List[str]) -> str:
    return ", ".join(xs) if xs else "none"
