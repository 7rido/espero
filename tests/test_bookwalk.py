"""#51's book walk: the arithmetic and the registered verdict order."""
import unittest
import warnings

import numpy as np
import pandas as pd

from espero import bookwalk as bw


def book(prices, amounts):
    return np.array([prices], dtype=float), np.array([amounts], dtype=float)


class WalkTests(unittest.TestCase):
    def test_small_order_fills_at_the_best_price(self):
        px, qty = book([101.0, 102.0], [100.0, 100.0])
        cost = bw.walk(px, qty, np.array([100.0]), 1_000, "buy")
        self.assertAlmostEqual(cost[0], 100.0)

    def test_order_walks_to_the_second_level_at_its_average_fill(self):
        px, qty = book([100.0, 200.0], [1.0, 1.0])
        # $100 buys 1.0 at 100, $100 buys 0.5 at 200: 1.5 for $200, an average of 133.33
        cost = bw.walk(px, qty, np.array([100.0]), 200, "buy")
        self.assertAlmostEqual(cost[0], (200 / 1.5 / 100 - 1) * 1e4)

    def test_sell_cost_is_positive_below_mid(self):
        px, qty = book([99.0, 98.0], [100.0, 100.0])
        cost = bw.walk(px, qty, np.array([100.0]), 1_000, "sell")
        self.assertAlmostEqual(cost[0], 100.0)

    def test_order_exactly_the_book_size_fills(self):
        px, qty = book([100.0, 100.0], [1.0, 1.0])
        self.assertTrue(np.isfinite(bw.walk(px, qty, np.array([100.0]), 200, "buy")[0]))

    def test_order_larger_than_the_book_has_no_cost(self):
        px, qty = book([100.0, 100.0], [1.0, 1.0])
        self.assertTrue(np.isnan(bw.walk(px, qty, np.array([100.0]), 201, "buy")[0]))

    def test_missing_levels_count_as_no_depth(self):
        px, qty = book([100.0, np.nan], [1.0, np.nan])
        self.assertAlmostEqual(bw.walk(px, qty, np.array([100.0]), 50, "buy")[0], 0.0)
        self.assertTrue(np.isnan(bw.walk(px, qty, np.array([100.0]), 101, "buy")[0]))

    def test_unknown_side_is_refused(self):
        px, qty = book([100.0], [1.0])
        with self.assertRaises(ValueError):
            bw.walk(px, qty, np.array([100.0]), 50, "hold")


class SnapshotTests(unittest.TestCase):
    def test_crossed_locked_and_one_sided_snapshots_are_not_valid(self):
        ask = np.array([101.0, 100.0, 99.0, np.nan, 101.0])
        bid = np.array([100.0, 100.0, 100.0, 100.0, np.nan])
        self.assertEqual(list(bw.valid_snapshots(ask, bid)), [True, False, False, False, False])

    def test_coin_day_averages_sides_and_counts_unfillable_over_both(self):
        asks_px = np.array([[100.1], [100.1]])
        asks_qty = np.array([[1000.0], [1.0]])
        bids_px = np.array([[99.9], [99.9]])
        bids_qty = np.array([[1000.0], [1000.0]])
        out = bw.coin_day(asks_px, asks_qty, bids_px, bids_qty, sizes=(1_000,))[1_000]
        self.assertAlmostEqual(out["unfillable"], 0.25)
        self.assertAlmostEqual(out["cost"], 10.0, places=6)

    def test_a_side_that_never_fills_gives_no_cost(self):
        asks_px, asks_qty = np.array([[100.1]]), np.array([[1.0]])
        bids_px, bids_qty = np.array([[99.9]]), np.array([[1000.0]])
        with warnings.catch_warnings():
            warnings.simplefilter("error")  # no mean of an empty side
            out = bw.coin_day(asks_px, asks_qty, bids_px, bids_qty, sizes=(1_000,))[1_000]
        self.assertTrue(np.isnan(out["cost"]))
        self.assertAlmostEqual(out["unfillable"], 0.5)


class VerdictTests(unittest.TestCase):
    def test_round_trip_is_two_legs_of_fee_and_cost(self):
        self.assertAlmostEqual(bw.round_trip(1.0, 4.5), 11.0)

    def test_upper_end_at_exactly_the_hurdle_is_covered(self):
        self.assertEqual(bw.verdict(1.0, 4.5, 0.0, 20, 4.5), "COVERED")

    def test_lower_end_above_the_hurdle_is_not_covered(self):
        self.assertEqual(bw.verdict(4.6, 6.0, 0.0, 20, 4.5), "NOT COVERED")

    def test_interval_spanning_the_hurdle_is_unknown(self):
        self.assertEqual(bw.verdict(4.0, 5.0, 0.0, 20, 4.5), "UNKNOWN")

    def test_unfillable_share_overrides_a_cheap_cost(self):
        self.assertEqual(bw.verdict(0.1, 0.2, 0.051, 20, 4.5), "UNKNOWN")
        self.assertEqual(bw.verdict(0.1, 0.2, 0.05, 20, 4.5), "COVERED")

    def test_too_few_days_overrides_a_cheap_cost(self):
        self.assertEqual(bw.verdict(0.1, 0.2, 0.0, 9, 4.5), "UNKNOWN")
        self.assertEqual(bw.verdict(0.1, 0.2, 0.0, 10, 4.5), "COVERED")

    def test_unfillable_share_overrides_an_expensive_cost(self):
        self.assertEqual(bw.verdict(9.0, 10.0, 0.5, 20, 4.5), "UNKNOWN")


class SummaryTests(unittest.TestCase):
    def test_bootstrap_is_seeded_and_brackets_the_mean(self):
        days = np.arange(1.0, 23.0)
        self.assertEqual(bw.bootstrap_ci(days), bw.bootstrap_ci(days))
        low, high = bw.bootstrap_ci(days)
        self.assertLess(low, days.mean())
        self.assertGreater(high, days.mean())

    def test_summary_ignores_days_without_cost_but_counts_their_unfillable_share(self):
        rows = [{"coin": "A", "usd": 1_000, "cost": 1.0, "p95": 2.0, "unfillable": 0.0} for _ in range(11)]
        rows.append({"coin": "A", "usd": 1_000, "cost": float("nan"), "p95": float("nan"), "unfillable": 1.0})
        row = bw.summarize(pd.DataFrame(rows), 4.5).iloc[0]
        self.assertEqual((row["days"], row["days_with_cost"]), (12, 11))
        self.assertAlmostEqual(row["cost"], 1.0)
        self.assertAlmostEqual(row["unfillable"], 1 / 12)
        self.assertEqual(row["verdict"], "UNKNOWN")

    def test_summary_keeps_coins_and_sizes_apart(self):
        rows = [{"coin": c, "usd": u, "cost": 1.0, "p95": 2.0, "unfillable": 0.0}
                for c in ("A", "B") for u in (1_000, 10_000) for _ in range(12)]
        self.assertEqual(len(bw.summarize(pd.DataFrame(rows), 4.5)), 4)


if __name__ == "__main__":
    unittest.main()
