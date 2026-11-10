"""#75's rule on hand-built bars: a fall to a swing low, a rally to a swing high, a pullback through the proximal
line, then a rally to the targets. Every index below is set by the path."""
import math
import unittest

import pandas as pd

from espero import brackets as B
from espero import dealrange as D
from espero.indicators import atr as atr_


def path(closes, lows=None, highs=None):
    """Bars from closes: each opens at the last close, high and low 0.1 beyond (so neighbours tie, which is no
    swing); `lows` and `highs` set a bar's extreme, to make it one."""
    o = [closes[0]] + list(closes[:-1])
    h = [max(a, b) + 0.1 for a, b in zip(o, closes)]
    low = [min(a, b) - 0.1 for a, b in zip(o, closes)]
    for i, v in (lows or {}).items():
        low[i] = v
    for i, v in (highs or {}).items():
        h[i] = v
    return o, h, low, list(closes)


DOWN = [110.0 - k for k in range(10)]                    # bars 0-9, down bars to 101
LOW_BAR = [100.2]                                         # bar 10: a down bar from 101, its low set to 99.8
RALLY = [101.4 + 1.2 * k for k in range(10)]              # bars 11-20: up to 112.2, bar 20's high set to 112.5
PULL = [111.0, 110.0, 109.5, 109.0, 108.6]                # bars 21-25: down, still above the line; 25 arms
DROP = [104.0, 101.0]                                     # bars 26-27: 27 trades through the line (101.1)
UP = [103.0, 105.0, 107.0, 108.0, 109.0, 110.0]           # bars 28-33: both targets


SWINGS = dict(lows={10: 99.8}, highs={20: 112.5})


def base():
    return path(DOWN + LOW_BAR + RALLY + PULL + DROP + UP, **SWINGS)


class TestSwings(unittest.TestCase):
    def test_strict_with_five_bars_each_side(self):
        low = [5, 5, 5, 5, 5, 1, 5, 5, 5, 5, 5]
        self.assertTrue(D.swing_low(low, 5))
        self.assertFalse(D.swing_low(low[:10], 5))                  # only four bars after it
        self.assertFalse(D.swing_low([5, 5, 5, 5, 5, 1, 1, 5, 5, 5, 5, 5], 5))   # a tie is not a swing
        self.assertFalse(D.swing_low(low, 4))
        high = [1, 1, 1, 1, 1, 9, 1, 1, 1, 1, 1]
        self.assertTrue(D.swing_high(high, 5))
        self.assertFalse(D.swing_high([1, 1, 1, 1, 1, 9, 9, 1, 1, 1, 1, 1], 5))
        self.assertFalse(D.swing_high(high[1:], 4))                 # only four bars before it

    def test_the_proximal_line_is_the_last_down_bar_within_ten(self):
        o, c, h = [10.0] * 12, [11.0] * 12, [12.0 + k for k in range(12)]
        self.assertIsNone(D.proximal(o, h, c, 11))
        c[1] = 9.0
        self.assertEqual(D.proximal(o, h, c, 11), 13.0)             # bar 1: ten back from 11
        c[0], c[1] = 9.0, 11.0
        self.assertIsNone(D.proximal(o, h, c, 11))                  # bar 0 is eleven back
        c[11] = 9.0
        self.assertEqual(D.proximal(o, h, c, 11), 23.0)             # the low's own bar counts
        c[11], c[1] = 10.0, 9.0
        self.assertEqual(D.proximal(o, h, c, 11), 13.0)             # a flat bar is not a down bar


class TestTheRule(unittest.TestCase):
    def test_the_registered_path(self):
        o, h, low, c = base()
        orders, trades = D.orders_and_trades(o, h, low, c)
        self.assertEqual(len(orders), 1)
        od = orders[0]
        atr = atr_(pd.DataFrame({"high": h, "low": low, "close": c})).to_numpy()
        self.assertEqual((od.armed_i, od.line, od.range_low, od.range_high), (25, 101.1, 99.8, 112.5))
        self.assertAlmostEqual(od.stop, 99.8 - 0.1 * atr[25])
        self.assertEqual(len(trades), 1)
        t = trades[0]
        self.assertEqual((t.signal_i, t.entry_i, t.entry, t.outcome), (25, 27, 101.1, "target"))
        want = B.simulate_limit(o, h, low, c, 27, 101.1, 1, 101.1 - od.stop, D.BRACKET, signal_i=25)
        self.assertAlmostEqual(t.r, want.r)
        self.assertAlmostEqual(t.risk, 101.1 - od.stop)

    def test_no_order_when_the_line_is_above_the_midpoint(self):
        small = [100.3 + 0.1 * k for k in range(10)]            # a rally to 101.4: the midpoint 100.6 is under 101.1
        o, h, low, c = path(DOWN + LOW_BAR + small + [101.1, 101.0, 100.9, 100.8, 100.7] + DROP + UP,
                            lows={10: 99.8}, highs={20: 101.4})
        self.assertEqual(D.orders_and_trades(o, h, low, c), ([], []))

    def test_no_order_when_the_line_is_above_the_midpoint_and_the_price_still_above_it(self):
        rally = [100.4 + 0.2 * k for k in range(10)]               # to 102.2: the midpoint 101.075 is under 101.1
        o, h, low, c = path(DOWN + LOW_BAR + rally + [102.0, 101.9, 101.8, 101.7, 101.6] + DROP + UP,
                            lows={10: 99.8}, highs={20: 102.35})
        self.assertEqual(D.orders_and_trades(o, h, low, c), ([], []))

    def test_a_bar_both_swing_low_and_swing_high_makes_no_range(self):
        flat = [100.0] * 9
        o, h, low, c = path(flat + [99.95, 100.0, 100.2, 100.4, 100.6, 100.8, 101.0, 101.2], lows={10: 99.0},
                            highs={10: 103.0})
        self.assertTrue(D.swing_low(low, 10) and D.swing_high(h, 10))
        self.assertEqual(D.orders_and_trades(o, h, low, c), ([], []))

    def test_a_later_swing_low_cancels_with_nothing_to_arm_again(self):
        dip = [106.0, 105.0, 106.0, 107.0, 108.0, 109.0, 110.0]      # bars 26-32: a swing low at 27, known at 32
        o, h, low, c = path(DOWN + LOW_BAR + RALLY + PULL + dip + DROP + UP, lows={10: 99.8, 27: 104.5},
                            highs={20: 112.5})
        orders, trades = D.orders_and_trades(o, h, low, c)
        self.assertEqual([x.armed_i for x in orders], [25])
        self.assertEqual(trades, [])                                # the drop through 101.1 at bar 34 finds no order

    def test_the_registered_numbers(self):
        self.assertEqual((D.SWING, D.PROX_BACK, D.STOP_ATR, D.ATR_PERIOD, D.COST_BPS), (5, 10, 0.1, 14, 14.0))
        self.assertEqual(D.BRACKET, B.Bracket(targets=((1.5, 0.5), (2.8, 0.5)), breakeven_after=1, cost_bps=14.0))
        self.assertEqual((D.RANDOM_DRAWS, D.RANDOM_SEED, D.MIN_TRADES, D.MIN_MARKET_TRADES), (2000, 0, 100, 5))

    def test_no_order_when_the_price_is_already_through_the_line(self):
        o, h, low, c = path(DOWN + LOW_BAR + RALLY + [111.0, 110.0, 109.5, 109.0, 101.0] + DROP + UP, **SWINGS)
        orders, trades = D.orders_and_trades(o, h, low, c)
        self.assertEqual((orders, trades), ([], []))

    def test_no_fill_on_the_arming_bar_and_a_touch_is_not_a_fill(self):
        touch = [104.0, 101.2]                                   # bar 27 down to 101.1, bar 28 opening at 101.2
        o, h, low, c = path(DOWN + LOW_BAR + RALLY + PULL + touch + UP, lows={10: 99.8, 25: 100.5, 27: 101.1},
                            highs={20: 112.5})
        orders, trades = D.orders_and_trades(o, h, low, c)
        self.assertEqual(len(orders), 1)
        self.assertEqual(trades, [])                              # bar 25 armed it; bar 27 only touched the line

    def test_a_later_swing_cancels_and_a_new_range_arms_again(self):
        chop = [109.0, 110.0, 113.0, 110.0, 109.0, 108.8, 108.6, 108.4]   # bars 26-33: a new high at bar 28
        o, h, low, c = path(DOWN + LOW_BAR + RALLY + PULL + chop + DROP + UP, lows={10: 99.8},
                            highs={20: 112.5, 28: 113.4})
        orders, trades = D.orders_and_trades(o, h, low, c)
        self.assertEqual([x.armed_i for x in orders], [25, 33])
        self.assertEqual(orders[1].range_high, 113.4)
        self.assertEqual([t.signal_i for t in trades], [33])        # the first order never filled

    def test_one_position_per_market(self):
        o, h, low, c = path((DOWN + LOW_BAR + RALLY + PULL + DROP + UP) * 2, lows={10: 99.8, 44: 99.8},
                            highs={20: 112.5, 54: 112.5})
        far = B.Bracket(targets=((50.0, 1.0),), cost_bps=0)          # the first trade lasts to the end
        orders, trades = D.orders_and_trades(o, h, low, c, b=far)
        self.assertEqual(len(trades), 1)
        self.assertEqual(trades[0].outcome, "end of data")
        self.assertGreaterEqual(len(orders), 2)                     # the second was armed, its fill cancelled
        orders, trades = D.orders_and_trades(o, h, low, c)
        self.assertEqual(len(trades), 2)                            # with the registered bracket, both trade

    def test_a_bar_that_fills_and_closes_under_the_range_low_is_a_trade(self):
        o, h, low, c = path(DOWN + LOW_BAR + RALLY + PULL + [104.0, 99.0, 99.0], **SWINGS)
        orders, trades = D.orders_and_trades(o, h, low, c)
        self.assertEqual(len(trades), 1)
        self.assertEqual((trades[0].entry_i, trades[0].outcome), (27, "stop"))
        self.assertAlmostEqual(trades[0].r, -1.0 - D.COST_BPS / 1e4 * (101.1 + orders[0].stop) / trades[0].risk)


class TestCriteria(unittest.TestCase):
    def test_the_t_is_clustered_by_entry_day(self):
        t1, g1 = D.clustered_t([1.0, -0.5, 2.0, -1.0], ["a", "b", "c", "d"])
        t2, g2 = D.clustered_t([1.0, 1.0, -1.0, -1.0, 2.0, 2.0], ["a", "a", "b", "b", "c", "c"])
        self.assertEqual((g1, g2), (4, 3))
        rs = [1.0, -0.5, 2.0, -1.0]
        mean = sum(rs) / 4
        se = math.sqrt(sum((r - mean) ** 2 for r in rs) / 16 * 4 / 3)
        self.assertAlmostEqual(t1, mean / se)
        rs = [1.0, 1.0, -1.0, -1.0, 2.0, 2.0]
        mean = sum(rs) / 6
        se = math.sqrt(sum((2 * (r - mean)) ** 2 for r in (1.0, -1.0, 2.0)) / 36 * 3 / 2)
        self.assertAlmostEqual(t2, mean / se)
        self.assertEqual(D.clustered_t([1.0], ["a"]), (None, 1))
        self.assertEqual(D.clustered_t([1.0, 2.0], ["a", "a"]), (None, 1))

    def test_the_p_value_by_number_of_days(self):
        self.assertAlmostEqual(D.two_sided_p(2.0, 11), 0.0734, places=4)
        self.assertAlmostEqual(D.two_sided_p(2.228, 11), 0.05, places=3)
        self.assertAlmostEqual(D.two_sided_p(3.0, 6), 0.0301, places=4)
        self.assertAlmostEqual(D.two_sided_p(-2.0, 11), 0.0734, places=4)
        self.assertAlmostEqual(D.two_sided_p(1.96, 101), 0.05, places=3)
        self.assertGreater(D.two_sided_p(1.96, 100), 0.05)           # Student's t up to 100 days

    def test_halves_and_breadth(self):
        self.assertEqual(D.halves([1.0, 2.0, 3.0, -1.0, -2.0]), (2.0, -1.5))
        self.assertEqual(D.breadth({"A": [1.0] * 5, "B": [-1.0] * 5, "C": [1.0] * 4, "D": [0.5] * 6}), (2, 3))

    def test_the_verdict(self):
        good = dict(n=300, pf=1.6, mean=0.3, t=3.2, q=0.01, random_share=0.01, h1=0.2, h2=0.1, up=10, counted=19)
        self.assertEqual(D.verdict(**good), ("PASS", []))
        self.assertEqual(D.verdict(**{**good, "n": 99})[0], "INCONCLUSIVE")
        for key, bad in (("pf", 1.49), ("pf", None), ("t", 2.99), ("q", 0.05), ("mean", 0.0), ("random_share", 0.05),
                         ("h1", 0.0), ("h2", -0.1), ("up", 9), ("counted", 0)):
            got, missed = D.verdict(**{**good, key: bad, **({"up": 0} if key == "counted" else {})})
            self.assertEqual((got, len(missed)), ("FAIL", 1), key)
        self.assertEqual(D.verdict(**{**good, "pf": 1.5})[0], "PASS")
        self.assertEqual(D.verdict(**{**good, "t": 3.0})[0], "PASS")
        self.assertEqual(D.verdict(**{**good, "up": 10, "counted": 20})[0], "FAIL")      # half is not more than half


if __name__ == "__main__":
    unittest.main()
