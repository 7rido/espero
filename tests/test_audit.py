import math
import unittest

import numpy as np
import pandas as pd

from espero import audit as au
from espero.liq import clustered
from tests.approx import approx


class TestAudit(unittest.TestCase):
    """espero.audit: day means, trade-weighted and Newey-West t, the changed rule."""

    def test_day_mean_matches_liq_clustered(self):
        x = pd.Series([1.0, 3.0, 2.0, 4.0, 6.0])
        d = pd.Series(["a", "a", "b", "c", "c"])
        got = au.day_mean(x, d)
        want = clustered(x.groupby(d).mean())
        assert got["mean"] == approx(want["mean"]) and got["t"] == approx(want["t"])

    def test_trade_weighted_differs_when_days_have_unequal_counts(self):
        # one quiet day with a big winner, one crowded day of small losers
        x = pd.Series([10.0] + [-1.0] * 9)
        d = pd.Series(["q"] + ["c"] * 9)
        assert au.day_mean(x, d)["mean"] == approx(4.5)
        assert au.trade_weighted(x, d)["mean"] == approx(0.1)

    def test_trade_weighted_se_is_clustered(self):
        rng = np.random.default_rng(0)
        days = np.repeat(np.arange(50), 10)
        shock = rng.normal(0, 1, 50)[days]                 # a common shock within each day
        x = pd.Series(0.1 + shock + rng.normal(0, 0.1, 500))
        d = pd.Series(days)
        naive_t = x.mean() / (x.std(ddof=1) / math.sqrt(len(x)))
        t = au.trade_weighted(x, d)["t"]
        assert abs(t) < abs(naive_t) / 2                   # clustering removes the false precision
        # with independent events and one per day, it is close to the plain t
        y = pd.Series(rng.normal(0.2, 1, 400))
        one = pd.Series(np.arange(400))
        plain = y.mean() / (y.std(ddof=1) / math.sqrt(400))
        assert au.trade_weighted(y, one)["t"] == approx(plain, rel=0.01)

    def test_diff_slope_is_the_pooled_group_difference(self):
        y = pd.Series([3.0, 5.0, 1.0, 1.0, 2.0, 0.0, 7.0, 2.0])
        f = pd.Series([1, 1, 0, 0, 1, 0, 1, 0])
        d = pd.Series(["a", "a", "a", "b", "b", "b", "c", "c"])
        r = au.diff_trade_weighted(y, f, d)
        assert r["mean"] == approx(y[f == 1].mean() - y[f == 0].mean())
        assert np.isfinite(r["t"]) and r["days"] == 3

    def test_quiet_share(self):
        d = pd.Series(["a"] * 5 + ["b"] * 3 + ["c"])
        assert au.quiet_share(d) == approx(2 / 3)                    # a 3-event day counts as quiet

    def test_changed_rule(self):
        bar = (lambda m: m > 18e-4, lambda t: t > 2)
        a, b = {"mean": 25e-4, "t": 4.0}, {"mean": 20e-4, "t": 2.5}
        assert not au.changed(a, b, *bar)
        assert au.changed(a, {"mean": 15e-4, "t": 3.0}, *bar)               # falls under 18 bps
        assert au.changed(a, {"mean": -1e-4, "t": -0.2}, *bar)              # sign flip
        assert au.changed({"mean": 5e-4, "t": 1}, {"mean": -5e-4, "t": -1}, *bar)   # flip, neither met
        assert not au.changed({"mean": 5e-4, "t": 1}, {"mean": 6e-4, "t": 1.5}, *bar)

    def test_nw_with_no_lags_equals_the_clustered_t(self):
        rng = np.random.default_rng(1)
        days = pd.Series(pd.date_range("2026-01-01", periods=60, freq="D").strftime("%Y-%m-%d")).repeat(5)
        x = pd.Series(rng.normal(0.1, 1, len(days)), index=days.index)
        a = au.trade_weighted(x, days)
        b = au.trade_weighted_nw(x, days, lags=0)
        assert b["mean"] == approx(a["mean"]) and b["t"] == approx(a["t"])

    def test_nw_lowers_t_when_neighbouring_days_share_a_shock(self):
        rng = np.random.default_rng(2)
        dates = pd.date_range("2026-01-01", periods=120, freq="D")
        shock = np.convolve(rng.normal(0, 1, 121), [1, 1], mode="valid")       # adjacent days correlated
        day = pd.Series(dates.strftime("%Y-%m-%d")).repeat(4).reset_index(drop=True)
        x = pd.Series(0.2 + np.repeat(shock, 4) + rng.normal(0, 0.1, 480))
        assert abs(au.trade_weighted_nw(x, day, lags=2)["t"]) < abs(au.trade_weighted(x, day)["t"])


if __name__ == "__main__":
    unittest.main()
