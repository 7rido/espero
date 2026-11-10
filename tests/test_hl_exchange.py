"""Testnet-only signing: the guards, the rounding, the mirror. No key, no network."""
from __future__ import annotations

import sqlite3
import tempfile
import unittest
from pathlib import Path

from espero import carry_paper as cp
from espero import hl_exchange as hx

GOOD = {"HL_NETWORK": "testnet", "ESPERO_ALLOW_HL_TESTNET": "1", "HL_PRIVATE_KEY": "0x" + "1" * 64}


class TestGuard(unittest.TestCase):
    def test_all_four_conditions(self):
        self.assertEqual(hx.guard(GOOD), GOOD["HL_PRIVATE_KEY"])
        for broken in ({**GOOD, "HL_NETWORK": "mainnet"}, {**GOOD, "HL_NETWORK": ""},
                       {**GOOD, "ESPERO_ALLOW_HL_TESTNET": ""}, {**GOOD, "ESPERO_ALLOW_HL_TESTNET": "yes"},
                       {**GOOD, "HL_PRIVATE_KEY": ""},
                       {**GOOD, "HL_API_URL": "https://api.hyperliquid.xyz"}):
            with self.assertRaises(hx.TestnetRefused):
                hx.guard(broken)

    def test_testnet_url_override_allowed(self):
        for url in ("https://api.hyperliquid-testnet.xyz", "https://api.hyperliquid-testnet.xyz/"):
            self.assertEqual(hx.guard({**GOOD, "HL_API_URL": url}), GOOD["HL_PRIVATE_KEY"])

    def test_the_url_guard_reads_the_host_not_the_word(self):
        """A URL that merely contains "testnet" is not the testnet."""
        for url in ("https://api.hyperliquid.xyz/?testnet", "https://api.hyperliquid.xyz#testnet",
                    "https://testnet.evil.example/", "https://api.hyperliquid-testnet.xyz.evil.example",
                    "api.hyperliquid-testnet.xyz", "not a url"):
            with self.subTest(url=url), self.assertRaises(hx.TestnetRefused):
                hx.guard({**GOOD, "HL_API_URL": url})

    def test_building_without_injection_reads_no_key_when_guard_fails(self):
        with self.assertRaises(hx.TestnetRefused):
            hx.TestnetExchange(env={"HL_NETWORK": "mainnet", "HL_PRIVATE_KEY": "x"})


class TestRounding(unittest.TestCase):
    def test_price_five_sig_figs_and_side_aware(self):
        self.assertEqual(hx.round_price(80752.123, 5, "sell"), 80753.0)
        self.assertEqual(hx.round_price(80752.123, 5, "buy"), 80752.0)
        self.assertEqual(hx.round_price(2344.5678, 4, "buy"), 2344.5)
        self.assertEqual(hx.round_price(0.0043537, 0, "sell"), 0.004354)   # 6 decimals cap
        self.assertEqual(hx.round_price(1.234567, 0, "buy"), 1.2345)

    def test_size_floors_to_sz_decimals(self):
        self.assertEqual(hx.round_size(0.0019, 3), 0.001)
        self.assertEqual(hx.round_size(12.3456, 1), 12.3)

    def test_size_already_on_the_grid_stays_put(self):
        # #40's testnet session: 0.00014 floored to 0.00013 and left 0.00011 BTC open
        for sz, sd in ((0.00014, 5), (0.29, 2), (0.57, 2), (0.0052, 4), (1.15, 2)):
            self.assertEqual(hx.round_size(sz, sd), sz)

    def test_parse_order_response(self):
        resting = {"status": "ok", "response": {"type": "order", "data": {"statuses": [{"resting": {"oid": 7}}]}}}
        self.assertEqual(hx.parse_order_response(resting)["status"], "resting")
        filled = {"filled": {"oid": 8, "totalSz": "0.5", "avgPx": "9"}}
        f = hx.parse_order_response({"status": "ok", "response": {"data": {"statuses": [filled]}}})
        self.assertEqual((f["status"], f["oid"], f["filled"], f["avg_px"]), ("filled", 8, 0.5, 9.0))
        e = hx.parse_order_response({"status": "ok", "response": {"data": {"statuses": [{"error": "Post only"}]}}})
        self.assertEqual((e["status"], e["error"]), ("error", "Post only"))
        self.assertEqual(hx.parse_order_response("garbage")["status"], "error")


class FakeExchange:
    """Records orders; `resting` unless told to fill."""

    def __init__(self, fill=False):
        self.orders, self.cancels, self.fill = [], [], fill
        self.base_url = hx.TESTNET_URL

    def order(self, name, is_buy, sz, px, order_type, reduce_only=False, **kw):
        tif = order_type["limit"]["tif"] if "limit" in order_type else order_type
        self.orders.append((name, "buy" if is_buy else "sell", sz, px, tif, reduce_only))
        oid = len(self.orders)
        if self.fill:
            st = {"filled": {"oid": oid, "totalSz": str(sz), "avgPx": str(px)}}
        else:
            st = {"resting": {"oid": oid}}
            self.info.open.append({"oid": oid})         # the venue lists a resting order
        return {"status": "ok", "response": {"data": {"statuses": [st]}}}

    def cancel(self, name, oid):
        self.cancels.append((name, oid))
        self.info.open = [o for o in self.info.open if o["oid"] != oid]
        return {"status": "ok"}


class FakeInfo:
    def __init__(self):
        self.open, self.fills_ = [], []
        self.books = {"ETH": (1999.0, 2001.0), "BTC": (79990.0, 80010.0), "xyz:NVDA": (180.0, 180.1)}

    def l2_snapshot(self, coin):
        bid, ask = self.books[coin]
        return {"levels": [[{"px": str(bid), "sz": "1"}], [{"px": str(ask), "sz": "1"}]]}

    def meta(self, dex=""):
        if dex == "xyz":
            return {"universe": [{"name": "xyz:NVDA", "szDecimals": 3}, {"name": "xyz:OLD", "szDecimals": 2,
                                                                       "isDelisted": True}]}
        if dex:
            raise ValueError(dex)
        return {"universe": [{"name": "ETH", "szDecimals": 4}, {"name": "BTC", "szDecimals": 5}]}

    def open_orders(self, address):
        return self.open

    def user_fills(self, address):
        return self.fills_


def exchange(fill=False, dexes=()):
    info = FakeInfo()
    fake = FakeExchange(fill)
    fake.info = info
    return hx.TestnetExchange(exchange=fake, info=info, address="0xtest", dexes=dexes)


class TestExchange(unittest.TestCase):
    def test_limit_rounds_and_posts_alo(self):
        ex = exchange()
        r = ex.limit("ETH", "sell", 0.12345678, 2344.5678)
        self.assertEqual(ex.ex.orders[0], ("ETH", "sell", 0.1234, 2344.6, "Alo", False))
        self.assertEqual((r.status, r.oid), ("resting", 1))

    def test_cloid_is_passed_only_when_given(self):
        ex = exchange()
        seen = []
        order = ex.ex.order
        ex.ex.order = lambda *a, **kw: (seen.append(kw), order(*a, **kw))[1]
        ex.limit("ETH", "buy", 0.1, 2000, tif="Ioc", cloid="0x" + "a" * 32)
        ex.limit("ETH", "buy", 0.1, 2000, tif="Ioc")
        self.assertEqual(str(seen[0]["cloid"]), "0x" + "a" * 32)
        self.assertNotIn("cloid", seen[1])

    def test_unknown_coin_and_zero_size_refused(self):
        ex = exchange()
        with self.assertRaises(ValueError):
            ex.limit("DOGE", "sell", 1, 1)
        with self.assertRaises(ValueError):
            ex.limit("BTC", "sell", 0.000001, 80000)

    def test_a_price_that_rounds_to_zero_is_refused(self):
        ex = exchange()
        with self.assertRaises(ValueError):
            ex.limit("BTC", "buy", 1, 3e-7)                 # a buy rounds down, to 0.0 at 6 decimals


class TestBuilderExchanges(unittest.TestCase):
    def test_a_builder_exchange_s_coins_are_known_only_when_asked_for(self):
        self.assertNotIn("xyz:NVDA", exchange().meta)
        ex = exchange(dexes=("xyz",))
        self.assertEqual(ex.meta["xyz:NVDA"], 3)
        self.assertNotIn("xyz:OLD", ex.meta)                          # delisted
        self.assertEqual(ex.meta["ETH"], 4)                           # the venue's own perps stay
        r = ex.limit("xyz:NVDA", "buy", 1.23456, 180.123)
        self.assertEqual(ex.ex.orders[0], ("xyz:NVDA", "buy", 1.234, 180.12, "Alo", False))
        self.assertEqual(ex.book("xyz:NVDA"), (180.0, 180.1))
        self.assertEqual(r.status, "resting")
        with self.assertRaises(ValueError):
            exchange().limit("xyz:NVDA", "buy", 1, 180)

    def test_only_a_plain_name_is_a_builder_exchange(self):
        for bad in ("", "XYZ", "xyz:NVDA", "x:y", "x y", "a" * 17, "../x"):
            with self.assertRaises(ValueError):
                exchange(dexes=(bad,))
        self.assertEqual(exchange(dexes=("xyz", "flx")).dexes, ("xyz", "flx"))

    def test_the_testnet_guard_still_comes_first(self):
        with self.assertRaises(hx.TestnetRefused):
            hx.TestnetExchange(env={"HL_NETWORK": "mainnet", "HL_PRIVATE_KEY": "x"}, dexes=("xyz",))


class TestTheSdkIsToldTheDexes(unittest.TestCase):
    """The injected fakes skip building the SDK's clients; this builds them from stand-in modules."""

    def build(self, dexes):
        import sys
        import types
        from unittest import mock

        seen = {}

        class Exchange:
            base_url = hx.TESTNET_URL

            def __init__(self, wallet, base_url=None, account_address=None, perp_dexs=None):
                seen["exchange"] = (base_url, perp_dexs)

        class Info:
            def __init__(self, base_url=None, skip_ws=False, perp_dexs=None):
                seen["info"] = (base_url, perp_dexs)

        wallet = types.SimpleNamespace(address="0x" + "1" * 40)
        mods = {"eth_account": types.SimpleNamespace(Account=types.SimpleNamespace(from_key=lambda k: wallet)),
                "hyperliquid": types.ModuleType("hyperliquid"),
                "hyperliquid.exchange": types.SimpleNamespace(Exchange=Exchange),
                "hyperliquid.info": types.SimpleNamespace(Info=Info)}
        with mock.patch.dict(sys.modules, mods):
            hx.TestnetExchange(env=GOOD, dexes=dexes)
        return seen

    def test_the_venue_s_own_perps_come_first_and_only_the_named_dexes_follow(self):
        seen = self.build(("xyz",))
        self.assertEqual(seen["exchange"], (hx.TESTNET_URL, ["", "xyz"]))
        self.assertEqual(seen["info"], (hx.TESTNET_URL, ["", "xyz"]))
        seen = self.build(())
        self.assertEqual((seen["exchange"][1], seen["info"][1]), (None, None))        # as it always was


class TestStop(unittest.TestCase):
    def test_a_reduce_only_trigger_with_a_worst_price_beyond_it(self):
        ex = exchange(dexes=("xyz",))
        r = ex.stop("xyz:NVDA", "sell", 1.23456, 176.789, cloid="0x" + "b" * 32)
        name, side, sz, worst, kind, reduce_only = ex.ex.orders[0]
        self.assertEqual((name, side, sz, reduce_only), ("xyz:NVDA", "sell", 1.234, True))
        self.assertEqual(kind, {"trigger": {"triggerPx": 176.79, "isMarket": True, "tpsl": "sl"}})
        self.assertEqual(worst, 167.95)                              # 5% under the trigger, rounded for a sell
        self.assertEqual((r.status, r.tif, r.price), ("resting", "Stop", 176.79))

    def test_a_buy_stop_for_a_short_goes_the_other_way(self):
        ex = exchange()
        ex.stop("ETH", "buy", 0.5, 2100.0)
        _, side, _, worst, kind, reduce_only = ex.ex.orders[0]
        self.assertEqual((side, worst, reduce_only), ("buy", 2205.0, True))
        self.assertEqual(kind["trigger"]["triggerPx"], 2100.0)

    def test_refusals(self):
        ex = exchange()
        for args in (("DOGE", "sell", 1, 1), ("ETH", "hold", 1, 1), ("ETH", "sell", 1, 0),
                     ("ETH", "sell", 0.00001, 100)):
            with self.assertRaises(ValueError):
                ex.stop(*args)
        self.assertEqual(ex.ex.orders, [])


class TestMirrorGrace(unittest.TestCase):
    def test_just_placed_order_not_listed_yet_stays_resting(self):
        with tempfile.TemporaryDirectory() as d:
            book = cp.CarryBook(Path(d) / "b.db", costs="maker", initial=500.0, max_coins=1)
            ex = exchange()
            mirror = hx.TestnetMirror(book.db, ex)
            book.on_hour(3600, {"ETH": cp.Row(1e-5, 0.2, 2000.0, 1999.0)})
            mirror.sync(book.open_positions(), book.closed_positions(), {"ETH": 2000.0}, now=3600)
            ex.info.open = []                                   # venue lagging
            mirror.refresh(now=3601)
            self.assertEqual(mirror.rows()[0]["open_status"], "resting")
            mirror.refresh(now=3600 + 120)                      # past the grace: really gone
            self.assertEqual(mirror.rows()[0]["open_status"], "cancelled")
            book.close()


class TestMirror(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.book = cp.CarryBook(Path(self.tmp.name) / "b.db", costs="maker", initial=500.0, max_coins=1)
        self.ex = exchange()
        self.mirror = hx.TestnetMirror(self.book.db, self.ex)

    def tearDown(self):
        self.book.close()
        self.tmp.cleanup()

    def rows(self, f_ann=0.2, perp=2000.0):
        return {"ETH": cp.Row(funding=1e-5, f_ann=f_ann, perp=perp, spot=1999.0)}

    def test_new_paper_position_becomes_a_resting_short(self):
        self.book.on_hour(3600, self.rows())
        out = self.mirror.sync(self.book.open_positions(), self.book.closed_positions(), {"ETH": 2000.0}, now=3600)
        self.assertEqual(len(self.ex.ex.orders), 1)
        name, side, sz, px, tif, ro = self.ex.ex.orders[0]
        self.assertEqual((name, side, tif, ro), ("ETH", "sell", "Alo", False))
        self.assertAlmostEqual(sz, round(250.0 / 2000.0, 4))
        self.assertEqual(self.mirror.rows()[0]["open_status"], "resting")
        # a second sync places nothing new
        self.mirror.sync(self.book.open_positions(), self.book.closed_positions(), {"ETH": 2000.0}, now=3601)
        self.assertEqual(len(self.ex.ex.orders), 1)
        self.assertTrue(any("resting" in o for o in out))

    def test_unfilled_open_is_cancelled_when_paper_closes(self):
        self.book.on_hour(3600, self.rows())
        self.mirror.sync(self.book.open_positions(), self.book.closed_positions(), {"ETH": 2000.0}, now=3600)
        self.book.on_hour(7200, self.rows(f_ann=0.01))          # paper exits: funding_low
        self.mirror.sync(self.book.open_positions(), self.book.closed_positions(), {"ETH": 2000.0}, now=7200)
        self.assertEqual(self.ex.ex.cancels, [("ETH", 1)])
        self.assertEqual(self.mirror.rows()[0]["close_status"], "unfilled_open")
        self.assertEqual(len(self.ex.ex.orders), 1)              # no close order for nothing

    def test_filled_open_gets_a_reduce_only_close(self):
        self.ex.ex.fill = True
        self.book.on_hour(3600, self.rows())
        self.mirror.sync(self.book.open_positions(), self.book.closed_positions(), {"ETH": 2000.0}, now=3600)
        self.assertEqual(self.mirror.rows()[0]["open_status"], "filled")
        self.book.on_hour(7200, self.rows(f_ann=0.01))
        self.mirror.sync(self.book.open_positions(), self.book.closed_positions(), {"ETH": 2010.0}, now=7200)
        self.assertEqual(self.ex.ex.orders[1][:2], ("ETH", "buy"))
        self.assertTrue(self.ex.ex.orders[1][5])                  # reduce-only
        self.assertEqual(self.mirror.summary()["filled"], 1)

    def test_refresh_reads_fills_and_open_orders(self):
        self.book.on_hour(3600, self.rows())
        self.mirror.sync(self.book.open_positions(), self.book.closed_positions(), {"ETH": 2000.0}, now=3600)
        size = self.mirror.rows()[0]["open_size"]
        self.ex.info.fills_ = [{"oid": 1, "sz": str(size / 2), "time": 3600_000}]
        self.mirror.refresh(now=10_000)
        self.assertEqual(self.mirror.rows()[0]["open_status"], "part")
        self.ex.info.fills_.append({"oid": 1, "sz": str(size / 2), "time": 3601_000})
        self.mirror.refresh(now=10_000)
        self.assertEqual(self.mirror.rows()[0]["open_status"], "filled")

    def test_order_error_is_recorded_not_raised(self):
        err = {"status": "ok", "response": {"data": {"statuses": [{"error": "Post only would cross"}]}}}
        self.ex.ex.order = lambda *a, **k: err
        self.book.on_hour(3600, self.rows())
        out = self.mirror.sync(self.book.open_positions(), self.book.closed_positions(), {"ETH": 2000.0}, now=3600)
        self.assertEqual(self.mirror.rows()[0]["open_status"], "error")
        self.assertIn("Post only", out[0])
        self.assertEqual(self.mirror.summary()["errors"], 1)

    def test_mirror_survives_reopen(self):
        self.book.on_hour(3600, self.rows())
        self.mirror.sync(self.book.open_positions(), self.book.closed_positions(), {"ETH": 2000.0}, now=3600)
        db = sqlite3.connect(self.book.path)
        db.row_factory = sqlite3.Row
        again = hx.TestnetMirror(db, exchange())
        self.assertEqual(len(again.rows()), 1)
        db.close()



class TestMirrorAudit(unittest.TestCase):
    """2026-10-27 audit, section C."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.book = cp.CarryBook(Path(self.tmp.name) / "b.db", costs="maker", initial=500.0, max_coins=1)
        self.ex = exchange()
        self.mirror = hx.TestnetMirror(self.book.db, self.ex)

    def tearDown(self):
        self.book.close()
        self.tmp.cleanup()

    def rows(self, f_ann=0.2):
        return {"ETH": cp.Row(funding=1e-5, f_ann=f_ann, perp=2000.0, spot=1999.0)}

    def open_and_close(self, fill_part=None):
        self.book.on_hour(3600, self.rows())
        self.mirror.sync(self.book.open_positions(), self.book.closed_positions(), {"ETH": 2000.0}, now=3600)
        if fill_part is not None:
            self.ex.info.fills_ = [{"oid": 1, "sz": str(fill_part), "time": 3700_000}]
        self.book.on_hour(7200, self.rows(f_ann=0.01))
        return self.mirror.sync(self.book.open_positions(), self.book.closed_positions(),
                                {"ETH": 2000.0}, now=7200)

    def test_orders_are_priced_from_the_testnet_book_not_mainnet(self):
        self.book.on_hour(3600, self.rows())
        self.mirror.sync(self.book.open_positions(), self.book.closed_positions(), {"ETH": 2500.0}, now=3600)
        self.assertEqual(self.ex.ex.orders[0][3], 2001.0)               # the testnet ask
        self.assertEqual(self.mirror.rows()[0]["paper_px"], 2500.0)     # the gap is recorded

    def test_part_filled_open_is_cancelled_and_only_the_fill_bought_back(self):
        self.open_and_close(fill_part=0.05)
        self.assertIn(("ETH", 1), self.ex.ex.cancels)
        name, side, sz, px, tif, ro = self.ex.ex.orders[-1]
        self.assertEqual((side, sz, px, tif, ro), ("buy", 0.05, 1999.0, "Alo", True))

    def test_unfilled_close_is_repriced_then_crosses_after_three_tries(self):
        self.open_and_close(fill_part=0.05)
        ex, now = self.ex.ex, 7200
        for k in range(3):
            now += hx.REPRICE_S + 1
            self.ex.info.open = [{"oid": len(ex.orders)}]               # the close still rests
            self.mirror.sync(self.book.open_positions(), self.book.closed_positions(), {"ETH": 2000.0}, now=now)
        tifs = [o[4] for o in ex.orders[1:]]
        self.assertEqual(tifs, ["Alo", "Alo", "Alo", "Ioc"])
        self.assertEqual(ex.orders[-1][3], 2001.0)                     # crosses at the ask
        self.assertTrue(all(o[5] for o in ex.orders[1:]))               # all reduce-only

    def test_a_close_that_filled_is_not_placed_again(self):
        self.ex.ex.fill = True
        self.open_and_close()
        n = len(self.ex.ex.orders)
        self.mirror.sync(self.book.open_positions(), self.book.closed_positions(), {"ETH": 2000.0},
                         now=7200 + hx.REPRICE_S + 1)
        self.assertEqual(len(self.ex.ex.orders), n)
        self.assertEqual(self.mirror.rows()[0]["close_status"], "filled")

    def test_order_lost_to_a_timeout_is_recovered_from_open_orders(self):
        def timeout(name, is_buy, sz, px, order_type, reduce_only=False, **kw):
            self.ex.info.open.append({"oid": 77, "coin": name, "side": "B" if is_buy else "A",
                                      "sz": str(sz), "limitPx": str(px)})
            raise TimeoutError("read timed out")
        self.ex.ex.order = timeout
        self.book.on_hour(3600, self.rows())
        self.mirror.sync(self.book.open_positions(), self.book.closed_positions(), {"ETH": 2000.0}, now=3600)
        row = self.mirror.rows()[0]
        self.assertEqual((row["open_oid"], row["open_status"]), (77, "resting"))
        self.assertIn("recovered", row["note"])

    def test_old_mirror_table_gains_the_new_columns(self):
        db = sqlite3.connect(":memory:")
        db.executescript(hx.MIRROR_SCHEMA)
        hx.TestnetMirror(db, exchange())
        cols = {r[1] for r in db.execute("PRAGMA table_info(testnet_mirror)")}
        self.assertTrue(set(hx.MIRROR_COLUMNS) <= cols)


class TestAccountAddress(unittest.TestCase):
    def test_wallet_address_must_be_well_formed(self):
        good = "0x" + "ab" * 20
        self.assertEqual(hx.account_address({"HL_WALLET_ADDRESS": good}), good)
        for bad in ("", "0x123", "not an address", "0x" + "g" * 40):
            self.assertIsNone(hx.account_address({"HL_WALLET_ADDRESS": bad}))

    def test_api_wallet_signs_for_the_main_account(self):
        if __import__("importlib").util.find_spec("hyperliquid") is None:
            self.skipTest("hyperliquid SDK not installed")
        from unittest import mock
        main = "0x" + "cd" * 20
        with mock.patch("hyperliquid.exchange.Info"), mock.patch("hyperliquid.info.Info"):   # no network
            ex = hx.TestnetExchange(env={**GOOD, "HL_WALLET_ADDRESS": main})
        self.assertEqual(ex.address, main)
        self.assertEqual(ex.ex.account_address, main)
        self.assertEqual(ex.ex.base_url, hx.TESTNET_URL)


if __name__ == "__main__":
    unittest.main()
