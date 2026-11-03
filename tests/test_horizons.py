import unittest

import numpy as np
import pandas as pd

from espero import horizons as hz
from espero import markout as mk
from tests.approx import approx

DAY = 86_400


def bars(n_days=30, start=1_700_000_000 - 1_700_000_000 % DAY, drift=0.0):
    ts = np.arange(start, start + n_days * DAY, 300)
    px = 100 * np.exp(drift * np.arange(len(ts)))
    return pd.DataFrame({"open": px, "close": px * np.exp(drift)}, index=pd.Index(ts))


class TestHorizons(unittest.TestCase):
    """#43's horizons: prices, funding windows, criteria and the Holm step-down."""

    def test_bar_matches(self):
        assert mk.bar(hz.PRIOR_TESTS + hz.CELLS) == approx(hz.BAR, abs=5e-4)

    def test_prices_enter_at_open_and_exit_at_the_close_ending_at_h(self):
        b = bars(2)
        t0 = int(b.index[10])
        p0, p1 = hz.prices(b, np.array([t0]), 3600)
        assert p0[0] == b["open"].iloc[10]
        assert p1[0] == b["close"].iloc[10 + 12 - 1]                     # the bar ending at t0 + 1 h
        p0, p1 = hz.prices(b, np.array([t0 + 7]), 3600)                    # not on a bar: missing
        assert np.isnan(p0[0])
        gap = b.drop(b.index[10 + 11])
        _, p1 = hz.prices(gap, np.array([t0]), 3600)
        assert np.isnan(p1[0])

    def test_funding_window_is_entry_exclusive_exit_inclusive(self):
        st = np.array([0, 8, 16, 24]) * 3600
        r = np.array([1.0, 2.0, 4.0, 8.0])
        f = hz.funding_over(np.array([0, 0, 1]), 16 * 3600, st, r)
        assert f.tolist() == [6.0, 6.0, 6.0]                               # 8 h and 16 h, not 0 h
        assert hz.funding_over(np.array([0]), 8 * 3600 - 1, st, r)[0] == 0.0

    def test_one_per_coin_skips_entries_inside_a_hold(self):
        e = np.array([0, 10, 3600, 3599, 7200])
        keep = hz.one_per_coin(e, 3600)
        assert keep.tolist() == [True, False, True, False, True]

    def test_trades_net_charges_cost_and_funding_by_side(self):
        b = bars(3, drift=1e-5)
        t0 = int(b.index[0])
        st, r = np.array([t0 + 8 * 3600]), np.array([0.001])
        ev = pd.DataFrame({"ts": [t0, t0], "side": [1.0, -1.0]})
        tr = hz.trades(ev, b, DAY, 0.001, st, r, one=False)
        long_, short = tr.iloc[0], tr.iloc[1]
        assert long_["gross"] == approx(-short["gross"])
        assert long_["funding"] == approx(-0.001) and short["funding"] == approx(0.001)
        assert long_["net"] == approx(long_["gross"] - 0.001 - 0.001)
        assert short["net"] == approx(short["gross"] - 0.001 + 0.001)
        assert long_["net_spot"] == approx(long_["gross"] - 0.001)

    def test_windows_purge_holds_that_cross_the_boundary(self):
        end = pd.Timestamp("2024-12-31", tz="UTC").value // 10 ** 9
        tr = pd.DataFrame({"day": ["2024-12-30", "2024-12-31", "2025-01-01"],
                           "exit": [end, end + 2 * DAY, end + 2 * DAY]})
        sel, hold = hz.windows(tr)
        assert sel["day"].tolist() == ["2024-12-30"] and hold["day"].tolist() == ["2025-01-01"]

    def test_choose_takes_the_largest_t_among_positive_cells_over_two(self):
        cells = {"1h": {"mean": 5, "t": 3.0}, "1d": {"mean": 9, "t": 2.5}, "7d": {"mean": -4, "t": 5.0},
                 "14d": {"mean": 30, "t": 1.9}}
        assert hz.choose(cells) == "1h"
        assert hz.choose({"1h": {"mean": 1, "t": 1.0}}) is None

    def test_holm_steps_down_and_stops(self):
        assert hz.holm({"a": 0.01, "b": 0.02}) == {"a": True, "b": True}          # 0.01 <= .025, 0.02 <= .05
        assert hz.holm({"a": 0.03, "b": 0.04}) == {"a": False, "b": False}        # 0.03 > .025: stop
        assert hz.holm({"a": 0.001, "b": 0.06}) == {"a": True, "b": False}

    def test_confirm_rules(self):
        sel, hold = {"mean": 30.0}, {"mean": 12.0}
        c = hz.confirm("S3", "7d", sel, hold, {"mean": 5}, {"mean": 1}, True)
        assert all(c.values())
        assert not hz.confirm("S3", "7d", sel, {"mean": 9.0}, {"mean": 5}, {"mean": 1}, True)["no_collapse"]
        assert not hz.confirm("S3", "7d", sel, hold, {"mean": 5}, {"mean": -1}, True)["halves"]
        assert not hz.confirm("S1", "4h", sel, hold, {"mean": 5}, {"mean": 1}, True)["unseen"]
        assert not hz.confirm("S3", "7d", sel, hold, {"mean": 5}, {"mean": 1}, False)["holm"]

    def test_trend_events_need_every_lookback_up(self):
        b = bars(400, drift=1e-6)                                         # rising: every lookback up
        ev = hz.trend_events(b)
        assert len(ev) > 0 and (ev["ts"] % DAY == 0).all()
        first = pd.to_datetime(ev["ts"].iloc[0], unit="s") - pd.to_datetime(int(b.index[0]), unit="s")
        assert first.days >= 364
        falling = bars(400, drift=-1e-6)
        assert len(hz.trend_events(falling)) == 0

    def test_settlement_events_rules(self):
        s = pd.DataFrame({"ts": [0, 8 * 3600, 16 * 3600, 4 * 3600, 24 * 3600],
                          "rate8": [-0.0006, 0.0002, -0.0002, -0.001, 0.00005]})
        s2 = hz.settlement_events(s, "S2")
        assert s2["ts"].tolist() == [0] and (s2["side"] == -1).all()          # 04:00 is not 00/08/16
        s3 = hz.settlement_events(s, "S3")
        assert s3["ts"].tolist() == [0, 8 * 3600, 16 * 3600]
        assert s3["side"].tolist() == [1.0, -1.0, 1.0]                          # the side receiving funding

    def test_stats_day_means_and_hit(self):
        tr = pd.DataFrame({"day": ["a", "a", "b", "c"], "net": [0.001, 0.003, 0.002, 0.004],
                           "gross": [1, -1, 1, 1]})
        s = hz.stats(tr, DAY)
        assert s["mean"] == approx(1e4 * np.mean([0.002, 0.002, 0.004]))
        assert s["days"] == 3 and s["trades"] == 4 and s["hit"] == 0.75


if __name__ == "__main__":
    unittest.main()
