"""#60: buying after the price falls through a dense band of long liquidation prices
(research/FORWARD_LADDER.md).

The rule reads `data/hlcollect/`: the top accounts' positions every hour and Hyperliquid's 1-minute
candles. A file's `ts` is when its read started, so a band is used only from `ts` + 30 minutes. There
is no paper book. The verdict comes from `ledger`, rebuilt once after the window has closed, and it
refuses to read the recordings before then.
"""
from __future__ import annotations

import json
import math
import time
from collections import Counter, deque
from pathlib import Path
from typing import Dict, List, NamedTuple, Optional

import numpy as np
import pandas as pd

from . import hlpbook as hb
from .hlcollect import DATA

KNOWN_AFTER_S = 1800
FALL_S = 3600
BAND = 0.01
HISTORY_S = 168 * 3600
MIN_HISTORY = 84
DENSE_PCT = 90.0
THIN_PCT = 50.0
MIN_THIN = 30


class Slot(NamedTuple):
    ts: int                     # when the file's read started
    rows: Dict[str, pd.DataFrame]


def slot_paths(data: Path = DATA) -> List[Path]:
    return sorted(Path(data).glob("positions/*/*.csv.gz"))


def status(data: Path = DATA, now: Optional[int] = None) -> List[str]:
    """What is on disk for #60, by file name only: nothing opens a recorded file before the window closes."""
    now = int(time.time()) if now is None else now
    data = Path(data)
    opens, closes = pd.Timestamp(hb.WINDOW_START, unit="s").date(), pd.Timestamp(hb.WINDOW_END - 1, unit="s").date()
    where = "not open yet" if now < hb.WINDOW_START else "open" if now < hb.WINDOW_END else "closed"
    return [f"#60 ladder: window {opens} to {closes}; {where}. No paper book; the verdict is computed once, "
            f"after {closes}, with `espero ladder --verdict`",
            f"position slots on disk: {len(slot_paths(data))}",
            f"candle files on disk: {len(list(data.glob('candles/*.csv.gz')))}"]


def read_slot(path: Path) -> Optional[Slot]:
    """One positions file, the 14 coins only. A file with no rows says nothing, so it counts as missing."""
    df = pd.read_csv(path, usecols=["ts", "coin", "szi", "value", "liq"])
    if df.empty:
        return None
    ours = df[df["coin"].isin(hb.COINS)]
    return Slot(int(df["ts"].iloc[0]), {coin: part for coin, part in ours.groupby("coin")})


def band_usd(rows: Optional[pd.DataFrame], px: float) -> float:
    """L: the dollars of long positions with a liquidation price in [px * 0.99, px). A blank liq is left out."""
    if rows is None or rows.empty:
        return 0.0
    liq = pd.to_numeric(rows["liq"], errors="coerce")
    keep = (rows["szi"] > 0) & (liq >= px * (1 - BAND)) & (liq < px)
    return float(rows.loc[keep, "value"].sum())


def walk(slots: List[Slot], prices: hb.Prices) -> Dict:
    """Every dense signal and thin event in the window. Trailing values never include the slot itself."""
    signals: List[hb.Signal] = []
    thin: List[hb.Signal] = []
    counts: Counter = Counter()
    history: Dict[str, deque] = {c: deque() for c in hb.COINS}
    for slot in sorted(slots, key=lambda s: s.ts):
        known, done = slot.ts + KNOWN_AFTER_S, slot.ts + KNOWN_AFTER_S + FALL_S
        for coin in hb.COINS:
            px = prices.close_at(coin, known)
            if not px > 0:
                counts["no_price"] += 1
                continue
            value = band_usd(slot.rows.get(coin), px)
            past = history[coin]
            while past and past[0][0] < slot.ts - HISTORY_S:
                past.popleft()
            after = prices.close_at(coin, done)
            if hb.WINDOW_START <= done < hb.WINDOW_END and len(past) >= MIN_HISTORY and after <= px * (1 - BAND):
                trailing = [p[1] for p in past]
                ret = after / px - 1
                if value > 0 and value > np.percentile(trailing, DENSE_PCT):
                    signals.append(hb.Signal(coin, done, value, ret))
                elif value <= np.percentile(trailing, THIN_PCT):
                    thin.append(hb.Signal(coin, done, value, ret))
            past.append((slot.ts, value))
    return {"signals": signals, "thin": thin, "counts": counts}


def closed_trades(rows: List[dict], fetch: Optional[hb.Fetch] = None) -> pd.DataFrame:
    """The closed trades, each net of the 18 bps and the funding settled during its hold."""
    out = []
    for r in rows:
        if r["status"] == "closed":
            funding = hb.funding_bps(r["coin"], r["entry_ts"], r["exit_ts"], fetch)
            out.append({**r, "funding_bps": funding, "net_bps": hb.net_bps(r["entry_px"], r["exit_px"], funding)})
    return pd.DataFrame(out) if out else pd.DataFrame(columns=["coin", "entry_ts", "net_bps"])


def evaluate(closed: pd.DataFrame, thin: pd.DataFrame) -> Dict:
    """The registered verdict: #58's four criteria on the signals, then the comparison with thin bands."""
    out = hb.evaluate(closed)
    if out["verdict"] == "INCONCLUSIVE":
        return out
    four = all(out["checks"].values())
    band = len(thin) >= MIN_THIN and float(closed["net_bps"].mean()) > float(thin["net_bps"].mean())
    out["checks"]["band"] = band
    out["thin_n"] = len(thin)
    out["thin_mean"] = float(thin["net_bps"].mean()) if len(thin) else math.nan
    out["verdict"] = "PASS" if four and band else "FAIL (it bounces, but the band adds nothing)" if four else "FAIL"
    return out


def ledger(data: Path = DATA, fetch: Optional[hb.Fetch] = None, now: Optional[int] = None) -> Dict:
    """The verdict's ledger. Before the window has closed it refuses and opens no recorded file."""
    now = int(time.time()) if now is None else now
    if now < hb.WINDOW_END:
        raise RuntimeError("#60 is judged once, after 2027-03-31: its recordings are not read before then")
    prices = hb.Prices()
    for path in sorted(Path(data).glob("candles/*.csv.gz")):
        hb.load_candle_file(path, prices)
    api_rows = hb.fetch_recent(prices, now, fetch, pace=0)
    paths = slot_paths(data)
    slots = [s for s in (read_slot(p) for p in paths) if s is not None]
    found = walk(slots, prices)
    rows = hb.trades(found["signals"], prices, final=True)
    thin_rows = hb.trades(found["thin"], prices, final=True)
    closed, thin = closed_trades(rows, fetch), closed_trades(thin_rows, fetch)
    return {"verdict": evaluate(closed, thin), "slots": len(paths), "empty_slots": len(paths) - len(slots),
            "candles_from_api": api_rows, "counts": dict(found["counts"]),
            "statuses": dict(Counter(r["status"] for r in rows)), "rows": rows, "thin_rows": thin_rows}


if __name__ == "__main__":
    report = ledger()
    print(json.dumps({k: v for k, v in report.items() if k not in ("rows", "thin_rows")}, indent=1, default=float))
