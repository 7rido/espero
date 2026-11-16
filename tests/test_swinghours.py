"""#82's measurement (espero/swinghours.py), on made-up hourly bars whose answers are known."""
import unittest

import numpy as np
import pandas as pd

from espero import swinghours as S


def bars(start="2023-01-02", hours=24 * 7 * 60, size=None, seed=0):
    """Hourly bars from `start` (UTC); `size(ts) -> body in log units` shapes the swings, sign random."""
    rng = np.random.default_rng(seed)
    t = pd.date_range(start, periods=hours, freq="h", tz="UTC")
    body = np.array([size(x) for x in t]) if size else np.full(hours, 0.002)
    sign = rng.choice([-1.0, 1.0], hours)
    o = 100.0 * np.exp(np.cumsum(np.r_[0.0, (sign * body)[:-1]]))
    c = o * np.exp(sign * body)
    ms = ((t - pd.Timestamp(0, tz="UTC")) // pd.Timedelta("1ms")).to_numpy().astype("int64")
    return pd.DataFrame({"open_time": ms, "open": o,
                         "high": np.maximum(o, c) * 1.0005, "low": np.minimum(o, c) * 0.9995, "close": c,
                         "volume": np.full(hours, 10.0)})


def busy_at(hour_utc, factor=3.0):
    return lambda ts: 0.002 * (factor if ts.hour == hour_utc and ts.dayofweek < 5 else 1.0)


class TestTheSwings(unittest.TestCase):
    def test_body_and_range_are_normalised_by_the_previous_720_bars_only(self):
        f = bars(hours=800)
        s = S.swings(f)
        self.assertEqual(len(s), 800 - S.WINDOW)                # the first 720 have no normaliser
        self.assertTrue(np.allclose(s["body"], 1.0))            # a constant body over its own mean
        g = f.copy()
        g.loc[799, "close"] = g.loc[799, "open"] * np.exp(0.02)  # the last bar ten times bigger
        g.loc[799, "high"] = g.loc[799, "close"] * 1.0005
        s2 = S.swings(g)
        self.assertAlmostEqual(s2["body"].iloc[-1], 10.0, places=6)
        self.assertTrue(np.allclose(s2["body"].iloc[:-1], 1.0))  # it never reaches back: past only

    def test_bad_bars_are_dropped(self):
        f = bars(hours=760)
        f.loc[750, "volume"] = 0.0
        f.loc[751, "high"] = f.loc[751, "low"] * 0.5
        f.loc[752, "open"] = 0.0
        self.assertEqual(len(S.swings(f)), 760 - 3 - S.WINDOW)


    def test_open_times_in_microseconds_are_read_as_such(self):
        f = bars(hours=760)
        g = f.copy()
        g["open_time"] = g["open_time"] * 1000                  # Binance's archive moved some files to microseconds
        self.assertTrue(S.swings(f)["t"].equals(S.swings(g)["t"]))
        self.assertEqual(S.swings(f)["t"].iloc[0].year, 2023)


class TestTheProfiles(unittest.TestCase):
    def test_a_busy_hour_shows_on_the_utc_clock_in_its_slot(self):
        p = S.profiles(S.swings(bars(size=busy_at(14))))
        h = p.hours["utc"]
        self.assertEqual(int(np.nanargmax(h)), 14)
        self.assertGreater(h[14] / np.nanmedian(h), 2.0)
        self.assertEqual(p.week.shape, (168,))
        self.assertEqual(int(np.nanargmax(p.week)) % 24, 14)
        self.assertLess(int(np.nanargmax(p.week)) // 24, 5)     # a weekday

    def test_the_new_york_clock_follows_daylight_saving(self):
        def ny(ts):
            return 0.002 * (3.0 if ts.tz_convert(S.NEW_YORK).hour == 9 and ts.dayofweek < 5 else 1.0)
        both = bars(start="2023-01-02", hours=24 * 7 * 52, size=ny)    # winter and summer: 14 and 13 UTC
        p = S.profiles(S.swings(both))
        self.assertEqual(int(np.nanargmax(p.hours["new_york"])), 9)
        self.assertGreater(S.peak_to_trough(p.hours["new_york"]), S.peak_to_trough(p.hours["utc"]))

    def test_the_weekday_hours_leave_the_weekend_out(self):
        def quiet_weekend(ts):
            return 0.002 * (0.3 if ts.dayofweek >= 5 else 1.0)
        p = S.profiles(S.swings(bars(size=quiet_weekend)))
        self.assertLess(np.nanmax(p.hours["utc"]) / np.nanmin(p.hours["utc"]), 1.2)   # flat across weekday hours
        self.assertTrue(S.weekend_quietest(p.days))
        self.assertLess(S.weekend_ratio(p.days), 0.6)
        self.assertFalse(S.weekend_quietest(S.profiles(S.swings(bars())).days + np.arange(7) * 0.0 +
                                            np.array([0, 0, 0, 0, 0, 1, 1]) * 0.5))


class TestTheWeekdayAndWeekendRules(unittest.TestCase):
    def test_a_weekend_only_busy_hour_stays_out_of_the_weekday_hours(self):
        def weekend_03(ts):
            return 0.002 * (5.0 if ts.hour == 3 and ts.dayofweek >= 5 else 1.0)
        p = S.profiles(S.swings(bars(size=weekend_03)))
        self.assertLess(S.peak_to_trough(p.hours["utc"]), 1.2)
        self.assertGreater(p.week[5 * 24 + 3] / np.nanmedian(p.week), 3.0)

    def test_the_weekend_readouts_exactly(self):
        days = np.array([1.0, 1.0, 1.0, 1.0, 1.0, 0.5, 0.5])
        self.assertAlmostEqual(S.weekend_ratio(days), 0.5)
        self.assertTrue(S.weekend_quietest(days))
        self.assertFalse(S.weekend_quietest(np.array([1.0, 0.6, 1.0, 1.0, 1.0, 0.5, 0.7])))   # Tuesday, not Sunday

    def test_a_coin_needs_a_year_out_of_sample_too(self):
        hours = (pd.Timestamp("2025-04-01") - pd.Timestamp("2023-01-02")).days * 24
        late = S.swings(bars(start="2023-01-02", hours=hours))
        self.assertGreaterEqual(S.months(S.halves(late)["in"]), 12)
        self.assertFalse(S.compares(S.halves(late)))


class TestTheReadouts(unittest.TestCase):
    def coins(self, n=15, out_hour=14, in_hour=14):
        out = {}
        for i in range(n):
            f_in = bars(start="2023-01-02", hours=24 * 7 * 60, size=busy_at(in_hour), seed=i)
            f_out = bars(start="2025-01-06", hours=24 * 7 * 60, size=busy_at(out_hour), seed=100 + i)
            out[f"C{i}"] = {"in": S.profiles(S.swings(f_in)), "out": S.profiles(S.swings(f_out))}
        return out

    def test_the_same_hours_in_both_halves_repeat(self):
        r = S.repeat(self.coins(), "body", "utc")
        self.assertGreater(r.pooled_rho, 0.0)
        self.assertEqual(r.coins, 15)

    def test_the_thresholds_are_the_pre_registrations(self):
        self.assertEqual((S.POOLED_MIN, S.COIN_MIN, S.COINS_NEEDED, S.CLOCK_MARGIN), (0.7, 0.5, 13, 0.05))
        self.assertEqual((S.WINDOW, str(S.SPLIT.date()), str(S.END.date()), S.MIN_MONTHS),
                         (720, "2025-01-01", "2026-10-01", 12))
        r = S.Repeat("body", "utc", 0.7, {}, 13, 15)
        self.assertTrue(r.repeats)
        self.assertFalse(S.Repeat("body", "utc", 0.69, {}, 15, 15).repeats)
        self.assertFalse(S.Repeat("body", "utc", 0.9, {}, 12, 15).repeats)

    def test_a_shaped_profile_repeats_and_a_moved_one_does_not(self):
        def shaped(peak):
            return lambda ts: 0.002 * (1.0 + 2.0 * np.exp(-((ts.hour - peak) ** 2) / 8.0)) * (ts.dayofweek < 5 or 1)
        coins = {}
        for i in range(15):
            coins[f"C{i}"] = {"in": S.profiles(S.swings(bars(start="2023-01-02", size=shaped(14), seed=i))),
                              "out": S.profiles(S.swings(bars(start="2025-01-06", size=shaped(14), seed=50 + i)))}
        same = S.repeat(coins, "body", "utc")
        self.assertTrue(same.repeats, (same.pooled_rho, same.coins_at_min))
        for i in range(15):
            coins[f"C{i}"]["out"] = S.profiles(S.swings(bars(start="2025-01-06", size=shaped(2), seed=50 + i)))
        moved = S.repeat(coins, "body", "utc")
        self.assertFalse(moved.repeats)
        self.assertLess(moved.pooled_rho, 0.0)

    def test_the_clock_readout(self):
        a = S.Repeat("body", "utc", 0.8, {}, 15, 15)
        self.assertEqual(S.clock_readout(a, S.Repeat("body", "new_york", 0.6, {}, 10, 15)), "UTC")
        self.assertEqual(S.clock_readout(a, S.Repeat("body", "new_york", 0.9, {}, 10, 15)), "New York")
        self.assertEqual(S.clock_readout(a, S.Repeat("body", "new_york", 0.77, {}, 10, 15)), "no clear clock")
        self.assertEqual(S.clock_readout(a, S.Repeat("body", "new_york", float("nan"), {}, 0, 0)), "no clear clock")

    def test_a_coin_compares_only_with_a_year_in_each_half(self):
        early = S.swings(bars(start="2024-06-03", hours=24 * 7 * 40))
        self.assertFalse(S.compares(S.halves(early)))           # seven months in-sample
        long = S.swings(bars(start="2023-01-02", hours=24 * 7 * 52 * 3))
        self.assertTrue(S.compares(S.halves(long)))
        h = S.halves(long)
        self.assertTrue((h["in"]["t"] < S.SPLIT).all() and (h["out"]["t"] >= S.SPLIT).all())

    def test_busiest_quietest_and_spearman(self):
        p = np.array([1.0, 3.0, np.nan, 0.5, 2.0])
        busy, quiet, ratio = S.busiest_quietest(p)
        self.assertEqual((busy, quiet, ratio), ([1], [3], 6.0))
        self.assertAlmostEqual(S.spearman(np.arange(5.0), np.arange(5.0) ** 2), 1.0)
        self.assertAlmostEqual(S.spearman(np.arange(5.0), -np.arange(5.0)), -1.0)
        self.assertTrue(np.isnan(S.spearman(np.ones(5), np.arange(5.0))))

    def test_the_signed_return_is_kept_apart_and_raw_bps_are_bps(self):
        f = bars(hours=900)
        s = S.swings(f)
        self.assertEqual(S.signed_by_slot(s).shape, (168,))
        bps = S.raw_bps_median(f)
        self.assertTrue(np.allclose(bps[np.isfinite(bps)], 20.0))   # 0.002 in log units is 20 bps


if __name__ == "__main__":
    unittest.main()
