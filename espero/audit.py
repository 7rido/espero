"""Two ways to summarise an event study, and which one a book earns (#44,
research/PREREGISTRATION_DAYMEAN_AUDIT.md).

* `day_mean`: the mean of each day's mean, t over days. This repo's convention
  through #43. It gives a lone event on a quiet day the weight of a crowded day,
  and that weight depends on events later the same day: not something a book can hold.
* `trade_weighted`: the mean over events, t with the standard error clustered by
  day. What a book taking every event earns, with honest errors.
* `diff_trade_weighted`: forced − organic as an OLS slope on a dummy, day-clustered.
"""
from __future__ import annotations

import math
from typing import Dict

import numpy as np
import pandas as pd


def day_mean(x: pd.Series, day: pd.Series) -> Dict[str, float]:
    ok = np.isfinite(x)
    g = x[ok].groupby(day[ok]).mean()
    n = int(g.size)
    sd = float(g.std(ddof=1)) if n > 1 else math.nan
    m = float(g.mean()) if n else math.nan
    return {"mean": m, "t": m / (sd / math.sqrt(n)) if n > 1 and sd > 0 else math.nan, "days": n}


def trade_weighted(x: pd.Series, day: pd.Series) -> Dict[str, float]:
    ok = np.isfinite(x)
    x, day = x[ok].astype(float), day[ok]
    n, G = int(x.size), int(day.nunique())
    if n < 2 or G < 2:
        return {"mean": math.nan, "t": math.nan, "n": n, "days": G}
    m = float(x.mean())
    s = (x - m).groupby(day).sum().to_numpy()
    se = math.sqrt(G / (G - 1)) * math.sqrt(float(s @ s)) / n
    return {"mean": m, "t": m / se if se > 0 else math.nan, "n": n, "days": G}


def diff_trade_weighted(y: pd.Series, forced: pd.Series, day: pd.Series) -> Dict[str, float]:
    """Slope b of y = a + b * forced, each event weighted equally, errors clustered by day."""
    ok = np.isfinite(y)
    y, f, day = y[ok].astype(float).to_numpy(), forced[ok].astype(float).to_numpy(), day[ok].to_numpy()
    X = np.column_stack([np.ones_like(f), f])
    xtx_inv = np.linalg.inv(X.T @ X)
    beta = xtx_inv @ X.T @ y
    u = y - X @ beta
    meat = np.zeros((2, 2))
    groups = pd.Series(np.arange(len(y))).groupby(day).indices
    for idx in groups.values():
        s = X[idx].T @ u[idx]
        meat += np.outer(s, s)
    G, n = len(groups), len(y)
    cov = xtx_inv @ meat @ xtx_inv * (G / (G - 1)) * ((n - 1) / (n - 2))
    se = math.sqrt(cov[1, 1])
    return {"mean": float(beta[1]), "t": float(beta[1] / se) if se > 0 else math.nan, "n": n, "days": G}


def quiet_share(day: pd.Series, k: int = 3) -> float:
    """Share of the day-mean's total weight on days with at most k events."""
    size = day.value_counts()
    return float((size <= k).mean()) if len(size) else math.nan


def meets(stat: Dict[str, float], mean_rule, t_rule) -> bool:
    return bool(np.isfinite(stat["mean"]) and np.isfinite(stat["t"]) and mean_rule(stat["mean"]) and t_rule(stat["t"]))


def changed(a: Dict[str, float], b: Dict[str, float], mean_rule, t_rule) -> bool:
    """#44's rule: the sign flips, or the study's own bar is met under one and not the other."""
    flip = np.sign(a["mean"]) != np.sign(b["mean"])
    return bool(flip or meets(a, mean_rule, t_rule) != meets(b, mean_rule, t_rule))


def trade_weighted_nw(x: pd.Series, day: pd.Series, lags: int = 1) -> Dict[str, float]:
    """Trade-weighted mean whose t lets the day-clustered residual sums correlate across
    neighbouring days (Newey-West, Bartlett weights): for holds that run past midnight."""
    ok = np.isfinite(x)
    x, day = x[ok].astype(float), day[ok]
    n = int(x.size)
    if n < 2 or day.nunique() < 2:
        return {"mean": math.nan, "t": math.nan, "n": n, "days": int(day.nunique())}
    m = float(x.mean())
    s = (x - m).groupby(day).sum().sort_index()
    idx = pd.to_datetime(pd.Series(s.index))
    full = pd.Series(s.to_numpy(), index=idx).reindex(pd.date_range(idx.min(), idx.max(), freq="D"), fill_value=0.0)
    v = full.to_numpy()
    G = int(len(s))
    lr = float(v @ v)
    for lag in range(1, lags + 1):
        lr += 2 * (1 - lag / (lags + 1)) * float(v[lag:] @ v[:-lag])
    se = math.sqrt(max(lr, 0.0) * G / (G - 1)) / n
    return {"mean": m, "t": m / se if se > 0 else math.nan, "n": n, "days": G}
