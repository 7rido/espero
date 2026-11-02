"""#61's rebuild and comparison, on made-up frames only: aggr's arithmetic (dollars by taker side, counts,
liquidations by order side with Bybit's flip), the registered tolerance per field, a bar inside a recorded
gap excluded, a bar aggr lacks counted as a miss, and the day and family calls."""
from __future__ import annotations

import unittest

import numpy as np
import pandas as pd

from espero import rawbars as rb

T = 1_793_664_000_000       # 2026-11-03 00:00:00 UTC, ms


def frame(ch, d):
    return {"rt": T, "ch": ch, "s": "", "d": d}


class TestEvents(unittest.TestCase):
    def test_bybit_trades_and_the_liquidation_flip(self):
        frames = [frame("publicTrade", {"data": [{"T": T + 5, "s": "BTCUSDT", "p": "100", "v": "2", "S": "Buy"},
                                                 {"T": T + 6, "s": "BTCUSDT", "p": "99", "v": "1", "S": "Sell"}]}),
                  frame("allLiquidation", {"data": [{"T": T + 7, "s": "BTCUSDT", "p": "98", "v": "3", "S": "Buy"}]})]
        e = rb.events_from_frames("bybit", frames)
        self.assertEqual(list(e["side"]), ["buy", "sell", "sell"], "a long liquidated (S=Buy) is a sell order")
        self.assertEqual(list(e["liquidation"]), [False, False, True])
        self.assertEqual(e["market"].iloc[0], "BYBIT:BTCUSDT")

    def test_okx_sizes_are_contracts_times_ct_val(self):
        frames = [frame("trades", {"data": [{"instId": "BTC-USDT-SWAP", "ts": str(T + 1), "px": "100", "sz": "5",
                                             "side": "sell"}]}),
                  frame("liquidation-orders", {"data": [{"instId": "BTC-USDT-SWAP",
                                                         "details": [{"ts": str(T + 2), "bkPx": "99", "sz": "2",
                                                                      "side": "buy"}]},
                                                        {"instId": "OTHER-USDT-SWAP",
                                                         "details": [{"ts": str(T + 2), "bkPx": "1", "sz": "2",
                                                                      "side": "buy"}]}]})]
        e = rb.events_from_frames("okx", frames, ct_val={"BTC-USDT-SWAP": 0.01})
        self.assertEqual(len(e), 2, "an instrument without a contract value is not ours")
        self.assertAlmostEqual(e["size"].iloc[0], 0.05)
        self.assertAlmostEqual(e["size"].iloc[1], 0.02)
        self.assertEqual(e["market"].iloc[1], "OKEX:BTC-USDT-SWAP")

    def test_binance_agg_trade_counts_its_trades_and_maker_flag_is_the_side(self):
        frames = [frame("aggTrade", {"data": {"s": "BTCUSDT", "T": T + 1, "p": "100", "q": "1", "f": 10, "l": 14,
                                              "m": True}}),
                  frame("forceOrder", {"data": {"o": {"s": "BTCUSDT", "T": T + 2, "p": "90", "q": "2", "S": "BUY"}}})]
        e = rb.events_from_frames("binance", frames)
        self.assertEqual(list(e["count"]), [5, 1])
        self.assertEqual(list(e["side"]), ["sell", "buy"])
        self.assertEqual(e["market"].iloc[0], "BINANCE_FUTURES:btcusdt")

    def test_archive_rows_become_the_same_events(self):
        agg = pd.DataFrame({"agg_trade_id": [1], "price": [100.0], "quantity": [2.0], "first_trade_id": [7],
                            "last_trade_id": [9], "transact_time": [T + 1], "is_buyer_maker": ["false"]})
        e = rb.events_from_archive("BTCUSDT", agg)
        self.assertEqual((e["side"].iloc[0], int(e["count"].iloc[0]), bool(e["liquidation"].iloc[0])), ("buy", 3, False))


class TestBars(unittest.TestCase):
    def events(self):
        return pd.DataFrame([
            (T + 1_000, "BYBIT:BTCUSDT", 100.0, 1.0, "buy", False, 1),
            (T + 2_000, "BYBIT:BTCUSDT", 101.0, 2.0, "sell", False, 1),
            (T + 3_000, "BYBIT:BTCUSDT", 99.0, 1.0, "buy", False, 3),
            (T + 4_000, "BYBIT:BTCUSDT", 98.0, 4.0, "sell", True, 1),       # a liquidation: dollars only
            (T + rb.HOUR_MS + 1, "BYBIT:BTCUSDT", 105.0, 1.0, "buy", False, 1),
        ], columns=rb.EVENT_COLS)

    def test_aggrs_arithmetic(self):
        bars = rb.build_bars(self.events())
        self.assertEqual(len(bars), 2)
        b = bars.iloc[0]
        self.assertEqual((b["time"], b["open"], b["high"], b["low"], b["close"]), (T // 1000, 100.0, 101.0, 99.0, 99.0))
        self.assertAlmostEqual(b["vbuy"], 100.0 + 99.0)
        self.assertAlmostEqual(b["vsell"], 202.0)
        self.assertEqual((b["cbuy"], b["csell"]), (4, 1))
        self.assertAlmostEqual(b["lsell"], 392.0)
        self.assertEqual(b["lbuy"], 0.0)
        self.assertEqual(bars.iloc[1]["open"], 105.0)

    def test_five_minute_bars_floor_by_exchange_time(self):
        bars = rb.build_bars(self.events(), bar_ms=rb.FIVE_MS)
        self.assertEqual(list(bars["time"]), [T // 1000, (T + rb.HOUR_MS) // 1000])

    def test_a_liquidation_alone_makes_a_bar_without_prices(self):
        e = pd.DataFrame([(T + 1, "OKEX:X", 10.0, 1.0, "buy", True, 1)], columns=rb.EVENT_COLS)
        b = rb.build_bars(e)
        self.assertEqual(len(b), 1)
        self.assertTrue(np.isnan(b.iloc[0]["close"]))
        self.assertEqual(b.iloc[0]["lbuy"], 10.0)


class TestCompare(unittest.TestCase):
    def rows(self, **over):
        base = {"time": T // 1000, "market": "BYBIT:BTCUSDT", "open": 100.0, "high": 101.0, "low": 99.0, "close": 100.5,
                "vbuy": 1e6, "vsell": 9e5, "cbuy": 1000, "csell": 900, "lbuy": 0.0, "lsell": 5e4}
        ours = pd.Series(base)
        theirs = pd.Series({**base, **over})
        return ours, theirs

    def test_tolerance_per_field(self):
        ours, theirs = self.rows()
        self.assertTrue(rb.compare_bar(ours, theirs)["match"])
        self.assertEqual(rb.compare_bar(*self.rows(close=100.5 * 1.0004))["match"], True)
        self.assertEqual(rb.compare_bar(*self.rows(close=100.5 * 1.0006))["failed"], "close")
        self.assertTrue(rb.compare_bar(*self.rows(vbuy=1e6 * 1.015))["match"])
        self.assertEqual(rb.compare_bar(*self.rows(vbuy=1e6 * 1.05))["failed"], "volume")
        self.assertTrue(rb.compare_bar(*self.rows(cbuy=1015))["match"])
        self.assertEqual(rb.compare_bar(*self.rows(cbuy=1100))["failed"], "count")
        self.assertTrue(rb.compare_bar(*self.rows(lsell=5e4 * 1.04))["match"])
        self.assertEqual(rb.compare_bar(*self.rows(lsell=5e4 * 1.1))["failed"], "lsell")
        self.assertEqual(rb.compare_bar(*self.rows(lsell=5e4 * 1.1), liq_comparable=False)["match"], True,
                         "an archive bar is not compared on liquidations")

    def test_aggrs_empty_liquidation_means_zero(self):
        ours, theirs = self.rows(lbuy=np.nan, lsell=np.nan)
        ours["lsell"] = 0.0
        self.assertTrue(rb.compare_bar(ours, theirs)["match"])

    def test_missing_rows_and_gaps(self):
        ours, theirs = self.rows()
        self.assertEqual(rb.compare_bar(None, theirs)["failed"], "missing_ours")
        self.assertEqual(rb.compare_bar(ours, None)["failed"], "missing_theirs")
        o = pd.DataFrame([ours])
        t = pd.DataFrame([theirs.to_dict(), {**theirs.to_dict(), "time": T // 1000 + 3600}])
        table = rb.compare_day(o, t, gaps_ms={"bybit": [(T + rb.HOUR_MS + 10, T + rb.HOUR_MS + 500_000)]})
        self.assertEqual(list(table["comparable"]), [True, False], "the second bar overlaps a recorded gap")
        self.assertEqual(list(table["failed"]), ["", "gap"])
        table = rb.compare_day(o, t, gaps_ms={})
        self.assertEqual(list(table["failed"]), ["", "missing_ours"], "no gap: a bar we lack is a miss")
        s = rb.day_summary(table)
        self.assertEqual((s["comparable"], s["matched"], s["excluded"], s["day_matches"]), (2, 1, 0, False))
        self.assertEqual(s["worst_field"], "missing_ours")

    def test_verdict_needs_thirty_days_then_95_percent(self):
        days = pd.DataFrame({"day": [f"d{i}" for i in range(40)], "bar": "1h", "comparable": 10,
                             "day_matches": [i != 0 for i in range(40)]})
        v = rb.verdict(days)
        self.assertEqual(v["days"], 40)
        self.assertTrue(v["a"])
        days.loc[1:2, "day_matches"] = False
        self.assertFalse(rb.verdict(days)["a"])
        self.assertIsNone(rb.verdict(days.head(10))["a"])


if __name__ == "__main__":
    unittest.main()
