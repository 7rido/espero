"""Hyperliquid's builder-deployed perps (HIP-3): what is listed, what a fill costs in fees, which markets trade
enough, and which listed ticker each one follows. A reader only: it places nothing and judges no strategy.

One exchange carries the stocks, indexes and commodities: trade.xyz, `xyz`, whose coins are named "xyz:NVDA". Its
markets began on 2025-10-13, so any test longer than a year runs on the listed ticker (`research/hip3_map.csv`,
checked by hand on 2026-11-09), and how closely the perp follows that ticker is #73's measurement, not assumed here.

    espero hip3              # the markets now, from one request
    espero hip3 --screen     # the 30-day liquidity screen: one paced request per market, kept in state/

**Fees.** A builder exchange charges the venue's fee times a scale (twice it, at trade.xyz's deployer scale of 1),
and a tenth of that while a market is in "growth mode" (Hyperliquid's fee schedule, read 2026-11-09). The deployer
switches growth mode per market, so `fees_bps` is computed from what the venue reports now and is never a constant.

**The screen.** A market passes when the median of its last 30 complete days' dollar volume is at least
`MIN_DAY_USD`. Only markets whose last 24 hours already reach that are asked for their days: the venue's request
limit is per address and this Mac's recorders share it, so the screen sends one request every `PAUSE_S` seconds.
"""
from __future__ import annotations

import csv
import json
import statistics
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Dict, Iterable, List, Optional, Sequence, Tuple

from .venues import VENUES

DEX = "xyz"
GROWTH_SCALE = 0.1
MIN_DAY_USD = 5e6
SCREEN_DAYS = 30
PAUSE_S = 10.0
DAY_MS = 86_400_000
MAP = Path(__file__).resolve().parents[1] / "research" / "hip3_map.csv"
SCREEN = "hip3_screen.json"
KINDS = ("US stock", "ETF", "leveraged ETF", "index", "commodity", "Korea stock", "Japan stock", "Hong Kong stock",
         "no listed equivalent")


@dataclass(frozen=True)
class Market:
    coin: str                     # "xyz:NVDA"
    price: float                  # the mark
    change: float                 # since the venue's previous day, a fraction
    funding_h: float              # hourly; positive: longs pay shorts
    oi_usd: float
    volume_usd: float             # the last 24 hours
    max_leverage: int
    taker_bps: float
    maker_bps: float
    growth: bool
    impact_bps: Optional[float]   # the venue's impact ask over its impact bid: a round trip's price cost

    @property
    def name(self) -> str:
        return self.coin.split(":", 1)[-1]


@dataclass(frozen=True)
class Equivalent:
    ticker: str                   # Yahoo's symbol; empty: none
    kind: str
    since: str                    # the ticker's first trade date, ISO; empty: none
    note: str = ""

    def years(self, today: str) -> Optional[float]:
        if not self.since:
            return None
        a, b = (time.strptime(x, "%Y-%m-%d") for x in (self.since, today))
        return (time.mktime(b) - time.mktime(a)) / 86_400 / 365.25


def fee_scale(deployer_scale: float) -> float:
    """What a builder exchange multiplies the venue's fee by: 1 + the deployer's share below 1, twice it from 1."""
    return deployer_scale + 1 if deployer_scale < 1 else deployer_scale * 2


def fees_bps(deployer_scale: float, growth: bool, venue: str = "hyperliquid") -> Tuple[float, float]:
    """(taker, maker) in bps at the base tier, before any staking or volume discount."""
    k = fee_scale(deployer_scale) * (GROWTH_SCALE if growth else 1.0)
    return VENUES[venue].taker_bps * k, VENUES[venue].maker_bps * k


def parse(payload) -> List[Market]:
    """`metaAndAssetCtxs` for one builder exchange; delisted markets and rows without a price are left out."""
    meta, ctxs = payload
    out = []
    for u, c in zip(meta["universe"], ctxs):
        if u.get("isDelisted"):
            continue
        try:
            mark, prev = float(c["markPx"]), float(c["prevDayPx"])
            growth = u.get("growthMode") == "enabled"
            taker, maker = fees_bps(float(u.get("deployerFeeScale", 1.0)), growth)
            imp = c.get("impactPxs")
            out.append(Market(u["name"], mark, mark / prev - 1 if prev > 0 else 0.0, float(c["funding"]),
                              float(c["openInterest"]) * mark, float(c["dayNtlVlm"]), int(u.get("maxLeverage", 0)),
                              taker, maker, growth,
                              (float(imp[1]) / float(imp[0]) - 1) * 1e4 if imp and float(imp[0]) > 0 else None))
        except (KeyError, TypeError, ValueError):
            continue
    return out


def markets(dex: str = DEX, post: Optional[Callable] = None) -> List[Market]:
    """The live markets of one builder exchange, always from mainnet: one request."""
    from . import hyperliquid as hl

    post = post or (lambda body: hl.post(body, url=hl.MAINNET_URL + "/info"))
    return parse(post({"type": "metaAndAssetCtxs", "dex": dex}))


def ticker_map(path: Path = MAP) -> Dict[str, Equivalent]:
    """Market name (without the exchange's prefix) -> its listed equivalent."""
    with Path(path).open(newline="", encoding="utf-8") as fh:
        return {r["coin"]: Equivalent(r["ticker"], r["kind"], r["since"], r.get("note", ""))
                for r in csv.DictReader(fh)}


def median_day_usd(candles: Sequence[dict], now_ms: int, days: int = SCREEN_DAYS) -> Optional[float]:
    """The median dollar volume of the last `days` complete UTC days, from the venue's daily candles (volume in
    coins, times the close). The day still forming is left out; fewer than `days` complete days is no answer."""
    today = now_ms // DAY_MS * DAY_MS
    done = sorted((int(c["t"]), float(c["v"]) * float(c["c"])) for c in candles if int(c["t"]) < today)
    if len(done) < days:
        return None
    return statistics.median(v for _, v in done[-days:])


def screen(rows: Iterable[Market], candles_of: Callable[[str], Sequence[dict]], now_ms: int,
           min_usd: float = MIN_DAY_USD, pause_s: float = PAUSE_S, sleep: Callable[[float], None] = time.sleep
           ) -> List[dict]:
    """Each market whose last 24 hours reach `min_usd`, with its 30-day median and whether that passes too."""
    out = []
    asked = [m for m in sorted(rows, key=lambda m: -m.volume_usd) if m.volume_usd >= min_usd]
    for i, m in enumerate(asked):
        med = median_day_usd(candles_of(m.coin), now_ms)
        out.append({"coin": m.coin, "volume_usd": m.volume_usd, "median_day_usd": med,
                    "passes": med is not None and med >= min_usd})
        if i + 1 < len(asked):
            sleep(pause_s)
    return out


def daily_candles(coin: str, now_ms: int, post: Optional[Callable] = None) -> List[dict]:
    from . import hyperliquid as hl

    post = post or (lambda body: hl.post(body, url=hl.MAINNET_URL + "/info"))
    req = {"coin": coin, "interval": "1d", "startTime": now_ms - (SCREEN_DAYS + 5) * DAY_MS, "endTime": now_ms}
    return post({"type": "candleSnapshot", "req": req})


def read_screen(state: Path) -> Optional[dict]:
    try:
        return json.loads((Path(state) / SCREEN).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def write_screen(state: Path, rows: List[dict], now_ms: int, dex: str = DEX) -> Path:
    path = Path(state) / SCREEN
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps({"at_ms": now_ms, "dex": dex, "min_day_usd": MIN_DAY_USD, "days": SCREEN_DAYS,
                               "rows": rows}, indent=1), encoding="utf-8")
    tmp.replace(path)
    return path


def _usd(x: Optional[float]) -> str:
    if x is None:
        return "-"
    return f"${x / 1e9:,.1f}B" if x >= 1e9 else f"${x / 1e6:,.1f}M" if x >= 1e6 else f"${x / 1e3:,.0f}K"


def render(rows: Sequence[Market], eq: Dict[str, Equivalent], screened: Optional[dict], today: str,
           min_usd: float = MIN_DAY_USD) -> str:
    """The markets whose last 24 hours reach `min_usd`, most traded first, as text."""
    med = {r["coin"]: r for r in (screened or {}).get("rows", [])}
    lines = [f"{'market':10s} {'ticker':10s} {'kind':18s} {'price':>10s} {'today':>7s} {'24 h':>8s} {'30-day':>8s} "
             f"{'take':>5s} {'rest':>5s} {'funding/yr':>10s} {'history':>8s}"]
    shown = [m for m in sorted(rows, key=lambda m: -m.volume_usd) if m.volume_usd >= min_usd]
    for m in shown:
        e = eq.get(m.name, Equivalent("", "not mapped", ""))
        yrs = e.years(today)
        s = med.get(m.coin)
        lines.append(f"{m.name:10s} {e.ticker or '-':10s} {e.kind:18s} {m.price:10,.2f} {m.change:+7.1%} "
                     f"{_usd(m.volume_usd):>8s} {_usd(s['median_day_usd']) if s else '?':>8s} {m.taker_bps:5.1f} "
                     f"{m.maker_bps:5.1f} {m.funding_h * 24 * 365:+10.0%} "
                     f"{'-' if yrs is None else f'{yrs:.1f} y':>8s}")
    n_pass = sum(1 for m in shown if med.get(m.coin, {}).get("passes"))
    lines.append("")
    lines.append(f"{len(rows)} live markets, {len(shown)} with {_usd(min_usd)} or more in the last 24 hours"
                 + (f", {n_pass} of them above that on the 30-day median too." if screened else
                    ". 30-day medians: run `espero hip3 --screen` (about 10 seconds a market)."))
    lines.append("take and rest: the fee in bps for a market and a resting order, as the venue reports the market now. "
                 "history: years the listed ticker has traded.")
    return "\n".join(lines)


def main(argv=None) -> int:
    import argparse

    ap = argparse.ArgumentParser(prog="espero hip3")
    ap.add_argument("--screen", action="store_true", help="fetch each market's days and keep the 30-day screen")
    ap.add_argument("--state-dir", default=str(Path(__file__).resolve().parents[1] / "state"))
    a = ap.parse_args(argv)
    now_ms = int(time.time() * 1000)
    rows = markets()
    if a.screen:
        got = screen(rows, lambda coin: daily_candles(coin, now_ms), now_ms)
        print(f"kept {write_screen(Path(a.state_dir), got, now_ms)}")
    print(render(rows, ticker_map(), read_screen(Path(a.state_dir)), time.strftime("%Y-%m-%d", time.gmtime())))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
