"""Descriptive patterns for the operator (#52-#56, research/PREREGISTRATION_PATTERNS.md). Measurements, not signals."""
from __future__ import annotations

from typing import Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

WINDOW_MIN = 120
MIN_HISTORY = 60
HIGH_PCT, LOW_PCT = 0.80, 0.20
MIN_STATES = 20
MIN_COINS_STATE = 9
BOOT_DRAWS = 10_000
CENSOR_S = 300


def states(signal: pd.Series) -> pd.Series:
    """+1 high, -1 low, 0 neither, from cut-offs on the previous window only. NaN signal gives 0."""
    past = signal.shift(1).rolling(WINDOW_MIN, min_periods=MIN_HISTORY)
    high, low = past.quantile(HIGH_PCT), past.quantile(LOW_PCT)
    out = pd.Series(0, index=signal.index, dtype=int)
    out[signal >= high] = 1
    out[signal <= low] = -1
    return out


def forward_bps(prices: pd.Series, at: pd.DatetimeIndex, seconds: int) -> np.ndarray:
    """Change in bps from the last price at or before each time to the last at or before time + seconds.

    NaN when the later time falls past the series' last timestamp.
    """
    now = prices.reindex(at, method="ffill").to_numpy(float)
    later_at = at + pd.Timedelta(seconds=seconds)
    later = prices.reindex(later_at, method="ffill").to_numpy(float, copy=True)
    later[later_at > prices.index[-1]] = np.nan
    return (later / now - 1) * 1e4


def high_minus_low(state: np.ndarray, move: np.ndarray) -> Tuple[float, float, float]:
    """(high mean - low mean, up share after high, up share after low); NaN with under MIN_STATES of either."""
    ok = np.isfinite(move)
    high, low = move[ok & (state == 1)], move[ok & (state == -1)]
    if len(high) < MIN_STATES or len(low) < MIN_STATES:
        return float("nan"), float("nan"), float("nan")
    return float(high.mean() - low.mean()), float((high > 0).mean()), float((low > 0).mean())


def bootstrap_ci(values: np.ndarray, level: float, seed: int, draws: int = BOOT_DRAWS) -> Tuple[float, float]:
    rng = np.random.default_rng(seed)
    means = rng.choice(values, size=(draws, len(values)), replace=True).mean(axis=1)
    tail = (1 - level) / 2 * 100
    return float(np.percentile(means, tail)), float(np.percentile(means, 100 - tail))


def clear_label(low: float, high: float, first_half: float, second_half: float, coins_same: int,
                coins_needed: int) -> bool:
    """The registered CLEAR rule: the CI excludes zero, the halves agree, and enough coins share the sign."""
    if low <= 0 <= high:
        return False
    return np.sign(first_half) == np.sign(second_half) == np.sign(low) and coins_same >= coins_needed


def horizon_summary(rows: pd.DataFrame, level: float, seed: int,
                    coins_needed: int = MIN_COINS_STATE) -> Dict[str, object]:
    """One horizon from coin-day rows with coin, day, value: days average their coins, the CI resamples days."""
    rows = rows.dropna(subset=["value"])
    by_day = rows.groupby("day")["value"].mean().sort_index()
    by_coin = rows.groupby("coin")["value"].mean()
    mean = float(by_day.mean())
    low, high = bootstrap_ci(by_day.to_numpy(), level, seed)
    half = len(by_day) // 2
    first, second = float(by_day.iloc[:half].mean()), float(by_day.iloc[half:].mean())
    same = int((np.sign(by_coin) == np.sign(mean)).sum())
    clear = clear_label(low, high, first, second, same, coins_needed)
    return {"mean": mean, "low": low, "high": high, "first_half": first, "second_half": second, "days": len(by_day),
            "coins_same": same, "coins": len(by_coin), "clear": clear}


def grid_prices(ms: np.ndarray, prices: np.ndarray, day_start_ms: int, step_ms: int, bins: int) -> np.ndarray:
    """The last price in or before each bin; NaN before the first trade."""
    idx = ((ms - day_start_ms) // step_ms).astype(np.int64)
    keep = (idx >= 0) & (idx < bins)
    out = np.full(bins, np.nan)
    order = np.argsort(ms[keep], kind="stable")
    out[idx[keep][order]] = prices[keep][order]
    return pd.Series(out).ffill().to_numpy()


def peak_lag(first: np.ndarray, second: np.ndarray, max_lag: int) -> Tuple[int, float]:
    """The lag in bins with the highest correlation of returns; positive means `first` moved before `second`."""
    a = np.nan_to_num(np.diff(np.log(first)))
    b = np.nan_to_num(np.diff(np.log(second)))
    a, b = a - a.mean(), b - b.mean()
    denom = float(np.sqrt((a * a).sum() * (b * b).sum()))
    if denom == 0:
        return 0, float("nan")
    best_lag, best = 0, -np.inf
    for lag in range(-max_lag, max_lag + 1):
        value = float((a[:-lag] * b[lag:]).sum() if lag > 0 else (a[-lag:] * b[:lag or None]).sum())
        if value > best:
            best_lag, best = lag, value
    return best_lag, best / denom


def spaced_events(times: np.ndarray, gap: float) -> np.ndarray:
    """A mask keeping each time at least `gap` after the previous time, kept or not. `times` must be sorted."""
    keep = np.zeros(len(times), dtype=bool)
    last = -np.inf
    for i, t in enumerate(times):
        keep[i] = t - last >= gap
        last = t
    return keep


def refill(times_s: np.ndarray, depth: np.ndarray, burst_s: float, baseline: float) -> Tuple[float, float]:
    """(seconds until depth is back to 90% of baseline, censored at 300; lowest depth as a share of baseline)."""
    after = (times_s >= burst_s) & (times_s <= burst_s + CENSOR_S)
    if not after.any() or not baseline > 0:
        return float("nan"), float("nan")
    t, d = times_s[after], depth[after]
    hit = np.flatnonzero(d >= 0.9 * baseline)
    seconds = float(t[hit[0]] - burst_s) if len(hit) else float(CENSOR_S)
    end = hit[0] + 1 if len(hit) else len(d)
    return seconds, float(d[:end].min() / baseline)


def top5_notional(px: np.ndarray, qty: np.ndarray) -> np.ndarray:
    return np.nansum(px * qty, axis=1)


def imbalance(bid_notional: np.ndarray, ask_notional: np.ndarray) -> np.ndarray:
    total = bid_notional + ask_notional
    return np.divide(bid_notional, total, out=np.full(len(total), np.nan), where=total > 0)


def flow(buy: pd.Series, sell: pd.Series) -> pd.Series:
    """One-sidedness over 60 s at each second's row, NaN when nothing traded."""
    b, s = buy.rolling(60, min_periods=1).sum(), sell.rolling(60, min_periods=1).sum()
    total = b + s
    return ((b - s) / total).where(total > 0)


def summary_rows(rows: List[Dict[str, object]], name: Optional[str] = None) -> pd.DataFrame:
    frame = pd.DataFrame(rows)
    if name is not None:
        frame.insert(0, "name", name)
    return frame
