"""Point-in-time store over Binance's public archive: Parquet files read through DuckDB.

Every row has two clocks, in integer milliseconds UTC:

* `valid_time`: when the fact was true in the market;
* `known_time`: the earliest a live participant could have held it. A kline is known when
  it closes, not when it opens.

The third clock, when the archive published a file, sits on the manifest as `last_modified`:
Binance writes history in bulk (2021's funding carries a 2023 date), so it says when a copy of
the file existed, never when the fact was known.

Each file is hashed with SHA-256 and checked against Binance's own `.CHECKSUM` before anything
is written; a mismatch stops the file. Raw zips are deleted after reduction (as #39's fetch does);
the manifest keeps the hash, so a re-download can be proved identical.

Pure parts first (`parse`, the reports' SQL, `universe_sql`); the network only in `fetch_file`.
"""
from __future__ import annotations

import csv
import dataclasses
import datetime as dt
import gzip
import hashlib
import io
import json
import time
import urllib.error
import urllib.parse
import urllib.request
import zipfile
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
STORE = ROOT / "data" / "pit"
MANIFEST = ROOT / "research" / "pit_manifest.csv.gz"
ARCHIVE = "https://data.binance.vision/"
LISTING = "https://s3-ap-northeast-1.amazonaws.com/data.binance.vision"
WAYBACK_CDX = "https://web.archive.org/cdx/search/cdx"
EXCHANGE_INFO = "fapi.binance.com/fapi/v1/exchangeInfo"
MANIFEST_COLS = ["dataset", "symbol", "period", "url", "sha256", "checksum", "bytes", "last_modified",
                 "rows", "rows_kept", "valid_min", "valid_max", "reduced"]

_AGG = ["agg_trade_id", "price", "quantity", "first_trade_id", "last_trade_id", "transact_time", "is_buyer_maker"]
_BOOK = ["update_id", "best_bid_price", "best_bid_qty", "best_ask_price", "best_ask_qty", "transaction_time",
         "event_time"]
_KLINE = ["open_time", "open", "high", "low", "close", "volume", "close_time", "quote_volume", "count",
          "taker_buy_volume", "taker_buy_quote_volume", "ignore"]
_FUND = ["calc_time", "funding_interval_hours", "last_funding_rate"]
_DEPTH = ["timestamp", "percentage", "depth", "notional"]
_METRICS = ["create_time", "symbol", "sum_open_interest", "sum_open_interest_value",
            "count_toptrader_long_short_ratio", "sum_toptrader_long_short_ratio", "count_long_short_ratio",
            "sum_taker_long_short_vol_ratio"]
# spot archives have one extra flag and no header
_SPOT_AGG = ["agg_trade_id", "price", "quantity", "first_trade_id", "last_trade_id", "transact_time",
             "is_buyer_maker", "is_best_match"]


@dataclasses.dataclass(frozen=True)
class Dataset:
    name: str
    columns: Tuple[str, ...]
    key: Tuple[str, ...]            # the columns no two rows may share
    max_gap_ms: Optional[int]       # a larger step between rows is reported as a gap
    daily_only: bool = False


DATASETS: Dict[str, Dataset] = {
    "aggTrades": Dataset("aggTrades", tuple(_AGG), ("agg_trade_id",), None),
    "spotAggTrades": Dataset("spotAggTrades", tuple(_SPOT_AGG), ("agg_trade_id",), None),
    "bookTicker": Dataset("bookTicker", tuple(_BOOK), ("update_id",), 60_000),
    "bookDepth": Dataset("bookDepth", tuple(_DEPTH), ("valid_time", "percentage"), 300_000, daily_only=True),
    "metrics": Dataset("metrics", tuple(_METRICS), ("valid_time",), 300_000, daily_only=True),
    "fundingRate": Dataset("fundingRate", tuple(_FUND), ("valid_time",), 8 * 3_600_000),
    "premiumIndexKlines": Dataset("premiumIndexKlines", tuple(_KLINE), ("valid_time",), 3_600_000),
    "markPriceKlines": Dataset("markPriceKlines", tuple(_KLINE), ("valid_time",), 3_600_000),
    "indexPriceKlines": Dataset("indexPriceKlines", tuple(_KLINE), ("valid_time",), 3_600_000),
    "klines": Dataset("klines", tuple(_KLINE), ("valid_time",), None),
}


def archive_path(dataset: str, symbol: str, period: str, interval: str = "1h") -> str:
    """The zip's path in the archive. `period` is YYYY-MM-DD (daily) or YYYY-MM (monthly)."""
    freq = "daily" if len(period) == 10 else "monthly"
    if dataset == "spotAggTrades":
        return f"data/spot/{freq}/aggTrades/{symbol}/{symbol}-aggTrades-{period}.zip"
    if dataset.endswith("lines"):
        return f"data/futures/um/{freq}/{dataset}/{symbol}/{interval}/{symbol}-{interval}-{period}.zip"
    return f"data/futures/um/{freq}/{dataset}/{symbol}/{symbol}-{dataset}-{period}.zip"


def _ms(series: pd.Series) -> pd.Series:
    """Epoch integers in ms: the archive moved some files to microseconds."""
    v = pd.to_numeric(series).astype("int64")
    return v.where(v < 10**14, v // 1000)


def _clock(strings: pd.Series) -> pd.Series:
    t = pd.to_datetime(strings, utc=True)
    return (t - pd.Timestamp("1970-01-01", tz="UTC")) // pd.Timedelta("1ms")


def parse(dataset: str, text: bytes, symbol: str) -> pd.DataFrame:
    """One archive CSV -> typed rows with `valid_time`, `known_time` and `symbol`.

    Older files have no header line, so the first field decides; a file with neither the
    expected header nor a numeric first field raises rather than guessing.
    """
    spec = DATASETS[dataset]
    head = text[: text.find(b"\n") + 1 or len(text)].decode("utf-8", "replace").strip()
    fields = next(csv.reader([head]), []) if head else []
    has_header = bool(fields) and not _numeric(fields[0]) and "-" not in fields[0]
    if has_header and tuple(fields[: len(spec.columns)]) != spec.columns:
        raise ValueError(f"{dataset} {symbol}: unexpected header {fields}")
    df = pd.read_csv(io.BytesIO(text), header=0 if has_header else None,
                     names=None if has_header else list(spec.columns), low_memory=False)
    if dataset in ("aggTrades", "spotAggTrades"):
        df["valid_time"] = _ms(df["transact_time"])
        df["known_time"] = df["valid_time"]
        df["is_buyer_maker"] = df["is_buyer_maker"].astype(str).str.lower().eq("true")
    elif dataset == "bookTicker":
        df["valid_time"] = _ms(df["transaction_time"])
        df["known_time"] = _ms(df["event_time"])
    elif dataset == "bookDepth":
        df["valid_time"] = _clock(df["timestamp"])
        df["known_time"] = df["valid_time"]
        df = df.drop(columns=["timestamp"])
    elif dataset == "metrics":
        df["valid_time"] = _clock(df["create_time"])
        df["known_time"] = df["valid_time"]
        df = df.drop(columns=["create_time", "symbol"])
    elif dataset == "fundingRate":
        df["valid_time"] = _ms(df["calc_time"])
        df["known_time"] = df["valid_time"]
    else:
        df["valid_time"] = _ms(df["open_time"])
        df["known_time"] = _ms(df["close_time"]) + 1
        df = df.drop(columns=["ignore"])
    df["symbol"] = symbol
    return df


def _numeric(s: str) -> bool:
    try:
        float(s)
        return True
    except ValueError:
        return False


def keep_windows(df: pd.DataFrame, windows: Sequence[Tuple[int, int]]) -> pd.DataFrame:
    """The rows inside any [start, end) of `windows`: how a 2 GB bookTicker day stays small."""
    mask = np.zeros(len(df), dtype=bool)
    t = df["valid_time"].to_numpy()
    for a, b in windows:
        mask |= (t >= a) & (t < b)
    return df.loc[mask]


def store_path(store: Path, dataset: str, symbol: str, period: str, interval: str = "1h") -> Path:
    name = f"{dataset}_{interval}" if dataset.endswith("lines") else dataset
    return Path(store) / name / symbol / f"{period}.parquet"


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def checksum_of(text: str) -> str:
    """The hash in a Binance `.CHECKSUM` file (`<hash>  <name>`)."""
    parts = text.split()
    if not parts or len(parts[0]) != 64:
        raise ValueError(f"not a checksum: {text[:80]!r}")
    return parts[0].lower()


def _get(url: str, tries: int = 8, timeout: int = 300) -> Tuple[Optional[bytes], str]:
    for k in range(tries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "espero"})
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return r.read(), r.headers.get("Last-Modified", "")
        except urllib.error.HTTPError as exc:
            if exc.code == 404:
                return None, ""
            if k == tries - 1:
                raise
        except (urllib.error.URLError, TimeoutError, ConnectionError, OSError):
            if k == tries - 1:
                raise
        time.sleep(2 * (k + 1))
    return None, ""


def fetch_file(dataset: str, symbol: str, period: str, store: Path = STORE, interval: str = "1h",
               windows: Optional[Sequence[Tuple[int, int]]] = None) -> Optional[dict]:
    """Download, verify, write Parquet, drop the raw bytes. A manifest row, or None for a 404."""
    path = urllib.parse.quote(archive_path(dataset, symbol, period, interval))    # some symbols are not ASCII
    body, modified = _get(ARCHIVE + path)
    if body is None:
        return None
    digest = sha256(body)
    check, _ = _get(ARCHIVE + path + ".CHECKSUM", timeout=60)
    published = checksum_of(check.decode()) if check else ""
    if published and published != digest:
        raise ValueError(f"{path}: sha256 {digest} != published {published}")
    with zipfile.ZipFile(io.BytesIO(body)) as z:
        text = z.read(z.namelist()[0])
    df = parse(dataset, text, symbol)
    rows = len(df)
    if windows is not None:
        df = keep_windows(df, windows)
    out = store_path(store, dataset, symbol, period, interval)
    out.parent.mkdir(parents=True, exist_ok=True)
    tmp = out.with_suffix(".tmp")
    df.to_parquet(tmp, compression="zstd", index=False)
    tmp.rename(out)
    return {"dataset": dataset if not dataset.endswith("lines") else f"{dataset}_{interval}", "symbol": symbol,
            "period": period, "url": ARCHIVE + path, "sha256": digest, "checksum": "ok" if published else "absent",
            "bytes": len(body), "last_modified": modified, "rows": rows, "rows_kept": len(df),
            "valid_min": int(df["valid_time"].min()) if len(df) else -1,
            "valid_max": int(df["valid_time"].max()) if len(df) else -1, "reduced": windows is not None}


def write_manifest(rows: Iterable[dict], path: Path = MANIFEST) -> pd.DataFrame:
    """Merge rows into the manifest. A file seen twice must carry the same hash: a restated
    archive file is a fact to report, not to overwrite."""
    new = pd.DataFrame(list(rows), columns=MANIFEST_COLS)
    old = pd.read_csv(path) if Path(path).exists() else pd.DataFrame(columns=MANIFEST_COLS)
    both = pd.concat([old, new], ignore_index=True)
    clash = both.groupby(["dataset", "symbol", "period"])["sha256"].nunique()
    clash = clash[clash > 1]
    if len(clash):
        raise ValueError(f"archive file restated: {clash.index.tolist()[:5]}")
    both = both.drop_duplicates(["dataset", "symbol", "period"], keep="first")
    both = both.sort_values(["dataset", "symbol", "period"]).reset_index(drop=True)
    both.to_csv(path, index=False)
    return both


def parse_exchange_info(body: bytes, capture_ms: int) -> pd.DataFrame:
    """A Wayback capture of /fapi/v1/exchangeInfo -> one row per symbol, known at the capture."""
    if body[:2] == b"\x1f\x8b":        # Wayback serves some captures still gzipped
        body = gzip.decompress(body)
    info = json.loads(body)
    rows = []
    for s in info.get("symbols", []):
        filters = {f.get("filterType"): f for f in s.get("filters", [])}
        rows.append({"valid_time": capture_ms, "known_time": capture_ms, "symbol": s.get("symbol"),
                     "status": s.get("status"), "contract_type": s.get("contractType"),
                     "onboard_date": s.get("onboardDate"), "delivery_date": s.get("deliveryDate"),
                     "tick_size": float(filters.get("PRICE_FILTER", {}).get("tickSize", "nan")),
                     "step_size": float(filters.get("LOT_SIZE", {}).get("stepSize", "nan")),
                     "min_notional": float(filters.get("MIN_NOTIONAL", {}).get("notional", "nan"))})
    return pd.DataFrame(rows)


def wayback_captures() -> List[Tuple[str, str]]:
    """Distinct-content captures of exchangeInfo that answered 200: (timestamp, digest)."""
    url = (f"{WAYBACK_CDX}?url={EXCHANGE_INFO}&output=json&collapse=digest&filter=statuscode:200"
           "&fl=timestamp,digest")
    body, _ = _get(url, timeout=120)
    if not body:
        return []
    return [(r[0], r[1]) for r in json.loads(body)[1:]]


# ---------------------------------------------------------------- DuckDB

def connect(store: Path = STORE):
    """An in-memory DuckDB with one view per dataset on disk: the database is the files."""
    import duckdb

    con = duckdb.connect()
    for sub in sorted(p for p in Path(store).iterdir() if p.is_dir()) if Path(store).exists() else []:
        glob = str(sub / "*" / "*.parquet")
        if list(sub.glob("*/*.parquet")):
            con.execute(f"CREATE VIEW \"{sub.name}\" AS SELECT * FROM read_parquet('{glob}', union_by_name=true)")
    return con


def universe_sql(asof_ms: int, top_n: int = 20, lookback_days: int = 30, view: str = "klines_1d") -> str:
    """The tradable USDT perps as of a moment, ranked by trailing dollar volume: a query, never a list.

    Only rows known by `asof_ms` count. A symbol is out if the newest exchangeInfo capture known at
    that moment says it is not TRADING; between captures the last known status stands, and a symbol
    the capture does not list yet is judged by its bars alone, because captures are sparse. The tradable
    set and its order are the same at any later date: nothing here reads the future.
    """
    start = asof_ms - lookback_days * 86_400_000
    return f"""
    WITH vol AS (
        SELECT symbol, SUM(quote_volume) AS dollar_volume, COUNT(*) AS bars
        FROM "{view}"
        WHERE known_time <= {asof_ms} AND valid_time >= {start}
        GROUP BY symbol
    ), last_seen AS (
        SELECT symbol, status FROM (
            SELECT symbol, status,
                   ROW_NUMBER() OVER (PARTITION BY symbol ORDER BY known_time DESC) AS r
            FROM exchange_info WHERE known_time <= {asof_ms}
        ) WHERE r = 1
    )
    SELECT v.symbol, v.dollar_volume, v.bars
    FROM vol v LEFT JOIN last_seen s USING (symbol)
    WHERE v.symbol LIKE '%USDT'
      AND COALESCE(s.status, 'TRADING') = 'TRADING'
      AND v.bars >= {lookback_days}
    ORDER BY v.dollar_volume DESC, v.symbol
    LIMIT {top_n}
    """


def quality_sql(view: str, key: Sequence[str], max_gap_ms: Optional[int], per_day: bool = False) -> str:
    """Per symbol: rows, duplicate keys, rows out of time order, and steps wider than `max_gap_ms`.
    `per_day` measures steps within a UTC day: for tables holding scattered coin-days, not a span."""
    k = ", ".join(key)
    within = "symbol, valid_time // 86400000" if per_day else "symbol"
    gap = f"SUM(CASE WHEN step > {max_gap_ms} THEN 1 ELSE 0 END)" if max_gap_ms else "NULL"
    return f"""
    WITH t AS (
        SELECT symbol, valid_time, known_time,
               valid_time - LAG(valid_time) OVER (PARTITION BY {within} ORDER BY valid_time) AS step
        FROM "{view}"
    ), d AS (
        SELECT symbol, SUM(n - 1) AS dups FROM (
            SELECT symbol, {k}, COUNT(*) AS n FROM "{view}" GROUP BY symbol, {k}
        ) WHERE n > 1 GROUP BY symbol
    )
    SELECT '{view}' AS dataset, t.symbol, COUNT(*) AS rows, COALESCE(MAX(d.dups), 0) AS duplicate_keys,
           SUM(CASE WHEN known_time < valid_time THEN 1 ELSE 0 END) AS known_before_valid,
           {gap} AS gaps, MAX(step) AS max_step_ms, MIN(valid_time) AS valid_min, MAX(valid_time) AS valid_max
    FROM t LEFT JOIN d ON t.symbol = d.symbol
    GROUP BY t.symbol ORDER BY t.symbol
    """


def agg_id_gaps_sql(view: str = "aggTrades") -> str:
    """aggTrades ids count up without a hole inside a file: a hole within a day is lost prints."""
    return f"""
    SELECT symbol, day, COUNT(*) AS rows, MAX(agg_trade_id) - MIN(agg_trade_id) + 1 - COUNT(DISTINCT agg_trade_id)
           AS missing_ids
    FROM (SELECT symbol, valid_time // 86400000 AS day, agg_trade_id FROM "{view}")
    GROUP BY symbol, day HAVING missing_ids <> 0 ORDER BY symbol, day
    """


def missing_periods(expected: Iterable[Tuple[str, str, str]], manifest: pd.DataFrame) -> pd.DataFrame:
    """Expected (dataset, symbol, period) triples absent from the manifest. A gap stays a gap."""
    have = set(zip(manifest["dataset"], manifest["symbol"], manifest["period"].astype(str)))
    rows = [e for e in expected if e not in have]
    return pd.DataFrame(rows, columns=["dataset", "symbol", "period"])


def day_ms(day: str) -> int:
    d = dt.datetime.strptime(day, "%Y-%m-%d").replace(tzinfo=dt.timezone.utc)
    return int(d.timestamp() * 1000)
