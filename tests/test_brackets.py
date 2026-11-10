"""The bracket simulator on hand-made bars: every number below is worked out by hand."""
import unittest

import numpy as np

from espero import brackets as B

PLAIN = B.Bracket()                                          # half at 1.5R, half at 2.8R, stop to the entry after one


def bars(*rows):
    """(open, high, low, close) rows -> four lists."""
    o, h, low, c = (list(x) for x in zip(*rows))
    return o, h, low, c


class TestOneTrade(unittest.TestCase):
    def test_entry_is_the_next_open_and_a_stop_is_minus_one_r(self):
        o, h, low, c = bars((99, 99, 99, 99), (100, 101, 99.5, 100), (100, 100.5, 97.9, 98))
        t = B.simulate(o, h, low, c, 0, 1, 2.0, PLAIN)
        self.assertEqual((t.entry_i, t.exit_i, t.entry, t.outcome), (1, 2, 100.0, "stop"))
        self.assertAlmostEqual(t.r, -1.0)

    def test_both_targets_half_and_half(self):
        o, h, low, c = bars((0, 0, 0, 0), (100, 103.1, 99.5, 103), (103, 105.7, 102, 105))
        t = B.simulate(o, h, low, c, 0, 1, 2.0, PLAIN)
        self.assertEqual(t.outcome, "target")
        self.assertAlmostEqual(t.r, 0.5 * 1.5 + 0.5 * 2.8)

    def test_after_the_first_target_the_stop_is_the_entry_from_the_next_bar(self):
        o, h, low, c = bars((0, 0, 0, 0), (100, 103.0, 99.0, 102), (102, 102.5, 99.9, 100))
        t = B.simulate(o, h, low, c, 0, 1, 2.0, PLAIN)
        self.assertEqual((t.outcome, t.exit_i), ("breakeven", 2))
        self.assertAlmostEqual(t.r, 0.75)                     # half at +1.5R, half at 0

    def test_a_bar_reaching_stop_and_target_is_a_stop(self):
        o, h, low, c = bars((0, 0, 0, 0), (100, 104, 97, 101))
        t = B.simulate(o, h, low, c, 0, 1, 2.0, PLAIN)
        self.assertEqual(t.outcome, "stop")
        self.assertAlmostEqual(t.r, -1.0)

    def test_a_gap_through_the_stop_fills_at_the_worse_open(self):
        o, h, low, c = bars((0, 0, 0, 0), (100, 100.5, 99, 100), (95, 96, 94, 95))
        t = B.simulate(o, h, low, c, 0, 1, 2.0, PLAIN)
        self.assertAlmostEqual(t.r, -2.5)
        self.assertEqual(t.outcome, "stop")

    def test_a_gap_through_a_target_fills_at_the_target(self):
        o, h, low, c = bars((0, 0, 0, 0), (100, 100.5, 99, 100), (110, 110, 109, 110))
        t = B.simulate(o, h, low, c, 0, 1, 2.0, PLAIN)
        self.assertAlmostEqual(t.r, 0.5 * 1.5 + 0.5 * 2.8)

    def test_a_short_mirrors_a_long(self):
        o, h, low, c = bars((0, 0, 0, 0), (100, 100.5, 96.9, 97), (97, 97.5, 94.3, 95))
        t = B.simulate(o, h, low, c, 0, -1, 2.0, PLAIN)
        self.assertAlmostEqual(t.r, 0.5 * 1.5 + 0.5 * 2.8)
        o, h, low, c = bars((0, 0, 0, 0), (100, 102.0, 99, 101))
        self.assertAlmostEqual(B.simulate(o, h, low, c, 0, -1, 2.0, PLAIN).r, -1.0)

    def test_the_time_stop_and_the_end_of_the_day(self):
        rows = [(0, 0, 0, 0), (100, 100.5, 99.5, 100.2), (100.2, 100.6, 99.8, 100.4), (100.4, 100.6, 99.9, 100.5)]
        o, h, low, c = bars(*rows)
        t = B.simulate(o, h, low, c, 0, 1, 2.0, B.Bracket(max_bars=2))
        self.assertEqual((t.outcome, t.exit_i), ("time", 2))
        self.assertAlmostEqual(t.r, 0.2)
        day = ["a", "a", "a", "b"]
        t = B.simulate(o, h, low, c, 0, 1, 2.0, B.Bracket(flat_at_day_end=True), day)
        self.assertEqual((t.outcome, t.exit_i), ("day end", 2))
        t = B.simulate(o, h, low, c, 0, 1, 2.0, PLAIN, day)
        self.assertEqual((t.outcome, t.exit_i), ("end of data", 3))
        self.assertAlmostEqual(t.r, 0.25)
        t = B.simulate(o, h, low, c, 2, 1, 2.0, B.Bracket(flat_at_day_end=True), day)
        self.assertEqual((t.outcome, t.exit_i), ("day end", 3))                 # the data's last bar ends its day

    def test_costs_on_the_entry_and_on_every_exit(self):
        o, h, low, c = bars((0, 0, 0, 0), (100, 103.1, 99.5, 103), (103, 105.7, 102, 105))
        t = B.simulate(o, h, low, c, 0, 1, 2.0, B.Bracket(cost_bps=10))
        paid = (100 + 0.5 * 103 + 0.5 * 105.6) * 10 / 1e4
        self.assertAlmostEqual(t.r, 0.5 * 1.5 + 0.5 * 2.8 - paid / 2.0)

    def test_no_next_bar_no_trade_and_bad_input_refused(self):
        self.assertIsNone(B.simulate([1.0], [1.0], [1.0], [1.0], 0, 1, 1.0, PLAIN))
        with self.assertRaises(ValueError):
            B.simulate([1.0, 1.0], [1.0] * 2, [1.0] * 2, [1.0] * 2, 0, 0, 1.0, PLAIN)
        with self.assertRaises(ValueError):
            B.simulate([1.0, 1.0], [1.0] * 2, [1.0] * 2, [1.0] * 2, 0, 1, 0.0, PLAIN)
        for bad in (dict(targets=((2.0, 0.5), (1.0, 0.5))), dict(targets=((1.0, 0.7), (2.0, 0.5))),
                    dict(targets=((1.0, 0.0),)), dict(max_bars=0), dict(cost_bps=-1)):
            with self.assertRaises(ValueError):
                B.Bracket(**bad)

    def test_a_single_full_target_and_no_breakeven(self):
        o, h, low, c = bars((0, 0, 0, 0), (100, 103.0, 99.0, 102), (102, 102.5, 99.9, 100), (100, 100, 97.5, 98))
        t = B.simulate(o, h, low, c, 0, 1, 2.0, B.Bracket(targets=((1.5, 0.5),), breakeven_after=None))
        self.assertEqual(t.outcome, "stop")
        self.assertAlmostEqual(t.r, 0.75 - 0.5)


class TestMany(unittest.TestCase):
    def test_one_at_a_time(self):
        rows = [(100, 100.5, 99.5, 100)] * 3 + [(100, 100.5, 97.5, 98)] + [(98, 98.5, 97.5, 98)] * 3
        o, h, low, c = bars(*rows)
        got = B.run(o, h, low, c, [(2, 1, 2.0), (0, 1, 2.0), (3, 1, 2.0), (4, 1, 2.0)], PLAIN)
        self.assertEqual([t.signal_i for t in got], [0, 4])  # 2 and 3 fall inside the first trade's bars

    def test_summary(self):
        s = B.summary([2.0, -1.0, -1.0, 1.0])
        self.assertEqual((s.n, s.win_rate, s.total_r), (4, 0.5, 1.0))
        self.assertAlmostEqual(s.mean_r, 0.25)
        self.assertAlmostEqual(s.profit_factor, 1.5)
        self.assertAlmostEqual(s.t, 0.25 / (np.std([2.0, -1.0, -1.0, 1.0], ddof=1) / 2))
        self.assertIsNone(B.summary([1.0, 2.0]).profit_factor)
        self.assertIsNone(B.summary([1.0]).t)
        self.assertEqual(B.summary([]).n, 0)
        self.assertEqual(B.summary([0.0, 1.0]).win_rate, 0.5)               # flat is not a win


class TestRandom(unittest.TestCase):
    def test_random_entries_on_a_steady_rise_earn_what_the_rise_gives(self):
        n = 400
        close = 100 * 1.002 ** np.arange(n)
        o, c = np.r_[close[0], close[:-1]], close
        h, low = np.maximum(o, c) * 1.0005, np.minimum(o, c) * 0.9995
        real = B.simulate(o, h, low, c, 10, 1, 1.0, PLAIN)
        means = B.random_means([(o, h, low, c, None, [real])], PLAIN, draws=50, seed=1)
        self.assertEqual(means.shape, (50,))
        self.assertGreater(np.nanmedian(means), 1.5)          # a long on a rise mostly reaches its targets
        again = B.random_means([(o, h, low, c, None, [real])], PLAIN, draws=50, seed=1)
        np.testing.assert_array_equal(means, again)            # seeded
        gap, share = B.beats_random(float(np.nanmedian(means)) + 0.5, means)
        self.assertAlmostEqual(gap, 0.5)
        self.assertEqual(share, 0.0)
        self.assertEqual(B.beats_random(-10.0, means)[1], 1.0)

    def test_a_random_draw_keeps_the_side_and_the_stop_as_a_fraction_of_price(self):
        o = [100.0, 100.0, 200.0, 200.0, 200.0]
        h, low, c = [x * 1.01 for x in o], [x * 0.99 for x in o], list(o)
        real = B.Trade(-1, 0, 1, 1, 100.0, 2.0, 0.0, "stop")
        seen = []
        orig = B.simulate

        def spy(o_, h_, l_, c_, i, side, risk, b, day=None):
            seen.append((side, round(risk / o_[i + 1], 6)))
            return orig(o_, h_, l_, c_, i, side, risk, b, day)

        B.simulate = spy
        try:
            B.random_means([(o, h, low, c, None, [real])], PLAIN, draws=20, seed=0)
        finally:
            B.simulate = orig
        self.assertEqual(set(seen), {(-1, 0.02)})


if __name__ == "__main__":
    unittest.main()
