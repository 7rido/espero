"""#77: the slow night shift, the stock perps held from the week's first close to its last open, once a week
(research/PREREGISTRATION_NIGHTWEEK.md).

The frozen rule and its criteria, pure: daily bars in, weekly returns and a verdict out, no I/O.
research/nightweek.py fetches and prints. The numbers below are the pre-registration's.
"""
from __future__ import annotations

import datetime as dt
from typing import Dict, List, Mapping, Optional, Sequence, Tuple

COST_BPS = 14.0                  # a fill, as #76
FUNDING_YEAR = 0.10              # a long pays this a year, pro rata for the hours held
SESSION_S = 6.5 * 3600           # the official close is 6.5 hours after the 09:30 open
HOURS_YEAR = 365 * 24
MIN_TRADING_DAYS = 3
MIN_PF = 1.5
MIN_T = 3.0
MAX_Q = 0.05
MIN_WEEKS = 100
MIN_MARKET_WEEKS = 100


def week_of(day: str) -> str:
    """The Monday that starts `day`'s calendar week, ISO."""
    d = dt.date.fromisoformat(day)
    return (d - dt.timedelta(days=d.weekday())).isoformat()


def windows(day: Sequence[str]) -> Dict[str, Tuple[int, int]]:
    """{week: (the index of its first trading day, of its last)} for weeks with at least three trading days."""
    by: Dict[str, List[int]] = {}
    for k, d in enumerate(day):
        by.setdefault(week_of(d), []).append(k)
    return {w: (ks[0], ks[-1]) for w, ks in by.items() if len(ks) >= MIN_TRADING_DAYS}


def weeks(ts: Sequence[int], o: Sequence[float], c: Sequence[float], day: Sequence[str],
          cost_bps: float = COST_BPS, funding_year: float = FUNDING_YEAR) -> Dict[str, Tuple[float, float, float]]:
    """{week: (gross, net, hours held)}: bought at the close of the week's first trading day, sold at the open of
    its last."""
    out = {}
    for w, (a, b) in windows(day).items():
        if not (c[a] > 0 and o[b] > 0):
            continue
        hours = (ts[b] - (ts[a] + SESSION_S)) / 3600
        gross = o[b] / c[a] - 1
        out[w] = (gross, gross - 2 * cost_bps / 1e4 - funding_year * hours / HOURS_YEAR, hours)
    return out


def market_weeks(o: Sequence[float], c: Sequence[float], day: Sequence[str]) -> Dict[str, float]:
    """{week: the gross return from the first trading day's close to the last's open} for the benchmark."""
    return {w: o[b] / c[a] - 1 for w, (a, b) in windows(day).items() if c[a] > 0 and o[b] > 0}


def profit_factor(values: Sequence[float]) -> Optional[float]:
    won = sum(v for v in values if v > 0)
    lost = -sum(v for v in values if v < 0)
    return won / lost if lost > 0 else None


def breadth(per_market: Mapping[str, Mapping[str, float]]) -> Tuple[int, int]:
    """(markets with a mean net week above zero, markets with 100 weeks or more)."""
    counted = [list(v.values()) for v in per_market.values() if len(v) >= MIN_MARKET_WEEKS]
    return sum(1 for v in counted if sum(v) / len(v) > 0), len(counted)


def verdict(n: int, pf: Optional[float], mean: float, t: Optional[float], q: Optional[float], market: float,
            h1: float, h2: float, up: int, counted: int) -> Tuple[str, List[str]]:
    if n < MIN_WEEKS:
        return "INCONCLUSIVE", [f"{n} weeks, under {MIN_WEEKS}"]
    missed = []
    if pf is None or pf < MIN_PF:
        missed.append(f"1: profit factor {pf if pf is None else round(pf, 3)} under {MIN_PF}")
    if not (mean > 0 and t is not None and t >= MIN_T and q is not None and q < MAX_Q):
        missed.append(f"2: mean {mean:.6f}, t {t}, q {q} (need mean > 0, t >= {MIN_T}, q < {MAX_Q})")
    if not mean > market:
        missed.append(f"3: the net week {mean:.6f} not above the market's {market:.6f}")
    if not (h1 > 0 and h2 > 0):
        missed.append(f"4: halves {h1:+.6f} / {h2:+.6f}")
    if not (counted and up * 2 > counted):
        missed.append(f"5: {up} of {counted} markets above zero")
    return ("PASS" if not missed else "FAIL"), missed
