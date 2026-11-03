"""Robustness readouts reported beside every result from #61 on (research/ROBUSTNESS_STANDARD.md).

Deflated Sharpe, PBO by CSCV, purged k-fold with embargo, signal half-life, turnover, capacity from
recorded depth.

Pure: arrays in, numbers out. None of these is a pass bar; FDR and t ≥ 3 stay the bar
(research/FDR_STANDARD.md). They say how much of a result survives the ways results usually don't: the
trials behind it (deflated Sharpe, `espero.trials`), the choice among configurations (PBO), leakage across
the fold boundary (purged k-fold), how fast the signal fades (half-life), how much it trades (turnover),
and how much money the recorded book would carry at the measured edge (capacity).

A second table, for sleeves at their sizing document and the family's judgment (research/ROBUSTNESS_LIVE.md):
BTC beta of each sleeve and of the dip-buying cluster (#22, #24, #31), lower-tail dependence between sleeves
beside #63's Pearson correlation, the split by year and by funding regime, and the deflated Sharpe at the
intended size, net of the extra impact the recorded book charges there. Reported, never decisive.
"""

from __future__ import annotations

import math
from itertools import combinations
from typing import Dict, List, Optional, Sequence, Tuple

import numpy as np
import pandas as pd

from . import trials

MAX_COMBINATIONS = 2000


# ------------------------------------------------------------------ deflated Sharpe
def sharpe_moments(returns: Sequence[float]) -> Dict[str, float]:
    r = np.asarray(returns, dtype=float)
    r = r[np.isfinite(r)]
    n = len(r)
    if n < 3 or r.std(ddof=1) == 0:
        return {"n": n, "sharpe": float("nan"), "skew": float("nan"), "kurt": float("nan")}
    m, s = r.mean(), r.std(ddof=1)
    z = (r - m) / s
    return {"n": n, "sharpe": float(m / s), "skew": float((z**3).mean()), "kurt": float((z**4).mean())}


def deflated_sharpe(returns: Sequence[float], n_trials: int, var_sharpe: float) -> Dict[str, float]:
    """Bailey & López de Prado's deflated Sharpe: the probability the per-observation Sharpe beats what
    the best of `n_trials` null trials reaches on average, given the variance of the trials' Sharpes.
    `n_trials` is the ledger's count when the test is judged; `var_sharpe` the variance of their
    per-observation Sharpes (`trials_dsr.csv`), never zero."""
    mo = sharpe_moments(returns)
    if not math.isfinite(mo["sharpe"]) or n_trials < 1:
        return {**mo, "n_trials": n_trials, "expected_max": float("nan"), "dsr": float("nan")}
    emax = trials.expected_max_sharpe(n_trials, var_sharpe)
    dsr = trials.psr(mo["sharpe"], emax, mo["n"], mo["skew"], mo["kurt"])
    return {**mo, "n_trials": n_trials, "expected_max": float(emax), "dsr": float(dsr)}


# ------------------------------------------------------------------ PBO by CSCV
def pbo_cscv(
    matrix: np.ndarray, splits: int = 16, seed: int = 0, max_combinations: int = MAX_COMBINATIONS
) -> Dict[str, object]:
    """Probability of backtest overfitting, Bailey, Borwein, López de Prado & Zhu (2017): T × N returns
    (one column per configuration tried), T cut into `splits` blocks, every half-and-half pairing of the
    blocks a train/test pair; the configuration best on train is ranked on test; PBO is the share of
    pairings where that rank is below the median. With one configuration there is nothing to overfit
    among: `pbo` is NaN and `applicable` False."""
    m = np.asarray(matrix, dtype=float)
    if m.ndim != 2 or m.shape[1] < 2 or m.shape[0] < 2 * splits:
        return {
            "applicable": False,
            "pbo": float("nan"),
            "n_configs": int(m.shape[1]) if m.ndim == 2 else 0,
            "pairings": 0,
            "note": "needs at least two configurations and 2 x splits observations",
        }
    t, n = m.shape
    blocks = np.array_split(np.arange(t), splits)
    all_pairs = list(combinations(range(splits), splits // 2))
    rng = np.random.default_rng(seed)
    if len(all_pairs) > max_combinations:
        idx = rng.choice(len(all_pairs), size=max_combinations, replace=False)
        all_pairs = [all_pairs[i] for i in sorted(idx)]
    lambdas = []
    for train_blocks in all_pairs:
        test_blocks = [b for b in range(splits) if b not in train_blocks]
        tr = np.concatenate([blocks[b] for b in train_blocks])
        te = np.concatenate([blocks[b] for b in test_blocks])
        s_tr = _sharpes(m[tr])
        s_te = _sharpes(m[te])
        best = int(np.nanargmax(s_tr))
        rank = (np.sum(s_te < s_te[best]) + 0.5 * np.sum(s_te == s_te[best])) / n  # relative rank in (0, 1)
        omega = min(max(rank, 1 / (2 * n)), 1 - 1 / (2 * n))
        lambdas.append(math.log(omega / (1 - omega)))
    lam = np.asarray(lambdas)
    return {
        "applicable": True,
        "pbo": float((lam < 0).mean()),
        "n_configs": n,
        "pairings": len(lam),
        "lambda_median": float(np.median(lam)),
        "note": "",
    }


def _sharpes(block: np.ndarray) -> np.ndarray:
    mu = block.mean(axis=0)
    sd = block.std(axis=0, ddof=1)
    with np.errstate(divide="ignore", invalid="ignore"):
        return np.where(sd > 0, mu / sd, -np.inf)


# ------------------------------------------------------------------ purged k-fold with embargo
def purged_kfold(
    t0: Sequence[int], t1: Sequence[int], k: int = 5, embargo: float = 0.01
) -> List[Tuple[np.ndarray, np.ndarray]]:
    """López de Prado's purged k-fold: each observation spans [t0, t1] (its label's start and end, in bar
    index). Test folds are contiguous blocks of observations; a training observation whose span overlaps
    the test span is purged, and the `embargo` share of the bar range after the test span is dropped too.
    Returns (train_idx, test_idx) per fold."""
    t0 = np.asarray(t0, dtype=np.int64)
    t1 = np.asarray(t1, dtype=np.int64)
    n = len(t0)
    if n == 0 or k < 2 or len(t1) != n or np.any(t1 < t0):
        raise ValueError("purged_kfold needs t1 >= t0 for every observation and k >= 2")
    order = np.argsort(t0, kind="stable")
    span = int(t1.max() - t0.min() + 1)
    h = int(math.ceil(embargo * span))
    out = []
    for fold in np.array_split(order, k):
        test_start, test_end = int(t0[fold].min()), int(t1[fold].max())
        keep = (t1 < test_start) | (t0 > test_end + h)  # no overlap with the test span, past the embargo
        keep[fold] = False
        out.append((np.flatnonzero(keep), np.sort(fold)))
    return out


# ------------------------------------------------------------------ half-life, turnover
def half_life(signal: Sequence[float]) -> Dict[str, float]:
    """AR(1) on the signal: half-life = -ln 2 / ln φ, in the series' own bars. φ outside (0, 1) has no
    half-life (NaN): the signal does not decay, or flips."""
    x = np.asarray(signal, dtype=float)
    x = x[np.isfinite(x)]
    if len(x) < 10:
        return {"phi": float("nan"), "half_life": float("nan"), "n": len(x)}
    a, b = x[:-1] - x[:-1].mean(), x[1:] - x[1:].mean()
    denom = float((a * a).sum())
    phi = float((a * b).sum() / denom) if denom > 0 else float("nan")
    hl = -math.log(2) / math.log(phi) if 0 < phi < 1 else float("nan")
    return {"phi": phi, "half_life": hl, "n": len(x)}


def turnover(weights: pd.DataFrame, periods_per_year: Optional[float] = None) -> Dict[str, float]:
    """Mean one-way turnover per period: half the sum of |Δw| across assets (a full switch from one asset
    to another is 1.0). Annualised when `periods_per_year` is given."""
    w = weights.fillna(0.0).astype(float)
    per = (w.diff().abs().sum(axis=1) / 2.0).iloc[1:]
    mean = float(per.mean()) if len(per) else float("nan")
    return {
        "per_period": mean,
        "annual": mean * periods_per_year if periods_per_year else float("nan"),
        "periods": int(len(per)),
    }


# ------------------------------------------------------------------ capacity from recorded depth
def sweep_cost_bps(levels: Sequence[Tuple[float, float]], mid: float, notional: float) -> float:
    """Average slippage in bps of mid for `notional` dollars swept through `levels` (price, size), best
    first, on one side; NaN when the recorded levels cannot hold it."""
    need, usd, units = notional, 0.0, 0.0
    for px, sz in levels:
        take = min(px * sz, need)
        units += take / px
        usd += take
        need -= take
        if need <= 1e-9:
            break
    if need > 1e-9 or units <= 0:
        return float("nan")
    return abs(usd / units - mid) / mid * 1e4


def capacity(levels: Sequence[Tuple[float, float]], mid: float, edge_bps: float, grid: int = 60) -> Dict[str, float]:
    """The largest notional the recorded side of the book fills at an average slippage within `edge_bps`
    (the measured edge a trade must keep), by bisection on a dollar grid; `depth_usd` is everything the
    recorded levels hold. Capacity is at most the recorded depth: beyond it the book is unknown, not deep."""
    depth = float(sum(px * sz for px, sz in levels))
    if depth <= 0 or not mid > 0:
        return {"capacity_usd": 0.0, "depth_usd": depth, "edge_bps": edge_bps}
    if not (sweep_cost_bps(levels, mid, depth) <= edge_bps):
        lo, hi = 0.0, depth
        for _ in range(grid):
            m = (lo + hi) / 2
            c = sweep_cost_bps(levels, mid, m)
            if math.isfinite(c) and c <= edge_bps:
                lo = m
            else:
                hi = m
        cap = lo
    else:
        cap = depth
    return {"capacity_usd": float(cap), "depth_usd": depth, "edge_bps": edge_bps}


def capacity_from_hlbook(slot: pd.DataFrame, coin: str, side: str, edge_bps: float) -> Dict[str, float]:
    """`capacity` on one `data/hlbook` slot file (ts, valid_ms, coin, side, level, px, sz, n): a buy sweeps
    the asks, a sell the bids; mid is the touch's midpoint."""
    c = slot[slot["coin"] == coin]
    bids = c[c["side"] == "bid"].sort_values("level")
    asks = c[c["side"] == "ask"].sort_values("level")
    if bids.empty or asks.empty:
        return {"capacity_usd": 0.0, "depth_usd": 0.0, "edge_bps": edge_bps}
    mid = (float(bids["px"].iloc[0]) + float(asks["px"].iloc[0])) / 2
    side_levels = asks if side == "buy" else bids
    return capacity(list(zip(side_levels["px"].astype(float), side_levels["sz"].astype(float))), mid, edge_bps)


def block(
    returns: Optional[Sequence[float]] = None,
    n_trials: int = 0,
    var_sharpe: float = float("nan"),
    configs: Optional[np.ndarray] = None,
    signal: Optional[Sequence[float]] = None,
    weights: Optional[pd.DataFrame] = None,
    periods_per_year: Optional[float] = None,
    book: Optional[Tuple[Sequence[Tuple[float, float]], float]] = None,
    edge_bps: float = float("nan"),
) -> Dict[str, object]:
    """The whole readout for a results document: each line computed where its input exists, "not
    applicable" with the reason where it does not. A measurement with no return series gets all six as
    not applicable, and says so."""
    out: Dict[str, object] = {}
    out["deflated_sharpe"] = (
        deflated_sharpe(returns, n_trials, var_sharpe)
        if returns is not None and n_trials and math.isfinite(var_sharpe)
        else {"applicable": False, "note": "no return series, trial count or trial variance"}
    )
    out["pbo"] = pbo_cscv(configs) if configs is not None else {"applicable": False, "note": "no configurations tried"}
    out["half_life"] = half_life(signal) if signal is not None else {"applicable": False, "note": "no signal series"}
    out["turnover"] = (
        turnover(weights, periods_per_year) if weights is not None else {"applicable": False, "note": "no weights"}
    )
    out["capacity"] = (
        capacity(book[0], book[1], edge_bps)
        if book is not None and math.isfinite(edge_bps)
        else {"applicable": False, "note": "no recorded book or no measured edge"}
    )
    out["purged_kfold"] = {"applicable": False, "note": "a fold scheme, used by a test's own script, not a number"}
    return out


def render(b: Dict[str, object]) -> str:
    """The block as the results document prints it."""
    lines = ["| readout | value |", "|---|---|"]
    for key, label in (
        ("deflated_sharpe", "Deflated Sharpe"),
        ("pbo", "PBO (CSCV)"),
        ("half_life", "Signal half-life"),
        ("turnover", "Turnover"),
        ("capacity", "Capacity from recorded depth"),
        ("purged_kfold", "Purged k-fold"),
    ):
        v = b[key]
        if isinstance(v, dict) and v.get("applicable") is False:
            lines.append(f"| {label} | not applicable: {v['note']} |")
            continue
        if key == "deflated_sharpe":
            lines.append(
                f"| {label} | DSR {v['dsr']:.3f} (Sharpe/obs {v['sharpe']:.3f}, "
                f"expected max of {v['n_trials']} trials {v['expected_max']:.3f}, n {v['n']}) |"
            )
        elif key == "pbo":
            lines.append(f"| {label} | {v['pbo']:.2f} over {v['n_configs']} configurations, {v['pairings']} pairings |")
        elif key == "half_life":
            lines.append(f"| {label} | {v['half_life']:.1f} bars (φ {v['phi']:.3f}) |")
        elif key == "turnover":
            lines.append(f"| {label} | {v['per_period']:.3f} one-way per period, {v['annual']:.1f} a year |")
        elif key == "capacity":
            lines.append(
                f"| {label} | ${v['capacity_usd']:,.0f} at {v['edge_bps']:.1f} bps "
                f"(recorded depth ${v['depth_usd']:,.0f}) |"
            )
    return "\n".join(lines)



# ------------------------------------------------------------------ the readouts at size (research/ROBUSTNESS_LIVE.md)
DIP_CLUSTER = ("22", "24", "31")          # FORWARD_FAMILY.md rule 6: they buy the same kind of dip
TAIL_Q = 0.05


def _aligned(*series: pd.Series) -> pd.DataFrame:
    return pd.concat([x.rename(i) for i, x in enumerate(series)], axis=1).dropna()


def beta(returns: pd.Series, benchmark: pd.Series) -> Dict[str, float]:
    """OLS beta of a sleeve's daily returns on BTC's, on the days both have, with its plain t and R²."""
    d = _aligned(returns, benchmark)
    n = len(d)
    if n < 10 or d[1].std(ddof=1) == 0:
        return {"n": n, "beta": float("nan"), "alpha": float("nan"), "t_beta": float("nan"), "r2": float("nan")}
    r, b = d[0].to_numpy(), d[1].to_numpy()
    bc = b - b.mean()
    slope = float((bc * (r - r.mean())).sum() / (bc**2).sum())
    alpha = float(r.mean() - slope * b.mean())
    resid = r - alpha - slope * b
    se = math.sqrt(float((resid**2).sum()) / (n - 2) / float((bc**2).sum()))
    sst = float(((r - r.mean()) ** 2).sum())
    return {"n": n, "beta": slope, "alpha": alpha, "t_beta": slope / se if se > 0 else float("nan"),
            "r2": 1 - float((resid**2).sum()) / sst if sst > 0 else float("nan")}


def cluster_beta(sleeves: pd.DataFrame, benchmark: pd.Series, members: Sequence[str] = DIP_CLUSTER) -> Dict[str, float]:
    """The beta of the members' equal-weight daily return (a day a member did not trade is 0, as #63 counts it)."""
    have = [m for m in members if m in sleeves.columns]
    if not have:
        return {"applicable": False, "note": "no member of the cluster passed"}
    out = beta(sleeves[have].fillna(0.0).mean(axis=1), benchmark)
    out["members"] = have
    return out


def lower_tail_dependence(x: pd.Series, y: pd.Series, q: float = TAIL_Q) -> Dict[str, float]:
    """P(y in its lower q tail | x in its lower q tail), against q if the two were independent, beside Pearson."""
    d = _aligned(x, y)
    n = len(d)
    if n < 20:
        return {"n": n, "q": q, "lambda_lower": float("nan"), "n_tail": 0, "pearson": float("nan")}
    qx, qy = d[0].quantile(q), d[1].quantile(q)
    tail = d[0] <= qx
    both = tail & (d[1] <= qy)
    return {"n": n, "q": q, "lambda_lower": float(both.sum() / tail.sum()) if tail.sum() else float("nan"),
            "n_tail": int(tail.sum()), "pearson": float(d[0].corr(d[1]))}


def tail_matrix(sleeves: pd.DataFrame, q: float = TAIL_Q) -> pd.DataFrame:
    """Every pair of sleeves: lower-tail dependence both ways round, the Pearson correlation #63 uses, the counts."""
    rows = []
    cols = list(sleeves.columns)
    for i, a in enumerate(cols):
        for b in cols[i + 1:]:
            ab, ba = lower_tail_dependence(sleeves[a], sleeves[b], q), lower_tail_dependence(sleeves[b], sleeves[a], q)
            rows.append({"a": a, "b": b, "lambda_a_given_b": ba["lambda_lower"], "lambda_b_given_a": ab["lambda_lower"],
                         "pearson": ab["pearson"], "n": ab["n"], "n_tail": ab["n_tail"]})
    return pd.DataFrame(rows, columns=["a", "b", "lambda_a_given_b", "lambda_b_given_a", "pearson", "n", "n_tail"])


def regime_split(returns: pd.Series, labels: pd.Series) -> Dict[str, Dict[str, float]]:
    """The sleeve's daily return in each regime: count, mean, plain t, per-observation Sharpe."""
    d = _aligned(returns, labels)
    out = {}
    for label, g in d.groupby(1)[0]:
        v = g.to_numpy(dtype=float)
        sd = v.std(ddof=1) if len(v) > 1 else float("nan")
        out[str(label)] = {"n": int(len(v)), "mean": float(v.mean()),
                           "t": float(v.mean() / sd * math.sqrt(len(v))) if sd and sd > 0 else float("nan"),
                           "sharpe": float(v.mean() / sd) if sd and sd > 0 else float("nan")}
    return out


def by_year(index: pd.DatetimeIndex) -> pd.Series:
    return pd.Series(index.year.astype(str), index=index)


def funding_regime(funding: pd.Series, window: int = 30) -> pd.Series:
    """'high' where the trailing mean of daily funding is above its median over the whole window, else 'low'.
    Descriptive: the median is the window's, so the split is a reading of the past, not a rule."""
    trail = funding.rolling(window, min_periods=window).mean().dropna()
    return pd.Series(np.where(trail > trail.median(), "high", "low"), index=trail.index)


def extra_cost_bps(levels: Sequence[Tuple[float, float]], mid: float, notional: float, small: float = 1_000.0) -> float:
    """What a round trip costs at `notional` beyond what it costs at `small`, from the recorded side of the book:
    the impact the registered costs (measured at small size) do not hold. NaN past the recorded depth."""
    at, base = sweep_cost_bps(levels, mid, notional), sweep_cost_bps(levels, mid, small)
    return 2 * max(0.0, at - base) if math.isfinite(at) and math.isfinite(base) else float("nan")


def deflated_sharpe_at_size(net_returns: Sequence[float], trades_per_obs: float, extra_bps: float, n_trials: int,
                            var_sharpe: float) -> Dict[str, float]:
    """The deflated Sharpe of the registered net series once each observation pays its trades' extra impact at
    the intended size."""
    r = np.asarray(net_returns, dtype=float) - trades_per_obs * extra_bps / 1e4
    return {**deflated_sharpe(r, n_trials, var_sharpe), "extra_bps": extra_bps, "trades_per_obs": trades_per_obs}


def block_live(sleeves: Optional[pd.DataFrame] = None, btc: Optional[pd.Series] = None,
               labels: Optional[Dict[str, pd.Series]] = None, at_size: Optional[Dict[str, float]] = None,
               net: Optional[Sequence[float]] = None, n_trials: int = 0, var_sharpe: float = float("nan"),
               capacity_usd: Optional[float] = None) -> Dict[str, object]:
    """The second table: each readout where its input exists, "not applicable" with the reason where not."""
    out: Dict[str, object] = {}
    if sleeves is not None and btc is not None:
        out["beta"] = {c: beta(sleeves[c], btc) for c in sleeves.columns}
        out["cluster_beta"] = cluster_beta(sleeves, btc)
    else:
        out["beta"] = out["cluster_beta"] = {"applicable": False, "note": "no sleeve returns or no BTC series"}
    out["tail"] = (tail_matrix(sleeves) if sleeves is not None and sleeves.shape[1] >= 2
                   else {"applicable": False, "note": "fewer than two sleeves"})
    if sleeves is not None and labels:
        out["regimes"] = {name: {c: regime_split(sleeves[c], lab) for c in sleeves.columns}
                          for name, lab in labels.items()}
    else:
        out["regimes"] = {"applicable": False, "note": "no sleeve returns or no regime labels"}
    if net is not None and at_size and n_trials and math.isfinite(var_sharpe):
        out["dsr_at_size"] = deflated_sharpe_at_size(net, at_size["trades_per_obs"], at_size["extra_bps"], n_trials,
                                                     var_sharpe)
        out["dsr_at_size"]["capacity_usd"] = capacity_usd
        out["dsr_at_size"]["notional"] = at_size.get("notional")
    else:
        out["dsr_at_size"] = {"applicable": False, "note": "no net series, intended size or trial count"}
    return out


def render_live(b: Dict[str, object]) -> str:
    lines = ["| readout at size | value |", "|---|---|"]
    for key, label in (("beta", "BTC beta"), ("cluster_beta", "BTC beta, #22/#24/#31 together"),
                       ("tail", "Lower-tail dependence (q 5 %)"), ("regimes", "By year and funding regime"),
                       ("dsr_at_size", "Deflated Sharpe at the intended size")):
        v = b[key]
        if isinstance(v, dict) and v.get("applicable") is False:
            lines.append(f"| {label} | not applicable: {v['note']} |")
        elif key == "beta":
            lines.append(f"| {label} | " + "; ".join(f"#{c} {x['beta']:+.2f} (t {x['t_beta']:.1f}, n {x['n']})"
                                                     for c, x in v.items()) + " |")
        elif key == "cluster_beta":
            lines.append(f"| {label} | {v['beta']:+.2f} (t {v['t_beta']:.1f}, n {v['n']}, members "
                         f"{', '.join('#' + m for m in v['members'])}) |")
        elif key == "tail":
            lines.append(f"| {label} | " + "; ".join(
                f"#{r.a}/#{r.b} λ {r.lambda_b_given_a:.2f} vs Pearson {r.pearson:+.2f} ({r.n_tail} tail days)"
                for r in v.itertuples()) + " |")
        elif key == "regimes":
            parts = []
            for name, per in v.items():
                for c, regs in per.items():
                    parts.append(f"#{c} {name}: " + ", ".join(f"{k} {x['mean'] * 1e4:+.1f} bps (n {x['n']})"
                                                              for k, x in regs.items()))
            lines.append(f"| {label} | " + "; ".join(parts) + " |")
        elif key == "dsr_at_size":
            cap = v.get("capacity_usd")
            lines.append(f"| {label} | DSR {v['dsr']:.3f} after {v['extra_bps']:.1f} bps extra a round trip at "
                         f"${(v.get('notional') or 0):,.0f}" + (f"; capacity ${cap:,.0f}" if cap is not None else "")
                         + " |")
    return "\n".join(lines)
