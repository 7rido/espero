"""#52-#56: five descriptive patterns for the operator (research/PREREGISTRATION_PATTERNS.md).

    python research/patterns.py fetch     # free Tardis files into data/patterns/, no key; read the log before running
    python research/patterns.py run 52    # then 53, 54, 55 and 56, each once
"""
from __future__ import annotations

import contextlib
import sys
import urllib.error
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "research")]

import markout  # noqa: E402

from espero import patterns as pt  # noqa: E402

COINS = ["BTC", "ETH", "SOL", "XRP", "DOGE", "LINK", "ADA", "AVAX", "BNB", "TRX", "LTC", "XLM", "HBAR", "kSHIB"]
LEAD_COINS = COINS[:6]
DAYS = [d.strftime("%Y-%m-%d") for d in pd.date_range("2024-11-01", "2026-10-01", freq="MS")]
RAW = ROOT / "data" / "patterns"
BOOKS = ROOT / "data" / "bookwalk"
OUT = ROOT / "research"
LEVEL = 0.9875
US = 1_000_000
pd.set_option("display.width", 200, "display.max_rows", 300, "display.max_columns", 30)


def path(ex: str, kind: str, sym: str, day: str) -> Path:
    return RAW / ex / kind / f"{sym}-{day}.csv.gz"


def fetch() -> None:
    wanted = [("hyperliquid", "trades", c) for c in COINS] + [("hyperliquid", "derivative_ticker", c) for c in COINS]
    wanted += [("binance-futures", "trades", f"{c}USDT") for c in LEAD_COINS]
    for ex, kind, sym in wanted:
        for day in DAYS:
            y, m, d = day.split("-")
            try:
                got = markout.get(markout.TARDIS.format(ex=ex, kind=kind, y=y, m=m, d=d, sym=sym), path(ex, kind, sym, day))
            except urllib.error.HTTPError as exc:
                if exc.code != 400:  # Tardis refuses a day before a symbol's listing with a 400
                    raise
                got = None
            print(ex, kind, sym, day, "missing" if got is None else f"{got.stat().st_size / 1e6:.1f} MB", flush=True)


def index(us: pd.Series) -> pd.DatetimeIndex:
    return pd.to_datetime(us.to_numpy(), unit="us")


def load_book(coin: str, day: str):
    """Per snapshot: seconds into the day, mid, and top-5 notional per side, from #51's files."""
    p = BOOKS / f"{coin}-{day}.csv.gz"
    if not p.exists():
        return None
    cols = ["timestamp"] + [f"{s}[{i}].{f}" for s in ("asks", "bids") for i in range(5) for f in ("price", "amount")]
    df = pd.read_csv(p, usecols=cols).sort_values("timestamp")
    px = {s: df[[f"{s}[{i}].price" for i in range(5)]].to_numpy(float) for s in ("asks", "bids")}
    qty = {s: df[[f"{s}[{i}].amount" for i in range(5)]].to_numpy(float) for s in ("asks", "bids")}
    ok = px["asks"][:, 0] > px["bids"][:, 0]
    out = pd.DataFrame({"mid": (px["asks"][:, 0] + px["bids"][:, 0]) / 2, "ask": px["asks"][:, 0], "bid": px["bids"][:, 0],
                        "asks5": pt.top5_notional(px["asks"], qty["asks"]), "bids5": pt.top5_notional(px["bids"], qty["bids"])},
                       index=index(df["timestamp"]))
    out = out[ok]
    return out[~out.index.duplicated(keep="last")]


def state_cells(rows, coin, day, signal, prices, horizons):
    state = pt.states(signal)
    for name, seconds in horizons:
        diff, up_high, up_low = pt.high_minus_low(state.to_numpy(), pt.forward_bps(prices, signal.index, seconds))
        rows.append({"coin": coin, "day": day, "horizon": name, "value": diff, "up_high": up_high, "up_low": up_low,
                     "high_n": int((state == 1).sum()), "low_n": int((state == -1).sum())})


def state_report(rows, title, seed, csv_name):
    days = pd.DataFrame(rows)
    days.to_csv(OUT / csv_name, index=False, float_format="%.5f")
    print(title)
    table = []
    for i, (horizon, g) in enumerate(days.groupby("horizon", sort=False)):
        s = pt.horizon_summary(g[["coin", "day", "value"]], LEVEL, seed + i)
        table.append({"horizon": horizon, **{k: round(v, 3) if isinstance(v, float) else v for k, v in s.items()},
                      "up_after_high": round(g["up_high"].mean(), 3), "up_after_low": round(g["up_low"].mean(), 3),
                      "label": "CLEAR PATTERN" if s["clear"] else "NO CLEAR PATTERN"})
    print(pd.DataFrame(table).drop(columns="clear").to_string(index=False))
    print("\nPer coin, mean high minus low, bps:")
    print(days.pivot_table(index="coin", columns="horizon", values="value", sort=False).round(2).to_string())


def run_52():
    rows, moves, stand = [], [], []
    bins, step = 864_000, 100
    for coin in LEAD_COINS:
        for day in DAYS:
            hp, bp = path("hyperliquid", "trades", coin, day), path("binance-futures", "trades", f"{coin}USDT", day)
            if not (hp.exists() and bp.exists()):
                continue
            cols = ["timestamp", "local_timestamp", "price"]
            h, b = pd.read_csv(hp, usecols=cols), pd.read_csv(bp, usecols=cols)
            start = int(pd.Timestamp(day).value // 1_000_000)
            row = {"coin": coin, "day": day}
            for clock in ("local_timestamp", "timestamp"):
                gh = pt.grid_prices((h[clock].to_numpy() // 1000), h["price"].to_numpy(float), start, step, bins)
                gb = pt.grid_prices((b[clock].to_numpy() // 1000), b["price"].to_numpy(float), start, step, bins)
                first = max(np.argmax(np.isfinite(gh)), np.argmax(np.isfinite(gb)))
                lag, corr = pt.peak_lag(gb[first:], gh[first:], 50)
                row.update({f"lag_ms_{clock}": lag * step, f"corr_{clock}": corr})
                if clock == "local_timestamp":
                    sb, sh = gb[9::10], gh[9::10]
                    mb, mh = sb[59::60], sh[59::60]
                    gap = np.abs(mh / mb - 1) * 1e4
                    rb, rh = np.diff(np.log(mb[4::5])), np.diff(np.log(mh[4::5]))
                    ok = np.isfinite(rb) & np.isfinite(rh)
                    stand.append({"coin": coin, "day": day, "gap_median": np.nanmedian(gap), "gap_p99": np.nanpercentile(gap, 99),
                                  "corr_5m": np.corrcoef(rb[ok], rh[ok])[0, 1]})
                    for name, lead, follow in (("binance_moves", sb, sh), ("hyperliquid_moves", sh, sb)):
                        one = (lead[1:] / lead[:-1] - 1) * 1e4
                        t = np.flatnonzero(np.abs(one) >= 10) + 1
                        t = t[pt.spaced_events(t.astype(float), 30.0)]
                        for s in (1, 5, 30):
                            valid = t[t + s < len(follow)]
                            d = np.sign(lead[valid] / lead[valid - 1] - 1) * (follow[valid + s] / follow[valid] - 1) * 1e4
                            moves.append({"coin": coin, "day": day, "event": name, "seconds": s, "n": len(valid), "sum": np.nansum(d)})
            rows.append(row)
        print("read", coin, file=sys.stderr, flush=True)
    days = pd.DataFrame(rows)
    days.to_csv(OUT / "patterns_52_days.csv", index=False, float_format="%.5f")
    print(f"#52 who moves first: {days['day'].nunique()} days, {len(days)} coin-days. Positive lag: Binance first.")
    for clock in ("local_timestamp", "timestamp"):
        col = f"lag_ms_{clock}"
        by_day = days.groupby("day")[col].median().sort_index()
        low, high = pt.bootstrap_ci(by_day.to_numpy(), 0.95, 52)
        half = len(by_day) // 2
        first, second = by_day.iloc[:half].mean(), by_day.iloc[half:].mean()
        by_coin = days.groupby("coin", sort=False)[col].median()
        same = int((np.sign(by_coin) == np.sign(by_day.mean())).sum())
        label = "CLEAR LEADER" if pt.clear_label(low, high, first, second, same, 4) else "NO CLEAR LEADER"
        print(f"\n{clock}: mean of daily median lag {by_day.mean():.0f} ms (95% CI {low:.0f} to {high:.0f}); halves {first:.0f}, {second:.0f}; "
              f"{same} of 6 coins share the sign; {label}")
        print(f"coin-days Binance first {(days[col] > 0).sum()}, Hyperliquid first {(days[col] < 0).sum()}, same bin {(days[col] == 0).sum()}")
        print(days.groupby("coin", sort=False).agg(median_lag_ms=(col, "median"), peak_corr=(f"corr_{clock}", "mean")).round(3).to_string())
    print("\nAs a stand-in, per coin (mean of days): price gap in bps and 5-minute return correlation")
    print(pd.DataFrame(stand).groupby("coin", sort=False)[["gap_median", "gap_p99", "corr_5m"]].mean().round(3).to_string())
    print("\nAfter a 10 bps move in 1 s on one venue: the other venue's mean move in that direction, bps")
    m = pd.DataFrame(moves).groupby(["event", "seconds"], sort=False)[["n", "sum"]].sum()
    m["mean_bps"] = (m["sum"] / m["n"]).round(2)
    print(m[["n", "mean_bps"]].to_string())


def run_53():
    rows, own = [], []
    for coin in COINS:
        for day in DAYS:
            p = path("hyperliquid", "derivative_ticker", coin, day)
            if not p.exists():
                continue
            df = pd.read_csv(p, usecols=["timestamp", "mark_price", "index_price"]).dropna().sort_values("timestamp")
            if df.empty:
                continue
            df = df.drop_duplicates("timestamp", keep="last")
            prices = pd.Series(df["mark_price"].to_numpy(float), index=index(df["timestamp"]))
            premium = pd.Series(((df["mark_price"] / df["index_price"] - 1) * 1e4).to_numpy(float), index=prices.index)
            grid = pd.date_range(day, periods=1440, freq="min") + pd.Timedelta(minutes=1)
            signal = premium.reindex(grid, method="ffill")
            horizons = [("1m", 60), ("5m", 300), ("15m", 900), ("60m", 3600)]
            state_cells(rows, coin, day, signal, prices, horizons)
            state = pt.states(signal).to_numpy()
            for name, seconds in horizons:
                later = premium.reindex(grid + pd.Timedelta(seconds=seconds), method="ffill").to_numpy(float, copy=True)
                later[grid + pd.Timedelta(seconds=seconds) > premium.index[-1]] = np.nan
                diff, _, _ = pt.high_minus_low(state, later - signal.to_numpy(float))
                own.append({"coin": coin, "day": day, "horizon": name, "value": diff})
    state_report(rows, "#53 mark against index: mark's move, high premium minus low premium, bps", 5300, "patterns_53_days.csv")
    print("\nAlso: the premium's own change, high minus low, bps (the definitional reversion)")
    print(pd.DataFrame(own).groupby("horizon", sort=False)["value"].mean().round(3).to_string())


def run_54():
    rows = []
    for coin in COINS:
        for day in DAYS:
            p = path("hyperliquid", "trades", coin, day)
            book = load_book(coin, day)
            if book is None or not p.exists():
                continue
            t = pd.read_csv(p, usecols=["timestamp", "side", "price", "amount"])
            t["usd"] = t["price"] * t["amount"]
            t.index = index(t["timestamp"]).floor("s")
            seconds = pd.date_range(day, periods=86400, freq="s")
            buy = t.loc[t["side"] == "buy", "usd"].groupby(level=0).sum().reindex(seconds, fill_value=0.0)
            sell = t.loc[t["side"] == "sell", "usd"].groupby(level=0).sum().reindex(seconds, fill_value=0.0)
            grid = pd.date_range(day, periods=1440, freq="min") + pd.Timedelta(minutes=1)
            signal = pt.flow(buy, sell).shift(1, freq="s").reindex(grid)
            state_cells(rows, coin, day, signal, book["mid"], [("10s", 10), ("1m", 60), ("5m", 300), ("15m", 900)])
    state_report(rows, "#54 aggressive flow: mid's move, one-sided buying minus one-sided selling, bps", 5400, "patterns_54_days.csv")


def run_55():
    rows = []
    for coin in COINS:
        for day in DAYS:
            book = load_book(coin, day)
            if book is None:
                continue
            raw = pd.Series(pt.imbalance(book["bids5"].to_numpy(), book["asks5"].to_numpy()), index=book.index)
            grid = pd.date_range(day, periods=1440, freq="min") + pd.Timedelta(minutes=1)
            mean10 = raw.rolling("10s", closed="left").mean()
            signal = mean10.reindex(grid, method="ffill", tolerance=pd.Timedelta(seconds=10))
            state_cells(rows, coin, day, signal, book["mid"], [("10s", 10), ("1m", 60), ("5m", 300), ("15m", 900)])
    state_report(rows, "#55 book imbalance: mid's move, bid-heavy minus ask-heavy, bps", 5500, "patterns_55_days.csv")


def run_56():
    rows = []
    for coin in COINS:
        for day in DAYS:
            p = path("hyperliquid", "trades", coin, day)
            book = load_book(coin, day)
            if book is None or not p.exists():
                continue
            t = pd.read_csv(p, usecols=["timestamp", "side", "price", "amount"])
            t["usd"] = t["price"] * t["amount"]
            t["second"] = t["timestamp"] // US
            per = t.groupby(["second", "side"])["usd"].sum().reset_index().sort_values("second")
            burst = per[per["usd"] >= per["usd"].quantile(0.99)]
            burst = burst[pt.spaced_events(burst["second"].to_numpy(float), 60.0)]
            times = (book.index - pd.Timestamp(0)).total_seconds().to_numpy()
            mids = book["mid"]
            for second, side in zip(burst["second"], burst["side"]):
                hit = "asks5" if side == "buy" else "bids5"
                before = (times >= second - 60) & (times <= second - 5)
                if not before.any():
                    continue
                base = float(np.median(book[hit].to_numpy()[before]))
                secs, low = pt.refill(times, book[hit].to_numpy(), float(second + 1), base)
                if not np.isfinite(secs):
                    continue
                at = pd.DatetimeIndex([pd.Timestamp(second + 1, unit="s")])
                sign = 1 if side == "buy" else -1
                row = {"coin": coin, "day": day, "refill_s": secs, "lowest": low}
                for h in (1, 5, 30, 60):
                    row[f"move_{h}s"] = sign * pt.forward_bps(mids, at, h)[0]
                rows.append(row)
    ev = pd.DataFrame(rows)
    ev.to_csv(OUT / "patterns_56_events.csv.gz", index=False, float_format="%.4f")
    agg = {"bursts": ("refill_s", "size"), "median_refill_s": ("refill_s", "median"), "lowest_median": ("lowest", "median")}
    table = ev.groupby("coin", sort=False).agg(**agg)
    for s in (1, 5, 30, 60, 300):
        table[f"by_{s}s"] = ev.groupby("coin", sort=False)["refill_s"].apply(lambda x, s=s: (x <= s).mean() if s < 300 else (x < 300).mean())
    print(f"#56 refill: {len(ev)} bursts on {ev['day'].nunique()} days")
    print(table.round(3).to_string())
    print("\nAll coins:", {k: round(float(v), 3) for k, v in {
        "median_refill_s": ev["refill_s"].median(), "share_censored_300s": (ev["refill_s"] >= 300).mean(), "lowest_median": ev["lowest"].median()}.items()})
    print("\nMid's mean move in the burst's direction, bps, 95% CI over days")
    for i, h in enumerate((1, 5, 30, 60)):
        by_day = ev.groupby("day")[f"move_{h}s"].mean().dropna()
        low, high = pt.bootstrap_ci(by_day.to_numpy(), 0.95, 5600 + i)
        print(f"{h}s: {by_day.mean():.2f} ({low:.2f} to {high:.2f})")


RUNS = {"52": run_52, "53": run_53, "54": run_54, "55": run_55, "56": run_56}


def main() -> None:
    if len(sys.argv) >= 2 and sys.argv[1] == "fetch":
        return fetch()
    if len(sys.argv) == 3 and sys.argv[1] == "run" and sys.argv[2] in RUNS:
        output = OUT / f"patterns_{sys.argv[2]}_output.txt"
        if output.exists():
            raise SystemExit(f"{output} exists: this runs once")
        buffer = output.with_suffix(".part")
        with open(buffer, "w") as f, contextlib.redirect_stdout(f):
            RUNS[sys.argv[2]]()
        buffer.rename(output)
        print(output.read_text())
        return None
    raise SystemExit(__doc__)


if __name__ == "__main__":
    main()
