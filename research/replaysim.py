"""#62: replay every paper and testnet fill since the recorder started on the recorded book, and compare
(research/PREREGISTRATION_REPLAYSIM.md).

    .venv/bin/python research/replaysim.py                # every fill on the tape; prints the tables
    .venv/bin/python research/replaysim.py --final        # the judgment call with whatever exists (2027-03-31)

Reads the journals in state/ read-only and the Hyperliquid tapes under ESPERO_RAW_DIR, writes
research/replaysim_fills.csv (one row per fill and latency row) and prints the summaries. Information only
until the registered judgment; it changes no book and no verdict.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import sys
from pathlib import Path
from typing import Dict, List

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from espero import rawrec as rr  # noqa: E402
from espero import replaysim as rs  # noqa: E402

OUT = ROOT / "research" / "replaysim_fills.csv"


def recorder_start_ms(raw: Path) -> int:
    """When the tape begins: the coins file's chosen time, the first start of the recorder of record."""
    path = raw / "coins.json"
    if path.exists():
        return int(json.loads(path.read_text())["chosen_ts"]) * 1000
    return 0


def tape_for(raw: Path, venue: str, coin: str, start_ms: int, end_ms: int):
    """The coin's books and trades over the UTC days [start, end], from the venue's tape."""
    frames = []
    day = dt.datetime.fromtimestamp(start_ms / 1000, dt.timezone.utc).date()
    last = dt.datetime.fromtimestamp(end_ms / 1000, dt.timezone.utc).date()
    while day <= last:
        name = day.isoformat()
        if (raw / venue / name).is_dir():
            frames += [r for r in rr.read_day(raw, venue, name) if r.get("s") == coin]
        day += dt.timedelta(days=1)
    return rs.books_and_trades(frames, coin)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--final", action="store_true", help="judge with whatever exists (the window's end)")
    ap.add_argument("--raw-dir", default=None)
    ap.add_argument("--state-dir", default=str(ROOT / "state"))
    args = ap.parse_args(argv)
    raw = rr.raw_dir({**os.environ, rr.ENV: args.raw_dir} if args.raw_dir else None)
    since = recorder_start_ms(raw)
    orders, skipped = rs.orders_from_journals(Path(args.state_dir), since)
    print(f"tape starts {dt.datetime.fromtimestamp(since / 1000, dt.timezone.utc):%Y-%m-%d %H:%M} UTC; "
          f"{len(orders)} fills since then in the journals, {len(skipped)} rows not replayable")
    for ref, why in skipped:
        print(f"   skipped {ref}: {why}")
    results: List[rs.Result] = []
    lags: Dict[str, dict] = {}
    for o in orders:
        end = max(o.decision_ms + rs.LATENCY_INFO_MS, o.until_ms or 0) + 1000
        books, trades = tape_for(raw, o.venue, o.coin, o.decision_ms - 120_000, end + rs.TRADE_WINDOW_MS)
        if not books:
            results.append(rs.Result(o, False, "no tape for the coin at that time"))
            continue
        lags.setdefault(o.venue, []).append(rs.feed_lag_ms(books, trades)["median"])
        if o.kind == "market":
            results.append(rs.replay_market(o, books, rs.LATENCY_MS))
            results.append(rs.replay_market(o, books, rs.LATENCY_INFO_MS))
        else:
            results.append(rs.replay_limit(o, books, trades, rs.LATENCY_MS))
    rows = rs.rows_of(results)
    rows.to_csv(OUT, index=False)
    print(f"wrote {OUT} ({len(rows)} rows)\n")
    for latency in (rs.LATENCY_MS, rs.LATENCY_INFO_MS):
        part = [r for r in results if r.latency_ms == latency]
        s = rs.summarize(part)
        tag = "registered" if latency == rs.LATENCY_MS else "information only"
        print(f"== latency {latency} ms ({tag}): {s['taker_n']} comparable taker fills, {s['maker_n']} maker orders, "
              f"excluded {s['excluded']}")
        if s["taker"]:
            t = s["taker"]
            print(f"   taker |diff| median {t['median_abs']:.2f} bps, p90 {t['p90_abs']:.2f}; signed median "
                  f"{t['median_signed']:+.2f} (p10 {t['p10']:+.2f}, p90 {t['p90']:+.2f}); partial {t['partial']}, "
                  f"walked >1 level {t['walked_more_than_one_level']}")
        if s["maker"]:
            m = s["maker"]
            print(f"   maker filled/not agreement {m['agreement']:.0%} on {m['n_with_outcome']}; sim filled {m['sim_filled']}")
        if latency == rs.LATENCY_MS:
            v = rs.verdict(s, final=args.final)
            print(f"   call: {v['call']}  {v.get('note', '')}")
    for venue, med in lags.items():
        print(f"feed lag {venue}: median of per-fill medians {pd.Series(med).median():.0f} ms")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
