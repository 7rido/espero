"""#39's published numbers, rebuilt from the committed day rows (research/markout_days.csv.gz).
A change to espero.markout's statistics that moves them fails here."""
import unittest
from pathlib import Path

import pandas as pd

from espero import costs
from espero import markout as mk
from tests.approx import approx

DAYS = Path(__file__).resolve().parents[1] / "research" / "markout_days.csv.gz"
KEYS = ["venue", "coin", "measure", "horizon", "cond", "level"]
HEADLINE = [
    (("binance", "BTC", "taker", 0), 0.3342, 61.49, 210),
    (("hyperliquid", "BTC", "maker_cons", 60), -1.4185, -25.23, 24),
    (("binance", "SOL", "maker_opt", 60), 0.3854, 33.64, 210),
    (("binance", "XRP", "maker_cons", 60), -1.1046, -62.01, 210),
]


class TestPublishedNumbers(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        d = pd.read_csv(DAYS)
        d = d[d["set"].isin(["B", "H"]) & (d["cond"] == "all")]
        cls.stats = mk.day_stats(d, KEYS).set_index(["venue", "coin", "measure", "horizon"])

    def test_headline_cells(self):
        for cell, mean, t, days in HEADLINE:
            with self.subTest(cell=cell):
                r = self.stats.loc[cell]
                assert r["mean"] == approx(mean, abs=1e-4)
                assert r["t"] == approx(t, abs=0.01)
                assert r["days"] == days

    def test_bar_and_the_shipped_table(self):
        assert mk.bar(mk.PRIOR_TESTS + mk.CELLS) == approx(4.596, abs=5e-4)
        assert costs.round_trip("hyperliquid", "BTC") == approx(9.91, abs=0.01)
        assert costs.round_trip("binance", "BTC") == approx(10.67, abs=0.01)
        assert ("binance", "BTC", "taker", 0, "liq", "liq_hour") in costs.TABLE


if __name__ == "__main__":
    unittest.main()
