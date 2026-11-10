"""#77's weekly hold on hand-made daily bars: every number below is worked out by hand."""
import datetime as dt
import unittest
from zoneinfo import ZoneInfo

from espero import nightweek as W

ET = ZoneInfo("America/New_York")


def open_ts(day):
    y, m, d = (int(x) for x in day.split("-"))
    return int(dt.datetime(y, m, d, 9, 30, tzinfo=ET).timestamp())


# a normal week, a week with a Monday holiday (starts Tuesday), and a short week of two days (skipped)
DAYS = ["2026-11-02", "2026-11-03", "2026-11-04", "2026-11-05", "2026-11-06",
        "2026-11-10", "2026-11-11", "2026-11-12", "2026-11-13",
        "2026-11-19", "2026-11-20"]
TS = [open_ts(d) for d in DAYS]
O = [100.0, 101.0, 102.0, 103.0, 106.0, 105.0, 104.0, 103.0, 102.0, 110.0, 111.0]
C = [100.5, 101.5, 102.5, 103.5, 105.0, 105.5, 104.5, 103.5, 102.5, 110.5, 111.5]


class TestWeeks(unittest.TestCase):
    def test_monday_to_the_monday_of_the_week(self):
        self.assertEqual(W.week_of("2026-11-06"), "2026-11-02")
        self.assertEqual(W.week_of("2026-11-02"), "2026-11-02")
        self.assertEqual(W.week_of("2026-11-08"), "2026-11-02")

    def test_first_close_to_last_open_weeks_of_three_days_or_more(self):
        self.assertEqual(W.windows(DAYS), {"2026-11-02": (0, 4), "2026-11-09": (5, 8)})
        got = W.weeks(TS, O, C, DAYS)
        gross, net, hours = got["2026-11-02"]
        self.assertAlmostEqual(gross, 106.0 / 100.5 - 1)
        self.assertAlmostEqual(hours, 89.5)                            # Monday 16:00 to Friday 09:30
        self.assertAlmostEqual(net, gross - 28e-4 - 0.10 * 89.5 / 8760)
        gross, net, hours = got["2026-11-09"]
        self.assertAlmostEqual(gross, 102.0 / 105.5 - 1)               # Tuesday's close to Friday's open
        self.assertAlmostEqual(hours, 65.5)
        self.assertNotIn("2026-11-16", got)                            # two trading days

    def test_a_bad_price_and_the_market(self):
        o = list(O)
        o[4] = 0.0
        self.assertNotIn("2026-11-02", W.weeks(TS, o, C, DAYS))
        self.assertEqual(sorted(W.market_weeks(O, C, DAYS)), ["2026-11-02", "2026-11-09"])
        self.assertAlmostEqual(W.market_weeks(O, C, DAYS)["2026-11-02"], 106.0 / 100.5 - 1)
        self.assertNotIn("2026-11-02", W.market_weeks(o, C, DAYS))


class TestCriteria(unittest.TestCase):
    def test_profit_factor_and_breadth(self):
        self.assertAlmostEqual(W.profit_factor([0.03, -0.01, -0.01, 0.0]), 1.5)
        self.assertIsNone(W.profit_factor([0.01]))
        many = {f"w{k}": 0.001 for k in range(100)}
        few = {f"w{k}": 0.001 for k in range(99)}
        bad = {f"w{k}": -0.001 for k in range(100)}
        flat = {f"w{k}": 0.0 for k in range(100)}
        self.assertEqual(W.breadth({"A": many, "B": few, "C": bad, "D": flat}), (1, 3))

    def test_each_criterion(self):
        good = dict(n=250, pf=1.6, mean=0.006, t=3.2, q=0.01, market=0.002, h1=0.004, h2=0.008, up=19, counted=37)
        self.assertEqual(W.verdict(**good), ("PASS", []))
        self.assertEqual(W.verdict(**{**good, "n": 99})[0], "INCONCLUSIVE")
        self.assertEqual(W.verdict(**{**good, "n": 100})[0], "PASS")
        for key, bad in (("pf", 1.49), ("pf", None), ("t", 2.99), ("t", None), ("q", 0.05), ("q", None),
                         ("market", 0.006), ("h1", 0.0), ("h2", -0.1), ("up", 18)):
            got, missed = W.verdict(**{**good, key: bad})
            self.assertEqual((got, len(missed)), ("FAIL", 1), (key, bad))
        got, missed = W.verdict(**{**good, "mean": 0.0, "market": -0.1})
        self.assertEqual((got, len(missed)), ("FAIL", 1))
        self.assertEqual(W.verdict(**{**good, "pf": 1.5, "t": 3.0})[0], "PASS")
        self.assertEqual(W.verdict(**{**good, "counted": 20, "up": 10})[0], "FAIL")
        self.assertEqual(W.verdict(**{**good, "counted": 0, "up": 0})[0], "FAIL")

    def test_the_registered_numbers(self):
        self.assertEqual((W.COST_BPS, W.FUNDING_YEAR, W.SESSION_S, W.MIN_TRADING_DAYS), (14.0, 0.10, 23400.0, 3))
        self.assertEqual((W.MIN_PF, W.MIN_T, W.MAX_Q, W.MIN_WEEKS, W.MIN_MARKET_WEEKS), (1.5, 3.0, 0.05, 100, 100))


if __name__ == "__main__":
    unittest.main()
