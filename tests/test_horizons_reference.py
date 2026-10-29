"""#43's S1 12 h headline, rebuilt from the committed trade list. Both readings are pinned:
the pre-registered day-mean, and the trade-weighted mean a book would earn."""
from pathlib import Path

import pandas as pd
import pytest

from espero import horizons as hz

TRADES = Path(__file__).resolve().parents[1] / "research" / "horizons_s1_12h_trades.csv.gz"
H = hz.HORIZONS["12h"]


@pytest.fixture(scope="module")
def split():
    return hz.windows(pd.read_csv(TRADES))


def test_day_mean_headline(split):
    sel, hold = split
    assert hz.stats(sel, H)["mean"] == pytest.approx(43.54, abs=0.01)
    s = hz.stats(hold, H)
    assert s["mean"] == pytest.approx(21.76, abs=0.01) and s["t"] == pytest.approx(2.12, abs=0.01)
    assert s["trades"] == 6310


def test_trade_weighted_reading(split):
    sel, hold = split
    assert 1e4 * sel["net"].mean() == pytest.approx(13.1, abs=0.05)
    assert 1e4 * hold["net"].mean() == pytest.approx(-9.6, abs=0.05)
