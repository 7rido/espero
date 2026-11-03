"""#68's measurement (research/PREREGISTRATION_COSTCURVE.md), on made-up books only."""
import unittest

import numpy as np
import pandas as pd

from espero import costcurve as cc


def book(levels, usd_per_level, mid=100.0, tick=0.01, n=1):
    """`n` identical snapshots with `levels` levels a side, each holding `usd_per_level` dollars."""
    asks_px = np.array([[mid + tick * (i + 1) for i in range(levels)]] * n)
    bids_px = np.array([[mid - tick * (i + 1) for i in range(levels)]] * n)
    qty = np.array([[usd_per_level / (mid + tick * (i + 1)) for i in range(levels)]] * n)
    return asks_px, qty, bids_px, qty.copy()


def days_frame(coin, days, cost_by_size, unfillable=0.0):
    rows = []
    for d in days:
        for usd, c in cost_by_size.items():
            cost = c(d) if callable(c) else c
            rows.append({"coin": coin, "day": d, "usd": usd, "cost": cost, "unfillable": unfillable})
    return pd.DataFrame(rows)


DAYS = [f"2025-{m:02d}-01" for m in range(1, 13)] + ["2026-01-01", "2026-02-01", "2026-03-01", "2026-04-01",
                                                      "2026-05-01", "2026-06-01", "2026-07-01", "2026-08-01"]
DESIGN = DAYS[:10]


class CoinDayTests(unittest.TestCase):
    def test_small_order_costs_half_the_spread_and_a_big_one_is_unfillable(self):
        a_px, a_q, b_px, b_q = book(levels=2, usd_per_level=1_000, n=4)
        by_size, buckets = cc.coin_day(a_px, a_q, b_px, b_q, hours=np.array([0, 5, 13, 23]), sizes=(500, 5_000))
        self.assertAlmostEqual(by_size[500]["cost"], 1.0)          # one tick on a 100 mid is 1 bp
        self.assertEqual(by_size[500]["unfillable"], 0.0)
        self.assertTrue(np.isnan(by_size[5_000]["cost"]))
        self.assertEqual(by_size[5_000]["unfillable"], 1.0)
        self.assertEqual(buckets, {})                               # no $10,000 size asked for

    def test_a_coin_day_averages_the_two_sides(self):
        # $300 a level: a $500 order reaches the second level, a tick away on the asks and a dollar away on the bids
        a_px, b_px = np.array([[100.01, 100.02]] * 2), np.array([[99.99, 99.00]] * 2)
        a_q, b_q = 300.0 / a_px, 300.0 / b_px
        by_size, _ = cc.coin_day(a_px, a_q, b_px, b_q, hours=np.array([0, 0]), sizes=(500,))
        buy = (500 / (300 / 100.01 + 200 / 100.02) / 100 - 1) * 1e4
        sell = (1 - 500 / (300 / 99.99 + 200 / 99.00) / 100) * 1e4
        self.assertGreater(sell, buy + 10)
        self.assertAlmostEqual(by_size[500]["cost"], (buy + sell) / 2, places=6)

    def test_hour_buckets_hold_the_ten_thousand_dollar_cost_where_the_day_has_snapshots(self):
        a_px, a_q, b_px, b_q = book(levels=20, usd_per_level=2_000, n=3)
        _, buckets = cc.coin_day(a_px, a_q, b_px, b_q, hours=np.array([1, 2, 22]), sizes=(10_000,))
        self.assertEqual(sorted(buckets), [0, 1, 2, 3, 4, 5])
        self.assertTrue(np.isfinite(buckets[0]) and np.isfinite(buckets[5]))
        self.assertTrue(all(np.isnan(buckets[b]) for b in (1, 2, 3, 4)))
        self.assertGreater(buckets[0], 1.0)                         # $10,000 walks five levels, past the first tick


class MeasuredSizesTests(unittest.TestCase):
    def test_sizes_stop_at_the_first_that_fails_and_do_not_resume(self):
        d = days_frame("X", DAYS, {500: 1.0, 1_000: 1.1, 2_000: 1.2, 5_000: 1.3})
        d.loc[d["usd"] == 2_000, "unfillable"] = 0.06
        self.assertEqual(cc.measured_sizes(d, "X", sizes=(500, 1_000, 2_000, 5_000)), [500, 1_000])

    def test_too_few_days_with_a_cost_ends_the_reach(self):
        d = days_frame("X", DAYS, {500: 1.0, 1_000: 1.1})
        d.loc[(d["usd"] == 1_000) & (d["day"] > "2025-09-01"), "cost"] = np.nan   # 9 days left with a cost
        self.assertEqual(cc.measured_sizes(d, "X", sizes=(500, 1_000)), [500])

    def test_a_coin_with_no_rows_has_no_measured_size(self):
        d = days_frame("X", DAYS, {500: 1.0})
        self.assertEqual(cc.measured_sizes(d, "Y", sizes=(500,)), [])


class CurveTests(unittest.TestCase):
    def test_fit_recovers_an_exact_square_root_law(self):
        sizes = [1_000, 10_000, 100_000]
        c0, k = cc.sqrt_fit(sizes, cc.predict(0.3, 1.5, sizes))
        self.assertAlmostEqual(c0, 0.3)
        self.assertAlmostEqual(k, 1.5)

    def test_predict_is_the_constant_at_the_reference_size(self):
        self.assertAlmostEqual(float(cc.predict(0.2, 0.7, 10_000)), 0.9)
        self.assertAlmostEqual(float(cc.predict(0.2, 0.7, 40_000)), 1.6)

    def test_fit_needs_two_finite_points(self):
        self.assertTrue(all(np.isnan(v) for v in cc.sqrt_fit([1_000], [0.5])))
        self.assertTrue(all(np.isnan(v) for v in cc.sqrt_fit([1_000, 2_000], [0.5, np.nan])))

    def test_rmse(self):
        self.assertAlmostEqual(cc.rmse([1.0, 2.0], [1.0, 4.0]), np.sqrt(2.0))


class VerdictTests(unittest.TestCase):
    def test_the_registered_order(self):
        self.assertEqual(cc.verdict(2, 10, 10, 0.1, 0.1), "UNKNOWN")
        self.assertEqual(cc.verdict(3, 4, 10, 0.1, 0.1), "UNKNOWN")
        self.assertEqual(cc.verdict(3, 10, 4, 0.1, 0.1), "UNKNOWN")
        self.assertEqual(cc.verdict(3, 5, 5, 0.5, 2.0), "FLAT IS ENOUGH")
        self.assertEqual(cc.verdict(3, 5, 5, 0.51, 0.5), "CURVE HOLDS")
        self.assertEqual(cc.verdict(3, 5, 5, 0.51, 0.51), "CURVE DRIFTS")


class ScoreTests(unittest.TestCase):
    def test_a_stable_square_root_book_gives_curve_holds_with_a_flat_cost_too_far_off(self):
        law = lambda usd: 0.2 + 3.0 * np.sqrt(usd / 10_000)        # noqa: E731
        d = days_frame("X", DAYS, {usd: law(usd) for usd in cc.SIZES})
        s = cc.score(d, "X", DESIGN)
        self.assertEqual(s["sizes"], list(cc.SIZES))
        self.assertEqual(s["reach"], 500_000)
        self.assertAlmostEqual(s["c0"], 0.2)
        self.assertAlmostEqual(s["k"], 3.0)
        self.assertAlmostEqual(s["err_curve"], 0.0)
        self.assertAlmostEqual(s["err_table"], 0.0)
        self.assertGreater(s["err_flat"], cc.TOL_BPS)
        self.assertEqual(s["design_days"], 10)
        self.assertEqual(s["holdout_days"], 10)
        self.assertEqual(s["verdict"], "CURVE HOLDS")

    def test_a_book_whose_cost_doubles_in_the_holdout_drifts(self):
        law = lambda usd, d: (2.0 if d not in DESIGN else 1.0) * (0.2 + 3.0 * np.sqrt(usd / 10_000))   # noqa: E731
        d = days_frame("X", DAYS, {usd: (lambda u: (lambda day: law(u, day)))(usd) for usd in cc.SIZES})
        s = cc.score(d, "X", DESIGN)
        self.assertEqual(s["verdict"], "CURVE DRIFTS")
        self.assertGreater(s["err_curve"], cc.TOL_BPS)
        self.assertGreater(s["err_table"], cc.TOL_BPS)

    def test_the_flat_prediction_is_the_design_cost_at_one_thousand_dollars(self):
        d = days_frame("X", DAYS, {usd: (5.0 if usd == 500 else 1.0) for usd in cc.SIZES})
        s = cc.score(d, "X", DESIGN)
        self.assertAlmostEqual(s["err_flat"], np.sqrt(16.0 / len(cc.SIZES)))

    def test_a_tiny_flat_cost_is_flat_is_enough_whatever_the_curve_does(self):
        d = days_frame("X", DAYS, {usd: 0.1 + 0.001 * np.sqrt(usd / 10_000) for usd in cc.SIZES})
        self.assertEqual(cc.score(d, "X", DESIGN)["verdict"], "FLAT IS ENOUGH")

    def test_a_reach_with_few_holdout_days_is_unknown(self):
        d = days_frame("X", DAYS, {usd: 1.0 + np.sqrt(usd / 10_000) for usd in (500, 1_000, 2_000)})
        d.loc[(d["usd"] == 2_000) & (~d["day"].isin(DESIGN)) & (d["day"] > "2026-01-01"), "cost"] = np.nan
        s = cc.score(d, "X", DESIGN)
        self.assertEqual(s["reach"], 2_000)
        self.assertEqual(s["holdout_days"], 3)
        self.assertEqual(s["verdict"], "UNKNOWN")

    def test_size_table_separates_design_and_holdout_means(self):
        d = days_frame("X", DAYS, {1_000: lambda day: 1.0 if day in DESIGN else 3.0})
        t = cc.size_table(d, "X", DESIGN, sizes=(1_000,))
        self.assertAlmostEqual(float(t["design"].iloc[0]), 1.0)
        self.assertAlmostEqual(float(t["holdout"].iloc[0]), 3.0)
        self.assertAlmostEqual(float(t["cost"].iloc[0]), 2.0)
        self.assertEqual(int(t["days_with_cost"].iloc[0]), 20)
        self.assertLessEqual(float(t["low"].iloc[0]), 2.0)
        self.assertGreaterEqual(float(t["high"].iloc[0]), 2.0)


class ProfileTests(unittest.TestCase):
    def test_hour_profile_ratio_is_dearest_over_cheapest(self):
        rows = [{"coin": "X", "day": d, "bucket": b, "cost": 1.0 + (0.5 if b == 3 else 0.0)}
                for d in DAYS for b in range(6)]
        out, ratio = cc.hour_profile(pd.DataFrame(rows), "X")
        self.assertEqual(list(out["bucket"]), ["00-03", "04-07", "08-11", "12-15", "16-19", "20-23"])
        self.assertAlmostEqual(ratio, 1.5)
        self.assertEqual(int(out["days"].iloc[0]), 20)


class TableTests(unittest.TestCase):
    TABLE = {"BTC": {"c0": 0.1, "k": 0.05, "reach": 500_000, "verdict": "FLAT IS ENOUGH"},
             "HBAR": {"c0": 1.0, "k": 4.0, "reach": 50_000, "verdict": "CURVE HOLDS"},
             "TRX": {"c0": 1.0, "k": 4.0, "reach": 100_000, "verdict": "CURVE DRIFTS"},
             "XLM": {"c0": 1.0, "k": 4.0, "reach": 100_000, "verdict": "UNKNOWN"}}

    def test_cost_follows_the_curve_and_the_floor_adjustment(self):
        self.assertAlmostEqual(cc.cost("HBAR", 40_000, table=self.TABLE), 9.0)
        self.assertAlmostEqual(cc.cost("HBAR", 40_000, table=self.TABLE, adjust=True), 9.0 + cc.FLOOR_GAP_DEFAULT)
        self.assertAlmostEqual(cc.cost("BTC", 10_000, table=self.TABLE, adjust=True), 0.15 + 0.354)

    def test_cost_refuses_what_the_table_does_not_cover(self):
        for coin, usd in (("SOL", 1_000), ("TRX", 1_000), ("XLM", 1_000), ("HBAR", 50_001)):
            with self.assertRaises(cc.NotMeasured):
                cc.cost(coin, usd, table=self.TABLE)
        self.assertTrue(np.isfinite(cc.cost("HBAR", 50_000, table=self.TABLE)))

    def test_adjusted_uses_the_largest_gap_for_an_unvalidated_coin(self):
        self.assertAlmostEqual(cc.adjusted("ADA", 1.0), 1.562)
        self.assertAlmostEqual(cc.adjusted("ETH", 1.0), 1.370)


if __name__ == "__main__":
    unittest.main()
