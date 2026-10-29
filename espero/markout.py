"""What a fill costs, measured on prints (#39, research/PREREGISTRATION_MARKOUT.md).

Pure: arrays in, frames out, no I/O. Times are integer milliseconds UTC.

* prints carry an aggressor sign s (+1 a buyer lifted the ask, -1 a seller hit
  the bid); the maker on the other side has sign -s.
* a mid is either a real quote (bid + ask) / 2 or the trade proxy
  (last buyer print + last seller print) / 2, missing when either is older
  than 60 s or they cross.
* three measures, in bps: the taker's effective half-spread against the mid
  just before the print; the optimistic maker markout of every print; the
  conservative maker markout, once per level cleared, from the first print
  through it (the back of the queue fills only then).
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from statistics import NormalDist
from typing import Dict, List, Optional, Sequence

import numpy as np
import pandas as pd

HORIZONS_S = (1, 10, 60, 300)
PROXY_MAX_AGE_MS = 60_000
FLOW_WINDOW_MS = 10_000
FLOW_CUT = 1 / 3
SETTLE_S = 8 * 3600
SETTLE_WINDOW_S = 300
MIN_PRINTS = 1000
TOL_BPS = 0.25
TOL_REL = 0.20
PRIOR_TESTS = 39
CELLS = 2 * 4 * 10 * 4             # venues x coins x condition levels x horizons
BAR = 4.596                        # checked against bar(PRIOR_TESTS + CELLS)
FEES_BPS = {"binance": {"taker": 5.0, "maker": 2.0}, "hyperliquid": {"taker": 4.5, "maker": 1.5}}
CONDITIONS = {"spread": ("tight", "wide"), "flow": ("against", "neutral", "with"),
              "funding": ("settlement", "other"), "liq": ("liq_hour", "other")}
INFO = {"hour": tuple(f"{h:02d}" for h in range(24)), "size": ("small", "big")}   # information only
LEVELS = {**CONDITIONS, **INFO}


@dataclass
class Prints:
    t: np.ndarray      # int64 ms, sorted
    p: np.ndarray      # float
    q: np.ndarray      # float, base units
    s: np.ndarray      # int8, aggressor sign

    @classmethod
    def frame(cls, df: pd.DataFrame) -> "Prints":
        df = df.sort_values("t", kind="stable")
        return cls(df["t"].to_numpy(np.int64), df["p"].to_numpy(float), df["q"].to_numpy(float),
                   df["s"].to_numpy(np.int8))

    def __len__(self) -> int:
        return len(self.t)


def collapse(df: pd.DataFrame) -> pd.DataFrame:
    """One row per aggressor, price and millisecond (Binance's aggTrade unit), so
    sources that publish single fills and sources that aggregate count alike."""
    g = df.groupby(["t", "s", "p"], sort=False, as_index=False)["q"].sum()
    return g.sort_values("t", kind="stable").reset_index(drop=True)


@dataclass
class Mids:
    """A step function of the mid. `born` is when the value became knowable in
    full; a value older than `max_age` ms at the asking time is missing."""
    t: np.ndarray
    mid: np.ndarray
    spread: np.ndarray
    born: np.ndarray
    max_age: float = math.inf

    def at(self, when: np.ndarray, strict: bool = False):
        """(mid, spread) at each time: the last value at or before it, or
        strictly before it when `strict` (the mid a print traded against)."""
        when = np.asarray(when, dtype=np.int64)
        i = np.searchsorted(self.t, when, side="left" if strict else "right") - 1
        ok = i >= 0
        j = np.where(ok, i, 0)
        ok &= (when - self.born[j]) <= self.max_age
        mid = np.where(ok, self.mid[j], np.nan)
        spr = np.where(ok, self.spread[j], np.nan)
        return mid, spr


def quote_mids(t, bid, ask) -> Mids:
    """Real quotes: the last update in each millisecond stands."""
    t = np.asarray(t, dtype=np.int64)
    bid, ask = np.asarray(bid, float), np.asarray(ask, float)
    order = np.argsort(t, kind="stable")
    t, bid, ask = t[order], bid[order], ask[order]
    last = np.r_[t[1:] != t[:-1], True]
    t, bid, ask = t[last], bid[last], ask[last]
    good = (bid > 0) & (ask >= bid)
    mid = np.where(good, (bid + ask) / 2, np.nan)
    return Mids(t, mid, np.where(good, ask - bid, np.nan), t)


def proxy_mids(pr: Prints, max_age: float = PROXY_MAX_AGE_MS) -> Mids:
    """(last buyer-aggressor price + last seller-aggressor price) / 2, the state
    after each millisecond's prints; missing if they cross or either is stale."""
    n = len(pr)
    idx = np.arange(n)
    buy_i = np.where(pr.s > 0, idx, -1)
    sell_i = np.where(pr.s < 0, idx, -1)
    buy_i = np.maximum.accumulate(buy_i)
    sell_i = np.maximum.accumulate(sell_i)
    last = np.r_[pr.t[1:] != pr.t[:-1], True]
    t, bi, si = pr.t[last], buy_i[last], sell_i[last]
    have = (bi >= 0) & (si >= 0)
    a = np.where(have, pr.p[np.maximum(bi, 0)], np.nan)
    b = np.where(have, pr.p[np.maximum(si, 0)], np.nan)
    good = have & (a >= b)
    born = np.where(have, np.minimum(pr.t[np.maximum(bi, 0)], pr.t[np.maximum(si, 0)]), np.iinfo(np.int64).min)
    return Mids(t, np.where(good, (a + b) / 2, np.nan), np.where(good, a - b, np.nan), born, max_age)


def tick(p: np.ndarray) -> float:
    """The smallest positive gap between distinct prices that day."""
    u = np.unique(np.round(np.asarray(p, float), 10))
    d = np.diff(u)
    d = d[d > 1e-12]
    return float(d.min()) if len(d) else math.nan


def flow(pr: Prints, when: np.ndarray, window: int = FLOW_WINDOW_MS) -> np.ndarray:
    """Trade imbalance (buy - sell notional) / total over [when - window, when)."""
    notional = pr.p * pr.q
    cs = np.r_[0.0, np.cumsum(pr.s * notional)]
    ct = np.r_[0.0, np.cumsum(notional)]
    hi = np.searchsorted(pr.t, when, side="left")
    lo = np.searchsorted(pr.t, np.asarray(when) - window, side="left")
    tot = ct[hi] - ct[lo]
    with np.errstate(invalid="ignore", divide="ignore"):
        return np.where(tot > 0, (cs[hi] - cs[lo]) / tot, 0.0)


def settlement(when: np.ndarray) -> np.ndarray:
    sec = (np.asarray(when, dtype=np.int64) // 1000) % SETTLE_S
    return (sec <= SETTLE_WINDOW_S) | (sec >= SETTLE_S - SETTLE_WINDOW_S)


def cleared(pr: Prints):
    """Back-of-the-queue fills: for each side, a level is active once an
    aggressor printed at it and is cleared, once, by the first aggressor print
    of that side strictly through it. Returns (time, level, maker sign)."""
    out_t: List[int] = []
    out_p: List[float] = []
    out_s: List[int] = []
    for side in (-1, 1):                 # -1: sellers clear resting bids; +1: buyers clear asks
        sel = pr.s == side
        ts, ps = pr.t[sel], pr.p[sel]
        stack: List[float] = []
        for k in range(len(ts)):
            x = ps[k]
            if side < 0:
                while stack and stack[-1] > x:
                    out_t.append(int(ts[k]))
                    out_p.append(stack.pop())
                    out_s.append(1)
            else:
                while stack and stack[-1] < x:
                    out_t.append(int(ts[k]))
                    out_p.append(stack.pop())
                    out_s.append(-1)
            if not stack or stack[-1] != x:
                stack.append(x)
    order = np.argsort(np.asarray(out_t, dtype=np.int64), kind="stable")
    return (np.asarray(out_t, dtype=np.int64)[order], np.asarray(out_p, float)[order],
            np.asarray(out_s, dtype=np.int8)[order])


def _levels(spread_ticks, a, when, liq, big=None) -> Dict[str, np.ndarray]:
    """Each condition as integer codes into LEVELS[cond]; -1 where unknown."""
    sp = np.where(np.isnan(spread_ticks), -1, np.where(spread_ticks <= 1 + 1e-6, 0, 1))
    fl = np.where(a <= -FLOW_CUT, 0, np.where(a >= FLOW_CUT, 2, 1))
    out = {"spread": sp, "flow": fl, "funding": np.where(settlement(when), 0, 1)}
    if liq is not None:
        out["liq"] = np.where(liq, 0, 1)
    out["hour"] = (np.asarray(when, dtype=np.int64) // 3_600_000) % 24
    if big is not None:
        out["size"] = np.where(big, 1, 0)
    return out


def _liq_flags(when: np.ndarray, liq_hours: Optional[np.ndarray]) -> Optional[np.ndarray]:
    if liq_hours is None:
        return None
    hour = (np.asarray(when, dtype=np.int64) // 3_600_000) * 3_600_000
    return np.isin(hour, liq_hours)


def measures(pr: Prints, mids: Mids, liq_hours: Optional[np.ndarray] = None,
             horizons: Sequence[int] = HORIZONS_S) -> pd.DataFrame:
    """One row per (measure, horizon, condition, level): the day's n and mean in bps."""
    tk = tick(pr.p)
    rows = []

    def add(measure, horizon, vals, levels):
        ok = ~np.isnan(vals)
        rows.append((measure, horizon, "all", "all", int(ok.sum()), float(vals[ok].mean()) if ok.any() else math.nan))
        for cond, code in levels.items():
            names = LEVELS[cond]
            m = ok & (code >= 0)
            cnt = np.bincount(code[m], minlength=len(names))
            tot = np.bincount(code[m], weights=vals[m], minlength=len(names))
            for k, name in enumerate(names):
                rows.append((measure, horizon, cond, name, int(cnt[k]),
                             float(tot[k] / cnt[k]) if cnt[k] else math.nan))

    # taker: the effective half-spread against the mid just before the print
    m0, sp0 = mids.at(pr.t, strict=True)
    c = pr.s * (pr.p - m0) / m0 * 1e4
    a = pr.s * flow(pr, pr.t)
    big = pr.q > np.median(pr.q)
    add("taker", 0, c, _levels(sp0 / tk, a, pr.t, _liq_flags(pr.t, liq_hours), big))

    # optimistic maker: every print, the maker's side
    sm = -pr.s
    a = sm * flow(pr, pr.t)
    lv = _levels(sp0 / tk, a, pr.t, _liq_flags(pr.t, liq_hours), big)
    for h in horizons:
        mh, _ = mids.at(pr.t + h * 1000)
        add("maker_opt", h, sm * (mh - pr.p) / pr.p * 1e4, lv)

    # conservative maker: once per level cleared, from the through print
    ct, cp, cs = cleared(pr)
    if len(ct):
        _, spc = mids.at(ct, strict=True)
        lv = _levels(spc / tk, cs * flow(pr, ct), ct, _liq_flags(ct, liq_hours))
        for h in horizons:
            mh, _ = mids.at(ct + h * 1000)
            add("maker_cons", h, cs * (mh - cp) / cp * 1e4, lv)
    return pd.DataFrame(rows, columns=["measure", "horizon", "cond", "level", "n", "mean"])


def day_stats(days: pd.DataFrame, keys: Sequence[str], halves: Optional[str] = None) -> pd.DataFrame:
    """Each day's mean is one observation: mean of day means, its t, the day
    count; and, with `halves` (a split date), the mean in each half."""
    d = days[days["n"] > 0].dropna(subset=["mean"])

    def one(g):
        x = g["mean"].to_numpy(float)
        n = len(x)
        sd = x.std(ddof=1) if n > 1 else math.nan
        out = {"days": n, "fills": int(g["n"].sum()), "mean": x.mean() if n else math.nan,
               "t": x.mean() / (sd / math.sqrt(n)) if n > 1 and sd > 0 else math.nan}
        if halves is not None:
            first = g["day"] < halves
            out["h1"] = g.loc[first, "mean"].mean()
            out["h2"] = g.loc[~first, "mean"].mean()
        return pd.Series(out)

    return d.groupby(list(keys)).apply(one).reset_index()


def bar(n_trials: int, alpha: float = 0.05) -> float:
    """Bailey & Lopez de Prado's expected maximum of n null t's, plus the one-sided
    5% quantile: the deflated hurdle in t units with unit null variance."""
    nd, g = NormalDist(), 0.5772156649015329
    e = (1 - g) * nd.inv_cdf(1 - 1 / n_trials) + g * nd.inv_cdf(1 - 1 / (n_trials * math.e))
    return e + nd.inv_cdf(1 - alpha)


def within(x: float, ref: float, tol_bps: float = TOL_BPS, tol_rel: float = TOL_REL) -> bool:
    if not (np.isfinite(x) and np.isfinite(ref)):
        return False
    return abs(x - ref) <= max(tol_bps, tol_rel * abs(ref))


def agree(a: pd.DataFrame, b: pd.DataFrame, keys: Sequence[str]) -> pd.DataFrame:
    """Cell-by-cell comparison of two stats tables on `keys` (a is tested, b the reference)."""
    m = a.merge(b, on=list(keys), suffixes=("", "_ref"), how="outer")
    m["ok"] = [within(x, r) for x, r in zip(m["mean"], m["mean_ref"])]
    return m


def q3(stats: pd.DataFrame, validated: Optional[set] = None, replicated: bool = True,
       bar_t: float = BAR) -> pd.DataFrame:
    """The cells that answer YES: conservative maker markout net of the venue's
    maker fee > 0 with t >= the bar and > 0 in both halves; on Binance only on a
    validated (coin, horizon) and only if the second source replicated."""
    pre = stats["cond"].isin(["all", *CONDITIONS])
    s = stats[(stats["measure"] == "maker_cons") & pre].copy()
    fee = s["venue"].map(lambda v: FEES_BPS[v]["maker"])
    s["net"] = s["mean"] - fee
    s["net_h1"], s["net_h2"] = s["h1"] - fee, s["h2"] - fee
    s["t_net"] = s["t"] * s["net"] / s["mean"]
    ok = (s["net"] > 0) & (s["t_net"] >= bar_t) & (s["net_h1"] > 0) & (s["net_h2"] > 0)
    if validated is not None:
        on_b = s["venue"] == "binance"
        val = [(c, h) in validated for c, h in zip(s["coin"], s["horizon"])]
        ok &= ~on_b | (np.asarray(val) & replicated)
    s["pass"] = ok
    return s
