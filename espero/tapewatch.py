"""The live tape on one screen: spread, depth, taker flow, liquidations and lag per venue.

Read from the files the recorder is writing now. Information, not a signal.

    espero rawrec --watch BTC,ETH          # refreshes every 2 s; ctrl-c stops
    espero rawrec --watch BTC --read       # adds a column of words for what the book and flow show: untested

Under each coin a second block gives trades, dollars, buy share and liquidations by side over 5 minutes,
30 minutes and an hour; the screen starts from the previous hour's file so the hour window is full.

It reads what `espero rawrec --loop` wrote in the last second, so it needs no second connection to any
venue and shows exactly what the tape holds, lag included. It draws two tables a coin on `rich`, sized
for an 80-column pane: the book, then flow by window. It shows no return and no rule. With `--read`
it adds, at the account holder's request, a column of words for what the book and the last minute's flow
show, with a net lean; that column is untested, outside the registry, written to no book or ledger, and
nothing in it was ever checked against what came next. A rule anyone wants to act on is a numbered
pre-registration, not this column.

Each venue's current book comes from the tape's own snapshots: Binance's `depth20@100ms` and Hyperliquid's
`l2Book` are whole books every frame; Bybit's `orderbook.50` and OKX's `books` are a snapshot plus deltas,
rebuilt from the last snapshot on the tape (the recorder requests one every five minutes), with OKX's
sequence chain checked (its checksum field reads 0 on this channel now), so a book that drifted shows a
dash rather than a wrong number.
"""

from __future__ import annotations

import collections
import datetime as dt
import json
import statistics
import sys
import time
import zlib
from pathlib import Path
from typing import Callable, Dict, Iterator, List, Optional, Tuple

from . import rawrec as rr

REFRESH_S = 2.0
FLOW_S = 60
LIQ_S = 300
WINDOWS = (("5m", 300), ("30m", 1800), ("1h", 3600))
KEEP_S = 3600
DEPTH_BPS = 10.0
LAG_FRAMES = 200
DELTA_BUFFER = 2000
BYBIT_WINDOW = 50
COINBASE_WINDOW = 50
OKX_WINDOW = 400
HL_NAME = rr.HL_NAME


def _iso_ms(text: str) -> int:
    """Coinbase's ISO-8601 time with microseconds and a Z, as ms."""
    t = text.rstrip("Z")
    head, _, frac = t.partition(".")
    base = dt.datetime.fromisoformat(head).replace(tzinfo=dt.timezone.utc)
    return int(base.timestamp() * 1000) + (int(frac[:3].ljust(3, "0")) if frac else 0)


def symbols_for(coin: str) -> Dict[str, str]:
    """The symbol each venue uses for a coin, as the recorder subscribes to it."""
    return {
        "binance": f"{coin}USDT",
        "bybit": f"{coin}USDT",
        "okx": f"{coin}-USDT-SWAP",
        "hyperliquid": HL_NAME.get(coin, coin),
        "coinbase": f"{coin}-USD",
    }


# ------------------------------------------------------------------ books
class Book:
    """One venue's book for one symbol, as the tape shows it."""

    def __init__(self, ct_val: float = 1.0):
        self.bids: Dict[float, float] = {}
        self.asks: Dict[float, float] = {}
        self.raw_bids: Dict[float, Tuple[str, str]] = {}
        self.raw_asks: Dict[float, Tuple[str, str]] = {}
        self.ok = False
        self.ct_val = ct_val
        self.whole = False  # whole-book frames: no deltas to apply

    def set(self, bids, asks) -> None:
        self.bids = {float(p): float(s) for p, s in bids if float(s) > 0}
        self.asks = {float(p): float(s) for p, s in asks if float(s) > 0}
        self.ok = bool(self.bids and self.asks) and max(self.bids) < min(self.asks)

    def apply(self, bids, asks, window: Optional[int] = None) -> None:
        for side, levels in ((self.bids, bids), (self.asks, asks)):
            for p, s in levels:
                p, s = float(p), float(s)
                if s == 0:
                    side.pop(p, None)
                else:
                    side[p] = s
        self.trim(window)

    def trim(self, window: Optional[int]) -> None:
        """Keep the top `window` levels a side: a venue that streams a window never deletes a level that
        left it. A crossed book is not a book: it reads as a dash until the next snapshot."""
        if window:
            for attr, rev in (("bids", True), ("asks", False)):
                d = getattr(self, attr)
                if len(d) > window:
                    keep = sorted(d, reverse=rev)[:window]
                    setattr(self, attr, {p: d[p] for p in keep})
                    raw = getattr(self, "raw_" + attr)
                    if raw:
                        setattr(self, "raw_" + attr, {p: raw[p] for p in keep if p in raw})
        self.ok = bool(self.bids and self.asks) and max(self.bids) < min(self.asks)

    def top(self) -> Tuple[Optional[float], Optional[float]]:
        if not self.ok:
            return None, None
        return max(self.bids), min(self.asks)

    def spread_bps(self) -> Optional[float]:
        b, a = self.top()
        if b is None or a <= b:
            return None
        return (a - b) / ((a + b) / 2) * 1e4

    def depth_usd(self, bps: float = DEPTH_BPS) -> Optional[float]:
        b, a = self.top()
        if b is None:
            return None
        mid = (a + b) / 2
        band = mid * bps / 1e4
        return sum(p * s * self.ct_val for p, s in self.bids.items() if mid - p <= band) + sum(
            p * s * self.ct_val for p, s in self.asks.items() if p - mid <= band
        )

    def prune_outside(self, best_bid: float, best_ask: float) -> None:
        """Drop levels a venue's ticker says are gone: bids above its best bid, asks below its best ask.
        A windowed feed (Coinbase's level2_50) never deletes a level that left the window."""
        self.bids = {p: s for p, s in self.bids.items() if p <= best_bid}
        self.asks = {p: s for p, s in self.asks.items() if p >= best_ask}
        self.ok = bool(self.bids and self.asks) and max(self.bids) < min(self.asks)

    def okx_checksum_ok(self, want: int) -> bool:
        """OKX: crc32 over the top 25 bid and ask levels interleaved, 'px:sz:px:sz...', on the strings the
        venue sent, never on reformatted floats."""
        bids = sorted(self.raw_bids.items(), reverse=True)[:25]
        asks = sorted(self.raw_asks.items())[:25]
        parts = []
        for i in range(25):
            if i < len(bids):
                parts += list(bids[i][1])
            if i < len(asks):
                parts += list(asks[i][1])
        crc = zlib.crc32(":".join(parts).encode())
        return (crc - (1 << 32) if crc >= 1 << 31 else crc) == want

    def set_raw(self, bids, asks) -> None:
        """OKX levels as sent, [px, sz, ...] strings, kept beside the floats for the checksum."""
        self.raw_bids = {float(x[0]): (x[0], x[1]) for x in bids if float(x[1]) > 0}
        self.raw_asks = {float(x[0]): (x[0], x[1]) for x in asks if float(x[1]) > 0}
        self.set([(x[0], x[1]) for x in bids], [(x[0], x[1]) for x in asks])

    def apply_raw(self, bids, asks) -> None:
        for side, raw_side, levels in ((self.bids, self.raw_bids, bids), (self.asks, self.raw_asks, asks)):
            for x in levels:
                p, sz = float(x[0]), float(x[1])
                if sz == 0:
                    side.pop(p, None)
                    raw_side.pop(p, None)
                else:
                    side[p] = sz
                    raw_side[p] = (x[0], x[1])
        self.trim(400)


class VenueState:
    """What the screen shows for one venue and coin, kept up to date frame by frame."""

    def __init__(self, venue: str, symbol: str, ct_val: float = 1.0):
        self.venue, self.symbol = venue, symbol
        self.book = Book(ct_val)
        self.book.whole = venue in ("binance", "hyperliquid")
        self.cb_seq: Optional[int] = None
        self.trades: collections.deque = collections.deque()  # (t_ms, usd, buy)
        self.liqs: collections.deque = collections.deque()  # (t_ms, usd, side)
        self.lags: collections.deque = collections.deque(maxlen=LAG_FRAMES)
        self.recent: collections.deque = collections.deque(maxlen=DELTA_BUFFER)  # (ts, bids, asks) deltas
        self.okx_seq: Optional[int] = None
        self.last_rt: Optional[int] = None
        self.frames = 0
        self.ct_val = ct_val

    def feed(self, rec: dict) -> None:
        ch, d = rec.get("ch"), rec.get("d")
        if not isinstance(d, dict):
            return
        rt = rec["rt"]
        v = self.venue
        if v == "okx" and ch == "liquidation-orders":
            for inst in d.get("data", []):
                if inst.get("instId") == self.symbol:
                    for t in inst.get("details", []):
                        self.liqs.append((int(t["ts"]), float(t["sz"]) * self.ct_val * float(t["bkPx"]), t["side"]))
            return
        if rec.get("s") != self.symbol:
            return
        self.frames += 1
        self.last_rt = rt
        if v == "binance":
            data = d.get("data", {})
            if ch == "depth20@100ms":
                self.book.set(data["b"], data["a"])
                self.lags.append(rt - int(data["E"]))
            elif ch == "trade":
                self.trades.append((int(data["T"]), float(data["p"]) * float(data["q"]), not data["m"]))
                self.lags.append(rt - int(data["T"]))
            elif ch == "forceOrder":
                o = data["o"]
                self.liqs.append((int(o["T"]), float(o["p"]) * float(o["q"]), o["S"].lower()))
        elif v == "bybit":
            data = d.get("data", {})
            if ch == "orderbook.50":
                ts = int(d["ts"])
                if d.get("type") == "snapshot" or data.get("u") == 1:
                    self.book.set(data["b"], data["a"])
                    self._replay(ts, raw=False)  # deltas already on the tape that are newer than it
                else:
                    self.recent.append((ts, data["b"], data["a"]))
                    if self.book.ok:
                        self.book.apply(data["b"], data["a"], BYBIT_WINDOW)
                self.lags.append(rt - ts)
            elif ch == "publicTrade":
                for t in data:
                    self.trades.append((int(t["T"]), float(t["p"]) * float(t["v"]), t["S"] == "Buy"))
                    self.lags.append(rt - int(t["T"]))
            elif ch == "allLiquidation":
                for t in data:
                    self.liqs.append((int(t["T"]), float(t["p"]) * float(t["v"]), "sell" if t["S"] == "Buy" else "buy"))
        elif v == "okx":
            if ch == "rest.books":
                data = d["data"][0]
                self.book.set_raw(data["bids"], data["asks"])
                self.okx_seq = None  # the chain restarts from the next update
                self._replay(int(data.get("ts", 0)), raw=True)
            elif ch == "books":
                for data in d.get("data", []):
                    ts = int(data["ts"])
                    seq, prev = int(data.get("seqId", -1)), int(data.get("prevSeqId", -1))
                    if d.get("action") == "snapshot":
                        self.book.set_raw(data["bids"], data["asks"])
                    else:
                        self.recent.append((ts, data["bids"], data["asks"]))
                        if self.book.ok and self.okx_seq is not None and prev != self.okx_seq and prev != -1:
                            self.book.ok = False  # a sequence gap: a dash until the next snapshot
                        if self.book.ok:
                            self.book.apply_raw(data["bids"], data["asks"])
                    self.okx_seq = seq
                    # OKX sends checksum 0 on this channel now (seen 2026-11-02); a non-zero one is checked
                    if (
                        self.book.ok
                        and int(data.get("checksum", 0)) != 0
                        and not self.book.okx_checksum_ok(int(data["checksum"]))
                    ):
                        self.book.ok = False  # drifted: a dash until the next snapshot
                    self.lags.append(rt - ts)
            elif ch == "trades":
                for t in d.get("data", []):
                    self.trades.append(
                        (int(t["ts"]), float(t["px"]) * float(t["sz"]) * self.ct_val, t["side"] == "buy")
                    )
                    self.lags.append(rt - int(t["ts"]))
        elif v == "coinbase":
            if ch == "snapshot":
                self.book.set(d["bids"], d["asks"])
            elif ch == "l2update":
                self.lags.append(rt - _iso_ms(d["time"]))
                if self.book.ok:
                    bids = [(p, sz) for side, p, sz in d["changes"] if side == "buy"]
                    asks = [(p, sz) for side, p, sz in d["changes"] if side == "sell"]
                    self.book.apply(bids, asks, COINBASE_WINDOW)
            elif ch == "rest.book":
                self.book.set([(x[0], x[1]) for x in d["bids"]], [(x[0], x[1]) for x in d["asks"]])
            elif ch == "ticker" and d.get("best_bid") and d.get("best_ask"):
                self.book.prune_outside(float(d["best_bid"]), float(d["best_ask"]))
            elif ch in ("match", "last_match"):
                t_ms = _iso_ms(d["time"])
                self.trades.append(
                    (t_ms, float(d["price"]) * float(d["size"]), d["side"] == "sell")
                )  # the maker sold: the taker bought
                self.lags.append(rt - t_ms)
        elif v == "hyperliquid":
            if ch == "l2Book":
                lv = d["data"]["levels"]
                self.book.set([(x["px"], x["sz"]) for x in lv[0]], [(x["px"], x["sz"]) for x in lv[1]])
                self.lags.append(rt - int(d["data"]["time"]))
            elif ch == "trades":
                for t in d.get("data", []):
                    self.trades.append((int(t["time"]), float(t["px"]) * float(t["sz"]), t["side"] == "B"))
                    self.lags.append(rt - int(t["time"]))

    def _replay(self, snapshot_ts: int, raw: bool) -> None:
        """A snapshot the recorder fetched on the side (Bybit's second subscription, OKX's REST) lands on
        the tape after deltas that are newer than it: apply those again on top, in order."""
        for ts, bids, asks in list(self.recent):
            if ts > snapshot_ts and self.book.ok:
                if raw:
                    self.book.apply_raw(bids, asks)
                else:
                    self.book.apply(bids, asks, BYBIT_WINDOW)

    def window(self, now_ms: int, seconds: int) -> Dict[str, object]:
        """Trades, dollars, buy share and liquidations by side over the last `seconds` (an hour is kept)."""
        since = now_ms - seconds * 1000
        tr = [x for x in self.trades if x[0] >= since]
        usd = sum(x[1] for x in tr)
        buy = sum(x[1] for x in tr if x[2])
        lq = [x for x in self.liqs if x[0] >= since]
        return {
            "trades": len(tr),
            "usd": usd,
            "buy_share": buy / usd if usd else None,
            "liq_buy": sum(x[1] for x in lq if x[2] == "buy"),
            "liq_sell": sum(x[1] for x in lq if x[2] == "sell"),
        }

    def row(self, now_ms: int) -> Dict[str, object]:
        while self.trades and now_ms - self.trades[0][0] > KEEP_S * 1000:
            self.trades.popleft()
        while self.liqs and now_ms - self.liqs[0][0] > KEEP_S * 1000:
            self.liqs.popleft()
        minute, five = self.window(now_ms, FLOW_S), self.window(now_ms, LIQ_S)
        b, a = self.book.top()
        return {
            "venue": self.venue,
            "bid": b,
            "ask": a,
            "spread_bps": self.book.spread_bps(),
            "depth_usd": self.book.depth_usd(),
            "trades_1m": minute["trades"],
            "usd_1m": minute["usd"],
            "buy_share": minute["buy_share"],
            "liq_buy_5m": five["liq_buy"],
            "liq_sell_5m": five["liq_sell"],
            "lag_ms": statistics.median(self.lags) if self.lags else None,
            "age_s": (now_ms - self.last_rt) / 1000 if self.last_rt else None,
            "frames": self.frames,
            "windows": {name: self.window(now_ms, sec) for name, sec in WINDOWS},
        }


# ------------------------------------------------------------------ following the tape
def follow(
    raw: Path,
    venue: str,
    clock: Callable[[], int] = lambda: int(time.time() * 1000),
    start_ms: Optional[int] = None,
    symbols: Optional[List[str]] = None,
) -> Iterator[Optional[dict]]:
    """Yield records as the recorder writes them: the hour file of `start_ms` (default now) from the
    beginning, then every new line, moving to the next hour's file when it appears and this one is read.
    Yields None when nothing new arrived. Cut frames (a restart) are handled as `rawrec.FrameDecoder` does."""
    pos = 0
    path = rr.hour_path(raw, venue, start_ms or clock())
    fh = None
    dec = None
    keys = [f'"s":"{s_}"'.encode() for s_ in symbols] + [b'"ch":"liquidation-orders"'] if symbols else None
    while True:
        want = rr.hour_path(raw, venue, clock())
        if fh is None and path.exists():
            want = path  # begin where asked (an hour back), not at now
        elif fh is not None and want != path:
            # drain what the recorder wrote to this hour after the last read before leaving it
            while True:
                tail = fh.read(1 << 20)
                if not tail:
                    break
                pos += len(tail)
                yield from (r for r in dec.feed(tail, only=keys) if not r.get("truncated"))
            day, hh = path.parent.name, int(path.stem.split(".")[0])
            t = dt.datetime.strptime(f"{day} {hh:02d}", "%Y-%m-%d %H").replace(tzinfo=dt.timezone.utc)
            following = rr.hour_path(raw, venue, int(t.timestamp() * 1000) + 3_600_000)
            if following != want and following.exists():
                want = following  # the hour after this one, before jumping to now
        if fh is None or (want != path and want.exists()):
            if fh is not None:
                fh.close()
                fh = None
            if want.exists():
                path = want
            if not path.exists():
                yield None
                continue
            fh = path.open("rb")
            dec, pos = rr.FrameDecoder(), 0
        fh.seek(pos)
        got = False
        while True:
            # in pieces, as read_lines does: one read() of an hour fed to the decoder at once held the whole
            # decompressed hour in memory (gigabytes for Binance's, at the start of every watch and livesig loop)
            data = fh.read(1 << 20)
            if not data:
                break
            got = True
            pos += len(data)
            for rec in dec.feed(data, only=keys):
                if not rec.get("truncated"):
                    yield rec
        if not got:
            yield None
            continue


def okx_ct_vals(raw: Path) -> Dict[str, float]:
    path = raw / "okx" / "instruments.json"
    if not path.exists():
        return {}
    return {k: float(v["ctVal"]) for k, v in json.loads(path.read_text()).get("instruments", {}).items()}


# ------------------------------------------------------------------ the untested read, opt-in
def read_of(row: Dict[str, object], book: Book) -> str:
    """Words for what the book and the last minute show, asked for with --read. Not a registered signal:
    outside the ledger, untested, and nothing here was checked against what came next. The book's lean
    (bid against ask dollars in the band), the taker flow's lean, which side is being liquidated, and a
    net lean when book and flow agree."""
    b, a = book.top()
    parts, votes = [], 0
    if b is not None:
        mid = (a + b) / 2
        band = mid * DEPTH_BPS / 1e4
        bid_usd = sum(p * s * book.ct_val for p, s in book.bids.items() if mid - p <= band)
        ask_usd = sum(p * s * book.ct_val for p, s in book.asks.items() if p - mid <= band)
        tot = bid_usd + ask_usd
        lean = (bid_usd - ask_usd) / tot if tot else 0.0
        parts.append("bid-heavy" if lean > 0.2 else "ask-heavy" if lean < -0.2 else "book even")
        votes += 1 if lean > 0.2 else -1 if lean < -0.2 else 0
    share = row.get("buy_share")
    if share is not None:
        parts.append("buyers" if share > 0.6 else "sellers" if share < 0.4 else "flow even")
        votes += 1 if share > 0.6 else -1 if share < 0.4 else 0
    lb, ls = row["liq_buy_5m"], row["liq_sell_5m"]
    if lb or ls:
        parts.append("shorts liquidated" if lb > ls else "longs liquidated")
    if not parts:
        return "-"
    parts.append("leans up" if votes >= 2 else "leans down" if votes <= -2 else "no lean")
    return ", ".join(parts)


# ------------------------------------------------------------------ the screen
def render(coin: str, rows: List[Dict[str, object]], now_ms: int, reads: Optional[List[str]] = None) -> str:
    def f(x, fmt, dash="-"):
        return dash if x is None else format(x, fmt)

    label = "information, not a signal" + ("; the read column is untested and outside the registry" if reads else "")
    lines = [
        f"{coin}  {dt.datetime.fromtimestamp(now_ms / 1000, dt.timezone.utc):%H:%M:%S} UTC   {label}",
        f"{'venue':<12}{'bid':>12}{'ask':>12}{'spread bps':>11}{'depth ±10bps':>14}{'trades/1m':>10}"
        f"{'$M/1m':>8}{'buy':>6}{'liq buy 5m':>12}{'liq sell 5m':>12}{'lag ms':>8}{'age s':>7}"
        + ("   read" if reads else ""),
    ]
    for i, r in enumerate(rows):
        depth = "-" if r["depth_usd"] is None else f"{r['depth_usd'] / 1e6:.1f}M"
        lines.append(
            f"{r['venue']:<12}{f(r['bid'], ',.6g'):>12}{f(r['ask'], ',.6g'):>12}{f(r['spread_bps'], '.2f'):>11}"
            f"{depth:>14}{r['trades_1m']:>10}{r['usd_1m'] / 1e6:>8.2f}{f(r['buy_share'], '.2f'):>6}"
            f"{r['liq_buy_5m'] / 1e3:>11.0f}k{r['liq_sell_5m'] / 1e3:>11.0f}k"
            f"{f(r['lag_ms'], '.0f'):>8}{f(r['age_s'], '.0f'):>7}"
            + (f"   {reads[i]}" if reads else "")
        )
    lines.append(
        f"{'flow by window':<12}"
        + "".join(f"{name:>8}{'$M':>8}{'buy':>6}{'liq buy':>9}{'liq sell':>10}" for name, _ in WINDOWS)
    )
    for r in rows:
        cells = ""
        for name, _ in WINDOWS:
            w = r["windows"][name]
            cells += (
                f"{w['trades']:>8}{w['usd'] / 1e6:>8.2f}{f(w['buy_share'], '.2f'):>6}"
                f"{w['liq_buy'] / 1e3:>8.0f}k{w['liq_sell'] / 1e3:>9.0f}k"
            )
        lines.append(f"{r['venue']:<12}" + cells)
    return "\n".join(lines)


# ------------------------------------------------------------------ the screen, on rich
def _fmt_px(x: Optional[float]) -> str:
    """A price with the decimals its size needs: 78,400.1, 2,302.46, 88.120, 0.08106."""
    if x is None:
        return "-"
    decimals = 1 if x >= 10_000 else 2 if x >= 1_000 else 3 if x >= 10 else 5 if x >= 0.1 else 6
    return f"{x:,.{decimals}f}"


def _fmt_usd(x: float) -> str:
    """Dollars as a short word: 0.4k, 26k, 2.6M, 35M."""
    if x >= 1e6:
        return f"{x / 1e6:.1f}M" if x < 1e7 else f"{x / 1e6:.0f}M"
    if x >= 1e3:
        return f"{x / 1e3:.0f}k" if x >= 1e4 else f"{x / 1e3:.1f}k"
    return f"{x:.0f}" if x else "0"


def _pct(x: Optional[float]) -> str:
    return "-" if x is None else f"{x * 100:.0f}%"


def tables(coin: str, rows: List[Dict[str, object]], now_ms: int, reads: Optional[List[str]] = None):
    """Rich tables for one coin, sized for an 80-column pane: the book, flow by window, and with `reads` a
    third of words per venue."""
    from rich import box
    from rich.table import Table

    stamp = dt.datetime.fromtimestamp(now_ms / 1000, dt.timezone.utc).strftime("%H:%M:%S")
    book = Table(
        title=f"{coin}  {stamp} UTC",
        title_justify="left",
        box=box.SIMPLE_HEAD,
        pad_edge=False,
        show_edge=False,
        expand=False,
    )
    for name, just in (
        ("venue", "left"),
        ("bid", "right"),
        ("ask", "right"),
        ("sprd bps", "right"),
        ("depth ±10", "right"),
        ("lag ms", "right"),
        ("age", "right"),
    ):
        book.add_column(name, justify=just, no_wrap=True)
    for r in rows:
        cells = [
            r["venue"],
            _fmt_px(r["bid"]),
            _fmt_px(r["ask"]),
            "-" if r["spread_bps"] is None else f"{r['spread_bps']:.2f}",
            "-" if r["depth_usd"] is None else _fmt_usd(r["depth_usd"]),
            "-" if r["lag_ms"] is None else f"{r['lag_ms']:.0f}",
            "-" if r["age_s"] is None else f"{r['age_s']:.0f}s",
        ]
        book.add_row(*cells, style="dim" if r["bid"] is None else "")
    flow = Table(
        box=box.SIMPLE_HEAD,
        pad_edge=False,
        show_edge=False,
        expand=False,
        caption="$ traded (taker buy %) · liq: $ liquidated, buys/sells",
        caption_justify="left",
    )
    flow.add_column("flow", justify="left", no_wrap=True)
    for name in ("1m",) + tuple(n for n, _ in WINDOWS):
        flow.add_column(name, justify="right", no_wrap=True)
    for r in rows:
        w = {"1m": {"usd": r["usd_1m"], "buy_share": r["buy_share"], "liq_buy": 0.0, "liq_sell": 0.0}, **r["windows"]}
        cells = [r["venue"]]
        for name in ("1m",) + tuple(n for n, _ in WINDOWS):
            x = w[name]
            line = f"{_fmt_usd(x['usd'])} ({_pct(x['buy_share'])})"
            if name != "1m" and (x["liq_buy"] or x["liq_sell"]):
                line += f"\nliq {_fmt_usd(x['liq_buy'])}/{_fmt_usd(x['liq_sell'])}"
            cells.append(line)
        flow.add_row(*cells)
    if not reads:
        return book, flow
    read = Table(box=box.SIMPLE_HEAD, pad_edge=False, show_edge=False, expand=False)
    read.add_column("venue", justify="left", no_wrap=True)
    read.add_column("read (untested, outside the registry)", justify="left", overflow="fold", max_width=60, style="dim")
    for r, words in zip(rows, reads):
        read.add_row(r["venue"], words)
    return book, flow, read


def screen(
    coins: List[str], states: Dict[Tuple[str, str], "VenueState"], venues: Tuple[str, ...], now_ms: int, read: bool
):
    """The whole screen as one rich renderable."""
    from rich.console import Group
    from rich.text import Text

    parts = []
    for c in coins:
        rows = [states[(c, v)].row(now_ms) for v in venues]
        reads = [read_of(rows[i], states[(c, v)].book) for i, v in enumerate(venues)] if read else None
        parts += list(tables(c, rows, now_ms, reads)) + [Text("")]
    note = "information, not a signal" + ("; the read column is untested and outside the registry" if read else "")
    parts.append(
        Text(
            note + "\nBinance depth: top 20 levels; Coinbase and Bybit 50; OKX 400. A dash: the rebuilt book "
            "is not trustworthy until the next snapshot.",
            style="dim",
        )
    )
    return Group(*parts)


def watch(
    raw: Path,
    coins: List[str],
    refresh_s: float = REFRESH_S,
    out=sys.stdout,
    clock=lambda: int(time.time() * 1000),
    max_rounds: Optional[int] = None,
    sleep=time.sleep,
    read: bool = False,
) -> int:
    ct = okx_ct_vals(raw)
    venues = ("binance", "bybit", "okx", "hyperliquid", "coinbase")
    states = {
        (c, v): VenueState(v, symbols_for(c)[v], ct.get(symbols_for(c)["okx"], 1.0) if v == "okx" else 1.0)
        for c in coins
        for v in venues
    }
    try:
        import os

        os.nice(10)  # the recorder wins the CPU; this screen can wait
    except (OSError, AttributeError):
        pass
    start = clock() - KEEP_S * 1000  # from the previous hour's file, so the hour window is full
    feeds = {v: follow(raw, v, clock, start_ms=start, symbols=[symbols_for(c)[v] for c in coins]) for v in venues}
    rounds = 0
    try:
        from rich.console import Console
        from rich.live import Live

        console = Console(file=out, force_terminal=out is sys.stdout)
    except ImportError:  # the tui extra is missing: the plain layout
        console = None

    def catch_up() -> int:
        for v, gen in feeds.items():
            for rec in gen:
                if rec is None:
                    break
                for c in coins:
                    states[(c, v)].feed(rec)
        return clock()  # after the read, so an age is never negative

    if console is None:
        while max_rounds is None or rounds < max_rounds:
            now = catch_up()
            text = "\n\n".join(
                render(
                    c,
                    [states[(c, v)].row(now) for v in venues],
                    now,
                    [read_of(states[(c, v)].row(now), states[(c, v)].book) for v in venues] if read else None,
                )
                for c in coins
            )
            out.write("\x1b[2J\x1b[H" + text + "\n")
            out.flush()
            rounds += 1
            sleep(refresh_s)
        return 0
    with Live(
        screen(coins, states, venues, clock(), read),
        console=console,
        screen=out is sys.stdout,
        auto_refresh=False,
        transient=False,
    ) as live:
        while max_rounds is None or rounds < max_rounds:
            now = catch_up()
            live.update(screen(coins, states, venues, now, read), refresh=True)
            rounds += 1
            sleep(refresh_s)
    return 0
