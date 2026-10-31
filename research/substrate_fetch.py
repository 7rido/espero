"""Fills the point-in-time store (espero/pit.py) and its manifest. Resumable: a file on disk is skipped.

    python research/substrate_fetch.py small       # funding, premium, mark and index bars, metrics, depth (design)
    python research/substrate_fetch.py universe    # daily bars for every USD-M symbol, Wayback exchangeInfo
    python research/substrate_fetch.py design      # #2's 2021-23 legs and the impact sample, prints and quotes
    python research/substrate_fetch.py vendor      # Tardis's free first-of-month files, on the reconciliation days
    python research/substrate_fetch.py holdout     # #2's 2024-26 legs: only after #48's registration is committed
    python research/substrate_fetch.py carry       # #11's 2024 legs, perp and spot: only after #48's read

Coverage is the days the books traded, not the whole archive: aggTrades plus bookTicker for these
coins is about 440 GB, more than this machine has free. research/SUBSTRATE_GAPS.md says what that
leaves out.
"""
from __future__ import annotations

import json
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Iterable, List, Optional, Tuple

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "research"))
from espero import pit  # noqa: E402

XS_COINS = ["BTC", "ETH", "SOL", "LINK", "ADA", "XRP", "DOGE", "LTC", "AVAX"]
CARRY_COINS = ["AAVE", "BNB", "BTC", "DOGE", "ENA", "ETH", "LINK", "NEAR", "SOL", "UNI", "WLD", "XRP", "ZEC", "ZRO"]
COINS = sorted(set(XS_COINS) | set(CARRY_COINS))
LEGS_XS = ROOT / "research" / "substrate_xs_legs.csv"
LEGS_CARRY = ROOT / "research" / "substrate_carry_trades.csv"
WORKERS = 6
BOOK_WINDOW_MS = 2 * 3_600_000
BOOK_FIRST, BOOK_LAST = "2023-05-16", "2024-03-30"
DEPTH_FIRST = "2023-01-01"
DESIGN = ("2021-01-01", "2023-12-31")
HOLDOUT_FIRST = "2024-01-01"
SAMPLE_EVERY = 4        # the impact sample: every 4th Monday of the design window, all nine coins
TARDIS = "https://datasets.tardis.dev/v1/binance-futures/{kind}/{y}/{m}/{d}/{sym}.csv.gz"
VENDOR_DIR = ROOT / "data" / "pit" / "vendor"


def months(first: str, last: str) -> List[str]:
    return [d.strftime("%Y-%m") for d in pd.period_range(first, last, freq="M")]


def mondays(first: str, last: str) -> List[str]:
    return [d.strftime("%Y-%m-%d") for d in pd.date_range(first, last, freq="W-MON")]


def run(jobs: Iterable[Tuple], workers: int = WORKERS) -> None:
    """Each job is the args of pit.fetch_file. A 404 is recorded as a miss, never filled."""
    seen = set()
    if pit.MANIFEST.exists():
        m = pd.read_csv(pit.MANIFEST, usecols=["dataset", "symbol", "period"], dtype=str)
        seen = set(zip(m["dataset"], m["symbol"], m["period"]))
    todo = []
    for j in jobs:
        dataset, sym, period = j[0], j[1], j[2]
        interval = j[3] if len(j) > 3 and j[3] else "1h"
        name = f"{dataset}_{interval}" if dataset.endswith("lines") else dataset
        # a file without its manifest row is not ingested: no hash, no row
        if (name, sym, period) not in seen or not pit.store_path(pit.STORE, dataset, sym, period, interval).exists():
            todo.append(j)
    print(f"{len(todo)} files to fetch", flush=True)
    rows, missing, failed = [], [], []

    def one(j):
        interval = j[3] if len(j) > 3 and j[3] else "1h"
        windows = j[4] if len(j) > 4 else None
        return j, pit.fetch_file(j[0], j[1], j[2], interval=interval, windows=windows)

    with ThreadPoolExecutor(workers) as ex:
        futures = [ex.submit(one, j) for j in todo]
        for k, fut in enumerate(as_completed(futures), 1):
            try:
                j, row = fut.result()
            except Exception as exc:
                failed.append(repr(exc)[:200])
                if len(failed) <= 5:
                    print(f"  failed: {failed[-1]}", flush=True)
                continue
            if row is None:
                missing.append(j[:3])
            else:
                rows.append(row)
            if len(rows) >= 200 or k == len(futures):
                pit.write_manifest(rows)
                rows = []
            if k % 200 == 0:
                print(f"  {k}/{len(futures)}", flush=True)
    if rows:
        pit.write_manifest(rows)
    if failed:
        print(f"{len(failed)} files failed; run again to retry them", flush=True)
    if missing:
        path = ROOT / "research" / "pit_missing.csv"
        old = pd.read_csv(path) if path.exists() else pd.DataFrame(columns=["dataset", "symbol", "period"])
        new = pd.DataFrame(missing, columns=["dataset", "symbol", "period"])
        pd.concat([old, new]).drop_duplicates().sort_values(["dataset", "symbol", "period"]).to_csv(path, index=False)
        print(f"{len(missing)} files absent from the archive, listed in {path.name}")


def small() -> None:
    last = "2026-09"
    jobs: List[Tuple] = []
    for c in COINS:
        sym = f"{c}USDT"
        for m in months("2020-01", last):
            jobs.append(("fundingRate", sym, m))
            for k in ("premiumIndexKlines", "markPriceKlines", "indexPriceKlines"):
                jobs.append((k, sym, m, "1h"))
            jobs.append(("klines", sym, m, "1h"))
    run(jobs)


def symbols() -> List[str]:
    out, marker = [], None
    while True:
        q = {"prefix": "data/futures/um/monthly/klines/", "delimiter": "/", "max-keys": "1000"}
        if marker:
            q["marker"] = marker
        with urllib.request.urlopen(pit.LISTING + "?" + urllib.parse.urlencode(q), timeout=120) as r:
            body = r.read().decode()
        got = [p.split("/")[-2] for p in pd.Series(body.split("<Prefix>")[2:]).str.split("<").str[0]]
        out += got
        if "<IsTruncated>true" not in body or not got:
            return sorted(set(out))
        marker = f"data/futures/um/monthly/klines/{got[-1]}/"


def listed_months(symbol: str) -> List[str]:
    """The months of 1-day bars the archive holds for a symbol, from its index, not by probing."""
    prefix = f"data/futures/um/monthly/klines/{symbol}/1d/"
    url = pit.LISTING + "?" + urllib.parse.urlencode({"prefix": prefix, "max-keys": "1000"})
    body, _ = pit._get(url, timeout=120)
    return sorted(set(re.findall(r"-1d-(\d{4}-\d{2})\.zip</Key>", (body or b"").decode())))


def universe() -> None:
    syms = symbols()
    print(f"{len(syms)} USD-M symbols ever listed")
    with ThreadPoolExecutor(WORKERS) as ex:
        listed = list(ex.map(listed_months, syms))
    run([("klines", s, m, "1d") for s, ms in zip(syms, listed) for m in ms], workers=12)
    caps = pit.wayback_captures()
    print(f"{len(caps)} distinct exchangeInfo captures")
    frames, rows = [], []
    for ts, digest in caps:
        url = f"https://web.archive.org/web/{ts}id_/https://{pit.EXCHANGE_INFO}"
        body, _ = pit._get(url, timeout=120)
        if body is None:
            continue
        ms = int(pd.Timestamp(ts, tz="UTC").timestamp() * 1000)
        try:
            df = pit.parse_exchange_info(body, ms)
        except (json.JSONDecodeError, UnicodeDecodeError, OSError):
            print(f"  {ts}: not JSON, recorded as unusable")
            rows.append({"capture": ts, "digest": digest, "sha256": pit.sha256(body), "symbols": 0, "usable": False})
            continue
        frames.append(df)
        rows.append({"capture": ts, "digest": digest, "sha256": pit.sha256(body), "symbols": len(df), "usable": True})
    out = pit.STORE / "exchange_info" / "all" / "captures.parquet"
    out.parent.mkdir(parents=True, exist_ok=True)
    if frames:
        pd.concat(frames, ignore_index=True).to_parquet(out, compression="zstd", index=False)
    pd.DataFrame(rows).to_csv(ROOT / "research" / "pit_exchange_info_captures.csv", index=False)


def day_jobs(rows: Iterable[Tuple[str, str]], kinds=("aggTrades", "bookDepth", "metrics")) -> List[Tuple]:
    """(coin, YYYY-MM-DD): the files that exist for that day; bookTicker keeps hours around 00:00."""
    jobs: List[Tuple] = []
    for coin, day in sorted(set(rows)):
        sym = f"{coin}USDT"
        for k in kinds:
            if k == "bookDepth" and day < DEPTH_FIRST:
                continue
            if k == "metrics" and day < "2021-12-01":
                continue
            jobs.append((k, sym, day))
        if BOOK_FIRST <= day <= BOOK_LAST:
            a = pit.day_ms(day)
            jobs.append(("bookTicker", sym, day, None, [(a, a + BOOK_WINDOW_MS)]))
    return jobs


def design() -> None:
    legs = pd.read_csv(LEGS_XS)
    legs = legs[(legs["day"] >= DESIGN[0]) & (legs["day"] <= DESIGN[1])]
    sample = mondays(*DESIGN)[::SAMPLE_EVERY]
    rows = [(r.coin, r.day) for r in legs.itertuples()] + [(c, d) for c in XS_COINS for d in sample]
    # the days reconciled against the vendor's quotes: first of the month, 2023 only (before the holdout)
    recon = []
    for c in ("ETH", "SOL"):
        for m in months("2023-06", "2023-12"):
            a = pit.day_ms(f"{m}-01")
            recon.append(("bookTicker", f"{c}USDT", f"{m}-01", None, [(a, a + BOOK_WINDOW_MS)]))
    run(day_jobs(rows) + recon)


def holdout() -> None:
    legs = pd.read_csv(LEGS_XS)
    legs = legs[legs["day"] >= HOLDOUT_FIRST]
    # the monthly bars stop at September: the holdout's last weeks read October's daily files
    october = [d.strftime("%Y-%m-%d") for d in pd.date_range("2026-10-01", "2026-10-27")]
    bars = [("klines", f"{c}USDT", d, "1d") for c in XS_COINS for d in october]
    run(day_jobs((r.coin, r.day) for r in legs.itertuples()) + bars)


def carry() -> None:
    t = pd.read_csv(LEGS_CARRY)
    rows = []
    for r in t.itertuples():
        for stamp in (r.entry, r.exit):
            if stamp[:4] == "2024":
                rows.append((r.coin, stamp[:10]))
    jobs = []
    for coin, day in sorted(set(rows)):
        sym = f"{coin}USDT"
        jobs += [("aggTrades", sym, day), ("bookDepth", sym, day), ("spotAggTrades", sym, day)]
        if BOOK_FIRST <= day <= BOOK_LAST:
            hours = sorted({pd.Timestamp(s) for r in t.itertuples() if r.coin == coin
                            for s in (r.entry, r.exit) if s[:10] == day})
            windows = [(int(h.timestamp() * 1000), int(h.timestamp() * 1000) + BOOK_WINDOW_MS) for h in hours]
            jobs.append(("bookTicker", sym, day, None, windows))
    run(jobs)


def vendor_file(kind: str, day: str, sym: str) -> Optional[Path]:
    """One Tardis free day, kept as gzip with its hash listed. A refusal is a miss, not an error."""
    y, m, d = day.split("-")
    out = VENDOR_DIR / kind / f"{sym}_{day}.csv.gz"
    if out.exists():
        return out
    url = TARDIS.format(kind=kind, y=y, m=m, d=d, sym=sym)
    try:
        body, _ = pit._get(url, tries=4, timeout=300)
    except urllib.error.HTTPError:
        return None
    if body is None:
        return None
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_bytes(body)
    return out


def vendor() -> None:
    """First-of-month days, on the three coins most of the book's legs traded."""
    days = [f"{m}-01" for m in months("2021-01", "2026-10")]
    jobs = [("derivative_ticker", d, f"{c}USDT") for c in ("BTC", "ETH", "SOL") for d in days]
    jobs += [("liquidations", d, f"{c}USDT") for c in ("BTC", "ETH", "SOL") for d in days]
    jobs += [("book_ticker", d, f"{c}USDT") for c in ("ETH", "SOL") for d in days if BOOK_FIRST <= d <= "2023-12-31"]
    rows = []
    with ThreadPoolExecutor(WORKERS) as ex:
        futures = {ex.submit(vendor_file, *j): j for j in jobs}
        for fut in as_completed(futures):
            j, p = futures[fut], fut.result()
            rows.append({"kind": j[0], "day": j[1], "symbol": j[2], "present": p is not None,
                         "bytes": p.stat().st_size if p else 0,
                         "sha256": pit.sha256(p.read_bytes()) if p else ""})
    pd.DataFrame(rows).sort_values(["kind", "symbol", "day"]).to_csv(
        ROOT / "research" / "pit_vendor_manifest.csv", index=False)
    print(f"vendor files: {sum(r['present'] for r in rows)} of {len(rows)}")


if __name__ == "__main__":
    {"small": small, "universe": universe, "design": design, "holdout": holdout, "carry": carry,
     "vendor": vendor}[sys.argv[1]]()
