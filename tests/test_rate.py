"""#50's rating against synthetic markets: nothing from the future, a planted signal found and a null not,
the fixed bands, a failed reading leaving the number alone, the window it may not read, and its own score."""
from __future__ import annotations

import contextlib
import io
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import numpy as np
import pandas as pd

from espero import cli
from espero import rate as rt

NOW = pd.Timestamp("2026-10-31")


def walk(seed: int, days: int = 1500, end: str = "2026-10-29", drift=None) -> pd.Series:
    rng = np.random.default_rng(seed)
    r = rng.normal(0.0, 0.02, days) + (0.0 if drift is None else drift(rng, days))
    return pd.Series(100 * np.exp(np.cumsum(r)), index=pd.date_range(end=end, periods=days, freq="D"), name="close")


def regimes(rng, days):
    """Long up and down spells: the last month's direction says something about the next week."""
    out, sign, left = np.zeros(days), 1.0, 0
    for i in range(days):
        if left == 0:
            sign, left = rng.choice([-1.0, 1.0]), int(rng.integers(40, 120))
        out[i], left = sign * 0.012, left - 1
    return out


def frame(px: pd.Series) -> pd.DataFrame:
    p = px.to_numpy()
    return pd.DataFrame({"dt": px.index, "ts": px.index.astype("int64") // 10**9, "open": p, "high": p, "low": p, "close": p,
                         "adj_close": p, "volume": 1.0})


class TestRule(unittest.TestCase):
    def test_the_bands_are_the_registered_ones(self):
        cases = {0.10: 1, 0.2999: 1, 0.30: 2, 0.35: 3, 0.40: 4, 0.45: 5, 0.4999: 5, 0.50: 6, 0.55: 7, 0.60: 8, 0.65: 9,
                 0.6999: 9, 0.70: 10, 0.95: 10}
        for p, want in cases.items():
            self.assertEqual(rt.rating(p), want, p)

    def test_five_and_six_are_called_barely(self):
        self.assertEqual([rt.lean(s) for s in (4, 5, 6, 7)], ["leans down", "barely down", "barely up", "leans up"])

    def test_a_name_it_does_not_know_needs_a_flag(self):
        self.assertEqual(rt.resolve("btc"), ("BTC-USD", "crypto"))
        self.assertEqual(rt.resolve("spy"), ("SPY", "etf"))
        self.assertEqual(rt.resolve("HYPE", "crypto"), ("HYPE-USD", "crypto"))
        self.assertEqual(rt.resolve("aapl", "etf"), ("AAPL", "etf"))
        with self.assertRaises(rt.RatingError):
            rt.resolve("AAPL")


class TestNoFuture(unittest.TestCase):
    def test_a_feature_row_does_not_change_when_later_prices_do(self):
        px = walk(1)
        cut = px.index[900]
        moved = px.copy()
        moved[moved.index > cut] *= 3.0
        a, b = rt.features(px, "crypto").loc[:cut], rt.features(moved, "crypto").loc[:cut]
        pd.testing.assert_frame_equal(a, b)

    def test_the_outcome_is_the_close_h_days_later(self):
        px = pd.Series([1.0, 2.0, 1.5, 3.0], index=pd.date_range("2026-01-01", periods=4, freq="D"))
        self.assertEqual(rt.outcome(px, 1).tolist()[:3], [1.0, 0.0, 1.0])
        self.assertTrue(np.isnan(rt.outcome(px, 1).iloc[-1]))

    def test_etf_gaps_use_calendar_days(self):
        px = pd.Series([1.0, 2.0, 3.0], index=pd.to_datetime(["2026-01-02", "2026-01-05", "2026-01-12"]))
        self.assertEqual(rt.outcome(px, 7).iloc[0], 1.0)            # 01-09 carries 01-05's close
        self.assertEqual(rt.outcome(px, 7).iloc[1], 1.0)

    def test_a_friday_is_compared_with_monday_not_with_itself(self):
        px = pd.Series([1.0, 2.0, 3.0], index=pd.to_datetime(["2026-01-01", "2026-01-02", "2026-01-05"]))
        self.assertEqual(rt.outcome(px, 1).tolist()[:2], [1.0, 1.0])

    def test_the_typical_move_uses_the_same_later_close(self):
        px = pd.Series([100.0, 110.0], index=pd.to_datetime(["2026-01-02", "2026-01-05"]))
        self.assertAlmostEqual(rt.typical_move(px, 1, NOW), 0.10)

    def test_the_model_ignores_outcomes_in_the_frozen_window(self):
        px = walk(2, end="2027-01-15")
        moved = px.copy()
        moved[moved.index >= rt.FROZEN_FROM] *= 5.0
        pd.testing.assert_frame_equal(rt.rows(px, "crypto", 7, NOW + pd.Timedelta(days=60)),
                                      rt.rows(moved, "crypto", 7, NOW + pd.Timedelta(days=60)))
        last = rt.rows(px, "crypto", 7, NOW + pd.Timedelta(days=60)).index[-1]
        self.assertLess(last + pd.Timedelta(days=7), rt.FROZEN_FROM)

    def test_the_window_opens_only_after_the_verdicts(self):
        self.assertEqual(rt.readable_until(pd.Timestamp("2027-03-31")), rt.FROZEN_FROM)
        self.assertEqual(rt.readable_until(pd.Timestamp("2027-04-01")), pd.Timestamp("2027-04-01"))


class TestPool(unittest.TestCase):
    def test_a_symbol_lost_to_a_rate_limit_is_fetched_again(self):
        px = walk(5)
        calls = []

        def get(sym):
            calls.append(sym)
            if sym == "B" and calls.count("B") == 1:
                raise RuntimeError("HTTP Error 429")
            return frame(px)
        prices, errors = rt.load_frames(["A", "B"], {"A": "crypto", "B": "crypto"}, get=get, now=NOW)
        self.assertEqual(sorted(prices), ["A", "B"])
        self.assertEqual(errors, {})

    def test_a_symbol_that_keeps_failing_is_named(self):
        def get(sym):
            raise RuntimeError("no such symbol")
        prices, errors = rt.load_frames(["A"], {"A": "crypto"}, get=get, now=NOW)
        self.assertEqual(prices, {})
        self.assertIn("no such symbol", errors["A"])

    def test_the_report_says_how_many_symbols_were_fitted(self):
        prices = {f"P{k}-USD": walk(k + 20) for k in range(4)}
        cm = rt.build_model(prices, "crypto", 7, NOW)
        r = rt.rate_symbol("P0-USD", "crypto", prices["P0-USD"], cm, 7, NOW)
        ctx = {"funding": "a", "liquidations": "b", "book": "c"}
        self.assertIn("fitted on 4 of 42 symbols, only coins still listed", rt.format_report({**r, "fitted": 4, "pool": 42}, ctx))


class TestDetects(unittest.TestCase):
    def test_a_planted_signal_clears_and_a_null_does_not(self):
        planted = rt.build_model({f"P{k}": walk(k, drift=regimes) for k in range(6)}, "crypto", 7, NOW)
        null = rt.build_model({f"N{k}": walk(100 + k) for k in range(6)}, "crypto", 7, NOW)
        self.assertGreater(planted.skill["lo"], 0.0)
        self.assertTrue(rt.proven(planted.skill))
        self.assertLess(null.skill["lo"], 0.0)
        self.assertFalse(rt.proven(null.skill))

    def test_the_logistic_recovers_a_planted_slope(self):
        rng = np.random.default_rng(3)
        x = rng.normal(size=(5000, 2))
        y = (rng.random(5000) < 1 / (1 + np.exp(-(1.0 * x[:, 0])))).astype(float)
        m = rt.fit(x, y, ridge=0.0)
        self.assertAlmostEqual(m.beta[1], 1.0, delta=0.15)
        self.assertAlmostEqual(m.beta[2], 0.0, delta=0.15)

    def test_the_penalty_shrinks(self):
        rng = np.random.default_rng(3)
        x = rng.normal(size=(2000, 1))
        y = (rng.random(2000) < 1 / (1 + np.exp(-x[:, 0]))).astype(float)
        self.assertLess(abs(rt.fit(x, y, ridge=0.1).beta[1]), abs(rt.fit(x, y, ridge=0.0).beta[1]))


class TestRating(unittest.TestCase):
    def setUp(self):
        self.prices = {f"P{k}-USD": walk(k + 20) for k in range(4)}
        self.cm = rt.build_model(self.prices, "crypto", 7, NOW)

    def test_a_short_history_gets_a_reason_not_a_number(self):
        with self.assertRaises(rt.RatingError):
            rt.rate_symbol("NEW-USD", "crypto", walk(9, days=120), self.cm, 7, NOW)

    def test_a_rating_carries_its_evidence_and_says_unproven(self):
        r = rt.rate_symbol("P0-USD", "crypto", self.prices["P0-USD"], self.cm, 7, NOW)
        self.assertEqual(r["rating"], rt.rating(r["p_up"]))
        self.assertTrue(all(0 <= e["up"] <= 1 and e["lo"] <= e["hi"] for e in r["evidence"] if e["up"] is not None))
        text = rt.format_report(r, {"funding": "a", "liquidations": "b", "book": "c"})
        self.assertIn(f"RATING {r['rating']}/10", text)
        self.assertIn("UNPROVEN", text)
        self.assertIn("not advice", text)

    def test_a_rating_below_the_usual_rate_says_so(self):
        r = rt.rate_symbol("P0-USD", "crypto", self.prices["P0-USD"], self.cm, 7, NOW)
        ctx = {"funding": "a", "liquidations": "b", "book": "c"}
        self.assertIn("so below usual", rt.format_report({**r, "p_up": 0.56, "rating": 7, "usual": 0.61}, ctx))
        self.assertIn("so above usual", rt.format_report({**r, "p_up": 0.56, "rating": 7, "usual": 0.51}, ctx))
        self.assertNotIn("usual)", rt.format_report({**r, "p_up": 0.56, "rating": 7, "usual": 0.56}, ctx).split("UNPROVEN")[0].replace("56%)", ""))

    def test_a_model_worse_than_the_usual_rate_says_so(self):
        r = rt.rate_symbol("P0-USD", "crypto", self.prices["P0-USD"], self.cm, 7, NOW)
        ctx = {"funding": "a", "liquidations": "b", "book": "c"}
        worse = {**r, "proven": False, "skill": {"skill": -0.02, "lo": -0.04, "hi": -0.01, "days": 100}}
        unclear = {**r, "proven": False, "skill": {"skill": 0.0, "lo": -0.01, "hi": 0.01, "days": 100}}
        self.assertIn("did worse than the usual rate", rt.format_report(worse, ctx))
        self.assertIn("did not reliably beat the usual rate", rt.format_report(unclear, ctx))

    def test_a_proven_label_never_claims_profit(self):
        r = rt.rate_symbol("P0-USD", "crypto", self.prices["P0-USD"], self.cm, 7, NOW)
        text = rt.format_report({**r, "proven": True}, {"funding": "a", "liquidations": "b", "book": "c"})
        self.assertNotIn("UNPROVEN", text)
        self.assertIn("not evidence of profit", text)

    def test_every_rated_coin_pays_a_stated_cost(self):
        self.assertGreater(rt.round_trip_bps("NOTACOIN-USD", "crypto")[0], 0)
        self.assertGreater(rt.round_trip_bps("BTC-USD", "crypto")[0], 0)
        self.assertGreater(rt.round_trip_bps("SPY", "etf")[0], 0)

    def test_the_same_state_counts_are_this_symbols_own_past(self):
        px = self.prices["P0-USD"]
        ev = rt.same_state(px, "crypto", 7, NOW)
        past = rt.rows(px, "crypto", 7, NOW)
        today = rt.features(px, "crypto").iloc[-1]
        want = (np.sign(past["sma200"]) == np.sign(today["sma200"])).sum()
        self.assertEqual(ev[0]["days"], want)


class TestReadings(unittest.TestCase):
    BOOK = {"levels": [[{"px": "100", "sz": "3"}, {"px": "98", "sz": "99"}], [{"px": "101", "sz": "1"}]]}

    def post(self, body):
        if body["type"] == "l2Book":
            return self.BOOK
        return [{"time": 1_793_000_000_000, "fundingRate": "0.00001"}]

    def aggr(self, *_):
        return pd.DataFrame({"time": [1_793_000_000], "market": ["BINANCE_FUTURES:btcusdt"], "open": [1.0], "close": [1.0],
                             "vbuy": [1.0], "vsell": [1.0], "lbuy": [5.0], "lsell": [7.0]})

    def read(self, d, **kw):
        kw = {"post": self.post, "fetch_aggr": self.aggr, **kw}
        return rt.context("BTC-USD", "crypto", now=1_793_000_400.0, folder=Path(d), **kw)

    def test_the_book_leaves_out_levels_beyond_one_percent(self):
        with tempfile.TemporaryDirectory() as d:
            self.assertIn("75% bids", self.read(d)["book"])         # 300 of bids, 101 of asks; 98 is too far

    def test_a_failed_reading_says_so_and_does_not_raise(self):
        def boom(*_):
            raise RuntimeError("down")
        with tempfile.TemporaryDirectory() as d:
            got = self.read(d, post=boom, fetch_aggr=boom)
        self.assertEqual(got, {"funding": "unavailable", "liquidations": "unavailable", "book": "unavailable"})

    def test_aggr_is_asked_at_most_once_an_hour(self):
        fetch = mock.Mock(side_effect=self.aggr)
        with tempfile.TemporaryDirectory() as d:
            with mock.patch("time.time", return_value=1_793_000_400.0):
                self.read(d, fetch_aggr=fetch)
                path = Path(d) / rt.AGGR_CACHE
                os.utime(path, (1_793_000_400, 1_793_000_400))
                second = self.read(d, fetch_aggr=fetch)
            self.assertEqual(fetch.call_count, 1)
            self.assertIn("longs $7", second["liquidations"])
            self.assertIn("shorts $5", second["liquidations"])
            os.utime(path, (1_793_000_400 - rt.AGGR_MAX_AGE_S - 1, 1_793_000_400 - rt.AGGR_MAX_AGE_S - 1))
            self.read(d, fetch_aggr=fetch)
            self.assertEqual(fetch.call_count, 2)

    def test_a_coin_aggr_does_not_cover_is_named(self):
        with tempfile.TemporaryDirectory() as d:
            got = rt.context("HYPE-USD", "crypto", now=1_793_000_400.0, folder=Path(d), post=self.post, fetch_aggr=self.aggr)
        self.assertEqual(got["liquidations"], "not covered")

    def test_stocks_have_no_readings(self):
        self.assertTrue(all("not available" in v for v in rt.context("SPY", "etf").values()))


class TestScore(unittest.TestCase):
    def rating(self, day="2026-10-20", score=7, p=0.6, symbol="BTC-USD", h=7):
        return {"asof": pd.Timestamp(day), "symbol": symbol, "kind": "crypto", "horizon": h, "rating": score, "p_up": p,
                "usual": 0.5, "proven": False, "close": 100.0}

    def test_one_row_per_symbol_day_and_horizon(self):
        with tempfile.TemporaryDirectory() as d:
            self.assertTrue(rt.log_rating(self.rating(p=0.6), Path(d)))
            self.assertFalse(rt.log_rating(self.rating(p=0.9), Path(d)))
            self.assertTrue(rt.log_rating(self.rating(h=30), Path(d)))
            book = rt.read_ledger(Path(d))
        self.assertEqual(len(book), 2)
        self.assertEqual(book["p_up"].iloc[0], 0.6)

    def test_only_due_ratings_are_scored(self):
        px = pd.Series(np.arange(100.0, 130.0), index=pd.date_range("2026-10-01", periods=30, freq="D"))
        get = lambda s: frame(px)  # noqa: E731
        with tempfile.TemporaryDirectory() as d:
            rt.log_rating(self.rating(day="2026-10-20", h=7), Path(d))
            rt.log_rating(self.rating(day="2026-10-29", h=7, symbol="ETH-USD"), Path(d))
            card = rt.scorecard(Path(d), get=get, now=NOW)
        self.assertEqual((card["recorded"], card["due"], card["scored"]), (2, 1, 1))
        self.assertEqual(card["rows"], [{"rating": 7, "n": 1, "up": 1.0, "expected": 0.6}])
        self.assertAlmostEqual(card["skill"], 1 - 0.16 / 0.25)

    def test_nothing_due_says_so(self):
        with tempfile.TemporaryDirectory() as d:
            self.assertEqual(rt.format_scorecard(rt.scorecard(Path(d))), "No ratings recorded yet.")
            rt.log_rating(self.rating(day="2026-10-30"), Path(d))
            self.assertIn("none due", rt.format_scorecard(rt.scorecard(Path(d), now=NOW)))


class TestCommand(unittest.TestCase):
    def run_cli(self, *args):
        out, err = io.StringIO(), io.StringIO()
        prices = {s: walk(i + 40) for i, s in enumerate(rt.pool("crypto"))}
        frames = (prices, {})
        with mock.patch.object(rt, "load_frames", return_value=frames), mock.patch.object(rt, "log_rating") as logged, \
                mock.patch.object(rt, "context", return_value={"funding": "f", "liquidations": "l", "book": "b"}), \
                contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = cli.main(["rate", *args])
        return code, out.getvalue(), err.getvalue(), logged

    def test_a_rating_is_printed_and_recorded(self):
        code, out, _, logged = self.run_cli("BTC")
        self.assertEqual(code, 0)
        self.assertIn("BTC-USD", out)
        self.assertIn("/10", out)
        logged.assert_called_once()

    def test_one_bad_symbol_does_not_lose_the_good_one(self):
        code, out, err, _ = self.run_cli("BTC", "AAPL")
        self.assertEqual(code, 1)
        self.assertIn("BTC-USD", out)
        self.assertIn("AAPL", err)

    def test_no_symbol_is_a_clean_error(self):
        code, _, err, _ = self.run_cli()
        self.assertEqual(code, 2)
        self.assertIn("at least one symbol", err)


if __name__ == "__main__":
    unittest.main()
