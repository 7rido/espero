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


if __name__ == "__main__":
    unittest.main()
