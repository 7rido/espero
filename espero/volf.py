"""#66: a HAR forecast of next week's variance from 5-minute bars, against the books' trailing variance.

Does a HAR forecast built from 5-minute realized variance predict next week's variance of daily returns better
than the trailing 30-day estimator #8 sizes with (research/PREREGISTRATION_VOLF.md)?

Pure: frames and arrays in, numbers out, no I/O. research/volf.py reads the archive and prints.

Every window counts complete days only. A day is complete when it has at least MIN_BARS of its 288 five-minute
bars, its 23:55 bar (whose close is the day's close), the previous day's 23:55 bar, and a realized variance above
zero. A window that touches an incomplete day gives no number, and a cell is scored only when both forecasts and
the target exist, so the two forecasts are always compared on the same cells.
"""
from __future__ import annotations

import math
from typing import Dict, List, Optional, Sequence, Tuple

import numpy as np
import pandas as pd

from .factor_eval import newey_west_t

DAY_S = 86_400
MIN_BARS = 276                  # of 288: a day may miss up to 12 bars, an hour, and still count
LAST_BAR_S = DAY_S - 300        # the 23:55 bar; its close is the day's close
HAR_DAYS = (1, 7, 30)           # yesterday, the last week, the last month (Corsi 2009, on a 7-day week)
MIN_TRAIN = 365                 # training rows a coin needs before its first forecast
WEEK = 7                        # #8 decides at Sunday's close and holds the next seven days
TRAIL_WEEK = 30                 # #8's VOL_WINDOW (espero/mf.py)
TRAIL_MONTH = 90                # #63's VOL_WINDOW (espero/sleeves.py)
MONTH_TRAIN_H = 30              # the monthly HAR is fitted on 30-day targets
PASS_T = 3.0
MIN_ORIGINS = 100               # fewer weekly origins than this: INCONCLUSIVE
MIN_COIN_ORIGINS = 52           # breadth counts coins with a year of weekly cells
LIQUID = ("BTC", "ETH")

FIRST_MONTH = "2020-01"                            # the archive's first month for these coins
DESIGN_LAST_MONTH = "2022-12"
DESIGN_LAST_DAY = pd.Timestamp("2022-12-31")      # the design run reads nothing later
DESIGN_FIRST_ORIGIN = pd.Timestamp("2021-01-03")  # a Sunday; month-end and daily origins start 2020-12-31
HOLDOUT_FIRST_ORIGIN = pd.Timestamp("2023-01-01")  # a Sunday; month-end origins start 2022-12-31
HOLDOUT_LAST_MONTH = "2026-03"
HOLDOUT_LAST_DAY = pd.Timestamp("2026-03-31")      # the last day of the archive on disk

PASS = "PASS"
PASS_WEEK = "PASS at a week; a month not shown"
FAIL = "FAIL"
INCONCLUSIVE = "INCONCLUSIVE"


# ----------------------------------------------------------------------------------------------- months
def months_through(last: str, first: str = FIRST_MONTH) -> List[str]:
    """Every month 'YYYY-MM' from `first` to `last`, both included."""
    return [p.strftime("%Y-%m") for p in pd.period_range(first, last, freq="M")]


def readable(month: str, design: bool) -> bool:
    """The design run may open no file after DESIGN_LAST_MONTH; the holdout run none after the archive's end."""
    return month <= (DESIGN_LAST_MONTH if design else HOLDOUT_LAST_MONTH)


# ------------------------------------------------------------------------------------------------- days
def daily(bars: pd.DataFrame) -> pd.DataFrame:
    """Five-minute bars (index: open time in seconds, a `close` column) -> one row per UTC day on a continuous
    calendar: `n` bars, `rv` the sum of squared log returns between consecutive bars opening in the day, `ret`
    the log close-to-close return, `complete`. `rv` and `ret` are NaN on an incomplete day."""
    cols = ["n", "rv", "ret", "complete"]
    if bars.empty:
        return pd.DataFrame(columns=cols)
    ts = bars.index.to_numpy(dtype="int64")
    lc = np.log(bars["close"].to_numpy(dtype=float))
    r = np.diff(lc, prepend=np.nan)          # from the previous bar on the tape, across any gap
    day = ts // DAY_S
    last = (ts - day * DAY_S) == LAST_BAR_S
    f = pd.DataFrame({"day": day, "r2": r * r})
    g = f.groupby("day")
    n = g.size()
    rv = g["r2"].sum(min_count=1)
    close = pd.Series(lc[last], index=day[last])
    full = np.arange(int(day.min()), int(day.max()) + 1)
    out = pd.DataFrame(index=full)
    out["n"] = n.reindex(full).fillna(0).astype(int)
    out["rv"] = rv.reindex(full)
    c = close[~close.index.duplicated(keep="last")].reindex(full)
    prev = c.shift(1)
    out["ret"] = c - prev
    out["complete"] = (out["n"] >= MIN_BARS) & c.notna() & prev.notna() & (out["rv"] > 0)
    out.loc[~out["complete"], ["rv", "ret"]] = np.nan
    out.index = pd.to_datetime(full * DAY_S, unit="s")
    return out[cols]


def har_features(rv: pd.Series) -> pd.DataFrame:
    """log of the mean daily realized variance over the last 1, 7 and 30 days through day t."""
    return pd.DataFrame({f"d{k}": np.log(rv.rolling(k, min_periods=k).mean()) for k in HAR_DAYS}, index=rv.index)


def trailing_var(ret: pd.Series, window: int) -> pd.Series:
    """The books' estimator: sample variance (ddof 1) of the last `window` daily log returns through day t."""
    return ret.rolling(window, min_periods=window).var(ddof=1)


def forward_mean_sq(ret: pd.Series, h: int) -> pd.Series:
    """The target at origin t: the mean squared daily return over days t+1 .. t+h, NaN unless all are there."""
    return (ret * ret).rolling(h, min_periods=h).mean().shift(-h)


def month_target(ret: pd.Series, origin: pd.Timestamp) -> float:
    """The mean squared daily return over the calendar month after a month-end origin, NaN unless complete."""
    start = origin + pd.Timedelta(days=1)
    end = start + pd.offsets.MonthEnd(0)
    days = pd.date_range(start, end, freq="D")
    x = ret.reindex(days)
    return float((x * x).mean()) if x.notna().all() else float("nan")


def sundays(first: pd.Timestamp, last_day: pd.Timestamp, h: int = WEEK) -> List[pd.Timestamp]:
    """Weekly origins: every Sunday from `first` whose h-day target ends on or before `last_day`."""
    d = pd.date_range(first, last_day - pd.Timedelta(days=h), freq="W-SUN")
    return list(d)


def month_ends(first: pd.Timestamp, last_day: pd.Timestamp) -> List[pd.Timestamp]:
    """Monthly origins: every month end from `first` whose next calendar month ends on or before `last_day`."""
    out = []
    for e in pd.date_range(first, last_day, freq="ME"):
        if (e + pd.Timedelta(days=1)) + pd.offsets.MonthEnd(0) <= last_day:
            out.append(e)
    return out


# -------------------------------------------------------------------------------------------- the model
def fit(x: np.ndarray, y: np.ndarray) -> Tuple[np.ndarray, float]:
    """OLS of log y on [1, x]; Duan's smearing factor, the mean of exp(residual), undoes the log's bias."""
    a = np.column_stack([np.ones(len(y)), x])
    ly = np.log(y)
    beta, *_ = np.linalg.lstsq(a, ly, rcond=None)
    return beta, float(np.mean(np.exp(ly - a @ beta)))


def predict(beta: np.ndarray, smear: float, x: np.ndarray) -> float:
    return float(math.exp(beta[0] + float(np.dot(beta[1:], x))) * smear)


def forecasts(feats: pd.DataFrame, y: pd.Series, origins: Sequence[pd.Timestamp], h: int,
              min_train: int = MIN_TRAIN) -> pd.Series:
    """At each origin T: fit on every day t with t + h <= T whose inputs and target exist, then forecast from
    T's inputs. Refitted at every origin, so nothing after T is used. NaN where T's inputs are missing or
    fewer than `min_train` rows qualify."""
    x = feats.to_numpy(dtype=float)
    yy = y.reindex(feats.index).to_numpy(dtype=float)
    ok = np.isfinite(x).all(axis=1) & np.isfinite(yy) & (yy > 0)
    pos = feats.index.get_indexer(pd.DatetimeIndex(origins)) if len(origins) else np.array([], dtype=int)
    out: Dict[pd.Timestamp, float] = {}
    for t, i in zip(origins, pos):
        out[t] = float("nan")
        if i < 0 or not np.isfinite(x[i]).all() or i - h < 0:
            continue
        rows = np.flatnonzero(ok[: i - h + 1])
        if rows.size < min_train:
            continue
        beta, smear = fit(x[rows], yy[rows])
        out[t] = predict(beta, smear, x[i])
    return pd.Series(out, dtype=float)


# ----------------------------------------------------------------------------------------------- scoring
def qlike(y, f):
    """Patton's QLIKE: robust to noise in the target, and it punishes a forecast that is too low."""
    r = np.asarray(y, dtype=float) / np.asarray(f, dtype=float)
    return r - np.log(r) - 1.0


def scored(cells: pd.DataFrame, a: str, b: str) -> pd.DataFrame:
    """The cells both forecasts and the target cover, with `d` = QLIKE(a) - QLIKE(b): positive when b is better."""
    ok = cells[["y", a, b]].notna().all(axis=1)
    c = cells[ok & (cells["y"] > 0) & (cells[a] > 0) & (cells[b] > 0)].copy()
    c["d"] = qlike(c["y"], c[a]) - qlike(c["y"], c[b])
    return c


def per_origin(cells: pd.DataFrame, a: str, b: str) -> pd.Series:
    """The loss gap averaged over coins at each origin, in date order."""
    c = scored(cells, a, b)
    return c.groupby("origin")["d"].mean().sort_index()


def nw_lags(n: int) -> int:
    """research/FDR_STANDARD.md's lag count."""
    return int(math.floor(4 * (n / 100) ** (2 / 9))) if n > 0 else 0


def t_of(d: pd.Series) -> float:
    return newey_west_t(d.to_numpy(dtype=float), nw_lags(len(d))) if len(d) >= 3 else float("nan")


def p_two_sided(t: float) -> float:
    """The standard's normal p, which it uses over 100 observations; MIN_ORIGINS keeps the primary above that."""
    return math.erfc(abs(t) / math.sqrt(2)) if math.isfinite(t) else float("nan")


def halves(d: pd.Series) -> Tuple[float, float]:
    """Mean gap over the earlier and the later half of the origins; the earlier half takes an odd one."""
    k = (len(d) + 1) // 2
    return float(d.iloc[:k].mean()), float(d.iloc[k:].mean())


def breadth(cells: pd.DataFrame, a: str, b: str, min_origins: int = MIN_COIN_ORIGINS) -> Tuple[float, int]:
    """Among coins with at least `min_origins` scored cells, the share whose mean gap is above zero."""
    c = scored(cells, a, b)
    g = c.groupby("coin")["d"].agg(["mean", "size"])
    g = g[g["size"] >= min_origins]
    return (float((g["mean"] > 0).mean()) if len(g) else float("nan")), int(len(g))


def evaluate(week: pd.DataFrame, month: pd.DataFrame, q: Optional[float] = None) -> Dict[str, object]:
    """The registered criteria. `week` holds weekly cells (origin, coin, y, bench, har), `month` monthly ones.
    `q` is #66's Benjamini-Hochberg q over the ledger at judgment; without it the outcome says the FDR bar
    is still to be read."""
    d = per_origin(week, "bench", "har")
    n = len(d)
    t = t_of(d)
    first, second = halves(d) if n else (float("nan"), float("nan"))
    share, coins = breadth(week, "bench", "har")
    dm = per_origin(month, "bench", "har")
    res: Dict[str, object] = {
        "origins": n, "cells": int(len(scored(week, "bench", "har"))), "mean": float(d.mean()) if n else float("nan"),
        "t": t, "lags": nw_lags(n), "p": p_two_sided(t), "q": q,
        "first_half": first, "second_half": second, "breadth": share, "breadth_coins": coins,
        "month_origins": len(dm), "month_mean": float(dm.mean()) if len(dm) else float("nan"), "month_t": t_of(dm),
    }
    if n < MIN_ORIGINS:
        res["outcome"] = INCONCLUSIVE
        return res
    checks = {
        "t": math.isfinite(t) and t >= PASS_T and res["mean"] > 0,
        "halves": first > 0 and second > 0,
        "breadth": math.isfinite(share) and share > 0.5,
        "fdr": q is not None and q < 0.05,
    }
    res["checks"] = checks
    if not (checks["t"] and checks["halves"] and checks["breadth"]):
        res["outcome"] = FAIL
    elif q is None:
        res["outcome"] = "weekly criteria met; the FDR bar is read from the ledger at judgment"
    elif not checks["fdr"]:
        res["outcome"] = FAIL
    else:
        res["outcome"] = PASS if res["month_mean"] > 0 else PASS_WEEK
    return res


# ----------------------------------------------------------------------------------- information only
def sizing(cells: pd.DataFrame, f: str) -> Dict[str, float]:
    """What a forecast does to a position scaled to a volatility target: the realized vol over the target is
    sqrt(y / f). Mean |log| of that ratio (lower is better sizing), the share of cells above twice the target,
    and the mean week-to-week |change| in log scale per coin (the turnover the forecast causes)."""
    c = cells[cells[["y", f]].notna().all(axis=1) & (cells["y"] > 0) & (cells[f] > 0)]
    ratio = 0.5 * np.log(c["y"] / c[f])
    scale = (-0.5 * np.log(c[f])).groupby(c["coin"]).diff().abs()
    return {"cells": int(len(c)), "mean_abs_log_ratio": float(ratio.abs().mean()),
            "share_over_2x": float((ratio > math.log(2)).mean()), "scale_change": float(scale.mean())}


def mse_ratio(cells: pd.DataFrame, a: str, b: str) -> float:
    """Mean squared error of a over that of b on the variance itself, on the cells both cover."""
    c = scored(cells, a, b)
    return float(((c["y"] - c[a]) ** 2).mean() / ((c["y"] - c[b]) ** 2).mean()) if len(c) else float("nan")


def by_group(cells: pd.DataFrame, a: str, b: str, key: pd.Series) -> pd.DataFrame:
    """Mean gap and cell count by a grouping of the cells (year of origin, or tier)."""
    c = scored(cells, a, b)
    return c.groupby(key.reindex(c.index))["d"].agg(["mean", "size"])
