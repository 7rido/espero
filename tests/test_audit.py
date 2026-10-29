import math

import numpy as np
import pandas as pd
import pytest

from espero import audit as au
from espero.liq import clustered


def test_day_mean_matches_liq_clustered():
    x = pd.Series([1.0, 3.0, 2.0, 4.0, 6.0])
    d = pd.Series(["a", "a", "b", "c", "c"])
    got = au.day_mean(x, d)
    want = clustered(x.groupby(d).mean())
    assert got["mean"] == pytest.approx(want["mean"]) and got["t"] == pytest.approx(want["t"])


def test_trade_weighted_differs_when_days_have_unequal_counts():
    # one quiet day with a big winner, one crowded day of small losers
    x = pd.Series([10.0] + [-1.0] * 9)
    d = pd.Series(["q"] + ["c"] * 9)
    assert au.day_mean(x, d)["mean"] == pytest.approx(4.5)
    assert au.trade_weighted(x, d)["mean"] == pytest.approx(0.1)


def test_trade_weighted_se_is_clustered():
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
    assert au.trade_weighted(y, one)["t"] == pytest.approx(plain, rel=0.01)


def test_diff_slope_is_the_pooled_group_difference():
    y = pd.Series([3.0, 5.0, 1.0, 1.0, 2.0, 0.0, 7.0, 2.0])
    f = pd.Series([1, 1, 0, 0, 1, 0, 1, 0])
    d = pd.Series(["a", "a", "a", "b", "b", "b", "c", "c"])
    r = au.diff_trade_weighted(y, f, d)
    assert r["mean"] == pytest.approx(y[f == 1].mean() - y[f == 0].mean())
    assert np.isfinite(r["t"]) and r["days"] == 3


def test_quiet_share():
    d = pd.Series(["a"] * 5 + ["b"] * 3 + ["c"])
    assert au.quiet_share(d) == pytest.approx(2 / 3)                    # a 3-event day counts as quiet


def test_changed_rule():
    bar = (lambda m: m > 18e-4, lambda t: t > 2)
    a, b = {"mean": 25e-4, "t": 4.0}, {"mean": 20e-4, "t": 2.5}
    assert not au.changed(a, b, *bar)
    assert au.changed(a, {"mean": 15e-4, "t": 3.0}, *bar)               # falls under 18 bps
    assert au.changed(a, {"mean": -1e-4, "t": -0.2}, *bar)              # sign flip
    assert au.changed({"mean": 5e-4, "t": 1}, {"mean": -5e-4, "t": -1}, *bar)   # flip, neither met
    assert not au.changed({"mean": 5e-4, "t": 1}, {"mean": 6e-4, "t": 1.5}, *bar)
