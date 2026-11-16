"""#80's weekly funding spread on a hand-made nine-market world: every number below is worked out by hand."""
import math
import unittest

import numpy as np

from espero import fundspread as F

W = F.WEEK_S
T0 = 10 * W                                   # a Monday, in seconds; only arithmetic on it is used
NAMES = list("ABCDEFGHI")
LOW, MID, HIGH = NAMES[:3], NAMES[3:6], NAMES[6:]


def rows(first, last, rate):
    """One funding row an hour in [first, last) at `rate`."""
    ts = list(range(first, last, 3600))
    return ts, [rate] * len(ts)


def world(weeks=3, signal=None, settle=None):
    """Funding: the week before each Monday at `signal[m]`, the week after at `settle[m]`. Prices: candles at every
    Monday; the first week's longs rise 1, 2, 3% and its shorts fall 1, 2, 3%."""
    signal = signal or {m: 0.00001 * (i + 1) for i, m in enumerate(NAMES)}
    settle = settle or {m: 0.001 if m in LOW else 0.003 if m in HIGH else 0.002 for m in NAMES}
    funding, prices = {}, {}
    for m in NAMES:
        ts, rs = [], []
        for w in range(-1, weeks):
            a, b = rows(T0 + w * W, T0 + (w + 1) * W, signal[m] if w < 0 else settle[m])
            ts += a
            rs += b
        funding[m] = (ts, rs)
        prices[m] = {T0 + w * W: 100.0 for w in range(weeks + 1)}
    for m, r in zip(LOW, (0.01, 0.02, 0.03)):
        prices[m][T0 + W] = 100.0 * (1 + r)
    for m, r in zip(HIGH, (-0.01, -0.02, -0.03)):
        prices[m][T0 + W] = 100.0 * (1 + r)
    return funding, prices


class TestPieces(unittest.TestCase):
    def test_the_signal_is_the_mean_over_the_week_before_and_needs_144_rows(self):
        ts, rs = rows(T0 - W, T0, 0.0001)
        self.assertAlmostEqual(F.signal(ts, rs, T0), 0.0001)
        self.assertIsNone(F.signal(ts[:143], rs[:143], T0))
        self.assertAlmostEqual(F.signal(ts[:144], rs[:144], T0), 0.0001)
        later, lr = rows(T0, T0 + W, 0.5)
        self.assertAlmostEqual(F.signal(ts + later, rs + lr, T0), 0.0001)           # rows from t on are not the signal
        before, br = rows(T0 - 2 * W, T0 - W, 0.5)
        self.assertAlmostEqual(F.signal(before + ts, br + rs, T0), 0.0001)          # nor the week before that

    def test_settled_funding_is_the_sum_over_the_week_ahead(self):
        ts, rs = rows(T0 - W, T0 + 2 * W, 0.0001)
        self.assertAlmostEqual(F.settled(ts, rs, T0), 168 * 0.0001)

    def test_the_lowest_third_long_the_highest_short_ties_by_name_and_nine_needed(self):
        sig = {m: i for i, m in enumerate(NAMES)}
        self.assertEqual(F.split(sig), (("A", "B", "C"), ("G", "H", "I")))
        self.assertIsNone(F.split({m: 0.0 for m in NAMES[:8]}))
        flat = F.split({m: 1.0 for m in NAMES})
        self.assertEqual(flat, (("A", "B", "C"), ("G", "H", "I")))
        twelve = F.split({f"M{i:02d}": i for i in range(12)})
        self.assertEqual((len(twelve[0]), len(twelve[1])), (4, 4))
        ten = F.split({f"M{i:02d}": i for i in range(10)})
        self.assertEqual((len(ten[0]), len(ten[1])), (3, 3))

    def test_weights_and_turnover(self):
        w = F.weights(("A", "B"), ("C", "D"))
        self.assertEqual(w, {"A": 0.25, "B": 0.25, "C": -0.25, "D": -0.25})
        self.assertAlmostEqual(F.turnover({}, w), 1.0)
        self.assertAlmostEqual(F.turnover(w, w), 0.0)
        new = F.weights(("A", "E"), ("C", "D"))
        self.assertAlmostEqual(F.turnover(w, new), 0.5)                 # B out, E in
        self.assertAlmostEqual(F.turnover(w, {}), 1.0)

    def test_price_and_funding_components(self):
        p0 = {m: 100.0 for m in "ABCD"}
        p1 = {"A": 102.0, "B": 104.0, "C": 98.0, "D": 96.0}
        fund = {"A": 0.001, "B": 0.003, "C": 0.004, "D": 0.006}
        price, pay = F.gross_parts(("A", "B"), ("C", "D"), p0, p1, fund)
        self.assertAlmostEqual(price, 0.5 * (0.03 - (-0.03)))
        self.assertAlmostEqual(pay, 0.5 * (0.005 - 0.002))


class TestTheRun(unittest.TestCase):
    def test_the_first_week_by_hand(self):
        funding, prices = world()
        got = F.run(funding, prices, [T0])
        self.assertEqual(len(got), 1)
        wk = got[0]
        self.assertEqual((wk.n, wk.long, wk.short), (9, ("A", "B", "C"), ("G", "H", "I")))
        self.assertAlmostEqual(wk.price, 0.5 * (0.02 - (-0.02)))                  # 0.02
        self.assertAlmostEqual(wk.fund, 0.5 * (0.003 * 168 - 0.001 * 168))        # 168 hourly rows settle in the week
        self.assertAlmostEqual(wk.gross, wk.price + wk.fund)
        self.assertAlmostEqual(wk.turnover, 1.0)
        self.assertAlmostEqual(wk.net, wk.gross - 14e-4)

    def test_a_market_that_stays_costs_nothing_and_one_that_swaps_costs_its_weight_twice(self):
        funding, prices = world(weeks=3)
        for m in NAMES:
            prices[m][T0 + 2 * W] = prices[m][T0 + W]
            prices[m][T0 + 3 * W] = prices[m][T0 + 2 * W]
        got = F.run(funding, prices, [T0, T0 + W, T0 + 2 * W])
        self.assertEqual([round(g.turnover, 12) for g in got][:2], [1.0, 0.0])    # a sum of weights: 1 to rounding
        self.assertAlmostEqual(got[1].net, got[1].gross)
        # in the second week D's funding was the lowest of all, so D is long and C is not
        funding2, prices2 = world(weeks=3)
        funding2["D"] = (funding2["D"][0], [r if not (T0 <= t < T0 + W) else -1.0 for t, r in zip(*funding2["D"])])
        two = F.run(funding2, prices2, [T0, T0 + W])
        self.assertEqual((two[0].long, two[1].long), (("A", "B", "C"), ("D", "A", "B")))
        self.assertEqual(two[1].short, ("G", "H", "I"))
        self.assertAlmostEqual(two[1].turnover, (0.5 / 3) * 2)         # C leaves its leg, D enters it

    def test_too_few_markets_no_position_and_the_book_starts_again(self):
        funding, prices = world(weeks=3)
        for m in NAMES[:2]:
            del prices[m][T0 + W]                                      # eight markets have both candles in week one
        got = F.run(funding, prices, [T0, T0 + W, T0 + 2 * W])
        self.assertEqual([g.t for g in got], [T0 + 2 * W])             # seven markets in the first two weeks
        self.assertAlmostEqual(got[0].turnover, 1.0)                   # the book is built whole when it starts

    def test_after_a_week_with_no_position_the_whole_book_is_traded_again(self):
        funding, prices = world(weeks=4)
        for m in NAMES[:2]:
            del prices[m][T0 + 2 * W]                                   # A and B have no candle at the third Monday
        got = F.run(funding, prices, [T0, T0 + W, T0 + 2 * W, T0 + 3 * W])
        self.assertEqual([g.t for g in got], [T0, T0 + 3 * W])
        self.assertEqual([round(g.turnover, 12) for g in got], [1.0, 1.0])   # not 0.0: the book was closed in between

    def test_a_market_left_out_is_not_in_the_legs(self):
        funding, prices = world()
        self.assertEqual(F.run(funding, prices, [T0], skip="A"), [])    # eight left: below nine
        self.assertNotIn("B", F.eligible(funding, prices, T0, skip="B"))
        self.assertIn("B", F.eligible(funding, prices, T0))


class TestRandom(unittest.TestCase):
    def test_random_legs_on_a_world_with_no_information_average_to_the_gross_mean_of_zero_drift(self):
        funding, prices = world()
        weeks = F.run(funding, prices, [T0])
        means = F.random_means(funding, prices, weeks, draws=300, seed=1)
        self.assertEqual(means.shape, (300,))
        np.testing.assert_array_equal(means, F.random_means(funding, prices, weeks, draws=300, seed=1))
        # the rule's own legs are the best assignment: its gross beats every random one
        self.assertEqual(F.share_at_or_above(weeks[0].gross, means), float(np.mean(means >= weeks[0].gross)))
        self.assertLess(float(np.mean(means >= weeks[0].gross)), 0.05)
        self.assertGreater(float(np.nanmedian(means)), -0.03)

    def test_a_draw_is_the_mean_gross_of_random_legs_replayed_by_hand(self):
        funding, prices = world(weeks=2)
        weeks = F.run(funding, prices, [T0, T0 + W])
        rng = np.random.default_rng(7)
        total = 0.0
        for wk in weeks:
            order = rng.permutation(9)                                  # the markets in name order
            long = [NAMES[i] for i in order[:3]]
            short = [NAMES[i] for i in order[3:6]]
            p0 = {m: prices[m][wk.t] for m in NAMES}
            p1 = {m: prices[m][wk.t + W] for m in NAMES}
            fund = {m: F.settled(*funding[m], wk.t) for m in NAMES}
            a, b = F.gross_parts(long, short, p0, p1, fund)
            total += a + b
        got = F.random_means(funding, prices, weeks, draws=1, seed=7)
        self.assertAlmostEqual(float(got[0]), total / 2)
        self.assertGreater(float(np.nanmax(F.random_means(funding, prices, weeks, draws=50, seed=3))),
                           float(np.nanmin(F.random_means(funding, prices, weeks, draws=50, seed=3))))

    def test_the_share_counts_ties_as_at_or_above(self):
        self.assertEqual(F.share_at_or_above(0.2, np.array([0.1, 0.2])), 0.5)
        self.assertEqual(F.share_at_or_above(0.0, np.array([np.nan])), 1.0)


class TestCriteria(unittest.TestCase):
    def test_pieces(self):
        self.assertAlmostEqual(F.profit_factor([0.3, -0.1, -0.1, 0.0]), 1.5)
        self.assertIsNone(F.profit_factor([0.1]))
        self.assertEqual(F.halves([1.0, 2.0, 3.0, -1.0, -2.0]), (2.0, -1.5))
        self.assertAlmostEqual(F.two_sided_p(-3.0), math.erfc(3 / math.sqrt(2)))

    def test_each_criterion(self):
        good = dict(n=50, pf=1.6, mean=0.01, t=3.2, q=0.01, share=0.01, h1=0.01, h2=0.02, loo_min=0.005)
        self.assertEqual(F.verdict(**good), ("PASS", []))
        self.assertEqual(F.verdict(**{**good, "n": 39})[0], "INCONCLUSIVE")
        self.assertEqual(F.verdict(**{**good, "n": 40})[0], "PASS")
        for key, bad in (("pf", 1.49), ("pf", None), ("mean", 0.0), ("t", 2.99), ("t", None), ("q", 0.05), ("q", None),
                         ("share", 0.05), ("h1", 0.0), ("h2", -0.1), ("loo_min", 0.0)):
            got, missed = F.verdict(**{**good, key: bad})
            self.assertEqual((got, len(missed)), ("FAIL", 1), (key, bad))
        self.assertEqual(F.verdict(**{**good, "pf": 1.5, "t": 3.0})[0], "PASS")

    def test_the_registered_numbers(self):
        self.assertEqual((F.WEEK_S, F.MIN_ROWS, F.MIN_MARKETS, F.COST_BPS), (604800, 144, 9, 14.0))
        self.assertEqual((F.MIN_PF, F.MIN_T, F.MAX_Q, F.MAX_RANDOM_SHARE), (1.5, 3.0, 0.05, 0.05))
        self.assertEqual((F.RANDOM_DRAWS, F.RANDOM_SEED, F.MIN_WEEKS), (2000, 0, 40))


if __name__ == "__main__":
    unittest.main()
