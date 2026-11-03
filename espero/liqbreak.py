"""#27's forward paper test (research/FORWARD_LIQBREAK.md): #26's rule on live data.

Every morning: save yesterday's aggr 5-minute bars (longs and shorts liquidated per
market; aggr keeps them only for days) into data/aggr/forward5m/, then rebuild the
ledger of every break on aggr's 14 coins with its forced share, within-day group
and returns at 15 minutes, 1 hour and 4 hours, from the Binance 5-minute bars #24
records. Nothing trades; the running numbers decide nothing.
"""
from __future__ import annotations

import gzip
import io
from pathlib import Path
from typing import Callable, List, Optional

import pandas as pd

from . import aggr, liq, lowsfwd, manifest

FORWARD_FROM = pd.Timestamp("2026-10-30", tz="UTC")
FORWARD_TO = pd.Timestamp("2027-03-31", tz="UTC")
DATA = Path(__file__).resolve().parents[1] / "data" / "aggr" / "forward5m"
LEDGER = "liqbreak_trades.csv"


def record(data: Path = DATA, now: Optional[pd.Timestamp] = None, fetch: Callable = aggr.fetch,
           empty: Optional[List[str]] = None) -> List[str]:
    """Save each complete UTC day of aggr 5-minute bars not on disk yet."""
    now = pd.Timestamp.now(tz="UTC") if now is None else now
    saved, day = [], FORWARD_FROM
    while day + pd.Timedelta(days=1) <= now.normalize() and day <= FORWARD_TO + pd.Timedelta(days=1):
        path = data / f"{day:%Y-%m-%d}.csv.gz"
        if not path.exists():
            df = fetch(day, day + pd.Timedelta(days=1), bar_ms=300_000)
            if df.empty:
                # aggr answered with no bars: saving it would mark the day done and never ask again
                if empty is not None:
                    empty.append(f"{day:%Y-%m-%d}")
                day += pd.Timedelta(days=1)
                continue
            buf = io.StringIO()
            df.sort_values(["market", "time"]).to_csv(buf, index=False)
            manifest.write_atomic(path, gzip.compress(buf.getvalue().encode(), mtime=0), manifest.gzip_whole)
            saved.append(f"{day:%Y-%m-%d}")
        day += pd.Timedelta(days=1)
    return saved


def liq_rows(raw: pd.DataFrame, coin: str) -> pd.DataFrame:
    """A coin's 5-minute bars as `liq.liquidations` rows: each bar's longs liquidated as one
    'sell' row and its shorts as one 'buy' row, stamped at the bar's open, summed over venues."""
    m = raw[raw["market"].isin(aggr.COINS[coin]["all"])].groupby("time")[["lsell", "lbuy"]].sum()
    t = m.index.to_numpy(dtype=float)
    return pd.concat([pd.DataFrame({"ts": t, "side": "sell", "usd": m["lsell"].to_numpy(), "venue": "aggr"}),
                      pd.DataFrame({"ts": t, "side": "buy", "usd": m["lbuy"].to_numpy(), "venue": "aggr"})],
                     ignore_index=True)


def binance_bars(coin: str, data: Path = lowsfwd.DATA) -> Optional[pd.DataFrame]:
    files = sorted((data / liq.symbol("binance-futures", coin)).glob("*.zip"))
    if not files:
        return None
    return liq.bars_5m(pd.concat([lowsfwd.read(f.read_bytes()) for f in files], ignore_index=True))


def ledger(data: Path = DATA, bars_data: Path = lowsfwd.DATA) -> pd.DataFrame:
    rows = []
    days = {f.name[:10]: f for f in sorted(data.glob("*.csv.gz"))}
    for coin in aggr.COINS:
        bars = binance_bars(coin, bars_data)
        if bars is None:
            continue
        for day, f in days.items():
            start = int(pd.Timestamp(day, tz="UTC").timestamp())
            window = bars[(bars.index >= start - 86400) & (bars.index < start + 2 * 86400)]
            if window.empty or not ((window.index >= start) & (window.index < start + 86400)).any():
                continue
            ev = liq.events(window, liq_rows(pd.read_csv(f), coin), start)
            rows.append(ev.assign(coin=coin, day=day))
    # a coin with no breaks is an empty object-typed table, and joining it would leave every column object-typed
    ev = pd.concat([r for r in rows if not r.empty] or rows, ignore_index=True) if rows else pd.DataFrame()
    if ev.empty:
        return ev
    use = liq.usable(ev)
    return ev.assign(group=liq.tag(use).reindex(ev.index))


def run(state_dir: Path, data: Path = DATA, now: Optional[pd.Timestamp] = None, fetch: Callable = aggr.fetch) -> dict:
    empty: List[str] = []
    saved = record(data, now, fetch, empty=empty)
    led = ledger(data)
    led.to_csv(Path(state_dir) / LEDGER, index=False, float_format="%.8g")
    note = f"mark: {len(led)} breaks on {led['day'].nunique() if len(led) else 0} days"
    if len(led):
        fd = led[(led["direction"] == -1) & (led["group"] == "forced")]
        if len(fd):
            mean = -float(fd.groupby("day")["y60"].mean().mean())
            note += f"; forced down-breaks bought: {len(fd)}, {1e4 * mean:+.1f} bps an hour (decides nothing)"
    if empty:
        # the ledger above is rebuilt from what is on disk; the step still fails, so the day is seen and retried
        raise RuntimeError(f"aggr returned no bars for {', '.join(empty)}: not saved, asked again next run "
                           f"(a day aggr no longer serves stays a gap; research/ERRATA.md, 2026-11-03). {note}")
    return {"note": note, "equity": None, "saved": saved}
