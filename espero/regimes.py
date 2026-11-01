"""Regime research: the lean gate that runs before a candidate is counted (research/REGIME_CANDIDATES.md).

Both candidates need the rating to lean against last week's move. In each walk-forward fold this takes the
correlation between the test rows' P(up) and their `r7` feature. It reads no test-row outcome, skill or regime
label, and it places nothing.
"""
from __future__ import annotations

from typing import Dict, List

import numpy as np
import pandas as pd

from . import rate as rt
from .factor_eval import purged_walk_forward

HORIZON = 7
MIN_NEGATIVE = 5                # of the rating's 6 folds, set before running


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
