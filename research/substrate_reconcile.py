"""Every series in the store against the venue's own aggregates and a vendor's sample.

    python research/substrate_reconcile.py

Tolerances are fixed here, in advance of the comparison. A check that fails stays in the table:
research/RESULTS_SUBSTRATE.md says what it means for the numbers built on that series.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from espero import pit  # noqa: E402

OUT = ROOT / "research" / "substrate_reconcile.csv"
VENDOR = pit.STORE / "vendor"
FUND_TOL = 1e-8             # a published rate has eight decimals
VOLUME_TOL = 0.001          # prints against the venue's bars, share of the day's volume
INDEX_TOL_BPS = 5.0         # vendor's index or mark print against the archive's, at the hour
QUOTE_TOL_BPS = 1.0         # vendor's best bid or ask against the archive's, on one-second samples
OI_TOL = 0.005              # vendor's open interest against the archive's five-minute figure
LIQ_TOL = 0.05              # liquidated dollars, vendor against vendor: no venue total exists
FUND_OVERLAP = ("2020-01", "2026-09")
rows = []


def add(series: str, against: str, check: str, n: int, stat: float, tol: float, unit: str, note: str = "") -> None:
    ok = bool(np.isfinite(stat) and n > 0 and abs(stat) <= tol)
    rows.append({"series": series, "against": against, "check": check, "n": n, "stat": stat, "tol": tol, "unit": unit,
                 "pass": ok, "note": note})
    print(f"{'ok  ' if ok else 'FAIL'} {series:<22} {check:<42} n={n:<7} {stat:.6g} {unit} (tol {tol:g}) {note}")


def read_all(view: str, symbol: str, cols) -> pd.DataFrame:
    files = sorted((pit.STORE / view / symbol).glob("*.parquet"))
    if not files:
        return pd.DataFrame(columns=cols)
    return pd.concat([pd.read_parquet(f, columns=cols) for f in files], ignore_index=True)


def funding() -> None:
    """Archive monthly files against the REST history the repo cached earlier, rate by rate and in total."""
    worst, n, months_bad, coins = 0.0, 0, 0, 0
    for path in sorted((ROOT / "data" / "settle" / "funding").glob("*.json")):
        sym = path.stem
        arc = read_all("fundingRate", sym, ["valid_time", "last_funding_rate"])
        if arc.empty:
            continue
        coins += 1
        rest = pd.DataFrame(json.loads(path.read_text()))
        rest["t"] = rest["fundingTime"].astype("int64") // 1000
        rest["rate"] = rest["fundingRate"].astype(float)
        arc = arc.assign(t=arc["valid_time"] // 1000)
        last = min(arc["t"].max(), rest["t"].max())
        m = arc.merge(rest, on="t", how="outer", indicator=True)
        m = m[m["t"] <= last]
        m = m[m["t"] >= max(arc["t"].min(), rest["t"].min())]
        both = m[m["_merge"] == "both"]
        n += len(both)
        worst = max(worst, float((both["last_funding_rate"] - both["rate"]).abs().max()))
        months_bad += int((m["_merge"] != "both").sum())
    add("fundingRate", "Binance REST fapi history (cached)", "largest rate difference", n, worst, FUND_TOL, "rate",
        f"{coins} coins")
    add("fundingRate", "Binance REST fapi history (cached)", "times present in one source only", n, months_bad, 0, "times")


def funding_vs_premium() -> None:
    """Binance's published formula: F = P + clamp(I - P, +/-0.05%), with I 0.01% per 8 h and P the premium's
    average since the last settlement. The hourly bars approximate its time weighting, so this is a sanity
    bound on the funding series, never a replica of it."""
    diffs = []
    for c in ("BTC", "ETH", "SOL", "XRP", "DOGE"):
        f = read_all("fundingRate", f"{c}USDT", ["valid_time", "last_funding_rate", "funding_interval_hours"])
        p = read_all("premiumIndexKlines_1h", f"{c}USDT", ["valid_time", "close"])
        if f.empty or p.empty:
            continue
        p = p.drop_duplicates("valid_time").set_index("valid_time")["close"].sort_index()
        for r in f.itertuples():
            h = int(r.funding_interval_hours) if r.funding_interval_hours == r.funding_interval_hours else 8
            window = p[(p.index >= r.valid_time - h * 3_600_000) & (p.index < r.valid_time)]
            if len(window) < h:
                continue
            avg = float(window.mean())
            i = 0.0001 * h / 8
            diffs.append(r.last_funding_rate - (avg + np.clip(i - avg, -0.0005, 0.0005)))
    d = np.abs(np.array(diffs))
    add("fundingRate", "premiumIndexKlines via venue formula", "median |published - implied|", len(d),
        float(np.median(d)) * 1e4, 0.5, "bps of notional", "hourly approximation")
    add("fundingRate", "premiumIndexKlines via venue formula", "95th percentile |published - implied|", len(d),
        float(np.quantile(d, 0.95)) * 1e4, 2.0, "bps of notional", "hourly approximation")


def prints_vs_bars() -> None:
    """Each coin-day of prints against the venue's own hourly bars: volume, dollars, trade count, range."""
    vol, usd, cnt, hi, lo, days, raw_vol = [], [], [], [], [], 0, []
    for path in sorted((pit.STORE / "aggTrades").glob("*/*.parquet")):
        sym, day = path.parent.name, path.stem
        a = pit.day_ms(day)
        bars = read_all("klines_1h", sym, ["valid_time", "high", "low", "volume", "quote_volume", "count"])
        bars = bars[(bars["valid_time"] >= a) & (bars["valid_time"] < a + 86_400_000)].drop_duplicates("valid_time")
        if len(bars) != 24:
            continue
        p = pd.read_parquet(path, columns=["agg_trade_id", "price", "quantity", "first_trade_id", "last_trade_id"])
        raw_vol.append(p["quantity"].sum() / bars["volume"].sum() - 1)
        p = p.drop_duplicates("agg_trade_id")
        days += 1
        vol.append(p["quantity"].sum() / bars["volume"].sum() - 1)
        usd.append((p["price"] * p["quantity"]).sum() / bars["quote_volume"].sum() - 1)
        cnt.append((p["last_trade_id"] - p["first_trade_id"] + 1).sum() / bars["count"].sum() - 1)
        hi.append(p["price"].max() / bars["high"].max() - 1)
        lo.append(p["price"].min() / bars["low"].min() - 1)
    add("aggTrades", "klines_1h (venue's bars)", "raw files, base volume: days outside tolerance", days,
        float((np.abs(raw_vol) > VOLUME_TOL).sum()), 0, "days", "before de-duplicating on the id")
    for name, x in (("base volume", vol), ("dollar volume", usd), ("trade count", cnt), ("day high", hi), ("day low", lo)):
        x = np.abs(np.array(x))
        add("aggTrades", "klines_1h (venue's bars)", f"{name}: largest day difference", days, float(x.max()) if days else
            float("nan"), VOLUME_TOL, "share")
        add("aggTrades", "klines_1h (venue's bars)", f"{name}: days outside tolerance", days,
            float((x > VOLUME_TOL).sum()), 0, "days")


def vendor_ticker(sym: str, day: str):
    p = VENDOR / "derivative_ticker" / f"{sym}_{day}.csv.gz"
    if not p.exists():
        return None
    d = pd.read_csv(p, usecols=["timestamp", "funding_rate", "open_interest", "index_price", "mark_price"])
    d["t"] = d["timestamp"] // 1000
    return d.sort_values("t")


def index_and_mark() -> None:
    """Hourly archive bars and five-minute open interest against the vendor's tick, first-of-month days."""
    idx, mark, oi, fund = [], [], [], []
    for path in sorted((VENDOR / "derivative_ticker").glob("*.csv.gz")):
        sym, day = path.name.replace(".csv.gz", "").split("_")
        d = vendor_ticker(sym, day)
        a = pit.day_ms(day)
        for view, col, out in (("indexPriceKlines_1h", "index_price", idx), ("markPriceKlines_1h", "mark_price", mark)):
            b = read_all(view, sym, ["valid_time", "open"])
            b = b[(b["valid_time"] >= a) & (b["valid_time"] < a + 86_400_000)].drop_duplicates("valid_time")
            v = d[["t", col]].dropna()
            if b.empty or v.empty:
                continue
            m = pd.merge_asof(b.sort_values("valid_time"), v, left_on="valid_time", right_on="t",
                              tolerance=60_000, direction="backward").dropna()
            out += list(((m[col] - m["open"]) / m["open"] * 1e4).abs())
        f = read_all("fundingRate", sym, ["valid_time", "last_funding_rate"])
        f = f[(f["valid_time"] >= a) & (f["valid_time"] < a + 86_400_000)]
        v = d[["t", "funding_rate"]].dropna()
        if not f.empty and not v.empty:
            m = pd.merge_asof(f.sort_values("valid_time"), v, left_on="valid_time", right_on="t",
                              tolerance=120_000, direction="backward").dropna()
            fund += list((m["funding_rate"] - m["last_funding_rate"]).abs())
        mp = pit.store_path(pit.STORE, "metrics", sym, day)
        v = d[["t", "open_interest"]].dropna()
        if mp.exists() and not v.empty:
            o = pd.read_parquet(mp, columns=["valid_time", "sum_open_interest"]).sort_values("valid_time")
            m = pd.merge_asof(o, v, left_on="valid_time", right_on="t", tolerance=60_000, direction="nearest").dropna()
            oi += list((m["open_interest"] / m["sum_open_interest"] - 1).abs())
    for name, x, tol, unit in (("index print, median", idx, INDEX_TOL_BPS, "bps"), ("mark print, median", mark, INDEX_TOL_BPS, "bps"),
                               ("open interest, median", oi, OI_TOL, "share")):
        add(name.split(",")[0].replace(" print", ""), "Tardis derivative_ticker", name, len(x),
            float(np.median(x)) if x else float("nan"), tol, unit)
    add("fundingRate", "Tardis derivative_ticker", "last rate before settlement, median |diff|", len(fund),
        float(np.median(fund)) * 1e4 if fund else float("nan"), 0.5, "bps of notional", "vendor's rate is a running estimate")


def quotes() -> None:
    bid, ask, n = [], [], 0
    for path in sorted((VENDOR / "book_ticker").glob("*.csv.gz")):
        sym, day = path.name.replace(".csv.gz", "").split("_")
        a = pit.store_path(pit.STORE, "bookTicker", sym, day)
        if not a.exists():
            continue
        q = pd.read_parquet(a, columns=["valid_time", "best_bid_price", "best_ask_price"]).sort_values("valid_time")
        if q.empty:
            continue
        v = pd.read_csv(path, usecols=["timestamp", "bid_price", "ask_price"])
        v["t"] = v["timestamp"] // 1000
        v = v.sort_values("t")
        grid = pd.DataFrame({"t": np.arange(q["valid_time"].iloc[0] + 1000, q["valid_time"].iloc[-1], 1000)})
        m = pd.merge_asof(pd.merge_asof(grid, q, left_on="t", right_on="valid_time"), v, on="t").dropna()
        bid += list(((m["bid_price"] - m["best_bid_price"]) / m["best_bid_price"] * 1e4).abs().to_numpy())
        ask += list(((m["ask_price"] - m["best_ask_price"]) / m["best_ask_price"] * 1e4).abs().to_numpy())
        n += 1
    for name, x in (("best bid", bid), ("best ask", ask)):
        add("bookTicker", "Tardis book_ticker", f"{name}, 99th percentile on 1 s samples", len(x),
            float(np.quantile(x, 0.99)) if x else float("nan"), QUOTE_TOL_BPS, "bps", f"{n} coin-days, 2023 only")


def liquidations() -> None:
    """USD-M has no venue liquidation file, so no venue total exists. This compares two vendors'
    records of the same feed, in dollars by coin-day."""
    add("liquidationSnapshot", "(the archive holds none for USD-M)", "venue total available", 0, float("nan"), 0, "",
        "gap, not a failure of the store: COIN-M only")
    diffs, n = [], 0
    for path in sorted((VENDOR / "liquidations").glob("*.csv.gz")):
        sym, day = path.name.replace(".csv.gz", "").split("_")
        month = day[:7]
        ex = ROOT / "data" / "aggr" / "explore" / f"{month}.csv.gz"
        if not ex.exists():
            continue
        d = pd.read_csv(path, usecols=["price", "amount"])
        a = pit.day_ms(day) // 1000
        bars = pd.read_csv(ex)
        bars = bars[(bars["market"] == f"BINANCE_FUTURES:{sym.lower()}") & (bars["time"] >= a) & (bars["time"] < a + 86400)]
        if bars.empty:
            continue
        aggr = bars[["lbuy", "lsell"]].fillna(0).to_numpy().sum()
        tardis = float((d["price"] * d["amount"]).sum())
        if tardis > 0:
            diffs.append(abs(aggr / tardis - 1))
            n += 1
    add("liquidations", "Tardis against aggr (explore, frozen)", "median |dollars ratio - 1| by coin-day", n,
        float(np.median(diffs)) if diffs else float("nan"), LIQ_TOL, "share", "vendor against vendor")


def main() -> None:
    funding()
    funding_vs_premium()
    prints_vs_bars()
    index_and_mark()
    quotes()
    liquidations()
    pd.DataFrame(rows).to_csv(OUT, index=False)
    t = pd.DataFrame(rows)
    print(f"\n{int(t['pass'].sum())} of {len(t)} checks inside tolerance")


if __name__ == "__main__":
    main()
