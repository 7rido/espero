"""#57: what is left of Hyperliquid's catch-up to Binance after a delay (research/PREREGISTRATION_CATCHUP.md).

    python research/catchup.py run    # once; reads files already on disk, writes research/catchup_output.txt
"""
from __future__ import annotations

import contextlib
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from espero import catchup as cu  # noqa: E402
from espero import patterns as pt  # noqa: E402

COINS = ["BTC", "ETH", "SOL", "XRP", "DOGE", "LINK"]
DAYS = [d.strftime("%Y-%m-%d") for d in pd.date_range("2024-11-01", "2026-10-01", freq="MS")]
TRADES = ROOT / "data" / "patterns" / "binance-futures" / "trades"
BOOKS = ROOT / "data" / "bookwalk"
OUT = ROOT / "research"
DELAYS = [100, 250, 500, 1_000, 2_000, 5_000]
MAIN_DELAY, MAIN_HOLD, MAIN_USD = 1_000, 30_000, 1_000
pd.set_option("display.width", 200, "display.max_rows", 200, "display.max_columns", 30)


def load_book(coin: str, day: str) -> dict:
    cols = ["local_timestamp"] + [f"{s}[{i}].{f}" for s in ("asks", "bids") for i in range(5) for f in ("price", "amount")]
    df = pd.read_csv(BOOKS / f"{coin}-{day}.csv.gz", usecols=cols).sort_values("local_timestamp")
    book = {"ms": df["local_timestamp"].to_numpy() / 1000}
    for s in ("asks", "bids"):
        book[f"{s}_px"] = df[[f"{s}[{i}].price" for i in range(5)]].to_numpy(float)
        book[f"{s}_qty"] = df[[f"{s}[{i}].amount" for i in range(5)]].to_numpy(float)
    ok = book["asks_px"][:, 0] > book["bids_px"][:, 0]
    return {k: v[ok] for k, v in book.items()}


def collect() -> pd.DataFrame:
    rows = []
    cases = [(d, MAIN_HOLD, MAIN_USD) for d in DELAYS] + [(MAIN_DELAY, MAIN_HOLD, 10_000)]
    cases += [(MAIN_DELAY, h, MAIN_USD) for h in (5_000, 60_000)]
    for coin in COINS:
        for day in DAYS:
            path = TRADES / f"{coin}USDT-{day}.csv.gz"
            if not path.exists() or not (BOOKS / f"{coin}-{day}.csv.gz").exists():
                continue
            tr = pd.read_csv(path, usecols=["local_timestamp", "price"]).sort_values("local_timestamp", kind="stable")
            ms, px = tr["local_timestamp"].to_numpy() / 1000, tr["price"].to_numpy(float)
            book = load_book(coin, day)
            mids = (book["asks_px"][:, 0] + book["bids_px"][:, 0]) / 2
            for index, direction in cu.events(ms, px):
                i = int(index)
                base = {"coin": coin, "day": day, "event_ms": ms[i]}
                for delay, hold, usd in cases:
                    row = {**base, "delay": delay, "hold": hold, "usd": usd,
                           **cu.trade(book, ms[i], direction, delay, hold, usd)}
                    if delay == MAIN_DELAY and hold == MAIN_HOLD and usd == MAIN_USD:
                        before = cu.snapshot_at(book["ms"], ms[i])
                        after = cu.snapshot_at(book["ms"], ms[i] + delay)
                        ref = np.searchsorted(ms, ms[i] - cu.WINDOW_MS, side="right") - 1
                        if before is not None and after is not None:
                            full = abs(px[i] / px[ref] - 1) * 1e4
                            row["already_done"] = direction * (mids[after] / mids[before] - 1) * 1e4 >= full
                    rows.append(row)
    return pd.DataFrame(rows)


def by_day(frame: pd.DataFrame, seed: int) -> dict:
    days = frame[frame["status"] == "ok"].groupby("day")["net"].mean().sort_index()
    low, high = pt.bootstrap_ci(days.to_numpy(), 0.95, seed)
    half = len(DAYS) // 2
    first = days[days.index < DAYS[half]].mean()
    second = days[days.index >= DAYS[half]].mean()
    return {"mean": days.mean(), "low": low, "high": high, "first": first, "second": second, "days": len(days)}


def report() -> None:
    all_rows = collect()
    all_rows.to_csv(OUT / "catchup_events.csv.gz", index=False, float_format="%.4f")
    main = all_rows[(all_rows["hold"] == MAIN_HOLD) & (all_rows["usd"] == MAIN_USD)]
    print("#57 net bps per event, $1,000, 30 s hold, by delay")
    table = []
    for i, delay in enumerate(DELAYS):
        f = main[main["delay"] == delay]
        s = by_day(f, 57 if delay == MAIN_DELAY else 5700 + i)
        table.append({"delay_ms": delay, "events": len(f), "filled": int((f["status"] == "ok").sum()), **s})
    table = pd.DataFrame(table)
    print(table.round(2).to_string(index=False))
    positive = table[table["mean"] > 0]
    print("longest delay with a positive mean:", int(positive["delay_ms"].max()) if len(positive) else "none")

    f = main[main["delay"] == MAIN_DELAY]
    s = by_day(f, 57)
    ok = f[f["status"] == "ok"]
    coin_means = ok.groupby("coin", sort=False)["net"].mean()
    unfillable = float((f["status"] == "unfillable").mean())
    result = cu.verdict(s["low"], s["high"], s["first"], s["second"], int((coin_means > 0).sum()), unfillable)
    print(f"\nVERDICT at 1,000 ms, $1,000, 30 s: {result}")
    print(f"mean {s['mean']:.2f} bps (95% CI {s['low']:.2f} to {s['high']:.2f}); halves {s['first']:.2f}, {s['second']:.2f}; "
          f"{int((coin_means > 0).sum())} of 6 coins positive; unfillable {unfillable:.3f}")
    print("\nParts, mean bps:", ok[["gross", "walk", "fees", "net"]].mean().round(2).to_dict())
    print("\nPer coin\n", ok.groupby("coin", sort=False)[["gross", "walk", "net"]].mean().round(2).to_string())
    print("\nStatus shares\n", f["status"].value_counts(normalize=True).round(4).to_string())
    print("\nMid already at the event's full size by entry:", round(float(f["already_done"].dropna().astype(float).mean()), 3))

    print("\nOther cases at 1,000 ms")
    for name, g in (("$10,000, 30 s", all_rows[(all_rows["usd"] == 10_000)]),
                    ("$1,000, 5 s", all_rows[(all_rows["hold"] == 5_000)]),
                    ("$1,000, 60 s", all_rows[(all_rows["hold"] == 60_000)])):
        x = by_day(g, 5710)
        print(f"{name}: mean {x['mean']:.2f} ({x['low']:.2f} to {x['high']:.2f}); unfillable {(g['status'] == 'unfillable').mean():.3f}")


def main() -> None:
    if sys.argv[1:] != ["run"]:
        raise SystemExit(__doc__)
    output = OUT / "catchup_output.txt"
    if output.exists():
        raise SystemExit(f"{output} exists: #57 runs once")
    buffer = output.with_suffix(".part")
    with open(buffer, "w") as f, contextlib.redirect_stdout(f):
        report()
    buffer.rename(output)
    print(output.read_text())


if __name__ == "__main__":
    main()
