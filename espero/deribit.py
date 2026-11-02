"""The Deribit recorder: every listed option's open interest, mark and implied volatility, and every
future's, saved so the options dealers' positioning can be read later (idea 16 in research/IDEAS_NOVEL.md).

Deribit's book summary is the present only: it serves no history of open interest by strike. Every 5
minutes, for each currency, one call for its options and one for its futures, written whole into
`data/deribit/<currency>/<day>/<HHMM>.csv.gz`. BTC and ETH hold the inverse contracts; USDC holds the
linear ones on SOL, XRP, BNB, DOGE, LINK and the rest, named `SOL_USDC-27NOV26-170-C`. A file's `ts` is
when its read started. Public data only: nothing signs or trades. Nothing here computes a signal; the
Black-76 gamma helper is a measurement for the idea's pre-registration to fix a convention around.
"""

from __future__ import annotations

import datetime as dt
import json
import logging
import math
import time
import urllib.request
from pathlib import Path
from typing import Callable, Dict, List, Optional, Tuple

import pandas as pd

from .hlcollect import stamp, write

log = logging.getLogger(__name__)

DATA = Path(__file__).resolve().parents[1] / "data" / "deribit"
BASE = "https://www.deribit.com/api/v2/public/"
CURRENCIES = ("BTC", "ETH", "USDC")
KINDS = ("option", "future")
EVERY_S = 300
EXPIRY_HOUR_UTC = 8
COLS = [
    "ts",
    "currency",
    "kind",
    "instrument",
    "base",
    "expiry_ts",
    "strike",
    "type",
    "open_interest",
    "mark_iv",
    "mark_price",
    "underlying_price",
    "estimated_delivery_price",
    "bid",
    "ask",
    "volume",
    "volume_usd",
    "interest_rate",
]
MONTHS = {
    m: i + 1 for i, m in enumerate(("JAN", "FEB", "MAR", "APR", "MAY", "JUN", "JUL", "AUG", "SEP", "OCT", "NOV", "DEC"))
}
Get = Callable[[str], bytes]


def _get(url: str) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": "espero"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return r.read()


def _f(x) -> float:
    try:
        return float(x)
    except (TypeError, ValueError):
        return math.nan


# ----------------------------------------------------------------- names
def expiry_ts(code: str) -> int:
    """`13NOV26` -> that day at 08:00 UTC, Deribit's settlement hour."""
    day, mon, year = int(code[:-5]), MONTHS[code[-5:-2]], 2000 + int(code[-2:])
    return int(dt.datetime(year, mon, day, EXPIRY_HOUR_UTC, tzinfo=dt.timezone.utc).timestamp())


def parse_name(name: str) -> Tuple[str, Optional[int], Optional[float], Optional[str]]:
    """(base, expiry ts, strike, 'C'/'P'): `BTC-13NOV26-83000-P`, `XRP_USDC-13NOV26-1d16-C` (1.16),
    `BTC-29JAN27` (a future), `SOL_USDC-PERPETUAL` (no expiry)."""
    parts = name.split("-")
    base = parts[0].split("_")[0]
    if len(parts) < 2 or parts[1] == "PERPETUAL":
        return base, None, None, None
    expiry = expiry_ts(parts[1])
    if len(parts) == 2:
        return base, expiry, None, None
    return base, expiry, float(parts[2].replace("d", ".")), parts[3]


# ----------------------------------------------------------------- one call
def summary(currency: str, kind: str, get: Get, ts: int) -> pd.DataFrame:
    """Every instrument of this currency and kind, as the book summary shows it now."""
    raw = json.loads(get(f"{BASE}get_book_summary_by_currency?currency={currency}&kind={kind}"))
    rows = []
    for r in raw["result"]:
        base, expiry, strike, typ = parse_name(r["instrument_name"])
        rows.append(
            {
                "ts": ts,
                "currency": currency,
                "kind": kind,
                "instrument": r["instrument_name"],
                "base": base,
                "expiry_ts": expiry,
                "strike": strike,
                "type": typ,
                "open_interest": _f(r.get("open_interest")),
                "mark_iv": _f(r.get("mark_iv")),
                "mark_price": _f(r.get("mark_price")),
                "underlying_price": _f(r.get("underlying_price")),
                "estimated_delivery_price": _f(r.get("estimated_delivery_price")),
                "bid": _f(r.get("bid_price")),
                "ask": _f(r.get("ask_price")),
                "volume": _f(r.get("volume")),
                "volume_usd": _f(r.get("volume_usd")),
                "interest_rate": _f(r.get("interest_rate")),
            }
        )
    return pd.DataFrame(rows, columns=COLS)


# ----------------------------------------------------------------- the recorder
class Recorder:
    """Which currency slots are due, and the file that holds each. `get` reads a URL; injected in tests."""

    def __init__(
        self, data: Path = DATA, get: Optional[Get] = None, sleep=time.sleep, currencies: Tuple[str, ...] = CURRENCIES
    ):
        self.data, self.get, self.sleep, self.currencies = Path(data), get or _get, sleep, currencies

    def path(self, currency: str, ts: int) -> Path:
        slot = ts - ts % EVERY_S
        return self.data / currency / stamp(slot, "%Y-%m-%d") / f"{stamp(slot, '%H%M')}.csv.gz"

    def due(self, now: int) -> List[str]:
        return [c for c in self.currencies if not self.path(c, now).exists()]

    def run(self, currency: str, now: int) -> str:
        """Both kinds for one currency, written together; a failed call writes nothing for the slot."""
        frames = [summary(currency, kind, self.get, now) for kind in KINDS]
        df = pd.concat(frames, ignore_index=True)
        write(df, self.path(currency, now))
        return f"{currency}: {len(frames[0])} options, {len(frames[1])} futures"

    def attempt(self, currency: str, now: int) -> str:
        try:
            return self.run(currency, now)
        except Exception as exc:  # noqa: BLE001 - the loop must outlive a bad minute
            log.error("%s failed: %s", currency, exc)
            return f"{currency}: FAILED {type(exc).__name__}: {exc}"

    def step(self, now: Optional[int] = None) -> List[str]:
        now = int(time.time()) if now is None else now
        return [self.attempt(c, now) for c in self.due(now)]

    def loop(self, tick: float = 30.0, clock=time.time) -> None:
        while True:
            now = int(clock())
            for note in self.step(now):
                print(f"{stamp(now, '%Y-%m-%d %H:%M:%S')} UTC  {note}", flush=True)
            self.sleep(tick)


def status(data: Path = DATA) -> Dict[str, Dict[str, object]]:
    """What is on disk per currency: files, bytes, the latest."""
    out: Dict[str, Dict[str, object]] = {}
    for c in CURRENCIES:
        files = sorted((Path(data) / c).rglob("*.csv.gz"))
        out[c] = {
            "files": len(files),
            "latest": str(files[-1].relative_to(data)) if files else None,
            "bytes": sum(f.stat().st_size for f in files),
        }
    return out


# ----------------------------------------------------------------- a measurement, not a signal
def black76_gamma(forward: float, strike: float, iv: float, years: float, rate: float = 0.0) -> float:
    """Gamma of one option under Black-76, per unit of the forward: e^{-rT} φ(d1) / (F σ √T). `iv` is a
    fraction (Deribit's mark_iv is a percent). Puts and calls share it. Zero at or after expiry."""
    if not (forward > 0 and strike > 0 and iv > 0 and years > 0):
        return 0.0
    v = iv * math.sqrt(years)
    d1 = (math.log(forward / strike) + 0.5 * v * v) / v
    return math.exp(-rate * years) * math.exp(-0.5 * d1 * d1) / math.sqrt(2 * math.pi) / (forward * v)


def gamma_by_strike(options: pd.DataFrame, now: int) -> pd.DataFrame:
    """Open interest × gamma × underlying², per expiry and strike and type, unsigned: the dollars of hedging
    a 1% move would force on whoever holds the other side. Which side that is, the pre-registration must fix."""
    df = options[options["kind"] == "option"].copy()
    years = (df["expiry_ts"] - now) / (365.25 * 86400)
    g = [
        black76_gamma(f, k, iv / 100, t, r if r == r else 0.0)
        for f, k, iv, t, r in zip(df["underlying_price"], df["strike"], df["mark_iv"], years, df["interest_rate"])
    ]
    df["gamma_usd_per_pct"] = df["open_interest"] * pd.Series(g, index=df.index) * df["underlying_price"] ** 2 * 0.01
    return df.groupby(["base", "expiry_ts", "strike", "type"], as_index=False)["gamma_usd_per_pct"].sum()
