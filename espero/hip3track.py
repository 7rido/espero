"""#73: does a trade.xyz perp follow its listed ticker, hour by hour and at the bell?
(research/PREREGISTRATION_HIP3TRACK.md)

The registered measurement and its tolerances, pure: prices in, numbers out, no I/O. research/hip3track.py
fetches and prints. A measurement, information only: nothing here is a verdict on a rule.
"""
from __future__ import annotations

import datetime as dt
import math
import statistics
from dataclasses import dataclass
from typing import Dict, Iterable, List, Mapping, Optional, Sequence, Tuple
from zoneinfo import ZoneInfo

ET = ZoneInfo("America/New_York")
WINDOW = ("2026-09-21", "2026-11-07")       # UTC days, the end excluded
KINDS = ("US stock", "ETF", "leveraged ETF", "index", "commodity")
FUTURES_KINDS = ("index", "commodity")
MIN_DAY_USD = 5e6
QUARTER_S = 900
MAX_STEP_S = 65 * 60
MIN_PAIRS = 100
MIN_CORR = 0.90
MAX_MEDIAN_BPS = 10.0
MAX_P95_BPS = 50.0
SESSION_SHARE = 0.80
SESSIONS = ("pre-market", "regular", "after-hours", "futures hours")


def session(ts: int) -> Optional[str]:
    """A stock's session at unix second `ts`, by the Eastern clock; None overnight (20:00 to 04:00)."""
    t = dt.datetime.fromtimestamp(ts, ET)
    h = t.hour + t.minute / 60
    if 4 <= h < 9.5:
        return "pre-market"
    if 9.5 <= h < 16:
        return "regular"
    if 16 <= h < 20:
        return "after-hours"
    return None


def pairs(bars: Sequence[Tuple[int, float]], perp: Mapping[int, float], futures: bool = False,
          skip_days: Iterable[str] = ()) -> List[Tuple[str, float, float]]:
    """(session, the ticker's return, the perp's return) for consecutive ticker bars on one Eastern date, at most
    65 minutes apart, both starting on a quarter hour where the perp has a price. `bars` is (start, open), sorted;
    `perp` is the open of the 15-minute candle starting at each second; `skip_days` are Eastern dates left out."""
    skip = set(skip_days)
    out = []
    for (t0, o0), (t1, o1) in zip(bars, bars[1:]):
        if not (0 < t1 - t0 <= MAX_STEP_S) or t0 % QUARTER_S or t1 % QUARTER_S:
            continue
        d0, d1 = (dt.datetime.fromtimestamp(t, ET).date().isoformat() for t in (t0, t1))
        if d0 != d1 or d0 in skip:
            continue
        p0, p1 = perp.get(t0), perp.get(t1)
        if not (o0 and o1 and p0 and p1) or min(o0, o1, p0, p1) <= 0:
            continue
        s = "futures hours" if futures else session(t0)
        if s is None:
            continue
        out.append((s, o1 / o0 - 1, p1 / p0 - 1))
    return out


@dataclass(frozen=True)
class Stat:
    n: int
    corr: Optional[float]
    median_bps: Optional[float]      # of |perp - ticker|
    p95_bps: Optional[float]
    mean_bps: Optional[float]        # of perp - ticker, signed: a drift between the two

    @property
    def enough(self) -> bool:
        return self.n >= MIN_PAIRS

    @property
    def follows(self) -> bool:
        return (self.enough and self.corr is not None and self.corr >= MIN_CORR
                and self.median_bps <= MAX_MEDIAN_BPS and self.p95_bps <= MAX_P95_BPS)


def _corr(a: Sequence[float], b: Sequence[float]) -> Optional[float]:
    if len(a) < 3:
        return None
    ma, mb = statistics.fmean(a), statistics.fmean(b)
    va, vb = sum((x - ma) ** 2 for x in a), sum((y - mb) ** 2 for y in b)
    if va <= 0 or vb <= 0:
        return None
    return sum((x - ma) * (y - mb) for x, y in zip(a, b)) / math.sqrt(va * vb)


def percentile(xs: Sequence[float], q: float) -> float:
    """The value at or above the share `q` of the sorted values (nearest rank)."""
    s = sorted(xs)
    return s[min(len(s) - 1, max(0, math.ceil(q * len(s)) - 1))]


def stat(rows: Sequence[Tuple[float, float]]) -> Stat:
    """From (ticker return, perp return) pairs."""
    if not rows:
        return Stat(0, None, None, None, None)
    diff = [(p - t) * 1e4 for t, p in rows]
    absd = [abs(x) for x in diff]
    return Stat(len(rows), _corr([t for t, _ in rows], [p for _, p in rows]), statistics.median(absd),
                percentile(absd, 0.95), statistics.fmean(diff))


def by_session(prs: Sequence[Tuple[str, float, float]]) -> Dict[str, Stat]:
    out: Dict[str, List[Tuple[float, float]]] = {}
    for s, t, p in prs:
        out.setdefault(s, []).append((t, p))
    return {s: stat(v) for s, v in out.items()}


def stands_in(stats: Iterable[Stat]) -> Tuple[Optional[bool], int, int]:
    """(does the session stand in, markets following, markets with enough pairs); None with no market to judge."""
    enough = [s for s in stats if s.enough]
    good = sum(1 for s in enough if s.follows)
    return (good / len(enough) >= SESSION_SHARE if enough else None), good, len(enough)


def bell(days: Sequence[Tuple[int, float, float]], perp: Mapping[int, float], skip_days: Iterable[str] = ()
         ) -> Dict[str, Optional[float]]:
    """A stock's medians, in bps: the perp at 09:30 Eastern against the official open, at 16:00 against the close,
    and its overnight return against the ticker's. `days` is (the session's start in unix seconds, open, close)."""
    skip = set(skip_days)
    opens, closes, nights = [], [], []
    last: Optional[Tuple[float, float]] = None          # the previous kept day's (official close, perp at 16:00)
    for start, o, c in days:
        if dt.datetime.fromtimestamp(start, ET).date().isoformat() in skip or not (o and c):
            last = None
            continue
        t_open = start
        t_close = int(dt.datetime.fromtimestamp(start, ET).replace(hour=16, minute=0, second=0).timestamp())
        p_open, p_close = perp.get(t_open), perp.get(t_close)
        if p_open:
            opens.append(abs(p_open / o - 1) * 1e4)
            if last is not None:
                nights.append(abs((p_open / last[1] - 1) - (o / last[0] - 1)) * 1e4)
        if p_close:
            closes.append(abs(p_close / c - 1) * 1e4)
        last = (c, p_close) if p_close else None
    med = lambda v: statistics.median(v) if v else None  # noqa: E731
    return {"days": len(opens), "open_bps": med(opens), "close_bps": med(closes), "overnight_bps": med(nights)}


def bell_stands_in(medians: Iterable[Optional[float]]) -> Optional[bool]:
    """The median across markets of each market's median gap, against the 10 bps tolerance."""
    got = [m for m in medians if m is not None]
    return statistics.median(got) <= MAX_MEDIAN_BPS if got else None
