"""#66's rule (research/PREREGISTRATION_VOLF.md), on made-up data only."""
import importlib.util
import math
import unittest
from pathlib import Path

import numpy as np
import pandas as pd

from espero import volf as vf

ROOT = Path(__file__).resolve().parents[1]
DAY = 86_400
START = pd.Timestamp("2021-01-01")


def bars(days, start=START, drop=None, flat=None, seed=0):
    """`days` days of 288 five-minute closes on a random walk; `drop` maps a day to bar numbers left out, `flat`
    is a set of days whose closes do not move."""
    rng = np.random.default_rng(seed)
    t0 = int(start.timestamp())
    ts, cl, price = [], [], 100.0
    for k in range(days):
        for b in range(288):
            if k not in (flat or set()):
                price *= math.exp(rng.normal(0, 0.002))
            if drop and b in drop.get(k, ()):
                continue
            ts.append(t0 + k * DAY + b * 300)
            cl.append(price)
    return pd.DataFrame({"close": cl}, index=pd.Index(ts, name="ts"))


def runner():
    spec = importlib.util.spec_from_file_location("research_volf", ROOT / "research" / "volf.py")
    r = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(r)
    return r


class TestDays(unittest.TestCase):
    def test_variance_and_return_of_a_complete_day(self):
        b = bars(3)
        d = vf.daily(b)
        self.assertFalse(d["complete"].iloc[0])                      # no previous close
        self.assertTrue(d["complete"].iloc[1])
        lc = np.log(b["close"].to_numpy())
        day1 = lc[287:576]                                            # the previous 23:55 close, then day 1's bars
        self.assertAlmostEqual(d["rv"].iloc[1], float(np.sum(np.diff(day1) ** 2)), places=12)
        self.assertAlmostEqual(d["ret"].iloc[1], lc[575] - lc[287], places=12)
        self.assertEqual(d.index[1], START + pd.Timedelta(days=1))

    def test_a_day_needs_276_bars(self):
        twelve = vf.daily(bars(3, drop={1: set(range(100, 112))}))
        thirteen = vf.daily(bars(3, drop={1: set(range(100, 113))}))
        self.assertTrue(twelve["complete"].iloc[1])
        self.assertFalse(thirteen["complete"].iloc[1])
        self.assertTrue(np.isnan(thirteen["rv"].iloc[1]) and np.isnan(thirteen["ret"].iloc[1]))

    def test_a_day_needs_its_own_close_and_yesterdays(self):
        d = vf.daily(bars(4, drop={1: {287}}))
        self.assertFalse(d["complete"].iloc[1])                       # no 23:55 bar
        self.assertFalse(d["complete"].iloc[2])                       # no previous close
        self.assertTrue(d["complete"].iloc[3])

    def test_a_day_that_does_not_move_is_not_scored(self):
        d = vf.daily(bars(4, flat={2}))
        self.assertFalse(d["complete"].iloc[2])
        self.assertTrue(d["complete"].iloc[3])

    def test_a_missing_day_stays_on_the_calendar(self):
        b = bars(5)
        b = b[(b.index < int(START.timestamp()) + 2 * DAY) | (b.index >= int(START.timestamp()) + 3 * DAY)]
        d = vf.daily(b)
        self.assertEqual(len(d), 5)
        self.assertFalse(d["complete"].iloc[2])
        self.assertFalse(d["complete"].iloc[3])


class TestWindows(unittest.TestCase):
    def setUp(self):
        idx = pd.date_range("2021-01-01", periods=60, freq="D")
        self.rv = pd.Series(np.linspace(1e-4, 7e-4, 60), index=idx)
        self.ret = pd.Series(np.random.default_rng(1).normal(0, 0.03, 60), index=idx)

    def test_har_features(self):
        f = vf.har_features(self.rv)
        self.assertAlmostEqual(f["d1"].iloc[40], math.log(self.rv.iloc[40]))
        self.assertAlmostEqual(f["d7"].iloc[40], math.log(self.rv.iloc[34:41].mean()))
        self.assertAlmostEqual(f["d30"].iloc[40], math.log(self.rv.iloc[11:41].mean()))
        self.assertTrue(np.isnan(f["d30"].iloc[28]))
        gap = self.rv.copy()
        gap.iloc[35] = np.nan
        g = vf.har_features(gap)
        self.assertTrue(np.isnan(g["d7"].iloc[40]) and np.isnan(g["d30"].iloc[40]))
        self.assertFalse(np.isnan(g["d7"].iloc[42]))

    def test_trailing_variance_is_the_books_estimator(self):
        v = vf.trailing_var(self.ret, 30)
        self.assertAlmostEqual(v.iloc[45], float(np.var(self.ret.iloc[16:46], ddof=1)), places=14)
        self.assertTrue(np.isnan(v.iloc[28]))

    def test_the_target_is_the_next_h_days(self):
        y = vf.forward_mean_sq(self.ret, 7)
        self.assertAlmostEqual(y.iloc[10], float((self.ret.iloc[11:18] ** 2).mean()), places=14)
        self.assertTrue(np.isnan(y.iloc[53]))
        self.assertFalse(np.isnan(y.iloc[52]))

    def test_the_month_target_is_the_next_calendar_month(self):
        idx = pd.date_range("2021-01-01", "2021-03-31", freq="D")
        ret = pd.Series(np.arange(len(idx), dtype=float) / 100, index=idx)
        feb = ret["2021-02-01":"2021-02-28"]
        self.assertAlmostEqual(vf.month_target(ret, pd.Timestamp("2021-01-31")), float((feb ** 2).mean()))
        ret.loc["2021-02-14"] = np.nan
        self.assertTrue(np.isnan(vf.month_target(ret, pd.Timestamp("2021-01-31"))))

    def test_origins(self):
        self.assertEqual(vf.sundays(pd.Timestamp("2023-01-01"), pd.Timestamp("2023-01-21")),
                         [pd.Timestamp("2023-01-01"), pd.Timestamp("2023-01-08")])
        self.assertEqual(vf.month_ends(pd.Timestamp("2022-12-31"), pd.Timestamp("2023-03-31")),
                         [pd.Timestamp("2022-12-31"), pd.Timestamp("2023-01-31"), pd.Timestamp("2023-02-28")])
        week = vf.sundays(vf.HOLDOUT_FIRST_ORIGIN, vf.HOLDOUT_LAST_DAY)
        self.assertEqual((week[0], week[-1], len(week)), (pd.Timestamp("2023-01-01"), pd.Timestamp("2026-03-22"), 169))
        self.assertEqual(len(vf.month_ends(pd.Timestamp("2022-12-31"), vf.HOLDOUT_LAST_DAY)), 39)

    def test_the_design_run_opens_nothing_after_2022(self):
        self.assertEqual(vf.months_through("2020-03"), ["2020-01", "2020-02", "2020-03"])
        self.assertTrue(vf.readable("2022-12", design=True))
        self.assertFalse(vf.readable("2023-01", design=True))
        self.assertTrue(vf.readable("2026-03", design=False))
        self.assertFalse(vf.readable("2026-04", design=False))
        with self.assertRaises(SystemExit):
            runner().month_klines("BTCUSDT", "2023-01", design=True)


class TestModel(unittest.TestCase):
    def test_fit_recovers_a_log_linear_rule_and_smears(self):
        rng = np.random.default_rng(2)
        x = rng.normal(size=(300, 2))
        y = np.exp(0.5 + 0.3 * x[:, 0] - 0.2 * x[:, 1])
        beta, smear = vf.fit(x, y)
        np.testing.assert_allclose(beta, [0.5, 0.3, -0.2], atol=1e-10)
        self.assertAlmostEqual(smear, 1.0, places=10)
        e = rng.normal(0, 0.5, 300)
        beta, smear = vf.fit(x, y * np.exp(e))
        resid = np.log(y * np.exp(e)) - np.column_stack([np.ones(300), x]) @ beta
        self.assertAlmostEqual(smear, float(np.mean(np.exp(resid))), places=12)
        self.assertGreater(smear, 1.05)
        self.assertAlmostEqual(vf.predict(beta, smear, x[0]), math.exp(beta[0] + beta[1:] @ x[0]) * smear)

    def frame(self, n=600):
        rng = np.random.default_rng(3)
        idx = pd.date_range("2020-01-01", periods=n, freq="D")
        feats = pd.DataFrame(rng.normal(size=(n, 3)), index=idx, columns=["d1", "d7", "d30"])
        y = pd.Series(np.exp(rng.normal(size=n)), index=idx)
        return feats, y, idx

    def test_no_target_ending_after_the_origin_is_used(self):
        feats, y, idx = self.frame()
        origin = idx[500]
        base = vf.forecasts(feats, y, [origin], 7).iloc[0]
        late = y.copy()
        late.iloc[494:501] *= 50.0                         # targets ending after the origin
        self.assertAlmostEqual(vf.forecasts(feats, late, [origin], 7).iloc[0], base, places=12)
        edge = y.copy()
        edge.iloc[493] *= 50.0                             # the last target that ends on the origin
        self.assertNotAlmostEqual(vf.forecasts(feats, edge, [origin], 7).iloc[0], base, places=6)

    def test_too_few_rows_or_a_missing_input_gives_nothing(self):
        feats, y, idx = self.frame()
        self.assertTrue(np.isnan(vf.forecasts(feats, y, [idx[360]], 7).iloc[0]))     # 354 rows
        self.assertFalse(np.isnan(vf.forecasts(feats, y, [idx[371]], 7).iloc[0]))    # 365 rows
        gap = feats.copy()
        gap.iloc[400, 1] = np.nan
        self.assertTrue(np.isnan(vf.forecasts(gap, y, [idx[400]], 7).iloc[0]))
        self.assertTrue(np.isnan(vf.forecasts(feats, y, [pd.Timestamp("2030-01-01")], 7).iloc[0]))


def cells(n_origins=120, coins=("A", "B", "C"), har_noise=0.2, bench_noise=0.8, seed=5, noise=None):
    """Weekly cells whose forecasts miss the target by log-normal noise; `noise` maps a coin to (har, bench)."""
    rng = np.random.default_rng(seed)
    rows = []
    for o in pd.date_range("2023-01-01", periods=n_origins, freq="W-SUN"):
        for c in coins:
            h, b = (noise or {}).get(c, (har_noise, bench_noise))
            y = math.exp(rng.normal(-7, 1))
            rows.append({"origin": o, "coin": c, "y": y, "bench": y * math.exp(rng.normal(0, b)),
                         "har": y * math.exp(rng.normal(0, h))})
    return pd.DataFrame(rows)


class TestScoring(unittest.TestCase):
    def test_qlike(self):
        self.assertEqual(float(vf.qlike(2.0, 2.0)), 0.0)
        self.assertAlmostEqual(float(vf.qlike(2.0, 1.0)), 1 - math.log(2), places=12)
        self.assertGreater(float(vf.qlike(2.0, 1.0)), float(vf.qlike(1.0, 2.0)))    # too low costs more

    def test_cells_are_scored_on_what_both_cover_and_positive_means_har_better(self):
        c = pd.DataFrame({"origin": pd.to_datetime(["2023-01-01"] * 2 + ["2023-01-08"] * 2), "coin": list("ABAB"),
                          "y": [1.0, 1.0, 1.0, 1.0], "bench": [2.0, 2.0, 2.0, 2.0], "har": [1.0, np.nan, 1.0, 1.0]})
        s = vf.scored(c, "bench", "har")
        self.assertEqual(len(s), 3)
        d = vf.per_origin(c, "bench", "har")
        self.assertAlmostEqual(d.iloc[0], float(vf.qlike(1.0, 2.0)))
        self.assertGreater(d.iloc[1], 0)
        self.assertLess(vf.per_origin(c, "har", "bench").iloc[1], 0)

    def test_the_standards_lags(self):
        self.assertEqual([vf.nw_lags(n) for n in (39, 100, 169, 1185)], [3, 4, 4, 6])

    def test_halves_give_the_earlier_half_an_odd_origin(self):
        self.assertEqual(vf.halves(pd.Series([1.0, 2.0, 3.0, 4.0, 5.0])), (2.0, 4.5))

    def test_breadth_counts_coins_with_a_year_of_cells(self):
        rows = []
        for i in range(60):
            o = pd.Timestamp("2023-01-01") + pd.Timedelta(weeks=i)
            rows += [{"origin": o, "coin": "A", "y": 1.0, "bench": 2.0, "har": 1.0},
                     {"origin": o, "coin": "B", "y": 1.0, "bench": 1.0, "har": 2.0}]
            if i < 10:
                rows.append({"origin": o, "coin": "C", "y": 1.0, "bench": 2.0, "har": 1.0})
        share, n = vf.breadth(pd.DataFrame(rows), "bench", "har")
        self.assertEqual((share, n), (0.5, 2))


class TestCriteria(unittest.TestCase):
    def test_a_clear_win_waits_for_the_ledger_then_passes(self):
        week, month = cells(), cells(n_origins=39)
        ev = vf.evaluate(week, month)
        self.assertGreaterEqual(ev["t"], 3)
        self.assertIn("ledger", ev["outcome"])
        self.assertEqual(vf.evaluate(week, month, q=0.01)["outcome"], vf.PASS)
        self.assertEqual(vf.evaluate(week, month, q=0.2)["outcome"], vf.FAIL)

    def test_a_month_against_it_is_a_pass_at_a_week(self):
        month = cells(n_origins=39, har_noise=0.8, bench_noise=0.2)
        self.assertEqual(vf.evaluate(cells(), month, q=0.01)["outcome"], vf.PASS_WEEK)

    def test_no_edge_fails_and_too_few_origins_is_inconclusive(self):
        even = cells(har_noise=0.5, bench_noise=0.5)
        self.assertEqual(vf.evaluate(even, cells(n_origins=39), q=0.01)["outcome"], vf.FAIL)
        self.assertEqual(vf.evaluate(cells(n_origins=99), cells(n_origins=39), q=0.01)["outcome"], vf.INCONCLUSIVE)
        self.assertEqual(vf.evaluate(cells(n_origins=100), cells(n_origins=39), q=0.01)["outcome"], vf.PASS)

    def test_a_t_under_three_fails(self):
        weak = cells(har_noise=0.45, bench_noise=0.5, seed=14)
        ev = vf.evaluate(weak, cells(n_origins=39), q=0.01)
        self.assertTrue(2 < ev["t"] < 3)
        self.assertGreater(min(ev["first_half"], ev["second_half"]), 0)
        self.assertGreater(ev["breadth"], 0.5)
        self.assertEqual(ev["outcome"], vf.FAIL)

    def test_one_bad_half_fails(self):
        good = cells(n_origins=60, har_noise=0.2, bench_noise=1.2, seed=6)
        bad = cells(n_origins=60, har_noise=0.7, bench_noise=0.5, seed=7)
        bad["origin"] = bad["origin"] + pd.Timedelta(weeks=60)
        ev = vf.evaluate(pd.concat([good, bad], ignore_index=True), cells(n_origins=39), q=0.01)
        self.assertGreaterEqual(ev["t"], 3)
        self.assertGreater(ev["breadth"], 0.5)
        self.assertLess(ev["second_half"], 0)
        self.assertEqual(ev["outcome"], vf.FAIL)

    def test_one_coin_carrying_the_mean_fails(self):
        lopsided = cells(n_origins=600, noise={"A": (0.1, 1.5), "B": (0.7, 0.5), "C": (0.7, 0.5)}, seed=9)
        ev = vf.evaluate(lopsided, cells(n_origins=39), q=0.01)
        self.assertGreaterEqual(ev["t"], 3)
        self.assertGreater(min(ev["first_half"], ev["second_half"]), 0)
        self.assertAlmostEqual(ev["breadth"], 1 / 3)
        self.assertEqual(ev["outcome"], vf.FAIL)


class TestInformation(unittest.TestCase):
    def test_sizing(self):
        c = pd.DataFrame({"origin": pd.to_datetime(["2023-01-01", "2023-01-08"] * 2), "coin": ["A", "A", "B", "B"],
                          "y": [9.0, 1.0, 1.0, 1.0], "f": [1.0, 4.0, 1.0, 1.0]})
        s = vf.sizing(c, "f")
        self.assertAlmostEqual(s["mean_abs_log_ratio"], (math.log(3) + math.log(2)) / 4)
        self.assertAlmostEqual(s["share_over_2x"], 0.25)
        self.assertAlmostEqual(s["scale_change"], math.log(2) / 2)       # per coin: A moves, B does not

    def test_mse_ratio_and_groups(self):
        c = pd.DataFrame({"origin": pd.to_datetime(["2023-01-01", "2024-01-07"]), "coin": ["A", "B"],
                          "y": [1.0, 1.0], "bench": [3.0, 2.0], "har": [2.0, 1.0]})
        self.assertAlmostEqual(vf.mse_ratio(c, "bench", "har"), (4 + 1) / (1 + 0))
        g = vf.by_group(c, "bench", "har", c["origin"].dt.year)
        self.assertEqual(list(g.index), [2023, 2024])
        self.assertEqual(list(g["size"]), [1, 1])


if __name__ == "__main__":
    unittest.main(verbosity=2)
