"""What a market order costs as it walks a recorded book (#51, research/PREREGISTRATION_BOOKWALK.md).

A measurement: the cost is in bps of mid, from the displayed book, with no reaction from anyone else.
"""
from __future__ import annotations

from typing import Dict

import numpy as np
import pandas as pd

HURDLE_BPS = 18.0
UNFILLABLE_LIMIT = 0.05
MIN_DAYS = 10
BOOT_DRAWS = 10_000
BOOT_SEED = 51


def walk(px: np.ndarray, qty: np.ndarray, mid: np.ndarray, usd: float, side: str) -> np.ndarray:
    """Cost in bps per snapshot of spending `usd` through the levels, best first; NaN if the book runs out.

    `px` and `qty` are (snapshots, levels), with NaN for a level the book doesn't have.
    """
    if side not in ("buy", "sell"):
        raise ValueError(side)
    notional = np.nan_to_num(px * qty)
    cum = notional.cumsum(axis=1)
    prior = np.hstack([np.zeros((len(cum), 1)), cum[:, :-1]])
    take = np.clip(usd - prior, 0.0, notional)
    base = np.divide(take, px, out=np.zeros_like(take), where=np.nan_to_num(px) > 0).sum(axis=1)
    fill = np.divide(usd, base, out=np.full(len(base), np.nan), where=base > 0)
    cost = (fill / mid - 1) * 1e4 if side == "buy" else (1 - fill / mid) * 1e4
    cost[cum[:, -1] < usd] = np.nan
    return cost


def valid_snapshots(ask0: np.ndarray, bid0: np.ndarray) -> np.ndarray:
    """A snapshot with both sides and no cross; a missing side is NaN, which compares False."""
    return ask0 > bid0


def coin_day(asks_px: np.ndarray, asks_qty: np.ndarray, bids_px: np.ndarray, bids_qty: np.ndarray,
             sizes=(1_000, 10_000, 100_000)) -> Dict[int, Dict[str, float]]:
    """One coin-day's cost, 95th percentile and unfillable share per size. Rows must already be valid snapshots."""
    mid = (asks_px[:, 0] + bids_px[:, 0]) / 2
    out = {}
    for usd in sizes:
        buy, sell = walk(asks_px, asks_qty, mid, usd, "buy"), walk(bids_px, bids_qty, mid, usd, "sell")
        has_both = np.isfinite(buy).any() and np.isfinite(sell).any()
        out[usd] = {
            "cost": (np.nanmean(buy) + np.nanmean(sell)) / 2 if has_both else float("nan"),
            "p95": (np.nanpercentile(buy, 95) + np.nanpercentile(sell, 95)) / 2 if has_both else float("nan"),
            "unfillable": (np.isnan(buy).mean() + np.isnan(sell).mean()) / 2,
        }
    return out


def bootstrap_ci(days: np.ndarray, draws: int = BOOT_DRAWS, seed: int = BOOT_SEED):
    """95% percentile CI on the mean, resampling days."""
    rng = np.random.default_rng(seed)
    means = rng.choice(days, size=(draws, len(days)), replace=True).mean(axis=1)
    return float(np.percentile(means, 2.5)), float(np.percentile(means, 97.5))


def round_trip(cost_bps: float, fee_bps: float) -> float:
    return 2 * (fee_bps + cost_bps)


def verdict(low: float, high: float, unfillable: float, n_days: int, fee_bps: float) -> str:
    """The registered rule, checked in the registered order."""
    if unfillable > UNFILLABLE_LIMIT or n_days < MIN_DAYS:
        return "UNKNOWN"
    if round_trip(high, fee_bps) <= HURDLE_BPS:
        return "COVERED"
    if round_trip(low, fee_bps) > HURDLE_BPS:
        return "NOT COVERED"
    return "UNKNOWN"


def summarize(days: pd.DataFrame, fee_bps: float) -> pd.DataFrame:
    """One row per coin and size from coin-day rows with coin, usd, cost, p95 and unfillable."""
    rows = []
    for (coin, usd), g in days.groupby(["coin", "usd"], sort=False):
        have = g["cost"].dropna().to_numpy()
        low, high = bootstrap_ci(have) if len(have) else (float("nan"), float("nan"))
        unfillable = float(g["unfillable"].mean())
        rows.append({"coin": coin, "usd": usd, "days": len(g), "days_with_cost": len(have),
                     "cost": float(have.mean()) if len(have) else float("nan"), "low": low, "high": high,
                     "p95": float(g["p95"].mean()), "unfillable": unfillable,
                     "round_trip": round_trip(float(have.mean()), fee_bps) if len(have) else float("nan"),
                     "verdict": verdict(low, high, unfillable, len(have), fee_bps)})
    return pd.DataFrame(rows)
