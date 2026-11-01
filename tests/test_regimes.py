"""The lean gate against synthetic markets: fading and following told apart, test-row outcomes never read,
the frozen window cut first, and the 5-of-6 line."""
from __future__ import annotations

import unittest
from unittest import mock

import numpy as np
import pandas as pd

from espero import rate as rt
from espero import regimes as rg

NOW = pd.Timestamp("2026-10-31")


def market(seed: int, weight: float, days: int = 1400, end: str = "2026-10-29") -> pd.Series:
    """Daily returns that depend on the last week's return, by `weight`: below zero fades it, above zero follows it."""
    rng = np.random.default_rng(seed)
    r = np.zeros(days)
    for t in range(days):
        r[t] = rng.normal(0.0, 0.02) + weight * r[max(0, t - 7):t].sum() / 7
    return pd.Series(100 * np.exp(np.cumsum(r)), index=pd.date_range(end=end, periods=days, freq="D"), name="close")


def rows(weight: float, **kw) -> pd.DataFrame:
    return rg.panel({f"C{s}": market(s, weight, **kw) for s in range(4)}, "crypto", NOW)


class LeanTests(unittest.TestCase):
    def test_a_fading_market_passes_and_a_following_one_closes(self):
        fading = rg.lean_by_fold(rows(-0.5))
        following = rg.lean_by_fold(rows(0.5))
        self.assertEqual(len(fading), rt.SPLITS)
        self.assertTrue(rg.fades(fading), fading)
        self.assertFalse(rg.fades(following), following)
        self.assertLess(np.mean(fading), 0)
        self.assertGreater(np.mean(following), 0)

    def test_test_row_outcomes_are_never_read(self):
        x = rows(-0.5)
        dates = pd.DatetimeIndex(sorted(x.index.unique()))
        first_test = dates[rt.MIN_TRAIN]
        changed = x.copy()
        changed.loc[changed.index > dates[-1] - pd.Timedelta(days=30), "y"] = 0.5     # only ever a test row
        self.assertLess(first_test, dates[-1] - pd.Timedelta(days=30))
        self.assertEqual(rg.lean_by_fold(x), rg.lean_by_fold(changed))

    def test_later_closes_change_nothing_earlier(self):
        px = market(1, -0.5)
        a = rg.panel({"C": px}, "crypto", NOW)
        b = rg.panel({"C": px.iloc[:-40]}, "crypto", NOW)
        shared = b.drop(columns="y").index
        pd.testing.assert_frame_equal(a.loc[shared].drop(columns="y"), b.drop(columns="y"))


class FrozenWindowTests(unittest.TestCase):
    def test_no_row_reaches_into_the_frozen_window(self):
        px = market(2, -0.5, end="2026-12-31")
        x = rg.panel({"C": px}, "crypto", NOW)
        self.assertLess(x.index.max() + pd.Timedelta(days=rg.HORIZON), rt.FROZEN_FROM)

    def test_series_are_cut_before_any_feature_is_computed(self):
        px = market(3, -0.5, end="2026-12-31")
        seen = []
        real = rt.rows

        def spy(series, *args):
            seen.append(series.index.max())
            return real(series, *args)

        with mock.patch.object(rt, "rows", spy):
            rg.panel({"C": px}, "crypto", NOW)
        self.assertEqual(seen, [rt.FROZEN_FROM - pd.Timedelta(days=1)])


class PanelTests(unittest.TestCase):
    def test_every_symbol_with_history_is_pooled_and_a_short_one_is_left_out(self):
        long_a, long_b = market(4, -0.5), market(5, -0.5)
        short = market(6, -0.5).iloc[-50:]
        both = rg.panel({"A": long_a, "B": long_b}, "crypto", NOW)
        self.assertEqual(len(both), 2 * len(rg.panel({"A": long_a}, "crypto", NOW)))
        pd.testing.assert_frame_equal(rg.panel({"S": short, "A": long_a, "B": long_b}, "crypto", NOW), both)


class LineTests(unittest.TestCase):
    def test_five_of_six_passes_and_four_does_not(self):
        self.assertTrue(rg.fades([-0.1, -0.1, -0.1, -0.1, -0.1, 0.2]))
        self.assertFalse(rg.fades([-0.1, -0.1, -0.1, -0.1, 0.2, 0.2]))

    def test_zero_and_missing_folds_count_against(self):
        self.assertFalse(rg.fades([-0.1, -0.1, -0.1, -0.1, 0.0, 0.2]))
        self.assertFalse(rg.fades([-0.1, -0.1, -0.1, -0.1]))
        self.assertFalse(rg.fades([-0.1, -0.1, -0.1, -0.1, float("nan"), 0.2]))


def days(n: int, end: str = "2026-10-29") -> pd.DatetimeIndex:
    return pd.date_range(end=end, periods=n, freq="D")


class VolatilityTests(unittest.TestCase):
    def test_nothing_later_changes_an_earlier_label(self):
        px = market(7, 0.0, days=900)
        a = rg.volatility_states(px, "crypto")
        b = rg.volatility_states(px.iloc[:-100], "crypto")
        pd.testing.assert_series_equal(a.reindex(b.index), b)

    def test_todays_value_does_not_set_its_own_cut_off(self):
        rng = np.random.default_rng(8)
        r = rng.normal(0, 0.01, 800)
        r[-1] = 0.5                                     # the largest value on file on its last day
        px = pd.Series(100 * np.exp(np.cumsum(r)), index=days(800))
        self.assertEqual(rg.volatility_states(px, "crypto").iloc[-1], "high")

    def test_cut_offs_are_the_thirds_of_earlier_values(self):
        px = market(11, 0.0, days=700)
        v = np.log(px).diff().rolling(60, min_periods=60).std() * 365 ** 0.5
        s = rg.volatility_states(px, "crypto")
        for i in range(430, 700, 7):
            earlier = v.iloc[:i].dropna().to_numpy()
            low, high = np.quantile(earlier, 1 / 3), np.quantile(earlier, 2 / 3)
            expected = "low" if v.iloc[i] <= low else "high" if v.iloc[i] > high else "mid"
            self.assertEqual(s.iloc[i], expected, i)

    def test_no_label_until_a_full_year_of_earlier_values(self):
        s = rg.volatility_states(market(9, 0.0, days=900), "etf")
        first = s.dropna().index[0]
        self.assertEqual(list(s.index).index(first), 60 + rt.PERIODS["etf"])

    def test_states_follow_the_size_of_recent_moves(self):
        rng = np.random.default_rng(10)
        sizes = np.r_[np.full(500, 0.02), np.full(100, 0.002), np.full(100, 0.06)]
        px = pd.Series(100 * np.exp(np.cumsum(rng.normal(0, 1, 700) * sizes)), index=days(700))
        s = rg.volatility_states(px, "crypto")
        self.assertEqual(s.iloc[595], "low")
        self.assertEqual(s.iloc[695], "high")
        self.assertEqual(set(s.dropna().unique()), {"low", "mid", "high"})


def settlements(rate=0.00005, n_days: int = 10, end: str = "2026-10-10") -> pd.Series:
    idx = pd.date_range(end=f"{end} 16:00", periods=n_days * 3, freq="8h")
    return pd.Series(rate, index=idx, dtype=float)


class FundingTests(unittest.TestCase):
    def label(self, s, day="2026-10-10"):
        return rg.funding_states(s).get(pd.Timestamp(day))

    def test_the_lines(self):
        self.assertEqual(self.label(settlements(-0.00001)), "crowded short")
        self.assertEqual(self.label(settlements(0.0)), "neutral")
        self.assertEqual(self.label(settlements(0.0001)), "neutral")
        self.assertEqual(self.label(settlements(0.00011)), "crowded long")

    def test_the_mean_is_of_the_last_21_slots(self):
        s = settlements(0.0)
        s.iloc[-21:] = 0.0002
        self.assertEqual(self.label(s), "crowded long")
        s = settlements(0.0002)
        s.iloc[-21:] = 0.0
        self.assertEqual(self.label(s), "neutral")

    def test_the_next_days_midnight_is_not_counted(self):
        s = settlements(0.0)
        s.loc[pd.Timestamp("2026-10-11 00:00")] = 1.0
        self.assertEqual(self.label(s), "neutral")

    def test_the_days_16_00_is_counted(self):
        s = settlements(0.0)
        s.loc[pd.Timestamp("2026-10-10 16:00")] = 1.0
        self.assertEqual(self.label(s), "crowded long")

    def test_a_gap_stays_a_gap(self):
        s = settlements(0.0)
        self.assertEqual(self.label(s.drop(s.index[-6:-3])), "neutral")        # 18 of 21
        self.assertTrue(pd.isna(self.label(s.drop(s.index[-7:-3]))))           # 17 of 21

    def test_a_late_stamp_lands_on_its_slot_and_an_off_clock_one_is_dropped(self):
        s = settlements(0.0)
        s.index = s.index + pd.Timedelta(milliseconds=3)
        self.assertEqual(self.label(s), "neutral")
        s = settlements(0.0)
        s.loc[pd.Timestamp("2026-10-10 12:00")] = 1.0
        self.assertEqual(self.label(s), "neutral")


class CountTests(unittest.TestCase):
    def setUp(self):
        self.dates = days(1500)

    def test_counts_add_up_on_the_ratings_folds(self):
        labels = pd.Series(["a", "b", "c"] * 500, index=self.dates)
        c = rg.count_states(self.dates, labels)
        self.assertEqual(c["test_dates"], 1500 - rt.MIN_TRAIN)
        self.assertEqual(sum(r["test"] for r in c["states"].values()), c["test_dates"])
        for row in c["states"].values():
            self.assertEqual(row["first_half"] + row["second_half"], row["test"])
            self.assertEqual(sum(row["by_fold"]), row["test"])
            self.assertEqual(len(row["train"]), rt.SPLITS)

    def test_a_thin_training_fold_gives_that_state_nothing(self):
        labels = pd.Series("a", index=self.dates, dtype=object)
        labels.iloc[1000:] = "b"                       # no training dates for b in the early folds
        row = rg.count_states(self.dates, labels)["states"]["b"]
        self.assertLess(row["test"], 500)
        self.assertLess(min(row["train"]), rg.TRAIN_FLOOR)
        self.assertEqual(row["by_fold"][0], 0)

    def test_a_thin_fold_shows_nothing_even_with_test_dates_in_the_state(self):
        labels = pd.Series("a", index=self.dates, dtype=object)
        labels.iloc[400:500] = "b"                     # inside the first test block, none in its training window
        row = rg.count_states(self.dates, labels)["states"]["b"]
        self.assertEqual(row["train"][0], 0)
        self.assertEqual(row["by_fold"][0], 0)
        self.assertEqual(row["test"], 0)

    def test_exactly_the_floor_counts(self):
        labels = pd.Series("a", index=self.dates, dtype=object)
        labels.iloc[:rg.TRAIN_FLOOR] = "b"
        labels.iloc[rt.MIN_TRAIN + 10] = "b"
        self.assertEqual(rg.count_states(self.dates, labels)["states"]["b"]["test"], 1)
        labels.iloc[0] = "a"
        self.assertEqual(rg.count_states(self.dates, labels)["states"]["b"]["test"], 0)

    def test_unlabelled_dates_are_counted_apart_and_never_placed(self):
        labels = pd.Series("a", index=self.dates, dtype=object)
        labels.iloc[-100:] = None
        c = rg.count_states(self.dates, labels)
        self.assertEqual(c["unlabelled"], 100)
        self.assertEqual(c["unlabelled_test"], 100)
        self.assertEqual(c["states"]["a"]["test"], c["test_dates"] - 100)

    def test_it_reads_only_dates(self):
        labels = pd.Series(["a", "b"] * 750, index=self.dates)
        with mock.patch.object(rt, "fit", side_effect=AssertionError("fitted")), \
                mock.patch.object(rt, "skill", side_effect=AssertionError("scored")):
            rg.count_states(self.dates, labels)


def counted(state=300, comparator=600, total=1000, first=150, second=150):
    return {"test_dates": total, "states": {"s": {"test": state, "first_half": first, "second_half": second},
                                            "c": {"test": comparator}}}


class VerdictTests(unittest.TestCase):
    def test_the_committed_formula(self):
        v = rg.verdict(counted(), "s", ["c"], -0.61, 0.405)
        self.assertAlmostEqual(v["w"], 0.3)
        self.assertAlmostEqual(v["c"], 0.6)
        self.assertAlmostEqual(v["mde"], (2.80 / 1.96) * 0.405 * (1 / 0.3 + 1 / 0.6) ** 0.5)
        self.assertAlmostEqual(v["d"], 0.61 / 0.7)
        self.assertFalse(v["open"])

    def test_the_sum_of_comparators_is_used(self):
        c = counted(comparator=300)
        c["states"]["c2"] = {"test": 300}
        self.assertAlmostEqual(rg.verdict(c, "s", ["c", "c2"], -0.61, 0.405)["c"], 0.6)

    def test_open_needs_both_conditions(self):
        wide = {"state": 600, "comparator": 400, "first": 300, "second": 300}
        self.assertTrue(rg.verdict(counted(**wide), "s", ["c"], -0.61, 0.405)["open"])
        thin = dict(wide, first=51, second=549)
        self.assertFalse(rg.verdict(counted(**thin), "s", ["c"], -0.61, 0.405)["open"])
        self.assertTrue(rg.verdict(counted(**dict(wide, first=52, second=548)), "s", ["c"], -0.61, 0.405)["open"])
        self.assertFalse(rg.verdict(counted(**dict(wide, second=51, first=549)), "s", ["c"], -0.61, 0.405)["open"])
        self.assertFalse(rg.verdict(counted(**wide), "s", ["c"], -0.61, 4.0)["open"])

    def test_a_missing_state_closes(self):
        self.assertFalse(rg.verdict(counted(), "absent", ["c"], -0.61, 0.405)["open"])
        self.assertFalse(rg.verdict(counted(), "s", ["absent"], -0.61, 0.405)["open"])


if __name__ == "__main__":
    unittest.main()
