"""#76's night shift on hand-made daily bars: every number below is worked out by hand."""
import datetime as dt
import math
import unittest
from zoneinfo import ZoneInfo

from espero import nightshift as N

ET = ZoneInfo("America/New_York")


def open_ts(day):
    y, m, d = (int(x) for x in day.split("-"))
    return int(dt.datetime(y, m, d, 9, 30, tzinfo=ET).timestamp())


DAYS = ["2026-11-05", "2026-11-06", "2026-11-09", "2026-11-10"]      # Thursday, Friday, Monday, Tuesday
TS = [open_ts(d) for d in DAYS]
O = [100.0, 101.0, 104.0, 102.0]
C = [100.5, 102.0, 103.0, 103.0]


class TestNights(unittest.TestCase):
    def test_close_to_next_open_with_costs_and_funding_for_the_hours_held(self):
        got = N.nights(TS, O, C, DAYS)
        self.assertEqual(sorted(got), ["2026-11-06", "2026-11-09"])      # not the first bar's close, not the last's
        gross, net, hours = got["2026-11-06"]
        self.assertAlmostEqual(gross, 104.0 / 102.0 - 1)
        self.assertAlmostEqual(hours, 65.5)                              # Friday 16:00 to Monday 09:30
        self.assertAlmostEqual(net, gross - 28e-4 - 0.10 * 65.5 / 8760)
        self.assertAlmostEqual(got["2026-11-09"][2], 17.5)
        self.assertAlmostEqual(got["2026-11-09"][0], 102.0 / 103.0 - 1)

    def test_other_costs_and_a_bad_price(self):
        got = N.nights(TS, O, C, DAYS, cost_bps=0.0, funding_year=0.0)
        self.assertAlmostEqual(got["2026-11-09"][1], got["2026-11-09"][0])
        self.assertNotIn("2026-11-06", N.nights(TS, [100.0, 101.0, 0.0, 102.0], C, DAYS))

    def test_the_day_from_open_to_close(self):
        got = N.days(O, C, DAYS)
        self.assertEqual(sorted(got), DAYS[1:])
        gross, net = got["2026-11-09"]
        self.assertAlmostEqual(gross, 103.0 / 104.0 - 1)
        self.assertAlmostEqual(net, gross - 28e-4 - 0.10 * 6.5 / 8760)


class TestPortfolio(unittest.TestCase):
    def test_equal_weight_over_the_markets_there_that_day_in_date_order(self):
        p = N.portfolio({"A": {"2026-11-06": 0.01, "2026-11-05": 0.02}, "B": {"2026-11-06": 0.03}})
        self.assertEqual(list(p.index), ["2026-11-05", "2026-11-06"])
        self.assertAlmostEqual(p["2026-11-05"], 0.02)
        self.assertAlmostEqual(p["2026-11-06"], 0.02)
        one = N.portfolio({"A": {"2026-11-06": 0.01, "2026-11-05": 0.02}})
        self.assertEqual(list(one.index), ["2026-11-05", "2026-11-06"])       # sorted with one market too

    def test_profit_factor_halves_breadth(self):
        self.assertAlmostEqual(N.profit_factor([0.03, -0.01, -0.01, 0.0]), 1.5)
        self.assertIsNone(N.profit_factor([0.01]))
        self.assertEqual(N.halves([1.0, 2.0, 3.0, -1.0, -2.0]), (2.0, -1.5))
        many = {f"d{k}": 0.001 for k in range(250)}
        few = {f"d{k}": 0.001 for k in range(249)}
        bad = {f"d{k}": -0.001 for k in range(250)}
        flat = {f"d{k}": 0.0 for k in range(250)}
        self.assertEqual(N.breadth({"A": many, "B": few, "C": bad, "D": flat}), (1, 3))

    def test_the_p_value(self):
        self.assertAlmostEqual(N.two_sided_p(1.96), 0.05, places=3)
        self.assertAlmostEqual(N.two_sided_p(-3.0), math.erfc(3 / math.sqrt(2)))


class TestVerdict(unittest.TestCase):
    def test_each_criterion(self):
        good = dict(n=1200, pf=1.6, mean=0.001, t=3.2, q=0.01, night=0.001, day=-0.002, h1=0.001, h2=0.0005,
                    up=19, counted=37)
        self.assertEqual(N.verdict(**good), ("PASS", []))
        self.assertEqual(N.verdict(**{**good, "n": 499})[0], "INCONCLUSIVE")
        self.assertEqual(N.verdict(**{**good, "n": 500})[0], "PASS")
        for key, bad in (("pf", 1.49), ("pf", None), ("mean", 0.0), ("t", 2.99), ("t", None), ("q", 0.05), ("q", None),
                         ("night", -0.002), ("h1", 0.0), ("h2", -0.1), ("up", 18)):
            got, missed = N.verdict(**{**good, key: bad})
            self.assertEqual((got, len(missed)), ("FAIL", 1), (key, bad))
        self.assertEqual(N.verdict(**{**good, "pf": 1.5, "t": 3.0})[0], "PASS")
        self.assertEqual(N.verdict(**{**good, "counted": 0, "up": 0})[0], "FAIL")
        self.assertEqual(N.verdict(**{**good, "counted": 20, "up": 10})[0], "FAIL")      # half is not more than half

    def test_the_registered_numbers(self):
        self.assertEqual((N.COST_BPS, N.FUNDING_YEAR, N.SESSION_S, N.HOURS_YEAR), (14.0, 0.10, 23400.0, 8760))
        self.assertEqual((N.MIN_PF, N.MIN_T, N.MAX_Q, N.MIN_NIGHTS, N.MIN_MARKET_NIGHTS), (1.5, 3.0, 0.05, 500, 250))


if __name__ == "__main__":
    unittest.main()
