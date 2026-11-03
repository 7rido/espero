"""#69's measurement, on made-up overrides only: none exists, and none will before a sleeve is live."""
import math
import unittest

from espero import opalpha as O

DAY = O.DAY_S


def o(kind="reject", live=0.0, twin=10.0, notional=1000.0, at=0, rule="12"):
    return O.Override(kind, rule, at, notional, live, twin)


class TestScore(unittest.TestCase):
    def test_rejecting_a_winner_costs_and_rejecting_a_loser_earns(self):
        self.assertAlmostEqual(O.alpha_bps(o(live=0.0, twin=10.0)), -100.0)
        self.assertAlmostEqual(O.alpha_bps(o(live=0.0, twin=-5.0)), 50.0)

    def test_a_half_size_keeps_half_the_trade(self):
        self.assertAlmostEqual(O.alpha_bps(o("modify", live=5.0, twin=10.0)), -50.0)

    def test_missing_sides_are_not_comparable(self):
        self.assertIsNone(O.alpha_bps(o(live=None)))
        self.assertIsNone(O.alpha_bps(o(twin=None)))
        self.assertIsNone(O.alpha_bps(o(notional=0.0)))


class TestSummary(unittest.TestCase):
    def test_per_kind_and_overall(self):
        xs = [o("reject", 0.0, 10.0, at=3), o("reject", 0.0, -20.0, at=1), o("exit", 12.0, 2.0, at=2),
              o("silence", 0.0, 4.0, at=4), o("modify", None, 3.0, at=5), o("operator", 5.0, 5.0, at=6)]
        s = O.summary(xs)
        self.assertEqual(s["all"]["n"], 5)
        self.assertAlmostEqual(s["all"]["median_bps"], 0.0)       # -100, -40, 0, 100, 200
        self.assertAlmostEqual(s["all"]["mean_bps"], 32.0)
        self.assertEqual(s["not_comparable"], 1)
        self.assertEqual(s["reject"]["n"], 2)
        self.assertAlmostEqual(s["reject"]["mean_bps"], (-100.0 + 200.0) / 2)
        self.assertAlmostEqual(s["reject"]["dollars"], 10.0)
        self.assertAlmostEqual(s["exit"]["median_bps"], 100.0)
        self.assertAlmostEqual(s["silence_dollars"], -4.0)
        self.assertAlmostEqual(s["all"]["share_positive"], 0.4)
        self.assertEqual(s["delay"]["n"], 0)
        self.assertTrue(math.isnan(s["delay"]["mean_bps"]))
        self.assertTrue(math.isnan(s["exit"]["t_nw"]))           # under three overrides: no t

    def test_the_t_is_newey_west_over_time_order(self):
        xs = [o("reject", 0.0, float(v), at=i) for i, v in enumerate([3, -1, 4, -1, 5, -9, 2, 6])]
        s = O.summary([xs[i] for i in (5, 0, 7, 2, 4, 1, 6, 3)])   # handed over out of order
        from espero.factor_eval import newey_west_t
        want = newey_west_t([-(v / 1000.0) * 1e4 for v in [3, -1, 4, -1, 5, -9, 2, 6]], O.lags(8))
        self.assertAlmostEqual(s["reject"]["t_nw"], want)
        shuffled = newey_west_t([-(v / 1000.0) * 1e4 for v in [-9, 3, 6, 4, 5, -1, 2, -1]], O.lags(8))
        self.assertNotAlmostEqual(want, shuffled)                 # so the order is what the test pins

    def test_an_unknown_kind_is_refused(self):
        with self.assertRaises(ValueError):
            O.summary([o("vibes")])


class TestWhenReported(unittest.TestCase):
    def test_thirty_comparable_overrides_or_a_year(self):
        start = 1_800_000_000
        thirty = [o(at=start + i) for i in range(30)]
        self.assertTrue(O.ready(thirty, start, start + DAY))
        self.assertFalse(O.ready(thirty[:29], start, start + DAY))
        self.assertFalse(O.ready(thirty[:29] + [o(live=None)], start, start + DAY))
        self.assertTrue(O.ready([], start, start + 365 * DAY))
        self.assertFalse(O.ready(thirty, None, start + 400 * DAY))

    def test_lags_follow_fdr_standard(self):
        self.assertEqual([O.lags(n) for n in (0, 30, 100)], [0, 3, 4])

    def test_the_rule_is_the_summary(self):
        self.assertIs(O.rule(), O.summary)


if __name__ == "__main__":
    unittest.main()
