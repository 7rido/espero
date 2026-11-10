"""#73's measurement on made-up prices only: sessions, pairs, the tolerances, the bell."""
import datetime as dt
import unittest
from zoneinfo import ZoneInfo

from espero import hip3track as T

ET = ZoneInfo("America/New_York")


def et(day, hh, mm=0):
    y, m, d = (int(x) for x in day.split("-"))
    return int(dt.datetime(y, m, d, hh, mm, tzinfo=ET).timestamp())


DAY = "2026-10-06"                      # a Tuesday


class TestSession(unittest.TestCase):
    def test_by_the_eastern_clock(self):
        times = ((3, 59), (4, 0), (9, 29), (9, 30), (15, 59), (16, 0), (19, 59), (20, 0))
        self.assertEqual([T.session(et(DAY, h, m)) for h, m in times],
                         [None, "pre-market", "pre-market", "regular", "regular", "after-hours", "after-hours", None])

    def test_summer_and_winter_time_are_both_eastern(self):
        self.assertEqual(T.session(et("2026-11-03", 9, 30)), "regular")     # after the clocks went back
        utc = lambda *a: int(dt.datetime(*a, tzinfo=dt.timezone.utc).timestamp())  # noqa: E731
        self.assertEqual(T.session(utc(2026, 11, 3, 14, 0)), "pre-market")  # 09:00 in winter
        self.assertEqual(T.session(utc(2026, 10, 6, 14, 0)), "regular")     # 10:00 in summer
        self.assertEqual(et("2026-11-03", 9, 30) - et("2026-10-06", 9, 30), 28 * 86_400 + 3_600)


class TestPairs(unittest.TestCase):
    def test_consecutive_bars_on_one_day_with_perp_prices_at_both_starts(self):
        bars = [(et(DAY, 9, 0), 100.0), (et(DAY, 9, 30), 101.0), (et(DAY, 10, 30), 102.01), (et(DAY, 12, 30), 103.0),
                (et(DAY, 13, 30), 104.0), (et(DAY, 19, 0), 105.0), (et("2026-10-07", 4, 0), 106.0)]
        perp = {et(DAY, 9, 0): 50.0, et(DAY, 9, 30): 50.5, et(DAY, 10, 30): 51.0, et(DAY, 12, 30): 51.5,
                et(DAY, 19, 0): 52.0, et("2026-10-07", 4, 0): 53.0}
        got = T.pairs(bars, perp)
        self.assertEqual([s for s, _, _ in got], ["pre-market", "regular"])   # 10:30->12:30 is too far; 13:30 has no
        self.assertAlmostEqual(got[0][1], 0.01)                               # perp price; the night is another day
        self.assertAlmostEqual(got[0][2], 0.01)
        self.assertAlmostEqual(got[1][1], 0.01)
        self.assertAlmostEqual(got[1][2], 51.0 / 50.5 - 1)

    def test_off_the_quarter_hour_a_skipped_day_and_a_bad_price_are_left_out(self):
        a, b = et(DAY, 10, 30), et(DAY, 11, 30)
        self.assertEqual(len(T.pairs([(a, 1.0), (b, 1.0)], {a: 1.0, b: 1.0})), 1)
        self.assertEqual(T.pairs([(a + 60, 1.0), (b, 1.0)], {a + 60: 1.0, b: 1.0}), [])
        self.assertEqual(T.pairs([(a, 1.0), (b, 1.0)], {a: 1.0, b: 1.0}, skip_days=[DAY]), [])
        self.assertEqual(T.pairs([(a, 0.0), (b, 1.0)], {a: 1.0, b: 1.0}), [])
        self.assertEqual(T.pairs([(a, 1.0), (b, 1.0)], {a: 1.0, b: 0.0}), [])
        self.assertEqual(T.pairs([(a, 1.0), (a + 4_500, 1.0)], {a: 1.0, a + 4_500: 1.0}), [])    # 75 minutes

    def test_a_future_is_all_one_session_through_the_night(self):
        a, b = et(DAY, 22, 0), et(DAY, 23, 0)
        got = T.pairs([(a, 1.0), (b, 1.0)], {a: 1.0, b: 1.0}, futures=True)
        self.assertEqual([s for s, _, _ in got], ["futures hours"])
        self.assertEqual(T.pairs([(a, 1.0), (b, 1.0)], {a: 1.0, b: 1.0}), [])
        c, d = et(DAY, 23, 30), et("2026-10-07", 0, 30)                  # an hour apart, across midnight
        self.assertEqual(T.pairs([(c, 1.0), (d, 1.0)], {c: 1.0, d: 1.0}, futures=True), [])


def rows(n, gap_bps=0.0, wild=0):
    """`n` pairs: the ticker alternates +-1%, the perp differs by `gap_bps`; the first `wild` differ by 80 bps."""
    out = []
    for i in range(n):
        t = 0.01 if i % 2 else -0.01
        out.append((t, t + (80.0 if i < wild else gap_bps) / 1e4))
    return out


class TestTolerance(unittest.TestCase):
    def test_the_numbers(self):
        s = T.stat([(0.01, 0.011), (-0.01, -0.0105), (0.02, 0.02), (0.0, 0.0003)])
        self.assertEqual(s.n, 4)
        self.assertAlmostEqual(s.median_bps, 4.0)
        self.assertAlmostEqual(s.p95_bps, 10.0)
        self.assertAlmostEqual(s.mean_bps, (10 - 5 + 0 + 3) / 4)
        self.assertGreater(s.corr, 0.99)
        self.assertEqual(T.stat([]).n, 0)
        self.assertFalse(T.stat([]).follows)

    def test_the_percentile_is_the_nearest_rank(self):
        self.assertEqual(T.percentile(list(range(1, 101)), 0.95), 95)
        self.assertEqual(T.percentile([5.0], 0.95), 5.0)
        self.assertEqual(T.percentile(list(range(1, 21)), 0.95), 19)

    def test_a_market_follows_at_each_bar_and_not_past_it(self):
        self.assertTrue(T.stat(rows(100, gap_bps=10.0)).follows)
        self.assertFalse(T.stat(rows(99, gap_bps=1.0)).follows)                     # too few pairs
        self.assertFalse(T.stat(rows(100, gap_bps=10.1)).follows)                   # the median gap
        self.assertTrue(T.stat(rows(100, gap_bps=1.0, wild=5)).follows)             # 5 wild of 100: the 95th holds
        self.assertFalse(T.stat(rows(100, gap_bps=1.0, wild=6)).follows)            # 6: it does not
        noisy = [(0.01 if i % 2 else -0.01, (0.0001 if i % 4 < 2 else -0.0001)) for i in range(200)]
        s = T.stat(noisy)
        self.assertLess(s.corr, T.MIN_CORR)
        self.assertFalse(s.follows)
        mirror = T.stat([(x, -x) for x in (0.0002, -0.0002) * 60])               # 4 bps apart, moving opposite
        self.assertEqual((mirror.median_bps <= 10, mirror.p95_bps <= 50, mirror.follows), (True, True, False))

    def test_a_session_stands_in_at_four_markets_in_five_among_those_with_enough_pairs(self):
        good, bad, thin = T.stat(rows(100)), T.stat(rows(100, gap_bps=30.0)), T.stat(rows(10))
        self.assertEqual(T.stands_in([good] * 4 + [bad] + [thin] * 9), (True, 4, 5))
        self.assertEqual(T.stands_in([good] * 3 + [bad] * 1), (False, 3, 4))
        self.assertEqual(T.stands_in([thin]), (None, 0, 0))

    def test_by_session(self):
        got = T.by_session([("regular", 0.01, 0.01), ("regular", 0.0, 0.0), ("pre-market", 0.0, 0.001)])
        self.assertEqual((got["regular"].n, got["pre-market"].n), (2, 1))


class TestBell(unittest.TestCase):
    def test_gaps_at_the_open_and_close_and_the_night_between(self):
        d1, d2, d3 = (et(d, 9, 30) for d in ("2026-10-06", "2026-10-07", "2026-10-08"))
        days = [(d1, 100.0, 102.0), (d2, 103.0, 104.0), (d3, 105.0, 106.0)]
        perp = {d1: 100.1, d1 + 23_400: 102.0, d2: 103.0, d2 + 23_400: 104.208, d3: 105.0, d3 + 23_400: 106.0}
        got = T.bell(days, perp)
        self.assertEqual(got["days"], 3)
        self.assertAlmostEqual(got["open_bps"], 0.0)                      # gaps 10, 0, 0
        self.assertAlmostEqual(got["close_bps"], 0.0)                     # gaps 0, 20, 0
        want = [abs((103.0 / 102.0 - 1) - (103.0 / 102.0 - 1)), abs((105.0 / 104.208 - 1) - (105.0 / 104.0 - 1))]
        self.assertAlmostEqual(got["overnight_bps"], sum(want) / 2 * 1e4)
        skipped = T.bell(days, perp, skip_days=["2026-10-07"])
        self.assertEqual(skipped["days"], 2)
        self.assertIsNone(skipped["overnight_bps"])                       # no night spans a skipped day

    def test_the_bell_stands_in_on_the_median_market(self):
        self.assertTrue(T.bell_stands_in([2.0, 10.0, 40.0, None]))
        self.assertFalse(T.bell_stands_in([2.0, 10.1, 40.0]))
        self.assertIsNone(T.bell_stands_in([None]))


if __name__ == "__main__":
    unittest.main()
