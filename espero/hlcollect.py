"""Hyperliquid collector: record what Hyperliquid shows only in the present.

Hyperliquid publishes every account's positions, with their liquidation prices, but
keeps no history of them, and 1-minute candles only for about three days. This loop
saves them for ideas 3, 4, 10 and 14 in research/IDEAS_NOVEL.md (the liquidation
ladder, HLP's inventory, the funding snipe, Hyperliquid against Binance). It only
reads public data; nothing here signs or trades.

    every 5 minutes   every perp's funding, premium, open interest, mark, oracle, mid, impact prices
    every 15 minutes  the positions of HLP's sub-accounts (the exchange's own vault)
    every hour        the positions of the top accounts by account value (the leaderboard)
    every day         yesterday's 1-minute candles for every listed perp; the leaderboard's ranking

Files go under data/hlcollect/ (not committed), each written whole and renamed into
place, so a crash never leaves half a file. A slot already on disk is not fetched
again, so a restart picks up where it stopped; slots missed while the Mac slept are
gone (Hyperliquid has no history to rebuild them from).

The pace keeps the loop near a third of the per-IP limit (1,200 weight a minute;
positions cost 2, the contexts and candle calls 20 and more), leaving room for the
carry loops, the scan and the fast screen on the same address.
"""
from __future__ import annotations

import datetime as dt
import gzip
import io
import json
import logging
import time
import urllib.request
from pathlib import Path
from typing import Callable, Dict, List, Optional

import pandas as pd

from . import hyperliquid as hl

log = logging.getLogger("espero.hlcollect")

DATA = Path(__file__).resolve().parents[1] / "data" / "hlcollect"
LEADERBOARD_URL = "https://stats-data.hyperliquid.xyz/Mainnet/leaderboard"
HLP = "0xdfc24b077bc1425ad1dea75bcb6f8158e10df303"
TOP = 2000
PACE_S = 0.3                    # between position calls: 200 a minute, 400 weight
CANDLE_PACE_S = 3.0             # candle calls cost 20 and more each
CTX_EVERY_S = 300
HLP_EVERY_S = 900
POSITIONS_EVERY_S = 3600
QUICK = ("ctx", "hlp")          # run in the loop itself; positions and candles get a thread
POSITION_COLS = ["ts", "address", "coin", "szi", "entry", "value", "liq", "lev", "lev_type", "margin",
                 "upnl", "account_value"]
CTX_COLS = ["ts", "coin", "funding", "premium", "open_interest", "mark", "oracle", "mid", "impact_bid",
            "impact_ask", "day_volume"]
CANDLE_COLS = ["ts", "coin", "open", "high", "low", "close", "volume", "trades"]

Fetch = Callable[[dict], object]


def _f(x) -> float:
    try:
        return float(x)
    except (TypeError, ValueError):
        return float("nan")


# ----------------------------------------------------------------- what is read
def leaderboard(get: Optional[Callable[[str], bytes]] = None) -> List[dict]:
    raw = (get or _get)(LEADERBOARD_URL)
    data = json.loads(raw)
    return data.get("leaderboardRows", data) if isinstance(data, dict) else data


def top_addresses(rows: List[dict], n: int = TOP) -> List[str]:
    """The n largest accounts by account value, largest first."""
    ranked = sorted(rows, key=lambda r: _f(r.get("accountValue")), reverse=True)
    return [r["ethAddress"].lower() for r in ranked[:n] if r.get("ethAddress")]


def hlp_accounts(fetch: Fetch) -> List[str]:
    """HLP's own address and its sub-accounts, where its positions sit."""
    vd = fetch({"type": "vaultDetails", "vaultAddress": HLP}) or {}
    rel = vd.get("relationship") or {}
    kids = (rel.get("data") or {}).get("childAddresses") or []
    return [HLP] + [k.lower() for k in kids]


def position_rows(address: str, state: dict, ts: int) -> List[dict]:
    """One row per open position of one account (`clearinghouseState`)."""
    value = _f((state.get("marginSummary") or {}).get("accountValue"))
    out = []
    for ap in state.get("assetPositions") or []:
        p = ap.get("position") or {}
        szi = _f(p.get("szi"))
        if not szi:
            continue
        lev = p.get("leverage") or {}
        out.append({"ts": ts, "address": address, "coin": p.get("coin"), "szi": szi, "entry": _f(p.get("entryPx")),
                    "value": _f(p.get("positionValue")), "liq": _f(p.get("liquidationPx")),
                    "lev": _f(lev.get("value")), "lev_type": lev.get("type", ""), "margin": _f(p.get("marginUsed")),
                    "upnl": _f(p.get("unrealizedPnl")), "account_value": value})
    return out


def positions(addresses: List[str], fetch: Fetch, ts: int, sleep=time.sleep, pace: float = PACE_S) -> Dict:
    """Every account's open positions; an account that fails is counted, named and skipped."""
    rows, failed, failed_accounts = [], 0, []
    for k, a in enumerate(addresses):
        try:
            rows.extend(position_rows(a, fetch({"type": "clearinghouseState", "user": a}) or {}, ts))
        except Exception as exc:  # noqa: BLE001 - one account must not stop the snapshot
            failed += 1
            failed_accounts.append(a)
            log.warning("positions %s: %s", a, exc)
        if pace and k < len(addresses) - 1:
            sleep(pace)
    return {"frame": pd.DataFrame(rows, columns=POSITION_COLS), "accounts": len(addresses), "failed": failed,
            "failed_accounts": failed_accounts}


def contexts(fetch: Fetch, ts: int) -> pd.DataFrame:
    """Every listed perp's state now (`metaAndAssetCtxs`)."""
    meta, ctxs = fetch({"type": "metaAndAssetCtxs"})
    rows = []
    for m, c in zip(meta["universe"], ctxs):
        if m.get("isDelisted"):
            continue
        imp = c.get("impactPxs") or [None, None]
        rows.append({"ts": ts, "coin": m["name"], "funding": _f(c.get("funding")), "premium": _f(c.get("premium")),
                     "open_interest": _f(c.get("openInterest")), "mark": _f(c.get("markPx")),
                     "oracle": _f(c.get("oraclePx")), "mid": _f(c.get("midPx")), "impact_bid": _f(imp[0]),
                     "impact_ask": _f(imp[1]), "day_volume": _f(c.get("dayNtlVlm"))})
    return pd.DataFrame(rows, columns=CTX_COLS)


def day_candles(coins: List[str], day: str, fetch: Fetch, sleep=time.sleep, pace: float = CANDLE_PACE_S) -> Dict:
    """One UTC day of 1-minute candles for every coin; a coin that fails is counted and skipped."""
    start = int(pd.Timestamp(day, tz="UTC").timestamp()) * 1000
    rows, failed = [], 0
    for k, c in enumerate(coins):
        try:
            page = fetch({"type": "candleSnapshot",
                          "req": {"coin": c, "interval": "1m", "startTime": start, "endTime": start + 86_400_000 - 1}})
            for r in page or []:
                t = int(r["t"]) // 1000
                if start // 1000 <= t < start // 1000 + 86400:
                    rows.append({"ts": t, "coin": c, "open": _f(r["o"]), "high": _f(r["h"]), "low": _f(r["l"]),
                                 "close": _f(r["c"]), "volume": _f(r["v"]), "trades": int(r.get("n") or 0)})
        except Exception as exc:  # noqa: BLE001
            failed += 1
            log.warning("candles %s %s: %s", c, day, exc)
        if pace and k < len(coins) - 1:
            sleep(pace)
    return {"frame": pd.DataFrame(rows, columns=CANDLE_COLS), "coins": len(coins), "failed": failed}


# ----------------------------------------------------------------- where it goes
def write(df: pd.DataFrame, path: Path) -> Path:
    """A gzip CSV written whole, then renamed into place."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    buf = io.StringIO()
    df.to_csv(buf, index=False, float_format="%.10g")
    tmp.write_bytes(gzip.compress(buf.getvalue().encode(), mtime=0))
    tmp.replace(path)
    return path


def write_reads(path: Path, ts: int, accounts: List[str], failed: List[str]) -> Path:
    """#59's record of one HLP slot: the accounts asked and those that failed. Written whole, then renamed."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps({"ts": ts, "accounts": accounts, "failed": failed}))
    tmp.replace(path)
    return path


def stamp(ts: int, fmt: str) -> str:
    return dt.datetime.fromtimestamp(ts, dt.timezone.utc).strftime(fmt)


class Collector:
    """Which slots are due, and the files that hold them. `fetch` posts to the info
    endpoint, `get` reads a URL; both are injected in tests."""

    def __init__(self, data: Path = DATA, fetch: Optional[Fetch] = None, get=None, top: int = TOP,
                 sleep=time.sleep, pace: float = PACE_S, candle_pace: float = CANDLE_PACE_S):
        self.data, self.top, self.sleep = Path(data), top, sleep
        self.fetch = fetch or hl.post
        self.get = get or _get
        self.pace, self.candle_pace = pace, candle_pace

    # file per slot
    def ctx_path(self, ts: int) -> Path:
        slot = ts - ts % CTX_EVERY_S
        return self.data / "ctx" / stamp(slot, "%Y-%m-%d") / f"{stamp(slot, '%H%M')}.csv.gz"

    def hlp_path(self, ts: int) -> Path:
        slot = ts - ts % HLP_EVERY_S
        return self.data / "hlp" / stamp(slot, "%Y-%m-%d") / f"{stamp(slot, '%H%M')}.csv.gz"

    def hlp_reads_path(self, ts: int) -> Path:
        slot = ts - ts % HLP_EVERY_S
        return self.data / "hlp_reads" / stamp(slot, "%Y-%m-%d") / f"{stamp(slot, '%H%M')}.json"

    def positions_path(self, ts: int) -> Path:
        slot = ts - ts % POSITIONS_EVERY_S
        return self.data / "positions" / stamp(slot, "%Y-%m-%d") / f"{stamp(slot, '%H')}00.csv.gz"

    def candles_path(self, day: str) -> Path:
        return self.data / "candles" / f"{day}.csv.gz"

    def addresses_path(self, ts: int) -> Path:
        return self.data / "addresses" / f"{stamp(ts, '%Y-%m-%d')}.json"

    # the jobs
    def addresses(self, ts: int) -> List[str]:
        """Today's top accounts: the leaderboard read once a day, its ranking kept."""
        path = self.addresses_path(ts)
        if path.exists():
            return json.loads(path.read_text())["addresses"]
        ranked = top_addresses(leaderboard(self.get), self.top)
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_name(path.name + ".tmp")
        tmp.write_text(json.dumps({"ts": ts, "top": self.top, "addresses": ranked}))
        tmp.replace(path)
        return ranked

    def due(self, now: int) -> List[str]:
        jobs = []
        if not self.ctx_path(now).exists():
            jobs.append("ctx")
        if not self.hlp_path(now).exists():
            jobs.append("hlp")
        if not self.positions_path(now).exists():
            jobs.append("positions")
        if self.missing_candle_days(now):
            jobs.append("candles")
        return jobs

    def missing_candle_days(self, now: int) -> List[str]:
        """The last two complete UTC days not on disk (Hyperliquid keeps about three of 1-minute bars)."""
        today = pd.Timestamp(stamp(now, "%Y-%m-%d"), tz="UTC")
        days = [(today - pd.Timedelta(days=k)).strftime("%Y-%m-%d") for k in (2, 1)]
        return [d for d in days if not self.candles_path(d).exists()]

    def run(self, job: str, now: int) -> str:
        if job == "ctx":
            df = contexts(self.fetch, now)
            write(df, self.ctx_path(now))
            return f"ctx: {len(df)} perps"
        if job == "hlp":
            accts = hlp_accounts(self.fetch)
            out = positions(accts, self.fetch, now, self.sleep, self.pace)
            try:
                write_reads(self.hlp_reads_path(now), now, accts, out["failed_accounts"])
            except OSError as exc:      # the positions are worth more than their record: #59 voids a slot without one
                log.error("hlp reads: %s", exc)
            write(out["frame"], self.hlp_path(now))
            return f"hlp: {len(out['frame'])} positions in {out['accounts']} accounts ({out['failed']} failed)"
        if job == "positions":
            out = positions(self.addresses(now), self.fetch, now, self.sleep, self.pace)
            if out["failed"] > out["accounts"] // 2:
                raise RuntimeError(f"positions: {out['failed']} of {out['accounts']} accounts failed; not saved")
            write(out["frame"], self.positions_path(now))
            return (f"positions: {len(out['frame'])} positions in {out['accounts']} accounts "
                    f"({out['failed']} failed)")
        if job == "candles":
            meta, _ = self.fetch({"type": "metaAndAssetCtxs"})
            coins = [m["name"] for m in meta["universe"] if not m.get("isDelisted")]
            notes = []
            for day in self.missing_candle_days(now):
                out = day_candles(coins, day, self.fetch, self.sleep, self.candle_pace)
                if out["failed"] > out["coins"] // 2:
                    raise RuntimeError(f"candles {day}: {out['failed']} of {out['coins']} coins failed; not saved")
                write(out["frame"], self.candles_path(day))
                notes.append(f"candles {day}: {len(out['frame'])} bars, {out['coins']} coins ({out['failed']} failed)")
            return "; ".join(notes)
        raise ValueError(f"unknown job {job!r}")

    def attempt(self, job: str, now: int) -> str:
        """Run one job; a failure is logged and the slot is tried again on the next tick."""
        try:
            return self.run(job, now)
        except Exception as exc:  # noqa: BLE001 - the loop must outlive a bad minute
            log.error("%s failed: %s", job, exc)
            return f"{job}: FAILED {type(exc).__name__}: {exc}"

    def step(self, now: Optional[int] = None) -> List[str]:
        """Run every job that is due now, one after the other (`--once`)."""
        now = int(time.time()) if now is None else now
        return [self.attempt(job, now) for job in self.due(now)]

    def loop(self, tick: float = 30.0, clock=time.time) -> None:
        """Forever. The 5- and 15-minute jobs run here; the hourly positions and the daily candles
        take many minutes, so they run in a thread of their own and never make the quick ones
        miss a slot."""
        import threading

        def say(note: str) -> None:
            print(f"{stamp(int(clock()), '%Y-%m-%d %H:%M:%S')} UTC  {note}", flush=True)

        slow: Optional[threading.Thread] = None
        while True:
            now = int(clock())
            jobs = self.due(now)
            for job in (j for j in jobs if j in QUICK):
                say(self.attempt(job, now))
            pending = [j for j in jobs if j not in QUICK]
            if pending and (slow is None or not slow.is_alive()):
                slow = threading.Thread(target=lambda js=pending, t=now: [say(self.attempt(j, t)) for j in js],
                                        daemon=True)
                slow.start()
            self.sleep(tick)


def _get(url: str) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": "espero"})
    with urllib.request.urlopen(req, timeout=120) as r:
        return r.read()


def status(data: Path = DATA, now: Optional[int] = None) -> Dict[str, object]:
    """What is on disk: files and the latest of each kind."""
    now = int(time.time()) if now is None else now
    out: Dict[str, object] = {}
    for kind in ("ctx", "hlp", "positions", "candles"):
        files = sorted((Path(data) / kind).rglob("*.csv.gz"))
        out[kind] = {"files": len(files), "latest": str(files[-1].relative_to(data)) if files else None,
                     "bytes": sum(f.stat().st_size for f in files)}
    return out
