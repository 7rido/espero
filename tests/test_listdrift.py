"""#67's rule (research/PREREGISTRATION_LISTDRIFT.md), on made-up data only."""
import importlib.util
import unittest
from pathlib import Path
from unittest import mock

import numpy as np
import pandas as pd

from espero import listdrift as ld

ROOT = Path(__file__).resolve().parents[1]
D = pd.Timestamp


def ms(day: str, hours: float = 0.0, extra_ms: int = 5) -> int:
    return int(D(day).value // 1_000_000 + hours * 3_600_000 + extra_ms)


def bars(days, opens, closes, volume=None):
    idx = pd.DatetimeIndex([D(d) for d in days])
    out = pd.DataFrame({"open": opens, "close": closes}, index=idx, dtype=float)
    out["quote_volume"] = volume if volume is not None else 1.0
    return out


def runner():
    spec = importlib.util.spec_from_file_location("research_listdrift", ROOT / "research" / "listdrift.py")
    r = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(r)
    return r


class TestEvents(unittest.TestCase):
    def test_base_drops_the_multiplier(self):
        self.assertEqual([ld.base(s) for s in ("1000PEPEUSDT", "1000000BOBUSDT", "1MBABYDOGEUSDT", "ARBUSDT")],
                         ["PEPE", "BOB", "BABYDOGE", "ARB"])

    def test_classify(self):
        meta = {
            "NEWUSDT": {"type": "COIN", "onboard_ms": ms("2023-05-10", 12)},
            "1000PEPEUSDT": {"type": "COIN", "onboard_ms": ms("2023-05-05", 12)},
            "AAPLUSDT": {"type": "EQUITY", "onboard_ms": ms("2025-09-01", 12)},
            "RELUSDT": {"type": "COIN", "onboard_ms": ms("2025-03-01", 12)},
            "NOTIMEUSDT": {"type": "COIN", "onboard_ms": None},
            "DEFIUSDT": {"type": "COIN", "onboard_ms": ms("2023-02-01", 12)},
        }
        firsts = {"PEPEUSDT": "2022-06", "NEWUSDT": "2023-05", "1000PEPEUSDT": "2023-05", "AAPLUSDT": "2025-09",
                  "RELUSDT": "2024-02", "NOTIMEUSDT": "2023-07", "DEFIUSDT": "2023-02", "XYZUSDC": "2024-01",
                  "BTCUSDT_230630": "2023-01", "OLDUSDT": "2021-01"}
        c = ld.classify(meta, firsts).set_index("symbol")
        self.assertEqual(sorted(c.index), ["1000PEPEUSDT", "AAPLUSDT", "DEFIUSDT", "NEWUSDT", "NOTIMEUSDT", "RELUSDT"])
        self.assertEqual(c.at["NEWUSDT", "excluded"], "")
        self.assertEqual(c.at["NEWUSDT", "listing_day"], D("2023-05-10"))
        self.assertEqual(c.at["1000PEPEUSDT", "excluded"], "base listed before")
        self.assertEqual(c.at["AAPLUSDT", "excluded"], "type EQUITY")
        self.assertEqual(c.at["RELUSDT", "excluded"], "listing month differs from the first bar's")
        self.assertEqual(c.at["NOTIMEUSDT", "excluded"], "no listing time")
        self.assertEqual(c.at["DEFIUSDT", "excluded"], "index")

    def test_the_listing_day_is_the_first_trade(self):
        days = [D("2023-05-10"), D("2023-06-01"), D("2023-07-01")]
        ev = pd.DataFrame({"symbol": ["A", "B", "C"], "listing_day": days})
        d = ld.dated(ev, {"A": D("2023-05-11"), "B": D("2023-06-01")}).set_index("symbol")
        self.assertEqual(list(d.index), ["A", "B"])                      # C has no bar: dropped
        self.assertEqual(d.at["A", "listing_day"], D("2023-05-11"))
        self.assertEqual(d.at["A", "onboard_day"], D("2023-05-10"))
        self.assertEqual(d.at["B", "listing_day"], D("2023-06-01"))

    def test_window_and_span(self):
        entry, exit_ = ld.window(D("2023-05-10"), 14)
        self.assertEqual((entry, exit_), (D("2023-05-11"), D("2023-05-25")))
        self.assertEqual(ld.window(D("2023-05-10"), 14, entry_lag=2)[0], D("2023-05-12"))
        self.assertTrue(ld.inside(entry, exit_, (D("2023-01-01"), D("2023-05-25"))))
        self.assertFalse(ld.inside(entry, exit_, (D("2023-01-01"), D("2023-05-24"))))
        self.assertFalse(ld.inside(entry, exit_, (D("2023-05-12"), D("2023-12-31"))))


class TestLeg(unittest.TestCase):
    def setUp(self):
        days = pd.date_range("2023-05-11", "2023-05-15", freq="D").strftime("%Y-%m-%d")
        self.b = bars(days, [100, 110, 121, 100, 92], [110, 121, 100, 90, 95])

    def test_a_long_earns_open_to_open(self):
        p = ld.leg(self.b, D("2023-05-11"), D("2023-05-15"), +1)
        self.assertEqual(list(p.index), list(pd.date_range("2023-05-11", "2023-05-15")))
        self.assertAlmostEqual(p["pnl"].sum(), (92 - 100) / 100)
        self.assertAlmostEqual(p["pnl"].iloc[0], (110 - 100) / 100)
        self.assertAlmostEqual(p["pnl"].iloc[-1], (92 - 90) / 100)
        self.assertAlmostEqual(p["ratio"].iloc[1], 1.21)
        s = ld.leg(self.b, D("2023-05-11"), D("2023-05-15"), -1)
        self.assertAlmostEqual(s["pnl"].sum(), 0.08)

    def test_a_listing_that_stops_exits_at_its_last_close(self):
        short = self.b.iloc[:3]
        p = ld.leg(short, D("2023-05-11"), D("2023-05-15"), -1)
        self.assertEqual(p.index[-1], D("2023-05-13"))
        self.assertAlmostEqual(p["pnl"].sum(), -(100 - 100) / 100)

    def test_a_missing_day_carries_the_close_and_no_entry_bar_is_nothing(self):
        gap = self.b.drop(D("2023-05-12"))
        p = ld.leg(gap, D("2023-05-11"), D("2023-05-15"), +1)
        self.assertEqual(p.at[D("2023-05-12"), "pnl"], 0.0)
        self.assertAlmostEqual(p["pnl"].sum(), (92 - 100) / 100)
        self.assertTrue(ld.leg(self.b, D("2023-05-10"), D("2023-05-15"), +1).empty)


class TestFunding(unittest.TestCase):
    def test_settlements_inside_the_hold_booked_on_the_day_they_end(self):
        days = pd.date_range("2023-05-11", "2023-05-14", freq="D").strftime("%Y-%m-%d")
        b = bars(days, [100, 100, 100, 100], [100, 200, 100, 100])
        path = ld.leg(b, D("2023-05-11"), D("2023-05-14"), -1)
        rates = pd.Series([0.01, 0.02, 0.03, 0.04],
                          index=[ms("2023-05-11"), ms("2023-05-12", 8), ms("2023-05-14"), ms("2023-05-14", 8)])
        f = ld.funding(rates, path, D("2023-05-11"), D("2023-05-14"), -1)
        self.assertEqual(sorted(f.index), [D("2023-05-12"), D("2023-05-13")])
        self.assertAlmostEqual(f[D("2023-05-12")], 0.02 * 2.0)        # a short receives, scaled by the close
        self.assertAlmostEqual(f[D("2023-05-13")], 0.03 * 1.0)        # the exit's 00:00 settlement, on the day before
        g = ld.funding(rates, ld.leg(b, D("2023-05-11"), D("2023-05-14"), +1), D("2023-05-11"), D("2023-05-14"), +1)
        self.assertAlmostEqual(g.sum(), -(0.02 * 2.0 + 0.03))


class TestEvent(unittest.TestCase):
    def setUp(self):
        days = pd.date_range("2023-05-11", "2023-05-16", freq="D").strftime("%Y-%m-%d")
        self.coin = bars(days, [100, 90, 80, 70, 60, 50], [90, 80, 70, 60, 50, 45])
        self.btc = bars(days, [100, 101, 102, 104, 105, 106], [101, 102, 103, 105, 106, 107])
        self.none = pd.Series(dtype=float)

    def test_net_is_both_legs_funding_and_four_fills(self):
        e = ld.event(self.coin, self.btc, D("2023-05-11"), D("2023-05-16"), self.none, self.none, 0.0015, 0.0005)
        self.assertAlmostEqual(e["short"].sum(), (100 - 50) / 100)
        self.assertAlmostEqual(e["long"].sum(), (106 - 100) / 100)
        self.assertAlmostEqual(e["cost"].sum(), -2 * (0.0015 + 0.0005))
        self.assertAlmostEqual(e["net"].sum(), 0.50 + 0.06 - 0.004)

    def test_the_hedge_closes_when_the_listing_stops(self):
        stops = self.coin.iloc[:3]
        e = ld.event(stops, self.btc, D("2023-05-11"), D("2023-05-16"), self.none, self.none, 0.0, 0.0)
        self.assertEqual(e.index[-1], D("2023-05-13"))
        self.assertAlmostEqual(e["long"].sum(), (103 - 100) / 100)
        self.assertAlmostEqual(e["short"].sum(), (100 - 70) / 100)

    def test_the_hedge_leg_ends_on_the_listings_last_day(self):
        s = ld.leg(self.coin.iloc[:3], D("2023-05-11"), D("2023-05-16"), -1)
        h = ld.hedge_leg(self.btc, D("2023-05-11"), s, D("2023-05-16"))
        self.assertEqual(h.index[-1], D("2023-05-13"))
        self.assertAlmostEqual(h["pnl"].sum(), (103 - 100) / 100)

    def test_the_basket_and_its_stopped_members(self):
        stops = self.btc.iloc[:2]
        b = ld.basket([ld.leg(self.btc, D("2023-05-11"), D("2023-05-16"), +1),
                       ld.leg(stops, D("2023-05-11"), D("2023-05-16"), +1)])
        self.assertAlmostEqual(b["pnl"].sum(), ((106 - 100) / 100 + (102 - 100) / 100) / 2)
        a = ld.abnormal(self.coin, {"B": self.btc}, D("2023-05-11"), D("2023-05-16"))
        self.assertAlmostEqual(a["net"].sum(), 0.50 + 0.06)

    def test_break_even(self):
        e = {"A": ld.event(self.coin, self.btc, D("2023-05-11"), D("2023-05-16"), self.none, self.none, 0.0015, 0.0)}
        net = e["A"]["net"].sum()
        self.assertAlmostEqual(ld.break_even_bps(e, 0.0015), (net + 0.003) / 2 * 1e4)


class TestBasketMembers(unittest.TestCase):
    def test_established_liquid_and_known_before_the_entry(self):
        days = pd.date_range("2022-01-01", "2023-06-30", freq="D")
        vol = pd.DataFrame({"OLDBIG": 100.0, "OLDSMALL": 10.0, "YOUNG": 1000.0, "GAPPY": 500.0, "SKIP": 900.0,
                            "OLDMID": 50.0}, index=days)
        vol.loc[D("2023-05-20"), "GAPPY"] = np.nan
        vol.loc[D("2023-06-01"), "OLDSMALL"] = 1e9                   # the entry day itself must not count
        first = {"OLDBIG": D("2022-01-01"), "OLDSMALL": D("2022-01-01"), "YOUNG": D("2023-01-01"),
                 "GAPPY": D("2022-01-01"), "SKIP": D("2022-01-01"), "OLDMID": D("2022-01-01")}
        m = ld.basket_members(vol, first, D("2023-06-01"), excluded={"SKIP"}, n=2)
        self.assertEqual(m, ["OLDBIG", "OLDMID"])


def synthetic(n=150, mu=0.002, sd=0.004, seed=1, start="2025-01-01", spacing=4, hold=14, abnormal_mu=None):
    rng = np.random.default_rng(seed)
    net, abn = {}, {}
    for i in range(n):
        idx = pd.date_range(D(start) + pd.Timedelta(days=spacing * i), periods=hold, freq="D")
        net[f"E{i}"] = pd.DataFrame({"net": rng.normal(mu, sd, hold)}, index=idx)
        am = mu if abnormal_mu is None else abnormal_mu
        abn[f"E{i}"] = pd.DataFrame({"net": rng.normal(am, sd, hold)}, index=idx)
    return net, abn


class TestSeries(unittest.TestCase):
    def test_calendar_averages_the_open_positions(self):
        a = pd.DataFrame({"net": [1.0, 2.0]}, index=pd.date_range("2025-01-01", periods=2))
        b = pd.DataFrame({"net": [3.0, 5.0]}, index=pd.date_range("2025-01-02", periods=2))
        c = ld.calendar({"a": a, "b": b})
        self.assertEqual(list(c["mean"]), [1.0, 2.5, 5.0])
        self.assertEqual(list(c["open"]), [1, 2, 1])
        self.assertEqual(dict(ld.totals({"a": a, "b": b})), {"a": 3.0, "b": 8.0})

    def test_lags_and_halves(self):
        self.assertEqual([ld.nw_lags(n) for n in (39, 100, 638, 730, 10000)], [3, 4, 6, 6, 11])
        self.assertEqual(ld.halves(pd.Series([1.0, 2.0, 3.0, 4.0, 5.0])), (2.0, 4.5))


class TestCriteria(unittest.TestCase):
    def test_a_clear_drift_waits_for_the_ledger_then_passes(self):
        net, abn = synthetic()
        ev = ld.evaluate(net, abn)
        self.assertGreaterEqual(ev["t"], 3)
        self.assertIn("ledger", ev["outcome"])
        self.assertEqual(ld.evaluate(net, abn, q=0.01)["outcome"], ld.PASS)
        self.assertEqual(ld.evaluate(net, abn, q=0.2)["outcome"], ld.FAIL)

    def test_a_t_under_three_fails(self):
        net, abn = synthetic(mu=0.00025, sd=0.004, seed=2)
        ev = ld.evaluate(net, abn, q=0.01)
        self.assertTrue(2 < ev["t"] < 3, ev["t"])
        self.assertGreater(min(ev["first_half"], ev["second_half"]), 0)
        self.assertEqual(ev["outcome"], ld.FAIL)

    def test_no_drift_against_the_basket_fails(self):
        net, abn = synthetic(abnormal_mu=-0.001)
        ev = ld.evaluate(net, abn, q=0.01)
        self.assertGreaterEqual(ev["t"], 3)
        self.assertLess(ev["abnormal_mean"], 0)
        self.assertEqual(ev["outcome"], ld.FAIL)

    def test_a_few_collapses_with_most_positions_losing_fails(self):
        net, abn = synthetic(mu=-0.0004, sd=0.0005, seed=3, abnormal_mu=0.002)
        for i in range(0, 150, 10):
            net[f"E{i}"]["net"] = 0.05                                 # one position in ten collapses
        ev = ld.evaluate(net, abn, q=0.01)
        self.assertGreaterEqual(ev["t"], 3)
        self.assertLess(ev["median_event"], 0)
        self.assertEqual(ev["outcome"], ld.FAIL)

    def test_one_bad_half_fails(self):
        good, abn = synthetic(n=75, mu=0.004, seed=4)
        bad, abn2 = synthetic(n=75, mu=-0.0005, seed=5, start="2025-10-27")
        net = {**good, **{f"L{k}": v for k, v in bad.items()}}
        ab = {**abn, **{f"L{k}": v for k, v in abn2.items()}}
        ev = ld.evaluate(net, ab, q=0.01)
        self.assertGreaterEqual(ev["t"], 3)
        self.assertGreater(ev["median_event"], 0)
        self.assertLess(ev["second_half"], 0)
        self.assertEqual(ev["outcome"], ld.FAIL)

    def test_too_few_positions_is_inconclusive(self):
        net, abn = synthetic(n=99, spacing=7)
        self.assertEqual(ld.evaluate(net, abn, q=0.01)["outcome"], ld.INCONCLUSIVE)
        net, abn = synthetic(n=100, spacing=7)
        self.assertEqual(ld.evaluate(net, abn, q=0.01)["outcome"], ld.PASS)


class TestRunner(unittest.TestCase):
    def test_the_design_run_reads_nothing_after_2024(self):
        r = runner()
        self.assertTrue(r.readable("2024-12", ld.DESIGN_LAST_MONTH))
        self.assertFalse(r.readable("2025-01", ld.DESIGN_LAST_MONTH))
        self.assertFalse(r.readable("2025-01-03", ld.DESIGN_LAST_MONTH))
        self.assertEqual(r.months_between(D("2024-11-25"), D("2025-01-02")), ["2024-11", "2024-12", "2025-01"])
        with mock.patch.object(r.pit, "fetch_file", side_effect=AssertionError("no network in tests")):
            with self.assertRaises(SystemExit):
                r.funding_rates("NEWUSDT", ["2025-01"], ld.DESIGN_LAST_MONTH, [])

    def test_the_holdout_waits_for_its_hold(self):
        self.assertTrue(ld.CHOSEN_HOLD is None or ld.CHOSEN_HOLD in ld.HOLDS)


if __name__ == "__main__":
    unittest.main(verbosity=2)
