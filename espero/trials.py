"""Every test this project has run, counted against itself.

`deflated_sharpe` is Bailey & Lopez de Prado (2014): the probability a Sharpe beats the best of N
null trials. `spa` is Hansen's (2005) superior predictive ability test: can the best of k return
series be told from zero, allowing for having looked at k of them. `bh` and `holm` are the usual
multiple-test corrections on the p-values that exist.
"""
from __future__ import annotations

import math
from statistics import NormalDist
from typing import Dict, Sequence

import numpy as np
import pandas as pd

EULER = 0.5772156649015329
_N = NormalDist()


def expected_max_sharpe(n_trials: int, var_sharpe: float) -> float:
    """The Sharpe (per observation) the best of `n_trials` null trials reaches on average."""
    if n_trials < 2 or var_sharpe <= 0:
        return 0.0
    a = _N.inv_cdf(1 - 1 / n_trials)
    b = _N.inv_cdf(1 - 1 / (n_trials * math.e))
    return math.sqrt(var_sharpe) * ((1 - EULER) * a + EULER * b)


def psr(sharpe: float, benchmark: float, n_obs: int, skew: float = 0.0, kurt: float = 3.0) -> float:
    """Probabilistic Sharpe: P(true Sharpe > benchmark), both per observation."""
    if n_obs < 2:
        return float("nan")
    denom = 1 - skew * sharpe + (kurt - 1) / 4 * sharpe ** 2
    if denom <= 0:
        return float("nan")
    return _N.cdf((sharpe - benchmark) * math.sqrt(n_obs - 1) / math.sqrt(denom))


def deflated_sharpe(sharpe: float, n_obs: int, n_trials: int, var_sharpe: float, skew: float = 0.0,
                    kurt: float = 3.0) -> float:
    return psr(sharpe, expected_max_sharpe(n_trials, var_sharpe), n_obs, skew, kurt)


def holm(p: Sequence[float]) -> np.ndarray:
    """Holm-adjusted p-values, in the input order."""
    p = np.asarray(p, dtype=float)
    order = np.argsort(p)
    adj = np.empty(len(p))
    running = 0.0
    for rank, i in enumerate(order):
        running = max(running, min(1.0, (len(p) - rank) * p[i]))
        adj[i] = running
    return adj


def bh(p: Sequence[float]) -> np.ndarray:
    """Benjamini-Hochberg q-values, in the input order."""
    p = np.asarray(p, dtype=float)
    order = np.argsort(p)[::-1]
    q = np.empty(len(p))
    running = 1.0
    for rank, i in zip(range(len(p), 0, -1), order):
        running = min(running, p[i] * len(p) / rank)
        q[i] = running
    return q


def stationary_indices(rng: np.random.Generator, n: int, mean_block: float, draws: int) -> np.ndarray:
    """Politis-Romano stationary bootstrap indices, draws x n."""
    restart = rng.random((draws, n)) < 1 / mean_block
    restart[:, 0] = True
    fresh = rng.integers(0, n, size=(draws, n))
    idx = np.empty((draws, n), dtype=int)
    idx[:, 0] = fresh[:, 0]
    for t in range(1, n):
        idx[:, t] = np.where(restart[:, t], fresh[:, t], (idx[:, t - 1] + 1) % n)
    return idx


def spa(rng: np.random.Generator, returns: np.ndarray, mean_block: float = 10.0,
        draws: int = 2000) -> Dict[str, float]:
    """Hansen's consistent SPA p-value for H0: no column has a positive mean.

    `returns` is T x k, each column a strategy's return against a benchmark of zero, on a common
    calendar with no NaN. Columns far below zero are recentred away (the 2*loglog rule), so
    hopeless strategies do not make the best one look unremarkable.
    """
    d = np.asarray(returns, dtype=float)
    if np.isnan(d).any():
        raise ValueError("SPA needs a complete T x k panel")
    n, k = d.shape
    means = d.mean(axis=0)
    idx = stationary_indices(rng, n, mean_block, draws)
    boot = d[idx].mean(axis=1)                  # draws x k
    w = np.sqrt(n) * boot.std(axis=0)
    w[w == 0] = np.inf
    stat = max(0.0, float(np.max(np.sqrt(n) * means / w)))
    keep = np.sqrt(n) * means / w >= -math.sqrt(2 * math.log(math.log(max(n, 3))))
    g = means * keep
    z = np.sqrt(n) * (boot - g) / w
    t = np.maximum(z.max(axis=1), 0.0)
    return {"stat": stat, "p": float((t >= stat).mean()), "k": k, "n": n,
            "best": int(np.argmax(np.sqrt(n) * means / w)),
            "kept": int(keep.sum())}


def spend(trials: pd.DataFrame, alpha: float = 0.05) -> Dict[str, float]:
    """How fast the inventory spends its false-positive budget. `trials` needs `date` and `status`."""
    judged = trials[trials["status"].isin(["pass", "fail", "provisional", "exploratory"])]
    dates = pd.to_datetime(judged["date"].dropna())
    span = max((dates.max() - dates.min()).days + 1, 1) if len(dates) else 0
    n = len(judged)
    return {"tests_registered": len(trials), "tests_judged": n, "span_days": span,
            "tests_per_day": n / span if span else float("nan"),
            "expected_false_passes_at_alpha": n * alpha, "passes": int((judged["status"] == "pass").sum()),
            "bonferroni_alpha_per_test": alpha / n if n else float("nan"),
            "familywise_error_if_uncorrected": 1 - (1 - alpha) ** n}
