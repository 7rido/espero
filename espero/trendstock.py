"""#78: a daily breakout trend rule on the stock perps (research/PREREGISTRATION_TRENDSTOCK.md).

The frozen rule and its criteria, pure: daily bars in, trades and a verdict out, no I/O. research/trendstock.py
fetches and prints. The numbers below are the pre-registration's.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Dict, List, Mapping, Optional, Sequence, Tuple

import numpy as np

ENTRY_WINDOW = 100          # a close above the highest close of this many bars before it
EXIT_WINDOW = 50            # a close below the lowest close of this many bars before it
COST_BPS = 14.0             # a fill: trade.xyz's taker fee out of growth mode (9) + slippage (5)
FUNDING_YEAR = 0.10
MIN_PF = 1.5
MIN_T = 3.0
MAX_Q = 0.05
MAX_RANDOM_SHARE = 0.05
RANDOM_DRAWS = 2000
RANDOM_SEED = 0
MIN_TRADES = 100
MIN_MARKET_TRADES = 5


@dataclass(frozen=True)
class Trade:
    entry_i: int
    exit_i: int
    entry: float
    exit: float
    days: float          # calendar days from the entry open to the exit
    ret: float           # net of costs and funding
    end: bool            # still open at the end of the data


def net(entry: float, exit_: float, days: float, cost_bps: float = COST_BPS,
        funding_year: float = FUNDING_YEAR) -> float:
    return exit_ / entry - 1 - 2 * cost_bps / 1e4 - funding_year * days / 365


def trades(ts: Sequence[int], o: Sequence[float], c: Sequence[float], cost_bps: float = COST_BPS,
           funding_year: float = FUNDING_YEAR) -> List[Trade]:
    """Signals at a close fill at the next open; one position; the last bar's close if still held."""
    n = len(c)
    out: List[Trade] = []
    held: Optional[int] = None
    for i in range(ENTRY_WINDOW, n):
        if held is None:
            if c[i] > max(c[i - ENTRY_WINDOW:i]) and i + 1 < n:
                held = i + 1
        elif c[i] < min(c[i - EXIT_WINDOW:i]) and i + 1 < n:
            d = (ts[i + 1] - ts[held]) / 86400
            r = net(o[held], o[i + 1], d, cost_bps, funding_year)
            out.append(Trade(held, i + 1, o[held], o[i + 1], d, r, False))
            held = None
    if held is not None:
        d = (ts[n - 1] - ts[held]) / 86400
        out.append(Trade(held, n - 1, o[held], c[n - 1], d, net(o[held], c[n - 1], d, cost_bps, funding_year), True))
    return out


def profit_factor(values: Sequence[float]) -> Optional[float]:
    won = sum(v for v in values if v > 0)
    lost = -sum(v for v in values if v < 0)
    return won / lost if lost > 0 else None


def clustered_t(values: Sequence[float], groups: Sequence) -> Tuple[Optional[float], int]:
    """The mean's t with its standard error clustered by `groups` (the entry month); and the number of groups."""
    n = len(values)
    if n < 2:
        return None, len(set(groups))
    mean = sum(values) / n
    sums: Dict[object, float] = {}
    for v, g in zip(values, groups):
        sums[g] = sums.get(g, 0.0) + (v - mean)
    g = len(sums)
    if g < 2:
        return None, g
    var = sum(s * s for s in sums.values()) / (n * n) * g / (g - 1)
    return (mean / math.sqrt(var) if var > 0 else None), g


def two_sided_p(t: float, groups: int) -> float:
    """Normal above 100 clusters, Student's t with groups - 1 degrees of freedom otherwise."""
    if groups > 100:
        return math.erfc(abs(t) / math.sqrt(2))
    v = groups - 1
    return _betainc(v / 2, 0.5, v / (v + t * t))


def _betainc(a: float, b: float, x: float) -> float:
    """The regularized incomplete beta, by its continued fraction (Lentz)."""
    if x <= 0:
        return 0.0
    if x >= 1:
        return 1.0
    if x > (a + 1) / (a + b + 2):
        return 1.0 - _betainc(b, a, 1.0 - x)
    front = math.exp(math.lgamma(a + b) - math.lgamma(a) - math.lgamma(b) + a * math.log(x) + b * math.log(1 - x)) / a
    tiny = 1e-300
    f, cc, d = 1.0, 1.0, 0.0
    for i in range(400):
        m = i // 2
        if i == 0:
            num = 1.0
        elif i % 2 == 0:
            num = m * (b - m) * x / ((a + 2 * m - 1) * (a + 2 * m))
        else:
            num = -((a + m) * (a + b + m) * x) / ((a + 2 * m) * (a + 2 * m + 1))
        d = 1.0 + num * d
        d = 1.0 / (d if abs(d) > tiny else tiny)
        cc = 1.0 + num / cc
        cc = cc if abs(cc) > tiny else tiny
        f *= cc * d
        if abs(1.0 - cc * d) < 1e-14:
            break
    return front * (f - 1.0)


def random_means(markets: Sequence[Tuple[Sequence[int], Sequence[float], Sequence[float], Sequence[Trade]]],
                 draws: int = RANDOM_DRAWS, seed: int = RANDOM_SEED, cost_bps: float = COST_BPS,
                 funding_year: float = FUNDING_YEAR) -> np.ndarray:
    """Each draw replaces every real trade by one from a random bar on the same market held the same number of bars,
    opened at that bar's open and left at the open that many bars later (the last close at the end of the data);
    the draw's value is the mean net return. `markets` is (timestamps, opens, closes, trades) per market."""
    rng = np.random.default_rng(seed)
    out = np.empty(draws)
    for k in range(draws):
        rs = []
        for ts, o, c, trs in markets:
            n = len(c)
            for t in trs:
                length = t.exit_i - t.entry_i
                s = int(rng.integers(0, max(1, n - length)))
                e = s + length
                exit_ = float(c[e]) if e >= n - 1 and t.end else float(o[min(e, n - 1)])
                days = (ts[min(e, n - 1)] - ts[s]) / 86400
                rs.append(net(float(o[s]), exit_, days, cost_bps, funding_year))
        out[k] = sum(rs) / len(rs) if rs else float("nan")
    return out


def share_at_or_above(real_mean: float, means: np.ndarray) -> float:
    m = means[~np.isnan(means)]
    return float(np.mean(m >= real_mean)) if len(m) else 1.0


def halves(values: Sequence[float]) -> Tuple[float, float]:
    k = (len(values) + 1) // 2
    a, b = list(values[:k]), list(values[k:])
    return (sum(a) / len(a) if a else float("nan")), (sum(b) / len(b) if b else float("nan"))


def breadth(per_market: Mapping[str, Sequence[float]]) -> Tuple[int, int]:
    counted = [list(v) for v in per_market.values() if len(v) >= MIN_MARKET_TRADES]
    return sum(1 for v in counted if sum(v) / len(v) > 0), len(counted)


def verdict(n: int, pf: Optional[float], mean: float, t: Optional[float], q: Optional[float], share: float,
            h1: float, h2: float, up: int, counted: int) -> Tuple[str, List[str]]:
    if n < MIN_TRADES:
        return "INCONCLUSIVE", [f"{n} trades, under {MIN_TRADES}"]
    missed = []
    if pf is None or pf < MIN_PF:
        missed.append(f"1: profit factor {pf if pf is None else round(pf, 3)} under {MIN_PF}")
    if not (mean > 0 and t is not None and t >= MIN_T and q is not None and q < MAX_Q):
        missed.append(f"2: mean {mean:.6f}, t {t}, q {q} (need mean > 0, t >= {MIN_T}, q < {MAX_Q})")
    if not share < MAX_RANDOM_SHARE:
        missed.append(f"3: {share:.1%} of random draws at or above it (need under {MAX_RANDOM_SHARE:.0%})")
    if not (h1 > 0 and h2 > 0):
        missed.append(f"4: halves {h1:+.6f} / {h2:+.6f}")
    if not (counted and up * 2 > counted):
        missed.append(f"5: {up} of {counted} markets above zero")
    return ("PASS" if not missed else "FAIL"), missed
