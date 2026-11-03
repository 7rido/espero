"""#72: does open interest forecast tomorrow's cascade beyond volatility? (research/EXPLORE_CASCADE.md)

The frozen rule, pure: frames in, numbers out, no I/O. research/cascade.py reads the klines, the
open-interest metrics and the funding settlements, and prints.

* `hour_moves`: each day's most negative and most positive one-hour log move, from the 5-minute bars
* `events`: the cascade day (an hour's fall beyond k daily sigmas of the last 30 days) and the squeeze day
* `features`: the eleven features at the origin, every one known at the 23:55 close
* `logit_fit`, `logit_predict`: a ridged logistic regression by iteratively reweighted least squares
* `forecasts`: refit at every month end on targets known by then, forecast the following month
* `logloss`, `per_origin`, `verdict`: the score, the series and the registered rule
"""
from __future__ import annotations

from typing import Dict, List, Sequence, Tuple

import numpy as np
import pandas as pd

from .volf import DAY_S, har_features

BAR_S = 300
HOUR_S = 3_600
WINDOW = HOUR_S // BAR_S          # 12 bars: the close 12 bars on from a bar's close
TRAIL = 30                        # days of realized variance behind the daily sigma
K_SIGMA = 1.25                    # an hour that falls 1.25 of the last month's daily sigma
K_CHOICES = (1.0, 1.5)
RATE_BAND = (0.02, 0.08)
MIN_TRAIN = 5_000                 # pooled rows a fit needs: about four months of 42 coins
RIDGE = 0.01                      # per observation, on every standardized coefficient, none on the constant
MAX_ITER = 50
TOL = 1e-8
CLIP = 1e-4
FUND_FLOOR = 1e-6
PASS_T = 3.0
MIN_EVENTS = 200
MIN_COIN_DAYS = 365
VOL = ["d1", "d7", "d30"]
EXTRA = ["oi1", "oi7", "oivol", "f1", "f7", "fa7", "ls", "m7"]
FULL = VOL + EXTRA
PASS, FAIL, INCONCLUSIVE = "PASS", "FAIL", "INCONCLUSIVE"


# ------------------------------------------------------------------------------------------------ event
def hour_moves(bars: pd.DataFrame) -> pd.DataFrame:
    """Per UTC day: `fall`, the most negative log close change over any two bars exactly an hour apart
    inside the day, and `rise`, the most positive. A day with no such pair has NaN on both."""
    if bars.empty:
        return pd.DataFrame(columns=["fall", "rise"])
    ts = bars.index.to_numpy(dtype="int64")
    lc = np.log(bars["close"].to_numpy(dtype=float))
    day = ts // DAY_S
    ok = np.zeros(len(ts), dtype=bool)
    mv = np.full(len(ts), np.nan)
    if len(ts) > WINDOW:
        same = (ts[WINDOW:] - ts[:-WINDOW] == HOUR_S) & (day[WINDOW:] == day[:-WINDOW])
        ok[WINDOW:] = same
        mv[WINDOW:] = np.where(same, lc[WINDOW:] - lc[:-WINDOW], np.nan)
    f = pd.DataFrame({"day": day[ok], "mv": mv[ok]})
    g = f.groupby("day")["mv"]
    out = pd.DataFrame({"fall": g.min(), "rise": g.max()})
    out.index = pd.to_datetime(out.index.to_numpy() * DAY_S, unit="s")
    return out


def daily_sigma(rv: pd.Series) -> pd.Series:
    """sqrt of the mean realized variance over the last 30 complete days through t: a day's typical move."""
    return np.sqrt(rv.rolling(TRAIL, min_periods=TRAIL).mean())


def events(daily: pd.DataFrame, moves: pd.DataFrame, k: float = K_SIGMA) -> pd.DataFrame:
    """Per origin day t: `sigma_d`, and whether day t+1 is a `cascade` (an hour's fall ≤ −k sigma_d) or a
    `squeeze` (an hour's rise ≥ k sigma_d). NaN where t+1 is incomplete, has no hour window, or sigma_d is missing."""
    sig = daily_sigma(daily["rv"])
    nxt = moves.reindex(daily.index).shift(-1)
    complete_next = daily["complete"].shift(-1).fillna(False).astype(bool)
    have = sig.notna() & nxt["fall"].notna() & complete_next
    casc = pd.Series(np.where(have, nxt["fall"] <= -k * sig, np.nan), index=daily.index)
    sque = pd.Series(np.where(have, nxt["rise"] >= k * sig, np.nan), index=daily.index)
    return pd.DataFrame({"sigma_d": sig, "cascade": casc, "squeeze": sque})


def choose_k(rate: float, k: float = K_SIGMA) -> float:
    """The registered k unless the design rate is outside the band; then the nearest alternative inside."""
    if RATE_BAND[0] <= rate <= RATE_BAND[1]:
        return k
    return K_CHOICES[1] if rate > RATE_BAND[1] else K_CHOICES[0]


# --------------------------------------------------------------------------------------------- features
def features(daily: pd.DataFrame, volume: pd.Series, oi: pd.DataFrame, funding: pd.DataFrame) -> pd.DataFrame:
    """The eleven features at origin t. `daily` is espero.volf.daily's frame plus `close` (log close);
    `volume` the day's base volume; `oi` has oi and ls by day (the day's last row); `funding` has `rate`
    by settlement time (a DatetimeIndex). A non-positive open interest, ratio or volume gives NaN, never -inf."""
    idx = daily.index
    rv = daily["rv"]
    out = har_features(rv).reindex(idx)
    o = oi.reindex(idx)
    pos = o["oi"].where(o["oi"] > 0)
    vol30 = volume.reindex(idx).rolling(TRAIL, min_periods=TRAIL).mean()
    out["oi1"] = np.log(pos / pos.shift(1))
    out["oi7"] = np.log(pos / pos.shift(7))
    out["oivol"] = np.log(pos / vol30.where(vol30 > 0))
    if len(funding):
        day = pd.DatetimeIndex(funding.index).floor("D")
        r = pd.Series(funding["rate"].to_numpy(dtype=float), index=day)
        last = r.groupby(level=0).last().reindex(idx)
        signed = r.groupby(level=0).sum().reindex(idx).fillna(0.0)
        absum = r.abs().groupby(level=0).sum().reindex(idx).fillna(0.0)
        had = r.groupby(level=0).size().reindex(idx).fillna(0)
        out["f1"] = last
        week_had = had.rolling(7, min_periods=7).sum() > 0
        out["f7"] = signed.rolling(7, min_periods=7).sum().where(week_had)
        out["fa7"] = np.log(absum.rolling(7, min_periods=7).sum() + FUND_FLOOR).where(week_had)
    else:
        out["f1"] = out["f7"] = out["fa7"] = np.nan
    out["ls"] = np.log(o["ls"].where(o["ls"] > 0))
    out["m7"] = daily["close"] - daily["close"].shift(7)
    return out[FULL]


# ------------------------------------------------------------------------------------------------ model
def _sigmoid(z: np.ndarray) -> np.ndarray:
    return 1.0 / (1.0 + np.exp(-np.clip(z, -30, 30)))


def logit_fit(X: np.ndarray, y: np.ndarray, ridge: float = RIDGE) -> Dict[str, np.ndarray]:
    """Ridged logistic regression on standardized columns, by iteratively reweighted least squares."""
    X, y = np.asarray(X, float), np.asarray(y, float)
    n, p = X.shape
    mu, sd = X.mean(axis=0), X.std(axis=0)
    sd = np.where(sd > 0, sd, 1.0)
    Z = np.hstack([np.ones((n, 1)), (X - mu) / sd])
    ybar = min(max(y.mean(), CLIP), 1 - CLIP)
    beta = np.zeros(p + 1)
    beta[0] = np.log(ybar / (1 - ybar))
    pen = ridge * n * np.diag([0.0] + [1.0] * p)
    for _ in range(MAX_ITER):
        pr = _sigmoid(Z @ beta)
        w = pr * (1 - pr)
        grad = Z.T @ (y - pr) - pen @ beta
        hess = (Z * w[:, None]).T @ Z + pen
        step = np.linalg.solve(hess, grad)
        beta = beta + step
        if np.abs(step).max() < TOL:
            break
    return {"beta": beta, "mu": mu, "sd": sd}


def logit_predict(model: Dict[str, np.ndarray], X: np.ndarray) -> np.ndarray:
    X = np.asarray(X, float)
    Z = np.hstack([np.ones((len(X), 1)), (X - model["mu"]) / model["sd"]])
    return _sigmoid(Z @ model["beta"])


def month_ends(first: pd.Timestamp, last: pd.Timestamp) -> List[pd.Timestamp]:
    return [d for d in pd.date_range(first, last, freq="ME")]


def training_rows(use: pd.DataFrame, at: pd.Timestamp) -> pd.DataFrame:
    """The rows a fit at `at` may see: those whose target day, origin + 1, is on or before `at`."""
    return use[use["origin"] + pd.Timedelta(days=1) <= at]


def forecasts(rows: pd.DataFrame, cols: Sequence[str], fits: Sequence[pd.Timestamp],
              last_origin: pd.Timestamp, min_train: int = MIN_TRAIN) -> Tuple[pd.Series, Dict[pd.Timestamp, dict]]:
    """Refit at each date in `fits` on every row whose target day (origin + 1) is on or before it, and forecast
    the origins after it up to the next fit (or `last_origin`). `rows` has origin, coin, y and the columns;
    a row is used only when all of them are present. A fit needs `min_train` rows. Returns the probability
    per row index and the fitted models."""
    cols = list(cols)
    use = rows.dropna(subset=["y"] + cols)
    pred = pd.Series(np.nan, index=rows.index)
    models: Dict[pd.Timestamp, dict] = {}
    fits = sorted(fits)
    for i, at in enumerate(fits):
        train = training_rows(use, at)
        if len(train) < min_train or train["y"].nunique() < 2:
            continue
        model = logit_fit(train[cols].to_numpy(), train["y"].to_numpy())
        models[at] = model
        until = fits[i + 1] if i + 1 < len(fits) else last_origin
        tgt = rows[(rows["origin"] > at) & (rows["origin"] <= until)].dropna(subset=cols)
        if len(tgt):
            pred.loc[tgt.index] = logit_predict(model, tgt[cols].to_numpy())
    return pred, models


def base_rate(rows: pd.DataFrame, fits: Sequence[pd.Timestamp], last_origin: pd.Timestamp,
              min_train: int = MIN_TRAIN) -> pd.Series:
    """The training rows' event rate at each fit, applied to the following month."""
    use = rows.dropna(subset=["y"])
    pred = pd.Series(np.nan, index=rows.index)
    fits = sorted(fits)
    for i, at in enumerate(fits):
        train = training_rows(use, at)
        if len(train) < min_train:
            continue
        until = fits[i + 1] if i + 1 < len(fits) else last_origin
        m = (rows["origin"] > at) & (rows["origin"] <= until)
        pred.loc[rows.index[m]] = float(train["y"].mean())
    return pred


# ------------------------------------------------------------------------------------------------ score
def logloss(y, p) -> np.ndarray:
    y, p = np.asarray(y, float), np.clip(np.asarray(p, float), CLIP, 1 - CLIP)
    return -(y * np.log(p) + (1 - y) * np.log(1 - p))


def scored(cells: pd.DataFrame, a: str, b: str) -> pd.DataFrame:
    """The cells where both forecasts and the target exist."""
    return cells.dropna(subset=["y", a, b])


def per_origin(cells: pd.DataFrame, a: str, b: str) -> pd.Series:
    """The series: at each origin the mean over coins of loss(a) − loss(b), positive when b was better."""
    s = scored(cells, a, b)
    gap = logloss(s["y"], s[a]) - logloss(s["y"], s[b])
    return pd.Series(gap, index=s.index).groupby(s["origin"]).mean().sort_index()


def nw_t(x: np.ndarray, lags: int) -> float:
    """Newey-West t of the mean with Bartlett weights."""
    x = np.asarray(x, float)
    n = len(x)
    if n < 2:
        return float("nan")
    e = x - x.mean()
    var = float(e @ e) / n
    for lag in range(1, lags + 1):
        w = 1 - lag / (lags + 1)
        var += 2 * w * float(e[lag:] @ e[:-lag]) / n
    return float(x.mean() / np.sqrt(var / n)) if var > 0 else float("nan")


def halves(series: pd.Series) -> Tuple[float, float]:
    n = len(series)
    first = series.iloc[: (n + 1) // 2]
    return float(first.mean()), float(series.iloc[(n + 1) // 2:].mean())


def breadth(cells: pd.DataFrame, a: str, b: str, min_days: int = MIN_COIN_DAYS) -> Tuple[int, int]:
    """(coins with a positive mean gap, coins counted) among coins with at least `min_days` scored cells."""
    s = scored(cells, a, b)
    gap = pd.Series(logloss(s["y"], s[a]) - logloss(s["y"], s[b]), index=s.index)
    by = gap.groupby(s["coin"]).agg(["mean", "size"])
    by = by[by["size"] >= min_days]
    return int((by["mean"] > 0).sum()), int(len(by))


def verdict(t: float, q: float, half1: float, half2: float, up: int, counted: int, n_events: int,
            min_events: int = MIN_EVENTS) -> str:
    """The registered rule: enough events, then t ≥ 3 with q < 0.05, both halves above zero, breadth."""
    if n_events < min_events:
        return INCONCLUSIVE
    if not (t >= PASS_T and q < 0.05):
        return FAIL
    if not (half1 > 0 and half2 > 0):
        return FAIL
    if not (counted and up * 2 > counted):
        return FAIL
    return PASS


def calibration(p: np.ndarray, y: np.ndarray, bins: int = 10) -> pd.DataFrame:
    """Observed event rate by decile of the forecast probability."""
    p, y = np.asarray(p, float), np.asarray(y, float)
    rank = pd.qcut(pd.Series(p).rank(method="first"), bins, labels=False)
    f = pd.DataFrame({"decile": rank + 1, "p": p, "y": y})
    return f.groupby("decile").agg(n=("y", "size"), forecast=("p", "mean"), observed=("y", "mean")).reset_index()
