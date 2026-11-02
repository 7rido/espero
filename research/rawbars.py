"""#61: rebuild aggr's forward bars from the raw tape and compare, per day (research/PREREGISTRATION_RAWBARS.md).

    .venv/bin/python research/rawbars.py                 # every day both sides hold; prints the table
    .venv/bin/python research/rawbars.py --since 2026-11-03 --until 2026-11-30

Reads `ESPERO_RAW_DIR` (the tape, the OKX contract values, the Binance archive) and `data/aggr/forward*`,
writes `research/rawbars_days.csv` (one row per day, venue and bar size) and prints the per-day table.
Information only until the registered judgment; it changes no forward verdict. Binance bars whose live tape
has a gap are rebuilt from the archive where it is on disk (`espero.binance_archive`), marked `archive`.
"""
from __future__ import annotations

import argparse
import datetime as dt
import gzip
import io
import sys
import zipfile
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from espero import binance_archive as ba  # noqa: E402
from espero import rawbars as rb  # noqa: E402
from espero import rawrec as rr  # noqa: E402
from espero.aggr import COINS  # noqa: E402

FORWARD = {"1h": ROOT / "data" / "aggr" / "forward", "5m": ROOT / "data" / "aggr" / "forward5m"}
OUT = ROOT / "research" / "rawbars_days.csv"
ARCHIVE_COLS = ["agg_trade_id", "price", "quantity", "first_trade_id", "last_trade_id", "transact_time", "is_buyer_maker"]


def forward_days() -> List[str]:
    return sorted(p.name[:-7] for p in FORWARD["1h"].glob("????-??-??.csv.gz"))


def read_forward(kind: str, day: str) -> Optional[pd.DataFrame]:
    path = FORWARD[kind] / f"{day}.csv.gz"
    if not path.exists():
        return None
    with gzip.open(path, "rt") as f:
        df = pd.read_csv(f)
    return df[df["market"].isin(set(m for v in COINS.values() for m in v["all"]))]


def tape_events(raw: Path, day: str, ct_val: Dict[str, float]) -> Tuple[pd.DataFrame, Dict[str, List[Tuple[int, int]]]]:
    parts, gaps = [], {}
    for venue in ("binance", "bybit", "okx"):
        if not (raw / venue / day).is_dir():
            gaps[venue] = [(day_ms(day), day_ms(day) + 86_400_000)]
            continue
        parts.append(rb.events_from_frames(venue, rr.read_day(raw, venue, day), ct_val))
        gaps[venue] = rr.gaps(raw, venue, day)
    events = pd.concat(parts, ignore_index=True) if parts else pd.DataFrame(columns=rb.EVENT_COLS)
    return events, gaps


def archive_events(raw: Path, day: str, symbols: List[str]) -> Tuple[pd.DataFrame, List[str]]:
    """Binance's archived prints for the symbols whose zip is on disk; returns (events, markets covered)."""
    parts, markets = [], []
    for s in symbols:
        path = ba.target(raw, "aggTrades", s, day)
        if not path.exists():
            continue
        with zipfile.ZipFile(path) as z:
            name = z.namelist()[0]
            with z.open(name) as f:
                head = f.read(200).decode(errors="replace")
            with z.open(name) as f:
                df = pd.read_csv(io.TextIOWrapper(f), header=0 if head.startswith("agg_trade_id") else None,
                                 names=None if head.startswith("agg_trade_id") else ARCHIVE_COLS)
        parts.append(rb.events_from_archive(s, df))
        markets.append(rb.MARKET["binance"].format(s=s.lower()))
    return (pd.concat(parts, ignore_index=True) if parts else pd.DataFrame(columns=rb.EVENT_COLS)), markets


def day_ms(day: str) -> int:
    return int(dt.datetime.strptime(day, "%Y-%m-%d").replace(tzinfo=dt.timezone.utc).timestamp() * 1000)


def one_day(raw: Path, day: str, ct_val: Dict[str, float]) -> List[dict]:
    events, gaps = tape_events(raw, day, ct_val)
    binance_symbols = rr.plan()["binance"]
    archive_markets: List[str] = []
    if gaps.get("binance"):
        arch, archive_markets = archive_events(raw, day, binance_symbols)
        if len(arch):
            events = pd.concat([events[~events["market"].isin(archive_markets)], arch], ignore_index=True)
    rows = []
    for kind, bar_ms in (("1h", rb.HOUR_MS), ("5m", rb.FIVE_MS)):
        theirs = read_forward(kind, day)
        if theirs is None:
            continue
        ours = rb.build_bars(events, bar_ms)
        table = rb.compare_day(ours, theirs, gaps, bar_ms, archive_markets)
        for venue, prefix in (("binance", "BINANCE_FUTURES:"), ("bybit", "BYBIT:"), ("okx", "OKEX:"), ("all", "")):
            part = table[table["market"].str.startswith(prefix)] if prefix else table
            s = rb.day_summary(part)
            rows.append({"day": day, "bar": kind, "venue": venue, **s,
                         "archive_markets": len(archive_markets) if venue in ("binance", "all") else 0,
                         "gap_minutes": round(sum(b - a for a, b in gaps.get(venue, [])) / 60000, 1)
                         if venue != "all" else round(sum(b - a for g in gaps.values() for a, b in g) / 60000, 1)})
    return rows


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--since", default="2026-11-03", help="first UTC day (the first the tape can hold in full)")
    ap.add_argument("--until", default=None)
    ap.add_argument("--raw-dir", default=None)
    args = ap.parse_args(argv)
    raw = rr.raw_dir({**__import__("os").environ, rr.ENV: args.raw_dir} if args.raw_dir else None)
    inst = raw / "okx" / "instruments.json"
    ct_val = rb.ct_values(inst.read_text()) if inst.exists() else {}
    if not ct_val:
        print("no okx/instruments.json on the tape yet: OKX sizes cannot be converted; OKX bars will not match")
    days = [d for d in forward_days() if d >= args.since and (args.until is None or d <= args.until)]
    rows: List[dict] = []
    for day in days:
        rows += one_day(raw, day, ct_val)
    out = pd.DataFrame(rows)
    if out.empty:
        print(f"no day from {args.since} on is held by both data/aggr/forward and {raw}: nothing to compare yet")
        print(f"forward days on disk: {forward_days()[-3:]}; tape days: "
              f"{sorted(p.name for v in ('binance', 'bybit', 'okx') for p in rr.day_folders(raw, v))[-3:]}")
        pd.DataFrame(columns=["day", "bar", "venue", "bars", "comparable", "excluded", "matched", "fraction",
                              "day_matches", "worst_field", "archive_markets", "gap_minutes"]).to_csv(OUT, index=False)
        return 0
    out.to_csv(OUT, index=False)
    print(f"wrote {OUT} ({len(days)} days)\n")
    print("| day | bar | venue | bars | comparable | excluded | matched | fraction | day matches | worst field | archive | gap min |")
    print("|---|---|---|---|---|---|---|---|---|---|---|---|")
    for r in rows:
        print(f"| {r['day']} | {r['bar']} | {r['venue']} | {r['bars']} | {r['comparable']} | {r['excluded']} | "
              f"{r['matched']} | {r['fraction']:.3f} | {'yes' if r['day_matches'] else 'no'} | {r['worst_field']} | "
              f"{r['archive_markets']} | {r['gap_minutes']} |")
    v = rb.verdict(out)
    print(f"\ncriterion (a): {v['days']} comparable days, fraction matching "
          f"{v['fraction'] if v['fraction'] == v['fraction'] else 'n/a'}; "
          f"{'PASS' if v['a'] else 'FAIL' if v['a'] is False else 'not judged: ' + v['note']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
