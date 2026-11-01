"""Information only, after #52's read: is Hyperliquid's catch-up real on its mid, or stale last trades?

Writes nothing. Also shows why #53 has 22 days. Not part of any registered result.
"""
import pathlib
import sys

import numpy as np
import pandas as pd

repo = pathlib.Path(__file__).resolve().parents[1]
sys.path[:0] = [str(repo), str(repo / "research")]
from espero import patterns as pt  # noqa: E402

COINS = ["BTC", "ETH", "SOL", "XRP", "DOGE", "LINK"]
DAYS = [d.strftime("%Y-%m-%d") for d in pd.date_range("2024-11-01", "2026-10-01", freq="MS")]
RAW, BOOKS = repo / "data/patterns", repo / "data/bookwalk"
rows = []
for coin in COINS:
    for day in DAYS:
        start = int(pd.Timestamp(day).value // 1_000_000)
        b = pd.read_csv(RAW / f"binance-futures/trades/{coin}USDT-{day}.csv.gz", usecols=["local_timestamp", "price"])
        h = pd.read_csv(RAW / f"hyperliquid/trades/{coin}-{day}.csv.gz", usecols=["local_timestamp", "price"])
        cols = ["local_timestamp", "asks[0].price", "bids[0].price"]
        q = pd.read_csv(BOOKS / f"{coin}-{day}.csv.gz", usecols=cols)
        mid = ((q["asks[0].price"] + q["bids[0].price"]) / 2).to_numpy(float)
        sb = pt.grid_prices(b["local_timestamp"].to_numpy() // 1000, b["price"].to_numpy(float), start, 1000, 86400)
        sh = pt.grid_prices(h["local_timestamp"].to_numpy() // 1000, h["price"].to_numpy(float), start, 1000, 86400)
        sm = pt.grid_prices(q["local_timestamp"].to_numpy() // 1000, mid, start, 1000, 86400)
        one = (sb[1:] / sb[:-1] - 1) * 1e4
        t = np.flatnonzero(np.abs(one) >= 10) + 1
        t = t[pt.spaced_events(t.astype(float), 30.0)]
        t = t[(t >= 1) & (t + 30 < 86400)]
        for i in t:
            d = np.sign(sb[i] / sb[i - 1] - 1)
            rows.append({"coin": coin, "day": day, "binance_move": abs(one[i - 1]),
                         "mid_during": d * (sm[i] / sm[i - 1] - 1) * 1e4,
                         "mid_1s": d * (sm[i + 1] / sm[i] - 1) * 1e4, "mid_5s": d * (sm[i + 5] / sm[i] - 1) * 1e4,
                         "mid_30s": d * (sm[i + 30] / sm[i] - 1) * 1e4, "trade_5s": d * (sh[i + 5] / sh[i] - 1) * 1e4})
ev = pd.DataFrame(rows)
print("events", len(ev), "median Binance move", round(ev["binance_move"].median(), 1))
cols = ["binance_move", "mid_during", "mid_1s", "mid_5s", "mid_30s", "trade_5s"]
print("mean, all events\n", ev[cols].mean().round(2).to_string())
print("\nmedian, all events\n", ev[cols].median().round(2).to_string())
print("\nper coin, mean\n", ev.groupby("coin", sort=False)[cols].mean().round(2).assign(n=ev.groupby("coin", sort=False).size()).to_string())
by_day = ev.groupby("day")[["mid_5s", "mid_30s"]].mean()
print("\nper day: events and mean mid_5s")
print(ev.groupby("day").size().to_frame("n").join(by_day["mid_5s"].round(2)).to_string())
counts = ev.groupby("day").size().sort_values(ascending=False)
print("\nshare of events on the top 3 days", round(counts.iloc[:3].sum() / len(ev), 3))
for c in ("mid_1s", "mid_5s", "mid_30s"):
    v = ev.groupby("day")[c].mean().dropna().to_numpy()
    print(c, "day-mean", round(v.mean(), 2), "95% CI", tuple(round(x, 2) for x in pt.bootstrap_ci(v, 0.95, 52)))
print("share of events with mid_5s above 9.9 bps", round((ev["mid_5s"] > 9.9).mean(), 3))

print("\n#53: why 22 days")
for day in DAYS:
    d = pd.read_csv(RAW / f"hyperliquid/derivative_ticker/BTC-{day}.csv.gz", usecols=["timestamp", "mark_price", "index_price"])
    span = (d["timestamp"].max() - d["timestamp"].min()) / 3.6e9
    print(day, len(d), "rows; both present", int(d[["mark_price", "index_price"]].notna().all(axis=1).sum()), "hours", round(span, 1))
