"""#64: taking the side of HLP's liquidator vaults when they are handed a position
(research/FORWARD_LIQVAULT.md).

The rule reads `data/hlcollect/`: HLP's accounts every 15 minutes, their read records, and Hyperliquid's
1-minute candles of every listed perp. A file's `ts` is when its read started, so a vault's inventory is
used only from `ts` + 120 s. There is no paper book. The verdict comes from `ledger`, rebuilt once after
the window has closed, and it refuses to read the recordings before then.
"""

from __future__ import annotations

import json
import math
import time
from collections import Counter
from pathlib import Path
from typing import Dict, Iterable, List, NamedTuple, Optional, Tuple

import pandas as pd

from . import hlpbook as hb
from . import hyperliquid as hl
from .audit import trade_weighted_nw
from .hlcollect import DATA, stamp

VAULTS = (
    "0x2e3d94f0562703b25c83308a05046ddaf9a8dd14",  # HLP Liquidator
    "0xb0a55f13d22f66e6d495ac98113841b2326e9540",  # HLP Liquidator 2
    "0x5e177e5e39c0f4e421f5865a6d8beed8d921cb70",  # HLP Liquidator 3
    "0x2ed5c4484ea3ff8b57d5f2fb152a40d9f2b68308",
)  # HLP Liquidator 4
WINDOW_START = hb._utc(2026, 11, 4)
WINDOW_END = hb.WINDOW_END  # exclusive: signals through 2027-03-31 23:59 UTC
SECOND_HALF = hb.SECOND_HALF
SLOT_S = 900
KNOWN_AFTER_S = 120
MIN_VALUE_USD = 50_000.0
MIN_TRADES = 30
PASS_T = 3.0
COST_BPS = hb.COST_BPS
LATER_FRACTION = 0.25
TIERS = ((50e6, "≥$50M"), (5e6, "$5M–$50M"), (0.0, "<$5M"))


class Slot(NamedTuple):
    slot: int  # the 15-minute slot, from the file's path
    ts: int  # when the read started: the rule's t
    positions: Dict[Tuple[str, str], Tuple[float, float]]  # (address, coin) -> (szi, value), vaults only
    clean: Optional[bool] = None  # True: no vault failed; False: one did; None: no record


class Signal(NamedTuple):
    coin: str
    ts: int  # A = ts + 120 s
    side: int  # +1 the vault is long, -1 short
    address: str
    value: float
    slot: int


# ----------------------------------------------------------------- the recordings
def slot_paths(data: Path = DATA) -> List[Path]:
    return sorted(Path(data).glob("hlp/*/*.csv.gz"))


def read_record(path: Path) -> Optional[bool]:
    """True if no liquidator address failed in the slot's read record, False if one did, None without a record."""
    record = path.parents[2] / "hlp_reads" / path.parent.name / (path.name.split(".")[0] + ".json")
    try:
        failed = {str(a).lower() for a in json.loads(record.read_text())["failed"]}
    except (OSError, ValueError, KeyError, TypeError):
        return None
    return not (failed & set(VAULTS))


def read_slot(path: Path) -> Slot:
    """One HLP file: the liquidator vaults' rows only, with the read record."""
    df = pd.read_csv(path, usecols=["ts", "address", "coin", "szi", "value"])
    slot, clean = hb.slot_of(path), read_record(path)
    if df.empty:
        return Slot(slot, slot, {}, clean)
    ours = df[df["address"].str.lower().isin(VAULTS)]
    positions = {(str(r.address).lower(), str(r.coin)): (float(r.szi), float(r.value)) for r in ours.itertuples()}
    return Slot(slot, int(df["ts"].iloc[0]), positions, clean)


def load_candles(path: Path, prices: hb.Prices, coins: Optional[Iterable[str]] = None) -> None:
    """A daily file's candles, for these coins or every coin (hlpbook's loader keeps #58's 14 coins only)."""
    df = pd.read_csv(path, usecols=["ts", "coin", "open", "close"])
    if coins is not None:
        df = df[df["coin"].isin(set(coins))]
    for coin, part in df.groupby("coin"):
        prices.add(coin, part)


def slots_not_asking_a_vault(data: Path = DATA) -> int:
    """Read records whose `accounts` lack one of the four addresses: a vault the collector stopped asking for
    (retired or replaced) gives no signal and never shows in `failed`; this count is the only trace of it."""
    n = 0
    for record in sorted(Path(data).glob("hlp_reads/*/*.json")):
        try:
            asked = {str(a).lower() for a in json.loads(record.read_text())["accounts"]}
        except (OSError, ValueError, KeyError, TypeError):
            continue
        if not set(VAULTS) <= asked:
            n += 1
    return n


def fetch_recent(
    prices: hb.Prices,
    coins: Iterable[str],
    now: int,
    fetch: Optional[hb.Fetch] = None,
    pace: float = 0.5,
    sleep=time.sleep,
) -> int:
    """Candles the daily files don't hold yet, for these coins, from the public API. Returns rows."""
    rows = 0
    for coin in sorted(set(coins)):
        since = max(prices.last_end(coin), WINDOW_START - 86400)
        got = hl.candles(coin, "1m", since * 1000, now * 1000, fetch=fetch)
        if not got.empty:
            got = got.assign(ts=[int(pd.Timestamp(x).timestamp()) for x in got["time"]])
            closed = got[got["ts"] + 60 <= now]
            prices.add(coin, closed)
            rows += len(closed)
        if pace:
            sleep(pace)
    return rows


def day_volume(data: Path, slot: int, coin: str) -> float:
    """The coin's `day_volume` from the ctx file of the same slot, or nan without one."""
    path = Path(data) / "ctx" / stamp(slot, "%Y-%m-%d") / f"{stamp(slot, '%H%M')}.csv.gz"
    try:
        df = pd.read_csv(path, usecols=["coin", "day_volume"])
    except (OSError, ValueError):
        return math.nan
    hit = df.loc[df["coin"] == coin, "day_volume"]
    return float(hit.iloc[0]) if len(hit) else math.nan


def tier_of(volume: float) -> str:
    if not volume == volume:
        return "unknown"
    return next(name for floor, name in TIERS if volume >= floor)


# ----------------------------------------------------------------- the rule
def new_positions(prev: Slot, cur: Slot) -> List[Signal]:
    """Rule 3: a vault's row in `cur` with szi ≠ 0 and value ≥ the floor, absent from `prev` or of the other sign."""
    out = []
    for (address, coin), (szi, value) in sorted(cur.positions.items()):
        if szi == 0 or not value >= MIN_VALUE_USD:
            continue
        before = prev.positions.get((address, coin))
        if before is None or before[0] == 0 or (before[0] > 0) != (szi > 0):
            out.append(Signal(coin, cur.ts + KNOWN_AFTER_S, 1 if szi > 0 else -1, address, value, cur.slot))
    return out


def later_entry(signal: Signal, by_slot: Dict[int, Slot]) -> Optional[Signal]:
    """The information-only entry: the first later slot at which the vault's |szi| is at or below a quarter of
    its first read, or the position is gone. None if the recordings end first or a slot is missing."""
    first = abs(by_slot[signal.slot].positions[(signal.address, signal.coin)][0])
    slot = signal.slot
    while True:
        slot += SLOT_S
        cur = by_slot.get(slot)
        if cur is None:
            return None
        size = abs(cur.positions.get((signal.address, signal.coin), (0.0, 0.0))[0])
        if size <= LATER_FRACTION * first:
            return Signal(signal.coin, cur.ts + KNOWN_AFTER_S, signal.side, signal.address, signal.value, slot)


def unwind_slots(signal: Signal, by_slot: Dict[int, Slot]) -> Optional[int]:
    """Slots from the first read until the position is gone; None if the recordings end or a slot is missing first."""
    slot, n = signal.slot, 0
    while True:
        slot += SLOT_S
        n += 1
        cur = by_slot.get(slot)
        if cur is None:
            return None
        if (signal.address, signal.coin) not in cur.positions or cur.positions[(signal.address, signal.coin)][0] == 0:
            return n


def walk(slots: List[Slot]) -> Dict:
    """Every signal in the window (rules 1–4), the information-only later entries, and the counts."""
    by_slot = {s.slot: s for s in slots}
    signals: List[Signal] = []
    counts: Counter = Counter()
    for cur in sorted(slots, key=lambda s: s.slot):
        known = cur.ts + KNOWN_AFTER_S
        if not WINDOW_START <= known < WINDOW_END:
            counts["outside_window"] += 1
            continue
        if any(szi != 0 for szi, _ in cur.positions.values()):
            counts["slots_with_a_vault_row"] += 1
        prev = by_slot.get(cur.slot - SLOT_S)
        if prev is None:
            counts["no_previous_slot"] += 1
            continue
        if prev.clean is not True or cur.clean is not True:
            counts["void"] += 1
            continue
        found = new_positions(prev, cur)
        counts["signals"] += len(found)
        signals.extend(found)
    later = [x for x in (later_entry(s, by_slot) for s in signals) if x is not None]
    unwind = {(s.coin, s.ts): unwind_slots(s, by_slot) for s in signals}
    return {"signals": signals, "later": later, "unwind": unwind, "counts": counts}


def trades(signals: List[Signal], prices: hb.Prices, final: bool = False) -> List[dict]:
    """Rules 5–7 through hlpbook's fills (#58's delay, tolerance, hold and one-at-a-time), with the side kept."""
    ordered = sorted(signals, key=lambda s: (s.ts, s.coin, s.address))
    rows = hb.trades([hb.Signal(s.coin, s.ts, s.value, 0.0) for s in ordered], prices, final)
    for r, s in zip(rows, ordered):
        r.update(side=s.side, address=s.address, value=s.value, slot=s.slot)
    return rows


def net_bps(side: int, entry_px: float, exit_px: float, funding: float) -> float:
    """side × gross − 18 − side × funding: a long pays a positive rate, a short receives it."""
    return side * 1e4 * (exit_px / entry_px - 1) - COST_BPS - side * funding


def closed_trades(rows: List[dict], fetch: Optional[hb.Fetch] = None) -> pd.DataFrame:
    out = []
    for r in rows:
        if r["status"] == "closed":
            funding = hb.funding_bps(r["coin"], r["entry_ts"], r["exit_ts"], fetch)
            out.append(
                {
                    **r,
                    "funding_bps": funding,
                    "gross_bps": r["side"] * 1e4 * (r["exit_px"] / r["entry_px"] - 1),
                    "net_bps": net_bps(r["side"], r["entry_px"], r["exit_px"], funding),
                }
            )
    return pd.DataFrame(out) if out else pd.DataFrame(columns=["coin", "entry_ts", "side", "net_bps"])


def evaluate(closed: pd.DataFrame) -> Dict:
    """The registered verdict, from closed trades with `coin`, `entry_ts` and `net_bps`."""
    n = len(closed)
    if n < MIN_TRADES:
        return {"verdict": "INCONCLUSIVE", "n": n, "mean": math.nan, "t": math.nan, "checks": {}}
    x = closed["net_bps"].astype(float)
    day = pd.to_datetime(closed["entry_ts"], unit="s").dt.normalize()
    head = trade_weighted_nw(x, day, lags=1)
    early = closed["entry_ts"] < SECOND_HALF
    coins = closed["coin"].unique()
    without = [float(x[closed["coin"] != c].mean()) if (closed["coin"] != c).any() else -math.inf for c in coins]
    checks = {
        "pays": bool(head["mean"] > 0 and head["t"] >= PASS_T),
        "both_halves": bool(early.any() and (~early).any() and x[early].mean() > 0 and x[~early].mean() > 0),
        "coins": bool(len(coins) > 1 and min(without) > 0),
        "median": bool(float(x.median()) > 0),
    }
    return {
        "verdict": "PASS" if all(checks.values()) else "FAIL",
        "n": n,
        "mean": head["mean"],
        "t": head["t"],
        "checks": checks,
    }


def information(closed: pd.DataFrame, later: pd.DataFrame, unwind: Dict, data: Path) -> Dict:
    """The information-only table: by side, vault and liquidity tier, gross and funding apart, the unwind."""
    out: Dict[str, object] = {
        "later_n": len(later),
        "later_mean": float(later["net_bps"].mean()) if len(later) else math.nan,
    }
    if len(closed):
        tiers = [tier_of(day_volume(data, int(r.slot), r.coin)) for r in closed.itertuples()]
        c = closed.assign(tier=tiers)
        out["by_side"] = {int(k): {"n": int(len(g)), "mean": float(g["net_bps"].mean())} for k, g in c.groupby("side")}
        out["by_vault"] = {
            k[:10]: {"n": int(len(g)), "mean": float(g["net_bps"].mean())} for k, g in c.groupby("address")
        }
        out["by_tier"] = {k: {"n": int(len(g)), "mean": float(g["net_bps"].mean())} for k, g in c.groupby("tier")}
        out["gross_mean"] = float(c["gross_bps"].mean())
        out["funding_mean"] = float(c["funding_bps"].mean())
        out["hit_rate"] = float((c["net_bps"] > 0).mean())
        out["value_median"] = float(c["value"].median())
    known = [v for v in unwind.values() if v is not None]
    out["unwind_slots_median"] = float(pd.Series(known).median()) if known else math.nan
    return out


def status(data: Path = DATA, now: Optional[int] = None) -> List[str]:
    """What is on disk for #64, by file name only: nothing opens a recorded file before the window closes."""
    now = int(time.time()) if now is None else now
    data = Path(data)
    opens, closes = pd.Timestamp(WINDOW_START, unit="s").date(), pd.Timestamp(WINDOW_END - 1, unit="s").date()
    where = "not open yet" if now < WINDOW_START else "open" if now < WINDOW_END else "closed"
    return [
        f"#64 liqvault: window {opens} to {closes}; {where}. No paper book; the verdict is computed once, "
        f"after {closes}, with `espero liqvault --verdict`",
        f"HLP slots on disk: {len(slot_paths(data))}",
        f"candle files on disk: {len(list(data.glob('candles/*.csv.gz')))}",
    ]


def ledger(data: Path = DATA, fetch: Optional[hb.Fetch] = None, now: Optional[int] = None) -> Dict:
    """The verdict's ledger. Before the window has closed it refuses and opens no recorded file."""
    now = int(time.time()) if now is None else now
    if now < WINDOW_END:
        raise RuntimeError("#64 is judged once, after 2027-03-31: its recordings are not read before then")
    data = Path(data)
    paths = slot_paths(data)
    found = walk([read_slot(p) for p in paths])
    prices = hb.Prices()
    wanted = {s.coin for s in found["signals"]}
    for path in sorted(data.glob("candles/*.csv.gz")):
        load_candles(path, prices, wanted)
    api_rows = fetch_recent(prices, [s.coin for s in found["signals"]], now, fetch, pace=0)
    rows = trades(found["signals"], prices, final=True)
    later_rows = trades(found["later"], prices, final=True)
    closed, later = closed_trades(rows, fetch), closed_trades(later_rows, fetch)
    info = information(closed, later, found["unwind"], data)
    info["slots_not_asking_a_vault"] = slots_not_asking_a_vault(data)
    return {
        "verdict": evaluate(closed),
        "information": info,
        "slots": len(paths),
        "candles_from_api": api_rows,
        "counts": dict(found["counts"]),
        "statuses": dict(Counter(r["status"] for r in rows)),
        "rows": rows,
        "later_rows": later_rows,
    }


if __name__ == "__main__":
    report = ledger()
    print(json.dumps({k: v for k, v in report.items() if k not in ("rows", "later_rows")}, indent=1, default=float))
