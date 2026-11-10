"""#75: buy the discount half of an hourly dealing range at its proximal line (research/PREREGISTRATION_DEALRANGE.md).

The frozen rule and its criteria, pure: bars in, trades and a verdict out, no I/O. research/dealrange.py fetches
and prints. The rule numbers below are the pre-registration's; none is to be tuned here.

Each bar is processed at its close, in the registered order: a resting order's fill first (rule 6), then the
cancels (rule 8), then the swings that become known on this bar, which cancel an older order and may arm a new one
(rules 1 to 5). Exits are `espero.brackets`, with the fill inside a bar (`simulate_limit`).
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Dict, List, Optional, Sequence, Tuple

import pandas as pd

from . import brackets as B
from .indicators import atr as atr_

SWING = 5                    # bars each side, strictly beyond
PROX_BACK = 10               # bars searched back from the swing low for the last down bar
STOP_ATR = 0.1               # the stop sits this many ATRs under the range low
ATR_PERIOD = 14
COST_BPS = 14.0              # every fill: trade.xyz's taker fee out of growth mode (9) + slippage (5)
BRACKET = B.Bracket(targets=((1.5, 0.5), (2.8, 0.5)), breakeven_after=1, cost_bps=COST_BPS)

MIN_PF = 1.5
MIN_T = 3.0
MAX_Q = 0.05
MAX_RANDOM_SHARE = 0.05
RANDOM_DRAWS = 2000
RANDOM_SEED = 0
MIN_TRADES = 100
MIN_MARKET_TRADES = 5


def swing_low(low: Sequence[float], j: int, k: int = SWING) -> bool:
    """Bar j's low is strictly below the k lows on each side; needs bars j-k to j+k."""
    if j - k < 0 or j + k >= len(low):
        return False
    return all(low[j] < low[x] for x in range(j - k, j + k + 1) if x != j)


def swing_high(high: Sequence[float], j: int, k: int = SWING) -> bool:
    if j - k < 0 or j + k >= len(high):
        return False
    return all(high[j] > high[x] for x in range(j - k, j + k + 1) if x != j)


def proximal(o: Sequence[float], h: Sequence[float], c: Sequence[float], low_bar: int,
             back: int = PROX_BACK) -> Optional[float]:
    """The high of the last bar at or before `low_bar`, at most `back` bars back, that closed below its open."""
    for k in range(low_bar, max(-1, low_bar - back - 1), -1):
        if c[k] < o[k]:
            return float(h[k])
    return None


@dataclass(frozen=True)
class Order:
    armed_i: int
    line: float                 # the proximal line: the resting buy's price
    stop: float
    range_low: float
    range_high: float


def orders_and_trades(o: Sequence[float], h: Sequence[float], low: Sequence[float], c: Sequence[float],
                      day: Optional[Sequence] = None, b: B.Bracket = BRACKET) -> Tuple[List[Order], List[B.Trade]]:
    """Every order armed, and every trade filled, on one market's bars, as registered."""
    n = len(o)
    atr = atr_(pd.DataFrame({"high": h, "low": low, "close": c})).to_numpy()
    orders: List[Order] = []
    trades: List[B.Trade] = []
    pending: Optional[Order] = None
    busy_until = -1
    last_low: Optional[int] = None                       # the latest known swing low's bar
    for i in range(n):
        if pending is not None and i > pending.armed_i and low[i] < pending.line:          # rule 6: fill first
            if i > busy_until:                                                          # rule 9
                t = B.simulate_limit(o, h, low, c, i, pending.line, 1, pending.line - pending.stop, b, day,
                                     signal_i=pending.armed_i)
                trades.append(t)
                busy_until = t.exit_i
            pending = None
        if pending is not None and c[i] < pending.range_low:                                # rule 8
            pending = None
        j = i - SWING
        new_low, new_high = swing_low(low, j), swing_high(h, j)
        if (new_low or new_high) and pending is not None:                                   # rule 8: a later swing
            pending = None
        if new_low:
            last_low = j
        if new_high and last_low is not None and last_low < j:                              # rule 2
            line = proximal(o, h, c, last_low)                                              # rule 3
            if line is not None and not math.isnan(atr[i]):
                rlow, rhigh = float(low[last_low]), float(h[j])
                stop = rlow - STOP_ATR * float(atr[i])                                     # rule 5
                if line < (rlow + rhigh) / 2 and line > stop and c[i] > line:              # rule 4
                    pending = Order(i, line, stop, rlow, rhigh)
                    orders.append(pending)
    return orders, trades                                                                # rule 10: pending dropped


def clustered_t(rs: Sequence[float], days: Sequence) -> Tuple[Optional[float], int]:
    """The mean R's t, its standard error clustered by entry day; and the number of days."""
    n = len(rs)
    if n < 2:
        return None, len(set(days))
    mean = sum(rs) / n
    sums: Dict[object, float] = {}
    for r, d in zip(rs, days):
        sums[d] = sums.get(d, 0.0) + (r - mean)
    g = len(sums)
    if g < 2:
        return None, g
    var = sum(s * s for s in sums.values()) / (n * n) * g / (g - 1)
    return (mean / math.sqrt(var) if var > 0 else None), g


def two_sided_p(t: float, days: int) -> float:
    """Normal with more than 100 entry days, Student's t with days - 1 degrees of freedom otherwise."""
    if days > 100:
        return math.erfc(abs(t) / math.sqrt(2))
    v = days - 1
    return _betainc(v / 2, 0.5, v / (v + t * t))


def _betainc(a: float, b: float, x: float) -> float:
    """The regularized incomplete beta I_x(a, b), by its continued fraction (Lentz); I_x(v/2, 1/2) at
    x = v / (v + t^2) is Student's two-sided tail."""
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


def halves(rs: Sequence[float]) -> Tuple[float, float]:
    """Mean R of each half in entry order, the earlier half taking the odd one."""
    k = (len(rs) + 1) // 2
    a, b = rs[:k], rs[k:]
    return (sum(a) / len(a) if a else float("nan")), (sum(b) / len(b) if b else float("nan"))


def breadth(by_market: Dict[str, Sequence[float]]) -> Tuple[int, int]:
    """(markets with a mean R above zero, markets with at least 5 trades)."""
    counted = [rs for rs in by_market.values() if len(rs) >= MIN_MARKET_TRADES]
    return sum(1 for rs in counted if sum(rs) / len(rs) > 0), len(counted)


def verdict(n: int, pf: Optional[float], mean: Optional[float], t: Optional[float], q: Optional[float],
            random_share: float, h1: float, h2: float, up: int, counted: int) -> Tuple[str, List[str]]:
    """PASS, FAIL or INCONCLUSIVE, and every criterion missed."""
    if n < MIN_TRADES:
        return "INCONCLUSIVE", [f"{n} trades, under {MIN_TRADES}"]
    missed = []
    if pf is None or pf < MIN_PF:
        missed.append(f"1: profit factor {pf if pf is None else round(pf, 3)} under {MIN_PF}")
    if mean is None or mean <= 0 or t is None or t < MIN_T or q is None or q >= MAX_Q:
        missed.append(f"2: mean {mean}, t {t}, q {q} (need mean > 0, t >= {MIN_T}, q < {MAX_Q})")
    if not random_share < MAX_RANDOM_SHARE:
        missed.append(f"3: {random_share:.1%} of random draws at or above it (need under {MAX_RANDOM_SHARE:.0%})")
    if not (h1 > 0 and h2 > 0):
        missed.append(f"4: halves {h1:+.3f} / {h2:+.3f}")
    if not (counted and up * 2 > counted):
        missed.append(f"5: {up} of {counted} markets above zero")
    return ("PASS" if not missed else "FAIL"), missed
