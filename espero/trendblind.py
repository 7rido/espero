"""#79: #78's trend rule on names chosen blind, the Dow Jones 30 of November 2021
(research/PREREGISTRATION_TRENDBLIND.md).

The list and the bar helper only: the rule, costs and criteria are `espero.trendstock`'s, unchanged.
research/trendblind.py fetches and prints.
"""
from __future__ import annotations

from typing import List, Tuple

import pandas as pd

# The Dow's 30 components as recalled on 2021-11-08, listed before any price of them was read.
DOW = ("AAPL", "AMGN", "AXP", "BA", "CAT", "CRM", "CSCO", "CVX", "DIS", "DOW", "GS", "HD", "HON", "IBM", "INTC",
       "JNJ", "JPM", "KO", "MCD", "MMM", "MRK", "MSFT", "NKE", "PG", "TRV", "UNH", "V", "VZ", "WBA", "WMT")


def bars_of(df: pd.DataFrame) -> Tuple[List[int], List[float], List[float]]:
    """(unix seconds, opens, closes) of a daily frame with `ts`, `open`, `close`, in time order, bars without both
    prices dropped."""
    d = df.dropna(subset=["ts", "open", "close"]).sort_values("ts")
    return [int(x) for x in d["ts"]], [float(x) for x in d["open"]], [float(x) for x in d["close"]]
