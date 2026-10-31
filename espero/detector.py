"""Does the pipeline find what is there, and nothing when nothing is?

Synthetic markets with a known answer, run through the same rule, the same bootstrap and the same
attribution as the real book. Nothing here reads market data.

`synthetic_market` plants `alpha_ann` (log, per year) in whichever coin the rule holds, on top of
fat-tailed, vol-clustered returns with a common factor. With alpha 0 the rule has no edge by
construction, so any "detection" is a false positive. The truth for a path is alpha times the share
of its weeks in the market.

`attribution` is #48's number: the share of a book's realised shortfall against its benchmark
that execution accounts for.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, Tuple

import numpy as np

WEEKS_PER_YEAR = 365.25 / 7
LOOKBACK = 30
BLOCK_WEEKS = 8
SIGNAL_BELOW = 0.25
EXECUTION_ABOVE = 0.75


@dataclass(frozen=True)
class Book:
    gross: np.ndarray           # weekly log return of the book before costs
    bench: np.ndarray           # weekly log return of coin 0
    in_market: np.ndarray       # bool per week
    switches: np.ndarray        # legs traded per week


def synthetic_market(rng: np.random.Generator, weeks: int, alpha_ann: float = 0.0, coins: int = 9,
                     weekly_vol: float = 0.12, common: float = 0.6, df: float = 4.0) -> Book:
    """Daily returns under a one-coin weekly momentum rule (#2's rule: top 30-day return if > 0)."""
    days = weeks * 7 + LOOKBACK + 1
    daily_vol = weekly_vol / np.sqrt(7)
    shocks = rng.standard_t(df, size=(days, coins + 1)) / np.sqrt(df / (df - 2))
    # volatility clusters: a slow common multiplier, normalised to keep the target variance
    log_v = np.zeros(days)
    eta = rng.normal(0, 0.15, days)
    for i in range(1, days):
        log_v[i] = 0.97 * log_v[i - 1] + eta[i]
    mult = np.exp(log_v - log_v.mean())
    mult = mult / np.sqrt((mult ** 2).mean())
    ret = daily_vol * mult[:, None] * (np.sqrt(common) * shocks[:, [coins]] + np.sqrt(1 - common) * shocks[:, :coins])
    px = np.zeros((days, coins))
    px[0] = 0.0
    held: Optional[int] = None
    a_day = alpha_ann / 365.25
    gross, bench, in_mkt, legs = [], [], [], []
    week_gross, week_bench = 0.0, 0.0
    for d in range(1, days):
        at_decision = d > LOOKBACK and (d - LOOKBACK - 1) % 7 == 0
        if at_decision:
            if d > LOOKBACK + 1:
                gross.append(week_gross)
                bench.append(week_bench)
                in_mkt.append(held is not None)
            week_gross, week_bench = 0.0, 0.0
            mom = px[d - 1] - px[d - 1 - LOOKBACK]
            target = int(np.argmax(mom)) if mom.max() > 0 else None
            if d > LOOKBACK + 1 or target is not None:
                n = (held is not None and target != held) + (target is not None and target != held)
                legs.append(int(n))
            held = target
        r = ret[d].copy()
        if held is not None:
            r[held] += a_day
        px[d] = px[d - 1] + r
        if d > LOOKBACK:
            week_gross += r[held] if held is not None else 0.0
            week_bench += r[0]
    return Book(np.array(gross), np.array(bench), np.array(in_mkt), np.array(legs[: len(gross)]))


def block_indices(rng: np.random.Generator, n: int, block: int, draws: int) -> np.ndarray:
    """Moving-block resample indices, draws x n."""
    k = int(np.ceil(n / block))
    starts = rng.integers(0, max(n - block + 1, 1), size=(draws, k))
    idx = starts[:, :, None] + np.arange(block)[None, None, :]
    return idx.reshape(draws, -1)[:, :n] % n


def mean_ci(rng: np.random.Generator, x: np.ndarray, block: int = BLOCK_WEEKS, draws: int = 1000,
            level: float = 0.95) -> Tuple[float, float, float]:
    """Annualised mean of a weekly series with its moving-block percentile CI."""
    m = x[block_indices(rng, len(x), block, draws)].mean(axis=1) * WEEKS_PER_YEAR
    lo, hi = np.quantile(m, [(1 - level) / 2, (1 + level) / 2])
    return float(x.mean() * WEEKS_PER_YEAR), float(lo), float(hi)


def net_excess(book: Book, cost_per_leg: float) -> np.ndarray:
    """Weekly excess log return over the benchmark, after a fractional cost per leg."""
    return book.gross - book.switches * cost_per_leg - book.bench


def power_table(rng: np.random.Generator, alphas, weeks: int, paths: int, cost_per_leg: float = 0.001,
                draws: int = 300, **market) -> list:
    """For each planted alpha: how often the CI excludes zero, how often it covers the truth, and
    the average estimate. Alpha 0's rejection rate is the false-positive rate."""
    rows = []
    for a in alphas:
        hit_pos, hit_any, covered, est, truth = 0, 0, 0, [], []
        for _ in range(paths):
            b = synthetic_market(rng, weeks, a, **market)
            # the truth for this path: the alpha it was paid, minus what it paid to trade
            t = a * b.in_market.mean() - b.switches.mean() * cost_per_leg * WEEKS_PER_YEAR
            m, lo, hi = mean_ci(rng, net_excess(b, cost_per_leg), draws=draws)
            est.append(m)
            truth.append(t)
            hit_pos += lo > 0
            hit_any += (lo > 0) or (hi < 0)
            covered += lo <= t <= hi
        rows.append({"alpha_ann": a, "weeks": weeks, "paths": paths, "mean_estimate": float(np.mean(est)),
                     "mean_truth": float(np.mean(truth)), "detect_positive": hit_pos / paths,
                     "reject_any": hit_any / paths, "coverage_truth": covered / paths})
    return rows


@dataclass(frozen=True)
class Attribution:
    theta: float
    lo: float
    hi: float
    gross: float            # annualised log growth, before costs
    bench: float
    drag: float             # annualised log drag from execution
    shortfall: float        # bench - (gross - drag)
    verdict: str


def theta_of(gross: float, bench: float, drag: float) -> float:
    """Share of the shortfall execution explains; 1 when the book beat its benchmark before costs."""
    if gross >= bench:
        return 1.0 if drag > 0 else 0.0
    return drag / (bench - gross + drag)


def verdict_of(lo: float, hi: float) -> str:
    if hi <= SIGNAL_BELOW:
        return "signal"
    if lo >= EXECUTION_ABOVE:
        return "execution"
    return "cannot_separate"


def attribution(rng: np.random.Generator, gross_ann: float, bench_ann: float, leg_costs: np.ndarray, years: float,
                draws: int = 10_000, level: float = 0.95) -> Attribution:
    """#48's number. The failure already happened, so the realised path is a fact, not an estimate:
    `gross_ann` and `bench_ann` are held fixed and the CI resamples the legs' measured costs.

    `leg_costs` are fractions of notional. The drag is -sum(log(1 - c)) per year.
    """
    c = np.asarray(leg_costs, dtype=float)
    if np.isnan(c).any():
        raise ValueError("a leg with no measured cost: decide what it means before computing")
    per_leg = -np.log1p(-c)
    drag = float(per_leg.sum() / years)
    sample = per_leg[rng.integers(0, len(c), size=(draws, len(c)))].sum(axis=1) / years
    thetas = np.array([theta_of(gross_ann, bench_ann, d) for d in sample])
    lo, hi = np.quantile(thetas, [(1 - level) / 2, (1 + level) / 2])
    theta = theta_of(gross_ann, bench_ann, drag)
    return Attribution(theta, float(lo), float(hi), gross_ann, bench_ann, drag,
                       bench_ann - gross_ann + drag, verdict_of(float(lo), float(hi)))


def attribution_table(rng: np.random.Generator, cases, paths: int = 400, weeks: int = 147, legs: int = 133,
                      leg_sd: float = 0.0015) -> list:
    """Known shortfall splits: does the verdict come out right? Each case is (name, gross_gap_ann,
    mean_leg_cost); leg costs are drawn fat-tailed around that mean."""
    rows = []
    years = weeks / WEEKS_PER_YEAR
    for name, gap, mean_cost in cases:
        counts = {"signal": 0, "execution": 0, "cannot_separate": 0}
        cover, truth_sum = 0, 0.0
        for _ in range(paths):
            noise = rng.standard_t(4, legs) / np.sqrt(2)
            c = np.maximum(mean_cost + leg_sd * noise, -0.01)
            truth = theta_of(0.0, gap, -np.log1p(-mean_cost) * legs / years)
            a = attribution(rng, 0.0, gap, c, years, draws=1000)
            counts[a.verdict] += 1
            cover += a.lo <= truth <= a.hi
            truth_sum += truth
        rows.append({"case": name, "true_theta": truth_sum / paths, **{k: v / paths for k, v in counts.items()},
                     "coverage": cover / paths})
    return rows
