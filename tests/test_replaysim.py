"""#62's replay, on made-up journals and tape only: each journal row becomes the registered order, the book
at arrival is the last whole frame before it, a market order walks the levels best first and stops at the
recorded depth, the registered comparison and its call, and (with hftbacktest installed) a resting order
that the tape's prints should fill is filled."""

from __future__ import annotations

import sqlite3
import tempfile
import unittest
from pathlib import Path

import numpy as np

from espero import replaysim as rs

try:
    import hftbacktest  # noqa: F401

    HAVE_SIM = True
except ImportError:
    HAVE_SIM = False

T = 1_793_664_000_000


def book(t, bids, asks, lag=40):
    return {"t": t, "rt": t + lag, "bids": bids, "asks": asks}


class TestJournals(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.state = Path(self.tmp.name)
        con = sqlite3.connect(self.state / "carry-maker.db")
        con.executescript("""
            CREATE TABLE positions (id INTEGER PRIMARY KEY, coin TEXT, entry_ts INTEGER, exit_ts INTEGER,
                                    qty_perp REAL, perp_entry REAL);
            INSERT INTO positions VALUES (1, 'HYPE', 1793664000, NULL, 2.7, 92.75);
            INSERT INTO positions VALUES (2, 'OLD', 1793000000, 1793664000, 1.0, 1.0);
            CREATE TABLE testnet_mirror (position_id INTEGER PRIMARY KEY, coin TEXT, open_oid INTEGER, open_px REAL,
                open_size REAL, open_status TEXT, open_filled REAL, open_ts INTEGER, close_oid INTEGER, close_px REAL,
                close_status TEXT, close_filled REAL, close_ts INTEGER);
            INSERT INTO testnet_mirror VALUES
                (1, 'HYPE', 5, 49.88, 2.69, 'filled', 2.69, 1793664100, NULL, NULL, NULL, 0, NULL);
        """)
        con.commit()
        con.close()
        con = sqlite3.connect(self.state / "hlp-book.db")
        con.executescript("""
            CREATE TABLE trades (coin TEXT, signal_ts INTEGER, status TEXT, entry_ts INTEGER, entry_px REAL,
                                 exit_ts INTEGER, exit_px REAL);
            INSERT INTO trades VALUES ('BTC', 1793664000, 'closed', 1793664060, 80000.0, 1793678460, 80100.0);
        """)
        con.commit()
        con.close()
        con = sqlite3.connect(self.state / "paper-btc-usd-hl.db")
        con.executescript("""
            CREATE TABLE orders (id TEXT PRIMARY KEY, product TEXT, side TEXT, size REAL, status TEXT,
                                 filled_ts INTEGER, filled_px REAL);
            INSERT INTO orders VALUES ('a1', 'BTC-USD', 'BUY', 0.001, 'filled', 1793667600, 80040.0);
            INSERT INTO orders VALUES ('a2', 'BTC-USD', 'SELL', 0.001, 'pending', NULL, NULL);
        """)
        con.commit()
        con.close()

    def tearDown(self):
        self.tmp.cleanup()

    def test_every_fill_since_the_recorder_started_becomes_an_order(self):
        orders, skipped = rs.orders_from_journals(self.state, since_ms=1_793_600_000_000)
        got = sorted(
            (o.book, o.ref, o.side, round(o.qty, 6), o.decision_ms, o.paper_px, o.kind, o.venue) for o in orders
        )
        self.assertEqual(
            got,
            [
                ("carry-maker", "positions/1/entry", -1, 2.7, 1793664000000, 92.75, "market", "hyperliquid"),
                (
                    "hlp-book",
                    "trades/BTC/1793664000/entry",
                    1,
                    round(1000 / 80000, 6),
                    1793664060000,
                    80000.0,
                    "market",
                    "hyperliquid",
                ),
                (
                    "hlp-book",
                    "trades/BTC/1793664000/exit",
                    -1,
                    round(1000 / 80000, 6),
                    1793678460000,
                    80100.0,
                    "market",
                    "hyperliquid",
                ),
                ("mirror", "testnet_mirror/1/open", -1, 2.69, 1793664100000, 49.88, "limit", "hyperliquid_testnet"),
                ("paper-btc-usd-hl", "orders/a1", 1, 0.001, 1793667600000, 80040.0, "market", "hyperliquid"),
            ],
        )
        self.assertEqual(skipped, [("carry-maker positions/2/exit", "the perp exit price is not journaled")])
        mirror = [o for o in orders if o.kind == "limit"][0]
        self.assertTrue(mirror.paper_filled)
        self.assertEqual(rs.orders_from_journals(self.state, since_ms=2_000_000_000_000)[0], [])


class TestTape(unittest.TestCase):
    def frames(self):
        return [
            {
                "rt": T + 40,
                "ch": "l2Book",
                "s": "BTC",
                "d": {
                    "channel": "l2Book",
                    "data": {
                        "coin": "BTC",
                        "time": T,
                        "levels": [
                            [{"px": "100", "sz": "1"}, {"px": "99", "sz": "2"}],
                            [{"px": "101", "sz": "0.5"}, {"px": "102", "sz": "1"}],
                        ],
                    },
                },
            },
            {
                "rt": T + 1040,
                "ch": "l2Book",
                "s": "BTC",
                "d": {
                    "channel": "l2Book",
                    "data": {
                        "coin": "BTC",
                        "time": T + 1000,
                        "levels": [[{"px": "100", "sz": "1"}], [{"px": "101", "sz": "0.5"}, {"px": "102", "sz": "1"}]],
                    },
                },
            },
            {
                "rt": T + 60,
                "ch": "trades",
                "s": "BTC",
                "d": {
                    "channel": "trades",
                    "data": [{"coin": "BTC", "side": "B", "px": "101", "sz": "0.2", "time": T + 20}],
                },
            },
            {
                "rt": T + 60,
                "ch": "l2Book",
                "s": "ETH",
                "d": {"channel": "l2Book", "data": {"coin": "ETH", "time": T, "levels": [[], []]}},
            },
        ]

    def test_books_and_trades_are_the_coins_own(self):
        books, trades = rs.books_and_trades(self.frames(), "BTC")
        self.assertEqual([b["t"] for b in books], [T, T + 1000])
        self.assertEqual(books[0]["asks"], [(101.0, 0.5), (102.0, 1.0)])
        self.assertEqual(trades, [{"t": T + 20, "rt": T + 60, "px": 101.0, "sz": 0.2, "side": 1}])
        self.assertEqual(rs.feed_lag_ms(books, trades)["median"], 40.0)

    def test_book_at_is_the_last_frame_before_arrival_and_not_a_stale_one(self):
        books, _ = rs.books_and_trades(self.frames(), "BTC")
        self.assertEqual(rs.book_at(books, T + 999)["t"], T)
        self.assertEqual(rs.book_at(books, T + 1000)["t"], T + 1000)
        self.assertIsNone(rs.book_at(books, T - 1))
        self.assertIsNone(rs.book_at(books, T + 1000 + rs.MAX_BOOK_AGE_MS + 1))

    def test_a_market_order_walks_the_book_best_first_and_stops_at_the_tape(self):
        b = book(T, [(100.0, 1.0), (99.0, 2.0)], [(101.0, 0.5), (102.0, 1.0)])
        self.assertEqual(rs.walk(b, +1, 0.5), (101.0, 1.0, 1))
        px, filled, n = rs.walk(b, +1, 1.0)
        self.assertAlmostEqual(px, (0.5 * 101 + 0.5 * 102) / 1.0)
        self.assertEqual((filled, n), (1.0, 2))
        px, filled, n = rs.walk(b, +1, 3.0)
        self.assertAlmostEqual(filled, 0.5)
        self.assertEqual(rs.walk(b, -1, 0.5), (100.0, 1.0, 1))
        empty = rs.walk({"t": T, "rt": T, "bids": [], "asks": []}, -1, 1.0)
        self.assertTrue(np.isnan(empty[0]))
        self.assertEqual(empty[1:], (0.0, 0))

    def test_replay_market_arrives_after_the_latency_and_signs_the_difference(self):
        books, _ = rs.books_and_trades(self.frames(), "BTC")
        o = rs.Order("paper", "x", "BTC", +1, 0.5, T, paper_px=100.5)
        r = rs.replay_market(o, books, latency_ms=250)
        self.assertTrue(r.comparable)
        self.assertEqual(r.sim_px, 101.0)
        self.assertAlmostEqual(r.diff_bps, (101.0 - 100.5) / 100.5 * 1e4)
        self.assertEqual(r.book_age_ms, 250)
        r = rs.replay_market(rs.Order("paper", "x", "BTC", -1, 0.5, T, 100.5), books, latency_ms=250)
        self.assertAlmostEqual(r.diff_bps, -(100.0 - 100.5) / 100.5 * 1e4)
        r = rs.replay_market(o, books, latency_ms=rs.MAX_BOOK_AGE_MS + 2000)
        self.assertFalse(r.comparable)

    def test_tick_of(self):
        self.assertEqual(rs.tick_of([100.0, 99.5, 101.25]), 0.01)
        self.assertEqual(rs.tick_of([78445.0, 78446.0]), 1.0)


class TestComparison(unittest.TestCase):
    def results(self, diffs, maker=()):
        out = [
            rs.Result(rs.Order("b", str(i), "BTC", 1, 1.0, T, 1.0), True, "", 1.0, 1.0, d) for i, d in enumerate(diffs)
        ]
        for paper, sim in maker:
            o = rs.Order("mirror", "m", "HYPE", -1, 1.0, T, 1.0, "limit", 1.0, None, paper)
            out.append(rs.Result(o, True, "", 1.0, 1.0, 0.0, sim))
        out.append(
            rs.Result(rs.Order("b", "gap", "BTC", 1, 1.0, T, 1.0), False, "no book within a minute before arrival")
        )
        return out

    def test_summary_and_the_registered_call(self):
        rng = np.random.default_rng(62)
        diffs = list(rng.normal(1.0, 3.0, 40))
        res = self.results(diffs, maker=[(True, True)] * 9 + [(True, False)] * 1)
        s = rs.summarize(res)
        self.assertEqual((s["taker_n"], s["maker_n"]), (40, 10))
        self.assertEqual(s["excluded"], {"no book within a minute before arrival": 1})
        self.assertAlmostEqual(s["maker"]["agreement"], 0.9)
        v = rs.verdict(s)
        self.assertEqual(v["call"], "PASS")
        res = self.results(list(rng.normal(8.0, 3.0, 40)), maker=[(True, True)] * 10)
        self.assertEqual(rs.verdict(rs.summarize(res))["call"], "PARTIAL")
        self.assertEqual(rs.verdict(rs.summarize(res))["note"], "the paper books flatter themselves")
        res = self.results(list(rng.normal(8.0, 3.0, 40)), maker=[(True, False)] * 10)
        self.assertEqual(rs.verdict(rs.summarize(res))["call"], "FAIL")
        res = self.results(diffs, maker=[(True, True)] * 7 + [(True, False)] * 3)
        self.assertEqual(rs.verdict(rs.summarize(res))["call"], "PARTIAL", "70% agreement misses the 80% bar")
        self.assertEqual(rs.verdict(rs.summarize(self.results([1.0] * 5)))["call"], "not judged")
        self.assertEqual(rs.verdict(rs.summarize(self.results([1.0] * 5)), final=True)["call"], "INCONCLUSIVE")


@unittest.skipUnless(HAVE_SIM, "needs hftbacktest (the sim extra)")
class TestResting(unittest.TestCase):
    def tape(self, prints_at_our_price: float):
        books = [book(T + i * 100, [(100.0, 5.0), (99.0, 5.0)], [(101.0, 5.0), (102.0, 5.0)]) for i in range(600)]
        trades = [
            {"t": T + 5_000 + i * 100, "rt": T + 5_040 + i * 100, "px": 101.0, "sz": prints_at_our_price, "side": +1}
            for i in range(300)
        ]
        return books, trades

    def test_the_registered_queue_model_and_latency_are_what_the_engine_gets(self):
        from unittest import mock

        import hftbacktest

        o = rs.Order("mirror", "m", "X", -1, 1.0, T + 1000, 101.0, "limit", 101.0, T + 20_000, True)
        books, trades = self.tape(2.0)
        calls = {}

        def wrap(name, real):
            def f(self_, *a, **k):
                calls[name] = a
                return real(self_, *a, **k)

            return f

        real_q, real_l = (
            hftbacktest.BacktestAsset.power_prob_queue_model3,
            hftbacktest.BacktestAsset.constant_order_latency,
        )
        with (
            mock.patch.object(hftbacktest.BacktestAsset, "power_prob_queue_model3", wrap("q", real_q)),
            mock.patch.object(hftbacktest.BacktestAsset, "constant_order_latency", wrap("lat", real_l)),
        ):
            rs.replay_limit(o, books, trades, latency_ms=250)
        self.assertEqual(calls["q"], (rs.QUEUE_MODEL_POWER,))
        self.assertEqual(rs.QUEUE_MODEL_POWER, 3.0)
        self.assertEqual(calls["lat"], (250_000_000, 250_000_000), "the same latency both ways, in ns")

    def test_a_resting_ask_fills_when_enough_prints_hit_it_and_not_otherwise(self):
        o = rs.Order("mirror", "m", "X", -1, 1.0, T + 1000, 101.0, "limit", 101.0, T + 50_000, True)
        books, trades = self.tape(2.0)  # 600 units print at 101 against 5 ahead of us
        r = rs.replay_limit(o, books, trades, latency_ms=250)
        self.assertTrue(r.comparable)
        self.assertTrue(r.sim_filled, "prints at our price well beyond the queue ahead fill the order")
        self.assertGreater(r.sim_fill_ms, T + 5_000)
        books, trades = self.tape(0.001)  # 0.3 units print: the queue ahead is never cleared
        r = rs.replay_limit(o, books, trades, latency_ms=250)
        self.assertTrue(r.comparable)
        self.assertFalse(r.sim_filled)


if __name__ == "__main__":
    unittest.main()
