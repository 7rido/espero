"""#52-#56: the descriptive measures, on synthetic series only."""
import unittest

import numpy as np
import pandas as pd

from espero import patterns as pt


def minutes(n):
    return pd.date_range("2026-01-01", periods=n, freq="min")


class StateTests(unittest.TestCase):
    def test_no_state_before_the_minimum_history(self):
        s = pd.Series(np.arange(100.0), index=minutes(100))
        st = pt.states(s)
        self.assertTrue((st.iloc[:60] == 0).all())
        self.assertEqual(st.iloc[60], 1)

    def test_cut_offs_ignore_the_current_value(self):
        s = pd.Series(np.r_[np.arange(70.0), 1000.0], index=minutes(71))
        self.assertEqual(pt.states(s).iloc[-1], 1)
        changed = s.copy()
        changed.iloc[-1] = -1000.0
        self.assertEqual(pt.states(changed).iloc[-1], -1)

    def test_a_later_value_does_not_change_an_earlier_state(self):
        s = pd.Series(np.random.default_rng(1).normal(size=200), index=minutes(200))
        before = pt.states(s).iloc[150]
        s.iloc[151:] = 1e6
        self.assertEqual(pt.states(s).iloc[150], before)

    def test_window_forgets_older_values(self):
        values = np.r_[np.full(100, 1e6), np.arange(121.0)]
        s = pd.Series(values, index=minutes(len(values)))
        self.assertEqual(pt.states(s).iloc[-1], 1)

    def test_low_state_and_missing_signal(self):
        s = pd.Series(np.r_[np.arange(70.0), -5.0, np.nan], index=minutes(72))
        st = pt.states(s)
        self.assertEqual(st.iloc[-2], -1)
        self.assertEqual(st.iloc[-1], 0)

    def test_percentiles_are_eighty_and_twenty(self):
        s = pd.Series(np.r_[np.arange(101.0), 79.0, 81.0, 21.0, 19.0], index=minutes(105))
        st = pt.states(s)
        self.assertEqual(st.iloc[-4], 0)
        self.assertEqual(st.iloc[-2], 0)


class MoveTests(unittest.TestCase):
    def setUp(self):
        idx = pd.date_range("2026-01-01", periods=5, freq="min")
        self.prices = pd.Series([100.0, 101.0, 102.0, 103.0, 104.0], index=idx)
        self.idx = idx

    def test_forward_change_in_bps(self):
        move = pt.forward_bps(self.prices, self.idx[:1], 60)
        self.assertAlmostEqual(move[0], 100.0)

    def test_uses_last_price_at_or_before_the_time(self):
        at = pd.DatetimeIndex([self.idx[0] + pd.Timedelta(seconds=30)])
        self.assertAlmostEqual(pt.forward_bps(self.prices, at, 60)[0], 100.0)

    def test_move_past_the_end_is_dropped(self):
        self.assertTrue(np.isnan(pt.forward_bps(self.prices, self.idx[-1:], 60)[0]))

    def test_high_minus_low_and_up_shares(self):
        state = np.r_[np.ones(20), -np.ones(20), np.zeros(5)]
        move = np.r_[np.full(10, 4.0), np.full(10, -2.0), np.full(20, -1.0), np.full(5, 99.0)]
        diff, up_high, up_low = pt.high_minus_low(state, move)
        self.assertAlmostEqual(diff, 2.0)
        self.assertAlmostEqual(up_high, 0.5)
        self.assertAlmostEqual(up_low, 0.0)

    def test_too_few_states_gives_nothing(self):
        state = np.r_[np.ones(pt.MIN_STATES - 1), -np.ones(pt.MIN_STATES)]
        self.assertTrue(np.isnan(pt.high_minus_low(state, np.ones(len(state)))[0]))
        state = np.r_[np.ones(pt.MIN_STATES), -np.ones(pt.MIN_STATES)]
        self.assertFalse(np.isnan(pt.high_minus_low(state, np.ones(len(state)))[0]))

    def test_missing_moves_are_not_counted(self):
        state = np.r_[np.ones(21), -np.ones(20)]
        move = np.r_[np.full(20, 1.0), np.nan, np.zeros(20)]
        self.assertAlmostEqual(pt.high_minus_low(state, move)[0], 1.0)
        state = np.r_[np.ones(20), -np.ones(20)]
        move = np.r_[np.full(19, 1.0), np.nan, np.zeros(20)]
        self.assertTrue(np.isnan(pt.high_minus_low(state, move)[0]))


class LabelTests(unittest.TestCase):
    def test_clear_needs_all_three(self):
        self.assertTrue(pt.clear_label(1, 2, 1, 1, 9, 9))
        self.assertFalse(pt.clear_label(-1, 2, 1, 1, 9, 9))
        self.assertFalse(pt.clear_label(1, 2, 1, -1, 9, 9))
        self.assertFalse(pt.clear_label(1, 2, 1, 1, 8, 9))

    def test_clear_works_for_a_negative_effect(self):
        self.assertTrue(pt.clear_label(-2, -1, -1, -1, 9, 9))
        self.assertFalse(pt.clear_label(-2, -1, 1, 1, 9, 9))

    def test_ci_touching_zero_is_not_clear(self):
        self.assertFalse(pt.clear_label(0.0, 2, 1, 1, 9, 9))
        self.assertFalse(pt.clear_label(-2, 0.0, -1, -1, 9, 9))

    def test_bootstrap_is_seeded_and_wider_at_a_higher_level(self):
        values = np.random.default_rng(2).normal(size=24)
        self.assertEqual(pt.bootstrap_ci(values, 0.95, 5), pt.bootstrap_ci(values, 0.95, 5))
        low95, high95 = pt.bootstrap_ci(values, 0.95, 5)
        low99, high99 = pt.bootstrap_ci(values, 0.9875, 5)
        self.assertLess(low99, low95)
        self.assertGreater(high99, high95)

    def test_summary_averages_coins_within_days_then_days(self):
        rows = pd.DataFrame({"coin": ["A", "B", "A"], "day": ["d1", "d1", "d2"], "value": [1.0, 3.0, 5.0]})
        out = pt.horizon_summary(rows, 0.95, 1, coins_needed=1)
        self.assertAlmostEqual(out["mean"], 3.5)
        self.assertEqual(out["days"], 2)
        self.assertEqual(out["coins"], 2)

    def test_summary_halves_split_in_date_order_and_coins_count_sign(self):
        rows = pd.DataFrame({"coin": ["A", "A", "B", "B", "C", "C"], "day": ["d2", "d1", "d2", "d1", "d2", "d1"],
                             "value": [3.0, 1.0, -9.0, -9.0, -3.0, -4.0]})
        out = pt.horizon_summary(rows, 0.95, 1, coins_needed=1)
        self.assertAlmostEqual(out["first_half"], -4.0)
        self.assertAlmostEqual(out["second_half"], -3.0)
        self.assertEqual(out["coins_same"], 2)

    def test_summary_drops_missing_values(self):
        rows = pd.DataFrame({"coin": ["A", "A"], "day": ["d1", "d2"], "value": [1.0, float("nan")]})
        self.assertEqual(pt.horizon_summary(rows, 0.95, 1, coins_needed=1)["days"], 1)


class LeadTests(unittest.TestCase):
    def test_grid_takes_the_last_price_in_each_bin_and_carries_it(self):
        out = pt.grid_prices(np.array([0, 50, 250]), np.array([1.0, 2.0, 3.0]), 0, 100, 4)
        self.assertEqual(list(out), [2.0, 2.0, 3.0, 3.0])

    def test_grid_sorts_by_time_and_drops_out_of_day_prints(self):
        out = pt.grid_prices(np.array([50, 0, -10, 500]), np.array([2.0, 1.0, 9.0, 9.0]), 0, 100, 3)
        self.assertEqual(list(out), [2.0, 2.0, 2.0])

    def test_grid_is_empty_before_the_first_trade(self):
        self.assertTrue(np.isnan(pt.grid_prices(np.array([150]), np.array([1.0]), 0, 100, 3)[0]))

    def _paths(self, lag):
        steps = np.random.default_rng(3).normal(0, 1e-4, 2000)
        a = 100 * np.exp(np.cumsum(steps))
        b = np.r_[np.full(lag, 100.0), a[:-lag]] if lag else a.copy()
        return a, b

    def test_positive_lag_when_the_first_series_leads(self):
        a, b = self._paths(5)
        self.assertEqual(pt.peak_lag(a, b, 20)[0], 5)

    def test_negative_lag_when_the_second_series_leads(self):
        a, b = self._paths(5)
        self.assertEqual(pt.peak_lag(b, a, 20)[0], -5)

    def test_zero_lag_and_correlation_near_one(self):
        a, b = self._paths(0)
        lag, corr = pt.peak_lag(a, b, 20)
        self.assertEqual(lag, 0)
        self.assertAlmostEqual(corr, 1.0, places=6)

    def test_max_lag_limits_the_search(self):
        a, b = self._paths(30)
        self.assertLessEqual(abs(pt.peak_lag(a, b, 20)[0]), 20)

    def test_flat_series_has_no_correlation(self):
        self.assertTrue(np.isnan(pt.peak_lag(np.full(50, 1.0), np.full(50, 1.0), 5)[1]))

    def test_spacing_measures_from_the_previous_event_kept_or_not(self):
        mask = pt.spaced_events(np.array([0.0, 10.0, 25.0, 60.0]), 30.0)
        self.assertEqual(list(mask), [True, False, False, True])
        self.assertEqual(list(pt.spaced_events(np.array([0.0, 20.0, 40.0]), 30.0)), [True, False, False])

    def test_spacing_keeps_an_event_exactly_at_the_gap(self):
        self.assertEqual(list(pt.spaced_events(np.array([0.0, 30.0]), 30.0)), [True, True])


class RefillTests(unittest.TestCase):
    def setUp(self):
        self.t = np.array([99.0, 100.0, 101.0, 102.0, 110.0])

    def test_first_time_back_at_ninety_percent(self):
        seconds, low = pt.refill(self.t, np.array([100.0, 40.0, 60.0, 90.0, 100.0]), 100.0, 100.0)
        self.assertAlmostEqual(seconds, 2.0)
        self.assertAlmostEqual(low, 0.4)

    def test_eighty_five_percent_is_not_refilled(self):
        self.assertAlmostEqual(pt.refill(self.t, np.array([100.0, 40.0, 85.0, 90.0, 100.0]), 100.0, 100.0)[0], 2.0)

    def test_depth_before_the_burst_is_ignored(self):
        self.assertAlmostEqual(pt.refill(self.t, np.array([100.0, 10.0, 10.0, 10.0, 95.0]), 100.0, 100.0)[0], 10.0)

    def test_never_refilled_is_censored(self):
        seconds, low = pt.refill(self.t, np.array([100.0, 40.0, 30.0, 50.0, 60.0]), 100.0, 100.0)
        self.assertEqual(seconds, pt.CENSOR_S)
        self.assertAlmostEqual(low, 0.3)

    def test_depth_after_the_censor_time_is_ignored(self):
        t = np.array([100.0, 100.0 + pt.CENSOR_S + 1])
        self.assertEqual(pt.refill(t, np.array([10.0, 100.0]), 100.0, 100.0)[0], pt.CENSOR_S)

    def test_lowest_depth_stops_at_the_refill(self):
        self.assertAlmostEqual(pt.refill(self.t, np.array([100.0, 50.0, 95.0, 1.0, 1.0]), 100.0, 100.0)[1], 0.5)

    def test_no_baseline_gives_nothing(self):
        self.assertTrue(np.isnan(pt.refill(self.t, np.ones(5), 100.0, 0.0)[0]))
        self.assertTrue(np.isnan(pt.refill(self.t, np.ones(5), 500.0, 100.0)[0]))


class SignalTests(unittest.TestCase):
    def test_top5_notional_skips_missing_levels(self):
        out = pt.top5_notional(np.array([[10.0, np.nan]]), np.array([[2.0, np.nan]]))
        self.assertEqual(out[0], 20.0)

    def test_imbalance_is_the_bid_share(self):
        out = pt.imbalance(np.array([3.0, 0.0]), np.array([1.0, 0.0]))
        self.assertAlmostEqual(out[0], 0.75)
        self.assertTrue(np.isnan(out[1]))

    def test_flow_covers_sixty_seconds_and_has_a_sign(self):
        idx = pd.date_range("2026-01-01", periods=70, freq="s")
        buy = pd.Series(np.r_[np.full(10, 1.0), np.zeros(60)], index=idx)
        sell = pd.Series(np.r_[np.zeros(10), np.full(60, 1.0)], index=idx)
        out = pt.flow(buy, sell)
        self.assertAlmostEqual(out.iloc[9], 1.0)
        self.assertAlmostEqual(out.iloc[-1], -1.0)
        self.assertAlmostEqual(out.iloc[30], (10 - 21) / 31)

    def test_flow_without_trades_is_missing(self):
        idx = pd.date_range("2026-01-01", periods=2, freq="s")
        self.assertTrue(np.isnan(pt.flow(pd.Series(0.0, index=idx), pd.Series(0.0, index=idx)).iloc[0]))


if __name__ == "__main__":
    unittest.main()
