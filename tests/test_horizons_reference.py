"""#43's S1 12 h headline, rebuilt from the committed trade list. Both readings are pinned:
the pre-registered day-mean, and the trade-weighted mean a book would earn."""
import unittest
from pathlib import Path

import pandas as pd

from espero import horizons as hz
from tests.approx import approx

TRADES = Path(__file__).resolve().parents[1] / "research" / "horizons_s1_12h_trades.csv.gz"
H = hz.HORIZONS["12h"]


class TestS1Headline(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.sel, cls.hold = hz.windows(pd.read_csv(TRADES))

    def test_day_mean_headline(self):
        assert hz.stats(self.sel, H)["mean"] == approx(43.54, abs=0.01)
        s = hz.stats(self.hold, H)
        assert s["mean"] == approx(21.76, abs=0.01) and s["t"] == approx(2.12, abs=0.01)
        assert s["trades"] == 6310

    def test_trade_weighted_reading(self):
        assert 1e4 * self.sel["net"].mean() == approx(13.1, abs=0.05)
        assert 1e4 * self.hold["net"].mean() == approx(-9.6, abs=0.05)


if __name__ == "__main__":
    unittest.main()
