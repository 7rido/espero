"""Step 4's lean gate, research/REGIME_CANDIDATES.md: prints the 6 correlations per class and nothing else about the
model. It fetches the rating's public daily prices and keeps none of them.

    .venv/bin/python research/regime_gate.py
"""
from __future__ import annotations

import pandas as pd

from espero import rate as rt
from espero import regimes as rg

CANDIDATES = {"etf": "volatility, stocks and ETFs", "crypto": "funding, crypto"}


def main() -> None:
    now = pd.Timestamp.now(tz="UTC").tz_localize(None)
    for kind, name in CANDIDATES.items():
        symbols = rt.pool(kind)
        prices, errors = rt.load_frames(symbols, {s: kind for s in symbols}, now=now)
        rows = rg.panel(prices, kind, now)
        lean = rg.lean_by_fold(rows)
        negative = sum(c < 0 for c in lean)
        print(f"{name}: {len(prices)} of {len(symbols)} symbols, {rows.index.nunique()} dates, last {rows.index.max().date()}")
        print("  " + "  ".join(f"{c:+.3f}" for c in lean))
        print(f"  {negative} of {rt.SPLITS} folds negative: {'open' if rg.fades(lean) else 'CLOSED'}")
        for symbol, reason in errors.items():
            print(f"  not fetched, {symbol}: {reason[:80]}")


if __name__ == "__main__":
    main()
