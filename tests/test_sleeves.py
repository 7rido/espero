"""#63's combination rule on made-up sleeves only: clusters count once, a pair above the one-source
correlation shares one weight, each sleeve lands on its vol target under the sleeve and gross caps, the
drawdown throttle halves, goes flat and stays flat, and the book's return is the weighted sum."""

from __future__ import annotations

import unittest

import numpy as np
import pandas as pd

from espero import sleeves as sl


def series(rng, n, vol_daily, mean=0.0):
    return rng.normal(mean, vol_daily, n)


class TestSleeves(unittest.TestCase):
    def test_a_cluster_is_one_sleeve_represented_by_its_largest_t(self):
        got = sl.sleeves_from_passes({"27": 3.5, "45": 4.1, "24": 3.2, "8": 2.0})
        self.assertEqual(got, {"45": ["27", "45"], "24": ["24"], "8": ["8"]})

    def test_correlated_pair_shares_one_weight_and_the_rest_sit_on_the_target(self):
        rng = np.random.default_rng(63)
        n = 400
        a = series(rng, n, 0.01)
        b = a * 0.9 + series(rng, n, 0.003)  # the same source of return as a
        c = series(rng, n, 0.02)
        r = pd.DataFrame({"a": a, "b": b, "c": c})
        corr = sl.correlations(r)
        self.assertEqual(set(corr["days"]), {n})
        pair = corr[(corr["a"] == "a") & (corr["b"] == "b")]["corr"].iloc[0]
        self.assertGreater(pair, 0.9)
        self.assertEqual(sl.one_source_pairs(corr), [("a", "b")])
        w = sl.vol_target_weights(r, {"a": 3.0, "b": 4.0, "c": 3.5})
        self.assertEqual(w["a"], 0.0, "the smaller-t member of a one-source pair gets nothing")
        self.assertGreater(w["b"], 0.0)
        self.assertAlmostEqual(w["c"] * sl.sleeve_vol(r["c"]), sl.VOL_TARGET, delta=0.02)
        self.assertLessEqual(float(w.abs().sum()), sl.GROSS_CAP + 1e-9)
        self.assertLessEqual(float(w.max()), sl.SLEEVE_CAP + 1e-9)

    def test_the_gross_cap_scales_everyone_down_pro_rata(self):
        rng = np.random.default_rng(7)
        r = pd.DataFrame({k: series(rng, 300, 0.0005) for k in "abcd"})  # tiny vol: every sleeve wants 1.0
        w = sl.vol_target_weights(r, {k: 3.0 for k in "abcd"})
        self.assertAlmostEqual(float(w.sum()), 1.0, msg="this repo does not borrow: gross is capped at 100%")
        self.assertTrue(np.allclose(w.to_numpy(), w.iloc[0]))

    def test_short_history_uses_the_whole_series(self):
        rng = np.random.default_rng(1)
        short = pd.Series(series(rng, 30, 0.01))
        self.assertAlmostEqual(sl.sleeve_vol(short), float(short.std(ddof=1) * np.sqrt(sl.PERIODS)))
        long = pd.Series(np.r_[series(rng, 300, 0.05), series(rng, 100, 0.01)])
        self.assertLess(sl.sleeve_vol(long), 0.5, "the trailing window, not the noisy past")

    def test_drawdown_throttle_halves_recovers_and_goes_flat_for_good(self):
        self.assertEqual(sl.drawdown_state([100, 101, 95, 92])["state"], "full")  # -8.9% from the peak: not yet
        self.assertEqual(sl.drawdown_state([100, 110, 98])["state"], "half")  # -10.9%
        self.assertEqual(sl.drawdown_state([100, 110, 98, 108])["state"], "full")  # back within 5%
        self.assertEqual(sl.drawdown_state([100, 110, 98, 102])["state"], "half")  # not yet
        s = sl.drawdown_state([100, 110, 85, 120, 130])
        self.assertEqual(s["state"], "flat", "flat is absorbing, however high it climbs later")
        self.assertAlmostEqual(s["max_drawdown"], 85 / 110 - 1)
        self.assertEqual(sl.scale_of("half"), 0.5)
        self.assertEqual(sl.drawdown_state([])["state"], "full")

    def test_the_book_is_the_weighted_sum_and_the_summary_reports_everything(self):
        rng = np.random.default_rng(2)
        r = pd.DataFrame({"a": series(rng, 200, 0.01, 0.0005), "b": series(rng, 200, 0.02, 0.0005)})
        w = pd.Series({"a": 0.5, "b": 0.25})
        book = sl.combine(r, w)
        self.assertTrue(np.allclose(book.to_numpy(), 0.5 * r["a"].to_numpy() + 0.25 * r["b"].to_numpy()))
        s = sl.summary(r, {"a": 3.0, "b": 3.5})
        for key in ("weights", "scaled_weights", "gross", "correlations", "one_source", "drawdown", "book"):
            self.assertIn(key, s)
        self.assertEqual(set(s["drawdown"]), {"a", "b"})
        self.assertIn(s["book"]["state"], ("full", "half", "flat"))
        self.assertEqual(s["book"]["days"], 200)


if __name__ == "__main__":
    unittest.main()
