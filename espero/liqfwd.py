"""#22's forward paper test (research/FORWARD_LIQ.md): record aggr's hourly bars
day by day, and rebuild the paper ledger of long-liquidation spikes bought at the
spike hour's close and sold 4 hours later. Nothing trades.

`run` is the daily job's step: it records every complete UTC day not yet saved
(up to yesterday), then rewrites `liqfwd_trades.csv` in the state directory.
The ledger is rebuilt from the recorded bars each time, so it can always be
checked against them. Its running numbers decide nothing (the evaluation is
once, after the end date).
"""
from __future__ import annotations

import gzip
import io
from pathlib import Path
from typing import Callable, Dict, List, Optional

import numpy as np
import pandas as pd

from . import aggr, liqspike, manifest

FORWARD_FROM = pd.Timestamp("2026-10-30 00:00", tz="UTC")
FORWARD_TO = pd.Timestamp("2027-03-31 23:00", tz="UTC")
HOLD_H = 4
DATA = Path(__file__).resolve().parents[1] / "data" / "aggr"
COST_HL = 0.0009


def day_path(data: Path, day: pd.Timestamp) -> Path:
    return data / "forward" / f"{day:%Y-%m-%d}.csv.gz"


def record(data: Path = DATA, now: Optional[pd.Timestamp] = None,
           fetch: Callable = aggr.fetch, first: pd.Timestamp = FORWARD_FROM,
           empty: Optional[List[str]] = None) -> List[str]:
    """Save each complete UTC day from `first` to yesterday that is not on disk yet."""
    now = pd.Timestamp.now(tz="UTC") if now is None else now
    saved = []
    day = first.normalize()
    while day + pd.Timedelta(days=1) <= now.normalize() and day <= FORWARD_TO.normalize() + pd.Timedelta(days=1):
        path = day_path(data, day)
        if not path.exists():
            df = fetch(day, day + pd.Timedelta(days=1))
            if df.empty:
                # aggr answered with no bars: saving it would mark the day done and never ask again
                if empty is not None:
                    empty.append(f"{day:%Y-%m-%d}")
                day += pd.Timedelta(days=1)
                continue
            buf = io.StringIO()
            df.sort_values(["market", "time"]).to_csv(buf, index=False)
            manifest.write_atomic(path, gzip.compress(buf.getvalue().encode(), mtime=0), manifest.gzip_whole)
            saved.append(day.strftime("%Y-%m-%d"))
        day += pd.Timedelta(days=1)
    return saved


def load(data: Path = DATA) -> pd.DataFrame:
    """Warm-up (explored and sealed months) plus every recorded forward day."""
    files = sorted((data / "explore").glob("*.csv.gz")) + sorted((data / "holdout").glob("*.csv.gz")) + \
        sorted((data / "forward").glob("*.csv.gz"))
    frames = [pd.read_csv(f) for f in files]
    return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame(columns=aggr.COLUMNS)


LEDGERS = {"long": "liqfwd_trades.csv", "short": "liqfwd_short_trades.csv"}   # #22, #23


def ledger(p: Dict[str, pd.DataFrame], side: str = "long") -> pd.DataFrame:
    """Every spike on `side` in the forward window whose 4-hour exit is recorded. `ret` is
    the paper trade's: a long for long-liquidation spikes (#22), a short for short ones (#23)."""
    rows = []
    for c, df in p.items():
        close = df["close"].to_numpy()
        for t in liqspike.spikes(df, side, FORWARD_FROM, FORWARD_TO):
            i = df.index.get_loc(t)
            if i + HOLD_H >= len(df) or not (np.isfinite(close[i]) and np.isfinite(close[i + HOLD_H])):
                continue
            move = float(close[i + HOLD_H] / close[i] - 1)
            rows.append({"coin": c, "spike_hour": t, "day": t.strftime("%Y-%m-%d"),
                         "usd": float(df[side].iat[i]), "entry": float(close[i]),
                         "exit": float(close[i + HOLD_H]), "ret": move if side == "long" else -move})
    return pd.DataFrame(rows, columns=["coin", "spike_hour", "day", "usd", "entry", "exit", "ret"])


def run(state_dir: Path, data: Path = DATA, now: Optional[pd.Timestamp] = None,
        fetch: Callable = aggr.fetch) -> dict:
    empty: List[str] = []
    saved = record(data, now, fetch, empty=empty)
    p = aggr.panel(load(data))
    parts = []
    for side, name in LEDGERS.items():
        led = ledger(p, side)
        led.to_csv(Path(state_dir) / name, index=False, float_format="%.8g")
        days = led["day"].nunique()
        part = f"{side}s {len(led)} trades on {days} days"
        if days:
            part += f" ({1e4 * float(led.groupby('day')['ret'].mean().mean()):+.1f} bps a day)"
        parts.append(part)
    note = "mark: " + "; ".join(parts) + " (paper, gross; decides nothing)"
    if empty:
        # the ledger above is rebuilt from what is on disk; the step still fails, so the day is seen and retried
        raise RuntimeError(f"aggr returned no bars for {', '.join(empty)}: not saved, asked again next run "
                           f"(a day aggr no longer serves stays a gap; research/ERRATA.md, 2026-11-03). {note}")
    return {"note": note, "equity": None, "saved": saved}
