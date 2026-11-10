"""#80: the funding spread between trade.xyz's markets, short the payers and long the payees
(research/PREREGISTRATION_FUNDSPREAD.md).

The frozen rule and its criteria, pure: funding rows and prices in, weekly returns and a verdict out, no I/O.
research/fundspread.py fetches and prints. The numbers below are the pre-registration's.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Dict, List, Mapping, Optional, Sequence, Tuple

import numpy as np

WEEK_S = 7 * 86_400
MIN_ROWS = 144                  # hourly funding rows needed in the 168 before a Monday
MIN_MARKETS = 9
COST_BPS = 14.0                 # per unit of capital traded
MIN_PF = 1.5
MIN_T = 3.0
MAX_Q = 0.05
MAX_RANDOM_SHARE = 0.05
RANDOM_DRAWS = 2000
RANDOM_SEED = 0
MIN_WEEKS = 40

Funding = Mapping[str, Tuple[Sequence[int], Sequence[float]]]      # market -> (row times in s, hourly rates)
Prices = Mapping[str, Mapping[int, float]]                         # market -> {candle start in s: open}


@dataclass(frozen=True)
class Week:
    t: int
    n: int                       # eligible markets
    long: Tuple[str, ...]
    short: Tuple[str, ...]
    price: float                 # the price component of the gross return
    fund: float                  # the funding component
    gross: float
    turnover: float
    net: float


def signal(times: Sequence[int], rates: Sequence[float], t: int) -> Optional[float]:
    """The mean hourly rate over [t - a week, t), None with fewer than MIN_ROWS rows there."""
    inside = [r for ts, r in zip(times, rates) if t - WEEK_S <= ts < t]
    return sum(inside) / len(inside) if len(inside) >= MIN_ROWS else None


def settled(times: Sequence[int], rates: Sequence[float], t: int) -> float:
    """The sum of the hourly rates settled in [t, t + a week): what a long pays and a short receives."""
    return sum(r for ts, r in zip(times, rates) if t <= ts < t + WEEK_S)


def split(signals: Mapping[str, float]) -> Optional[Tuple[Tuple[str, ...], Tuple[str, ...]]]:
    """(long, short): the k lowest and the k highest signals, k = n // 3, ties by name; None below MIN_MARKETS."""
    n = len(signals)
    if n < MIN_MARKETS:
        return None
    k = n // 3
    ranked = sorted(signals, key=lambda m: (signals[m], m))
    return tuple(ranked[:k]), tuple(ranked[-k:])


def weights(long: Sequence[str], short: Sequence[str]) -> Dict[str, float]:
    """Each leg half the capital, equal weight inside it."""
    w = {m: 0.5 / len(long) for m in long}
    w.update({m: -0.5 / len(short) for m in short})
    return w


def turnover(prev: Mapping[str, float], new: Mapping[str, float]) -> float:
    return sum(abs(new.get(m, 0.0) - prev.get(m, 0.0)) for m in set(prev) | set(new))


def gross_parts(long: Sequence[str], short: Sequence[str], p0: Mapping[str, float], p1: Mapping[str, float],
                fund: Mapping[str, float]) -> Tuple[float, float]:
    """(price component, funding component) of the week on capital: half the long leg's mean price return minus the
    short leg's, and half the short leg's mean funding paid minus the long leg's."""
    ret = {m: p1[m] / p0[m] - 1 for m in list(long) + list(short)}
    price = 0.5 * (sum(ret[m] for m in long) / len(long) - sum(ret[m] for m in short) / len(short))
    pay = 0.5 * (sum(fund[m] for m in short) / len(short) - sum(fund[m] for m in long) / len(long))
    return price, pay


def eligible(funding: Funding, prices: Prices, t: int, skip: Optional[str] = None) -> Dict[str, float]:
    """{market: signal} for markets with a candle at t and at t + a week and enough funding rows."""
    out = {}
    for m, (ts, rs) in funding.items():
        if m == skip or t not in prices.get(m, {}) or t + WEEK_S not in prices.get(m, {}):
            continue
        s = signal(ts, rs, t)
        if s is not None:
            out[m] = s
    return out


def run(funding: Funding, prices: Prices, mondays: Sequence[int], cost_bps: float = COST_BPS,
        skip: Optional[str] = None) -> List[Week]:
    """The registered weekly rule over `mondays`, in order. A week with too few markets takes no position, and the
    next one trades the whole book again."""
    out: List[Week] = []
    prev: Dict[str, float] = {}
    for t in mondays:
        sig = eligible(funding, prices, t, skip)
        legs = split(sig)
        if legs is None:
            prev = {}
            continue
        long, short = legs
        p0 = {m: prices[m][t] for m in sig}
        p1 = {m: prices[m][t + WEEK_S] for m in sig}
        fund = {m: settled(*funding[m], t) for m in sig}
        price, pay = gross_parts(long, short, p0, p1, fund)
        w = weights(long, short)
        trade = turnover(prev, w)
        out.append(Week(t, len(sig), long, short, price, pay, price + pay, trade, price + pay - trade * cost_bps / 1e4))
        prev = w
    return out


def random_means(funding: Funding, prices: Prices, weeks: Sequence[Week], draws: int = RANDOM_DRAWS,
                 seed: int = RANDOM_SEED) -> np.ndarray:
    """Each draw assigns every week's eligible markets to same-size legs at random; the value is the mean gross."""
    rng = np.random.default_rng(seed)
    cases = []
    for wk in weeks:
        sig = eligible(funding, prices, wk.t)
        ms = sorted(sig)
        p0 = {m: prices[m][wk.t] for m in ms}
        p1 = {m: prices[m][wk.t + WEEK_S] for m in ms}
        fund = {m: settled(*funding[m], wk.t) for m in ms}
        cases.append((ms, len(wk.long), p0, p1, fund))
    out = np.empty(draws)
    for d in range(draws):
        total = 0.0
        for ms, k, p0, p1, fund in cases:
            order = rng.permutation(len(ms))
            long = [ms[i] for i in order[:k]]
            short = [ms[i] for i in order[k:2 * k]]
            a, b = gross_parts(long, short, p0, p1, fund)
            total += a + b
        out[d] = total / len(cases) if cases else float("nan")
    return out


def share_at_or_above(real: float, means: np.ndarray) -> float:
    m = means[~np.isnan(means)]
    return float(np.mean(m >= real)) if len(m) else 1.0


def profit_factor(values: Sequence[float]) -> Optional[float]:
    won = sum(v for v in values if v > 0)
    lost = -sum(v for v in values if v < 0)
    return won / lost if lost > 0 else None


def halves(values: Sequence[float]) -> Tuple[float, float]:
    k = (len(values) + 1) // 2
    a, b = list(values[:k]), list(values[k:])
    return (sum(a) / len(a) if a else float("nan")), (sum(b) / len(b) if b else float("nan"))


def two_sided_p(t: float) -> float:
    return math.erfc(abs(t) / math.sqrt(2))


def verdict(n: int, pf: Optional[float], mean: float, t: Optional[float], q: Optional[float], share: float,
            h1: float, h2: float, loo_min: float) -> Tuple[str, List[str]]:
    """`loo_min` is the smallest mean weekly net return over the leave-one-market-out re-runs."""
    if n < MIN_WEEKS:
        return "INCONCLUSIVE", [f"{n} weeks, under {MIN_WEEKS}"]
    missed = []
    if pf is None or pf < MIN_PF:
        missed.append(f"1: profit factor {pf if pf is None else round(pf, 3)} under {MIN_PF}")
    if not (mean > 0 and t is not None and t >= MIN_T and q is not None and q < MAX_Q):
        missed.append(f"2: mean {mean:.6f}, t {t}, q {q} (need mean > 0, t >= {MIN_T}, q < {MAX_Q})")
    if not share < MAX_RANDOM_SHARE:
        missed.append(f"3: {share:.1%} of random assignments at or above it (need under {MAX_RANDOM_SHARE:.0%})")
    if not (h1 > 0 and h2 > 0):
        missed.append(f"4: halves {h1:+.6f} / {h2:+.6f}")
    if not loo_min > 0:
        missed.append(f"5: the mean falls to {loo_min:+.6f} with one market removed")
    return ("PASS" if not missed else "FAIL"), missed
