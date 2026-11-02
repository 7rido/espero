"""#63: the portfolio layer, how passes combine, fixed before any two exist (research/PREREGISTRATION_SLEEVES.md).

Pure: the sleeves' daily net returns in, correlations, vol-target weights and drawdown states out. It reads
no ledger: research/sleeves.py will, once, at the family's judgment after 2027-03-31. The numbers here are
the pre-registration's and are not re-tuned.
"""
from __future__ import annotations

import math
from typing import Dict, List, Optional, Sequence, Tuple

import numpy as np
import pandas as pd

from . import portfolio

VOL_TARGET = 0.10
VOL_WINDOW = 90
MIN_DAYS_FOR_WINDOW = 60
GROSS_CAP = 1.0
SLEEVE_CAP = 1.0
CORR_ONE_SOURCE = 0.5
DD_HALVE, DD_FLAT, DD_RECOVER = -0.10, -0.20, -0.05
PERIODS = 365
CLUSTERS = ({"27", "32", "45"}, {"22", "24", "31"}, {"58", "59"})


def cluster_of(test: str) -> frozenset:
    for c in CLUSTERS:
        if test in c:
            return frozenset(c)
    return frozenset({test})


def sleeves_from_passes(passes: Dict[str, float]) -> Dict[str, List[str]]:
    """Passes {test: main-criterion t} -> sleeves {representative test: members}; a cluster is one sleeve,
    represented by its member with the largest t."""
    groups: Dict[frozenset, List[str]] = {}
    for t in passes:
        groups.setdefault(cluster_of(t), []).append(t)
    out = {}
    for members in groups.values():
        rep = max(members, key=lambda m: (passes[m], m))
        out[rep] = sorted(members)
    return out


def correlations(returns: pd.DataFrame) -> pd.DataFrame:
    """Pairwise Pearson correlation of the sleeves' daily returns (a day a sleeve did not trade is 0 and
    counted), with the day count; long form: a, b, corr, days."""
    r = returns.fillna(0.0)
    rows = []
    cols = list(r.columns)
    for i, a in enumerate(cols):
        for b in cols[i + 1:]:
            both = r[[a, b]]
            c = float(both[a].corr(both[b])) if len(both) > 2 and both[a].std() > 0 and both[b].std() > 0 else float("nan")
            rows.append({"a": a, "b": b, "corr": c, "days": int(len(both))})
    return pd.DataFrame(rows, columns=["a", "b", "corr", "days"])


def one_source_pairs(corr: pd.DataFrame, threshold: float = CORR_ONE_SOURCE) -> List[Tuple[str, str]]:
    return [(r["a"], r["b"]) for _, r in corr.iterrows() if math.isfinite(r["corr"]) and r["corr"] > threshold]


def sleeve_vol(returns: pd.Series, window: int = VOL_WINDOW, min_days: int = MIN_DAYS_FOR_WINDOW,
               periods: int = PERIODS) -> float:
    """Trailing annualised volatility of a sleeve's daily net returns (in return units, not bps); the whole
    series when it is shorter than `min_days`."""
    r = returns.dropna()
    if len(r) < 2:
        return float("nan")
    use = r.iloc[-window:] if len(r) >= min_days else r
    return float(use.std(ddof=1) * math.sqrt(periods))


def vol_target_weights(returns: pd.DataFrame, t_values: Dict[str, float], target: float = VOL_TARGET,
                       gross_cap: float = GROSS_CAP, sleeve_cap: float = SLEEVE_CAP) -> pd.Series:
    """Each sleeve at target / realised vol, capped at `sleeve_cap`; a pair above the one-source
    correlation shares one sleeve's weight (the larger-t member keeps it); the book scaled down pro rata to
    `gross_cap` when the sum would exceed it."""
    vols = pd.Series({c: sleeve_vol(returns[c]) for c in returns.columns})
    w = portfolio.vol_scaled(pd.Series(1.0, index=returns.columns), vols, target=target, max_gross=float("inf"),
                             max_scale=sleeve_cap)
    for a, b in one_source_pairs(correlations(returns)):
        loser = a if (t_values.get(a, 0.0), a) < (t_values.get(b, 0.0), b) else b
        w[loser] = 0.0
    gross = float(w.abs().sum())
    if gross > gross_cap:
        w = w * gross_cap / gross
    return w


def drawdown_state(equity: Sequence[float]) -> Dict[str, object]:
    """The sleeve's (or book's) state on its last day from its own peak: 'full', 'half' or 'flat', with the
    drawdown now and at its worst. 'flat' is absorbing: once hit, it stays until a new pre-registration."""
    e = np.asarray(equity, dtype=float)
    if len(e) == 0 or not np.isfinite(e).all() or e[0] <= 0:
        return {"state": "full", "drawdown": 0.0, "max_drawdown": 0.0}
    peak = np.maximum.accumulate(e)
    dd = e / peak - 1.0
    state = "full"
    for d in dd:
        if d <= DD_FLAT:
            state = "flat"
            break
        if state == "full" and d <= DD_HALVE:
            state = "half"
        elif state == "half" and d >= DD_RECOVER:
            state = "full"
    return {"state": state, "drawdown": float(dd[-1]), "max_drawdown": float(dd.min())}


def scale_of(state: str) -> float:
    return {"full": 1.0, "half": 0.5, "flat": 0.0}[state]


def combine(returns: pd.DataFrame, weights: pd.Series) -> pd.Series:
    """The book's daily return at fixed weights (a day a sleeve did not trade contributes 0)."""
    r = returns.fillna(0.0)
    return (r * weights.reindex(r.columns).fillna(0.0)).sum(axis=1)


def summary(returns: pd.DataFrame, t_values: Dict[str, float]) -> Dict[str, object]:
    """Everything RESULTS_SLEEVES.md records, from the sleeves' daily net returns (return units)."""
    corr = correlations(returns)
    w = vol_target_weights(returns, t_values)
    states = {c: drawdown_state((1.0 + returns[c].fillna(0.0)).cumprod().to_numpy()) for c in returns.columns}
    scaled = pd.Series({c: w[c] * scale_of(states[c]["state"]) for c in returns.columns})
    book = combine(returns, scaled)
    equity = (1.0 + book).cumprod()
    return {"weights": w.to_dict(), "scaled_weights": scaled.to_dict(), "gross": float(scaled.abs().sum()),
            "correlations": corr, "one_source": one_source_pairs(corr), "drawdown": states,
            "book": {"days": int(len(book)), "net_return": float(equity.iloc[-1] - 1.0) if len(equity) else float("nan"),
                     "vol": float(book.std(ddof=1) * math.sqrt(PERIODS)) if len(book) > 1 else float("nan"),
                     "max_drawdown": drawdown_state(equity.to_numpy())["max_drawdown"],
                     "state": drawdown_state(equity.to_numpy())["state"]}}


def rule():
    """The registered rule is `summary`; this name is what the scaffold's test looks for."""
    return summary
