"""The second raw recorder: trade.xyz's books and trades, into a folder of its own, for #74.

It is `espero.rawrec`'s recorder with one feed: the same hour files, frames, lock, manifests and free-space rule,
so `rawrec.read_day`, `rawrec.gaps` and the replay tools read its tape unchanged (venue folder `hyperliquid`).
It never touches the first recorder's tape: its folder is named by `ESPERO_RAW_DIR_HIP3`, which must not be
`ESPERO_RAW_DIR`'s folder or under the repo's `data/`. Public websocket data only; nothing signs or trades.

    espero hip3rec --coins     # what it would record now, and what its folder already holds
    espero hip3rec --loop      # what launchd runs (scripts/install-rawrec-hip3-launchd.sh)

**Which markets.** At each start: every market in `research/hip3_map.csv` whose last 24 hours reach
`hip3.MIN_DAY_USD` and that the venue lists now. The list is kept in `<folder>/coins.json` and only grows: a
market that qualified once stays recorded while it is listed (research/PREREGISTRATION_HIP3COST.md). One request
to the venue per start; the books and trades arrive over the websocket, which the venue's request limit does not
count.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
from pathlib import Path
from typing import Callable, Dict, Iterable, List, Optional, Sequence

from . import hip3
from . import rawrec as rr

log = logging.getLogger(__name__)
ENV = "ESPERO_RAW_DIR_HIP3"
VENUE = "hyperliquid"
RULE = ("every market in research/hip3_map.csv with $5M or more traded in the last 24 hours at a start; "
        "appended, never removed")


def raw_dir(env: Optional[dict] = None, project: Path = rr.PROJECT) -> Path:
    """`ESPERO_RAW_DIR_HIP3`, resolved. Unset, under the repo's data/, or the first recorder's folder is refused."""
    env = os.environ if env is None else env
    path = rr.raw_dir({rr.ENV: env.get(ENV) or ""}, project) if env.get(ENV) else None
    if path is None:
        raise RuntimeError(f"{ENV} is not set: the trade.xyz recorder writes only to a folder named there")
    first = (env.get(rr.ENV) or "").strip()
    if first:
        other = Path(first).expanduser().resolve()
        if path == other or other in path.parents or path in other.parents:
            raise RuntimeError(f"{ENV}={path} and {rr.ENV}={other} overlap: each recorder has its own folder")
    return path


def qualifying(markets: Iterable[hip3.Market], mapped: Iterable[str], min_usd: float = hip3.MIN_DAY_USD) -> List[str]:
    """The coins to record: mapped markets with `min_usd` or more in the last 24 hours, by name."""
    names = set(mapped)
    return sorted(m.coin for m in markets if m.name in names and m.volume_usd >= min_usd)


def coins(raw: Path, markets: Optional[Sequence[hip3.Market]], mapped: Iterable[str], now_s: int) -> List[str]:
    """The folder's list after this start: what it held, plus what qualifies now; then only what is listed now.
    `markets` None (the venue did not answer): the held list, unfiltered."""
    path = Path(raw) / "coins.json"
    doc: Dict[str, object] = (json.loads(path.read_text()) if path.exists()
                              else {"chosen_ts": now_s, "rule": RULE, "venues": {VENUE: []}, "added": {}})
    if markets is None:
        return list(doc["venues"][VENUE])
    new = [c for c in qualifying(markets, mapped) if c not in set(doc["venues"][VENUE])]
    if new or not path.exists():
        doc["venues"][VENUE] += new
        for c in new:
            doc["added"][f"{VENUE}:{c}"] = now_s
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_name(path.name + ".tmp")
        tmp.write_text(json.dumps(doc, indent=1))
        tmp.replace(path)
    live = {m.coin for m in markets}
    return [c for c in doc["venues"][VENUE] if c in live]


class Hip3Recorder(rr.Recorder):
    """One feed, Hyperliquid mainnet, trade.xyz's coins; no snapshots and no watch on the paper books."""

    def __init__(self, raw: Path, markets: Optional[Callable[[], Sequence[hip3.Market]]] = None,
                 mapped: Optional[Iterable[str]] = None, **kw):
        super().__init__(raw, **kw)
        self.markets = markets or hip3.markets
        self.mapped = list(mapped) if mapped is not None else list(hip3.ticker_map())

    async def _run(self) -> None:
        try:
            now = await asyncio.to_thread(self.markets)
        except Exception as exc:  # noqa: BLE001 - the venue did not answer: record what the folder already lists
            log.warning("trade.xyz markets: %s", exc)
            now = None
        wanted = coins(self.raw, now, self.mapped, self.clock() // 1000)
        if not wanted:
            raise RuntimeError("no trade.xyz market to record: the venue did not answer and the folder lists none")
        self.books = self.free(self.raw) > rr.FREE_FLOOR_GB
        feed = rr.Feed(VENUE, wanted, self.writers[VENUE], self.books, self.connect, self.clock,
                       books_on=lambda: self.books)
        self.feeds[VENUE] = feed
        log.info("recording %d trade.xyz markets", len(wanted))
        tasks = [asyncio.create_task(t) for t in (feed.run(), feed.keepalive(), feed.heartbeat(),
                                                  self.housekeeping(), self.hourly())]
        try:
            await asyncio.gather(*tasks)
        finally:
            for t in tasks:
                t.cancel()


def main_loop(raw: Path) -> int:
    """Run until SIGINT or SIGTERM (launchd's stop); either closes the hour file so its frame gets an end."""
    import signal

    rec = Hip3Recorder(raw)

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


def main(argv=None) -> int:
    import argparse

    ap = argparse.ArgumentParser(prog="espero hip3rec")
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--loop", action="store_true")
    g.add_argument("--coins", action="store_true")
    a = ap.parse_args(argv)
    if a.coins:
        now = qualifying(hip3.markets(), hip3.ticker_map())
        print(f"{len(now)} markets qualify now: {' '.join(c.split(':', 1)[1] for c in now)}")
        if os.environ.get(ENV):
            path = raw_dir() / "coins.json"
            held = json.loads(path.read_text())["venues"][VENUE] if path.exists() else []
            print(f"{path.parent} lists {len(held)}" + (f"; new at the next start: "
                  f"{' '.join(c.split(':', 1)[1] for c in now if c not in set(held)) or 'none'}" if held else ""))
        return 0
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
    raw = raw_dir()
    print(f"recording trade.xyz into {raw}; ctrl-c stops", flush=True)
    return main_loop(raw)


if __name__ == "__main__":
    raise SystemExit(main())
