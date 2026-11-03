import unittest

from espero import costs
from tests.approx import approx


class TestCosts(unittest.TestCase):
    """espero.costs: a leg is the fee plus the measured cell, and an unmeasured cell raises, never guesses."""

    def setUp(self):
        self._table = costs.TABLE
        costs.TABLE = {("hyperliquid", "BTC", "taker", 0, "all", "all"): 0.4,
                       ("hyperliquid", "BTC", "taker", 0, "funding", "settlement"): 1.1,
                       ("hyperliquid", "BTC", "maker_cons", 60, "all", "all"): -3.0}

    def tearDown(self):
        costs.TABLE = self._table

    def test_taker_leg_is_fee_plus_half_spread(self):
        assert costs.leg("hyperliquid", "BTC", "taker") == approx(4.9)
        assert costs.leg("hyperliquid", "BTC", "taker", ("funding", "settlement")) == approx(5.6)

    def test_maker_leg_adds_adverse_selection_only_when_asked(self):
        assert costs.leg("hyperliquid", "BTC", "maker") == approx(1.5)
        assert costs.leg("hyperliquid", "BTC", "maker", adverse=True) == approx(4.5)

    def test_round_trip(self):
        assert costs.round_trip("hyperliquid", "BTC", "maker", "taker") == approx(6.4)

    def test_unmeasured_raises(self):
        with self.assertRaises(costs.NotMeasured):
            costs.leg("hyperliquid", "DOGE", "taker")
        with self.assertRaises(costs.NotMeasured):
            costs.leg("binance", "BTC", "taker")
        with self.assertRaises(ValueError):
            costs.leg("hyperliquid", "BTC", "stop")


if __name__ == "__main__":
    unittest.main()
