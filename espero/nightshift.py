"""#76: the night shift, the stock perps held from the official close to the next official open
(research/PREREGISTRATION_NIGHTSHIFT.md).

The frozen rule and its criteria, pure: daily bars in, nightly returns and a verdict out, no I/O.
research/nightshift.py fetches and prints. The numbers below are the pre-registration's.
"""
from __future__ import annotations

import math
from typing import Dict, List, Mapping, Optional, Sequence, Tuple

import pandas as pd

COST_BPS = 14.0                  # a fill: trade.xyz's taker fee out of growth mode (9) + slippage at the bell (5)
FUNDING_YEAR = 0.10              # a long pays this a year, pro rata for the hours held
SESSION_S = 6.5 * 3600           # the official close is 6.5 hours after the 09:30 open
HOURS_YEAR = 365 * 24
MIN_PF = 1.5
MIN_T = 3.0
MAX_Q = 0.05
MIN_NIGHTS = 500
MIN_MARKET_NIGHTS = 250


def nights(ts: Sequence[int], o: Sequence[float], c: Sequence[float], day: Sequence[str],
           cost_bps: float = COST_BPS, funding_year: float = FUNDING_YEAR) -> Dict[str, Tuple[float, float, float]]:
    """{the close's day: (gross, net, hours held)} for every close after the first bar and its next open."""
    out = {}
    for k in range(1, len(ts) - 1):
        if not (c[k] > 0 and o[k + 1] > 0):
            continue
        hours = (ts[k + 1] - (ts[k] + SESSION_S)) / 3600
        gross = o[k + 1] / c[k] - 1
        out[day[k]] = (gross, gross - 2 * cost_bps / 1e4 - funding_year * hours / HOURS_YEAR, hours)
    return out


def days(o: Sequence[float], c: Sequence[float], day: Sequence[str], cost_bps: float = COST_BPS,
         funding_year: float = FUNDING_YEAR) -> Dict[str, Tuple[float, float]]:
    """{day: (gross, net)} held from the official open to the official close, for every bar after the first."""
    out = {}
    for k in range(1, len(o)):
        if not (o[k] > 0 and c[k] > 0):
            continue
        gross = c[k] / o[k] - 1
        out[day[k]] = (gross, gross - 2 * cost_bps / 1e4 - funding_year * (SESSION_S / 3600) / HOURS_YEAR)
    return out


def portfolio(per_market: Mapping[str, Mapping[str, float]]) -> pd.Series:
    """The equal-weight average across the markets that have a value that day, in date order."""
    frame = pd.DataFrame({m: pd.Series(v, dtype=float) for m, v in per_market.items()})
    return frame.sort_index().mean(axis=1, skipna=True).dropna()


def profit_factor(values: Sequence[float]) -> Optional[float]:
    won = sum(v for v in values if v > 0)
    lost = -sum(v for v in values if v < 0)
    return won / lost if lost > 0 else None


def halves(series: Sequence[float]) -> Tuple[float, float]:
    k = (len(series) + 1) // 2
    a, b = list(series[:k]), list(series[k:])
    return (sum(a) / len(a) if a else float("nan")), (sum(b) / len(b) if b else float("nan"))


def breadth(per_market: Mapping[str, Mapping[str, float]]) -> Tuple[int, int]:
    """(markets with a mean net night above zero, markets with 250 nights or more)."""
    counted = [list(v.values()) for v in per_market.values() if len(v) >= MIN_MARKET_NIGHTS]
    return sum(1 for v in counted if sum(v) / len(v) > 0), len(counted)


def two_sided_p(t: float) -> float:
    return math.erfc(abs(t) / math.sqrt(2))


def verdict(n: int, pf: Optional[float], mean: float, t: Optional[float], q: Optional[float], night: float,
            day: float, h1: float, h2: float, up: int, counted: int) -> Tuple[str, List[str]]:
    if n < MIN_NIGHTS:
        return "INCONCLUSIVE", [f"{n} nights, under {MIN_NIGHTS}"]
    missed = []
    if pf is None or pf < MIN_PF:
        missed.append(f"1: profit factor {pf if pf is None else round(pf, 3)} under {MIN_PF}")
    if not (mean > 0 and t is not None and t >= MIN_T and q is not None and q < MAX_Q):
        missed.append(f"2: mean {mean:.6f}, t {t}, q {q} (need mean > 0, t >= {MIN_T}, q < {MAX_Q})")
    if not night > day:
        missed.append(f"3: the night {night:.6f} not above the day {day:.6f}")
    if not (h1 > 0 and h2 > 0):
        missed.append(f"4: halves {h1:+.6f} / {h2:+.6f}")
    if not (counted and up * 2 > counted):
        missed.append(f"5: {up} of {counted} markets above zero")
    return ("PASS" if not missed else "FAIL"), missed
