"""Listed-ticker bars for Hyperliquid's stock perps, limited to what #73 found they may stand in for.

#73 (research/RESULTS_HIP3TRACK.md) measured each trade.xyz perp against its listed ticker. A backtest for these
perps may use a ticker's regular-session hourly bars and its official open and close, only for the markets that
followed in the regular session; not pre-market, after-hours, or any index's or commodity's hourly futures bars.
This module serves exactly that and refuses the rest:

* `allowed()`: the markets, read from research/hip3track_cells.csv, never typed here.
* `hourly(ticker)`: Yahoo's 1-hour bars, the last 730 days (all it serves), bars starting 09:30 to 15:30 Eastern
  only. The 15:30 bar is half an hour long.
* `daily(ticker)`: Yahoo's daily bars, five years by default; the open and close are the official ones.

Both carry `day`, the Eastern date, so `brackets.Bracket(flat_at_day_end=True)` can end a trade at the close.
Yahoo's prices here are adjusted for splits, not for dividends; a perp pays no dividend and its price falls with
the stock's on the day one is paid, so the unadjusted-for-dividends series is the one the perp follows.
Five years of hourly bars needs a data account (Alpaca's free plan serves them since 2016, with a key only the
account holder can create); none is used.
"""
from __future__ import annotations

import csv
import datetime as dt
import json
import time
import urllib.parse
from pathlib import Path
from typing import Callable, List, Optional, Tuple
from zoneinfo import ZoneInfo

import pandas as pd

from . import data

ET = ZoneInfo("America/New_York")
CELLS = Path(__file__).resolve().parents[1] / "research" / "hip3track_cells.csv"
STOCK_KINDS = ("US stock", "ETF", "leveraged ETF")
FIRST_BAR, LAST_BAR = (9, 30), (15, 30)
HOURLY_SPAN = "730d"
MAX_AGE_S = 86_400.0
COLUMNS = ["ts", "open", "high", "low", "close", "volume", "day"]


class NotAllowed(ValueError):
    """#73 did not find this market or session fit to stand in for the perp."""


def allowed(cells: Path = CELLS) -> List[Tuple[str, str]]:
    """(market, ticker) for each stock or ETF whose regular session followed its perp in #73."""
    with Path(cells).open(newline="", encoding="utf-8") as fh:
        return [(r["market"], r["ticker"]) for r in csv.DictReader(fh)
                if r["session"] == "regular" and r["follows"] == "yes" and r["kind"] in STOCK_KINDS]


def ticker_for(market: str, cells: Path = CELLS) -> str:
    for m, t in allowed(cells):
        if m == market:
            return t
    raise NotAllowed(f"{market}: #73 did not find its regular session to follow the perp "
                     "(research/RESULTS_HIP3TRACK.md)")


def regular_only(rows: List[dict]) -> List[dict]:
    """The bars starting from 09:30 to 15:30 Eastern, Monday to Friday."""
    out = []
    for r in rows:
        t = dt.datetime.fromtimestamp(r["ts"], ET)
        if t.weekday() < 5 and FIRST_BAR <= (t.hour, t.minute) <= LAST_BAR:
            out.append(r)
    return out


def parse(payload) -> List[dict]:
    """Yahoo's chart payload -> bars with all four prices, in time order."""
    res = payload["chart"]["result"][0]
    q = res["indicators"]["quote"][0]
    out = []
    for i, t in enumerate(res.get("timestamp") or []):
        o, h, low, c = (q[k][i] for k in ("open", "high", "low", "close"))
        if None in (o, h, low, c):
            continue
        out.append({"ts": int(t), "open": float(o), "high": float(h), "low": float(low), "close": float(c),
                    "volume": float(q["volume"][i] or 0), "day": dt.datetime.fromtimestamp(t, ET).date().isoformat()})
    return sorted(out, key=lambda r: r["ts"])


def _chart(ticker: str, rng: str, interval: str) -> dict:
    q = urllib.parse.urlencode({"range": rng, "interval": interval})
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{urllib.parse.quote(ticker)}?{q}"
    return data.http_json(url, headers={"User-Agent": "Mozilla/5.0"})


def _frame(rows: List[dict]) -> pd.DataFrame:
    return pd.DataFrame(rows, columns=COLUMNS).reset_index(drop=True)


def _load(ticker: str, rng: str, interval: str, fetch: Optional[Callable], cache_dir: Optional[Path],
          now: Callable[[], float]) -> List[dict]:
    folder = Path(cache_dir) if cache_dir is not None else data.CACHE_DIR / "tradfi"
    path = folder / f"{ticker.replace('=', '_').replace('^', '')}_{rng}_{interval}.json"
    if path.exists() and now() - path.stat().st_mtime <= MAX_AGE_S:
        return parse(json.loads(path.read_text()))
    payload = (fetch or _chart)(ticker, rng, interval)
    rows = parse(payload)
    folder.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(payload))
    tmp.replace(path)
    return rows


def hourly(market: str, fetch: Optional[Callable] = None, cache_dir: Optional[Path] = None,
           now: Callable[[], float] = time.time, cells: Path = CELLS) -> pd.DataFrame:
    """A market's regular-session hourly bars from its ticker; NotAllowed for a market #73 left out."""
    rows = _load(ticker_for(market, cells), HOURLY_SPAN, "1h", fetch, cache_dir, now)
    return _frame(regular_only(rows))


def daily(market: str, span: str = "5y", fetch: Optional[Callable] = None, cache_dir: Optional[Path] = None,
          now: Callable[[], float] = time.time, cells: Path = CELLS) -> pd.DataFrame:
    """A market's daily bars from its ticker: the official open and close; NotAllowed for a market #73 left out."""
    return _frame(_load(ticker_for(market, cells), span, "1d", fetch, cache_dir, now))
