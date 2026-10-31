"""What a fill would have cost, replayed on the venue's own prints and quotes.

Pure: arrays in, numbers out, no I/O. Times are integer milliseconds UTC. A positive cost is money
lost, in bps of the mid at the decision.

* `tape_fill`: a taker working `notional` at a fixed share of the same-side aggressive flow, from
  the decision on. Works wherever prints exist (all of 2021-26). A print is already at the touch,
  so the half-spread is inside the number.
* `depth_cost`: one instant sweep, from `bookDepth`'s cumulative depth at +/-1%, assuming depth
  grows linearly from the touch. That file holds nothing finer, so this is a coarse number (2023 on).
* `queue_fill`: a resting order at the touch, back of the queue, from `bookTicker` and prints
  (2023-05-16 to 2024-03-30 only). Fills as aggressive volume at or through its price clears what
  was ahead of it and then the order itself; cancels are never credited as queue ahead leaving.
* `flow_buckets` and `fit_impact`: a replay cannot show an order's own impact, because the prints do
  not react to it. So impact comes from the market's: return = a + b * sign(flow) * sqrt(|flow| / daily
  volume) over five-minute buckets, per symbol and volatility regime. The market's flow includes the
  informed part, so this errs toward too much impact, against the view that execution did not matter.
* `markouts`: the fill against the mid at later horizons, by size.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Optional, Sequence, Tuple

import numpy as np
import pandas as pd

PARTICIPATION = 0.10
MID_MAX_AGE_MS = 60_000
HORIZONS_S = (1, 10, 60, 300, 1800, 3600)
SIZES = (1_000.0, 10_000.0, 100_000.0, 1_000_000.0)
REGIMES = ("low", "mid", "high")
BUCKET_MS = 300_000


def proxy_mid(t: np.ndarray, price: np.ndarray, buyer_maker: np.ndarray, at: np.ndarray,
              max_age_ms: int = MID_MAX_AGE_MS) -> np.ndarray:
    """Midpoint of the last buyer-aggressor and last seller-aggressor print at or before each time
    in `at`; NaN when either is older than `max_age_ms` or they cross (#39's proxy, validated there)."""
    at = np.asarray(at)
    buys, sells = ~buyer_maker, buyer_maker
    tb, pb, ts, ps = t[buys], price[buys], t[sells], price[sells]
    out = np.full(at.shape, np.nan)
    if not len(tb) or not len(ts):
        return out
    ib = np.searchsorted(tb, at, side="right") - 1
    js = np.searchsorted(ts, at, side="right") - 1
    ok = (ib >= 0) & (js >= 0)
    ok[ok] &= (at[ok] - tb[ib[ok]] <= max_age_ms) & (at[ok] - ts[js[ok]] <= max_age_ms)
    ask, bid = pb[ib[ok]], ps[js[ok]]
    vals = (ask + bid) / 2
    vals[bid > ask] = np.nan
    out[ok] = vals
    return out


def decision_mid(t: np.ndarray, price: np.ndarray, buyer_maker: np.ndarray, t0: int) -> float:
    """The mid at `t0`. A daily file opens at 00:00, so a decision then has no earlier prints: the
    reference is the first uncrossed moment after both sides have printed, within `MID_MAX_AGE_MS`."""
    m = float(proxy_mid(t, price, buyer_maker, np.array([t0]))[0])
    if np.isfinite(m):
        return m
    a = int(np.searchsorted(t, t0, side="left"))
    b = int(np.searchsorted(t, t0 + MID_MAX_AGE_MS, side="right"))
    mids = proxy_mid(t, price, buyer_maker, t[a:b])
    good = mids[np.isfinite(mids)]
    return float(good[0]) if len(good) else float("nan")


@dataclass(frozen=True)
class Fill:
    cost_bps: float             # against the mid at the decision; NaN if no mid
    filled: float               # share of the notional done before the data ended
    price: float                # average fill
    mid0: float
    end_ms: int                 # when the last piece filled
    prints: int


def tape_fill(t: np.ndarray, price: np.ndarray, qty: np.ndarray, buyer_maker: np.ndarray, t0: int, side: int,
              notional: float, participation: float = PARTICIPATION) -> Fill:
    """Work `notional` from `t0` at `participation` of same-side aggressive flow.

    `side` is +1 to buy (lifting offers: the prints where the buyer was the aggressor) and -1 to sell.
    A leg the day cannot finish reports `filled` < 1 at the price of what was done.
    """
    mid0 = decision_mid(t, price, buyer_maker, t0)
    start = int(np.searchsorted(t, t0, side="left"))
    same = (~buyer_maker[start:]) if side > 0 else buyer_maker[start:]
    px, q, tt = price[start:][same], qty[start:][same], t[start:][same]
    if not len(px):
        return Fill(float("nan"), 0.0, float("nan"), mid0, t0, 0)
    usd = px * q * participation
    cum = np.cumsum(usd)
    last = int(np.searchsorted(cum, notional, side="left"))
    if last >= len(cum):
        done, take = cum[-1], usd
        n = len(cum)
    else:
        take = usd[: last + 1].copy()
        take[-1] -= cum[last] - notional
        done, n = notional, last + 1
    units = (take / px[:n]).sum()
    avg = done / units
    cost = side * (avg - mid0) / mid0 * 1e4 if np.isfinite(mid0) else float("nan")
    return Fill(cost, float(done / notional), float(avg), mid0, int(tt[n - 1]), n)


def depth_cost(depth_at_1pct_usd: float, notional: float) -> float:
    """Average slippage in bps sweeping `notional` at once, depth linear from the touch to +/-1%.

    Cost grows linearly with the fraction of the 1% depth used: half the distance to the last unit.
    Beyond the 1% band the file knows nothing, so the result is NaN rather than an extrapolation.
    """
    if not depth_at_1pct_usd > 0 or notional > depth_at_1pct_usd:
        return float("nan")
    return 0.5 * 100.0 * (notional / depth_at_1pct_usd)


@dataclass(frozen=True)
class QueueFill:
    filled: bool
    ms_to_fill: float           # NaN if never
    fill_price: float
    cost_bps: float             # against the mid at the decision; a maker fill can be negative
    crossed: bool               # gave up at the deadline and crossed the spread


def queue_fill(book_t: np.ndarray, bid: np.ndarray, bid_qty: np.ndarray, ask: np.ndarray, ask_qty: np.ndarray,
               t: np.ndarray, price: np.ndarray, qty: np.ndarray, buyer_maker: np.ndarray, t0: int, side: int,
               units: float, ttl_ms: int) -> Optional[QueueFill]:
    """Post at the touch at `t0` behind everything shown there; None if no quote is live at `t0`.

    A buy rests on the bid. Sellers hitting at our price eat the queue, then us. A print below our
    price clears what is ahead, and that print's size then goes to us. If `ttl_ms` passes, cross at the
    ask then in force.
    """
    i = int(np.searchsorted(book_t, t0, side="right")) - 1
    if i < 0 or t0 - book_t[i] > MID_MAX_AGE_MS:
        return None
    mid0 = (bid[i] + ask[i]) / 2
    rest = bid[i] if side > 0 else ask[i]
    ahead = float(bid_qty[i] if side > 0 else ask_qty[i])
    need = float(units)
    deadline = t0 + ttl_ms
    a = int(np.searchsorted(t, t0, side="left"))
    b = int(np.searchsorted(t, deadline, side="right"))
    for k in range(a, b):
        hits_us = bool(buyer_maker[k]) if side > 0 else not buyer_maker[k]
        if not hits_us:
            continue
        through = price[k] < rest if side > 0 else price[k] > rest
        at_price = price[k] == rest
        if through:
            # the level was cleared, but our own size would have stood in the way: only the flow fills it
            ahead = 0.0
            need -= qty[k]
        elif at_price:
            take = qty[k]
            used = min(ahead, take)
            ahead -= used
            need -= take - used
        if need <= 0:
            cost = side * (rest - mid0) / mid0 * 1e4
            return QueueFill(True, float(t[k] - t0), float(rest), float(cost), False)
    j = int(np.searchsorted(book_t, deadline, side="right")) - 1
    px = float(ask[j] if side > 0 else bid[j])
    return QueueFill(False, float("nan"), px, float(side * (px - mid0) / mid0 * 1e4), True)


def regime_edges(trailing_vol: pd.Series) -> Tuple[float, float]:
    """Tercile cuts of a symbol's trailing volatility. Fit once, then frozen for later periods."""
    v = trailing_vol.dropna()
    return float(v.quantile(1 / 3)), float(v.quantile(2 / 3))


def regime_of(vol: float, edges: Tuple[float, float]) -> str:
    if not np.isfinite(vol):
        return "mid"
    return REGIMES[0] if vol <= edges[0] else (REGIMES[1] if vol <= edges[1] else REGIMES[2])


def flow_buckets(t: np.ndarray, price: np.ndarray, qty: np.ndarray, buyer_maker: np.ndarray, adv: float,
                 bucket_ms: int = BUCKET_MS) -> pd.DataFrame:
    """Per five-minute bucket: return in bps and the signed square root of net aggressive dollars over
    daily volume. A bucket's return runs from its first print to the next bucket's first print."""
    if not len(t) or not adv > 0:
        return pd.DataFrame(columns=["ret_bps", "x"])
    k = t // bucket_ms
    edges = np.flatnonzero(np.r_[True, k[1:] != k[:-1]])
    first = price[edges]
    signed = np.where(buyer_maker, -1.0, 1.0) * price * qty
    flow = np.add.reduceat(signed, edges)
    return pd.DataFrame({"ret_bps": (first[1:] / first[:-1] - 1) * 1e4,
                         "x": (np.sign(flow) * np.sqrt(np.abs(flow) / adv))[:-1]})


def fit_impact(obs: pd.DataFrame, min_obs: int = 200) -> pd.DataFrame:
    """OLS of ret_bps on x, for each symbol and regime with enough buckets.

    `obs` needs symbol, regime, ret_bps, x. Returns a, b (bps per unit of sqrt participation), r2, n.
    Too few buckets gives no row: nothing is imputed.
    """
    rows = []
    for (sym, reg), g in obs.dropna(subset=["ret_bps", "x"]).groupby(["symbol", "regime"]):
        if len(g) < min_obs or np.ptp(g["x"].to_numpy()) == 0:
            continue
        x, y = g["x"].to_numpy(), g["ret_bps"].to_numpy()
        b, a = np.polyfit(x, y, 1)
        res = y - (a + b * x)
        tss = ((y - y.mean()) ** 2).sum()
        rows.append({"symbol": sym, "regime": reg, "a_bps": a, "b_bps": b,
                     "r2": 1 - (res ** 2).sum() / tss if tss else float("nan"), "n": len(g)})
    return pd.DataFrame(rows, columns=["symbol", "regime", "a_bps", "b_bps", "r2", "n"])


def predict_impact(fit: pd.DataFrame, symbol: str, regime: str, notional: float, adv: float) -> float:
    """Bps of impact for `notional`, from the frozen slope. The intercept is drift, not cost."""
    row = fit[(fit["symbol"] == symbol) & (fit["regime"] == regime)]
    if row.empty or not adv > 0:
        return float("nan")
    return float(max(row["b_bps"].iloc[0], 0.0) * np.sqrt(notional / adv))


def markouts(t: np.ndarray, price: np.ndarray, buyer_maker: np.ndarray, end_ms: int, side: int, fill_price: float,
             horizons_s: Sequence[int] = HORIZONS_S) -> Dict[int, float]:
    """P&L in bps of a fill against the mid h seconds after it finished (positive: the fill was good)."""
    at = np.array([end_ms + h * 1000 for h in horizons_s])
    mids = proxy_mid(t, price, buyer_maker, at)
    return {h: float(side * (m - fill_price) / fill_price * 1e4) for h, m in zip(horizons_s, mids)}


def weeks_from_legs(week_starts: Sequence[pd.Timestamp], held: Dict[pd.Timestamp, Optional[str]],
                    opens: pd.DataFrame) -> pd.Series:
    """Gross log return of a one-coin book per week, open to next open, on `opens` (index dates, one
    column per coin). Flat weeks earn zero. A held coin with no price raises: a hole never reads as flat."""
    out = {}
    for a, b in zip(week_starts[:-1], week_starts[1:]):
        coin = held.get(a)
        if coin is None:
            out[a] = 0.0
            continue
        pa, pb = opens.at[a, coin], opens.at[b, coin]
        if not (np.isfinite(pa) and np.isfinite(pb)):
            raise ValueError(f"no price for held {coin} on {a} or {b}")
        out[a] = float(np.log(pb / pa))
    return pd.Series(out)
