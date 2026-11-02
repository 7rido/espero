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
        v.feed(rec(T, "orderbook.50", "BTCUSDT", {"type": "snapshot", "ts": T - 50,
                                                   "data": {"b": [["100", "1"], ["99.95", "2"]], "a": [["100.01", "1"]]}}))
        v.feed(rec(T + 10, "orderbook.50", "BTCUSDT", {"type": "delta", "ts": T - 40,
                                                        "data": {"b": [["100", "0"]], "a": [["100.01", "3"], ["100.5", "1"]]}}))
        self.assertEqual(v.book.top(), (99.95, 100.01))
        r = v.row(T + 100)
        self.assertAlmostEqual(r["spread_bps"], 0.06 / 99.98 * 1e4)
        self.assertAlmostEqual(r["depth_usd"], 99.95 * 2 + 100.01 * 3, msg="100.5 is 50 bps out, beyond the band")
        self.assertEqual(r["lag_ms"], 50)

    def test_bybit_window_trim_and_a_side_snapshot_older_than_the_deltas(self):
        v = tw.VenueState("bybit", "BTCUSDT")
        v.feed(rec(T, "orderbook.50", "BTCUSDT", {"type": "snapshot", "ts": T - 50,
                                                   "data": {"b": [[str(100 - i * 0.01), "1"] for i in range(50)],
                                                            "a": [[str(100.01 + i * 0.01), "1"] for i in range(50)]}}))
        v.feed(rec(T + 1, "orderbook.50", "BTCUSDT", {"type": "delta", "ts": T - 40,
                                                       "data": {"b": [["100.005", "1"]], "a": []}}))
        self.assertEqual(len(v.book.bids), 50, "a 51st level is trimmed: the venue never deletes what left its window")
        self.assertEqual(v.book.top(), (100.005, 100.01))
        # the recorder's side snapshot, older than two deltas already on the tape
        v.feed(rec(T + 2, "orderbook.50", "BTCUSDT", {"type": "delta", "ts": T - 30, "data": {"b": [["100.005", "0"]], "a": []}}))
        v.feed(rec(T + 3, "orderbook.50", "BTCUSDT", {"type": "snapshot", "ts": T - 45,
                                                       "data": {"b": [["100.005", "1"], ["100", "1"]], "a": [["100.01", "1"]]}}))
        self.assertEqual(v.book.top(), (100.0, 100.01), "the newer delta (100.005 gone) is replayed over the older snapshot")
        v.feed(rec(T + 4, "orderbook.50", "BTCUSDT", {"type": "delta", "ts": T - 20, "data": {"b": [["100.02", "1"]], "a": []}}))
        self.assertEqual(v.book.top(), (None, None), "a crossed book is a dash")

    def test_delta_before_any_snapshot_is_ignored(self):
        v = tw.VenueState("bybit", "BTCUSDT")
        v.feed(rec(T, "orderbook.50", "BTCUSDT", {"type": "delta", "ts": T, "data": {"b": [["100", "1"]], "a": [["101", "1"]]}}))
        self.assertEqual(v.book.top(), (None, None))

    def test_okx_checksum_guards_the_book(self):
        v = tw.VenueState("okx", "BTC-USDT-SWAP", ct_val=0.01)
        bids, asks = [["100", "10", "0", "1"]], [["100.01", "20", "0", "1"]]
        v.feed(rec(T, "books", "BTC-USDT-SWAP", {"action": "snapshot", "data": [{"bids": bids, "asks": asks, "ts": str(T)}]}))
        crc = zlib.crc32(b"100:10:100.01:20")
        ok = crc - (1 << 32) if crc >= 1 << 31 else crc
        v.feed(rec(T + 1, "books", "BTC-USDT-SWAP", {"action": "update", "data": [{"bids": [], "asks": [], "ts": str(T), "checksum": ok}]}))
        self.assertEqual(v.book.top(), (100.0, 100.01))
        self.assertAlmostEqual(v.row(T + 2)["depth_usd"], (100 * 10 + 100.01 * 20) * 0.01, msg="contracts times ctVal")
        v.feed(rec(T + 2, "books", "BTC-USDT-SWAP", {"action": "update", "data": [{"bids": [], "asks": [], "ts": str(T), "checksum": ok + 1}]}))
        self.assertEqual(v.book.top(), (None, None), "a checksum miss is a dash, not a number")
        v.feed(rec(T + 3, "rest.books", "BTC-USDT-SWAP", {"data": [{"bids": bids, "asks": asks, "ts": str(T + 3)}]}))
        self.assertEqual(v.book.top(), (100.0, 100.01), "the next snapshot brings it back")
        # a REST snapshot older than a delta already on the tape: the delta is replayed over it
        v.feed(rec(T + 4, "books", "BTC-USDT-SWAP", {"action": "update", "data": [{"bids": [["100", "0", "0", "0"]], "asks": [], "ts": str(T + 10)}]}))
        v.feed(rec(T + 5, "rest.books", "BTC-USDT-SWAP", {"data": [{"bids": bids, "asks": asks, "ts": str(T + 8)}]}))
        self.assertEqual(v.book.top(), (None, None), "bid 100 was removed after the snapshot was taken: nothing rests")

    def test_whole_book_venues_and_hyperliquid_sides(self):
        b = tw.VenueState("binance", "BTCUSDT")
        b.feed(rec(T, "depth20@100ms", "BTCUSDT", {"data": {"E": T - 30, "b": [["100", "1"]], "a": [["100.1", "1"]]}}))
        self.assertEqual(b.book.top(), (100.0, 100.1))
        h = tw.VenueState("hyperliquid", "BTC")
        h.feed(rec(T, "l2Book", "BTC", {"data": {"time": T - 300, "levels": [[{"px": "100", "sz": "1"}], [{"px": "101", "sz": "1"}]]}}))
        h.feed(rec(T, "trades", "BTC", {"data": [{"time": T - 10, "px": "101", "sz": "2", "side": "B"},
                                                 {"time": T - 5, "px": "100", "sz": "1", "side": "A"}]}))
        r = h.row(T)
        self.assertEqual((r["trades_1m"], r["usd_1m"]), (2, 302.0))
        self.assertAlmostEqual(r["buy_share"], 202 / 302)
        self.assertEqual(r["lag_ms"], 10)


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

    def test_okx_liquidations_are_filtered_to_the_instrument(self):
        v = tw.VenueState("okx", "BTC-USDT-SWAP", ct_val=0.01)
        v.feed(rec(T, "liquidation-orders", "SWAP", {"data": [
            {"instId": "BTC-USDT-SWAP", "details": [{"ts": str(T), "sz": "100", "bkPx": "100", "side": "buy"}]},
            {"instId": "OTHER-USDT-SWAP", "details": [{"ts": str(T), "sz": "100", "bkPx": "1", "side": "buy"}]}]}))
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

    def test_watch_renders_without_a_forecast(self):
        with tempfile.TemporaryDirectory() as tmp:
            raw = Path(tmp)
            w = rr.HourWriter(raw, "hyperliquid")
            w.write(rr.line(T, "l2Book", "BTC", json.dumps({"data": {"time": T - 300, "levels": [[{"px": "100", "sz": "1"}], [{"px": "101", "sz": "1"}]]}}).encode()))
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
            w.close()

    def test_the_read_is_words_for_book_flow_and_liquidations(self):
        book = tw.Book()
        book.set([("100", "30")], [("100.01", "1")])
        row = {"buy_share": 0.9, "liq_buy_5m": 5.0, "liq_sell_5m": 0.0}
        self.assertEqual(tw.read_of(row, book), "bid-heavy, buyers, shorts liquidated, leans up")
        book.set([("100", "1")], [("100.01", "30")])
        self.assertEqual(tw.read_of({"buy_share": 0.2, "liq_buy_5m": 0.0, "liq_sell_5m": 0.0}, book), "ask-heavy, sellers, leans down")
        self.assertEqual(tw.read_of({"buy_share": 0.5, "liq_buy_5m": 0.0, "liq_sell_5m": 9.0}, book),
                         "ask-heavy, flow even, longs liquidated, no lean", "one vote is not a lean")
        self.assertEqual(tw.read_of({"buy_share": None, "liq_buy_5m": 0.0, "liq_sell_5m": 0.0}, tw.Book()), "-")

    def test_okx_sequence_gap_is_a_dash_and_a_zero_checksum_is_not_checked(self):
        v = tw.VenueState("okx", "BTC-USDT-SWAP", ct_val=0.01)
        bids, asks = [["100", "10", "0", "1"]], [["100.01", "20", "0", "1"]]
        v.feed(rec(T, "books", "BTC-USDT-SWAP", {"action": "snapshot", "data": [{"bids": bids, "asks": asks, "ts": str(T), "checksum": 0, "seqId": 10, "prevSeqId": -1}]}))
        v.feed(rec(T + 1, "books", "BTC-USDT-SWAP", {"action": "update", "data": [{"bids": [], "asks": [], "ts": str(T + 1), "checksum": 0, "seqId": 11, "prevSeqId": 10}]}))
        self.assertEqual(v.book.top(), (100.0, 100.01), "in sequence, checksum 0 means not provided")
        v.feed(rec(T + 2, "books", "BTC-USDT-SWAP", {"action": "update", "data": [{"bids": [], "asks": [], "ts": str(T + 2), "checksum": 0, "seqId": 13, "prevSeqId": 12}]}))
        self.assertEqual(v.book.top(), (None, None), "a gap in the chain is a dash")
        v.feed(rec(T + 3, "rest.books", "BTC-USDT-SWAP", {"data": [{"bids": bids, "asks": asks, "ts": str(T + 3)}]}))
        v.feed(rec(T + 4, "books", "BTC-USDT-SWAP", {"action": "update", "data": [{"bids": [], "asks": [], "ts": str(T + 4), "checksum": 0, "seqId": 20, "prevSeqId": 19}]}))
        self.assertEqual(v.book.top(), (100.0, 100.01), "after a snapshot the chain restarts from the next update")


if __name__ == "__main__":
    unittest.main()
