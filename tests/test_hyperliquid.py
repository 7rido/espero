"""Hyperliquid info endpoint parsing, with the network replaced by a fake fetch."""
from __future__ import annotations

import unittest

from espero import hyperliquid as hl
from espero.venues import VENUES


def fake_ctxs(_body):
    meta = {"universe": [{"name": "BTC", "maxLeverage": 50}, {"name": "ETH", "maxLeverage": 50},
                         {"name": "OLD", "maxLeverage": 10, "isDelisted": True}]}
    ctxs = [{"markPx": "100000", "funding": "0.0000125", "openInterest": "1000", "dayNtlVlm": "5e9"},
            {"markPx": "3000", "funding": "-0.00001", "openInterest": "50000", "dayNtlVlm": "2e9"},
            {"markPx": "1", "funding": "0", "openInterest": "1", "dayNtlVlm": "1"}]
    return [meta, ctxs]


class TestContexts(unittest.TestCase):
    def test_rows_in_dollars_and_delisted_dropped(self):
        rows = hl.asset_contexts(fetch=fake_ctxs)
        self.assertEqual([r["coin"] for r in rows], ["BTC", "ETH"])
        self.assertAlmostEqual(rows[0]["open_interest"], 1000 * 100000)
        self.assertAlmostEqual(rows[1]["open_interest"], 50000 * 3000)
        self.assertAlmostEqual(rows[0]["funding"], 1.25e-5)

    def test_top_by_open_interest(self):
        rows = hl.asset_contexts(fetch=fake_ctxs)
        self.assertEqual(hl.top_by_open_interest(1, rows), ["ETH"])
        self.assertEqual(hl.top_by_open_interest(5, rows), ["ETH", "BTC"])


class TestFunding(unittest.TestCase):
    def test_pages_forward_and_dedups(self):
        calls = []

        def fetch(body):
            calls.append(body["startTime"])
            if body["startTime"] == 0:
                return [{"time": t * 3600_000, "fundingRate": "0.00001"} for t in range(500)]
            return [{"time": 499 * 3600_000, "fundingRate": "0.00001"},
                    {"time": 500 * 3600_000, "fundingRate": "0.00002"}]

        df = hl.funding_history("BTC", 0, fetch=fetch, sleep=lambda s: None)
        self.assertEqual(calls, [0, 499 * 3600_000 + 1])
        self.assertEqual(len(df), 501)
        self.assertEqual(df["ts"].iloc[-1], 500 * 3600)
        self.assertAlmostEqual(df["funding"].iloc[-1], 2e-5)

    def test_funding_rates_for_the_paper_trader(self):
        seen = []

        def fetch(body):
            seen.append(body)
            return [{"time": 7_200_004, "fundingRate": "0.0000125"}, {"time": 10_799_998, "fundingRate": "-0.00002"}]
        rates = hl.funding_rates("BCH-USD", fetch=fetch)(7200, 10800)
        self.assertEqual(seen[0]["coin"], "BCH")
        self.assertEqual(rates, {7200: 0.0000125, 10800: -0.00002})   # settlement times land on the hour

    def test_empty(self):
        df = hl.funding_history("X", 0, fetch=lambda b: [])
        self.assertTrue(df.empty)
        self.assertEqual(list(df.columns), ["ts", "funding"])


class TestCandles(unittest.TestCase):
    def test_paginates_under_cap_and_matches_data_frame(self):
        step = 3600_000
        calls = []

        def fetch(body):
            req = body["req"]
            calls.append((req["startTime"], req["endTime"]))
            t0 = req["startTime"]
            n = min(hl.CANDLE_LIMIT, (req["endTime"] - t0) // step)
            return [{"t": t0 + k * step, "o": "1", "h": "2", "l": "0.5", "c": "1.5", "v": "10"}
                    for k in range(n)]

        end = 6000 * step
        df = hl.candles("ETH", "1h", 0, end_ms=end, fetch=fetch, sleep=lambda s: None)
        self.assertEqual(len(calls), 2)
        self.assertEqual(len(df), 6000)
        self.assertEqual(list(df.columns), ["time", "open", "high", "low", "close", "volume"])
        self.assertTrue(df["time"].iloc[0].startswith("1970-01-01T00:00:00"))
        self.assertEqual(df["close"].iloc[-1], 1.5)

    def test_stops_on_empty_page(self):
        df = hl.candles("ETH", "1h", 0, end_ms=10 * 3600_000, fetch=lambda b: [])
        self.assertTrue(df.empty)


class TestNetwork(unittest.TestCase):
    def test_default_is_mainnet(self):
        self.assertEqual(hl.network({}), "mainnet")
        self.assertEqual(hl.info_url({}), "https://api.hyperliquid.xyz/info")

    def test_env_switches_to_testnet(self):
        env = {"HL_NETWORK": "testnet"}
        self.assertEqual(hl.network(env), "testnet")
        self.assertEqual(hl.info_url(env), "https://api.hyperliquid-testnet.xyz/info")

    def test_url_override_and_explicit_flag(self):
        env = {"HL_NETWORK": "testnet", "HL_API_URL": "http://localhost:8080/"}
        self.assertEqual(hl.info_url(env), "http://localhost:8080/info")
        self.assertEqual(hl.info_url(env, testnet=False), "https://api.hyperliquid.xyz/info")

    def test_bad_network_rejected(self):
        with self.assertRaises(ValueError):
            hl.network({"HL_NETWORK": "devnet"})


class TestUserState(unittest.TestCase):
    def test_parses_positions_and_skips_flat(self):
        def fetch(body):
            self.assertEqual(body, {"type": "clearinghouseState", "user": "0xabc"})
            return {"marginSummary": {"accountValue": "1000.5", "totalMarginUsed": "100",
                                      "totalNtlPos": "200"},
                    "withdrawable": "900",
                    "assetPositions": [
                        {"position": {"coin": "ETH", "szi": "-0.1", "entryPx": "2000",
                                      "positionValue": "200", "unrealizedPnl": "-1.5",
                                      "cumFunding": {"sinceOpen": "0.4"},
                                      "liquidationPx": "3900", "leverage": {"value": 1}}},
                        {"position": {"coin": "BTC", "szi": "0"}}]}
        st = hl.user_state("0xabc", fetch=fetch)
        self.assertEqual(st["equity"], 1000.5)
        self.assertEqual(len(st["positions"]), 1)
        p = st["positions"][0]
        self.assertEqual((p["coin"], p["side"], p["size"]), ("ETH", "short", -0.1))
        self.assertEqual(p["liquidation"], 3900.0)
        self.assertEqual(p["funding_paid"], 0.4)


class TestMarginMode(unittest.TestCase):
    def fetch(self, mode):
        def get(body):
            if body["type"] == "userAbstraction":
                if isinstance(mode, Exception):
                    raise mode
                return mode
            self.assertEqual(body, {"type": "spotClearinghouseState", "user": "0xabc"})
            return {"balances": [{"coin": "HYPE", "total": "3"}, {"coin": "USDC", "total": "967.74", "hold": "12.5"}]}
        return get

    def test_unified_account_reports_spot_usdc_as_margin(self):
        mm = hl.margin_mode("0xabc", fetch=self.fetch("unifiedAccount"))
        self.assertEqual(mm, {"mode": "unifiedAccount", "spot_usdc": 967.74, "spot_hold": 12.5})

    def test_an_api_without_the_query_is_the_classic_split(self):
        mm = hl.margin_mode("0xabc", fetch=self.fetch(RuntimeError("unknown type")))
        self.assertEqual(mm["mode"], "default")
        self.assertEqual(mm["spot_usdc"], 967.74)


class TestVenue(unittest.TestCase):
    def test_hyperliquid_row_settles_hourly(self):
        v = VENUES["hyperliquid"]
        self.assertEqual(v.kind, "perp")
        self.assertEqual(v.funding_period_s, 3600)
        self.assertEqual((v.maker_bps, v.taker_bps), (1.5, 4.5))
        self.assertEqual(VENUES["perp"].funding_period_s, 8 * 3600)


if __name__ == "__main__":
    unittest.main()


class TestPricesForEspero(unittest.TestCase):
    NOW = 1_793_250_000 + 1800          # half way through the 06:00 UTC hourly bar

    def candles(self, coin, px=100.0):
        def fetch(body):
            r = body["req"]
            self.assertEqual(r["coin"], coin)
            step = 3600_000 if r["interval"] == "1h" else 86_400_000
            first = (r["startTime"] + step - 1) // step * step
            # the API answers up to endTime; add the forming bar too, as it does
            return [{"t": t, "o": str(px), "h": str(px), "l": str(px), "c": str(px + t / 1e12), "v": "2"}
                    for t in range(first, r["endTime"] + 2 * step, step)]
        return fetch

    def test_closed_bars_drop_the_bar_still_forming(self):
        df = hl.closed_bars("LTC-USD", 3600, 5, fetch=self.candles("LTC"), now=self.NOW)
        self.assertEqual(len(df), 5)
        self.assertLessEqual(int(df["ts"].iloc[-1]) + 3600, self.NOW)
        self.assertEqual(list(df.columns), ["dt", "ts", "open", "high", "low", "close", "volume"])

    def test_kshib_is_converted_back_to_one_coin(self):
        df = hl.closed_bars("SHIB-USD", 3600, 3, fetch=self.candles("kSHIB", px=0.005), now=self.NOW)
        self.assertAlmostEqual(df["open"].iloc[0], 0.005 / 1000)
        self.assertEqual(df["volume"].iloc[0], 2000.0)

    def test_daily_is_shaped_like_yahoo_adjusted(self):
        df = hl.daily("BTC-USD", "30d", fetch=self.candles("BTC"), now=self.NOW)
        self.assertEqual(len(df), 30)
        self.assertTrue((df["adj_close"] == df["close"]).all())

    def test_book_reads_levels_and_only_new_prints(self):
        trades = [[{"tid": 1, "time": 1_000, "side": "B", "px": "10", "sz": "1"}],
                  [{"tid": 1, "time": 1_000, "side": "B", "px": "10", "sz": "1"},
                   {"tid": 2, "time": 2_000, "side": "A", "px": "9.9", "sz": "3"}]]

        def fetch(body):
            if body["type"] == "l2Book":
                return {"levels": [[{"px": "9.9", "sz": "5", "n": 1}], [{"px": "10.1", "sz": "4", "n": 2}]]}
            return trades.pop(0)
        book = hl.HyperliquidBook("LTC-USD", fetch=fetch)
        first = book.read()
        self.assertEqual((first.best_bid, first.best_ask, first.trades), (9.9, 10.1, []))   # no "since" yet
        second = book.read()
        self.assertEqual([(t.id, t.side, t.price, t.size) for t in second.trades], [(2, "sell", 9.9, 3.0)])
