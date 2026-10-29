"""#32's forward test (research/FORWARD_FUNDSPLIT.md): #27's forced down-breaks split by
the Binance funding rate settled before each break. Above Binance's 0.01% default, longs
were paying to stay crowded, and their forced selling should overshoot more.

It reads #27's ledger (the daily job's liqbreak step writes it) and Binance's public
funding archive (monthly files), cached in data/funding/. Nothing trades; the running numbers decide
nothing.
"""
from __future__ import annotations

import io
import math
import urllib.error
import urllib.request
import zipfile
from pathlib import Path
from typing import Callable, Dict, List, Optional

import pandas as pd

from . import liq
from .levetf import welch
from .liq import clustered

FORWARD_FROM = "2026-10-30"
FORWARD_TO = "2027-03-31"
HALF = "2027-01-01"
BASELINE = 0.0001             # Binance's default 8-hour rate: above it, longs pay a premium
                              # (rates are scaled to 8 hours for coins settling every 4)
LEG_HURDLE = 0.0018
DATA = Path(__file__).resolve().parents[1] / "data" / "funding"
# Binance's public archive: its live API refuses US addresses (HTTP 451), see the amendment
URL = "https://data.binance.vision/data/futures/um/monthly/fundingRate/{sym}/{sym}-fundingRate-{month}.zip"
LEDGER_IN = "liqbreak_trades.csv"
LEDGER = "fundsplit_trades.csv"


def _get(url: str) -> Optional[bytes]:
    """The body, or None for a 404 (a month not published yet)."""
    try:
        with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "espero"}), timeout=60) as r:
            return r.read()
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            return None
        raise


def months(now: pd.Timestamp) -> List[str]:
    """From the month before the window to the month of `now`, capped at the window's end."""
    first = pd.Timestamp(FORWARD_FROM) - pd.Timedelta(days=1)
    last = min(pd.Timestamp(now.tz_convert(None).date()), pd.Timestamp(FORWARD_TO))
    return [m.strftime("%Y-%m") for m in pd.period_range(first, last, freq="M").to_timestamp()]


def parse(blob: bytes, scaled: bool = True) -> pd.DataFrame:
    """An archive month: `ts` (seconds) and `rate`, scaled to 8 hours (as #32 and #38 read it);
    `scaled=False` keeps the rate as settled, for summing over a hold (#45)."""
    with zipfile.ZipFile(io.BytesIO(blob)) as z:
        text = z.read(z.namelist()[0]).decode()
    header = text.split(",", 1)[0].strip() == "calc_time"
    df = pd.read_csv(io.StringIO(text), header=0 if header else None)
    df.columns = ["calc_time", "funding_interval_hours", "last_funding_rate"]
    return pd.DataFrame({"ts": (df["calc_time"].astype("int64") // 1000).to_numpy(),
                         "rate": (df["last_funding_rate"].astype(float)
                                  * (8 / df["funding_interval_hours"].astype(float) if scaled else 1.0)).to_numpy()})


def rates(sym: str, data: Path = DATA, now: Optional[pd.Timestamp] = None,
          get: Callable[[str], Optional[bytes]] = _get, scaled: bool = True) -> pd.DataFrame:
    """Every settlement the archive has published for the window's months, cached per month.
    A month not published yet is tried again next time."""
    now = pd.Timestamp.now(tz="UTC") if now is None else now
    frames = []
    for m in months(now):
        path = Path(data) / sym / f"{m}.zip"
        if not path.exists():
            blob = get(URL.format(sym=sym, month=m))
            if blob is None:
                continue
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(blob)
        frames.append(parse(path.read_bytes(), scaled))
    if not frames:
        return pd.DataFrame({"ts": pd.Series(dtype="int64"), "rate": pd.Series(dtype=float)})
    return pd.concat(frames, ignore_index=True).drop_duplicates("ts").sort_values("ts").reset_index(drop=True)


def attach(ev: pd.DataFrame, funding: Dict[str, pd.DataFrame]) -> pd.DataFrame:
    """Each break's `funding`: the last settlement at or before its close (NaN if none)."""
    out = []
    for coin, g in ev.groupby("coin", sort=False):
        f = funding.get(coin)
        g = g.sort_values("ts")
        if f is None or f.empty:
            out.append(g.assign(funding=math.nan))
            continue
        m = pd.merge_asof(g.astype({"ts": "int64"}), f.rename(columns={"rate": "funding"}).sort_values("ts"),
                          on="ts", direction="backward")
        out.append(m)
    return pd.concat(out, ignore_index=True) if out else ev.assign(funding=pd.Series(dtype=float))


def forced_down(ev: pd.DataFrame) -> pd.DataFrame:
    fd = ev[(ev["direction"] == -1) & (ev["group"] == "forced") & ev["funding"].notna()]
    return fd.assign(long60=-fd["y60"], long240=-fd["y240"], crowded=fd["funding"] > BASELINE)


def _days(fd: pd.DataFrame, col: str) -> pd.Series:
    return fd.dropna(subset=[col]).groupby("day")[col].mean()


def criteria(ev: pd.DataFrame) -> List[dict]:
    fd = forced_down(ev)
    hi, lo = fd[fd["crowded"]], fd[~fd["crowded"]]
    d1 = welch(_days(hi, "long60"), _days(lo, "long60"))
    leg = clustered(_days(hi, "long60"))
    halves = [welch(_days(hi[part(hi)], "long60"), _days(lo[part(lo)], "long60"))
              for part in (lambda x: x["day"] < HALF, lambda x: x["day"] >= HALF)]
    d4 = welch(_days(hi, "long240"), _days(lo, "long240"))
    bps = lambda x: f"{1e4 * x:+.1f} bps"  # noqa: E731
    return [
        {"criterion": "the crowd matters: crowded minus not, long 1h, D > 0, t >= 2",
         "actual": f"{bps(d1['diff'])}, t {d1['t']:.2f} ({len(hi)} crowded, {len(lo)} not)",
         "met": d1["diff"] > 0 and d1["t"] >= 2},
        {"criterion": "the crowded breaks pay: long 1h > 18 bps, t > 2",
         "actual": f"{bps(leg['mean'])}, t {leg['t']:.2f}, {leg['n']} days",
         "met": leg["mean"] > LEG_HURDLE and leg["t"] > 2},
        {"criterion": "not one stretch: D > 0 in each half",
         "actual": f"{bps(halves[0]['diff'])} (Oct-Dec), {bps(halves[1]['diff'])} (Jan-Mar)",
         "met": halves[0]["diff"] > 0 and halves[1]["diff"] > 0},
        {"criterion": "it lasts: D > 0 at 4 hours",
         "actual": f"{bps(d4['diff'])}, t {d4['t']:.2f}",
         "met": d4["diff"] > 0},
    ]


def verdict(rows: List[dict]) -> str:
    return "PASS" if all(r["met"] for r in rows) else "FAIL"


def run(state_dir: Path, data: Path = DATA, get: Optional[Callable[[str], Optional[bytes]]] = None,
        now: Optional[pd.Timestamp] = None) -> dict:
    """Join funding to #27's latest ledger and say where it stands (it decides nothing)."""
    path = Path(state_dir) / LEDGER_IN
    ev = pd.read_csv(path) if path.exists() and path.stat().st_size > 1 else pd.DataFrame()
    if ev.empty or "direction" not in ev:
        return {"note": "mark: no breaks yet", "equity": None}
    funding = {}
    for coin in ev["coin"].unique():
        try:
            funding[coin] = rates(liq.symbol("binance-futures", coin), data, now, get or _get)
        except (urllib.error.URLError, OSError, ValueError) as exc:
            raise RuntimeError(f"funding for {coin}: {exc}") from exc
    joined = attach(ev, funding)
    joined.to_csv(Path(state_dir) / LEDGER, index=False, float_format="%.8g")
    fd = forced_down(joined)
    hi = fd[fd["crowded"]]
    note = f"mark: {len(fd)} forced down-breaks, {len(hi)} after crowded funding"
    if len(hi) and len(fd) > len(hi):
        gap = float(_days(hi, "long60").mean() - _days(fd[~fd["crowded"]], "long60").mean())
        note += f" (crowded minus not {1e4 * gap:+.1f} bps an hour; decides nothing)"
    return {"note": note, "equity": None}
