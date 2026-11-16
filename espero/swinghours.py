"""#82: session swings, how big each coin's hourly moves are by hour of the week (PREREGISTRATION_SWINGHOURS.md).

A measurement, pure: frames in, numbers out, no I/O. research/swinghours.py reads the bars and prints. Each bar's
swing is its body, |ln(close/open)|, and its range, ln(high/low), each over the coin's previous 720 bars' mean of
the same. The profiles are the mean normalised swing per slot of the week, of the days, and of the weekday's hours
on the UTC and the New York clock. Nothing here trades or reads a direction; the signed return by slot is
information only.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Mapping, Optional, Sequence

import numpy as np
import pandas as pd

WINDOW = 720                     # the normaliser: the previous 30 days of hourly bars, the current bar excluded
SPLIT = pd.Timestamp("2025-01-01", tz="UTC")        # in-sample before, out-of-sample from
END = pd.Timestamp("2026-10-01", tz="UTC")          # out-of-sample to 2026-09-30 inclusive
MIN_MONTHS = 12                  # a coin compares the halves only with at least this many months in each
POOLED_MIN = 0.7                 # readout 1: the pooled weekday-hours correlation between the halves
COIN_MIN = 0.5                   # readout 1: a coin's own correlation
COINS_NEEDED = 13                # readout 1: of the 15 comparing coins
CLOCK_MARGIN = 0.05              # readout 2: a smaller difference between the clocks is "no clear clock"
NEW_YORK = "America/New_York"
MEASURES = ("body", "range")
CLOCKS = ("utc", "new_york")


def swings(frame: pd.DataFrame) -> pd.DataFrame:
    """One coin's hourly bars -> t (UTC), body, range and ret (the signed log return), kept bars only, normalised.
    Dropped: zero volume, high below low, any price not positive, and the first WINDOW bars (no normaliser yet)."""
    f = frame.sort_values("open_time").drop_duplicates("open_time")
    px = f[["open", "high", "low", "close"]]
    ok = (f["volume"] > 0) & (f["high"] >= f["low"]) & (px > 0).all(axis=1)
    f = f[ok]
    t = to_utc(f["open_time"].to_numpy())
    out = pd.DataFrame({"t": t, "ret": np.log(f["close"].to_numpy() / f["open"].to_numpy())})
    out["body"] = out["ret"].abs()
    out["range"] = np.log(f["high"].to_numpy() / f["low"].to_numpy())
    for m in MEASURES:
        level = out[m].shift(1).rolling(WINDOW, min_periods=WINDOW).mean()
        out[m] = out[m] / level
    out = out[out["body"].notna() & out["range"].notna() & np.isfinite(out["body"]) & np.isfinite(out["range"])]
    return out.reset_index(drop=True)


def to_utc(open_time: np.ndarray) -> pd.DatetimeIndex:
    """Open times in milliseconds, or in microseconds where Binance's archive changed unit, as UTC times."""
    x = np.asarray(open_time, dtype="int64")
    unit = "us" if len(x) and np.nanmax(x) > 10**14 else "ms"
    return pd.to_datetime(x, unit=unit, utc=True)


def slots(t: pd.Series, clock: str = "utc") -> pd.DataFrame:
    """For each time: the day of the week (Monday 0) and the hour, on the UTC or the New York clock."""
    local = t if clock == "utc" else t.dt.tz_convert(NEW_YORK)
    return pd.DataFrame({"dow": local.dt.dayofweek.to_numpy(), "hour": local.dt.hour.to_numpy()})


def profile(values: np.ndarray, keys: np.ndarray, n: int) -> np.ndarray:
    """The mean of `values` in each of n slots; NaN where a slot holds nothing."""
    total = np.bincount(keys, weights=values, minlength=n)[:n]
    count = np.bincount(keys, minlength=n)[:n]
    with np.errstate(invalid="ignore", divide="ignore"):
        return np.where(count > 0, total / np.maximum(count, 1), np.nan)


@dataclass(frozen=True)
class Profiles:
    week: np.ndarray             # 168: dow * 24 + hour, UTC
    days: np.ndarray             # 7, UTC
    hours: Dict[str, np.ndarray]  # clock -> 24: Monday to Friday on that clock, by its hour
    bars: int


def profiles(s: pd.DataFrame, measure: str = "body") -> Profiles:
    v = s[measure].to_numpy()
    u = slots(s["t"], "utc")
    hours = {}
    for clock in CLOCKS:
        c = u if clock == "utc" else slots(s["t"], clock)
        wk = c["dow"].to_numpy() < 5
        hours[clock] = profile(v[wk], c["hour"].to_numpy()[wk], 24)
    return Profiles(profile(v, (u["dow"] * 24 + u["hour"]).to_numpy(), 168), profile(v, u["dow"].to_numpy(), 7),
                    hours, len(s))


def halves(s: pd.DataFrame) -> Dict[str, pd.DataFrame]:
    return {"in": s[s["t"] < SPLIT], "out": s[(s["t"] >= SPLIT) & (s["t"] < END)]}


def months(s: pd.DataFrame) -> int:
    return int(s["t"].dt.strftime("%Y-%m").nunique()) if len(s) else 0


def compares(h: Mapping[str, pd.DataFrame]) -> bool:
    return months(h["in"]) >= MIN_MONTHS and months(h["out"]) >= MIN_MONTHS


def spearman(a: np.ndarray, b: np.ndarray) -> float:
    ok = np.isfinite(a) & np.isfinite(b)
    if ok.sum() < 3:
        return float("nan")
    ra, rb = pd.Series(a[ok]).rank().to_numpy(), pd.Series(b[ok]).rank().to_numpy()
    if ra.std() == 0 or rb.std() == 0:
        return float("nan")
    return float(np.corrcoef(ra, rb)[0, 1])


def pooled(arrays: Sequence[np.ndarray]) -> np.ndarray:
    """Equal-weight mean across coins, slot by slot."""
    with np.errstate(invalid="ignore"):
        return np.nanmean(np.vstack(arrays), axis=0)


def peak_to_trough(p: np.ndarray) -> float:
    return float(np.nanmax(p) / np.nanmin(p)) if np.nanmin(p) > 0 else float("nan")


@dataclass(frozen=True)
class Repeat:
    measure: str
    clock: str
    pooled_rho: float
    coin_rho: Dict[str, float]
    coins_at_min: int
    coins: int

    @property
    def repeats(self) -> bool:
        return self.pooled_rho >= POOLED_MIN and self.coins_at_min >= COINS_NEEDED


def repeat(by_coin: Mapping[str, Mapping[str, Profiles]], measure: str, clock: str) -> Repeat:
    """Readout 1 on one measure and clock: `by_coin[coin]["in"|"out"]` are the comparing coins' profiles."""
    rho = {c: spearman(p["in"].hours[clock], p["out"].hours[clock]) for c, p in by_coin.items()}
    pin = pooled([p["in"].hours[clock] for p in by_coin.values()])
    pout = pooled([p["out"].hours[clock] for p in by_coin.values()])
    return Repeat(measure, clock, spearman(pin, pout), rho, sum(1 for r in rho.values() if r >= COIN_MIN), len(rho))


def clock_readout(utc: Repeat, new_york: Repeat) -> str:
    """Readout 2: the clock whose pooled out-of-sample correlation is higher, by at least CLOCK_MARGIN."""
    d = utc.pooled_rho - new_york.pooled_rho
    if not np.isfinite(d) or abs(d) < CLOCK_MARGIN:
        return "no clear clock"
    return "UTC" if d > 0 else "New York"


def busiest_quietest(p: np.ndarray, k: int = 1) -> tuple:
    """The k busiest and k quietest slots, by index, and the ratio of the busiest to the quietest."""
    order = np.argsort(np.where(np.isfinite(p), p, np.inf))
    quiet = [int(i) for i in order[:k]]
    busy = [int(i) for i in np.argsort(np.where(np.isfinite(p), -p, np.inf))[:k]]
    return busy, quiet, peak_to_trough(p)


def weekend_ratio(days: np.ndarray) -> float:
    """Saturday's and Sunday's mean swing over Monday to Friday's."""
    return float(np.nanmean(days[5:7]) / np.nanmean(days[:5]))


def weekend_quietest(days: np.ndarray) -> bool:
    """Readout 4, one half: Saturday and Sunday are the two quietest days."""
    return set(int(i) for i in np.argsort(days)[:2]) == {5, 6}


def signed_by_slot(s: pd.DataFrame) -> np.ndarray:
    """Information only, not a signal: the mean signed log return per slot of the week, UTC."""
    u = slots(s["t"], "utc")
    return profile(s["ret"].to_numpy(), (u["dow"] * 24 + u["hour"]).to_numpy(), 168)


def year_rhos(s: pd.DataFrame, reference: np.ndarray, measure: str = "body", clock: str = "utc") -> Dict[int, float]:
    """Information only: each calendar year's weekday-hours profile against a reference profile."""
    out = {}
    for y, part in s.groupby(s["t"].dt.year):
        if months(part) >= MIN_MONTHS // 2:
            out[int(y)] = spearman(profiles(part, measure).hours[clock], reference)
    return out


def raw_bps_median(frame: pd.DataFrame, clock: str = "utc") -> np.ndarray:
    """Information only, for the Market tab: the median raw body in bps per weekday hour, on the kept bars."""
    f = frame.sort_values("open_time").drop_duplicates("open_time")
    f = f[(f["volume"] > 0) & (f[["open", "close"]] > 0).all(axis=1)]
    t = pd.Series(to_utc(f["open_time"].to_numpy()))
    c = slots(t, clock)
    body = np.abs(np.log(f["close"].to_numpy() / f["open"].to_numpy())) * 1e4
    wk = c["dow"].to_numpy() < 5
    hours = c["hour"].to_numpy()[wk]
    vals = body[wk]
    return np.array([float(np.median(vals[hours == h])) if (hours == h).any() else np.nan for h in range(24)])


def summary_rows(by_coin: Mapping[str, Mapping[str, Profiles]], measure: str) -> List[dict]:
    """Every coin's weekday-hours profile per half and clock, as rows for the profiles file."""
    rows = []
    for coin, p in by_coin.items():
        for half, prof in p.items():
            for clock in CLOCKS:
                for h, v in enumerate(prof.hours[clock]):
                    rows.append({"coin": coin, "measure": measure, "half": half, "clock": clock, "hour": h,
                                 "swing": None if not np.isfinite(v) else round(float(v), 6)})
    return rows


def week_slot_name(i: int) -> str:
    return f"{('Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun')[i // 24]} {i % 24:02d}:00"


def describe_hour(h: int, clock: str) -> str:
    return f"{h:02d}:00 {'UTC' if clock == 'utc' else 'New York'}"


def as_optional(x: float) -> Optional[float]:
    return None if x is None or not np.isfinite(x) else float(x)
