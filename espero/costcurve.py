"""#68: a cost curve by order size on Hyperliquid, from #51's book files (research/PREREGISTRATION_COSTCURVE.md).

A measurement, pure: arrays in, numbers out, no I/O. The walk is #51's `espero.bookwalk.walk`,
unchanged. research/costcurve.py reads the book files, prints, and writes the generated table.

* `coin_day`: one coin-day's cost and unfillable share at every size, and its cost at $10,000 by
  four-hour UTC bucket
* `measured_sizes`: the sizes a coin's book can answer, from $500 up to the first that fails #51's rule
* `sqrt_fit`, `predict`: the two-parameter curve `c0 + k * sqrt(size / $10,000)` on design-day means
* `score`: the holdout error of the curve, of a flat cost and of a plain lookup, and the verdict
* `cost`: the curve from the generated table, refusing anything the table does not cover
"""
from __future__ import annotations

from typing import Dict, Iterable, List, Optional, Sequence, Tuple

import numpy as np
import pandas as pd

from .bookwalk import bootstrap_ci, walk

SIZES = (500, 1_000, 2_000, 5_000, 10_000, 20_000, 50_000, 100_000, 200_000, 500_000)
REFERENCE_USD = 10_000        # x = sqrt(size / REFERENCE_USD)
FLAT_USD = 1_000              # the size-free cost every frozen test assumes
PROFILE_USD = 10_000          # the hour-of-day readout's size
BUCKET_HOURS = 4
BUCKETS = 24 // BUCKET_HOURS
TOL_BPS = 0.5
UNFILLABLE_LIMIT = 0.05
MIN_DAYS = 10
MIN_SIZES = 3
MIN_SPLIT_DAYS = 5
BOOT_SEED = 68
# #51's validation gap, bps a leg, the book walk below real trades' effective half-spread (RESULTS_BOOKWALK.md)
FLOOR_GAP_BPS = {"BTC": 0.354, "ETH": 0.370, "SOL": 0.459, "XRP": 0.531, "DOGE": 0.562, "LINK": 0.518}
FLOOR_GAP_DEFAULT = max(FLOOR_GAP_BPS.values())
USABLE = ("FLAT IS ENOUGH", "CURVE HOLDS")


class NotMeasured(KeyError):
    pass


def _both(buy: np.ndarray, sell: np.ndarray) -> float:
    """#51's coin-day rule: each side's mean over fillable snapshots, then the mean of the two sides."""
    if np.isfinite(buy).any() and np.isfinite(sell).any():
        return float((np.nanmean(buy) + np.nanmean(sell)) / 2)
    return float("nan")


def coin_day(asks_px: np.ndarray, asks_qty: np.ndarray, bids_px: np.ndarray, bids_qty: np.ndarray,
             hours: np.ndarray, sizes: Sequence[int] = SIZES) -> Tuple[Dict[int, Dict[str, float]], Dict[int, float]]:
    """One coin-day: per size its cost and unfillable share; per four-hour bucket its cost at $10,000.
    Rows must already be valid snapshots; `hours` is each snapshot's UTC hour."""
    mid = (asks_px[:, 0] + bids_px[:, 0]) / 2
    by_size: Dict[int, Dict[str, float]] = {}
    buckets: Dict[int, float] = {}
    for usd in sizes:
        buy, sell = walk(asks_px, asks_qty, mid, usd, "buy"), walk(bids_px, bids_qty, mid, usd, "sell")
        unfillable = float((np.isnan(buy).mean() + np.isnan(sell).mean()) / 2)
        by_size[usd] = {"cost": _both(buy, sell), "unfillable": unfillable}
        if usd == PROFILE_USD:
            bucket = np.asarray(hours, int) // BUCKET_HOURS
            for b in range(BUCKETS):
                m = bucket == b
                buckets[b] = _both(buy[m], sell[m]) if m.any() else float("nan")
    return by_size, buckets


def measured_sizes(days: pd.DataFrame, coin: str, sizes: Sequence[int] = SIZES) -> List[int]:
    """The sizes a coin's book answers: from the smallest up to the first whose mean unfillable share is above
    5% or that has a cost on fewer than 10 days, over every day in `days` (rows coin, day, usd, cost, unfillable)."""
    g = days[days["coin"] == coin]
    out: List[int] = []
    for usd in sizes:
        s = g[g["usd"] == usd]
        if len(s) == 0 or s["unfillable"].mean() > UNFILLABLE_LIMIT or int(s["cost"].notna().sum()) < MIN_DAYS:
            break
        out.append(int(usd))
    return out


def sqrt_x(usd) -> np.ndarray:
    return np.sqrt(np.asarray(usd, float) / REFERENCE_USD)


def sqrt_fit(sizes: Sequence[int], costs: Sequence[float]) -> Tuple[float, float]:
    """(c0, k) by ordinary least squares of cost on a constant and sqrt(size / $10,000)."""
    x, y = sqrt_x(sizes), np.asarray(costs, float)
    if len(x) < 2 or not np.isfinite(y).all():
        return float("nan"), float("nan")
    k, c0 = np.polyfit(x, y, 1)
    return float(c0), float(k)


def predict(c0: float, k: float, usd) -> np.ndarray:
    return c0 + k * sqrt_x(usd)


def rmse(pred, actual) -> float:
    p, a = np.asarray(pred, float), np.asarray(actual, float)
    return float(np.sqrt(np.mean((p - a) ** 2)))


def size_means(days: pd.DataFrame, coin: str, sizes: Iterable[int],
               which: Optional[Iterable[str]] = None) -> np.ndarray:
    """The mean cost per size over the days with a cost, restricted to `which` days when given."""
    g = days[days["coin"] == coin]
    if which is not None:
        g = g[g["day"].isin(set(which))]
    return np.array([g[g["usd"] == usd]["cost"].mean() for usd in sizes], float)


def verdict(n_sizes: int, n_design: int, n_holdout: int, err_flat: float, err_curve: float) -> str:
    """The registered rule, checked in the registered order."""
    if n_sizes < MIN_SIZES or n_design < MIN_SPLIT_DAYS or n_holdout < MIN_SPLIT_DAYS:
        return "UNKNOWN"
    if err_flat <= TOL_BPS:
        return "FLAT IS ENOUGH"
    if err_curve <= TOL_BPS:
        return "CURVE HOLDS"
    return "CURVE DRIFTS"


def score(days: pd.DataFrame, coin: str, design_days: Iterable[str]) -> Dict[str, object]:
    """One coin's curve on the design days, its three holdout errors and its verdict."""
    design = set(design_days)
    g = days[days["coin"] == coin]
    holdout = set(g["day"]) - design
    sizes = measured_sizes(days, coin)
    reach = sizes[-1] if sizes else 0
    d_means = size_means(days, coin, sizes, design)
    h_means = size_means(days, coin, sizes, holdout)
    at_reach = g[g["usd"] == reach].dropna(subset=["cost"]) if reach else g.iloc[0:0]
    n_design = int(at_reach["day"].isin(design).sum())
    n_holdout = int(at_reach["day"].isin(holdout).sum())
    c0, k = sqrt_fit(sizes, d_means) if len(sizes) >= 2 else (float("nan"), float("nan"))
    if len(sizes) and np.isfinite(h_means).all() and np.isfinite(d_means).all():
        flat = np.full(len(sizes), d_means[sizes.index(FLAT_USD)] if FLAT_USD in sizes else float("nan"))
        err_curve = rmse(predict(c0, k, sizes), h_means)
        err_flat = rmse(flat, h_means)
        err_table = rmse(d_means, h_means)
    else:
        err_curve = err_flat = err_table = float("nan")
    return {"coin": coin, "sizes": sizes, "reach": reach, "c0": c0, "k": k, "design_days": n_design,
            "holdout_days": n_holdout, "err_curve": err_curve, "err_flat": err_flat, "err_table": err_table,
            "verdict": verdict(len(sizes), n_design, n_holdout, err_flat, err_curve)}


def size_table(days: pd.DataFrame, coin: str, design_days: Iterable[str], sizes: Sequence[int] = SIZES,
               seed: int = BOOT_SEED) -> pd.DataFrame:
    """Per size: the mean over all days with its day-bootstrap CI, the unfillable share, and the design and
    holdout means."""
    design = set(design_days)
    g = days[days["coin"] == coin]
    rows = []
    for usd in sizes:
        s = g[g["usd"] == usd]
        have = s["cost"].dropna().to_numpy()
        low, high = bootstrap_ci(have, seed=seed) if len(have) else (float("nan"), float("nan"))
        rows.append({"usd": usd, "days_with_cost": len(have), "cost": float(have.mean()) if len(have) else float("nan"),
                     "low": low, "high": high, "unfillable": float(s["unfillable"].mean()) if len(s) else float("nan"),
                     "design": float(s[s["day"].isin(design)]["cost"].mean()),
                     "holdout": float(s[~s["day"].isin(design)]["cost"].mean())})
    return pd.DataFrame(rows)


def hour_profile(buckets: pd.DataFrame, coin: str, seed: int = BOOT_SEED) -> Tuple[pd.DataFrame, float]:
    """Per four-hour bucket the mean over days of the day's bucket mean at $10,000 with its day-bootstrap CI,
    and the ratio of the dearest bucket to the cheapest (rows coin, day, bucket, cost)."""
    g = buckets[buckets["coin"] == coin]
    rows = []
    for b in range(BUCKETS):
        have = g[g["bucket"] == b]["cost"].dropna().to_numpy()
        low, high = bootstrap_ci(have, seed=seed) if len(have) else (float("nan"), float("nan"))
        rows.append({"bucket": f"{b * BUCKET_HOURS:02d}-{b * BUCKET_HOURS + BUCKET_HOURS - 1:02d}", "days": len(have),
                     "cost": float(have.mean()) if len(have) else float("nan"), "low": low, "high": high})
    out = pd.DataFrame(rows)
    means = out["cost"].to_numpy()
    ok = np.isfinite(means).any() and np.nanmin(means) > 0
    ratio = float(np.nanmax(means) / np.nanmin(means)) if ok else float("nan")
    return out, ratio


def adjusted(coin: str, cost_bps: float) -> float:
    """The floor adjustment carried from #51's validation: the coin's gap where measured, else the largest."""
    return cost_bps + FLOOR_GAP_BPS.get(coin, FLOOR_GAP_DEFAULT)


def cost(coin: str, usd: float, table: Optional[Dict[str, Dict[str, object]]] = None, adjust: bool = False) -> float:
    """The curve's cost in bps a leg at `usd` from the generated table; raises for a coin not measured, a verdict
    that is not usable, or a size beyond the reach. Nothing is imputed."""
    if table is None:
        from .costcurve_table import TABLE as table  # generated by research/costcurve.py; absent until #68 ran
    if coin not in table:
        raise NotMeasured(f"#68 did not measure {coin}")
    row = table[coin]
    if row["verdict"] not in USABLE:
        raise NotMeasured(f"#68's verdict on {coin} is {row['verdict']}: the curve is not usable")
    if usd > row["reach"]:
        raise NotMeasured(f"#68's reach on {coin} is ${row['reach']:,}; ${usd:,.0f} is beyond the recorded book")
    c = float(predict(float(row["c0"]), float(row["k"]), usd))
    return adjusted(coin, c) if adjust else c
