"""The point-in-time store, the execution simulator, the detector and the trial budget."""
import hashlib
import importlib.util
import io
import json
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest import mock

import numpy as np
import pandas as pd

from espero import detector, execsim, pit, trials

HAS_STORE = all(importlib.util.find_spec(m) for m in ("duckdb", "pyarrow"))


class ParseTests(unittest.TestCase):
    def test_kline_is_known_at_its_close_not_its_open(self):
        text = (b"open_time,open,high,low,close,volume,close_time,quote_volume,count,taker_buy_volume,"
                b"taker_buy_quote_volume,ignore\n1000,1,1,1,1,0,3599999,0,1,0,0,0\n")
        df = pit.parse("markPriceKlines", text, "BTCUSDT")
        self.assertEqual(df["valid_time"].iloc[0], 1000)
        self.assertEqual(df["known_time"].iloc[0], 3600000)

    def test_old_file_without_header_parses(self):
        text = b"1,100.5,2,1,1,1600000000000,true\n2,100.6,3,2,2,1600000000500,false\n"
        df = pit.parse("aggTrades", text, "BTCUSDT")
        self.assertEqual(list(df["agg_trade_id"]), [1, 2])
        self.assertEqual(list(df["is_buyer_maker"]), [True, False])

    def test_microsecond_clock_becomes_milliseconds(self):
        text = b"1,100.5,2,1,1,1600000000000000,true,true\n"
        df = pit.parse("spotAggTrades", text, "BTCUSDT")
        self.assertEqual(df["valid_time"].iloc[0], 1600000000000)

    def test_book_ticker_known_at_the_event(self):
        text = (b"update_id,best_bid_price,best_bid_qty,best_ask_price,best_ask_qty,transaction_time,event_time\n"
                b"7,10,1,11,1,1000,1005\n")
        df = pit.parse("bookTicker", text, "BTCUSDT")
        self.assertEqual((df["valid_time"].iloc[0], df["known_time"].iloc[0]), (1000, 1005))

    def test_unknown_header_raises(self):
        with self.assertRaises(ValueError):
            pit.parse("fundingRate", b"when,rate,x\n1,2,3\n", "BTCUSDT")

    def test_depth_clock(self):
        text = b"timestamp,percentage,depth,notional\n2024-01-08 00:00:12,-5,1.5,100\n"
        df = pit.parse("bookDepth", text, "BTCUSDT")
        self.assertEqual(df["valid_time"].iloc[0], pit.day_ms("2024-01-08") + 12_000)

    def test_keep_windows(self):
        df = pd.DataFrame({"valid_time": [1, 5, 10, 20]})
        self.assertEqual(list(pit.keep_windows(df, [(5, 11)])["valid_time"]), [5, 10])

    def test_paths(self):
        self.assertEqual(pit.archive_path("aggTrades", "BTCUSDT", "2024-01-08"),
                         "data/futures/um/daily/aggTrades/BTCUSDT/BTCUSDT-aggTrades-2024-01-08.zip")
        self.assertEqual(pit.archive_path("markPriceKlines", "BTCUSDT", "2024-01"),
                         "data/futures/um/monthly/markPriceKlines/BTCUSDT/1h/BTCUSDT-1h-2024-01.zip")
        self.assertEqual(pit.archive_path("spotAggTrades", "BTCUSDT", "2024-01-08"),
                         "data/spot/daily/aggTrades/BTCUSDT/BTCUSDT-aggTrades-2024-01-08.zip")

    def test_exchange_info(self):
        price = {"filterType": "PRICE_FILTER", "tickSize": "0.1"}
        body = json.dumps({"symbols": [{"symbol": "BTCUSDT", "status": "TRADING", "contractType": "PERPETUAL",
                                        "onboardDate": 5, "filters": [price]}]}).encode()
        df = pit.parse_exchange_info(body, 99)
        self.assertEqual(df["known_time"].iloc[0], 99)
        self.assertEqual(df["tick_size"].iloc[0], 0.1)


def _zip(name: str, text: bytes) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr(name, text)
    return buf.getvalue()


@unittest.skipUnless(HAS_STORE, "duckdb and pyarrow live in the `pit` extra")
class FetchTests(unittest.TestCase):
    TEXT = b"calc_time,funding_interval_hours,last_funding_rate\n1000,8,0.0001\n"

    def _get(self, body, published):
        def fake(url, **_):
            return (published.encode(), "") if url.endswith(".CHECKSUM") else (body, "Tue, 09 May 2023 22:02:30 GMT")
        return fake

    def test_writes_parquet_and_manifest_row(self):
        body = _zip("a.csv", self.TEXT)
        digest = hashlib.sha256(body).hexdigest()
        with tempfile.TemporaryDirectory() as tmp, mock.patch.object(pit, "_get", self._get(body, f"{digest}  a.zip")):
            row = pit.fetch_file("fundingRate", "BTCUSDT", "2024-01", store=Path(tmp))
            self.assertEqual((row["sha256"], row["checksum"], row["rows"]), (digest, "ok", 1))
            self.assertTrue(pit.store_path(Path(tmp), "fundingRate", "BTCUSDT", "2024-01").exists())

    def test_bad_checksum_writes_nothing(self):
        body = _zip("a.csv", self.TEXT)
        bad = self._get(body, "0" * 64 + "  a.zip")
        with tempfile.TemporaryDirectory() as tmp, mock.patch.object(pit, "_get", bad):
            with self.assertRaises(ValueError):
                pit.fetch_file("fundingRate", "BTCUSDT", "2024-01", store=Path(tmp))
            self.assertFalse(pit.store_path(Path(tmp), "fundingRate", "BTCUSDT", "2024-01").exists())

    def test_restated_file_refuses_to_merge(self):
        row = dict.fromkeys(pit.MANIFEST_COLS, 1) | {"dataset": "d", "symbol": "s", "period": "p", "sha256": "a"}
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "m.csv"
            pit.write_manifest([row], path)
            pit.write_manifest([row], path)
            self.assertEqual(len(pd.read_csv(path)), 1)
            with self.assertRaises(ValueError):
                pit.write_manifest([row | {"sha256": "b"}], path)


@unittest.skipUnless(HAS_STORE, "duckdb and pyarrow live in the `pit` extra")
class StoreTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = Path(self.tmp.name)
        day = 86_400_000
        rows = []
        listed = (("AAAUSDT", 10.0, 0), ("BBBUSDT", 5.0, 0), ("LATEUSDT", 100.0, 40), ("CCCBUSD", 99.0, 0))
        for sym, usd, start in listed:
            for d in range(start, 60):
                rows.append({"symbol": sym, "valid_time": d * day, "known_time": (d + 1) * day, "quote_volume": usd})
        k = pd.DataFrame(rows)
        for sym, g in k.groupby("symbol"):
            p = self.store / "klines_1d" / sym / "all.parquet"
            p.parent.mkdir(parents=True)
            g.to_parquet(p)
        info = pd.DataFrame([{"symbol": "BBBUSDT", "status": s, "known_time": d * day, "valid_time": d * day}
                             for s, d in (("SETTLING", 50), ("TRADING", 10))])
        p = self.store / "exchange_info" / "all" / "x.parquet"
        p.parent.mkdir(parents=True)
        info.to_parquet(p)
        self.con = pit.connect(self.store)

    def tearDown(self):
        self.con.close()
        self.tmp.cleanup()

    def _uni(self, day):
        return [r[0] for r in self.con.execute(pit.universe_sql(day * 86_400_000)).fetchall()]

    def test_universe_cannot_see_the_future(self):
        self.assertEqual(self._uni(35), ["AAAUSDT", "BBBUSDT"])      # LATE unlisted; BUSD excluded

    def test_volume_after_the_moment_does_not_rank(self):
        day = 86_400_000
        rows = [{"symbol": "SPKUSDT", "valid_time": d * day, "known_time": (d + 1) * day,
                 "quote_volume": 1.0 if d < 35 else 1e9} for d in range(60)]
        p = self.store / "klines_1d" / "SPKUSDT" / "all.parquet"
        p.parent.mkdir(parents=True)
        pd.DataFrame(rows).to_parquet(p)
        con = pit.connect(self.store)
        got = [r[0] for r in con.execute(pit.universe_sql(35 * day)).fetchall()]
        con.close()
        self.assertEqual(got, ["AAAUSDT", "BBBUSDT", "SPKUSDT"])

    def test_new_listing_needs_its_lookback(self):
        self.assertNotIn("LATEUSDT", self._uni(55))

    def test_delisted_status_applies_only_once_known(self):
        self.assertIn("BBBUSDT", self._uni(45))
        self.assertNotIn("BBBUSDT", self._uni(55))

    def _quality(self, df):
        p = self.store / "q" / "S" / "x.parquet"
        p.parent.mkdir(parents=True)
        df.to_parquet(p)
        con = pit.connect(self.store)
        out = con.execute(pit.quality_sql("q", ("k",), 10)).df().iloc[0]
        con.close()
        return out

    def test_quality_reports_duplicates_gaps_and_bad_clocks(self):
        q = self._quality(pd.DataFrame({"symbol": "S", "k": [1, 1, 2, 3], "valid_time": [0, 0, 5, 100],
                                        "known_time": [0, 0, 4, 100]}))
        self.assertEqual((q["duplicate_keys"], q["gaps"], q["known_before_valid"], q["rows"]), (1, 1, 1, 4))

    def test_clean_series_reports_nothing(self):
        q = self._quality(pd.DataFrame({"symbol": "S", "k": [1, 2], "valid_time": [0, 5], "known_time": [0, 5]}))
        self.assertEqual((q["duplicate_keys"], q["gaps"], q["known_before_valid"]), (0, 0, 0))

    def test_agg_id_hole_reported(self):
        p = self.store / "aggTrades" / "S" / "x.parquet"
        p.parent.mkdir(parents=True)
        pd.DataFrame({"symbol": "S", "agg_trade_id": [1, 2, 4], "valid_time": [0, 1, 2]}).to_parquet(p)
        con = pit.connect(self.store)
        out = con.execute(pit.agg_id_gaps_sql()).df()
        con.close()
        self.assertEqual(out["missing_ids"].iloc[0], 1)

    def test_missing_periods(self):
        m = pd.DataFrame({"dataset": ["a"], "symbol": ["s"], "period": ["p1"]})
        out = pit.missing_periods([("a", "s", "p1"), ("a", "s", "p2")], m)
        self.assertEqual(out["period"].tolist(), ["p2"])


def tape(mid=100.0, half=0.01, n=2000, step_ms=100, q=1.0):
    """Alternating aggressors around a fixed mid."""
    t = np.arange(n) * step_ms
    bm = np.arange(n) % 2 == 1      # odd prints: seller aggressor, at the bid
    price = np.where(bm, mid - half, mid + half)
    return t, price, np.full(n, q), bm


class TapeTests(unittest.TestCase):
    def test_recovers_known_half_spread(self):
        t, p, q, bm = tape(half=0.05)                   # 5 bps of 100
        for side in (1, -1):
            f = execsim.tape_fill(t, p, q, bm, 1000, side, 500.0)
            self.assertAlmostEqual(f.cost_bps, 5.0, places=6)
            self.assertEqual(f.filled, 1.0)

    def test_participation_sets_how_long_it_takes(self):
        t, p, q, bm = tape()
        fast = execsim.tape_fill(t, p, q, bm, 1000, 1, 500.0, participation=1.0)
        slow = execsim.tape_fill(t, p, q, bm, 1000, 1, 500.0, participation=0.1)
        self.assertGreater(slow.end_ms, fast.end_ms)
        self.assertAlmostEqual(slow.prints / fast.prints, 10, delta=0.1)

    def test_no_print_before_the_decision_is_used(self):
        t, p, q, bm = tape()
        p = p.copy()
        p[t < 1000] = 1.0           # a crash before t0 must not reach the average price
        f = execsim.tape_fill(t, p, q, bm, 1000, 1, 100.0)
        self.assertGreater(f.price, 99)

    def test_unfinished_leg_says_so(self):
        t, p, q, bm = tape(n=100)
        f = execsim.tape_fill(t, p, q, bm, 0, 1, 1e9)
        self.assertLess(f.filled, 1.0)

    def test_impact_moves_cost_up_with_size(self):
        n = 4000
        t = np.arange(n) * 100
        bm = np.arange(n) % 2 == 1
        drift = np.where(t >= 0, t * 1e-5, 0)
        p = 100 + drift + np.where(bm, -0.01, 0.01)
        q = np.ones(n)
        small = execsim.tape_fill(t, p, q, bm, 1000, 1, 100.0)
        big = execsim.tape_fill(t, p, q, bm, 1000, 1, 1000.0)
        self.assertGreater(big.cost_bps, small.cost_bps)

    def test_stale_mid_is_nan(self):
        t = np.array([0, 1, 200_000, 200_001])
        p = np.array([100.0, 100.0, 101.0, 101.0])
        bm = np.array([False, True, False, True])
        self.assertTrue(np.isnan(execsim.proxy_mid(t, p, bm, np.array([100_000]))[0]))
        self.assertAlmostEqual(execsim.proxy_mid(t, p, bm, np.array([10]))[0], 100.0)

    def test_crossed_prints_give_no_mid(self):
        t = np.array([0, 1])
        p = np.array([99.0, 100.0])         # the buyer paid less than the seller received
        bm = np.array([False, True])
        self.assertTrue(np.isnan(execsim.proxy_mid(t, p, bm, np.array([5]))[0]))

    def test_depth_cost(self):
        self.assertAlmostEqual(execsim.depth_cost(1_000_000, 100_000), 5.0)
        self.assertTrue(np.isnan(execsim.depth_cost(1_000, 100_000)))


class QueueTests(unittest.TestCase):
    def _book(self):
        return (np.array([0]), np.array([99.0]), np.array([10.0]), np.array([101.0]), np.array([10.0]))

    def test_fills_only_after_the_queue_ahead_trades(self):
        bt, b, bq, a, aq = self._book()
        t = np.array([1, 2, 3])
        p = np.array([99.0, 99.0, 99.0])
        q = np.array([6.0, 4.0, 1.0])       # 10 ahead clear, the third print is ours
        f = execsim.queue_fill(bt, b, bq, a, aq, t, p, q, np.array([True, True, True]), 0, 1, 1.0, 1000)
        self.assertTrue(f.filled)
        self.assertEqual(f.ms_to_fill, 3)
        self.assertAlmostEqual(f.cost_bps, -100.0)      # earned the half-spread against the mid

    def test_not_filled_before_the_queue_clears_then_crosses(self):
        bt, b, bq, a, aq = self._book()
        f = execsim.queue_fill(bt, b, bq, a, aq, np.array([1]), np.array([99.0]), np.array([9.0]), np.array([True]),
                               0, 1, 1.0, 1000)
        self.assertFalse(f.filled)
        self.assertTrue(f.crossed)
        self.assertAlmostEqual(f.fill_price, 101.0)

    def test_buyers_do_not_fill_a_resting_buy(self):
        bt, b, bq, a, aq = self._book()
        f = execsim.queue_fill(bt, b, bq, a, aq, np.array([1]), np.array([99.0]), np.array([50.0]), np.array([False]),
                               0, 1, 1.0, 1000)
        self.assertFalse(f.filled)

    def test_trade_through_fills(self):
        bt, b, bq, a, aq = self._book()
        f = execsim.queue_fill(bt, b, bq, a, aq, np.array([1]), np.array([98.0]), np.array([0.5]), np.array([True]),
                               0, 1, 1.0, 1000)
        self.assertTrue(f.filled)

    def test_sell_side_mirror(self):
        bt, b, bq, a, aq = self._book()
        f = execsim.queue_fill(bt, b, bq, a, aq, np.array([1]), np.array([101.0]), np.array([20.0]), np.array([False]),
                               0, -1, 1.0, 1000)
        self.assertTrue(f.filled)
        self.assertAlmostEqual(f.fill_price, 101.0)

    def test_no_live_quote(self):
        self.assertIsNone(execsim.queue_fill(np.array([0]), np.array([1.0]), np.array([1.0]), np.array([2.0]),
                                             np.array([1.0]), np.array([1]), np.array([1.0]), np.array([1.0]),
                                             np.array([True]), 10**7, 1, 1.0, 1000))


class ImpactTests(unittest.TestCase):
    def test_recovers_planted_coefficients(self):
        rng = np.random.default_rng(1)
        n = 200
        notional = 10 ** rng.uniform(3, 6, n)
        adv = np.full(n, 1e8)
        obs = pd.DataFrame({"symbol": "X", "regime": "low", "notional": notional, "adv": adv,
                            "cost_bps": 2.0 + 300.0 * np.sqrt(notional / adv) + rng.normal(0, 0.1, n)})
        fit = execsim.fit_impact(obs)
        self.assertAlmostEqual(fit["a_bps"].iloc[0], 2.0, delta=0.1)
        self.assertAlmostEqual(fit["b_bps"].iloc[0], 300.0, delta=5)
        self.assertAlmostEqual(execsim.predict_impact(fit, "X", "low", 1e6, 1e8), 2.0 + 30.0, delta=1)

    def test_thin_cell_gets_no_fit(self):
        obs = pd.DataFrame({"symbol": "X", "regime": "low", "notional": [1.0, 2.0], "adv": [10.0, 10.0],
                            "cost_bps": [1.0, 2.0]})
        self.assertTrue(execsim.fit_impact(obs).empty)
        self.assertTrue(np.isnan(execsim.predict_impact(execsim.fit_impact(obs), "X", "low", 1.0, 10.0)))

    def test_regimes(self):
        edges = execsim.regime_edges(pd.Series(np.arange(1.0, 10.0)))
        self.assertEqual(execsim.regime_of(1.0, edges), "low")
        self.assertEqual(execsim.regime_of(5.0, edges), "mid")
        self.assertEqual(execsim.regime_of(9.0, edges), "high")

    def test_markout_sign(self):
        t, p, q, bm = tape(half=0.01)
        out = execsim.markouts(t, p, bm, 0, 1, 99.0, horizons_s=(1,))
        self.assertGreater(out[1], 0)           # bought below where it then trades

    def test_week_returns_and_holes(self):
        w = [pd.Timestamp("2024-01-01"), pd.Timestamp("2024-01-08"), pd.Timestamp("2024-01-15")]
        o = pd.DataFrame({"A": [100.0, 110.0, np.nan]}, index=w)
        out = execsim.weeks_from_legs(w[:2], {w[0]: "A"}, o)
        self.assertAlmostEqual(out.iloc[0], np.log(1.1))
        with self.assertRaises(ValueError):
            execsim.weeks_from_legs(w, {w[0]: "A", w[1]: "A"}, o)
        self.assertEqual(execsim.weeks_from_legs(w[:2], {w[0]: None}, o).iloc[0], 0.0)


class DetectorTests(unittest.TestCase):
    def test_null_market_has_no_edge_on_average(self):
        rng = np.random.default_rng(7)
        m = [detector.synthetic_market(rng, 150, 0.0) for _ in range(300)]
        excess = np.mean([(b.gross - b.bench).mean() for b in m]) * detector.WEEKS_PER_YEAR
        self.assertLess(abs(excess), 0.08)

    def test_planted_alpha_comes_back(self):
        rng = np.random.default_rng(8)
        row = detector.power_table(rng, [1.0], 150, 150, draws=200)[0]
        self.assertAlmostEqual(row["mean_estimate"], row["mean_truth"], delta=0.12)
        self.assertGreater(row["mean_estimate"], 0.4)

    def test_book_has_one_leg_count_per_week(self):
        b = detector.synthetic_market(np.random.default_rng(1), 60)
        self.assertEqual(len(b.gross), len(b.switches))
        self.assertTrue(set(np.unique(b.switches)) <= {0, 1, 2})

    def test_theta(self):
        self.assertAlmostEqual(detector.theta_of(-0.3, 0.2, 0.05), 0.05 / 0.55)
        self.assertEqual(detector.theta_of(0.5, 0.2, 0.05), 1.0)      # beat it before costs

    def test_verdict_bands(self):
        self.assertEqual(detector.verdict_of(0.05, 0.2), "signal")
        self.assertEqual(detector.verdict_of(0.8, 0.95), "execution")
        self.assertEqual(detector.verdict_of(0.2, 0.3), "cannot_separate")

    def test_attribution_uses_measured_costs(self):
        rng = np.random.default_rng(1)
        a = detector.attribution(rng, -0.3, 0.2, np.full(100, 0.001), 2.0)
        self.assertAlmostEqual(a.drag, -np.log1p(-0.001) * 50, places=9)
        self.assertEqual(a.verdict, "signal")

    def test_unmeasured_leg_refuses(self):
        with self.assertRaises(ValueError):
            detector.attribution(np.random.default_rng(1), -0.3, 0.2, np.array([0.001, np.nan]), 2.0)

    def test_table_classifies_known_splits(self):
        rng = np.random.default_rng(3)
        rows = detector.attribution_table(rng, [("signal", 0.6, 0.0005), ("execution", 0.0, 0.01)], paths=30)
        self.assertGreater(rows[0]["signal"], 0.9)
        self.assertGreater(rows[1]["execution"], 0.9)


class TrialTests(unittest.TestCase):
    def test_more_trials_deflate_more(self):
        self.assertLess(trials.deflated_sharpe(0.1, 500, 45, 0.001), trials.deflated_sharpe(0.1, 500, 5, 0.001))

    def test_expected_max_grows_with_trials(self):
        self.assertGreater(trials.expected_max_sharpe(100, 1.0), trials.expected_max_sharpe(10, 1.0))
        self.assertAlmostEqual(trials.expected_max_sharpe(1, 1.0), 0.0)

    def test_psr_is_half_at_the_benchmark(self):
        self.assertAlmostEqual(trials.psr(0.1, 0.1, 100), 0.5)

    def test_holm_and_bh(self):
        p = [0.01, 0.04, 0.03]
        self.assertTrue(np.allclose(trials.holm(p), [0.03, 0.06, 0.06]))
        self.assertTrue(np.allclose(trials.bh(p), [0.03, 0.04, 0.04]))

    def test_spa_false_positive_rate_is_controlled(self):
        rng = np.random.default_rng(11)
        hits = sum(trials.spa(rng, rng.normal(0, 1, (250, 10)), draws=300)["p"] < 0.05 for _ in range(100))
        self.assertLessEqual(hits, 12)

    def test_spa_finds_a_real_edge_among_duds(self):
        rng = np.random.default_rng(12)
        x = rng.normal(0, 1, (500, 10))
        x[:, 3] += 0.5
        out = trials.spa(rng, x, draws=500)
        self.assertLess(out["p"], 0.01)
        self.assertEqual(out["best"], 3)

    def test_spa_recentres_hopeless_columns(self):
        rng = np.random.default_rng(13)
        x = rng.normal(0, 1, (500, 2))
        x[:, 0] -= 5.0
        self.assertEqual(trials.spa(rng, x, draws=200)["kept"], 1)

    def test_spa_hopeless_columns_do_not_hide_an_edge(self):
        rng = np.random.default_rng(14)
        x = rng.normal(0, 1, (500, 30))
        x[:, 1:] -= 5.0
        x[:, 0] += 0.11 - x[:, 0].mean()
        self.assertLess(trials.spa(rng, x, draws=1000)["p"], 0.05)

    def test_spa_refuses_holes(self):
        with self.assertRaises(ValueError):
            trials.spa(np.random.default_rng(1), np.array([[1.0], [np.nan]]))

    def test_spend(self):
        d = pd.DataFrame({"status": ["pass", "fail", "forward_pending"],
                          "date": ["2026-10-01", "2026-10-02", "2026-10-03"]})
        s = trials.spend(d)
        self.assertEqual((s["tests_judged"], s["span_days"], s["passes"]), (2, 2, 1))
        self.assertAlmostEqual(s["tests_per_day"], 1.0)
        self.assertAlmostEqual(s["bonferroni_alpha_per_test"], 0.025)


if __name__ == "__main__":
    unittest.main()
