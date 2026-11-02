"""#62: the paper fills replayed on the recorded book (research/PREREGISTRATION_REPLAYSIM.md).

Pure where it can be: the order list a journal row becomes, the book at an order's arrival, the walk of a
market order down that book, the queue-position replay of a resting order (through hftbacktest, the `sim`
extra, when it is installed), the registered comparison. research/replaysim.py reads the journals and the
tape and prints. Nothing here writes a journal or touches a venue.

A market order arrives at decision + LATENCY_MS and fills against the last `l2Book` frame whose exchange
time is at or before its arrival: Hyperliquid's frames are whole books (top 20 a side), so the book at
arrival is the frame itself, no diffs to apply. Size beyond the recorded 20 levels is "beyond the tape"
and the fill is partial. A resting (post-only) order is replayed with hftbacktest's PowerProbQueueModel3
on the same frames and the trades between them, with the same latency both ways, until the mirror's own
cancel or close time.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Tuple

import numpy as np
import pandas as pd

LATENCY_MS = 250
LATENCY_INFO_MS = 1000
TAKER_MEDIAN_BPS, TAKER_P90_BPS = 5.0, 15.0
MAKER_AGREEMENT = 0.80
MIN_TAKER, MIN_MAKER = 30, 10
MIN_TAKER_INCONCLUSIVE = 10
BOOK_USD = 1000.0  # hlpbook.BOOK_USD, the notional each HLP trade carries
MAX_BOOK_AGE_MS = 60_000  # no frame within a minute before arrival: no book, not comparable
QUEUE_MODEL_POWER = 3.0
TRADE_WINDOW_MS = 3_600_000  # how much tape a resting order is replayed over at most


@dataclass
class Order:
    book: str  # carry-maker, carry-taker, hlp-book, hlp2-book, paper-btc-usd-hl, mirror
    ref: str  # the journal row it came from
    coin: str
    side: int  # +1 buy, -1 sell
    qty: float  # coins
    decision_ms: int
    paper_px: float
    kind: str = "market"  # market | limit
    limit_px: float = float("nan")
    until_ms: Optional[int] = None  # a resting order's cancel or close time
    paper_filled: Optional[bool] = None  # a resting order's own outcome
    venue: str = "hyperliquid"  # which tape: hyperliquid | hyperliquid_testnet


@dataclass
class Result:
    order: Order
    comparable: bool
    why: str = ""
    sim_px: float = float("nan")
    filled: float = 0.0  # share of qty filled
    diff_bps: float = float("nan")
    sim_filled: Optional[bool] = None  # resting orders
    sim_fill_ms: Optional[int] = None
    book_age_ms: Optional[int] = None
    latency_ms: int = LATENCY_MS
    levels_walked: int = 0


# ------------------------------------------------------------------ the journals, read-only
def _rows(db: Path, sql: str) -> List[sqlite3.Row]:
    con = sqlite3.connect(f"file:{db}?mode=ro", uri=True, timeout=2.0)
    con.row_factory = sqlite3.Row
    try:
        return con.execute(sql).fetchall()
    except sqlite3.Error:
        return []
    finally:
        con.close()


def orders_from_journals(state: Path, since_ms: int) -> Tuple[List[Order], List[Tuple[str, str]]]:
    """Every fill since `since_ms` in the paper books, as orders; and the rows that cannot be replayed, with
    why. Read-only; a missing journal contributes nothing."""
    state = Path(state)
    orders: List[Order] = []
    skipped: List[Tuple[str, str]] = []
    for db in sorted(state.glob("carry-*.db")):
        book = db.stem
        for r in _rows(db, "SELECT id, coin, entry_ts, exit_ts, qty_perp, perp_entry FROM positions"):
            if r["entry_ts"] * 1000 >= since_ms and r["qty_perp"] and r["perp_entry"]:
                orders.append(
                    Order(
                        book,
                        f"positions/{r['id']}/entry",
                        r["coin"],
                        -1,
                        float(r["qty_perp"]),
                        int(r["entry_ts"]) * 1000,
                        float(r["perp_entry"]),
                    )
                )
            if r["exit_ts"] and r["exit_ts"] * 1000 >= since_ms:
                skipped.append((f"{book} positions/{r['id']}/exit", "the perp exit price is not journaled"))
        if book == "carry-maker":
            for m in _rows(db, "SELECT * FROM testnet_mirror"):
                for leg, side in (("open", -1), ("close", +1)):
                    ts, px, status = m[f"{leg}_ts"], m[f"{leg}_px"], m[f"{leg}_status"]
                    if not ts or ts * 1000 < since_ms or not px:
                        continue
                    size = m["open_size"] if leg == "open" else (m["open_filled"] or m["open_size"])
                    until = (m["close_ts"] or 0) * 1000 if leg == "open" else None
                    orders.append(
                        Order(
                            "mirror",
                            f"testnet_mirror/{m['position_id']}/{leg}",
                            m["coin"],
                            side,
                            float(size or 0),
                            int(ts) * 1000,
                            float(px),
                            "limit",
                            float(px),
                            until or None,
                            status == "filled",
                            "hyperliquid_testnet",
                        )
                    )
    for db in sorted(state.glob("hlp*-book.db")):
        for r in _rows(db, "SELECT coin, signal_ts, status, entry_ts, entry_px, exit_ts, exit_px FROM trades"):
            if r["entry_ts"] and r["entry_px"] and r["entry_ts"] * 1000 >= since_ms:
                orders.append(
                    Order(
                        db.stem,
                        f"trades/{r['coin']}/{r['signal_ts']}/entry",
                        r["coin"],
                        +1,
                        BOOK_USD / float(r["entry_px"]),
                        int(r["entry_ts"]) * 1000,
                        float(r["entry_px"]),
                    )
                )
            if r["exit_ts"] and r["exit_px"] and r["exit_ts"] * 1000 >= since_ms:
                orders.append(
                    Order(
                        db.stem,
                        f"trades/{r['coin']}/{r['signal_ts']}/exit",
                        r["coin"],
                        -1,
                        BOOK_USD / float(r["entry_px"]),
                        int(r["exit_ts"]) * 1000,
                        float(r["exit_px"]),
                    )
                )
    for db in sorted(state.glob("paper-*.db")):
        for r in _rows(db, "SELECT id, product, side, size, filled_ts, filled_px FROM orders WHERE status='filled'"):
            if r["filled_ts"] and r["filled_ts"] * 1000 >= since_ms:
                orders.append(
                    Order(
                        db.stem,
                        f"orders/{r['id']}",
                        r["product"].split("-")[0],
                        +1 if r["side"] == "BUY" else -1,
                        float(r["size"]),
                        int(r["filled_ts"]) * 1000,
                        float(r["filled_px"]),
                    )
                )
    return orders, skipped


# ------------------------------------------------------------------ the tape
def books_and_trades(frames: Iterable[dict], coin: str) -> Tuple[List[dict], List[dict]]:
    """A coin's `l2Book` frames and trades from recorded lines: books as {t, rt, bids, asks} with (px, sz)
    best first; trades as {t, rt, px, sz, side} with side +1 for a buyer-initiated print."""
    books, trades = [], []
    for rec in frames:
        d = rec.get("d")
        if not isinstance(d, dict):
            continue
        if rec.get("ch") == "l2Book" and rec.get("s") == coin:
            lv = d["data"]["levels"]
            books.append(
                {
                    "t": int(d["data"]["time"]),
                    "rt": int(rec["rt"]),
                    "bids": [(float(x["px"]), float(x["sz"])) for x in lv[0]],
                    "asks": [(float(x["px"]), float(x["sz"])) for x in lv[1]],
                }
            )
        elif rec.get("ch") == "trades" and rec.get("s") == coin:
            for t in d.get("data", []):
                trades.append(
                    {
                        "t": int(t["time"]),
                        "rt": int(rec["rt"]),
                        "px": float(t["px"]),
                        "sz": float(t["sz"]),
                        "side": +1 if t["side"] == "B" else -1,
                    }
                )
    books.sort(key=lambda b: b["t"])
    trades.sort(key=lambda x: x["t"])
    return books, trades


def feed_lag_ms(books: List[dict], trades: List[dict]) -> Dict[str, float]:
    lags = [b["rt"] - b["t"] for b in books] + [x["rt"] - x["t"] for x in trades]
    if not lags:
        return {"n": 0, "median": float("nan"), "p90": float("nan")}
    a = np.asarray(lags, dtype=float)
    return {"n": len(a), "median": float(np.median(a)), "p90": float(np.percentile(a, 90))}


def book_at(books: List[dict], at_ms: int, max_age_ms: int = MAX_BOOK_AGE_MS) -> Optional[dict]:
    """The last whole book whose exchange time is at or before `at_ms`, if it is young enough."""
    ts = [b["t"] for b in books]
    i = int(np.searchsorted(ts, at_ms, side="right")) - 1
    if i < 0 or at_ms - books[i]["t"] > max_age_ms:
        return None
    return books[i]


def walk(book: dict, side: int, qty: float) -> Tuple[float, float, int]:
    """A market order against a whole book: (average price, share filled, levels walked). A buy lifts the
    asks best first; what the 20 recorded levels cannot fill stays unfilled."""
    levels = book["asks"] if side > 0 else book["bids"]
    need, usd, done, n = qty, 0.0, 0.0, 0
    for px, sz in levels:
        if need <= 0:
            break
        take = min(sz, need)
        usd += take * px
        done += take
        need -= take
        n += 1
    if done <= 0:
        return float("nan"), 0.0, 0
    return usd / done, done / qty, n


def tick_of(prices: Iterable[float]) -> float:
    """The finest price step the recorded prices show (a power of ten)."""
    decimals = 0
    for p in prices:
        s = f"{p:.10f}".rstrip("0").rstrip(".")
        decimals = max(decimals, len(s.split(".")[1]) if "." in s else 0)
    return 10.0**-decimals


def replay_market(order: Order, books: List[dict], latency_ms: int = LATENCY_MS) -> Result:
    arrival = order.decision_ms + latency_ms
    book = book_at(books, arrival)
    if book is None:
        return Result(order, False, "no book within a minute before arrival", latency_ms=latency_ms)
    px, filled, n = walk(book, order.side, order.qty)
    if filled <= 0:
        return Result(order, False, "empty side of the book", latency_ms=latency_ms, book_age_ms=arrival - book["t"])
    diff = order.side * (px - order.paper_px) / order.paper_px * 1e4
    return Result(order, True, "", px, filled, float(diff), None, None, arrival - book["t"], latency_ms, n)


# ------------------------------------------------------------------ resting orders, through hftbacktest
def event_array(books: List[dict], trades: List[dict], tick: float, lot: float, num_levels: int = 20):
    """hftbacktest's event array from whole books and trades, the way its own Hyperliquid converter builds
    it (diffs between consecutive whole books; trades by the initiator's side). Needs the `sim` extra."""
    from hftbacktest import BUY_EVENT, DEPTH_EVENT, SELL_EVENT, TRADE_EVENT, event_dtype
    from hftbacktest.data.utils.difforderbooksnapshot import CHANGED, INSERTED, DiffOrderBookSnapshot
    from hftbacktest.data.validation import correct_event_order, validate_event_order

    rows = []
    diff = DiffOrderBookSnapshot(num_levels, tick, lot)
    stream = sorted([("b", b) for b in books] + [("t", x) for x in trades], key=lambda e: (e[1]["t"], e[1]["rt"]))
    for kind, e in stream:
        exch, local = e["t"] * 1_000_000, e["rt"] * 1_000_000
        if kind == "t":
            rows.append(
                (TRADE_EVENT | (BUY_EVENT if e["side"] > 0 else SELL_EVENT), exch, local, e["px"], e["sz"], 0, 0, 0)
            )
            continue
        bid, ask, bid_del, ask_del = diff.snapshot(
            np.array([p for p, _ in e["bids"]]),
            np.array([s for _, s in e["bids"]]),
            np.array([p for p, _ in e["asks"]]),
            np.array([s for _, s in e["asks"]]),
        )
        for entries, ev in ((bid, DEPTH_EVENT | BUY_EVENT), (ask, DEPTH_EVENT | SELL_EVENT)):
            for px, qty, flag in entries:
                if flag == INSERTED or flag == CHANGED:
                    rows.append((ev, exch, local, px, qty, 0, 0, 0))
        for entries, ev in ((bid_del, DEPTH_EVENT | BUY_EVENT), (ask_del, DEPTH_EVENT | SELL_EVENT)):
            for px, _qty, _flag in entries:  # a level that left the top 20 is deleted, as the converter does
                rows.append((ev, exch, local, px, 0, 0, 0, 0))
    arr = np.array(rows, dtype=event_dtype)
    data = correct_event_order(
        arr, np.argsort(arr["exch_ts"], kind="mergesort"), np.argsort(arr["local_ts"], kind="mergesort")
    )
    validate_event_order(data)
    return data


def replay_limit(
    order: Order, books: List[dict], trades: List[dict], latency_ms: int = LATENCY_MS, until_ms: Optional[int] = None
) -> Result:
    """A post-only order at `limit_px`, submitted at decision time, back of the queue, replayed through
    hftbacktest until `until_ms` (the mirror's own close or cancel, else TRADE_WINDOW_MS later)."""
    try:
        from hftbacktest import GTX, LIMIT, BacktestAsset, HashMapMarketDepthBacktest
        from hftbacktest.order import FILLED
    except ImportError:
        return Result(order, False, "hftbacktest not installed (the sim extra)", latency_ms=latency_ms)
    if not books:
        return Result(order, False, "no book on the tape", latency_ms=latency_ms)
    until = until_ms or order.until_ms or (order.decision_ms + TRADE_WINDOW_MS)
    prices = [p for b in books for p, _ in b["bids"] + b["asks"]] + [order.limit_px]
    tick = tick_of(prices)
    lot = tick_of([s for b in books for _, s in b["bids"] + b["asks"]] + [order.qty]) or 1e-8
    data = event_array(books, trades, tick, lot)
    if not len(data):
        return Result(order, False, "no events on the tape", latency_ms=latency_ms)
    L = latency_ms * 1_000_000
    # NoPartialFillExchange: hftbacktest 2.4.4's PartialFillExchange stops with error 14 at the first print on a
    # tape of whole-book frames (its own converter's output included; checked 2026-11-02), so a resting order
    # here fills whole once the queue ahead of it is cleared, or not at all.
    asset = (
        BacktestAsset()
        .data([data])
        .linear_asset(1.0)
        .constant_order_latency(L, L)
        .power_prob_queue_model3(QUEUE_MODEL_POWER)
        .no_partial_fill_exchange()
        .trading_value_fee_model(0.0, 0.0)
        .tick_size(tick)
        .lot_size(lot)
        .last_trades_capacity(0)
    )
    hbt = HashMapMarketDepthBacktest([asset])
    start = order.decision_ms * 1_000_000
    hbt.elapse(1_000_000)  # the clock starts on the first elapse, at the tape's first frame
    if hbt.current_timestamp < start:
        hbt.elapse(start - hbt.current_timestamp)
    if order.side > 0:
        hbt.submit_buy_order(0, 1, order.limit_px, order.qty, GTX, LIMIT, False)
    else:
        hbt.submit_sell_order(0, 1, order.limit_px, order.qty, GTX, LIMIT, False)
    end = until * 1_000_000
    filled_at = None
    last = -1
    while hbt.current_timestamp < end:
        rc = hbt.elapse(min(500_000_000, end - hbt.current_timestamp))
        now = hbt.current_timestamp
        o = hbt.orders(0).get(1)
        if o is not None and o.status == FILLED:
            filled_at = int(now // 1_000_000)
            break
        if rc == 1 or (rc != 0 and now == last):
            break  # the tape ended, or the engine stopped advancing
        last = now
    hbt.close()
    sim_filled = filled_at is not None
    agree = order.paper_filled is None or sim_filled == order.paper_filled
    return Result(
        order,
        True,
        "",
        order.limit_px if sim_filled else float("nan"),
        1.0 if sim_filled else 0.0,
        0.0 if agree else float("nan"),
        sim_filled,
        filled_at,
        None,
        latency_ms,
    )


# ------------------------------------------------------------------ the comparison
def summarize(results: List[Result]) -> Dict[str, object]:
    taker = [r for r in results if r.comparable and r.order.kind == "market"]
    maker = [r for r in results if r.comparable and r.order.kind == "limit"]
    out: Dict[str, object] = {"taker_n": len(taker), "maker_n": len(maker), "excluded": {}, "taker": {}, "maker": {}}
    why: Dict[str, int] = {}
    for r in results:
        if not r.comparable:
            why[r.why] = why.get(r.why, 0) + 1
    out["excluded"] = why
    if taker:
        d = np.array([r.diff_bps for r in taker])
        out["taker"] = {
            "median_abs": float(np.median(np.abs(d))),
            "p90_abs": float(np.percentile(np.abs(d), 90)),
            "median_signed": float(np.median(d)),
            "p10": float(np.percentile(d, 10)),
            "p90": float(np.percentile(d, 90)),
            "partial": int(sum(r.filled < 1 for r in taker)),
            "walked_more_than_one_level": int(sum(r.levels_walked > 1 for r in taker)),
        }
    if maker:
        agree = [r.sim_filled == r.order.paper_filled for r in maker if r.order.paper_filled is not None]
        out["maker"] = {
            "agreement": float(np.mean(agree)) if agree else float("nan"),
            "n_with_outcome": len(agree),
            "sim_filled": int(sum(bool(r.sim_filled) for r in maker)),
        }
    return out


def verdict(summary: Dict[str, object], final: bool = False) -> Dict[str, object]:
    """The registered call: judged at 30 taker and 10 maker comparable fills, or at the window's end."""
    tn, mn = summary["taker_n"], summary["maker_n"]
    if not final and (tn < MIN_TAKER or mn < MIN_MAKER):
        return {"judged": False, "call": "not judged", "note": f"{tn}/{MIN_TAKER} taker, {mn}/{MIN_MAKER} maker fills"}
    if tn < MIN_TAKER_INCONCLUSIVE:
        return {"judged": True, "call": "INCONCLUSIVE", "note": f"{tn} comparable taker fills"}
    t = summary["taker"]
    taker_ok = t["median_abs"] <= TAKER_MEDIAN_BPS and t["p90_abs"] <= TAKER_P90_BPS
    m = summary["maker"]
    maker_ok = bool(m) and m["n_with_outcome"] > 0 and m["agreement"] >= MAKER_AGREEMENT
    call = "PASS" if taker_ok and maker_ok else "PARTIAL" if (taker_ok or maker_ok) else "FAIL"
    return {
        "judged": True,
        "call": call,
        "taker_ok": taker_ok,
        "maker_ok": maker_ok,
        "note": "the paper books flatter themselves" if t["median_signed"] > 3.0 else "",
    }


def rows_of(results: List[Result]) -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "book": r.order.book,
                "ref": r.order.ref,
                "coin": r.order.coin,
                "side": r.order.side,
                "kind": r.order.kind,
                "qty": r.order.qty,
                "decision_ms": r.order.decision_ms,
                "paper_px": r.order.paper_px,
                "latency_ms": r.latency_ms,
                "comparable": r.comparable,
                "why": r.why,
                "sim_px": r.sim_px,
                "filled": r.filled,
                "diff_bps": r.diff_bps,
                "sim_filled": r.sim_filled,
                "paper_filled": r.order.paper_filled,
                "sim_fill_ms": r.sim_fill_ms,
                "book_age_ms": r.book_age_ms,
                "levels": r.levels_walked,
            }
            for r in results
        ]
    )
