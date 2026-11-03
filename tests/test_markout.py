import math
import unittest

import numpy as np
import pandas as pd

from espero import markout as mk
from tests.approx import approx


def prints(rows):
    """rows: (t_ms, price, qty, sign)"""
    df = pd.DataFrame(rows, columns=["t", "p", "q", "s"])
    return mk.Prints.frame(df)


def _day():
    rows = []
    # bid 100 / ask 100.1 market; sellers push through 100 at t=10s, price then drifts down
    for k in range(10):
        rows.append((k * 1000, 100.1, 1, 1))
        rows.append((k * 1000 + 500, 100.0, 1, -1))
    rows.append((10_000, 99.9, 1, -1))
    rows.append((10_100, 100.0, 1, 1))
    for k in range(11, 400):
        rows.append((k * 1000, 99.9, 1, 1))
        rows.append((k * 1000 + 500, 99.8, 1, -1))
    return prints(rows)


def _stats(venue="binance", mean=5.0, t=10.0, h1=4.0, h2=6.0, measure="maker_cons"):
    return pd.DataFrame([{"venue": venue, "coin": "BTC", "measure": measure, "horizon": 60, "cond": "all",
                          "level": "all", "mean": mean, "t": t, "h1": h1, "h2": h2}])


class TestMarkout(unittest.TestCase):
    """#39's measures: proxy mids, cleared levels, markouts, conditions and the q3 answer."""

    def test_bar_matches_the_preregistered_number(self):
        assert mk.bar(mk.PRIOR_TESTS + mk.CELLS) == approx(4.596, abs=5e-4)
        assert mk.BAR == approx(mk.bar(mk.PRIOR_TESTS + mk.CELLS), abs=5e-4)
        assert mk.bar(39) < mk.bar(359)

    def test_proxy_mid_is_last_buy_and_last_sell(self):
        pr = prints([(1000, 100.0, 1, -1), (2000, 101.0, 1, 1), (3000, 100.5, 1, -1)])
        m = mk.proxy_mids(pr)
        mid, spr = m.at(np.array([999, 1500, 2000, 2500, 3000]))
        assert np.isnan(mid[0]) and np.isnan(mid[1])          # no buy yet
        assert mid[2] == approx(100.5) and spr[2] == approx(1.0)
        assert mid[4] == approx(100.75)

    def test_proxy_strict_excludes_the_print_itself(self):
        pr = prints([(1000, 100.0, 1, -1), (2000, 101.0, 1, 1), (3000, 100.5, 1, -1)])
        m = mk.proxy_mids(pr)
        before, _ = m.at(np.array([3000]), strict=True)
        after, _ = m.at(np.array([3000]))
        assert before[0] == approx(100.5) and after[0] == approx(100.75)

    def test_proxy_goes_missing_when_stale_or_crossed(self):
        pr = prints([(0, 100.0, 1, -1), (1000, 101.0, 1, 1)])
        m = mk.proxy_mids(pr)
        mid, _ = m.at(np.array([1000, 60_000, 60_001]))
        assert not np.isnan(mid[0]) and not np.isnan(mid[1]) and np.isnan(mid[2])   # sell print is 60 s old
        crossed = mk.proxy_mids(prints([(0, 101.0, 1, -1), (1000, 100.0, 1, 1)]))
        assert np.isnan(crossed.at(np.array([1000]))[0][0])

    def test_quote_mids_keep_the_last_update_in_a_millisecond(self):
        m = mk.quote_mids([5, 5, 9], [99, 100, 100], [101, 102, 101])
        mid, spr = m.at(np.array([5, 8, 9, 4]))
        assert mid[0] == 101 and spr[0] == 2 and mid[2] == 100.5 and np.isnan(mid[3])

    def test_tick_is_the_smallest_price_gap(self):
        assert mk.tick(np.array([100.0, 100.1, 100.3, 100.1])) == approx(0.1)

    def test_flow_window_excludes_the_present(self):
        pr = prints([(0, 100, 1, 1), (5000, 100, 3, -1), (12_000, 100, 10, 1)])
        ti = mk.flow(pr, np.array([12_000, 12_001]))
        assert ti[0] == approx(-1.0)                 # only the sell in [2s, 12s)
        assert ti[1] == approx((10 - 3) / 13)

    def test_settlement_window(self):
        h8 = 8 * 3600 * 1000
        when = np.array([h8, h8 + 300_000, h8 + 301_000, h8 - 300_000, h8 - 301_000, h8 // 2])
        assert mk.settlement(when).tolist() == [True, True, False, True, False, False]

    def test_cleared_counts_a_level_once_when_traded_through(self):
        pr = prints([
            (0, 100.0, 1, -1),      # bid level 100 hit
            (1, 100.0, 1, -1),      # same level again: still one level
            (2, 99.9, 1, -1),       # through: 100 cleared at t=2
            (3, 100.0, 1, 1),       # buyer at 100: ask level 100
            (4, 99.9, 1, -1),       # seller at 99.9 again: not through 99.9
            (5, 100.1, 1, 1),       # buyer through 100: ask level 100 cleared at t=5
        ])
        t, p, s = mk.cleared(pr)
        assert t.tolist() == [2, 5]
        assert p.tolist() == [100.0, 100.0]
        assert s.tolist() == [1, -1]                        # maker bought, then maker sold

    def test_cleared_sweep_clears_every_level_above(self):
        pr = prints([(0, 100.0, 1, -1), (1, 99.9, 1, -1), (2, 99.8, 1, -1)])
        t, p, _ = mk.cleared(pr)
        assert sorted(p.tolist()) == [99.9, 100.0]
        # a touch that never goes through fills nothing
        t2, _, _ = mk.cleared(prints([(0, 100.0, 1, -1), (1, 100.0, 1, -1), (2, 100.1, 1, 1)]))
        assert len(t2) == 0

    def test_measures_signs(self):
        pr = _day()
        out = mk.measures(pr, mk.proxy_mids(pr))
        def get(m, h):
            return out[(out.measure == m) & (out.horizon == h) & (out.cond == "all")]["mean"].iloc[0]
        assert get("taker", 0) > 0                          # takers pay half the spread
        assert get("maker_cons", 60) < 0                    # the cleared bid was picked off
        # bids at 100 (t=10s) and 99.9 (t=11.5s) cleared, both marked at the later mid 99.85
        expected = np.mean([(99.85 - 100) / 100 * 1e4, (99.85 - 99.9) / 99.9 * 1e4])
        assert get("maker_cons", 60) == approx(expected)

    def test_measures_levels_cover_all(self):
        pr = _day()
        out = mk.measures(pr, mk.proxy_mids(pr), liq_hours=np.array([0]))
        for (m, h), g in out.groupby(["measure", "horizon"]):
            n_all = g[g.cond == "all"]["n"].iloc[0]
            for cond in ("flow", "funding", "liq", "hour"):
                assert g[g.cond == cond]["n"].sum() == n_all
            assert g[g.cond == "spread"]["n"].sum() <= n_all

    def test_taker_cost_uses_the_mid_before_the_print(self):
        # quotes 100/100.2; a buy at the ask pays 10 bps of half-spread
        pr = prints([(1000, 100.2, 1, 1), (2000, 100.0, 1, -1)] * 1)
        q = mk.quote_mids([0, 1000], [100.0, 100.4], [100.2, 100.6])   # quote moves at 1000
        out = mk.measures(pr, q, horizons=(1,))
        c = out[(out.measure == "taker") & (out.cond == "all")]["mean"].iloc[0]
        expected = np.mean([(100.2 - 100.1) / 100.1 * 1e4, -(100.0 - 100.5) / 100.5 * 1e4])
        assert c == approx(expected)

    def test_day_stats_t_over_days(self):
        days = pd.DataFrame({"day": ["d1", "d2", "d3", "d4"], "k": "x", "n": 5, "mean": [1.0, 2.0, 3.0, 2.0]})
        s = mk.day_stats(days, ["k"], halves="d3")
        r = s.iloc[0]
        assert r["days"] == 4 and r["mean"] == approx(2.0)
        assert r["t"] == approx(2.0 / (np.std([1, 2, 3, 2], ddof=1) / 2))
        assert r["h1"] == approx(1.5) and r["h2"] == approx(2.5)

    def test_within_tolerance(self):
        assert mk.within(1.2, 1.0)                           # 0.2 <= 0.25
        assert not mk.within(1.3, 1.0)
        assert mk.within(11.9, 10.0) and not mk.within(12.1, 10.0)       # 20% of 10
        assert not mk.within(math.nan, 1.0)

    def test_q3_net_of_fee_and_halves(self):
        assert mk.q3(_stats())["pass"].iloc[0]
        assert not mk.q3(_stats(mean=1.9, h1=3, h2=3))["pass"].iloc[0]            # under the 2 bp fee
        assert mk.q3(_stats(venue="hyperliquid", mean=1.9, t=40, h1=3, h2=3))["pass"].iloc[0]
        assert not mk.q3(_stats(h1=1.0))["pass"].iloc[0]                           # a half under the fee
        assert not mk.q3(_stats(h2=1.0))["pass"].iloc[0]
        assert not mk.q3(_stats(t=5.0))["pass"].iloc[0]                            # net t = 3.0 < 4.6

    def test_q3_ignores_the_optimistic_bound_and_unvalidated_cells(self):
        assert len(mk.q3(_stats(measure="maker_opt"))) == 0
        assert not mk.q3(_stats(), validated=set())["pass"].iloc[0]
        assert mk.q3(_stats(), validated={("BTC", 60)})["pass"].iloc[0]
        assert not mk.q3(_stats(), validated={("BTC", 60)}, replicated=False)["pass"].iloc[0]
        hl = _stats(venue="hyperliquid", mean=9, t=20, h1=9, h2=9)
        assert mk.q3(hl, validated=set(), replicated=False)["pass"].iloc[0]

    def test_optimistic_markout_takes_the_makers_side(self):
        pr = prints([(0, 100.0, 1, -1), (500, 100.2, 1, 1)])             # maker bought 100, maker sold 100.2
        q = mk.quote_mids([0, 1000], [99.9, 100.9], [100.1, 101.1])       # the mid then rises to 101
        out = mk.measures(pr, q, horizons=(1,))
        m = out[(out.measure == "maker_opt") & (out.cond == "all")]["mean"].iloc[0]
        assert m == approx(np.mean([(101 - 100) / 100 * 1e4, -(101 - 100.2) / 100.2 * 1e4]))

    def test_q3_never_counts_information_conditions(self):
        s = _stats().assign(cond="hour", level="03")
        assert len(mk.q3(s)) == 0

    def test_collapse_merges_fills_of_one_aggressor_at_one_price(self):
        df = pd.DataFrame({"t": [1, 1, 1, 2], "p": [100, 100, 99, 100], "q": [1, 2, 3, 4], "s": [-1, -1, -1, -1]})
        out = mk.collapse(df)
        assert out[["t", "p", "q"]].values.tolist() == [[1, 100, 3], [1, 99, 3], [2, 100, 4]]

    def test_flow_level_is_against_when_the_maker_buys_into_selling(self):
        rows = [(k * 100, 100.0, 1, -1) for k in range(50)]            # 5 s of sellers hitting the bid
        rows += [(5000, 100.1, 1, 1)]                                   # one buyer
        pr = prints(rows)
        out = mk.measures(pr, mk.quote_mids([0], [100.0], [100.1]), horizons=(1,))
        o = out[(out.measure == "maker_opt") & (out.cond == "flow")].set_index("level")["n"]
        assert o["against"] == 49 and o["with"] == 1                    # the buyer's maker sold into buying
        tk = out[(out.measure == "taker") & (out.cond == "flow")].set_index("level")["n"]
        assert tk["with"] == 49 and tk["against"] == 1

    def test_spread_and_funding_levels_land_on_the_right_names(self):
        h8 = 8 * 3600 * 1000
        pr = prints([(h8 + 1000, 100.1, 1, 1), (h8 + 2000, 100.0, 1, -1), (h8 + 3000, 100.1, 1, 1),  # in the window
                     (h8 + 900_000, 100.3, 1, 1)])                                                   # 15 min later
        q = mk.quote_mids([h8, h8 + 800_000], [100.0, 100.0], [100.1, 100.3])        # 1 tick, then 3 ticks wide
        out = mk.measures(pr, q, horizons=(1,))
        tk = out[out.measure == "taker"].set_index(["cond", "level"])["n"]
        assert tk[("funding", "settlement")] == 3 and tk[("funding", "other")] == 1
        assert tk[("spread", "tight")] == 3 and tk[("spread", "wide")] == 1


if __name__ == "__main__":
    unittest.main()
