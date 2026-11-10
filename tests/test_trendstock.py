"""#78's breakout rule on hand-made daily bars; the windows are patched to 3 and 2 so each number is worked by hand."""
import math
import unittest
from unittest import mock

import numpy as np

from espero import trendstock as T

DAY = 86400
TS = [k * DAY for k in range(20)]


def short():
    return mock.patch.multiple(T, ENTRY_WINDOW=3, EXIT_WINDOW=2)


class TestTrades(unittest.TestCase):
    def test_a_breakout_enters_at_the_next_open_and_a_break_exits_at_the_next_open(self):
        c = [10, 10, 10, 10, 11, 12, 13, 12, 11, 10.5, 10.4, 10.3]
        o = [10, 10, 10, 10, 10.5, 11.5, 12.5, 13, 12, 11, 10.5, 10.4]
        with short():
            got = T.trades(TS[:12], o, c)
        # close 11 at bar 4 beats the 3 closes before it (10): fills at bar 5's open 11.5.
        # bar 8 closes 11 under the lowest close of the 2 before it (12, 13 -> 12): exit at bar 9's open 11
        self.assertEqual(len(got), 1)
        t = got[0]
        self.assertEqual((t.entry_i, t.exit_i, t.entry, t.exit, t.end), (5, 9, 11.5, 11.0, False))
        self.assertAlmostEqual(t.days, 4.0)
        self.assertAlmostEqual(t.ret, 11.0 / 11.5 - 1 - 28e-4 - 0.10 * 4 / 365)

    def test_one_position_and_a_trade_open_at_the_end_closes_at_the_last_close(self):
        c = [10, 10, 10, 10, 11, 12, 13, 14, 15, 16]
        o = [10, 10, 10, 10, 10.5, 11.5, 12.5, 13.5, 14.5, 15.5]
        with short():
            got = T.trades(TS[:10], o, c)
        self.assertEqual(len(got), 1)                                  # later new highs do not add positions
        t = got[0]
        self.assertEqual((t.entry_i, t.exit_i, t.exit, t.end), (5, 9, 16.0, True))
        self.assertAlmostEqual(t.days, 4.0)

    def test_a_signal_on_the_last_bar_has_no_next_open_and_no_trade(self):
        c = [10, 10, 10, 10, 11]
        with short():
            self.assertEqual(T.trades(TS[:5], [10] * 5, c), [])

    def test_the_exit_signal_the_bar_after_the_fill_counts_and_a_tie_is_not_a_break(self):
        c = [10, 10, 10, 10, 11, 12, 9, 9, 9]
        o = [10, 10, 10, 10, 10.5, 11.5, 11.0, 9.5, 9.0]
        with short():
            got = T.trades(TS[:9], o, c)
        self.assertEqual((got[0].entry_i, got[0].exit_i), (5, 7))     # bar 6 closes 9, under min(11, 12): out at 7
        c2 = [10, 10, 10, 10, 11, 12, 11, 9]
        with short():
            self.assertEqual(T.trades(TS[:8], [10] * 8, c2)[0].exit_i, 7)   # 11 equals the low of (11,12): no break

    def test_the_fill_bar_itself_can_give_the_exit_signal(self):
        c = [10, 10, 10, 10, 11, 9, 9, 9]
        o = [10, 10, 10, 10, 10.5, 10.2, 9.5, 9.0]
        with short():
            got = T.trades(TS[:8], o, c)
        self.assertEqual((got[0].entry_i, got[0].exit_i, got[0].exit), (5, 6, 9.5))

    def test_no_signal_before_the_window_is_full(self):
        with short():
            self.assertEqual(T.trades(TS[:4], [1, 2, 3, 4], [1, 2, 3, 4]), [])
        self.assertEqual(T.trades(TS[:50], [1.0] * 50, [1.0] * 50), [])

    def test_costs_and_funding(self):
        self.assertAlmostEqual(T.net(100.0, 110.0, 73.0), 0.10 - 28e-4 - 0.10 * 73 / 365)
        self.assertAlmostEqual(T.net(100.0, 110.0, 73.0, cost_bps=0.0, funding_year=0.0), 0.10)


class TestStatistics(unittest.TestCase):
    def test_profit_factor_and_halves_and_breadth(self):
        self.assertAlmostEqual(T.profit_factor([0.3, -0.1, -0.1, 0.0]), 1.5)
        self.assertIsNone(T.profit_factor([0.1]))
        self.assertEqual(T.halves([1.0, 2.0, 3.0, -1.0, -2.0]), (2.0, -1.5))
        self.assertEqual(T.breadth({"A": [1.0] * 5, "B": [-1.0] * 5, "C": [1.0] * 4, "D": [0.0] * 5}), (1, 3))

    def test_the_t_is_clustered_by_group(self):
        t, g = T.clustered_t([1.0, 1.0, -1.0, -1.0, 2.0, 2.0], ["a", "a", "b", "b", "c", "c"])
        mean = 4 / 6
        se = math.sqrt(sum((2 * (r - mean)) ** 2 for r in (1.0, -1.0, 2.0)) / 36 * 3 / 2)
        self.assertEqual(g, 3)
        self.assertAlmostEqual(t, mean / se)
        self.assertEqual(T.clustered_t([1.0], ["a"]), (None, 1))
        self.assertEqual(T.clustered_t([1.0, 2.0], ["a", "a"]), (None, 1))

    def test_the_p_value(self):
        self.assertAlmostEqual(T.two_sided_p(2.0, 11), 0.0734, places=4)
        self.assertAlmostEqual(T.two_sided_p(3.0, 6), 0.0301, places=4)
        self.assertAlmostEqual(T.two_sided_p(-2.0, 11), 0.0734, places=4)
        self.assertAlmostEqual(T.two_sided_p(1.96, 101), 0.05, places=3)
        self.assertGreater(T.two_sided_p(1.96, 100), 0.05)

    def test_each_criterion(self):
        good = dict(n=300, pf=1.6, mean=0.03, t=3.2, q=0.01, share=0.01, h1=0.02, h2=0.04, up=19, counted=37)
        self.assertEqual(T.verdict(**good), ("PASS", []))
        self.assertEqual(T.verdict(**{**good, "n": 99})[0], "INCONCLUSIVE")
        self.assertEqual(T.verdict(**{**good, "n": 100})[0], "PASS")
        for key, bad in (("pf", 1.49), ("pf", None), ("mean", 0.0), ("t", 2.99), ("t", None), ("q", 0.05), ("q", None),
                         ("share", 0.05), ("h1", 0.0), ("h2", -0.1), ("up", 18)):
            got, missed = T.verdict(**{**good, key: bad})
            self.assertEqual((got, len(missed)), ("FAIL", 1), (key, bad))
        self.assertEqual(T.verdict(**{**good, "pf": 1.5, "t": 3.0})[0], "PASS")
        self.assertEqual(T.verdict(**{**good, "counted": 20, "up": 10})[0], "FAIL")
        self.assertEqual(T.verdict(**{**good, "counted": 0, "up": 0})[0], "FAIL")


class TestRandom(unittest.TestCase):
    def test_random_entries_held_as_long_on_a_steady_rise_earn_the_rise(self):
        n = 200
        ts = [k * DAY for k in range(n)]
        o = list(100 * 1.01 ** np.arange(n))
        c = list(100 * 1.01 ** np.arange(n) * 1.001)
        real = T.Trade(10, 30, o[10], o[30], 20.0, 0.0, False)
        means = T.random_means([(ts, o, c, [real])], draws=40, seed=1)
        want = 1.01 ** 20 - 1 - 28e-4 - 0.10 * 20 / 365
        self.assertAlmostEqual(float(np.nanmean(means)), want, places=6)        # every window of 20 days earns it
        np.testing.assert_array_equal(means, T.random_means([(ts, o, c, [real])], draws=40, seed=1))
        self.assertEqual(T.share_at_or_above(want + 0.01, means), 0.0)
        self.assertEqual(T.share_at_or_above(want - 0.01, means), 1.0)
        self.assertEqual(T.share_at_or_above(0.0, np.array([np.nan])), 1.0)

    def test_the_draws_are_random_positions_not_the_real_ones(self):
        n = 200
        ts = [k * DAY for k in range(n)]
        o = [100.0] * 100 + [200.0] * 100
        real = T.Trade(10, 30, 100.0, 100.0, 20.0, 0.0, False)           # a flat stretch: its own return is the cost
        means = T.random_means([(ts, o, o, [real])], draws=60, seed=2)
        self.assertGreater(float(np.nanmax(means)), 0.5)                  # some draws span the jump
        self.assertLess(float(np.nanmin(means)), 0.0)                     # some do not
        self.assertEqual(T.share_at_or_above(0.2, np.array([0.1, 0.2])), 0.5)     # at or above, not above

    def test_the_registered_numbers(self):
        self.assertEqual((T.ENTRY_WINDOW, T.EXIT_WINDOW, T.COST_BPS, T.FUNDING_YEAR), (100, 50, 14.0, 0.10))
        self.assertEqual((T.MIN_PF, T.MIN_T, T.MAX_Q, T.MAX_RANDOM_SHARE), (1.5, 3.0, 0.05, 0.05))
        self.assertEqual((T.RANDOM_DRAWS, T.RANDOM_SEED, T.MIN_TRADES, T.MIN_MARKET_TRADES), (2000, 0, 100, 5))


if __name__ == "__main__":
    unittest.main()
