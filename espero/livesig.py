"""#71: the streaming signal engine on the raw tape, against the next-day batch (research/PREREGISTRATION_LIVESIG.md).

The engine turns Binance `trade` frames into 5-minute bars as they arrive (by the trade's own time, volume in base
units as Binance's klines count it), closes a bar on the tape's clock two seconds past its end, and calls the batch's
own rule functions, with the daily steps' own arguments, on each coin's panel: #24 `lows.events`, #31 `bids.events`,
#29 and #34 `levetf.rows`. It emits (rule, coin, side, ts) with the receive time that closed the bar, and keeps no
return the functions compute. The comparison replays a recorded day as it was written and matches its events against
the same functions on Binance's archive bars, and on the tape's own bars rebuilt after the day closed.

    espero livesig --replay DAY      # the events a running engine emitted on DAY: counts and latency only
    espero livesig --compare DAY     # those against the next-day batch's, per rule
    espero livesig --loop            # follow the tape as it is written; events to state/livesig_events.csv
"""
from __future__ import annotations

import csv
import datetime as dt
import json
import time
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Dict, Iterable, Iterator, List, Optional, Sequence, Tuple

import numpy as np
import pandas as pd

from . import bids, bidsfwd, latency, liq, lows, lowsfwd
from . import levetf as lv

BAR_S = 300
BAR_MS = BAR_S * 1000
CLOSE_GRACE_MS = 2_000
PANEL_BARS = 2 * 288                 # the rules look back at most 48 bars (and an hour of dedupe); two days is ample
COINS = latency.TAPE_BINANCE
RULE_COINS = {"24": COINS, "31": COINS, "29": ("BTC", "ETH"), "34": ("SOL", "XRP")}
SYMBOL = {liq.symbol("binance-futures", c): c for c in COINS}
DAY_AGREES = 0.95
REPRODUCES = 0.90
FIRST_COMPARABLE = "2026-11-04"
EVENTS = "livesig_events.csv"
FIELDS = ["rule", "coin", "side", "ts", "emitted_ms"]


@dataclass(frozen=True)
class Event:
    rule: str
    coin: str
    side: str                          # "buy" or "sell"
    ts: int                            # the entry time the rule reports, unix seconds
    emitted_ms: Optional[int] = None   # the tape's receive time when the engine knew it

    @property
    def key(self) -> Tuple[str, str, str, int]:
        return (self.rule, self.coin, self.side, self.ts)


def trade_of(rec: dict) -> Optional[Tuple[str, int, float, float]]:
    """(coin, trade time in ms, price, quantity in base units) from a Binance `trade` record, else None. A record
    without a positive price and size is not a trade: the stream sends some (`"X": "NA"`, price 0, size 0, about
    5,000 in three hours across the 13 coins on 2026-11-02), and counted as trades they would put zero lows in
    the bars (ERRATA, 2026-11-02, #71)."""
    if rec.get("ch") != "trade" or not isinstance(rec.get("d"), dict):
        return None
    data = rec["d"].get("data", {})
    coin = SYMBOL.get(data.get("s", ""))
    if coin is None:
        return None
    px, qty = float(data["p"]), float(data["q"])
    if not (px > 0 and qty > 0):
        return None
    return coin, int(data["T"]), px, qty


class Bars:
    """5-minute bars per coin, closed on the tape's clock. A coin with no trade in a closed bar gets one at its last
    close with volume 0, as Binance's klines do; a trade for a bar already closed is counted late, not applied."""

    def __init__(self, coins: Sequence[str] = COINS):
        self.coins = tuple(coins)
        self.open: Dict[str, Dict[int, list]] = {c: {} for c in self.coins}
        self.closed: Dict[str, Dict[int, list]] = {c: {} for c in self.coins}
        self.last_close: Dict[str, float] = {}
        self.closed_until: Optional[int] = None          # bars starting before this are closed
        self.late: Counter = Counter()

    def seed(self, coin: str, frame: pd.DataFrame) -> None:
        """Closed bars from elsewhere (the tape rebuilt for the days before a replay), in lows.bars' shape."""
        for ts, r in frame.iterrows():
            self.closed[coin][int(ts)] = [float(r["open"]), float(r["high"]), float(r["low"]), float(r["close"]),
                                          float(r["volume"])]
        if len(frame):
            self.last_close[coin] = float(frame["close"].iloc[-1])
            end = int(frame.index.max()) + BAR_S
            self.closed_until = end if self.closed_until is None else max(self.closed_until, end)

    def add(self, coin: str, t_ms: int, px: float, qty: float) -> None:
        start = t_ms // BAR_MS * BAR_S
        if self.closed_until is not None and start < self.closed_until:
            self.late[coin] += 1
            return
        b = self.open[coin].get(start)
        if b is None:
            self.open[coin][start] = [px, px, px, px, qty]
        else:
            b[1], b[2], b[3], b[4] = max(b[1], px), min(b[2], px), px, b[4] + qty

    def close(self, rt_ms: int) -> List[int]:
        """Close every bar whose end plus the grace is at or before `rt_ms`; return their starts, oldest first."""
        limit = (rt_ms - CLOSE_GRACE_MS) // BAR_MS * BAR_S          # bars starting before this have ended + grace
        if self.closed_until is None:
            starts = [s for c in self.coins for s in self.open[c]]
            if not starts:
                return []
            self.closed_until = min(starts)
        done = []
        for s in range(self.closed_until, limit, BAR_S):
            for c in self.coins:
                b = self.open[c].pop(s, None)
                if b is not None:
                    self.closed[c][s] = b
                    self.last_close[c] = b[3]
                elif c in self.last_close:
                    p = self.last_close[c]
                    self.closed[c][s] = [p, p, p, p, 0.0]
            done.append(s)
        self.closed_until = max(self.closed_until, limit)
        return done

    def frame(self, coin: str, last: Optional[int] = None) -> pd.DataFrame:
        """The coin's closed bars in lows.bars' shape: indexed by open time in seconds."""
        items = sorted(self.closed[coin].items())
        if last is not None:
            items = items[-last:]
        if not items:
            return pd.DataFrame(columns=["open", "high", "low", "close", "volume"], index=pd.Index([], name="ts"))
        ts, vals = zip(*items)
        return pd.DataFrame(list(vals), columns=["open", "high", "low", "close", "volume"],
                            index=pd.Index(list(ts), name="ts"))


# ------------------------------------------------------------------ the rules, as the batch computes them
def _date(ts: int) -> dt.date:
    return dt.datetime.fromtimestamp(ts, tz=dt.timezone.utc).date()


def events_24(bars: pd.DataFrame, coin: str) -> List[Event]:
    ev = lows.events(bars, "down", first=lowsfwd.FORWARD_FROM, last=lowsfwd.FORWARD_TO)
    return [Event("24", coin, "buy", int(t)) for t in ev["ts"]]


def events_31(bars: pd.DataFrame, coin: str) -> List[Event]:
    ev = bids.events(bars, None, bidsfwd.FORWARD_FROM, bidsfwd.FORWARD_TO, k=bidsfwd.K_ATR, hold=bidsfwd.HOLD,
                     taker_bars=bidsfwd.TAKER_BARS)
    return [Event("31", coin, "buy", int(t)) for t in ev["ts"]]


def events_close(bars: pd.DataFrame, coin: str, day: dt.date, rule: str) -> List[Event]:
    """#29 (after 16:00 ET, against the day's move) and #34 (15:45 to 16:00 ET, with it), from levetf.rows."""
    row = lv.rows(bars, coin, day.isoformat(), day.isoformat())
    if row.empty:
        return []
    r = float(row["r_post15" if rule == "29" else "r"].iloc[0])
    if not np.isfinite(r) or r == 0:
        return []
    side = ("sell" if r > 0 else "buy") if rule == "29" else ("buy" if r > 0 else "sell")
    return [Event(rule, coin, side, lv.at(day, 16, 0) if rule == "29" else lv.at(day, 15, 45))]


def signal_bar(rule: str, day: dt.date) -> Optional[int]:
    """The start of the bar whose close decides #29 or #34 on `day`, or None on a day it does not trade."""
    if lv.kind(day) == "early":
        return None
    return (lv.at(day, 16, 0) if rule == "29" else lv.at(day, 15, 45)) - BAR_S


def day_events(bars: Dict[str, pd.DataFrame], day: str) -> List[Event]:
    """Every in-scope event the batch functions give on `day`'s bars (24/31 by their trigger's UTC day)."""
    d = dt.date.fromisoformat(day)
    out: List[Event] = []
    for rule, coins in RULE_COINS.items():
        for c in coins:
            b = bars.get(c)
            if b is None or b.empty:
                continue
            if rule in ("24", "31"):
                fn = events_24 if rule == "24" else events_31
                out += [e for e in fn(b, c) if _date(e.ts - BAR_S) == d]
            elif signal_bar(rule, d) is not None:
                out += events_close(b, c, d, rule)
    return out


# ------------------------------------------------------------------ the engine
class Engine:
    """Feed it the tape's records in receive order; it returns the events each closed bar reveals, once each."""

    def __init__(self, coins: Sequence[str] = COINS):
        self.bars = Bars(coins)
        self.seen: set = set()

    def feed(self, rec: dict) -> List[Event]:
        t = trade_of(rec)
        if t is not None:
            self.bars.add(*t)
        rt = rec.get("rt")
        if rt is None:
            return []
        out: List[Event] = []
        for s in self.bars.close(int(rt)):
            out += self._evaluate(s, int(rt))
        return out

    def _evaluate(self, start: int, rt: int) -> List[Event]:
        found: List[Event] = []
        day = _date(start)
        for rule, coins in RULE_COINS.items():
            for c in coins:
                if c not in self.bars.coins:
                    continue
                if rule in ("24", "31"):
                    b = self.bars.frame(c, PANEL_BARS)
                    if b.empty:
                        continue
                    fn = events_24 if rule == "24" else events_31
                    found += [e for e in fn(b, c) if e.ts == start + BAR_S]
                elif signal_bar(rule, day) == start:
                    found += events_close(self.bars.frame(c), c, day, rule)
        out = []
        for e in found:
            if e.key not in self.seen:
                self.seen.add(e.key)
                out.append(Event(e.rule, e.coin, e.side, e.ts, rt))
        return out


# ------------------------------------------------------------------ the tape and the archive
def tape_records(raw: Path, day: str, only: Sequence[bytes] = (b'"ch":"trade"', b'"_meta"')) -> Iterator[dict]:
    """One day's Binance records in receive order, trades and the recorder's own meta lines only."""
    from . import rawrec

    folder = raw / "binance" / day
    for path in sorted(folder.glob("*" + rawrec.SUFFIX)) if folder.is_dir() else []:
        dec = rawrec.FrameDecoder()
        with path.open("rb") as fh:
            while True:
                chunk = fh.read(1 << 20)
                if not chunk:
                    break
                yield from (r for r in dec.feed(chunk, only=list(only)) if not r.get("truncated"))
        yield from (r for r in dec.finish() if not r.get("truncated"))


def tape_bars(raw: Path, days: Iterable[str]) -> Dict[str, pd.DataFrame]:
    """The tape's bars for whole days, late frames included: the closed-tape batch's input, and a replay's warm-up."""
    b = Bars()
    last = None
    for day in days:
        for rec in tape_records(raw, day):
            t = trade_of(rec)
            if t is not None:
                start = t[1] // BAR_MS * BAR_S
                bar = b.open[t[0]].setdefault(start, [])
                if not bar:
                    bar += [t[2], t[2], t[2], t[2], t[3]]
                else:
                    bar[1], bar[2], bar[3], bar[4] = max(bar[1], t[2]), min(bar[2], t[2]), t[2], bar[4] + t[3]
                last = start if last is None else max(last, start)
    if last is not None:
        b.close((last + BAR_S) * 1000 + CLOSE_GRACE_MS)                # through the last traded bar, no further
    return {c: b.frame(c) for c in b.coins}


def archive_bars(coins: Sequence[str] = COINS, data: Path = lowsfwd.DATA) -> Dict[str, pd.DataFrame]:
    """Binance's own 5-minute bars for the in-scope coins, as the daily steps read them."""
    out = {}
    for c in coins:
        files = sorted((Path(data) / liq.symbol("binance-futures", c)).glob("*.zip"))
        if files:
            out[c] = lows.bars(pd.concat([lowsfwd.read(f.read_bytes()) for f in files], ignore_index=True))
    return out


def warm_days(day: str) -> List[str]:
    """The days a replay of `day` seeds its panel with: the one before, and back to the previous NYSE session."""
    d = dt.date.fromisoformat(day)
    first = min(d - dt.timedelta(days=1), _date(lv.reference(d)))
    return [x.isoformat() for x in lv.days(first.isoformat(), (d - dt.timedelta(days=1)).isoformat())]


def replay(raw: Path, day: str, warm: Optional[Dict[str, pd.DataFrame]] = None) -> Tuple[List[Event], Counter]:
    """The events a running engine emitted on `day`: the days before as the warm-up, `day` streamed as written."""
    eng = Engine()
    for c, frame in (warm if warm is not None else tape_bars(raw, warm_days(day))).items():
        eng.bars.seed(c, frame)
    out: List[Event] = []
    for rec in tape_records(raw, day):
        out += eng.feed(rec)
    end = int(dt.datetime.fromisoformat(day).replace(tzinfo=dt.timezone.utc).timestamp()) + 86_400
    out += eng.feed({"rt": (end + 10 * BAR_S) * 1000})
    return [e for e in out if _date(e.ts - (BAR_S if e.rule in ("24", "31") else 0)).isoformat() == day], eng.bars.late


def compare(live: Sequence[Event], batch: Sequence[Event]) -> Dict[str, object]:
    """Matched on (rule, coin, side, ts): the agreement over the union, and what only one side saw."""
    a, b = {e.key for e in live}, {e.key for e in batch}
    union = a | b
    return {"live": len(a), "batch": len(b), "matched": len(a & b), "union": len(union),
            "agreement": len(a & b) / len(union) if union else 1.0,
            "live_only": sorted(a - b), "batch_only": sorted(b - a)}


def day_reading(live: Sequence[Event], batch: Sequence[Event], closed_tape: Sequence[Event]) -> Dict[str, object]:
    """One comparable day: the agreement overall and per rule, whether the day agrees, and each miss's class."""
    out = compare(live, batch)
    out["agrees"] = out["agreement"] >= DAY_AGREES
    out["per_rule"] = {r: compare([e for e in live if e.rule == r], [e for e in batch if e.rule == r])["agreement"]
                       for r in RULE_COINS}
    tape = {e.key for e in closed_tape}
    out["input"] = [k for k in out["live_only"] + out["batch_only"] if (k in tape) == (k in {e.key for e in live})]
    out["streaming"] = [k for k in out["live_only"] + out["batch_only"] if k not in out["input"]]
    return out


def reading(days: Sequence[Dict[str, object]]) -> Dict[str, object]:
    """Over the comparable days: the share that agree, and whether the engine reproduces the batch."""
    n = len(days)
    share = sum(1 for d in days if d["agrees"]) / n if n else float("nan")
    return {"days": n, "agreeing": share, "reproduces": bool(n >= 30 and share >= REPRODUCES)}


def latency_ms(events: Sequence[Event]) -> Dict[str, Tuple[float, float]]:
    """Per rule: the median and 95th percentile of the receive time past the deciding bar's end."""
    out = {}
    for r in RULE_COINS:
        lag = [e.emitted_ms - e.ts * 1000 for e in events if e.rule == r and e.emitted_ms is not None]
        if lag:
            out[r] = (float(np.median(lag)), float(np.percentile(lag, 95)))
    return out


def append_events(path: Path, events: Sequence[Event]) -> None:
    new = not path.exists()
    with open(path, "a", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        if new:
            w.writerow(FIELDS)
        for e in events:
            w.writerow([e.rule, e.coin, e.side, e.ts, e.emitted_ms])


def loop(raw: Path, state_dir: Path, clock: Callable[[], int] = lambda: int(time.time() * 1000)) -> None:
    """Follow the Binance tape as it is written (tapewatch.follow) and append each event as it is known."""
    from . import tapewatch

    today = dt.datetime.now(dt.timezone.utc).date().isoformat()
    eng = Engine()
    cut = (clock() - CLOSE_GRACE_MS) // BAR_MS * BAR_S        # only bars that have closed seed the panel
    for c, frame in tape_bars(raw, warm_days(today) + [today]).items():
        eng.bars.seed(c, frame[frame.index < cut])
    path = state_dir / EVENTS
    for rec in tapewatch.follow(raw, "binance", clock=clock, start_ms=None):
        if rec is None:
            evs = eng.feed({"rt": clock()})
            time.sleep(0.5)
        else:
            evs = eng.feed(rec)
        if evs:
            append_events(path, evs)


def main(argv=None) -> int:
    import argparse
    import os

    from . import rawrec

    ap = argparse.ArgumentParser(prog="espero livesig")
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--replay", metavar="DAY")
    g.add_argument("--compare", metavar="DAY")
    g.add_argument("--loop", action="store_true")
    ap.add_argument("--state-dir", default=str(Path(__file__).resolve().parents[1] / "state"))
    a = ap.parse_args(argv)
    raw = rawrec.raw_dir(os.environ)
    if a.loop:
        loop(raw, Path(a.state_dir))
        return 0
    day = a.replay or a.compare
    live, late = replay(raw, day)
    if a.replay:
        print(json.dumps({"day": day, "events": Counter(e.rule for e in live), "late_frames": sum(late.values()),
                          "latency_ms": latency_ms(live)}, indent=1, default=dict))
        return 0
    batch = day_events(archive_bars(), day)
    closed = day_events(tape_bars(raw, warm_days(day) + [day]), day)
    r = day_reading(live, batch, closed)
    print(json.dumps({k: v for k, v in r.items() if k not in ("live_only", "batch_only", "input", "streaming")}
                     | {"live_only": len(r["live_only"]), "batch_only": len(r["batch_only"]),
                        "input_misses": len(r["input"]), "streaming_misses": len(r["streaming"])}, indent=1))
    return 0


def rule():
    """The registered measurement is `day_reading` over `replay` and `day_events`; the scaffold's test looks here."""
    return day_reading
