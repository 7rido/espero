"""#59's testnet executor: entries, exits, lost calls, the kill switch. Fake venue, no key, no network."""
from __future__ import annotations

import sqlite3
import tempfile
import unittest
from pathlib import Path

from espero import hlp_testnet as ht
from espero.hl_exchange import OrderResult, round_price, round_size
from espero.hlpbook import HOLD_S, SCHEMA

T = 1_800_000_000          # a signal's ts
META = {"ETH": 4, "BTC": 5, "DOGE": 0}


class FakeVenue:
    """The TestnetExchange calls the executor uses. Each order fills `fill_frac` of its size at its limit."""

    def __init__(self):
        self.meta = dict(META)
        self.books = {"ETH": (1999.0, 2001.0), "BTC": (79990.0, 80010.0), "DOGE": (0.0999, 0.1001)}
        self.orders, self.fills_, self.status = [], [], {}
        self.fill_frac, self.raise_next, self.no_book = [1.0], 0, set()

    def book(self, coin):
        if coin in self.no_book:
            raise ValueError("empty testnet book")
        return self.books[coin]

    def limit(self, coin, side, size, price, tif="Alo", reduce_only=False, cloid=None):
        sd = self.meta[coin]
        sz, px = round_size(size, sd), round_price(price, sd, side)
        self.orders.append({"coin": coin, "side": side, "size": sz, "price": px, "tif": tif,
                            "reduce_only": reduce_only, "cloid": cloid})
        oid = len(self.orders)
        frac = self.fill_frac.pop(0) if len(self.fill_frac) > 1 else self.fill_frac[0]
        got = round_size(sz * frac, sd)
        if got:
            self.fills_.append({"oid": oid, "sz": str(got), "px": str(px), "fee": str(round(got * px * 4.5e-4, 6))})
        self.status[cloid] = {"status": "order", "order": {"order": {"oid": oid, "origSz": str(sz),
                                                                     "sz": str(sz - got)}, "status": "filled"}}
        if self.raise_next:
            self.raise_next -= 1
            raise TimeoutError("read timed out")
        return OrderResult(coin, side, sz, px, tif, "filled" if got else "error", oid, got,
                           px if got else None, None if got else "IOC could not match")

    def order_status(self, cloid):
        return self.status.get(cloid, {"status": "unknownOid"})

    def fills(self, since_ts=0):
        return list(self.fills_)


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        d = Path(self.tmp.name)
        self.book, self.state = d / "hlp2-book.db", d / "hlp2-testnet.db"
        db = sqlite3.connect(self.book)
        db.execute(SCHEMA)
        db.commit()
        db.close()
        self.venue = FakeVenue()
        self.lines = []
        self.ex = ht.Executor(self.state, self.book, self.venue, usd=100.0, log=self.lines.append)

    def tearDown(self):
        self.ex.close()
        self.tmp.cleanup()

    def paper(self, coin, ts=T, status="pending"):
        db = sqlite3.connect(self.book)
        db.execute("INSERT OR REPLACE INTO trades (coin, signal_ts, status, recorded_ts) VALUES (?,?,?,?)",
                   (coin, ts, status, ts))
        db.commit()
        db.close()

    def row(self, coin="ETH", ts=T):
        return self.ex.rows("coin=? AND signal_ts=?", (coin, ts))[0]


class TestEntry(Base):
    def test_fresh_signal_is_bought_with_a_crossing_ioc(self):
        self.paper("ETH")
        self.ex.step(now=T + 90)
        o = self.venue.orders[0]
        self.assertEqual((o["side"], o["tif"], o["reduce_only"]), ("buy", "Ioc", False))
        self.assertEqual(o["size"], round_size(100 / 2001.0, 4))
        self.assertEqual(o["price"], round_price(2001.0 * 1.005, 4, "buy"))
        self.assertEqual(o["cloid"], ht.cloid("ETH", T, "entry"))
        r = self.row()
        self.assertEqual((r["status"], r["qty"], r["entry_mid"]), ("open", o["size"], 2000.0))
        self.assertEqual(r["exit_due"], T + 90 + HOLD_S)

    def test_signal_at_the_tolerance_is_bought_and_one_second_past_it_is_late(self):
        self.paper("ETH")
        self.paper("BTC")
        self.ex.step(now=T + ht.LATE_S)
        self.assertEqual(self.row("ETH")["status"], "open")
        self.paper("DOGE", ts=T)
        self.ex.step(now=T + ht.LATE_S + 1)
        self.assertEqual(self.row("DOGE")["status"], "late")
        self.assertEqual(len(self.venue.orders), 2)

    def test_coin_missing_on_testnet_and_paper_skips_send_nothing(self):
        self.paper("XRP")
        for status in ("ignored", "dropped_entry"):
            self.paper("ETH", ts=T + len(status), status=status)
        self.ex.step(now=T + 60)
        self.assertEqual(self.row("XRP")["status"], "not_on_testnet")
        self.assertEqual({r["status"] for r in self.ex.rows("coin='ETH'")}, {"paper_skip"})
        self.assertEqual(self.venue.orders, [])

    def test_every_status_the_book_takes_a_trade_with_is_entered(self):
        for i, status in enumerate(("pending", "open", "closed")):
            self.paper(("ETH", "BTC", "DOGE")[i], status=status)
        self.ex.step(now=T + 60)
        self.assertEqual(len(self.venue.orders), 3)

    def test_zero_fill_is_unfilled_and_not_retried(self):
        self.venue.fill_frac = [0.0]
        self.paper("ETH")
        self.ex.step(now=T + 60)
        self.ex.step(now=T + 120)
        self.assertEqual(self.row()["status"], "unfilled")
        self.assertEqual(len(self.venue.orders), 1)

    def test_no_book_is_retried_while_fresh_then_given_up(self):
        self.venue.no_book.add("ETH")
        self.paper("ETH")
        self.ex.step(now=T + 60)
        self.assertEqual(self.row()["status"], "entering")
        self.venue.no_book.clear()
        self.ex.step(now=T + 120)
        self.assertEqual(self.row()["status"], "open")
        self.paper("BTC")
        self.venue.no_book.add("BTC")
        self.ex.step(now=T + 200)
        self.ex.step(now=T + ht.LATE_S + 1)
        self.assertEqual(self.row("BTC")["status"], "late")

    def test_a_coin_still_held_is_not_bought_twice(self):
        self.paper("ETH")
        self.ex.step(now=T + 60)
        self.paper("ETH", ts=T + 900)
        self.ex.step(now=T + 960)
        self.assertEqual(self.row(ts=T + 900)["status"], "held")
        self.assertEqual(len(self.venue.orders), 1)

    def test_partial_entry_holds_what_filled(self):
        self.venue.fill_frac = [0.5, 1.0]
        self.paper("ETH")
        self.ex.step(now=T + 60)
        r = self.row()
        self.assertEqual(r["qty"], round_size(self.venue.orders[0]["size"] * 0.5, 4))
        self.ex.step(now=T + 60 + HOLD_S)
        self.assertEqual(self.venue.orders[1]["size"], r["qty"])

    def test_under_the_minimum_is_refused(self):
        with self.assertRaises(ValueError):
            ht.Executor(self.state, self.book, self.venue, usd=10.0)

    def test_the_paper_journal_is_never_written(self):
        self.paper("ETH")
        before = self.book.read_bytes()
        self.ex.step(now=T + 60)
        self.ex.step(now=T + 60 + HOLD_S)
        self.assertEqual(self.book.read_bytes(), before)

    def test_no_journal_yet_is_quiet(self):
        self.book.unlink()
        self.assertEqual(self.ex.step(now=T), [])


class TestExit(Base):
    def setUp(self):
        super().setUp()
        self.paper("ETH")
        self.ex.step(now=T + 60)
        self.qty = self.row()["qty"]

    def test_nothing_is_sold_before_four_hours(self):
        self.ex.step(now=T + 60 + HOLD_S - 1)
        self.assertEqual(len(self.venue.orders), 1)
        self.assertEqual(self.row()["status"], "open")

    def test_at_four_hours_the_exact_quantity_is_sold_without_reduce_only(self):
        self.ex.step(now=T + 60 + HOLD_S)
        o = self.venue.orders[1]
        self.assertEqual((o["side"], o["tif"], o["reduce_only"], o["size"]), ("sell", "Ioc", False, self.qty))
        self.assertEqual(o["price"], round_price(1999.0 * (1 - ht.EXIT_SLIPS[0]), 4, "sell"))
        r = self.row()
        self.assertEqual((r["status"], r["exited"], r["exit_tries"]), ("closed", self.qty, 1))
        self.ex.step(now=T + 60 + HOLD_S + 60)
        self.assertEqual(len(self.venue.orders), 2)

    def test_unfilled_exit_crosses_further_each_try_and_sells_only_the_rest(self):
        self.venue.fill_frac = [0.0, 0.5, 0.0, 0.0, 1.0]
        for k in range(5):
            self.ex.step(now=T + 60 + HOLD_S + 60 * k)
        sells = self.venue.orders[1:]
        want = [round_price(1999.0 * (1 - s), 4, "sell") for s in ht.EXIT_SLIPS] + \
               [round_price(1999.0 * (1 - ht.EXIT_SLIPS[-1]), 4, "sell")]
        self.assertEqual([o["price"] for o in sells], want)
        self.assertEqual(sells[2]["size"], round_size(self.qty - round_size(self.qty * 0.5, 4), 4))
        self.assertEqual(len({o["cloid"] for o in sells}), 5)
        self.assertEqual(self.row()["status"], "closed")

    def test_exit_price_averages_the_partial_fills(self):
        self.venue.fill_frac = [0.5, 1.0]
        self.ex.step(now=T + 60 + HOLD_S)
        self.ex.step(now=T + 120 + HOLD_S)
        r = self.row()
        a, b = self.venue.orders[1], self.venue.orders[2]
        half = round_size(self.qty * 0.5, 4)
        want = (a["price"] * half + b["price"] * (self.qty - half)) / self.qty
        self.assertAlmostEqual(r["exit_px"], want)

    def test_dust_under_the_minimum_closes_without_an_order(self):
        self.venue.books["ETH"] = (100.0, 101.0)          # 0.05 ETH is now worth $5
        self.ex.step(now=T + 60 + HOLD_S)
        self.assertEqual(len(self.venue.orders), 1)
        self.assertEqual(self.row()["status"], "closed")
        self.assertIn("minimum", self.row()["note"])

    def test_restart_keeps_the_trade_and_exits_on_time(self):
        self.ex.close()
        self.ex = ht.Executor(self.state, self.book, self.venue, usd=100.0, log=self.lines.append)
        self.ex.step(now=T + 120)
        self.assertEqual(len(self.venue.orders), 1)
        self.ex.step(now=T + 60 + HOLD_S)
        self.assertEqual(self.row()["status"], "closed")

    def test_fees_are_taken_from_the_venue_fills(self):
        self.ex.step(now=T + 60 + HOLD_S)
        self.ex.step(now=T + 120 + HOLD_S)
        r = self.row()
        self.assertAlmostEqual(r["entry_fee"], float(self.venue.fills_[0]["fee"]))
        self.assertAlmostEqual(r["exit_fee"], float(self.venue.fills_[1]["fee"]))


class TestLostCalls(Base):
    def test_entry_lost_to_a_timeout_is_found_by_cloid(self):
        self.venue.raise_next = 1
        self.paper("ETH")
        self.ex.step(now=T + 60)
        self.assertEqual(self.row()["inflight"], ht.cloid("ETH", T, "entry"))
        self.ex.step(now=T + 90)
        r = self.row()
        self.assertEqual((r["status"], r["qty"], r["inflight"]), ("open", self.venue.orders[0]["size"], None))
        self.assertEqual(r["entry_px"], self.venue.orders[0]["price"])
        self.assertEqual(len(self.venue.orders), 1)

    def test_partial_fill_found_by_cloid_holds_only_what_filled(self):
        self.venue.raise_next, self.venue.fill_frac = 1, [0.5]
        self.paper("ETH")
        self.ex.step(now=T + 60)
        self.ex.step(now=T + 90)
        self.assertEqual(self.row()["qty"], round_size(self.venue.orders[0]["size"] * 0.5, 4))

    def test_the_cloid_is_on_disk_before_the_order_leaves(self):
        def die(*a, **k):
            raise SystemExit("killed mid-call")
        self.venue.limit = die
        self.paper("ETH")
        with self.assertRaises(SystemExit):
            self.ex.step(now=T + 60)
        db = sqlite3.connect(self.state)
        self.assertEqual(db.execute("SELECT inflight FROM hlp_testnet").fetchone()[0], ht.cloid("ETH", T, "entry"))
        db.close()

    def test_entry_that_never_arrived_is_sent_again_while_fresh(self):
        self.venue.raise_next = 1
        self.paper("ETH")
        self.ex.step(now=T + 60)
        self.venue.status.clear()                  # the venue has no record of it
        self.ex.step(now=T + 90)
        self.assertEqual(len(self.venue.orders), 2)
        self.assertEqual(self.row()["status"], "open")

    def test_nothing_new_is_sent_while_a_lookup_fails(self):
        self.venue.raise_next = 1
        self.paper("ETH")
        self.ex.step(now=T + 60)
        self.venue.order_status = lambda c: (_ for _ in ()).throw(TimeoutError("down"))
        self.ex.step(now=T + 90)
        self.ex.step(now=T + 60 + HOLD_S)
        self.assertEqual(len(self.venue.orders), 1)
        self.assertIsNotNone(self.row()["inflight"])

    def test_exit_lost_to_a_timeout_is_found_and_not_resent(self):
        self.paper("ETH")
        self.ex.step(now=T + 60)
        self.venue.raise_next = 1
        self.ex.step(now=T + 60 + HOLD_S)
        self.assertEqual(self.row()["inflight_leg"], "exit")
        self.ex.step(now=T + 90 + HOLD_S)
        self.assertEqual(self.row()["status"], "closed")
        self.assertEqual(len(self.venue.orders), 2)


class TestKillSwitch(Base):
    def test_stop_file_sells_open_trades_now_and_skips_new_signals(self):
        self.paper("ETH")
        self.ex.step(now=T + 60)
        self.ex.stop_file.touch()
        self.paper("BTC", ts=T + 900)
        self.ex.step(now=T + 960)
        self.assertEqual(self.row()["status"], "closed")
        self.assertEqual(self.row("BTC", T + 900)["status"], "stopped")
        self.assertEqual([o["side"] for o in self.venue.orders], ["buy", "sell"])
        self.assertTrue(any("kill switch" in line for line in self.lines))

    def test_stop_file_is_named_after_the_journal(self):
        self.assertEqual(self.ex.stop_file.name, "hlp2-testnet.stop")


class TestSummary(Base):
    def test_summary_reports_mechanics_and_says_it_is_not_a_result(self):
        self.paper("ETH")
        self.ex.step(now=T + 60)
        self.ex.step(now=T + 60 + HOLD_S)
        text = "\n".join(ht.summary(self.state))
        self.assertIn("closed 1", text)
        self.assertIn("60s after the signal", text)
        self.assertIn("not mainnet", text)

    def test_cloids_are_valid_and_distinct(self):
        ids = {ht.cloid("ETH", T, "entry"), ht.cloid("ETH", T, "exit", 0), ht.cloid("ETH", T, "exit", 1),
               ht.cloid("BTC", T, "entry")}
        self.assertEqual(len(ids), 4)
        for c in ids:
            self.assertRegex(c, r"^0x[0-9a-f]{32}$")


if __name__ == "__main__":
    unittest.main()
