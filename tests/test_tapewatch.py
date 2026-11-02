"""The live tape screen on made-up frames only: each venue's book from its own snapshot and deltas, OKX's
checksum turning a drifted book into a dash, flow and liquidations over their windows, lag, following a
file as it grows, and a screen that carries no forecast."""

from __future__ import annotations

import io
import json
import tempfile
import unittest
import zlib
from pathlib import Path

from espero import rawrec as rr
from espero import tapewatch as tw

try:
    import zstandard  # noqa: F401

    HAVE_ZSTD = True
except ImportError:
    HAVE_ZSTD = False

T = 1_793_664_000_000


def rec(rt, ch, s, d):
    return {"rt": rt, "ch": ch, "s": s, "d": d}


class TestBooks(unittest.TestCase):
    def test_bybit_snapshot_then_deltas(self):
        v = tw.VenueState("bybit", "BTCUSDT")
        v.feed(
            rec(
                T,
                "orderbook.50",
                "BTCUSDT",
                {
                    "type": "snapshot",
                    "ts": T - 50,
                    "data": {"b": [["100", "1"], ["99.95", "2"]], "a": [["100.01", "1"]]},
                },
            )
        )
        v.feed(
            rec(
                T + 10,
                "orderbook.50",
                "BTCUSDT",
                {"type": "delta", "ts": T - 40, "data": {"b": [["100", "0"]], "a": [["100.01", "3"], ["100.5", "1"]]}},
            )
        )
        self.assertEqual(v.book.top(), (99.95, 100.01))
        r = v.row(T + 100)
        self.assertAlmostEqual(r["spread_bps"], 0.06 / 99.98 * 1e4)
        self.assertAlmostEqual(r["depth_usd"], 99.95 * 2 + 100.01 * 3, msg="100.5 is 50 bps out, beyond the band")
        self.assertEqual(r["lag_ms"], 50)

    def test_bybit_window_trim_and_a_side_snapshot_older_than_the_deltas(self):
        v = tw.VenueState("bybit", "BTCUSDT")
        v.feed(
            rec(
                T,
                "orderbook.50",
                "BTCUSDT",
                {
                    "type": "snapshot",
                    "ts": T - 50,
                    "data": {
                        "b": [[str(100 - i * 0.01), "1"] for i in range(50)],
                        "a": [[str(100.01 + i * 0.01), "1"] for i in range(50)],
                    },
                },
            )
        )
        v.feed(
            rec(
                T + 1,
                "orderbook.50",
                "BTCUSDT",
                {"type": "delta", "ts": T - 40, "data": {"b": [["100.005", "1"]], "a": []}},
            )
        )
        self.assertEqual(len(v.book.bids), 50, "a 51st level is trimmed: the venue never deletes what left its window")
        self.assertEqual(v.book.top(), (100.005, 100.01))
        # the recorder's side snapshot, older than two deltas already on the tape
        v.feed(
            rec(
                T + 2,
                "orderbook.50",
                "BTCUSDT",
                {"type": "delta", "ts": T - 30, "data": {"b": [["100.005", "0"]], "a": []}},
            )
        )
        v.feed(
            rec(
                T + 3,
                "orderbook.50",
                "BTCUSDT",
                {
                    "type": "snapshot",
                    "ts": T - 45,
                    "data": {"b": [["100.005", "1"], ["100", "1"]], "a": [["100.01", "1"]]},
                },
            )
        )
        self.assertEqual(
            v.book.top(), (100.0, 100.01), "the newer delta (100.005 gone) is replayed over the older snapshot"
        )
        v.feed(
            rec(
                T + 4,
                "orderbook.50",
                "BTCUSDT",
                {"type": "delta", "ts": T - 20, "data": {"b": [["100.02", "1"]], "a": []}},
            )
        )
        self.assertEqual(v.book.top(), (None, None), "a crossed book is a dash")

    def test_delta_before_any_snapshot_is_ignored(self):
        v = tw.VenueState("bybit", "BTCUSDT")
        v.feed(
            rec(
                T,
                "orderbook.50",
                "BTCUSDT",
                {"type": "delta", "ts": T, "data": {"b": [["100", "1"]], "a": [["101", "1"]]}},
            )
        )
        self.assertEqual(v.book.top(), (None, None))

    def test_okx_checksum_guards_the_book(self):
        v = tw.VenueState("okx", "BTC-USDT-SWAP", ct_val=0.01)
        bids, asks = [["100", "10", "0", "1"]], [["100.01", "20", "0", "1"]]
        v.feed(
            rec(
                T,
                "books",
                "BTC-USDT-SWAP",
                {"action": "snapshot", "data": [{"bids": bids, "asks": asks, "ts": str(T)}]},
            )
        )
        crc = zlib.crc32(b"100:10:100.01:20")
        ok = crc - (1 << 32) if crc >= 1 << 31 else crc
        v.feed(
            rec(
                T + 1,
                "books",
                "BTC-USDT-SWAP",
                {"action": "update", "data": [{"bids": [], "asks": [], "ts": str(T), "checksum": ok}]},
            )
        )
        self.assertEqual(v.book.top(), (100.0, 100.01))
        self.assertAlmostEqual(v.row(T + 2)["depth_usd"], (100 * 10 + 100.01 * 20) * 0.01, msg="contracts times ctVal")
        v.feed(
            rec(
                T + 2,
                "books",
                "BTC-USDT-SWAP",
                {"action": "update", "data": [{"bids": [], "asks": [], "ts": str(T), "checksum": ok + 1}]},
            )
        )
        self.assertEqual(v.book.top(), (None, None), "a checksum miss is a dash, not a number")
        v.feed(rec(T + 3, "rest.books", "BTC-USDT-SWAP", {"data": [{"bids": bids, "asks": asks, "ts": str(T + 3)}]}))
        self.assertEqual(v.book.top(), (100.0, 100.01), "the next snapshot brings it back")
        # a REST snapshot older than a delta already on the tape: the delta is replayed over it
        v.feed(
            rec(
                T + 4,
                "books",
                "BTC-USDT-SWAP",
                {"action": "update", "data": [{"bids": [["100", "0", "0", "0"]], "asks": [], "ts": str(T + 10)}]},
            )
        )
        v.feed(rec(T + 5, "rest.books", "BTC-USDT-SWAP", {"data": [{"bids": bids, "asks": asks, "ts": str(T + 8)}]}))
        self.assertEqual(v.book.top(), (None, None), "bid 100 was removed after the snapshot was taken: nothing rests")

    def test_whole_book_venues_and_hyperliquid_sides(self):
        b = tw.VenueState("binance", "BTCUSDT")
        b.feed(rec(T, "depth20@100ms", "BTCUSDT", {"data": {"E": T - 30, "b": [["100", "1"]], "a": [["100.1", "1"]]}}))
        self.assertEqual(b.book.top(), (100.0, 100.1))
        h = tw.VenueState("hyperliquid", "BTC")
        h.feed(
            rec(
                T,
                "l2Book",
                "BTC",
                {"data": {"time": T - 300, "levels": [[{"px": "100", "sz": "1"}], [{"px": "101", "sz": "1"}]]}},
            )
        )
        h.feed(
            rec(
                T,
                "trades",
                "BTC",
                {
                    "data": [
                        {"time": T - 10, "px": "101", "sz": "2", "side": "B"},
                        {"time": T - 5, "px": "100", "sz": "1", "side": "A"},
                    ]
                },
            )
        )
        r = h.row(T)
        self.assertEqual((r["trades_1m"], r["usd_1m"]), (2, 302.0))
        self.assertAlmostEqual(r["buy_share"], 202 / 302)
        self.assertEqual(r["lag_ms"], 10)


class TestCoinbase(unittest.TestCase):
    def test_snapshot_changes_and_the_makers_side(self):
        v = tw.VenueState("coinbase", "BTC-USD")
        v.feed(
            rec(
                T,
                "snapshot",
                "BTC-USD",
                {
                    "type": "snapshot",
                    "product_id": "BTC-USD",
                    "bids": [["100.00", "1"], ["99.99", "2"]],
                    "asks": [["100.01", "1"]],
                },
            )
        )
        v.feed(
            rec(
                T + 60,
                "l2update",
                "BTC-USD",
                {
                    "type": "l2update",
                    "product_id": "BTC-USD",
                    "changes": [["buy", "100.00", "0.00000000"], ["sell", "100.02", "3"]],
                    "time": "2026-11-03T00:00:00.010000Z",
                },
            )
        )
        self.assertEqual(v.book.top(), (99.99, 100.01))
        self.assertEqual(v.lags[-1], 50)
        v.feed(
            rec(
                T + 70,
                "match",
                "BTC-USD",
                {
                    "type": "match",
                    "product_id": "BTC-USD",
                    "side": "sell",
                    "price": "100.01",
                    "size": "2",
                    "time": "2026-11-03T00:00:00.020000Z",
                },
            )
        )
        v.feed(
            rec(
                T + 70,
                "match",
                "ETH-USD",
                {
                    "type": "match",
                    "product_id": "ETH-USD",
                    "side": "buy",
                    "price": "1",
                    "size": "1",
                    "time": "2026-11-03T00:00:00.020000Z",
                },
            )
        )
        r = v.row(T + 100)
        self.assertEqual(
            (r["trades_1m"], r["usd_1m"], r["buy_share"]), (1, 200.02, 1.0), "a sell maker means the taker bought"
        )
        v.feed(rec(T + 80, "rest.book", "BTC-USD", {"bids": [["100.00", "5", 1]], "asks": [["100.01", "1", 1]]}))
        self.assertEqual(v.book.top(), (100.0, 100.01))
        v.feed(
            rec(
                T + 90,
                "l2update",
                "BTC-USD",
                {
                    "type": "l2update",
                    "product_id": "BTC-USD",
                    "changes": [["sell", "99.50", "1"]],
                    "time": "2026-11-03T00:00:00.100000Z",
                },
            )
        )
        self.assertEqual(v.book.top(), (None, None), "an ask under the bid crosses the book: a dash")
        v.feed(
            rec(
                T + 95,
                "ticker",
                "BTC-USD",
                {"type": "ticker", "product_id": "BTC-USD", "best_bid": "100.00", "best_ask": "100.01"},
            )
        )
        self.assertEqual(v.book.top(), (100.0, 100.01), "the ticker's best bid and ask prune the stale level")
        v.feed(
            rec(
                T + 96,
                "l2update",
                "BTC-USD",
                {
                    "type": "l2update",
                    "product_id": "BTC-USD",
                    "changes": [["buy", "100.50", "1"]],
                    "time": "2026-11-03T00:00:00.110000Z",
                },
            )
        )
        self.assertEqual(v.book.top(), (None, None), "a bid over the ask crosses it the other way")
        v.feed(
            rec(
                T + 97,
                "ticker",
                "BTC-USD",
                {"type": "ticker", "product_id": "BTC-USD", "best_bid": "100.00", "best_ask": "100.01"},
            )
        )
        self.assertEqual(v.book.top(), (100.0, 100.01), "and the ticker prunes a stale bid too")
        self.assertEqual(tw._iso_ms("2026-11-03T00:00:00Z"), T)


class TestFlow(unittest.TestCase):
    def test_flow_and_liquidations_fall_out_of_their_windows(self):
        v = tw.VenueState("bybit", "ETHUSDT")
        v.feed(rec(T, "publicTrade", "ETHUSDT", {"data": [{"T": T, "p": "10", "v": "1", "S": "Buy"}]}))
        v.feed(rec(T, "allLiquidation", "ETHUSDT", {"data": [{"T": T, "p": "10", "v": "5", "S": "Buy"}]}))
        r = v.row(T + 1000)
        self.assertEqual((r["trades_1m"], r["usd_1m"], r["liq_sell_5m"], r["liq_buy_5m"]), (1, 10.0, 50.0, 0.0))
        r = v.row(T + tw.FLOW_S * 1000 + 1)
        self.assertEqual((r["trades_1m"], r["liq_sell_5m"]), (0, 50.0))
        r = v.row(T + tw.LIQ_S * 1000 + 1)
        self.assertEqual(r["liq_sell_5m"], 0.0)

    def test_windows_of_thirty_minutes_and_an_hour(self):
        v = tw.VenueState("bybit", "ETHUSDT")
        for age_s, side in (
            (4000, "Buy"),
            (3500, "Sell"),
            (2000, "Buy"),
            (600, "Sell"),
            (10, "Buy"),
        ):  # oldest first, as a tape is
            v.feed(
                rec(T, "publicTrade", "ETHUSDT", {"data": [{"T": T - age_s * 1000, "p": "10", "v": "1", "S": side}]})
            )
        v.feed(
            rec(T, "allLiquidation", "ETHUSDT", {"data": [{"T": T - 1000 * 1000, "p": "10", "v": "1", "S": "Sell"}]})
        )
        r = v.row(T)
        w = r["windows"]
        self.assertEqual(
            (w["5m"]["trades"], w["30m"]["trades"], w["1h"]["trades"]), (1, 2, 4), "the 4000 s trade is out"
        )
        self.assertEqual(w["30m"]["buy_share"], 0.5)
        self.assertEqual(
            (w["5m"]["liq_buy"], w["30m"]["liq_buy"], w["1h"]["liq_buy"]),
            (0.0, 10.0, 10.0),
            "a short liquidated (S=Sell) is a buy order, 1000 s ago",
        )
        self.assertEqual(r["trades_1m"], 1)

    def test_okx_liquidations_are_filtered_to_the_instrument(self):
        v = tw.VenueState("okx", "BTC-USDT-SWAP", ct_val=0.01)
        v.feed(
            rec(
                T,
                "liquidation-orders",
                "SWAP",
                {
                    "data": [
                        {
                            "instId": "BTC-USDT-SWAP",
                            "details": [{"ts": str(T), "sz": "100", "bkPx": "100", "side": "buy"}],
                        },
                        {
                            "instId": "OTHER-USDT-SWAP",
                            "details": [{"ts": str(T), "sz": "100", "bkPx": "1", "side": "buy"}],
                        },
                    ]
                },
            )
        )
        self.assertEqual(v.row(T + 1)["liq_buy_5m"], 100.0)


@unittest.skipUnless(HAVE_ZSTD, "needs zstandard")
class TestFollow(unittest.TestCase):
    def test_follow_reads_the_file_as_it_grows_and_moves_to_the_next_hour(self):
        with tempfile.TemporaryDirectory() as tmp:
            raw = Path(tmp)
            clock = {"now": T}
            w = rr.HourWriter(raw, "bybit")
            w.write(rr.line(T, "publicTrade", "BTCUSDT", b'{"n":1}'))
            w.flush()
            w.write(rr.line(T, "publicTrade", "ETHUSDT", b'{"n":9}'))
            w.flush()
            gen = tw.follow(raw, "bybit", clock=lambda: clock["now"], symbols=["BTCUSDT"])
            self.assertEqual(next(gen)["d"]["n"], 1)
            self.assertIsNone(next(gen), "nothing new yet")
            w.write(rr.line(T + 5, "publicTrade", "BTCUSDT", b'{"n":2}'))
            w.flush()
            self.assertEqual(next(gen)["d"]["n"], 2)
            w.close()
            clock["now"] = T + 3_600_000
            w2 = rr.HourWriter(raw, "bybit")
            w2.write(rr.line(T + 3_600_000, "publicTrade", "BTCUSDT", b'{"n":3}'))
            w2.flush()
            got = [next(gen) for _ in range(3)]
            self.assertIn(3, [g["d"]["n"] for g in got if g], "the next hour's file is followed")
            w2.close()
            # started an hour back, the follower reads that hour, then this one, then waits
            clock["now"] = T + 7_200_000
            w3 = rr.HourWriter(raw, "bybit")
            w3.write(rr.line(T + 7_200_000, "publicTrade", "BTCUSDT", b'{"n":4}'))
            w3.close()
            gen2 = tw.follow(raw, "bybit", clock=lambda: clock["now"], start_ms=T, symbols=["BTCUSDT"])
            seen = []
            for _ in range(12):
                g = next(gen2)
                if g:
                    seen.append(g["d"]["n"])
            self.assertEqual(seen, [1, 2, 3, 4], "every hour from the start to now, in order")

    def test_watch_renders_without_a_forecast(self):
        with tempfile.TemporaryDirectory() as tmp:
            raw = Path(tmp)
            w = rr.HourWriter(raw, "hyperliquid")
            w.write(
                rr.line(
                    T,
                    "l2Book",
                    "BTC",
                    json.dumps(
                        {"data": {"time": T - 300, "levels": [[{"px": "100", "sz": "1"}], [{"px": "101", "sz": "1"}]]}}
                    ).encode(),
                )
            )
            w.flush()
            out = io.StringIO()
            tw.watch(raw, ["BTC"], out=out, clock=lambda: T + 1000, max_rounds=1, sleep=lambda s: None)
            text = out.getvalue()
            self.assertIn("information, not a signal", text)
            self.assertIn("hyperliquid", text)
            self.assertIn("100", text)
            for word in ("forecast", "buy signal", "sell signal", "long", "short", "leans"):
                self.assertNotIn(word, text.lower())
            out = io.StringIO()
            tw.watch(raw, ["BTC"], out=out, clock=lambda: T + 1000, max_rounds=1, sleep=lambda s: None, read=True)
            text = out.getvalue()
            self.assertIn("untested and outside the registry", text)
            self.assertIn("no lean", text)
            self.assertIn("flow", text)
            for name in ("1m", "5m", "30m", "1h"):
                self.assertIn(name, text)
            self.assertIn("read (untested, outside the registry)", text)
            w.close()

    def test_the_rich_screen_fits_eighty_columns_and_carries_no_forecast(self):
        with tempfile.TemporaryDirectory() as tmp:
            raw = Path(tmp)
            w = rr.HourWriter(raw, "hyperliquid")
            w.write(
                rr.line(
                    T,
                    "l2Book",
                    "BTC",
                    json.dumps(
                        {
                            "data": {
                                "time": T - 300,
                                "levels": [[{"px": "78400", "sz": "1"}], [{"px": "78401", "sz": "1"}]],
                            }
                        }
                    ).encode(),
                )
            )
            w.write(
                rr.line(
                    T,
                    "trades",
                    "BTC",
                    json.dumps({"data": [{"time": T - 10, "px": "78401", "sz": "0.5", "side": "B"}]}).encode(),
                )
            )
            w.close()
            out = io.StringIO()
            tw.watch(raw, ["BTC"], out=out, clock=lambda: T + 1000, max_rounds=1, sleep=lambda s: None, read=True)
            text = out.getvalue()
            self.assertIn("hyperliquid", text)
            self.assertIn("78,400", text)
            self.assertIn("39k (100%)", text, "the minute's $ traded with the taker buy share")
            self.assertIn("untested", text)
            self.assertLessEqual(max(len(line) for line in text.splitlines()), 80, "nothing wider than the pane")
            for word in ("forecast", "buy signal", "sell signal"):
                self.assertNotIn(word, text.lower())
        self.assertEqual(tw._fmt_usd(2_600_000), "2.6M")
        self.assertEqual(tw._fmt_usd(35_000_000), "35M")
        self.assertEqual(tw._fmt_usd(26_000), "26k")
        self.assertEqual(tw._fmt_usd(430), "430")
        self.assertEqual(tw._fmt_px(78400.12), "78,400.1")
        self.assertEqual(tw._fmt_px(2302.456), "2,302.46")

    def test_the_read_is_words_for_book_flow_and_liquidations(self):
        book = tw.Book()
        book.set([("100", "30")], [("100.01", "1")])
        row = {"buy_share": 0.9, "liq_buy_5m": 5.0, "liq_sell_5m": 0.0}
        self.assertEqual(tw.read_of(row, book), "bid-heavy, buyers, shorts liquidated, leans up")
        book.set([("100", "1")], [("100.01", "30")])
        self.assertEqual(
            tw.read_of({"buy_share": 0.2, "liq_buy_5m": 0.0, "liq_sell_5m": 0.0}, book),
            "ask-heavy, sellers, leans down",
        )
        self.assertEqual(
            tw.read_of({"buy_share": 0.5, "liq_buy_5m": 0.0, "liq_sell_5m": 9.0}, book),
            "ask-heavy, flow even, longs liquidated, no lean",
            "one vote is not a lean",
        )
        self.assertEqual(tw.read_of({"buy_share": None, "liq_buy_5m": 0.0, "liq_sell_5m": 0.0}, tw.Book()), "-")

    def test_okx_sequence_gap_is_a_dash_and_a_zero_checksum_is_not_checked(self):
        v = tw.VenueState("okx", "BTC-USDT-SWAP", ct_val=0.01)
        bids, asks = [["100", "10", "0", "1"]], [["100.01", "20", "0", "1"]]
        v.feed(
            rec(
                T,
                "books",
                "BTC-USDT-SWAP",
                {
                    "action": "snapshot",
                    "data": [{"bids": bids, "asks": asks, "ts": str(T), "checksum": 0, "seqId": 10, "prevSeqId": -1}],
                },
            )
        )
        v.feed(
            rec(
                T + 1,
                "books",
                "BTC-USDT-SWAP",
                {
                    "action": "update",
                    "data": [{"bids": [], "asks": [], "ts": str(T + 1), "checksum": 0, "seqId": 11, "prevSeqId": 10}],
                },
            )
        )
        self.assertEqual(v.book.top(), (100.0, 100.01), "in sequence, checksum 0 means not provided")
        v.feed(
            rec(
                T + 2,
                "books",
                "BTC-USDT-SWAP",
                {
                    "action": "update",
                    "data": [{"bids": [], "asks": [], "ts": str(T + 2), "checksum": 0, "seqId": 13, "prevSeqId": 12}],
                },
            )
        )
        self.assertEqual(v.book.top(), (None, None), "a gap in the chain is a dash")
        v.feed(rec(T + 3, "rest.books", "BTC-USDT-SWAP", {"data": [{"bids": bids, "asks": asks, "ts": str(T + 3)}]}))
        v.feed(
            rec(
                T + 4,
                "books",
                "BTC-USDT-SWAP",
                {
                    "action": "update",
                    "data": [{"bids": [], "asks": [], "ts": str(T + 4), "checksum": 0, "seqId": 20, "prevSeqId": 19}],
                },
            )
        )
        self.assertEqual(v.book.top(), (100.0, 100.01), "after a snapshot the chain restarts from the next update")


if __name__ == "__main__":
    unittest.main()
