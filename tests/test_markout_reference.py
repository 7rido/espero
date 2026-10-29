"""#39's published numbers, rebuilt from the committed day rows (research/markout_days.csv.gz).
A change to espero.markout's statistics that moves them fails here."""
from pathlib import Path

import pandas as pd
import pytest

from espero import costs
from espero import markout as mk

DAYS = Path(__file__).resolve().parents[1] / "research" / "markout_days.csv.gz"
KEYS = ["venue", "coin", "measure", "horizon", "cond", "level"]


@pytest.fixture(scope="module")
def stats():
    d = pd.read_csv(DAYS)
    d = d[d["set"].isin(["B", "H"]) & (d["cond"] == "all")]
    return mk.day_stats(d, KEYS).set_index(["venue", "coin", "measure", "horizon"])


@pytest.mark.parametrize("cell, mean, t, days", [
    (("binance", "BTC", "taker", 0), 0.3342, 61.49, 210),
    (("hyperliquid", "BTC", "maker_cons", 60), -1.4185, -25.23, 24),
    (("binance", "SOL", "maker_opt", 60), 0.3854, 33.64, 210),
    (("binance", "XRP", "maker_cons", 60), -1.1046, -62.01, 210),
])
def test_headline_cells(stats, cell, mean, t, days):
    r = stats.loc[cell]
    assert r["mean"] == pytest.approx(mean, abs=1e-4)
    assert r["t"] == pytest.approx(t, abs=0.01)
    assert r["days"] == days


def test_bar_and_the_shipped_table():
    assert mk.bar(mk.PRIOR_TESTS + mk.CELLS) == pytest.approx(4.596, abs=5e-4)
    assert costs.round_trip("hyperliquid", "BTC") == pytest.approx(9.91, abs=0.01)
    assert costs.round_trip("binance", "BTC") == pytest.approx(10.67, abs=0.01)
    assert ("binance", "BTC", "taker", 0, "liq", "liq_hour") in costs.TABLE
