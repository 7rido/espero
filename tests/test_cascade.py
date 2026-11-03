"""#72's rule (research/EXPLORE_CASCADE.md), on made-up data only."""
import math
import unittest

import numpy as np
import pandas as pd

from espero import cascade as cs

DAY = 86_400
T0 = int(pd.Timestamp("2022-03-01").timestamp())


def tape(days, hourly_drop_on=None, seed=0, sigma=0.001, drop=0.05):
    """`days` days of 288 five-minute closes on a random walk; on day `hourly_drop_on` the price falls `drop`
    over the hour from 12:00."""
    rng = np.random.default_rng(seed)
    ts, cl, price = [], [], 100.0
    for k in range(days):
        for b in range(288):
            price *= math.exp(rng.normal(0, sigma))
            if hourly_drop_on is not None and k == hourly_drop_on and 144 <= b < 156:
                price *= math.exp(-drop / 12)
            ts.append(T0 + k * DAY + b * 300)
            cl.append(price)
    return pd.DataFrame({"close": cl, "volume": 1000.0}, index=pd.Index(ts, name="ts"))


class HourMoveTests(unittest.TestCase):
    def test_the_engineered_fall_is_the_day_s_fall(self):
        b = tape(3, hourly_drop_on=1, sigma=0.0)
        m = cs.hour_moves(b)
        self.assertEqual(len(m), 3)
        self.assertAlmostEqual(float(m["fall"].iloc[1]), -0.05, places=6)
        self.assertAlmostEqual(float(m["rise"].iloc[1]), 0.0, places=9)
        self.assertAlmostEqual(float(m["fall"].iloc[0]), 0.0, places=9)

    def test_a_window_across_a_gap_does_not_count(self):
        b = tape(2, sigma=0.0)
        b.loc[b.index[300:], "close"] = 50.0                            # a crash at bar 12 of day 2
        self.assertAlmostEqual(float(cs.hour_moves(b)["fall"].iloc[1]), np.log(0.5), places=9)
        gapped = b.drop(b.index[300:312])                               # the crash hour itself is missing
        self.assertAlmostEqual(float(cs.hour_moves(gapped)["fall"].iloc[1]), 0.0, places=9)

    def test_a_window_across_the_day_boundary_does_not_count(self):
        b = tape(2, sigma=0.0)
        b.loc[b.index[288:], "close"] = 50.0                            # the crash is the first bar of day 2
        m = cs.hour_moves(b)
        self.assertAlmostEqual(float(m["fall"].iloc[0]), 0.0, places=9)
        self.assertAlmostEqual(float(m["fall"].iloc[1]), 0.0, places=9)
        self.assertTrue(cs.hour_moves(b.iloc[:5]).empty)


class EventTests(unittest.TestCase):
    def frame(self, rv, falls):
        idx = pd.date_range("2022-01-01", periods=len(rv), freq="D")
        daily = pd.DataFrame({"rv": rv, "ret": 0.0, "complete": True, "close": 4.6}, index=idx)
        moves = pd.DataFrame({"fall": falls, "rise": [0.0] * len(rv)}, index=idx)
        return daily, moves

    def test_cascade_reads_tomorrow_against_today_s_sigma(self):
        rv = [0.01] * 40                                                # sigma_d = 0.1
        falls = [0.0] * 40
        falls[31] = -0.13                                               # day 32: beyond 1.25 sigma
        falls[33] = -0.12                                               # day 34: inside
        falls[35] = -0.125                                              # day 36: exactly at the line
        daily, moves = self.frame(rv, falls)
        e = cs.events(daily, moves)
        self.assertTrue(np.isnan(e["cascade"].iloc[0]))                 # no sigma yet
        self.assertEqual(e["cascade"].iloc[30], 1.0)                    # origin day 31 sees day 32
        self.assertEqual(e["cascade"].iloc[32], 0.0)
        self.assertEqual(e["cascade"].iloc[34], 1.0)                    # at the line counts
        self.assertTrue(np.isnan(e["cascade"].iloc[-1]))                # no tomorrow

    def test_an_incomplete_tomorrow_has_no_event(self):
        daily, moves = self.frame([0.01] * 40, [-1.0] * 40)
        daily.loc[daily.index[35], "complete"] = False
        e = cs.events(daily, moves)
        self.assertTrue(np.isnan(e["cascade"].iloc[34]))
        self.assertEqual(e["cascade"].iloc[33], 1.0)

    def test_choose_k_moves_only_outside_the_band(self):
        self.assertEqual(cs.choose_k(0.05), 1.25)
        self.assertEqual(cs.choose_k(0.12), 1.5)
        self.assertEqual(cs.choose_k(0.01), 1.0)


class FeatureTests(unittest.TestCase):
    def test_open_interest_funding_and_positioning_land_on_the_origin(self):
        idx = pd.date_range("2022-01-01", periods=40, freq="D")
        daily = pd.DataFrame({"rv": 0.01, "ret": 0.0, "complete": True, "close": np.log(100.0)}, index=idx)
        daily["close"] = np.log(100.0 + np.arange(40))                 # a drifting close: day 39 is 139, day 32 is 132
        volume = pd.Series(1000.0, index=idx)
        oi = pd.DataFrame({"oi": np.linspace(1000, 2000, 40), "ls": 2.0}, index=idx)
        oi.loc[idx[5], "oi"] = 0.0                                      # a bad row gives NaN, not -inf
        settle = pd.date_range("2022-01-01", periods=120, freq="8h")
        funding = pd.DataFrame({"rate": 0.0001}, index=settle)
        funding.loc[settle[-1], "rate"] = -0.0005
        f = cs.features(daily, volume, oi, funding)
        self.assertEqual(list(f.columns), cs.FULL)
        self.assertAlmostEqual(float(f["oi1"].iloc[39]), np.log(2000 / (2000 - 1000 / 39)))
        self.assertAlmostEqual(float(f["oi7"].iloc[39]), np.log(2000 / (2000 - 7000 / 39)))
        self.assertAlmostEqual(float(f["oivol"].iloc[39]), np.log(2.0))
        self.assertAlmostEqual(float(f["f1"].iloc[39]), -0.0005)
        self.assertAlmostEqual(float(f["f7"].iloc[39]), 20 * 0.0001 - 0.0005)
        self.assertAlmostEqual(float(f["fa7"].iloc[39]), np.log(20 * 0.0001 + 0.0005 + cs.FUND_FLOOR))
        self.assertAlmostEqual(float(f["ls"].iloc[39]), np.log(2.0))
        self.assertAlmostEqual(float(f["m7"].iloc[39]), np.log(139 / 132))
        self.assertTrue(np.isnan(f["oi1"].iloc[5]) and np.isnan(f["oi1"].iloc[6]) and np.isfinite(f["oi1"].iloc[7]))
        self.assertTrue(np.isnan(f["oivol"].iloc[10]))                  # no 30-day volume yet
        self.assertTrue(np.isnan(f["d30"].iloc[10]))


class LogitTests(unittest.TestCase):
    def test_fit_recovers_the_sign_and_size_of_a_known_effect(self):
        rng = np.random.default_rng(1)
        X = rng.normal(size=(20_000, 2))
        p = 1 / (1 + np.exp(-(-2.0 + 1.0 * X[:, 0] - 0.5 * X[:, 1])))
        y = (rng.random(20_000) < p).astype(float)
        m = cs.logit_fit(X, y)
        self.assertAlmostEqual(m["beta"][0], -2.0, delta=0.15)
        self.assertAlmostEqual(m["beta"][1], 1.0, delta=0.1)            # sd of X is 1, so standardized = raw
        self.assertAlmostEqual(m["beta"][2], -0.5, delta=0.1)
        pr = cs.logit_predict(m, X)
        self.assertLess(np.abs(pr - p).mean(), 0.02)

    def test_the_ridge_shrinks_a_separable_coefficient(self):
        X = np.linspace(-1, 1, 200)[:, None]
        y = (X[:, 0] > 0).astype(float)
        self.assertLess(abs(cs.logit_fit(X, y)["beta"][1]), 20.0)
        self.assertLess(abs(cs.logit_fit(X, y, ridge=1.0)["beta"][1]), abs(cs.logit_fit(X, y, ridge=0.001)["beta"][1]))

    def test_logloss(self):
        self.assertAlmostEqual(float(cs.logloss([1.0], [0.5])[0]), np.log(2))
        self.assertAlmostEqual(float(cs.logloss([0.0], [1.0])[0]), -np.log(cs.CLIP))


def rows_frame(n_days, n_coins=3, seed=2, leak_after=None):
    """Pooled rows: y depends on x1; after `leak_after` x2 becomes a perfect predictor (to test the purge)."""
    rng = np.random.default_rng(seed)
    origins = pd.date_range("2021-01-01", periods=n_days, freq="D")
    rows = []
    for c in range(n_coins):
        x1 = rng.normal(size=n_days)
        x2 = rng.normal(size=n_days)
        p = 1 / (1 + np.exp(-(-2.5 + 1.5 * x1)))
        y = (rng.random(n_days) < p).astype(float)
        if leak_after is not None:
            late = origins > leak_after
            x2[late] = np.where(y[late] > 0, 5.0, -5.0)
        rows.append(pd.DataFrame({"origin": origins, "coin": f"C{c}", "y": y, "x1": x1, "x2": x2}))
    return pd.concat(rows, ignore_index=True)


class ForecastTests(unittest.TestCase):
    def test_forecasts_cover_only_the_month_after_each_fit_and_need_training_rows(self):
        rows = rows_frame(500)
        fits = cs.month_ends(pd.Timestamp("2021-01-31"), pd.Timestamp("2022-05-31"))
        pred, models = cs.forecasts(rows, ["x1"], fits, rows["origin"].max(), min_train=400)
        first = rows.loc[pred.notna(), "origin"].min()
        # 400 rows across 3 coins is reached after 134 days: the first fit with enough rows is 2021-05-31
        self.assertEqual(cs.MIN_TRAIN, 5_000)
        self.assertEqual(first, pd.Timestamp("2021-06-01"))
        self.assertEqual(min(models), pd.Timestamp("2021-05-31"))
        self.assertTrue(pred.notna().sum() > 0)
        self.assertTrue(((pred.dropna() > 0) & (pred.dropna() < 1)).all())

    def test_training_rows_stop_at_the_target_known_by_the_fit_date(self):
        rows = rows_frame(10)
        at = pd.Timestamp("2021-01-05")
        tr = cs.training_rows(rows, at)
        self.assertEqual(tr["origin"].max(), pd.Timestamp("2021-01-04"))   # its target, 01-05, is known at the fit
        self.assertEqual(len(tr), 4 * 3)

    def test_a_fit_never_sees_a_target_after_its_date(self):
        rows = rows_frame(500, leak_after=pd.Timestamp("2021-12-31"))
        fits = [pd.Timestamp("2021-12-31")]
        pred, models = cs.forecasts(rows, ["x1", "x2"], fits, rows["origin"].max(), min_train=100)
        m = models[pd.Timestamp("2021-12-31")]
        self.assertLess(abs(m["beta"][2]), 0.5)                          # x2 was noise up to the fit date
        late = rows["origin"] > pd.Timestamp("2021-12-31")
        self.assertTrue(pred[late].notna().all())
        self.assertTrue(pred[~late].isna().all())

    def test_base_rate_is_the_training_frequency(self):
        rows = rows_frame(400)
        fits = [pd.Timestamp("2021-06-30")]
        b = cs.base_rate(rows, fits, rows["origin"].max(), min_train=10)
        train = rows[rows["origin"] + pd.Timedelta(days=1) <= fits[0]]
        self.assertAlmostEqual(float(b.dropna().iloc[0]), float(train["y"].mean()))


class ScoreTests(unittest.TestCase):
    def cells(self):
        origins = pd.date_range("2023-01-01", periods=6, freq="D")
        return pd.DataFrame({"origin": list(origins) * 2, "coin": ["A"] * 6 + ["B"] * 6, "y": [1, 0, 0, 1, 0, 0] * 2,
                             "vol": [0.5] * 12, "full": [0.9, 0.1, 0.1, 0.9, 0.1, 0.1] * 2})

    def test_per_origin_is_the_mean_gap_over_coins(self):
        s = cs.per_origin(self.cells(), "vol", "full")
        self.assertEqual(len(s), 6)
        self.assertAlmostEqual(float(s.iloc[0]), np.log(2) + np.log(0.9))
        self.assertTrue((s > 0).all())

    def test_breadth_counts_coins_with_enough_days(self):
        self.assertEqual(cs.breadth(self.cells(), "vol", "full", min_days=6), (2, 2))
        self.assertEqual(cs.breadth(self.cells(), "vol", "full", min_days=7), (0, 0))

    def test_newey_west_t_and_halves(self):
        x = np.array([1.0, 1.0, 1.0, 1.0])
        self.assertTrue(np.isnan(cs.nw_t(x, 1)))
        x = np.array([1.0, -1.0] * 50)
        self.assertAlmostEqual(cs.nw_t(x, 0), 0.0)
        rng = np.random.default_rng(3)
        x = np.cumsum(rng.normal(size=300)) * 0.01 + 0.2             # a persistent series
        e = x - x.mean()
        lags = 4
        var = float(e @ e) / len(x)
        for lag in range(1, lags + 1):
            var += 2 * (1 - lag / (lags + 1)) * float(e[lag:] @ e[:-lag]) / len(x)
        self.assertAlmostEqual(cs.nw_t(x, lags), float(x.mean() / np.sqrt(var / len(x))))
        self.assertLess(abs(cs.nw_t(x, lags)), abs(cs.nw_t(x, 0)))
        self.assertEqual(cs.halves(pd.Series([1.0, 2.0, 3.0, 4.0, 5.0])), (2.0, 4.5))

    def test_verdict_order(self):
        self.assertEqual(cs.verdict(5.0, 0.001, 1.0, 1.0, 30, 40, 199), cs.INCONCLUSIVE)
        self.assertEqual(cs.verdict(5.0, 0.001, 1.0, 1.0, 30, 40, 200), cs.PASS)
        self.assertEqual(cs.verdict(2.9, 0.001, 1.0, 1.0, 30, 40, 300), cs.FAIL)
        self.assertEqual(cs.verdict(3.0, 0.05, 1.0, 1.0, 30, 40, 300), cs.FAIL)
        self.assertEqual(cs.verdict(3.0, 0.01, 1.0, -0.1, 30, 40, 300), cs.FAIL)
        self.assertEqual(cs.verdict(3.0, 0.01, 1.0, 1.0, 20, 40, 300), cs.FAIL)
        self.assertEqual(cs.verdict(3.0, 0.01, 1.0, 1.0, 21, 40, 300), cs.PASS)

    def test_calibration_deciles(self):
        p = np.linspace(0.01, 0.99, 1000)
        y = (p > 0.5).astype(float)
        c = cs.calibration(p, y)
        self.assertEqual(list(c["decile"]), list(range(1, 11)))
        self.assertEqual(float(c["observed"].iloc[0]), 0.0)
        self.assertEqual(float(c["observed"].iloc[-1]), 1.0)


if __name__ == "__main__":
    unittest.main()
