"""Hyperliquid's order book, recorded: the top 20 levels a side, every 5 minutes, on 10 coins.

`espero hlcollect` keeps impact prices, a proxy for depth. Nothing else here keeps the book itself
over days. Hyperliquid's API serves only the current book, and its S3 archive is paid, uploaded about
monthly and may have gaps (research/HL_ARCHIVE.md), so this keeps our own same-day copy. It only reads
public data; nothing here signs or trades.

The coins are chosen once, the top 10 perps by 24-hour dollar volume at the first run, and kept in
`coins.json`: a study needs the same coins throughout, and a list chosen later would know the future.
Each slot is one file, written whole and renamed into place. `valid_ms` is the book's own clock, and
`ts` when it was read. A slot where most coins failed is not saved; a coin that fails alone is counted
in the log and is simply absent from that file. A gap stays a gap.
"""
from __future__ import annotations

import datetime as dt
import json
import logging
import time
from pathlib import Path
from typing import Callable, Dict, List, Optional

import pandas as pd

from . import hyperliquid as hl
from .hlcollect import _f, stamp, write

log = logging.getLogger("espero.hlbook")

DATA = Path(__file__).resolve().parents[1] / "data" / "hlbook"
COINS = 10
EVERY_S = 300
PACE_S = 0.5
COLS = ["ts", "valid_ms", "coin", "side", "level", "px", "sz", "n"]

Fetch = Callable[[dict], object]


def top_coins(fetch: Fetch, n: int = COINS) -> List[str]:
    """The listed perps with the most 24-hour dollar volume, largest first."""
    meta, ctxs = fetch({"type": "metaAndAssetCtxs"})
    rows = [(m["name"], _f(c.get("dayNtlVlm"))) for m, c in zip(meta["universe"], ctxs) if not m.get("isDelisted")]
    return [name for name, _ in sorted(rows, key=lambda r: (-r[1], r[0]))[:n]]


def book_rows(coin: str, book: dict, ts: int) -> List[dict]:
    """One row per level. `levels` holds bids then asks, best first."""
    out = []
    for side, levels in zip(("bid", "ask"), book["levels"]):
        for k, lv in enumerate(levels):
            out.append({"ts": ts, "valid_ms": int(book["time"]), "coin": coin, "side": side, "level": k,
                        "px": _f(lv["px"]), "sz": _f(lv["sz"]), "n": int(lv["n"])})
    return out


class Recorder:
    """Which slot is due, and the file that holds it. `fetch` posts to the info endpoint; injected in tests."""

    def __init__(self, data: Path = DATA, fetch: Optional[Fetch] = None, sleep=time.sleep, pace: float = PACE_S):
        self.data, self.sleep, self.pace = Path(data), sleep, pace
        self.fetch = fetch or hl.post

    def path(self, ts: int) -> Path:
        slot = ts - ts % EVERY_S
        return self.data / stamp(slot, "%Y-%m-%d") / f"{stamp(slot, '%H%M')}.csv.gz"

    def coins(self, now: int) -> List[str]:
        """The frozen list, chosen and written at the first run only."""
        path = self.data / "coins.json"
        if path.exists():
            return json.loads(path.read_text())["coins"]
        chosen = top_coins(self.fetch)
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_name(path.name + ".tmp")
        tmp.write_text(json.dumps({"chosen_ts": now, "rule": f"top {COINS} by 24h dollar volume", "coins": chosen}))
        tmp.replace(path)
        return chosen

    def record(self, now: int) -> str:
        coins = self.coins(now)
        rows: List[dict] = []
        failed = []
        for k, coin in enumerate(coins):
            try:
                rows.extend(book_rows(coin, self.fetch({"type": "l2Book", "coin": coin}), now))
            except Exception as exc:  # noqa: BLE001 - one coin must not stop the slot
                failed.append(coin)
                log.warning("book %s: %s", coin, exc)
            if self.pace and k < len(coins) - 1:
                self.sleep(self.pace)
        if len(failed) > len(coins) // 2:
            raise RuntimeError(f"{len(failed)} of {len(coins)} coins failed; slot not saved")
        write(pd.DataFrame(rows, columns=COLS), self.path(now))
        return f"book: {len(coins) - len(failed)} coins, {len(rows)} levels" + (f", failed {failed}" if failed else "")

    def step(self, now: Optional[int] = None) -> str:
        """Record the current slot if it is not on disk. A failure is logged and tried on the next tick."""
        now = int(time.time()) if now is None else now
        if self.path(now).exists():
            return "nothing due"
        try:
            return self.record(now)
        except Exception as exc:  # noqa: BLE001 - the loop must outlive a bad minute
            log.error("book failed: %s", exc)
            return f"book: FAILED {type(exc).__name__}: {exc}"

    def loop(self, tick: float = 15.0, clock=time.time) -> None:
        while True:
            now = int(clock())
            note = self.step(now)
            if note != "nothing due":
                print(f"{stamp(now, '%Y-%m-%d %H:%M:%S')} UTC  {note}", flush=True)
            self.sleep(tick)


def status(data: Path = DATA, now: Optional[int] = None) -> Dict[str, object]:
    """Counts only, never a value: slots on disk today and yesterday against what a full day holds."""
    now = int(time.time()) if now is None else now
    data = Path(data)
    files = sorted(p for p in data.glob("*/*.csv.gz"))
    today = dt.datetime.fromtimestamp(now, dt.timezone.utc)
    done_today = (now % 86400) // EVERY_S + 1
    days = {}
    for day, want in ((today, done_today), (today - dt.timedelta(days=1), 86400 // EVERY_S)):
        name = day.strftime("%Y-%m-%d")
        days[name] = {"slots": len(list((data / name).glob("*.csv.gz"))), "expected": want}
    return {"files": len(files), "bytes": sum(f.stat().st_size for f in files),
            "latest": str(files[-1].relative_to(data)) if files else None, "days": days}
