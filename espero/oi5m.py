"""#65: a sharp 5-minute fall read by its open interest, cascade or repricing (research/FORWARD_OI5M.md).

The rule reads `data/hlcollect/`: every perp's mark, open interest and day volume every 5 minutes, and
Hyperliquid's 1-minute candles for fills. A file's `ts` is when its read started, so a slot is used only
from `ts` + 120 s. There is no paper book. The verdict comes from `ledger`, rebuilt once after the window
has closed, and it refuses to read the recordings before then.
"""
from __future__ import annotations

import json
import math
import time
from collections import Counter, deque
from pathlib import Path
from typing import Deque, Dict, List, NamedTuple, Optional, Tuple

import numpy as np
import pandas as pd

from . import hlpbook as hb
from . import liqvault as lv
from .hlcollect import DATA

WINDOW_START = hb._utc(2026, 11, 3)
WINDOW_END = hb.WINDOW_END                       # exclusive: signals through 2027-03-31 23:59 UTC
SECOND_HALF = hb.SECOND_HALF
SLOT_S = 300
KNOWN_AFTER_S = 120
TAIL_PCT = 2.0
FLOOR = 0.01
HISTORY_S = 7 * 86400
MIN_HISTORY = 1008
MIN_VOLUME = 5e6
LIQUID = 50e6
HOLD_S = 3600
INFO_HOLDS = {"15m": 900, "4h": 14400}
MIN_TRADES = 100
PASS_T = 3.0
SIDE_T = 2.0
LAGS = 12
COST_BPS = hb.COST_BPS
MIN_COIN_TRADES = hb.MIN_COIN_TRADES


class Slot(NamedTuple):
    slot: int                                   # the 5-minute slot, from the file's path
    ts: int                                     # when the read started
    mark: Dict[str, float]
    oi: Dict[str, float]
    volume: Dict[str, float]


class Signal(NamedTuple):
    coin: str
    ts: int                                     # A = ts + 120 s
    side: int                                   # +1 reversal (long), -1 continuation (short)
    slot: int
    r: float
    d: float
    d1h: float
    volume: float
    kind: str                                   # "fall" (the rule) or "rise" (the information-only mirror)


# ----------------------------------------------------------------- the recordings
def slot_paths(data: Path = DATA) -> List[Path]:
    return sorted(Path(data).glob("ctx/*/*.csv.gz"))


def read_slot(path: Path) -> Optional[Slot]:
    df = pd.read_csv(path, usecols=["ts", "coin", "mark", "open_interest", "day_volume"])
    if df.empty:
        return None
    df = df[df["mark"] > 0].drop_duplicates("coin")
    return Slot(hb.slot_of(path), int(df["ts"].iloc[0]), dict(zip(df["coin"], df["mark"].astype(float))),
                dict(zip(df["coin"], df["open_interest"].astype(float))),
                dict(zip(df["coin"], df["day_volume"].astype(float))))


# ----------------------------------------------------------------- the rule
def walk(slots: List[Slot]) -> Dict:
    """Rules 1–4 on every slot: the signals (liquid falls), the thin falls and the mirror on rises, all
    with the trailing-7-day tail per coin computed from the slots before, never including the slot."""
    by_slot = {s.slot: s for s in slots}
    history: Dict[str, Deque[Tuple[int, float]]] = {}
    signals: List[Signal] = []
    thin: List[Signal] = []
    mirror: List[Signal] = []
    counts: Counter = Counter()
    for cur in sorted(slots, key=lambda s: s.slot):
        prev = by_slot.get(cur.slot - SLOT_S)
        hour = by_slot.get(cur.slot - 12 * SLOT_S)
        known = cur.ts + KNOWN_AFTER_S
        inside = WINDOW_START <= known < WINDOW_END
        if prev is None:
            counts["no_previous_slot"] += 1
            continue
        for coin, mark in cur.mark.items():
            before = prev.mark.get(coin)
            if not before:
                continue
            r = mark / before - 1
            oi_now, oi_before = cur.oi.get(coin, math.nan), prev.oi.get(coin, math.nan)
            d = oi_now / oi_before - 1 if oi_before and oi_before == oi_before else math.nan
            past = history.setdefault(coin, deque())
            while past and past[0][0] < cur.slot - HISTORY_S:
                past.popleft()
            if inside and d == d and abs(d) >= FLOOR:
                if len(past) < MIN_HISTORY:
                    counts["short_history"] += 1
                else:
                    values = np.fromiter((v for _, v in past), dtype=float, count=len(past))
                    lo, hi = np.percentile(values, [TAIL_PCT, 100 - TAIL_PCT])
                    oi_hour = hour.oi.get(coin) if hour is not None else None
                    d1h = oi_now / oi_hour - 1 if oi_hour else math.nan
                    volume = cur.volume.get(coin, math.nan)
                    side = 1 if d <= -FLOOR else -1
                    if r <= lo:
                        s = Signal(coin, known, side, cur.slot, r, d, d1h, volume, "fall")
                        if volume >= MIN_VOLUME:
                            signals.append(s)
                            counts["signals"] += 1
                        else:
                            thin.append(s)
                            counts["thin"] += 1
                    elif r >= hi and volume >= MIN_VOLUME:
                        mirror.append(Signal(coin, known, -side, cur.slot, r, d, d1h, volume, "rise"))
                        counts["mirror"] += 1
            past.append((cur.slot, r))
    return {"signals": signals, "thin": thin, "mirror": mirror, "counts": counts}


def trades(signals: List[Signal], prices: hb.Prices, hold_s: int = HOLD_S, final: bool = False) -> List[dict]:
    """Rules 5–7: #58's delay and tolerance, this test's hold, one at a time per coin, the side kept."""
    out, held_until = [], {}
    for s in sorted(signals, key=lambda x: (x.ts, x.coin)):
        t = {"coin": s.coin, "signal_ts": s.ts, "side": s.side, "slot": s.slot, "r": s.r, "d": s.d, "d1h": s.d1h,
             "volume": s.volume, "entry_ts": None, "entry_px": None, "exit_ts": None, "exit_px": None}
        if s.ts < held_until.get(s.coin, 0):
            out.append({**t, "status": "ignored"})
            continue
        entry = prices.first_open(s.coin, s.ts + hb.ENTRY_DELAY_S, final)
        if entry == hb.PENDING:
            held_until[s.coin] = math.inf
            out.append({**t, "status": "pending"})
            continue
        if entry == hb.MISSING or entry[0] - s.ts > hb.FILL_TOLERANCE_S:
            out.append({**t, "status": "dropped_entry"})
            continue
        t.update(entry_ts=entry[0], entry_px=entry[1])
        due = entry[0] + hold_s
        leave = prices.first_open(s.coin, due, final)
        if leave == hb.PENDING:
            held_until[s.coin] = math.inf
            out.append({**t, "status": "open"})
        elif leave == hb.MISSING:
            held_until[s.coin] = due
            out.append({**t, "status": "dropped_exit"})
        elif leave[0] >= WINDOW_END:
            held_until[s.coin] = leave[0]
            out.append({**t, "status": "dropped_after_window"})
        else:
            held_until[s.coin] = leave[0]
            out.append({**t, "exit_ts": leave[0], "exit_px": leave[1], "status": "closed"})
    return out


net_bps = lv.net_bps


def closed_trades(rows: List[dict], fetch: Optional[hb.Fetch] = None) -> pd.DataFrame:
    out = []
    for r in rows:
        if r["status"] == "closed":
            funding = hb.funding_bps(r["coin"], r["entry_ts"], r["exit_ts"], fetch)
            out.append({**r, "funding_bps": funding, "gross_bps": r["side"] * 1e4 * (r["exit_px"] / r["entry_px"] - 1),
                        "net_bps": net_bps(r["side"], r["entry_px"], r["exit_px"], funding)})
    return pd.DataFrame(out) if out else pd.DataFrame(columns=["coin", "entry_ts", "side", "slot", "volume", "net_bps"])


def cluster_t(x: pd.Series, slot: pd.Series, lags: int = LAGS) -> Dict[str, float]:
    """Mean with a t whose variance sums the residuals within each 5-minute slot and lets neighbouring
    slots' sums correlate over `lags` slots (Bartlett weights)."""
    n = int(x.size)
    if n < 2:
        return {"mean": float(x.mean()) if n else math.nan, "t": math.nan, "slots": n}
    m = float(x.mean())
    s = (x - m).groupby(slot.values).sum().sort_index()
    grid = pd.RangeIndex(int(s.index.min()), int(s.index.max()) + SLOT_S, SLOT_S)
    v = s.reindex(grid, fill_value=0.0).to_numpy()
    var = float(v @ v)
    for k in range(1, lags + 1):
        if k < v.size:
            var += 2.0 * (1 - k / (lags + 1)) * float(v[k:] @ v[:-k])
    se = math.sqrt(max(var, 0.0)) / n
    return {"mean": m, "t": m / se if se > 1e-9 else math.nan, "slots": int(s.size)}


def evaluate(closed: pd.DataFrame) -> Dict:
    """The registered verdict, from closed trades with coin, entry_ts, side, slot, volume and net_bps."""
    n_long = int((closed["side"] == 1).sum()) if len(closed) else 0
    n_short = int((closed["side"] == -1).sum()) if len(closed) else 0
    if min(n_long, n_short) < MIN_TRADES:
        return {"verdict": "INCONCLUSIVE", "n": len(closed), "n_reversal": n_long, "n_continuation": n_short,
                "mean": math.nan, "t": math.nan, "checks": {}}
    x = closed["net_bps"].astype(float)
    head = cluster_t(x, closed["slot"])
    sides = {name: cluster_t(x[closed["side"] == side], closed.loc[closed["side"] == side, "slot"])
             for name, side in (("reversal", 1), ("continuation", -1))}
    early = closed["entry_ts"] < SECOND_HALF
    enough = closed.groupby("coin")["coin"].transform("size") >= MIN_COIN_TRADES
    by_coin = closed[enough].groupby("coin")["net_bps"].mean()
    liquid = closed["volume"] >= LIQUID
    checks = {
        "pays": bool(head["mean"] > 0 and head["t"] >= PASS_T),
        "reversal": bool(sides["reversal"]["mean"] > 0 and sides["reversal"]["t"] >= SIDE_T),
        "continuation": bool(sides["continuation"]["mean"] > 0 and sides["continuation"]["t"] >= SIDE_T),
        "both_halves": bool(early.any() and (~early).any() and x[early].mean() > 0 and x[~early].mean() > 0),
        "coins": bool(by_coin.size and (by_coin > 0).sum() > by_coin.size / 2),
        "liquid": bool(liquid.any() and x[liquid].mean() > 0),
    }
    others = all(checks[k] for k in ("pays", "both_halves", "coins", "liquid"))
    if all(checks.values()):
        verdict = "PASS"
    elif others and checks["reversal"] != checks["continuation"]:
        verdict = f"FAIL (one side only: {'reversal' if checks['reversal'] else 'continuation'} pays)"
    else:
        verdict = "FAIL"
    return {"verdict": verdict, "n": len(closed), "n_reversal": n_long, "n_continuation": n_short,
            "mean": head["mean"], "t": head["t"], "sides": sides, "checks": checks}


def summary(closed: pd.DataFrame) -> Dict[str, object]:
    if not len(closed):
        return {"n": 0}
    return {"n": int(len(closed)), "mean": float(closed["net_bps"].mean()), "gross": float(closed["gross_bps"].mean()),
            "funding": float(closed["funding_bps"].mean()), "hit": float((closed["net_bps"] > 0).mean())}


def information(closed: pd.DataFrame, extra: Dict[str, pd.DataFrame]) -> Dict[str, object]:
    out: Dict[str, object] = {name: summary(df) for name, df in extra.items()}
    if len(closed):
        out["by_side"] = {int(k): summary(g) for k, g in closed.groupby("side")}
        out["by_tier"] = {lv.tier_of(v): summary(g) for v, g in closed.groupby(closed["volume"].map(
            lambda v: 50e6 if v >= LIQUID else 5e6))}
        c = closed[np.isfinite(closed["d1h"])]
        if len(c):
            med = c.groupby("coin")["d1h"].transform("median")
            out["hour_before"] = {"crowded": summary(c[c["d1h"] > med]), "thinning": summary(c[c["d1h"] <= med])}
    return out


def status(data: Path = DATA, now: Optional[int] = None) -> List[str]:
    """What is on disk for #65, by file name only: nothing opens a recorded file before the window closes."""
    now = int(time.time()) if now is None else now
    data = Path(data)
    opens, closes = pd.Timestamp(WINDOW_START, unit="s").date(), pd.Timestamp(WINDOW_END - 1, unit="s").date()
    where = "not open yet" if now < WINDOW_START else "open" if now < WINDOW_END else "closed"
    return [f"#65 oi5m: window {opens} to {closes}; {where}. No paper book; the verdict is computed once, "
            f"after {closes}, with `espero oi5m --verdict`",
            f"context slots on disk: {len(slot_paths(data))}",
            f"candle files on disk: {len(list(data.glob('candles/*.csv.gz')))}"]


def ledger(data: Path = DATA, fetch: Optional[hb.Fetch] = None, now: Optional[int] = None) -> Dict:
    """The verdict's ledger. Before the window has closed it refuses and opens no recorded file."""
    now = int(time.time()) if now is None else now
    if now < WINDOW_END:
        raise RuntimeError("#65 is judged once, after 2027-03-31: its recordings are not read before then")
    data = Path(data)
    paths = slot_paths(data)
    slots = [s for s in (read_slot(p) for p in paths) if s is not None]
    found = walk(slots)
    everything = found["signals"] + found["thin"] + found["mirror"]
    prices = hb.Prices()
    wanted = {s.coin for s in everything}
    for path in sorted(data.glob("candles/*.csv.gz")):
        lv.load_candles(path, prices, wanted)
    api_rows = lv.fetch_recent(prices, wanted, now, fetch, pace=0)
    rows = trades(found["signals"], prices, HOLD_S, final=True)
    closed = closed_trades(rows, fetch)
    extra = {f"hold_{name}": closed_trades(trades(found["signals"], prices, hold, final=True), fetch)
             for name, hold in INFO_HOLDS.items()}
    extra["thin"] = closed_trades(trades(found["thin"], prices, HOLD_S, final=True), fetch)
    extra["mirror"] = closed_trades(trades(found["mirror"], prices, HOLD_S, final=True), fetch)
    return {"verdict": evaluate(closed), "information": information(closed, extra), "slots": len(paths),
            "empty_slots": len(paths) - len(slots), "candles_from_api": api_rows, "counts": dict(found["counts"]),
            "statuses": dict(Counter(r["status"] for r in rows)), "rows": rows}


if __name__ == "__main__":
    report = ledger()
    print(json.dumps({k: v for k, v in report.items() if k != "rows"}, indent=1, default=float))
