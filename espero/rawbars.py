"""#61: aggr's forward bars rebuilt from the raw streams (research/PREREGISTRATION_RAWBARS.md).

The rebuild and the comparison, pure: events in, bars and a match table out, no I/O. research/rawbars.py
reads the tape and the forward files and prints. The arithmetic is aggr-server's own (`src/storage/influx.js`,
read 2026-11-02): a trade goes to the bar of its exchange timestamp, prices come from trades only, volumes
are dollars by taker side, counts are trades by taker side, liquidations are dollars by order side.
"""
from __future__ import annotations

import json
from typing import Dict, Iterable, Iterator, List, Optional, Tuple

import numpy as np
import pandas as pd

from .aggr import COLUMNS

EVENT_COLS = ["ts", "market", "price", "size", "side", "liquidation", "count"]
HOUR_MS, FIVE_MS = 3_600_000, 300_000
# the registered tolerance, per field (research/PREREGISTRATION_RAWBARS.md)
PRICE_BPS = 5.0
VOLUME_PCT, VOLUME_USD = 0.02, 2_000.0
COUNT_PCT, COUNT_N = 0.02, 20
LIQ_PCT, LIQ_USD = 0.05, 500.0
DAY_MATCH = 0.95
DAYS_MATCH = 0.95
MARKET = {"binance": "BINANCE_FUTURES:{s}", "bybit": "BYBIT:{S}", "okx": "OKEX:{S}"}


# ------------------------------------------------------------------ frames -> events
def events_from_frames(venue: str, frames: Iterable[dict], ct_val: Optional[Dict[str, float]] = None) -> pd.DataFrame:
    """Trades and liquidations from a venue's recorded frames (`rawrec.read_day` records), one row each,
    in aggr's terms: `side` is the taker side for a trade and the order side for a liquidation."""
    rows: List[tuple] = []
    ct_val = ct_val or {}
    for rec in frames:
        ch, d = rec.get("ch"), rec.get("d")
        if not isinstance(d, dict):
            continue
        if venue == "bybit":
            if ch == "publicTrade":
                for t in d.get("data", []):
                    rows.append((int(t["T"]), MARKET["bybit"].format(S=t["s"]), float(t["p"]), float(t["v"]),
                                 "buy" if t["S"] == "Buy" else "sell", False, 1))
            elif ch == "allLiquidation":
                for t in d.get("data", []):      # S is the liquidated position's side: a long liquidated sells
                    rows.append((int(t["T"]), MARKET["bybit"].format(S=t["s"]), float(t["p"]), float(t["v"]),
                                 "sell" if t["S"] == "Buy" else "buy", True, 1))
        elif venue == "okx":
            if ch == "trades":
                for t in d.get("data", []):
                    k = ct_val.get(t["instId"], 1.0)
                    rows.append((int(t["ts"]), MARKET["okx"].format(S=t["instId"]), float(t["px"]),
                                 float(t["sz"]) * k, t["side"], False, 1))
            elif ch == "liquidation-orders":
                for inst in d.get("data", []):
                    k = ct_val.get(inst.get("instId", ""), None)
                    if k is None:
                        continue              # an instrument we hold no contract value for: not ours
                    for t in inst.get("details", []):
                        rows.append((int(t["ts"]), MARKET["okx"].format(S=inst["instId"]), float(t["bkPx"]),
                                     float(t["sz"]) * k, t["side"], True, 1))
        elif venue == "binance":
            data = d.get("data", {})
            if ch == "trade":                   # the raw print stream, aggr's own source: one trade each
                rows.append((int(data["T"]), MARKET["binance"].format(s=data["s"].lower()), float(data["p"]),
                             float(data["q"]), "sell" if data["m"] else "buy", False, 1))
            elif ch == "aggTrade":
                rows.append((int(data["T"]), MARKET["binance"].format(s=data["s"].lower()), float(data["p"]),
                             float(data["q"]), "sell" if data["m"] else "buy", False,
                             int(data["l"]) - int(data["f"]) + 1))
            elif ch == "forceOrder":
                o = data.get("o", {})
                rows.append((int(o["T"]), MARKET["binance"].format(s=o["s"].lower()), float(o["p"]), float(o["q"]),
                             "buy" if o["S"] == "BUY" else "sell", True, 1))
    return pd.DataFrame(rows, columns=EVENT_COLS)


def events_from_archive(symbol: str, agg: pd.DataFrame) -> pd.DataFrame:
    """Binance's archived `aggTrades` (columns agg_trade_id, price, quantity, first_trade_id, last_trade_id,
    transact_time, is_buyer_maker) as events; no liquidations exist there."""
    df = pd.DataFrame({"ts": agg["transact_time"].astype("int64"), "market": MARKET["binance"].format(s=symbol.lower()),
                       "price": agg["price"].astype(float), "size": agg["quantity"].astype(float),
                       "side": np.where(agg["is_buyer_maker"].astype(str).str.lower().isin(["true", "1"]), "sell", "buy"),
                       "liquidation": False,
                       "count": agg["last_trade_id"].astype("int64") - agg["first_trade_id"].astype("int64") + 1})
    return df[EVENT_COLS]


# ------------------------------------------------------------------ events -> bars
def build_bars(events: pd.DataFrame, bar_ms: int = HOUR_MS) -> pd.DataFrame:
    """aggr's bar per market and bar start (seconds, as aggr's files have it), from events."""
    if events.empty:
        return pd.DataFrame(columns=COLUMNS)
    e = events.copy()
    e["time"] = (e["ts"] // bar_ms) * bar_ms // 1000
    e["usd"] = e["price"] * e["size"]
    tr = e[~e["liquidation"]].sort_values(["ts"], kind="stable")
    out = []
    g = tr.groupby(["time", "market"], sort=True)
    prices = g["price"].agg(["first", "max", "min", "last"]) if len(tr) else pd.DataFrame()
    for (time, market), part in g:
        buy, sell = part["side"] == "buy", part["side"] == "sell"
        out.append({"time": int(time), "market": market,
                    "open": prices.at[(time, market), "first"], "high": prices.at[(time, market), "max"],
                    "low": prices.at[(time, market), "min"], "close": prices.at[(time, market), "last"],
                    "vbuy": float(part.loc[buy, "usd"].sum()), "vsell": float(part.loc[sell, "usd"].sum()),
                    "cbuy": int(part.loc[buy, "count"].sum()), "csell": int(part.loc[sell, "count"].sum()),
                    "lbuy": 0.0, "lsell": 0.0})
    bars = pd.DataFrame(out, columns=COLUMNS)
    liq = e[e["liquidation"]]
    if len(liq):
        ls = liq.groupby(["time", "market", "side"])["usd"].sum()
        bars = bars.set_index(["time", "market"])
        for (time, market, side), usd in ls.items():
            if (time, market) not in bars.index:
                bars.loc[(time, market), :] = [np.nan] * 4 + [0.0, 0.0, 0, 0, 0.0, 0.0]
            bars.at[(time, market), "l" + side] = float(usd)
        bars = bars.reset_index()[COLUMNS]
    return bars.sort_values(["market", "time"]).reset_index(drop=True)


# ------------------------------------------------------------------ bars -> matches
def _within(a: float, b: float, pct: float, absolute: float) -> bool:
    if not (np.isfinite(a) and np.isfinite(b)):
        return False
    return abs(a - b) <= max(pct * abs(b), absolute)


def compare_bar(ours: Optional[pd.Series], theirs: Optional[pd.Series], liq_comparable: bool = True) -> Dict[str, object]:
    """One market-bar: which registered fields match. `theirs` is aggr's row; None means aggr saved nothing
    (a miss). `liq_comparable` is False for a Binance bar rebuilt from the archive."""
    if theirs is None or ours is None:
        return {"match": False, "failed": "missing_theirs" if theirs is None else "missing_ours"}
    failed = []
    for f in ("open", "high", "low", "close"):
        ref = float(theirs[f])
        if not (np.isfinite(ref) and np.isfinite(ours[f]) and abs(ours[f] - ref) <= PRICE_BPS / 1e4 * abs(ref)):
            failed.append(f)
    if not _within(ours["vbuy"] + ours["vsell"], float(theirs["vbuy"]) + float(theirs["vsell"]), VOLUME_PCT, VOLUME_USD):
        failed.append("volume")
    if not _within(ours["cbuy"] + ours["csell"], float(theirs["cbuy"]) + float(theirs["csell"]), COUNT_PCT, COUNT_N):
        failed.append("count")
    if liq_comparable:
        for f in ("lbuy", "lsell"):
            ref = float(theirs[f]) if pd.notna(theirs[f]) else 0.0      # aggr writes the pair only when non-zero
            if not _within(float(ours[f]), ref, LIQ_PCT, LIQ_USD):
                failed.append(f)
    return {"match": not failed, "failed": ",".join(failed)}


def in_gap(time_s: int, bar_ms: int, gaps: List[Tuple[int, int]]) -> bool:
    start, end = int(time_s) * 1000, int(time_s) * 1000 + bar_ms
    return any(a < end and b > start for a, b in gaps)


def merge_archive(tape: pd.DataFrame, archive: pd.DataFrame, binance_gaps: List[Tuple[int, int]],
                  bar_ms: int = HOUR_MS) -> Tuple[pd.DataFrame, set]:
    """Per Binance market-bar: the tape's bar where no recorded gap overlaps it, the archive's bar where one
    does (and the archive has it). Returns the merged bars and the set of (time, market) taken from the
    archive, whose liquidation columns are then not comparable."""
    if archive is None or not len(archive):
        return tape, set()
    keep, taken = [], set()
    arch = archive.set_index(["time", "market"])
    for _, row in tape.iterrows():
        key = (int(row["time"]), row["market"])
        if row["market"].startswith("BINANCE_FUTURES:") and in_gap(key[0], bar_ms, binance_gaps) and key in arch.index:
            continue                            # the archive's bar replaces it below
        keep.append(row)
    for key, row in arch.iterrows():
        if in_gap(key[0], bar_ms, binance_gaps):
            keep.append(pd.Series({"time": int(key[0]), "market": key[1], **row.to_dict()}))
            taken.add((int(key[0]), key[1]))
    out = pd.DataFrame(keep, columns=COLUMNS) if keep else pd.DataFrame(columns=COLUMNS)
    return out.drop_duplicates(["time", "market"], keep="last").sort_values(["market", "time"]).reset_index(drop=True), taken


def compare_day(ours: pd.DataFrame, theirs: pd.DataFrame, gaps_ms: Dict[str, List[Tuple[int, int]]],
                bar_ms: int = HOUR_MS, archive_bars: Iterable[Tuple[int, str]] = (),
                markets: Optional[Iterable[str]] = None, no_liq: Iterable[str] = ("binance",)) -> pd.DataFrame:
    """Every market-bar of a day on either side, over aggr's `markets` only (a market aggr never has is not
    a miss): excluded when the bar overlaps a recorded gap of its venue and did not come from the archive,
    else compared. A venue in `no_liq` has no liquidation stream on this tape (Binance's delivers nothing
    here, ERRATA 2026-11-02), so its `lbuy`/`lsell` are not compared. Columns: time, market, comparable,
    match, failed."""
    archive = set(archive_bars)
    allowed = set(markets) if markets is not None else None
    o = ours.set_index(["time", "market"]) if len(ours) else pd.DataFrame(columns=COLUMNS).set_index(["time", "market"])
    t = theirs.set_index(["time", "market"]) if len(theirs) else pd.DataFrame(columns=COLUMNS).set_index(["time", "market"])
    keys = sorted(k for k in set(o.index) | set(t.index) if allowed is None or k[1] in allowed)
    rows = []
    for time, market in keys:
        venue = {"BINANCE_FUTURES": "binance", "BYBIT": "bybit", "OKEX": "okx"}.get(market.split(":")[0])
        from_archive = (int(time), market) in archive
        if not from_archive and in_gap(int(time), bar_ms, gaps_ms.get(venue, [])):
            rows.append({"time": int(time), "market": market, "comparable": False, "match": False, "failed": "gap"})
            continue
        r = compare_bar(o.loc[(time, market)] if (time, market) in o.index else None,
                        t.loc[(time, market)] if (time, market) in t.index else None,
                        liq_comparable=not from_archive and venue not in no_liq)
        rows.append({"time": int(time), "market": market, "comparable": True, **r})
    return pd.DataFrame(rows, columns=["time", "market", "comparable", "match", "failed"])


def day_summary(table: pd.DataFrame) -> Dict[str, object]:
    comp = table[table["comparable"]]
    frac = float(comp["match"].mean()) if len(comp) else float("nan")
    worst = comp.loc[~comp["match"], "failed"].str.split(",").explode().value_counts()
    return {"bars": int(len(table)), "comparable": int(len(comp)), "excluded": int((~table["comparable"]).sum()),
            "matched": int(comp["match"].sum()), "fraction": frac,
            "day_matches": bool(len(comp) and frac >= DAY_MATCH),
            "worst_field": str(worst.index[0]) if len(worst) else ""}


def verdict(days: pd.DataFrame, min_days: int = 30) -> Dict[str, object]:
    """Criterion (a) on the hourly table's `all` rows (all three venues' bars together, as registered): the
    share of comparable days that match, and the call."""
    d = days[(days["bar"] == "1h") & (days["comparable"] > 0)]
    if "venue" in d.columns:
        d = d[d["venue"] == "all"]
    n = int(d["day"].nunique()) if len(d) else 0
    if n < min_days:
        return {"days": n, "fraction": float("nan"), "a": None, "note": f"fewer than {min_days} comparable days"}
    by_day = d.groupby("day")["day_matches"].all()
    frac = float(by_day.mean())
    return {"days": n, "fraction": frac, "a": frac >= DAYS_MATCH, "note": ""}


def ct_values(instruments_json: str) -> Dict[str, float]:
    doc = json.loads(instruments_json)
    return {k: float(v["ctVal"]) for k, v in doc.get("instruments", {}).items()}


def iter_days(first: str, last: str) -> Iterator[str]:
    for d in pd.date_range(first, last, freq="D"):
        yield d.strftime("%Y-%m-%d")
