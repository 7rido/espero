"""The store's automated gap and duplicate report, per dataset and symbol. Run after any fetch:

    python research/substrate_quality.py

Writes research/pit_gaps.csv (one row per dataset and symbol), research/pit_id_gaps.csv (days whose
aggTrades ids have a hole), research/pit_empty_days.csv (coin-days whose prints do not add up to the
venue's own bars) and research/pit_universe_sample.csv (the universe at sample dates, by query).
"""
from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from espero import pit  # noqa: E402

OUT = ROOT / "research"
SPAN = {"fundingRate": (("valid_time",), 8 * 3_600_000 + 60_000),   # calc_time jitters by seconds
        "premiumIndexKlines_1h": (("valid_time",), 3_600_000),
        "markPriceKlines_1h": (("valid_time",), 3_600_000), "indexPriceKlines_1h": (("valid_time",), 3_600_000),
        "klines_1h": (("valid_time",), 3_600_000), "klines_1d": (("valid_time",), 86_400_000)}
PER_DAY = {"aggTrades": (("agg_trade_id",), None), "bookTicker": (("update_id",), 60_000),
           "bookDepth": (("valid_time", "percentage"), 300_000), "metrics": (("valid_time",), 300_000)}


def main() -> None:
    con = pit.connect()
    con.execute("SET memory_limit='8GB'")
    frames = []
    for view, (key, gap) in SPAN.items():
        frames.append(con.execute(pit.quality_sql(view, key, gap)).df())
    for view, (key, gap) in PER_DAY.items():
        frames.append(con.execute(pit.quality_sql(view, key, gap, per_day=True)).df())
    q = pd.concat(frames, ignore_index=True)
    q.to_csv(OUT / "pit_gaps.csv", index=False)
    print(q.groupby("dataset")[["rows", "duplicate_keys", "known_before_valid", "gaps"]].sum().to_string())
    ids = con.execute(pit.agg_id_gaps_sql()).df()
    ids.to_csv(OUT / "pit_id_gaps.csv", index=False)
    print(f"\naggTrades coin-days with a hole in the ids: {len(ids)}")

    rows = []
    for path in sorted((pit.STORE / "aggTrades").glob("*/*.parquet")):
        sym, day = path.parent.name, path.stem
        a = pit.day_ms(day)
        files = sorted((pit.STORE / "klines_1h" / sym).glob("*.parquet"))
        if not files:
            continue
        bars = pd.concat(pd.read_parquet(f, columns=["valid_time", "volume", "count"]) for f in files)
        bars = bars[(bars["valid_time"] >= a) & (bars["valid_time"] < a + 86_400_000)].drop_duplicates("valid_time")
        p = pd.read_parquet(path, columns=["valid_time", "quantity", "first_trade_id", "last_trade_id"])
        count = (p["last_trade_id"] - p["first_trade_id"] + 1).sum()
        vol = p["quantity"].sum() / bars["volume"].sum() if bars["volume"].sum() else float("nan")
        cnt = count / bars["count"].sum() if bars["count"].sum() else float("nan")
        if abs(vol - 1) > 0.001 or abs(cnt - 1) > 0.001 or len(bars) != 24:
            rows.append({"symbol": sym, "day": day, "print_rows": len(p), "bars": len(bars),
                         "volume_ratio": vol, "count_ratio": cnt,
                         "first_print_ms_after_midnight": int(p["valid_time"].min() - a) if len(p) else -1,
                         "last_print_ms_before_end": int(a + 86_400_000 - p["valid_time"].max()) if len(p) else -1})
    bad = pd.DataFrame(rows)
    bad.to_csv(OUT / "pit_empty_days.csv", index=False)
    print(f"\ncoin-days not matching the venue's bars: {len(bad)}")
    print(bad.to_string(index=False))

    uni = []
    for asof in ("2021-01-04", "2022-01-03", "2023-01-02", "2024-01-01"):
        got = con.execute(pit.universe_sql(pit.day_ms(asof), top_n=10)).df()
        uni.append(got.assign(asof=asof))
        print(f"\nuniverse {asof}: {' '.join(got['symbol'])}")
    pd.concat(uni).to_csv(OUT / "pit_universe_sample.csv", index=False)
    con.close()


if __name__ == "__main__":
    main()
