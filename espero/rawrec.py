"""Raw market data as it arrives: every websocket frame from Bybit, OKX and Hyperliquid, appended to hourly zstd files.

What `hlbook` and `hlcollect` keep is a sample: a book every five minutes, a context every five. This keeps
the stream itself, so a bar can be rebuilt from the prints that made it (#61) and a fill can be replayed
on the book that was there (#62). Nothing here signs, trades or reads a key; every subscription is public.

    espero rawrec --loop            # what launchd runs; ESPERO_RAW_DIR must be set
    espero rawrec --status          # files, bytes and the last receive time, per venue and day; never a value
    espero rawrec --gaps 2026-11-03 # where the stream was silent, from the tape itself
    espero rawrec --manifest        # MANIFEST.sha256 into every closed day folder (espero.manifest)

**Where.** `ESPERO_RAW_DIR`, and only there. Unset, the recorder refuses to start; inside the repo's `data/`,
it refuses too, because launchd's `hlcollect` and `hlbook` own that folder and a second writer there is the
one thing AGENTS.md forbids a recorder. The layout is `<raw>/<venue>/<YYYY-MM-DD>/<HH>.ndjson.zst`, one file
per venue and UTC hour, all channels and symbols together, so a restart has one file to append to.

**What a line is.** `{"rt": <receive time, ms>, "ch": <channel>, "s": <symbol>, "d": <the frame, verbatim>}`.
`rt` is this machine's clock when the frame was read; the exchange's own time is inside `d`. The recorder
parses a frame only far enough to name its channel and symbol and copies the bytes as they came, so a
downstream reader argues with the venue, not with this module. Control frames (subscribe acks, pongs) are
kept under channel `_ctrl`; the recorder's own events (open, reconnect, heartbeat every minute, errors,
snapshot requests) under `_meta`. A gap is therefore visible on the tape: `gaps()` reads nothing else.

**One writer.** `Recorder.run` holds an `flock` on `<raw>/rawrec.lock` (`espero.lock`); a second recorder
on the same folder refuses to start, and launchd's KeepAlive simply retries until the first one is gone.

**Append-only.** A file is opened for appending and each session writes one zstd frame into it; zstd frames
concatenate, so a restart adds a frame rather than rewriting the hour. A stop (SIGTERM from launchd, ctrl-c)
closes the frame; a crash or a kill leaves it without its end, and `read_lines()` returns what was decodable,
says so (`truncated`), and reads on from the next frame. Nothing is ever rewritten.

**The venues.**
* Bybit USDT perps: `publicTrade`, `orderbook.50` (20 ms deltas after a snapshot), `allLiquidation`. Its REST
  is refused from this machine (CloudFront, by country), so the periodic snapshot is a second, short websocket
  subscription every `SNAPSHOT_EVERY_S`: the subscribe response is a full book.
* OKX USDT swaps: `trades`, `books` (400 levels, 100 ms deltas with a checksum), `liquidation-orders` for every
  swap (the venue pushes all instruments on one subscription; everything it pushes is kept), and a REST
  `market/books?sz=400` snapshot every `SNAPSHOT_EVERY_S`. Sizes on OKX are contracts: `instruments.json`,
  written at each start, holds each swap's contract value.
* Hyperliquid mainnet: `trades` and `l2Book` (each `l2Book` frame is a full top-20 book, so no snapshot is needed).
  Hyperliquid publishes no liquidation stream; its liquidations are trades like any other.
* Hyperliquid testnet: the same two channels, for the coins #12's maker mirror rests orders on, so #62 can
  replay those fills on the book they rested in.
* Coinbase Exchange spot (added 2026-11-02 at the account holder's request): `matches` (every trade; `side` is
  the maker's, so a `sell` maker means the taker bought), `level2_batch` (a 50-level snapshot, then changes
  every 50 ms, absolute sizes; the venue serves it as `level2_50`, and a level that leaves the window is never
  deleted), `ticker` (the best bid and ask on every trade, which prunes those stale levels), `heartbeat`, and a
  REST level-2 book every
  `SNAPSHOT_EVERY_S`. BTC-USD, ETH-USD and the carry books' coins, whose spot leg #12 prices there.
* Binance USDⓈ-M: `trade` (every print, what aggr-server itself reads), `aggTrade`, `depth@100ms` (diffs,
  absolute size per level), `depth20@100ms` (the top 20 levels whole, every 100 ms: the snapshot the diffs
  are anchored to), `forceOrder`, `markPrice@1s`, `bookTicker`, and a REST `depth?limit=1000` snapshot where
  REST answers. **From this machine, checked 2026-11-02:** `fapi.binance.com` answers HTTP 451 (so no
  1000-level snapshot; one attempt an hour is on the tape), the single-stream `wss://fstream.binance.com/ws/...`
  never completes its handshake, and the combined `wss://fstream.binance.com/stream?streams=...` connects
  and streams, but only some streams: `trade`, `depth@100ms`, `depth20@100ms` and `bookTicker` deliver frames;
  `aggTrade`, `forceOrder`, `markPrice@1s` and `kline_1m` open and stay silent (probed one at a time). So here
  Binance's prints and books are live and its liquidations and mark price are not; the archive has prints,
  quotes and a mark-price kline but no liquidations either. The recorder uses the combined endpoint with the
  whole list, so a machine Binance treats differently records the rest; the streams are in the URL, so it
  sends no subscribe message. `espero.binance_archive` backfills
  the public archive for the gaps. Binance's own words on `forceOrder`: "For each symbol, only the latest one
  liquidation order within 1000ms will be pushed as the snapshot. If no liquidation happens in the interval
  of 1000ms, no stream will be pushed." So a cascade of ten liquidations in a second reaches every
  subscriber, aggr included, as one order; the archive has no liquidation dataset at all (checked 2026-11-01).

**Coins.** The 14 coins aggr's forward bars cover (`espero.aggr.COINS`), on each venue that lists them, plus
on Hyperliquid the ten `hlbook` records and every coin a paper book holds. The list is frozen in
`<raw>/coins.json` at the first start with its rule; a coin a paper book opens later is added, with the time
it was added, never removed. The watch reads the books' journals read-only, every `WATCH_EVERY_S`.

**What stays weak.** The recorder of record is a laptop that sleeps. Every gap is on the tape and in
`--gaps`; none is patched from another source. Disk: the first 17 minutes on 2026-11-02 put the five feeds
together near 4 GB a day, 6 with Coinbase (docs/DATA.md, section 5); `FREE_FLOOR_GB` stops the book
channels, trades continue, when the volume holding `ESPERO_RAW_DIR` falls under it.
"""

from __future__ import annotations

import asyncio
import datetime as dt
import json
import logging
import os
import shutil
import sqlite3
import time
import urllib.request
from pathlib import Path
from typing import Callable, Dict, Iterable, Iterator, List, Optional, Tuple

from . import manifest
from .aggr import COINS

log = logging.getLogger("espero.rawrec")

ENV = "ESPERO_RAW_DIR"
SUFFIX = ".ndjson.zst"
VENUES = ("bybit", "okx", "hyperliquid", "hyperliquid_testnet", "binance", "coinbase")
HEARTBEAT_S = 60
SNAPSHOT_EVERY_S = 300
WATCH_EVERY_S = 900
MANIFEST_EVERY_S = 3600
FLUSH_EVERY_S = 1.0
BINANCE_RETRY_S = 3600
FREE_FLOOR_GB = 30.0
HL_NAME = {"SHIB": "kSHIB"}  # Hyperliquid lists some coins in thousands
HL_MAINNET_WS = "wss://api.hyperliquid.xyz/ws"
HL_TESTNET_WS = "wss://api.hyperliquid-testnet.xyz/ws"
BYBIT_WS = "wss://stream.bybit.com/v5/public/linear"
OKX_WS = "wss://ws.okx.com/ws/v5/public"
OKX_REST = "https://www.okx.com/api/v5"
BINANCE_WS = "wss://fstream.binance.com/stream?streams="
COINBASE_WS = "wss://ws-feed.exchange.coinbase.com"
COINBASE_REST = "https://api.exchange.coinbase.com"
BINANCE_REST = "https://fapi.binance.com/fapi/v1"
BINANCE_STREAMS = ("trade", "aggTrade", "depth@100ms", "depth20@100ms", "forceOrder", "markPrice@1s", "bookTicker")
BOOK_CHANNELS = {
    "bybit": ("orderbook.50",),
    "okx": ("books", "rest.books"),
    "hyperliquid": ("l2Book",),
    "hyperliquid_testnet": ("l2Book",),
    "binance": ("depth@100ms", "depth20@100ms", "rest.depth"),
    "coinbase": ("snapshot", "l2update", "rest.book"),
}
PROJECT = Path(__file__).resolve().parents[1]


# ------------------------------------------------------------------ where
def raw_dir(env: Optional[dict] = None, project: Path = PROJECT) -> Path:
    """`ESPERO_RAW_DIR`, resolved. Unset, or anywhere under the repo's data/, is refused."""
    env = os.environ if env is None else env
    value = (env.get(ENV) or "").strip()
    if not value:
        raise RuntimeError(f"{ENV} is not set: the raw recorder writes only to a folder named there, never data/")
    path = Path(value).expanduser().resolve()
    data = (project / "data").resolve()
    if path == data or data in path.parents:
        raise RuntimeError(f"{ENV}={value} is inside {data}: launchd's hlcollect and hlbook own that folder")
    return path


def hour_of(rt_ms: int) -> int:
    return rt_ms - rt_ms % 3_600_000


def hour_path(raw: Path, venue: str, rt_ms: int) -> Path:
    t = dt.datetime.fromtimestamp(rt_ms / 1000, dt.timezone.utc)
    return Path(raw) / venue / t.strftime("%Y-%m-%d") / (t.strftime("%H") + SUFFIX)


def day_folders(raw: Path, venue: str) -> List[Path]:
    v = Path(raw) / venue
    return sorted(p for p in v.glob("????-??-??") if p.is_dir()) if v.is_dir() else []


# ------------------------------------------------------------------ the line
def line(rt_ms: int, channel: str, symbol: str, frame: bytes) -> bytes:
    """One NDJSON line; `frame` is the venue's JSON text, embedded verbatim."""
    head = json.dumps({"rt": int(rt_ms), "ch": channel, "s": symbol}, separators=(",", ":"))
    frame = frame.strip()
    if frame[:1] not in (b"{", b"["):  # a text frame such as OKX's "pong": kept as a JSON string
        frame = json.dumps(frame.decode("utf-8", "replace")).encode()
    return head[:-1].encode() + b',"d":' + frame + b"}\n"


def meta(rt_ms: int, event: str, **fields) -> bytes:
    return line(rt_ms, "_meta", "", json.dumps({"ev": event, **fields}, separators=(",", ":")).encode())


def classify(venue: str, frame: bytes) -> Tuple[str, str]:
    """(channel, symbol) of a frame, parsed only as far as that takes. Unknown shapes are `_ctrl`."""
    try:
        d = json.loads(frame)
    except ValueError:
        return "_ctrl", ""
    if not isinstance(d, dict):
        return "_ctrl", ""
    if venue == "bybit":
        topic = d.get("topic")
        if topic and "data" in d:
            ch, _, sym = topic.rpartition(".")
            return (ch or topic), sym
    elif venue == "okx":
        arg = d.get("arg") or {}
        if "data" in d and arg.get("channel"):
            return arg["channel"], arg.get("instId") or arg.get("instType") or ""
    elif venue in ("hyperliquid", "hyperliquid_testnet"):
        ch, data = d.get("channel"), d.get("data")
        if ch == "trades" and isinstance(data, list) and data:
            return ch, str(data[0].get("coin", ""))
        if ch == "l2Book" and isinstance(data, dict):
            return ch, str(data.get("coin", ""))
    elif venue == "binance":
        stream = d.get("stream")
        if stream and "data" in d:
            sym, _, ch = stream.partition("@")
            return ch, sym.upper()
    elif venue == "coinbase":
        t = d.get("type")
        if t in ("match", "last_match", "snapshot", "l2update", "ticker") and d.get("product_id"):
            return t, str(d["product_id"])
    return "_ctrl", ""


# ------------------------------------------------------------------ files
class HourWriter:
    """Append lines to `<raw>/<venue>/<day>/<HH>.ndjson.zst`, one zstd frame per session and hour."""

    def __init__(self, raw: Path, venue: str, level: int = 9):
        self.raw, self.venue, self.level = Path(raw), venue, level
        self._hour: Optional[int] = None
        self._fh = None
        self._zw = None
        self.lines = 0
        self.bytes = 0

    def _open(self, rt_ms: int) -> None:
        import zstandard

        self.close()
        path = hour_path(self.raw, self.venue, rt_ms)
        path.parent.mkdir(parents=True, exist_ok=True)
        self._fh = path.open("ab")
        self._zw = zstandard.ZstdCompressor(level=self.level).stream_writer(self._fh, closefd=False)
        self._hour = hour_of(rt_ms)

    def write(self, data: bytes, rt_ms: Optional[int] = None) -> None:
        """Append one line; the hour file is chosen by the line's own `rt` unless `rt_ms` says otherwise."""
        rt = rt_ms if rt_ms is not None else _rt_of(data)
        if self._zw is None or hour_of(rt) != self._hour:
            self._open(rt)
        self._zw.write(data)
        self.lines += 1
        self.bytes += len(data)

    def flush(self) -> None:
        if self._zw is not None:
            import zstandard

            self._zw.flush(zstandard.FLUSH_BLOCK)
            self._fh.flush()

    def close(self) -> None:
        if self._zw is not None:
            self._zw.close()
            self._fh.close()
            self._zw = self._fh = None
            self._hour = None


def _rt_of(data: bytes) -> int:
    m = _RT.match(data)
    return int(m.group(1)) if m else int(time.time() * 1000)


_RT = __import__("re").compile(rb'\{"rt":(\d+)')


ZSTD_MAGIC = b"\x28\xb5\x2f\xfd"
FRAME_HEADER_MAX = 18


def _next_frame(data: bytes, start: int) -> int:
    """Offset of the next frame start in `data` at or after `start`: the magic followed by a header zstd
    accepts, so four random bytes inside a frame are not mistaken for one. -1 when there is none."""
    import zstandard

    k = data.find(ZSTD_MAGIC, start)
    while k >= 0:
        if len(data) - k < FRAME_HEADER_MAX:
            return k  # maybe: the caller keeps these bytes for the next piece
        try:
            zstandard.get_frame_parameters(data[k : k + FRAME_HEADER_MAX])
            return k
        except zstandard.ZstdError:
            k = data.find(ZSTD_MAGIC, k + 1)
    return -1


class FrameDecoder:
    """The state machine behind `read_lines` and `tapewatch.follow`: bytes in, records out, across the
    concatenated zstd frames of one hour file. A frame without its end (a crash, a kill, or the session
    still writing) costs the block being written: the decoder yields one `{"truncated": True}` marker where
    the next session's frame begins (found by its magic and a valid header), and reads on. Input goes to
    zstd in small pieces on purpose: a decoder that raises discards the output of the call that raised."""

    def __init__(self):
        import zstandard

        self._dctx = zstandard.ZstdDecompressor()
        self._dobj = None
        self._rest = b""
        self._pending = b""
        self.open_frame = False
        self._resyncing = False
        self._only = None

    def _emit(self, out: bytes):
        self._rest += out
        *lines, self._rest = self._rest.split(b"\n")
        only = self._only
        for raw in lines:
            if raw.strip() and (only is None or any(k in raw for k in only)):
                yield json.loads(raw)

    def feed(self, chunk: bytes, final: bool = False, only=None) -> Iterator[dict]:
        """`only`: byte strings; a line is parsed only when it contains one of them (a cheap pre-filter)."""
        import zstandard

        self._only = only
        data = self._pending + chunk
        self._pending = b""
        while data:
            if self._dobj is None:
                self._dobj = self._dctx.decompressobj()
                self.open_frame = True
                cut_at = _next_frame(data, 1)  # this piece starts a frame; a second start inside it is a cut
            else:
                cut_at = _next_frame(data, 0)  # a frame start while one is open: the open one was cut
            if cut_at >= 0 and len(data) - cut_at < FRAME_HEADER_MAX and not final:
                self._pending = data[cut_at:]  # not enough bytes to judge the header yet
                data = data[:cut_at]
                if not data:
                    break
                cut_at = -1
            if cut_at >= 0:
                head, data = data[:cut_at], data[cut_at:]
                if head:
                    try:
                        yield from self._emit(self._dobj.decompress(head))
                    except zstandard.ZstdError:
                        pass
                if not self._dobj.eof:  # the open frame never got its end before the next began
                    yield {"truncated": True}
                    self._rest = b""
                self._dobj, self.open_frame = None, False
                continue
            try:
                out = self._dobj.decompress(data)
            except zstandard.ZstdError:
                if not self._resyncing:
                    yield {"truncated": True}
                self._resyncing = True
                self._rest = b""
                nxt = _next_frame(data, 1)
                self._dobj, self.open_frame = None, False
                if nxt < 0:
                    self._pending = b"" if final else data[-3:]
                    break
                data = data[nxt:]
                continue
            self._resyncing = False
            yield from self._emit(out)
            if self._dobj.eof:  # the frame ended: the next session's frame may follow
                data = self._dobj.unused_data
                self._dobj, self.open_frame = None, False
            else:
                data = b""

    def finish(self) -> Iterator[dict]:
        """At the end of the file: a frame still open is a cut (or still being written)."""
        if self.open_frame:
            yield {"truncated": True}
        elif self._rest.strip():
            try:
                yield json.loads(self._rest)
            except ValueError:
                yield {"truncated": True}


def read_lines(path: Path, piece: int = 1 << 12) -> Iterator[dict]:
    """Every decodable line of one hour file, in order (see `FrameDecoder` for what a cut frame costs)."""
    dec = FrameDecoder()
    with Path(path).open("rb") as fh:
        while True:
            chunk = fh.read(piece)
            if not chunk:
                break
            yield from dec.feed(chunk)
    yield from dec.finish()


def read_day(raw: Path, venue: str, day: str) -> Iterator[dict]:
    for path in sorted((Path(raw) / venue / day).glob("??" + SUFFIX)):
        yield from read_lines(path)


# ------------------------------------------------------------------ what gets recorded
def plan(
    coins: Dict[str, Dict[str, List[str]]] = COINS,
    hl_extra: Iterable[str] = (),
    testnet: Iterable[str] = (),
    coinbase: Iterable[str] = (),
) -> Dict[str, List[str]]:
    """Symbols per venue: aggr's coins on each venue that lists them; Hyperliquid also gets `hl_extra`;
    Coinbase spot gets BTC and ETH and the carry books' coins (their spot leg is priced there)."""
    bybit = [f"{c}USDT" for c, m in coins.items() if any(x.startswith("BYBIT:") for x in m["all"])]
    okx = [f"{c}-USDT-SWAP" for c, m in coins.items() if any(x.startswith("OKEX:") for x in m["all"])]
    binance = [f"{c}USDT" for c, m in coins.items() if any(x.startswith("BINANCE_FUTURES:") for x in m["all"])]
    hl = sorted({HL_NAME.get(c, c) for c in coins} | set(hl_extra))
    cb = sorted({f"{c}-USD" for c in ("BTC", "ETH")} | {f"{c}-USD" for c in coinbase})
    return {
        "bybit": bybit,
        "okx": okx,
        "hyperliquid": hl,
        "hyperliquid_testnet": sorted(set(testnet)),
        "binance": binance,
        "coinbase": cb,
    }


def hlbook_coins(project: Path = PROJECT) -> List[str]:
    """The ten coins `hlbook` froze, read from its coins.json; none if it hasn't run."""
    path = project / "data" / "hlbook" / "coins.json"
    if not path.is_file():
        return []
    try:
        return list(json.loads(path.read_text()).get("coins", []))
    except ValueError:
        return []


def book_coins(state: Path) -> Dict[str, List[str]]:
    """Coins the paper books hold now, read-only: {"carry": [...], "paper": [...]}. A missing or busy
    journal reads as empty; the recorder never waits on a book."""
    out: Dict[str, List[str]] = {"carry": [], "paper": []}
    state = Path(state)
    for db in sorted(state.glob("carry-*.db")):
        out["carry"] += _query(db, "SELECT DISTINCT coin FROM positions WHERE exit_ts IS NULL")
    for db in sorted(state.glob("paper-*.db")):
        out["paper"] += [p.split("-")[0] for p in _query(db, "SELECT DISTINCT product FROM bars")]
    return {k: sorted(set(v)) for k, v in out.items()}


def _query(db: Path, sql: str) -> List[str]:
    try:
        con = sqlite3.connect(f"file:{db}?mode=ro", uri=True, timeout=1.0)
        try:
            return [str(r[0]) for r in con.execute(sql)]
        finally:
            con.close()
    except sqlite3.Error:
        return []


def coins_file(raw: Path, base: Dict[str, List[str]], now: int) -> Dict[str, object]:
    """The frozen per-venue lists, written at the first start; later starts read them back."""
    path = Path(raw) / "coins.json"
    if path.exists():
        return json.loads(path.read_text())
    doc = {
        "chosen_ts": now,
        "rule": "aggr's 14 forward coins on every venue listing them; on Hyperliquid also "
        "hlbook's 10 and the paper books' holdings; added coins are appended, never removed",
        "venues": base,
        "added": {},
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(doc, indent=1))
    tmp.replace(path)
    return doc


def add_coins(raw: Path, doc: Dict[str, object], venue: str, coins: Iterable[str], now: int) -> List[str]:
    """Append coins to a venue's list (and the `added` record); returns the ones that were new."""
    have = set(doc["venues"].setdefault(venue, []))
    new = sorted(c for c in coins if c not in have)
    if new:
        doc["venues"][venue] += new
        for c in new:
            doc["added"][f"{venue}:{c}"] = now
        path = Path(raw) / "coins.json"
        tmp = path.with_name(path.name + ".tmp")
        tmp.write_text(json.dumps(doc, indent=1))
        tmp.replace(path)
    return new


# ------------------------------------------------------------------ reading the tape back
def gaps(
    raw: Path, venue: str, day: str, max_silence_s: float = 2 * HEARTBEAT_S, now_ms: Optional[int] = None
) -> List[Tuple[int, int]]:
    """Silences longer than `max_silence_s` in a venue's day, from every line's receive time: from
    00:00 to the first line, between lines, and from the last line to 24:00 (or to now, today)."""
    start = int(dt.datetime.strptime(day, "%Y-%m-%d").replace(tzinfo=dt.timezone.utc).timestamp() * 1000)
    end = start + 86_400_000
    now_ms = int(time.time() * 1000) if now_ms is None else now_ms
    end = min(end, now_ms)
    out, last = [], start
    limit = int(max_silence_s * 1000)
    for rec in read_day(raw, venue, day):
        rt = rec.get("rt")
        if rt is None:
            continue
        if rt - last > limit:
            out.append((last, rt))
        last = max(last, rt)
    if end - last > limit:
        out.append((last, end))
    return out


def status(raw: Path, venues: Iterable[str] = VENUES) -> Dict[str, Dict[str, dict]]:
    """Per venue and day: files, bytes and the last receive time, from the newest file's tail. Counts and
    clocks only; no price or size is read."""
    out: Dict[str, Dict[str, dict]] = {}
    for venue in venues:
        out[venue] = {}
        for folder in day_folders(raw, venue):
            files = sorted(folder.glob("??" + SUFFIX))
            last = None
            if files:
                for rec in read_lines(files[-1]):
                    if rec.get("rt"):
                        last = rec["rt"]
            out[venue][folder.name] = {
                "files": len(files),
                "bytes": sum(f.stat().st_size for f in files),
                "last_rt": last,
            }
    return out


def write_manifests(raw: Path, today: Optional[str] = None, venues: Iterable[str] = VENUES) -> List[Path]:
    """MANIFEST.sha256 into every day folder before `today` whose files are newer than its manifest."""
    today = today or dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%d")
    written = []
    for venue in venues:
        for folder in day_folders(raw, venue):
            if folder.name >= today:
                continue
            man = folder / manifest.NAME
            files = list(folder.glob("??" + SUFFIX))
            if not files:
                continue
            if man.exists() and man.stat().st_mtime >= max(f.stat().st_mtime for f in files):
                continue
            written.append(manifest.write(folder))
    return written


def free_gb(path: Path) -> float:
    return shutil.disk_usage(Path(path)).free / 1e9


# ------------------------------------------------------------------ the feeds
def _get(url: str, timeout: int = 20) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": "espero raw recorder"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()


def chunks(items: List[str], n: int) -> List[List[str]]:
    return [items[i : i + n] for i in range(0, len(items), n)]


def bybit_subscribe(symbols: List[str], books: bool = True) -> List[str]:
    topics = []
    for s in symbols:
        topics += [f"publicTrade.{s}", f"allLiquidation.{s}"] + ([f"orderbook.50.{s}"] if books else [])
    return [json.dumps({"op": "subscribe", "args": part}) for part in chunks(topics, 10)]


def okx_subscribe(symbols: List[str], books: bool = True) -> List[str]:
    args = [{"channel": "liquidation-orders", "instType": "SWAP"}]
    for s in symbols:
        args.append({"channel": "trades", "instId": s})
        if books:
            args.append({"channel": "books", "instId": s})
    return [json.dumps({"op": "subscribe", "args": part}) for part in chunks(args, 20)]


def hl_subscribe(coins: List[str], books: bool = True) -> List[str]:
    out = []
    for c in coins:
        out.append(json.dumps({"method": "subscribe", "subscription": {"type": "trades", "coin": c}}))
        if books:
            out.append(json.dumps({"method": "subscribe", "subscription": {"type": "l2Book", "coin": c}}))
    return out


def coinbase_subscribe(symbols: List[str], books: bool = True) -> List[str]:
    channels = ["matches", "heartbeat", "ticker"] + (["level2_batch"] if books else [])
    return [json.dumps({"type": "subscribe", "product_ids": list(symbols), "channels": channels})]


def binance_url(symbols: List[str], books: bool = True) -> str:
    skip = () if books else BOOK_CHANNELS["binance"] + ("bookTicker",)
    streams = [f"{s.lower()}@{st}" for s in symbols for st in BINANCE_STREAMS if st not in skip]
    return BINANCE_WS + "/".join(streams)


class Feed:
    """One venue's connection, written to one HourWriter. `connect` is websockets.connect unless a test
    injects something else; `clock` returns ms."""

    KEEPALIVE = {
        "bybit": (json.dumps({"op": "ping"}), 20),
        "okx": ("ping", 25),
        "hyperliquid": (json.dumps({"method": "ping"}), 50),
        "hyperliquid_testnet": (json.dumps({"method": "ping"}), 50),
        "binance": (None, 0),
        "coinbase": (None, 0),
    }
    URLS = {
        "bybit": BYBIT_WS,
        "okx": OKX_WS,
        "hyperliquid": HL_MAINNET_WS,
        "hyperliquid_testnet": HL_TESTNET_WS,
        "coinbase": COINBASE_WS,
    }

    def __init__(
        self,
        venue: str,
        symbols: List[str],
        writer: HourWriter,
        books: bool = True,
        connect=None,
        clock: Callable[[], int] = lambda: int(time.time() * 1000),
        books_on: Optional[Callable[[], bool]] = None,
    ):
        self.venue, self.symbols, self.writer, self.books = venue, list(symbols), writer, books
        self.connect, self.clock = connect, clock
        self.books_on = books_on or (lambda: True)  # the recorder's free-space flag, read per frame
        self.ws = None
        self.since_heartbeat = 0
        self.dropped = 0
        self.reconnects = 0

    def subscriptions(self, symbols: Optional[List[str]] = None) -> List[str]:
        symbols = self.symbols if symbols is None else symbols
        if self.venue == "binance":
            return []  # the streams are in the URL; a subscribe message is refused
        if self.venue == "bybit":
            return bybit_subscribe(symbols, self.books)
        if self.venue == "okx":
            return okx_subscribe(symbols, self.books)
        if self.venue == "coinbase":
            return coinbase_subscribe(symbols, self.books)
        return hl_subscribe(symbols, self.books)

    def url(self) -> str:
        return binance_url(self.symbols, self.books) if self.venue == "binance" else self.URLS[self.venue]

    def record(self, frame: bytes) -> None:
        ch, sym = classify(self.venue, frame)
        if not self.books_on() and ch in BOOK_CHANNELS.get(self.venue, ()) + ("bookTicker",):
            self.dropped += 1  # under the free-space floor: books are dropped, trades kept
            return
        self.writer.write(line(self.clock(), ch, sym, frame))
        self.since_heartbeat += 1

    def note(self, event: str, **fields) -> None:
        self.writer.write(meta(self.clock(), event, venue=self.venue, **fields))

    async def add(self, symbols: List[str]) -> None:
        """Subscribe to more symbols on the live connection (Binance would need a reconnect; not done)."""
        new = [s for s in symbols if s not in self.symbols]
        if not new:
            return
        self.symbols += new
        if self.ws is not None and self.venue != "binance":
            for msg in self.subscriptions(new):
                await self.ws.send(msg)
            self.note("subscribe", symbols=new)

    async def run(self) -> None:
        import websockets

        connect = self.connect or websockets.connect
        retry = 1.0
        while True:
            try:
                async with connect(self.url(), open_timeout=15, ping_interval=20, ping_timeout=20, max_size=None) as ws:
                    self.ws = ws
                    self.note(
                        "open" if not self.reconnects else "reconnect",
                        url=self.url(),
                        n=self.reconnects,
                        symbols=self.symbols,
                    )
                    retry = 1.0
                    for msg in self.subscriptions():
                        await ws.send(msg)
                    async for frame in ws:
                        self.record(frame if isinstance(frame, bytes) else frame.encode())
                self.ws = None
                self.reconnects += 1
                self.note("closed", retry_s=retry)
                await asyncio.sleep(retry)
                retry = min(retry * 2, 300.0)
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001 - the loop outlives any one failure
                self.ws = None
                self.reconnects += 1
                self.note("error", error=f"{type(exc).__name__}: {exc}"[:300], retry_s=retry)
                log.warning("%s: %s; retry in %.0fs", self.venue, exc, retry)
                await asyncio.sleep(retry)
                retry = min(retry * 2, 300.0)

    async def keepalive(self) -> None:
        payload, every = self.KEEPALIVE[self.venue]
        while payload:
            await asyncio.sleep(every)
            if self.ws is not None:
                try:
                    await self.ws.send(payload)
                except Exception:  # noqa: BLE001 - the run loop reports the connection
                    pass

    async def heartbeat(self) -> None:
        while True:
            await asyncio.sleep(HEARTBEAT_S)
            self.note(
                "heartbeat",
                frames=self.since_heartbeat,
                connected=self.ws is not None,
                lines=self.writer.lines,
                bytes=self.writer.bytes,
                dropped=self.dropped,
            )
            self.since_heartbeat = 0


async def bybit_snapshots(
    symbols: List[str], writer: HourWriter, connect=None, clock=None, timeout: float = 20.0
) -> int:
    """A second, short subscription: the first `orderbook.50` frame per symbol is a full book."""
    import websockets

    connect = connect or websockets.connect
    clock = clock or (lambda: int(time.time() * 1000))
    want = {f"orderbook.50.{s}" for s in symbols}
    got = 0
    async with connect(BYBIT_WS, open_timeout=15, max_size=None) as ws:
        writer.write(meta(clock(), "snapshot_request", venue="bybit", symbols=symbols))
        for msg in [json.dumps({"op": "subscribe", "args": part}) for part in chunks(sorted(want), 10)]:
            await ws.send(msg)
        deadline = time.monotonic() + timeout
        while want and time.monotonic() < deadline:
            try:
                frame = await asyncio.wait_for(ws.recv(), timeout=max(0.1, deadline - time.monotonic()))
            except asyncio.TimeoutError:
                break
            data = frame if isinstance(frame, bytes) else frame.encode()
            try:
                d = json.loads(data)
            except ValueError:
                continue
            if d.get("topic") in want and d.get("type") == "snapshot":
                writer.write(line(clock(), "orderbook.50", d["topic"].rpartition(".")[2], data))
                want.discard(d["topic"])
                got += 1
    return got


def hl_listed(testnet: bool, get=_get) -> Optional[List[str]]:
    """The perps a Hyperliquid network lists now; None when the question could not be asked. A
    subscription to a coin the network does not list makes it drop the whole socket."""
    url = ("https://api.hyperliquid-testnet.xyz" if testnet else "https://api.hyperliquid.xyz") + "/info"
    try:
        req = urllib.request.Request(
            url,
            data=b'{"type":"meta"}',
            method="POST",
            headers={"User-Agent": "espero raw recorder", "Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=20) as r:
            meta_ = json.loads(r.read())
        return [u["name"] for u in meta_.get("universe", []) if not u.get("isDelisted")]
    except Exception as exc:  # noqa: BLE001
        log.warning("hyperliquid %s meta: %s", "testnet" if testnet else "mainnet", exc)
        return None


def listed_only(venue: str, coins: List[str], listed: Optional[List[str]]) -> Tuple[List[str], List[str]]:
    """(kept, dropped) for a Hyperliquid venue; everything is kept when the listing is unknown."""
    if listed is None or not venue.startswith("hyperliquid"):
        return list(coins), []
    have = set(listed)
    return [c for c in coins if c in have], [c for c in coins if c not in have]


def okx_snapshot(symbol: str, get=_get) -> bytes:
    return get(f"{OKX_REST}/market/books?instId={symbol}&sz=400")


def okx_instruments(get=_get) -> dict:
    """Every USDT swap's contract value (`ctVal`) and tick, so a reader can turn contracts into coins."""
    d = json.loads(get(f"{OKX_REST}/public/instruments?instType=SWAP"))
    return {r["instId"]: {"ctVal": r["ctVal"], "tickSz": r["tickSz"], "lotSz": r["lotSz"]} for r in d.get("data", [])}


def binance_snapshot(symbol: str, get=_get) -> bytes:
    return get(f"{BINANCE_REST}/depth?symbol={symbol}&limit=1000")


def coinbase_snapshot(symbol: str, get=_get) -> bytes:
    return get(f"{COINBASE_REST}/products/{symbol}/book?level=2")


class Recorder:
    """The whole loop: five feeds, their snapshots, the watch on the paper books, the hourly manifests."""

    def __init__(
        self,
        raw: Path,
        state: Optional[Path] = None,
        connect=None,
        get=_get,
        clock: Callable[[], int] = lambda: int(time.time() * 1000),
        free: Callable[[Path], float] = free_gb,
    ):
        self.raw = Path(raw)
        self.state = Path(state) if state else PROJECT / "state"
        self.connect, self.get, self.clock, self.free = connect, get, clock, free
        self.writers = {v: HourWriter(self.raw, v) for v in VENUES}
        self.feeds: Dict[str, Feed] = {}
        self.books = True
        self.listed: Dict[str, Optional[List[str]]] = {}
        self._binance_rest_refused = -BINANCE_RETRY_S * 1000

    def lists(self) -> Dict[str, List[str]]:
        held = book_coins(self.state)
        base = plan(
            hl_extra=hlbook_coins() + held["carry"] + held["paper"], testnet=held["carry"], coinbase=held["carry"]
        )
        doc = coins_file(self.raw, base, self.clock() // 1000)
        self.doc = doc
        for venue in VENUES:
            if venue not in doc["venues"] and base.get(venue):  # a venue added after the file was frozen
                add_coins(self.raw, doc, venue, base[venue], self.clock() // 1000)
        return {v: list(doc["venues"].get(v, [])) for v in VENUES}

    async def watch(self) -> None:
        """Every WATCH_EVERY_S: a coin a paper book now holds joins the Hyperliquid feeds."""
        while True:
            await asyncio.sleep(WATCH_EVERY_S)
            held = book_coins(self.state)
            for venue, coins in (
                ("hyperliquid", held["carry"] + held["paper"]),
                ("hyperliquid_testnet", held["carry"]),
                ("coinbase", [f"{c}-USD" for c in held["carry"]]),
            ):
                new = add_coins(self.raw, self.doc, venue, coins, self.clock() // 1000)
                keep, _ = listed_only(venue, new, self.listed.get(venue))
                if keep and venue in self.feeds:
                    await self.feeds[venue].add(keep)

    async def snapshots(self) -> None:
        lists = self.lists
        while True:
            await asyncio.sleep(SNAPSHOT_EVERY_S)
            if not self.books:
                continue
            lst = lists()
            try:
                await bybit_snapshots(lst["bybit"], self.writers["bybit"], self.connect, self.clock)
            except Exception as exc:  # noqa: BLE001
                self.writers["bybit"].write(
                    meta(
                        self.clock(),
                        "error",
                        venue="bybit",
                        where="snapshot",
                        error=f"{type(exc).__name__}: {exc}"[:300],
                    )
                )
            for venue, fn in (("okx", okx_snapshot), ("binance", binance_snapshot), ("coinbase", coinbase_snapshot)):
                if venue == "binance" and self.clock() - self._binance_rest_refused < BINANCE_RETRY_S * 1000:
                    continue  # REST said 451 within the hour; the depth20 stream is the snapshot
                for s in lst[venue]:
                    try:
                        frame = await asyncio.to_thread(fn, s, self.get)
                        self.writers[venue].write(
                            line(
                                self.clock(),
                                "rest." + {"okx": "books", "binance": "depth", "coinbase": "book"}[venue],
                                s,
                                frame,
                            )
                        )
                    except Exception as exc:  # noqa: BLE001
                        self.writers[venue].write(
                            meta(
                                self.clock(),
                                "error",
                                venue=venue,
                                where="snapshot",
                                symbol=s,
                                error=f"{type(exc).__name__}: {exc}"[:300],
                            )
                        )
                        if venue == "binance":
                            self._binance_rest_refused = self.clock()
                            break  # one refusal says it for every symbol, for an hour
                    await asyncio.sleep(0.2)

    async def housekeeping(self) -> None:
        while True:
            for w in self.writers.values():
                w.flush()
            await asyncio.sleep(FLUSH_EVERY_S)

    async def hourly(self) -> None:
        while True:
            await asyncio.sleep(MANIFEST_EVERY_S)
            try:
                written = await asyncio.to_thread(write_manifests, self.raw)
                if written:
                    log.info("manifests: %s", ", ".join(str(p.parent.relative_to(self.raw)) for p in written))
            except Exception as exc:  # noqa: BLE001
                log.warning("manifest: %s", exc)
            free = self.free(self.raw)
            want_books = free > FREE_FLOOR_GB
            if want_books != self.books:
                self.books = want_books
                for w in self.writers.values():
                    w.write(meta(self.clock(), "books_on" if want_books else "books_off", free_gb=round(free, 1)))
                log.warning("free space %.1f GB: book channels %s", free, "on" if want_books else "off")

    async def run(self) -> None:
        from .lock import JournalLock

        with JournalLock(self.raw / "rawrec"):  # one writer per tape; the kernel frees it on any exit
            try:
                await self._run()
            finally:
                for w in self.writers.values():
                    w.close()  # every frame gets its end, whichever way the loop stopped

    async def _run(self) -> None:
        lists = self.lists()
        try:
            inst = await asyncio.to_thread(okx_instruments, self.get)
            (self.raw / "okx").mkdir(parents=True, exist_ok=True)
            (self.raw / "okx" / "instruments.json").write_text(json.dumps({"ts": self.clock(), "instruments": inst}))
        except Exception as exc:  # noqa: BLE001
            log.warning("okx instruments: %s", exc)
        self.books = self.free(self.raw) > FREE_FLOOR_GB
        self.listed: Dict[str, Optional[List[str]]] = {
            "hyperliquid": await asyncio.to_thread(hl_listed, False),
            "hyperliquid_testnet": await asyncio.to_thread(hl_listed, True),
        }
        tasks = []
        for venue in VENUES:
            coins, dropped = listed_only(venue, lists[venue], self.listed.get(venue))
            if dropped:
                self.writers[venue].write(meta(self.clock(), "unlisted", venue=venue, symbols=dropped))
            if not coins:
                continue
            feed = Feed(
                venue, coins, self.writers[venue], self.books, self.connect, self.clock, books_on=lambda: self.books
            )
            self.feeds[venue] = feed
            tasks += [
                asyncio.create_task(feed.run()),
                asyncio.create_task(feed.keepalive()),
                asyncio.create_task(feed.heartbeat()),
            ]
        tasks += [
            asyncio.create_task(self.snapshots()),
            asyncio.create_task(self.watch()),
            asyncio.create_task(self.housekeeping()),
            asyncio.create_task(self.hourly()),
        ]
        try:
            await asyncio.gather(*tasks)
        finally:
            for t in tasks:
                t.cancel()


def main_loop(raw: Path, state: Optional[Path] = None) -> int:
    """Run until SIGINT or SIGTERM (launchd's stop); either closes the hour files so their frames get an end."""
    import signal

    rec = Recorder(raw, state)

    async def run() -> None:
        loop = asyncio.get_running_loop()
        task = asyncio.ensure_future(rec.run())
        for sig in (signal.SIGINT, signal.SIGTERM):
            loop.add_signal_handler(sig, task.cancel)
        try:
            await task
        except asyncio.CancelledError:
            pass

    asyncio.run(run())
    return 0
