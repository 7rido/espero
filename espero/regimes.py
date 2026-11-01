"""Regime research: the lean gate that runs before a candidate is counted (research/REGIME_CANDIDATES.md).

Both candidates need the rating to lean against last week's move. In each walk-forward fold this takes the
correlation between the test rows' P(up) and their `r7` feature. It reads no test-row outcome, skill or regime
label, and it places nothing.
"""
from __future__ import annotations

import math
from typing import Dict, List, Sequence

import numpy as np
import pandas as pd

from . import rate as rt
from .factor_eval import purged_walk_forward

HORIZON = 7
MIN_NEGATIVE = 5                # of the rating's 6 folds, set before running
FUNDING_SLOTS = 21              # seven days of 8-hour settlements
FUNDING_MIN = 18
FUNDING_BASELINE = 0.0001       # Binance's default rate, #32's line
TRAIN_FLOOR = 52                # also the least test dates a state needs in each half
POWER_FACTOR = 2.80 / 1.96      # 80% power at 95%


def panel(prices: Dict[str, pd.Series], kind: str, now: pd.Timestamp, h: int = HORIZON) -> pd.DataFrame:
    """The rating's rows, with every series cut before the frozen window first."""
    until = rt.readable_until(now)
    parts = [rt.rows(px[px.index < until], kind, h, now) for px in prices.values()]
    return pd.concat([p for p in parts if not p.empty]).sort_index()


def lean_by_fold(rows: pd.DataFrame, h: int = HORIZON) -> List[float]:
    """One correlation per fold, on the rating's own folds. Fitting uses training outcomes only."""
    dates = pd.DatetimeIndex(sorted(rows.index.unique()))
    features = list(rt.FEATURES)
    out = []
    for train, test in purged_walk_forward(dates, n_splits=rt.SPLITS, horizon=h, embargo=rt.EMBARGO,
                                           min_train=rt.MIN_TRAIN):
        a = rows[rows.index.isin(train)]
        b = rows[rows.index.isin(test)]
        if a.empty or b.empty:
            continue
        model = rt.fit(a[features].to_numpy(), a["y"].to_numpy())
        out.append(float(np.corrcoef(rt.predict(model, b[features].to_numpy()), b["r7"].to_numpy())[0, 1]))
    return out


def fades(correlations: List[float]) -> bool:
    """Open only if at least 5 folds lean against last week's move. A missing fold counts against it."""
    return sum(c < 0 for c in correlations) >= MIN_NEGATIVE


# ------------------------------------------------------------- labels, research/REGIME_DEFINITIONS.md
def volatility_states(px: pd.Series, kind: str) -> pd.Series:
    """low, mid or high against the thirds of all earlier values. A date with no cut-off yet has no label."""
    periods = rt.PERIODS[kind]
    v = np.log(px).diff().rolling(rt.VOL_ROWS, min_periods=rt.VOL_ROWS).std() * math.sqrt(periods)
    earlier = v.shift(1).expanding(min_periods=periods)
    low, high = earlier.quantile(1 / 3), earlier.quantile(2 / 3)
    out = pd.Series("mid", index=px.index, dtype=object)
    out[v <= low] = "low"
    out[v > high] = "high"
    return out.where(low.notna() & high.notna() & v.notna())


def funding_states(settlements: pd.Series) -> pd.Series:
    """Per day, from the last 21 slots through 16:00 on that day.

    Under 18 present: no label, since a gap stays a gap.
    """
    s = settlements.copy()
    s.index = s.index.floor("min")
    s = s[(s.index.hour % 8 == 0) & (s.index.minute == 0)]
    s = s[~s.index.duplicated(keep="last")].sort_index()
    grid = s.reindex(pd.date_range(s.index[0].normalize(), s.index[-1].normalize() + pd.Timedelta(hours=16), freq="8h"))
    f = grid.rolling(FUNDING_SLOTS, min_periods=FUNDING_MIN).mean()
    f = f[f.index.hour == 16]
    f.index = f.index.normalize()
    out = pd.Series("neutral", index=f.index, dtype=object)
    out[f < 0] = "crowded short"
    out[f > FUNDING_BASELINE] = "crowded long"
    return out.where(f.notna())


# ---------------------------------------------------------------------- the count, research/REGIME_POWER.md
def count_states(dates: pd.DatetimeIndex, labels: pd.Series, h: int = HORIZON) -> Dict[str, object]:
    """Dates per state on the rating's folds, from the date index alone.

    A fold under the training floor gives that state nothing.
    """
    dates = pd.DatetimeIndex(sorted(set(dates)))
    labels = labels.reindex(dates)
    folds = purged_walk_forward(dates, n_splits=rt.SPLITS, horizon=h, embargo=rt.EMBARGO, min_train=rt.MIN_TRAIN)
    tests = pd.DatetimeIndex([d for _, test in folds for d in test])
    middle = tests[len(tests) // 2]
    states: Dict[str, dict] = {s: {"test": 0, "first_half": 0, "second_half": 0, "train": [], "by_fold": []}
                               for s in sorted(labels.dropna().unique())}
    for train, test in folds:
        for s, row in states.items():
            n_train = int((labels.reindex(train) == s).sum())
            hit = test[labels.reindex(test) == s]
            eligible = n_train >= TRAIN_FLOOR
            row["train"].append(n_train)
            row["by_fold"].append(len(hit) if eligible else 0)
            if eligible:
                row["test"] += len(hit)
                row["first_half"] += int((hit < middle).sum())
                row["second_half"] += int((hit >= middle).sum())
    return {"dates": len(dates), "labelled": int(labels.notna().sum()), "unlabelled": int(labels.isna().sum()),
            "test_dates": len(tests), "unlabelled_test": int(labels.reindex(tests).isna().sum()), "states": states}


def verdict(counts: Dict[str, object], state: str, comparator: Sequence[str], skill: float, half_width: float) -> dict:
    """MDE against D from the committed bar.

    Open only if the history can detect D and each half has the floor's dates.
    """
    row = counts["states"].get(state, {"test": 0, "first_half": 0, "second_half": 0})
    total = counts["test_dates"]
    w = row["test"] / total
    c = sum(counts["states"].get(s, {"test": 0})["test"] for s in comparator) / total
    if w <= 0 or c <= 0 or w >= 1:
        return {"w": w, "c": c, "mde": math.inf, "d": 0.0, "halves": False, "open": False}
    mde = POWER_FACTOR * half_width * math.sqrt(1 / w + 1 / c)
    d = abs(skill) / (1 - w)
    halves = min(row["first_half"], row["second_half"]) >= TRAIN_FLOOR
    return {"w": w, "c": c, "mde": mde, "d": d, "halves": halves, "open": mde <= d and halves}
