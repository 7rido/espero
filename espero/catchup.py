"""What is left of Hyperliquid's catch-up to Binance after a delay (#57, research/PREREGISTRATION_CATCHUP.md).

Measures a market order on recorded data; it places nothing.
"""
from __future__ import annotations

from typing import Dict, Optional

import numpy as np

from espero.bookwalk import walk

WINDOW_MS = 1_000
MOVE_BPS = 10.0
GAP_MS = 30_000
MAX_STALE_MS = 5_000
FEE_BPS = 4.5
MAX_UNFILLABLE = 0.05
COINS_NEEDED = 4


def events(ms: np.ndarray, prices: np.ndarray) -> np.ndarray:
    """(Trade index, direction) rows: a 10 bps change against the last trade at or before 1,000 ms earlier.

    Each event is at least 30 s after the previous kept event. `ms` must be sorted.
    """
    ref = np.searchsorted(ms, ms - WINDOW_MS, side="right") - 1
    has_ref = ref >= 0
    change = np.full(len(ms), np.nan)
    change[has_ref] = (prices[has_ref] / prices[ref[has_ref]] - 1) * 1e4
    out, last = [], -np.inf
    for i in np.flatnonzero(np.abs(np.nan_to_num(change)) >= MOVE_BPS):
        if ms[i] - last >= GAP_MS:
            out.append((i, np.sign(change[i])))
            last = ms[i]
    return np.array(out, dtype=float).reshape(-1, 2)


def snapshot_at(book_ms: np.ndarray, when: float) -> Optional[int]:
    """The first snapshot at or after `when`, if it is within 5 s; fills come after the decision."""
    i = int(np.searchsorted(book_ms, when, side="left"))
    if i >= len(book_ms) or book_ms[i] - when > MAX_STALE_MS:
        return None
    return i


def trade(book: Dict[str, np.ndarray], event_ms: float, direction: float, delay_ms: float, hold_ms: float,
          usd: float) -> Dict[str, object]:
    """One event's round trip. `book` holds ms, asks_px, asks_qty, bids_px and bids_qty, one row per snapshot."""
    entry_at = event_ms + delay_ms
    i = snapshot_at(book["ms"], entry_at)
    j = snapshot_at(book["ms"], entry_at + hold_ms)
    if i is None or j is None:
        return {"status": "no_snapshot"}
    costs, mids = [], []
    # a buy on an up move sells on exit, and the reverse on a down move
    for row, side in ((i, "buy" if direction > 0 else "sell"), (j, "sell" if direction > 0 else "buy")):
        levels = "asks" if side == "buy" else "bids"
        mid = (book["asks_px"][row, 0] + book["bids_px"][row, 0]) / 2
        px, qty = book[f"{levels}_px"][row:row + 1], book[f"{levels}_qty"][row:row + 1]
        cost = walk(px, qty, np.array([mid]), usd, side)[0]
        if not np.isfinite(cost):
            return {"status": "unfillable"}
        costs.append(float(cost))
        mids.append(float(mid))
    gross = float(direction * (mids[1] / mids[0] - 1) * 1e4)
    fees = 2 * FEE_BPS
    return {"status": "ok", "gross": gross, "walk": costs[0] + costs[1], "fees": fees,
            "net": gross - costs[0] - costs[1] - fees}


def verdict(low: float, high: float, first_half: float, second_half: float, coins_positive: int,
            unfillable: float) -> str:
    """The registered rule, checked in the registered order."""
    if high <= 0:
        return "NOT CAPTURED"
    if (low > 0 and first_half > 0 and second_half > 0 and coins_positive >= COINS_NEEDED
            and unfillable <= MAX_UNFILLABLE):
        return "WORTH TESTING ON UNREAD DAYS"
    return "CAN'T SAY"
