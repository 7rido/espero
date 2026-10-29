"""Measured trading costs, from #39 (research/PREREGISTRATION_MARKOUT.md).

All numbers are bps of notional, per leg, for a fill too small to walk the book.

* taker leg = the venue's taker fee + the measured effective half-spread.
* maker leg = the venue's maker fee. A rule whose gross return is measured from
  its own fill price (a resting order that fills only when traded through, as
  bids.py's rule) already carries the adverse selection; nothing more is added.
* maker leg with `adverse=True` also subtracts the conservative (back-of-queue)
  markout at `horizon`: for a rule whose gross is measured from the mid when it
  decided to rest, as if a touch were a fill.

Only the cells #39 measured, and on Binance only the ones whose trade proxy was
validated, are in the table. Anything else raises: no coin is imputed.
"""
from __future__ import annotations

from typing import Optional, Tuple

from espero.costs_table import SOURCE, TABLE
from espero.markout import FEES_BPS


class NotMeasured(KeyError):
    pass


def _cell(venue: str, coin: str, measure: str, horizon: int, condition: Optional[Tuple[str, str]]) -> float:
    cond, level = condition or ("all", "all")
    key = (venue, coin, measure, horizon, cond, level)
    if key not in TABLE:
        raise NotMeasured(f"#39 has no measured cell {key} ({SOURCE})")
    return TABLE[key]


def leg(venue: str, coin: str, kind: str, condition: Optional[Tuple[str, str]] = None,
        adverse: bool = False, horizon: int = 60) -> float:
    """One fill's cost in bps. `kind` is 'taker' or 'maker'; `condition` a
    (condition, level) pair such as ('funding', 'settlement')."""
    if kind not in ("taker", "maker"):
        raise ValueError(kind)
    fee = FEES_BPS[venue][kind]
    if kind == "taker":
        return fee + _cell(venue, coin, "taker", 0, condition)
    return fee - (_cell(venue, coin, "maker_cons", horizon, condition) if adverse else 0.0)


def round_trip(venue: str, coin: str, entry: str = "taker", exit: str = "taker",
               entry_condition: Optional[Tuple[str, str]] = None,
               exit_condition: Optional[Tuple[str, str]] = None) -> float:
    return leg(venue, coin, entry, entry_condition) + leg(venue, coin, exit, exit_condition)
