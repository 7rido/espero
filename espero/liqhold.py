"""#45's forward paper test (research/FORWARD_LIQHOLD.md): #26's forced down-breaks, held 4 h, 12 h, 1 day.

Daily: read the ledger liqbreak (#27) just wrote, price each forced down-break from #24's Binance
bars, charge the measured round trip (18 bps where `espero.costs` has none) and the Binance funding
settled over the hold. The headline is trade-weighted with Newey-West day-clustered errors (#44).
Nothing trades; the running numbers decide nothing.
"""
from __future__ import annotations

import math
from pathlib import Path
from statistics import NormalDist
from typing import Callable, Dict, List, Optional

import numpy as np
import pandas as pd

from . import audit, costs, fundsplit, horizons, liq, liqbreak, lowsfwd

HORIZONS = {"4h": 4 * 3600, "12h": 12 * 3600, "1d": 86_400}
FORWARD_FROM, FORWARD_TO = "2026-10-30", "2027-03-31"
HALF = "2027-01-01"
ASSUMED_RT = 0.0018
MEASURED = ("BTC", "ETH", "SOL", "XRP", "DOGE", "LINK")
MIN_COIN_TRADES = 10
ALPHA = 0.05
LEDGER = "liqhold_trades.csv"


def round_trip(coin: str) -> float:
    try:
        return costs.round_trip("hyperliquid", coin) / 1e4
    except costs.NotMeasured:
        return ASSUMED_RT


def events(led: pd.DataFrame) -> pd.DataFrame:
    """Forced down-breaks in the window; the ledger's ts (the break bar's close) is the entry."""
    if led.empty:
        return led
    fd = led[(led["direction"] == -1) & (led["group"] == "forced")]
    return fd[(fd["day"] >= FORWARD_FROM) & (fd["day"] <= FORWARD_TO)]


def trades(led: pd.DataFrame, bars: Dict[str, pd.DataFrame], funding: Dict[str, pd.DataFrame]) -> pd.DataFrame:
    ev_all = events(led)
    if not len(ev_all):
        return pd.DataFrame()
    out = []
    for coin, g in ev_all.groupby("coin"):
        b, f = bars.get(coin), funding.get(coin)
        if b is None or f is None:
            continue
        ev = pd.DataFrame({"ts": g["ts"].to_numpy(dtype="int64"), "side": 1.0})
        for name, h in HORIZONS.items():
            tr = horizons.trades(ev, b, h, round_trip(coin), f["ts"].to_numpy(), f["rate"].to_numpy(), one=False)
            out.append(tr.assign(coin=coin, h=name, measured=coin in MEASURED))
    return pd.concat(out, ignore_index=True) if out else pd.DataFrame()


def criteria(tr: pd.DataFrame) -> Dict[str, Dict[str, object]]:
    """Per horizon: the four pre-registered checks; Holm across the three horizons."""
    res, pvals = {}, {}
    for name, h in HORIZONS.items():
        x = tr[tr["h"] == name] if len(tr) else tr
        lags = max(1, math.ceil(h / 86_400))
        if not len(x):
            res[name] = {"n": 0}
            pvals[name] = 1.0
            continue
        s = audit.trade_weighted_nw(x["net"], x["day"], lags)
        h1 = x[x["day"] < HALF]["net"].mean()
        h2 = x[x["day"] >= HALF]["net"].mean()
        per = x.groupby("coin")["net"].agg(["size", "mean"])
        per = per[per["size"] >= MIN_COIN_TRADES]
        meas = x[x["measured"]]["net"].mean()
        pvals[name] = 1 - NormalDist().cdf(s["t"]) if np.isfinite(s["t"]) else 1.0
        res[name] = {"n": s["n"], "days": s["days"], "mean": s["mean"], "t": s["t"],
                     "halves": bool(h1 > 0 and h2 > 0), "h1": h1, "h2": h2,
                     "coins": bool(len(per) and (per["mean"] > 0).mean() > 0.5),
                     "coins_pos": int((per["mean"] > 0).sum()), "coins_n": int(len(per)),
                     "measured": bool(meas > 0), "measured_mean": meas,
                     "day_mean": audit.day_mean(x["net"], x["day"])["mean"]}
    holm = horizons.holm(pvals, ALPHA)
    for name in HORIZONS:
        r = res[name]
        r["p"] = pvals[name]
        r["pays"] = bool(r.get("n") and r["mean"] > 0 and holm[name])
        r["pass"] = bool(r["pays"] and r.get("halves") and r.get("coins") and r.get("measured"))
    return res


def run(state_dir: Path, bars_data: Path = lowsfwd.DATA, funding_data: Path = fundsplit.DATA,
        get: Optional[Callable] = None) -> dict:
    """Rebuild the trades from the ledger liqbreak just wrote and say where they stand (decides nothing)."""
    path = Path(state_dir) / liqbreak.LEDGER
    led = pd.read_csv(path) if path.exists() and path.stat().st_size > 1 else pd.DataFrame()
    coins = sorted(set(events(led)["coin"])) if len(led) else []
    bars: Dict[str, pd.DataFrame] = {}
    funding: Dict[str, pd.DataFrame] = {}
    for c in coins:
        b = liqbreak.binance_bars(c, bars_data)
        if b is not None:
            bars[c] = b
        funding[c] = fundsplit.rates(liq.symbol("binance-futures", c), funding_data,
                                     get=get or fundsplit._get, scaled=False)
    tr = trades(led, bars, funding)
    tr.to_csv(Path(state_dir) / LEDGER, index=False, float_format="%.8g")
    if not len(tr):
        return {"note": "mark: no forced down-break with a complete hold yet", "equity": None}
    parts: List[str] = []
    for name in HORIZONS:
        x = tr[tr["h"] == name]
        if len(x):
            parts.append(f"{name} {1e4 * float(x['net'].mean()):+.1f} bps over {len(x)}")
    return {"note": "mark: forced down-breaks held, net trade-weighted: " + "; ".join(parts) + " (decides nothing)",
            "equity": None}
