"""#51: a market order's cost on Hyperliquid as it gets larger (research/PREREGISTRATION_BOOKWALK.md).

    python research/bookwalk.py fetch     # Tardis's free book files into data/bookwalk/, no key
    python research/bookwalk.py report    # run once; writes research/bookwalk_output.txt
"""
from __future__ import annotations

import contextlib
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "research")]

import markout  # noqa: E402

from espero import bookwalk as bw  # noqa: E402
from espero.costs_table import TABLE  # noqa: E402
from espero.venues import VENUES  # noqa: E402

COINS = ["BTC", "ETH", "SOL", "XRP", "DOGE", "LINK", "ADA", "AVAX", "BNB", "TRX", "LTC", "XLM", "HBAR", "kSHIB"]
DAYS = [d.strftime("%Y-%m-%d") for d in pd.date_range("2024-11-01", "2026-10-01", freq="MS")]
THIN_FROM = "2026-09-01"
SEEN = {(c, d) for c in ("BTC", "SOL", "DOGE") for d in ("2025-02-01", "2025-10-01", "2026-10-01")}
VALIDATE = ["BTC", "ETH", "SOL", "XRP", "DOGE", "LINK"]
TOLERANCE_BPS = 0.5
LEVELS = 25
FEE = VENUES["hyperliquid"].taker_bps
RAW = ROOT / "data" / "bookwalk"
DAYS_CSV = ROOT / "research" / "bookwalk_days.csv"
OUTPUT = ROOT / "research" / "bookwalk_output.txt"


def path(coin: str, day: str) -> Path:
    return RAW / f"{coin}-{day}.csv.gz"


def fetch() -> None:
    for coin in COINS:
        for day in DAYS:
            y, m, d = day.split("-")
            url = markout.TARDIS.format(ex="hyperliquid", kind="book_snapshot_25", y=y, m=m, d=d, sym=coin)
            got = markout.get(url, path(coin, day))
            print(coin, day, "missing" if got is None else f"{got.stat().st_size / 1e6:.1f} MB", flush=True)


def one_file(coin: str, day: str) -> list:
    sides = [f"{s}[{i}].{f}" for s in ("asks", "bids") for i in range(LEVELS) for f in ("price", "amount")]
    df = pd.read_csv(path(coin, day), usecols=sides)
    arr = {f"{s}_{f}": df[[f"{s}[{i}].{f}" for i in range(LEVELS)]].to_numpy(float)
           for s in ("asks", "bids") for f in ("price", "amount")}
    ok = bw.valid_snapshots(arr["asks_price"][:, 0], arr["bids_price"][:, 0])
    levels = min(np.isfinite(arr["asks_price"][ok]).sum(axis=1).mean(), np.isfinite(arr["bids_price"][ok]).sum(axis=1).mean())
    res = bw.coin_day(arr["asks_price"][ok], arr["asks_amount"][ok], arr["bids_price"][ok], arr["bids_amount"][ok])
    return [{"coin": coin, "day": day, "usd": usd, "snapshots": int(ok.sum()), "dropped": int((~ok).sum()),
             "levels": round(float(levels), 2), **vals} for usd, vals in res.items()]


def report() -> None:
    if OUTPUT.exists():
        raise SystemExit(f"{OUTPUT} exists: #51 runs once")
    rows, missing = [], []
    for coin in COINS:
        for day in DAYS:
            if path(coin, day).exists():
                rows += one_file(coin, day)
            else:
                missing.append((coin, day))
        print("read", coin, flush=True)
    days = pd.DataFrame(rows)
    days.to_csv(DAYS_CSV, index=False, float_format="%.5f")
    main = days[days["day"] < THIN_FROM]
    thin = days[days["day"] >= THIN_FROM]

    pd.set_option("display.width", 200, "display.max_rows", 200, "display.max_columns", 30)
    fmt = {"cost": "{:.2f}".format, "low": "{:.2f}".format, "high": "{:.2f}".format, "p95": "{:.2f}".format,
           "unfillable": "{:.3f}".format, "round_trip": "{:.2f}".format}
    table = bw.summarize(main, FEE)
    print(f"#51 main group: {main['day'].nunique()} days through {main['day'].max()}; fee {FEE} bps a leg")
    print(table.to_string(index=False, formatters=fmt))
    print("\nVerdicts:", table.groupby(["usd", "verdict"]).size().to_dict())

    print("\n== Validation: $1,000 cost against #39/#41's measured taker half-spread")
    rows = []
    for coin in VALIDATE:
        cost = float(table[(table["coin"] == coin) & (table["usd"] == 1_000)]["cost"].iloc[0])
        ref = TABLE[("hyperliquid", coin, "taker", 0, "all", "all")]
        rows.append({"coin": coin, "walk_1k": round(cost, 3), "half_spread": round(ref, 3), "gap": round(cost - ref, 3),
                     "inside": abs(cost - ref) <= TOLERANCE_BPS})
    print(pd.DataFrame(rows).to_string(index=False))

    print("\n== Coin-days and snapshots")
    print("missing files:", missing or "none")
    print("main-group coin-days under 20 levels:", int((main.drop_duplicates(["coin", "day"])["levels"] < 20).sum()),
          "of", len(main.drop_duplicates(["coin", "day"])))
    once = days.drop_duplicates(["coin", "day"])
    print("snapshots:", int(once["snapshots"].sum()), "dropped:", int(once["dropped"].sum()))

    print("\n== Thin group: 2026-09-01 and 2026-10-01, cost only where the book could fill")
    print(thin.groupby(["coin", "usd"], sort=False).agg(levels=("levels", "mean"), unfillable=("unfillable", "mean"),
                                                        cost=("cost", "mean"), p95=("p95", "mean")).round(3).to_string())

    print("\n== Main result without the 9 coin-days already seen")
    keep = [(c, d) not in SEEN for c, d in zip(main["coin"], main["day"])]
    alt = bw.summarize(main[keep], FEE)
    both = table.merge(alt, on=["coin", "usd"], suffixes=("", "_alt"))
    changed = both[both["verdict"] != both["verdict_alt"]]
    print("verdicts that change:", len(changed))
    if len(changed):
        print(changed[["coin", "usd", "verdict", "verdict_alt", "cost", "cost_alt"]].to_string(index=False))


if __name__ == "__main__":
    command = sys.argv[1] if len(sys.argv) > 1 else ""
    if command == "fetch":
        fetch()
    elif command == "report":
        buffer = OUTPUT.with_suffix(".part")
        with open(buffer, "w") as f, contextlib.redirect_stdout(f):
            report()
        buffer.rename(OUTPUT)
        print(OUTPUT.read_text())
    else:
        raise SystemExit(__doc__)
