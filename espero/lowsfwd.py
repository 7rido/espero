"""#24's forward paper test (research/FORWARD_LOWS.md): record Binance's daily
5-minute archive for #20's 42 coins, and rebuild the paper ledger of new 4-hour
lows bought at the next bar's open and sold 4 hours later. Nothing trades.

Binance publishes a day's file a day or more after it ends, so a recent day that
is not there yet is tried again tomorrow; only a day still missing after a week
is recorded as missing. The ledger is rebuilt from the recorded files each time
and its running numbers decide nothing.
"""
from __future__ import annotations

import io
import urllib.error
import urllib.request
import zipfile
from pathlib import Path
from typing import Callable, Dict, List, Optional

import pandas as pd

from . import liq, lows, manifest
from .xs import UNIVERSE

FORWARD_FROM = "2026-10-30"
FORWARD_TO = "2027-03-31"
URL = "https://data.binance.vision/data/futures/um/daily/klines/{sym}/5m/{sym}-5m-{day}.zip"
KLINE_COLS = ["open_time", "open", "high", "low", "close", "volume", "close_time", "quote_volume",
              "count", "taker_buy_volume", "taker_buy_quote_volume", "ignore"]
DATA = Path(__file__).resolve().parents[1] / "data" / "lows" / "forward"
GIVE_UP_DAYS = 7
LEDGER = "lows_fwd_trades.csv"


def download(url: str) -> Optional[bytes]:
    try:
        with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "espero"}), timeout=60) as r:
            return r.read()
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            return None
        raise


def days(now: pd.Timestamp) -> List[str]:
    """Warm-up (the day before the window) through yesterday, within the window."""
    first = pd.Timestamp(FORWARD_FROM) - pd.Timedelta(days=1)
    last = min(pd.Timestamp(now.tz_convert(None).date()) - pd.Timedelta(days=1), pd.Timestamp(FORWARD_TO))
    return [d.strftime("%Y-%m-%d") for d in pd.date_range(first, last, freq="D")] if last >= first else []


def record(data: Path = DATA, now: Optional[pd.Timestamp] = None, fetch: Callable = download) -> Dict[str, int]:
    now = pd.Timestamp.now(tz="UTC") if now is None else now
    counts = {"saved": 0, "waiting": 0, "missing": 0}
    for c in UNIVERSE:
        sym = liq.symbol("binance-futures", c)
        for day in days(now):
            path = data / sym / f"{day}.zip"
            none = path.with_suffix(".none")
            if path.exists() or none.exists():
                continue
            blob = fetch(URL.format(sym=sym, day=day))
            path.parent.mkdir(parents=True, exist_ok=True)
            if blob is not None:
                manifest.write_atomic(path, blob, manifest.zip_whole)
                counts["saved"] += 1
            elif (now.tz_convert(None) - pd.Timestamp(day)).days > GIVE_UP_DAYS:
                none.write_text("")
                counts["missing"] += 1
            else:
                counts["waiting"] += 1
    return counts


def read(blob: bytes) -> pd.DataFrame:
    with zipfile.ZipFile(io.BytesIO(blob)) as z:
        text = z.read(z.namelist()[0]).decode()
    header = text.split(",", 1)[0].strip() == "open_time"
    df = pd.read_csv(io.StringIO(text), header=0 if header else None)
    df.columns = KLINE_COLS
    return df


def ledger(data: Path = DATA) -> pd.DataFrame:
    """Every breakdown in the window whose 4-hour exit is recorded, per coin."""
    out = []
    for c in UNIVERSE:
        files = sorted((data / liq.symbol("binance-futures", c)).glob("*.zip"))
        if not files:
            continue
        b = lows.bars(pd.concat([read(f.read_bytes()) for f in files], ignore_index=True))
        ev = lows.events(b, "down", first=FORWARD_FROM, last=FORWARD_TO)
        ev = ev[ev["r240"].notna()]
        out.append(ev.assign(coin=c)[["coin", "ts", "day", "r240"]].rename(columns={"r240": "ret"}))
    return pd.concat(out, ignore_index=True) if out else pd.DataFrame(columns=["coin", "ts", "day", "ret"])


def run(state_dir: Path, data: Path = DATA, now: Optional[pd.Timestamp] = None,
        fetch: Callable = download) -> dict:
    counts = record(data, now, fetch)
    led = ledger(data)
    led.to_csv(Path(state_dir) / LEDGER, index=False, float_format="%.8g")
    n_days = led["day"].nunique()
    note = f"mark: {len(led)} paper trades on {n_days} days"
    if n_days:
        note += f" ({1e4 * float(led.groupby('day')['ret'].mean().mean()):+.1f} bps a day, gross; decides nothing)"
    if counts["waiting"]:
        note += f"; {counts['waiting']} coin-days not published yet"
    return {"note": note, "equity": None, **counts}
