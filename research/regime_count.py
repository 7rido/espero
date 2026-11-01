"""Step 4's count against the bar in research/REGIME_POWER.md: dates per state, from the date index alone. It prints no
outcome, skill or return, and fits nothing. It fetches the rating's public daily prices and keeps none of them, and reads
BTC's funding from #19's file without changing it.

    .venv/bin/python research/regime_count.py
"""
from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

from espero import rate as rt
from espero import regimes as rg

FUNDING = Path(__file__).resolve().parents[1] / "data" / "settle" / "funding" / "BTCUSDT.json"
SPY, BTC = "SPY", "BTC funding"


def btc_funding(until: pd.Timestamp) -> pd.Series:
    rows = json.loads(FUNDING.read_text())
    s = pd.Series({pd.Timestamp(int(r["fundingTime"]), unit="ms"): float(r["fundingRate"]) for r in rows}).sort_index()
    return s[s.index < until]


def report(name: str, counts: dict, state: str, comparator: list, skill: float, half_width: float) -> None:
    print(f"\n{name}: {counts['dates']} dates, {counts['labelled']} labelled, {counts['unlabelled']} unlabelled")
    print(f"  test dates {counts['test_dates']}, of which unlabelled {counts['unlabelled_test']}")
    for s, row in counts["states"].items():
        print(f"  {s:14} test {row['test']:5}  halves {row['first_half']:4} / {row['second_half']:4}  "
              f"by fold {row['by_fold']}  training by fold {row['train']}")
    v = rg.verdict(counts, state, comparator, skill, half_width)
    print(f"  {state}: w {v['w']:.3f}, c {v['c']:.3f}, MDE {v['mde']:.2f}%, D {v['d']:.2f}%, "
          f"both halves {v['halves']}: {'OPEN' if v['open'] else 'CLOSED'}")


def main() -> None:
    now = pd.Timestamp.now(tz="UTC").tz_localize(None)
    until = rt.readable_until(now)

    symbols = rt.pool("etf")
    prices, _ = rt.load_frames(symbols, {s: "etf" for s in symbols}, now=now)
    dates = rg.panel(prices, "etf", now).index
    labels = rg.volatility_states(prices[SPY][prices[SPY].index < until], "etf")
    report("Volatility, stocks and ETFs (SPY)", rg.count_states(dates, labels), "high", ["low", "mid"], -0.61, 0.405)

    symbols = rt.pool("crypto")
    prices, _ = rt.load_frames(symbols, {s: "crypto" for s in symbols}, now=now)
    dates = rg.panel(prices, "crypto", now).index
    labels = rg.funding_states(btc_funding(until))
    report(f"Funding, crypto ({BTC})", rg.count_states(dates, labels), "crowded long", ["neutral"], -2.06, 1.93)


if __name__ == "__main__":
    main()
