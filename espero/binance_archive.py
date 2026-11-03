"""Binance USDⓈ-M's public archive, backfilled into ESPERO_RAW_DIR: what the raw recorder cannot record here.

`data.binance.vision` is a static archive and answers from this machine while the exchange itself refuses
it (HTTP 451). Per symbol and UTC day it publishes `aggTrades`, `bookTicker`, `bookDepth`, `metrics` and
`premiumIndexKlines` (5m), each a zip with a `.CHECKSUM` beside it. It has **no liquidation dataset**:
the daily and monthly listings were checked on 2026-11-01 and again by this module at each run
(`datasets.json` records what the listing held). Binance's `forceOrder` stream is the only source of its
liquidations, and that stream cannot be reached from here, so for Binance markets the liquidation columns
of a rebuilt bar (#61) are "cannot be rebuilt", not zero.

    .venv/bin/python research/rawbars.py --backfill 2026-10-30 2026-11-02     # aggTrades, the 13 symbols
    espero.binance_archive.backfill(raw, symbols, days, datasets)              # any dataset, from Python

Files go to `<raw>/binance_archive/<dataset>/<symbol>/<file>.zip`, written whole then renamed, each verified
against its published SHA-256 before it is kept. A day the archive does not have (HTTP 404: not published
yet, or that dataset ended) is appended to `missing.csv` with the time it was asked, and asked again next
time. Nothing is ever deleted or re-downloaded over a verified file.
"""
from __future__ import annotations

import csv
import datetime as dt
import hashlib
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Callable, Dict, Iterable, List, Optional

from . import manifest

BASE = "https://data.binance.vision/data/futures/um/daily/"
LISTING = "https://s3-ap-northeast-1.amazonaws.com/data.binance.vision?delimiter=/&prefix=data/futures/um/{period}/"
DATASETS = {
    "aggTrades": "aggTrades/{s}/{s}-aggTrades-{d}.zip",
    "bookTicker": "bookTicker/{s}/{s}-bookTicker-{d}.zip",
    "bookDepth": "bookDepth/{s}/{s}-bookDepth-{d}.zip",
    "metrics": "metrics/{s}/{s}-metrics-{d}.zip",
    "premiumIndexKlines": "premiumIndexKlines/{s}/5m/{s}-5m-{d}.zip",
}
FOLDER = "binance_archive"


class NotPublished(Exception):
    pass


def _get(url: str, timeout: int = 120) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": "espero binance archive"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.read()
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            raise NotPublished(url) from None
        raise


def url_for(dataset: str, symbol: str, day: str) -> str:
    return BASE + DATASETS[dataset].format(s=symbol, d=day)


def target(raw: Path, dataset: str, symbol: str, day: str) -> Path:
    return Path(raw) / FOLDER / dataset / symbol / Path(DATASETS[dataset].format(s=symbol, d=day)).name


def published_sha(checksum_text: bytes) -> str:
    return checksum_text.decode().split()[0].lower()


def fetch_one(raw: Path, dataset: str, symbol: str, day: str, get: Callable[[str], bytes] = _get) -> str:
    """'kept' (already verified on disk), 'fetched' (downloaded and verified now), 'missing' (404), or
    raises on a checksum that does not match (the file is not kept)."""
    path = target(raw, dataset, symbol, day)
    if path.exists():
        return "kept"
    url = url_for(dataset, symbol, day)
    try:
        want = published_sha(get(url + ".CHECKSUM"))
        blob = get(url)
    except NotPublished:
        return "missing"
    got = hashlib.sha256(blob).hexdigest()
    if got != want:
        raise RuntimeError(f"{url}: sha256 {got} != published {want}; not kept")
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_bytes(blob)
    tmp.replace(path)
    manifest.write_atomic(path.parent / (path.name + ".CHECKSUM"), f"{want}  {path.name}\n".encode())
    return "fetched"


def record_missing(raw: Path, rows: List[dict], now: Optional[int] = None) -> None:
    path = Path(raw) / FOLDER / "missing.csv"
    path.parent.mkdir(parents=True, exist_ok=True)
    new = not path.exists()
    with path.open("a", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["asked_ts", "dataset", "symbol", "day"])
        if new:
            w.writeheader()
        for r in rows:
            w.writerow({"asked_ts": now or int(time.time()), **r})


def backfill(raw: Path, symbols: Iterable[str], days: Iterable[str], datasets: Iterable[str] = ("aggTrades",),
             get: Callable[[str], bytes] = _get, log: Callable[[str], None] = print, pace: float = 0.2,
             sleep: Callable[[float], None] = time.sleep) -> Dict[str, int]:
    counts = {"kept": 0, "fetched": 0, "missing": 0}
    missing = []
    for dataset in datasets:
        for symbol in symbols:
            for day in days:
                r = fetch_one(raw, dataset, symbol, day, get)
                counts[r] += 1
                if r == "missing":
                    missing.append({"dataset": dataset, "symbol": symbol, "day": day})
                if r != "kept":
                    log(f"{dataset} {symbol} {day}: {r}")
                    sleep(pace)
    if missing:
        record_missing(raw, missing)
    return counts


def listing(get: Callable[[str], bytes] = _get) -> Dict[str, List[str]]:
    """The archive's dataset folders, daily and monthly, as the S3 listing names them."""
    import re
    out = {}
    for period in ("daily", "monthly"):
        text = get(LISTING.format(period=period)).decode()
        out[period] = sorted(p.rstrip("/").rsplit("/", 1)[-1] for p in re.findall(r"<Prefix>([^<]+)</Prefix>", text)
                             if p.rstrip("/").rsplit("/", 1)[-1] != period)
    return out


def record_listing(raw: Path, get: Callable[[str], bytes] = _get, now: Optional[int] = None) -> Dict[str, object]:
    """Write `datasets.json`: what the archive offers, and whether any dataset names liquidations."""
    import json
    found = listing(get)
    doc = {"checked_ts": now or int(time.time()), "datasets": found,
           "liquidation_dataset": any("liq" in d.lower() or "force" in d.lower() for v in found.values() for d in v)}
    path = Path(raw) / FOLDER / "datasets.json"
    manifest.write_atomic(path, json.dumps(doc, indent=1).encode())
    return doc


def days_between(first: str, last: str) -> List[str]:
    a = dt.date.fromisoformat(first)
    b = dt.date.fromisoformat(last)
    return [(a + dt.timedelta(days=i)).isoformat() for i in range((b - a).days + 1)]
