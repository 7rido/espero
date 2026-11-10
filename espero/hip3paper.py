"""Paper books for #75 and #76 on the live trade.xyz perps, at the account holder's request (2026-11-10).

Both rules **failed** their backtests (research/RESULTS_DEALRANGE.md, research/RESULTS_NIGHTSHIFT.md). These books
are for watching them live on the perps' own prices, information only: nothing here is a forward test, nothing is
judged from them, and nothing is ever sent to a venue.

* **#75 (dealing range):** the registered rule (`espero.dealrange`) on the perps' regular-session hourly bars,
  built from 30-minute candles so they start at 09:30 Eastern like the backtest's; the last bar of a session is
  half an hour, or the 12:30 bar on an early close.
* **#76 (night shift):** each trading day, bought at the perp's price at the session's close (16:00 Eastern, 13:00
  on an early close) and sold at its price at the next session's 09:30, both the open of the 30-minute candle
  starting then.

Costs and funding as registered: 14 bps a fill, funding at 10% a year for #76. The books start on `START`;
#75's swings need earlier bars, so its trades filled before `START` are tagged warm-up and left out of the
scorecard, as the screenshot the holder shared does.

    espero hip3paper --once     # fetch new candles (paced, about 10 minutes) and rewrite state/hip3paper.json
    espero hip3paper            # print the books from the last run
"""
from __future__ import annotations

import datetime as dt
import json
import time
from pathlib import Path
from typing import Callable, Dict, List, Optional, Sequence

import pandas as pd

from . import brackets as B
from . import dealrange as D
from . import levetf as lv
from . import nightshift as N

START = "2026-11-10"
WARMUP_DAYS = 12
CANDLE_S = 1800
PAUSE_S = 15.0
OUT = "hip3paper.json"
CACHE = "hip3paper"
BACKTEST = {
    "75": {"name": "Dealing range, proximal entry", "verdict": "FAIL", "trades": 1287, "mean": -0.583, "unit": "R",
           "pf": 0.44, "doc": "research/RESULTS_DEALRANGE.md"},
    "76": {"name": "Night shift, close to next open", "verdict": "FAIL", "trades": 1252, "mean": -20.93, "unit": "bps",
           "pf": 0.778, "doc": "research/RESULTS_NIGHTSHIFT.md"},
}


def bars(candles: Sequence[dict], first: str, now_s: int) -> pd.DataFrame:
    """The perp's regular-session hourly bars from 30-minute candles {t (ms), o, h, l, c}, every trading day from
    `first`, complete ones only (ended by `now_s`), in the columns espero.tradfi uses."""
    by_t = {int(x["t"]) // 1000: x for x in candles}
    rows = []
    d = dt.date.fromisoformat(first)
    end = dt.datetime.fromtimestamp(now_s, lv.ET).date()
    while d <= end:
        if lv.kind(d) != "closed":
            close = lv.session_close(d)
            start = lv.at(d, 9, 30)
            while start < close:
                stop = min(start + 3600, close)
                if stop > now_s:
                    break
                parts = [by_t[t] for t in range(start, stop, CANDLE_S) if t in by_t]
                if len(parts) == (stop - start) // CANDLE_S:
                    rows.append({"ts": start, "open": float(parts[0]["o"]), "high": max(float(p["h"]) for p in parts),
                                 "low": min(float(p["l"]) for p in parts), "close": float(parts[-1]["c"]),
                                 "volume": 0.0, "day": d.isoformat()})
                start = stop
        d += dt.timedelta(days=1)
    return pd.DataFrame(rows, columns=["ts", "open", "high", "low", "close", "volume", "day"])


def book75(df: pd.DataFrame, start: str = START) -> List[dict]:
    """#75's trades on one market's bars; `warmup` when filled before `start`, `open` while still held."""
    if df.empty:
        return []
    o, h, low, c = (df[k].to_numpy(dtype=float) for k in ("open", "high", "low", "close"))
    day = df["day"].tolist()
    _, trades = D.orders_and_trades(o, h, low, c, day)
    out = []
    for t in trades:
        out.append({"entry_day": day[t.entry_i], "entry_ts": int(df["ts"].iloc[t.entry_i]), "entry": t.entry,
                    "stop": t.entry - t.risk, "r": t.r, "outcome": t.outcome, "bars": t.exit_i - t.entry_i + 1,
                    "open": t.outcome == "end of data", "warmup": day[t.entry_i] < start,
                    "last": float(c[-1])})
    return out


def book76(candles: Sequence[dict], start: str, now_s: int, cost_bps: float = N.COST_BPS,
           funding_year: float = N.FUNDING_YEAR) -> List[dict]:
    """#76's nights from `start`: bought at the open of the candle starting at a session's close, sold at the open of
    the candle starting at the next session's 09:30; `open` when that candle has not come yet."""
    by_t = {int(x["t"]) // 1000: x for x in candles}
    out = []
    d = dt.date.fromisoformat(start)
    end = dt.datetime.fromtimestamp(now_s, lv.ET).date()
    while d <= end:
        if lv.kind(d) != "closed":
            buy_t = lv.session_close(d)
            nxt = d + dt.timedelta(days=1)
            while lv.kind(nxt) == "closed":
                nxt += dt.timedelta(days=1)
            sell_t = lv.at(nxt, 9, 30)
            if buy_t in by_t:
                buy = float(by_t[buy_t]["o"])
                if sell_t in by_t:
                    sell, held = float(by_t[sell_t]["o"]), True
                else:
                    last = max(t for t in by_t if t >= buy_t)
                    sell, held = float(by_t[last]["c"]), False
                hours = ((sell_t if held else now_s) - buy_t) / 3600
                gross = sell / buy - 1
                out.append({"day": d.isoformat(), "buy": buy, "sell": sell, "gross": gross, "hours": hours,
                            "net": gross - 2 * cost_bps / 1e4 - funding_year * hours / N.HOURS_YEAR, "open": not held})
        d += dt.timedelta(days=1)
    return out


def scorecard(values: Sequence[float]) -> Dict[str, Optional[float]]:
    s = B.summary(values)
    return {"n": s.n, "win_rate": s.win_rate, "mean": s.mean_r, "total": s.total_r, "pf": s.profit_factor}


def build(candles: Dict[str, Sequence[dict]], now_s: int, start: str = START) -> dict:
    """Both books and their scorecards from every market's 30-minute candles."""
    first = (dt.date.fromisoformat(start) - dt.timedelta(days=WARMUP_DAYS)).isoformat()
    t75, t76 = [], []
    for market, cs in candles.items():
        for t in book75(bars(cs, first, now_s), start):
            t75.append({"market": market, **t})
        for t in book76(cs, start, now_s):
            t76.append({"market": market, **t})
    t75.sort(key=lambda x: x["entry_ts"])
    t76.sort(key=lambda x: (x["day"], x["market"]))
    closed75 = [x["r"] for x in t75 if not x["open"] and not x["warmup"]]
    closed76 = [x["net"] * 1e4 for x in t76 if not x["open"]]
    return {"at": now_s, "start": start, "backtest": BACKTEST,
            "75": {"trades": t75, "score": scorecard(closed75)},
            "76": {"nights": t76, "score": scorecard(closed76)}}


# ------------------------------------------------------------------ fetching, paced: the recorders share the limit
def cached(folder: Path, market: str) -> List[dict]:
    try:
        return json.loads((folder / f"{market}.json").read_text())
    except (OSError, ValueError):
        return []


def refresh(folder: Path, markets: Sequence[str], now_s: int, post: Optional[Callable] = None,
            sleep: Callable[[float], None] = time.sleep, clock: Callable[[], float] = time.time,
            start: str = START) -> Dict[str, List[dict]]:
    """Each market's 30-minute candles from WARMUP_DAYS before `start`, asking only for what the cache lacks: one
    request a market, PAUSE_S apart, never in minutes 19 to 27 of the hour (the collector's sweep)."""
    from . import hyperliquid as hl

    post = post or (lambda body: hl.post(body, url=hl.MAINNET_URL + "/info"))
    folder.mkdir(parents=True, exist_ok=True)
    first_ms = int(dt.datetime.combine(dt.date.fromisoformat(start) - dt.timedelta(days=WARMUP_DAYS), dt.time(),
                                       tzinfo=dt.timezone.utc).timestamp() * 1000)
    out = {}
    for k, market in enumerate(markets):
        have = cached(folder, market)
        since = max([int(x["t"]) for x in have[:-1]], default=first_ms - CANDLE_S * 1000) + CANDLE_S * 1000
        while 19 <= time.gmtime(clock()).tm_min <= 27:
            sleep(20)
        try:
            new = post({"type": "candleSnapshot", "req": {"coin": f"xyz:{market}", "interval": "30m",
                                                          "startTime": since, "endTime": now_s * 1000}}) or []
        except Exception:  # noqa: BLE001 - a market that does not answer keeps what the cache holds
            new = []
        merged = {int(x["t"]): x for x in have}
        merged.update({int(x["t"]): x for x in new})
        rows = [merged[t] for t in sorted(merged) if t >= first_ms]
        tmp = folder / f"{market}.tmp"
        tmp.write_text(json.dumps(rows))
        tmp.replace(folder / f"{market}.json")
        out[market] = rows
        if k + 1 < len(markets):
            sleep(PAUSE_S)
    return out


def write(state: Path, book: dict) -> Path:
    path = Path(state) / OUT
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(book, indent=1, default=float))
    tmp.replace(path)
    return path


def read(state: Path) -> Optional[dict]:
    try:
        return json.loads((Path(state) / OUT).read_text())
    except (OSError, ValueError):
        return None


def render(book: Optional[dict]) -> str:
    if not book:
        return "no paper run yet: espero hip3paper --once"
    lines = [f"HIP-3 paper books since {book['start']}, last run "
             f"{dt.datetime.fromtimestamp(book['at'], lv.ET):%Y-%m-%d %H:%M} Eastern. Both failed their backtests; "
             "information only, nothing is sent."]
    for k, unit in (("75", "R"), ("76", "bps")):
        bt, s = book["backtest"][k], book[k]["score"]
        rows = book[k]["trades" if k == "75" else "nights"]
        live = [x for x in rows if x["open"] and not x.get("warmup")]
        lines.append(f"\n#{k} {bt['name']} (backtest {bt['verdict']}: {bt['trades']} trades, mean {bt['mean']:+g} "
                     f"{bt['unit']}, profit factor {bt['pf']})")
        mean = "-" if s["mean"] is None else f"{s['mean']:+.3f} {unit}"
        pf = "-" if s["pf"] is None else f"{s['pf']:.2f}"
        lines.append(f"  paper: {s['n']} closed, mean {mean}, profit factor {pf}; open now: {len(live)}")
        for x in live[:12]:
            if k == "75":
                lines.append(f"    {x['market']:8s} long from {x['entry']:.4g}, stop {x['stop']:.4g}, "
                             f"last {x['last']:.4g}")
            else:
                lines.append(f"    {x['market']:8s} bought {x['buy']:.4g} at the close of {x['day']}, "
                             f"now {x['sell']:.4g}")
    return "\n".join(lines)


def main(argv=None) -> int:
    import argparse

    from . import tradfi

    ap = argparse.ArgumentParser(prog="espero hip3paper")
    ap.add_argument("--once", action="store_true", help="fetch new candles and rewrite the books")
    ap.add_argument("--state-dir", default=str(Path(__file__).resolve().parents[1] / "state"))
    a = ap.parse_args(argv)
    state = Path(a.state_dir)
    if a.once:
        now_s = int(time.time())
        markets = [m for m, _ in tradfi.allowed()]
        candles = refresh(state / CACHE, markets, now_s)
        write(state, build(candles, now_s))
    print(render(read(state)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
