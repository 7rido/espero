"""Attribution and the equity check, on made-up fills: #59's testnet journal has none yet, and no twin is read."""
import math
import sqlite3
import tempfile
import unittest
from pathlib import Path

from espero import attribution as A
from espero import hlp_testnet, risk

T0 = 1_793_577_600            # 2026-11-02 00:00 UTC


def fill(side=1, px=100.0, decision=100.0, qty=1.0, ts=T0, fee=0.045, trade="t1", sleeve="59", venue="hl",
         liquidity="taker"):
    return A.Fill(sleeve, venue, "BTC", ts, side, qty, px, fee, decision, trade, liquidity)


class TestSlippage(unittest.TestCase):
    def test_worse_than_the_decision_is_positive_both_ways(self):
        self.assertAlmostEqual(A.slippage_bps(fill(1, 100.10, 100.0)), 10.0)
        self.assertAlmostEqual(A.slippage_bps(fill(-1, 99.90, 100.0)), 10.0)
        self.assertAlmostEqual(A.slippage_bps(fill(-1, 100.10, 100.0)), -10.0)
        self.assertAlmostEqual(A.slippage_usd(fill(1, 100.10, 100.0, qty=2.0)), 0.20)


class TestDaily(unittest.TestCase):
    def test_rows_by_sleeve_venue_and_day(self):
        fills = [fill(1, 100.1, 100.0, ts=T0 + 60), fill(-1, 99.8, 100.0, ts=T0 + 3600, liquidity="maker"),
                 fill(1, 50.0, 50.0, ts=T0 + 86_400 + 5, trade="t2")]
        rows = A.daily(fills, [A.FundingPayment("59", "hl", "BTC", T0 + 7200, -0.03, "t1")])
        self.assertEqual([(r["day"], r["fills"]) for r in rows], [("2026-11-02", 2), ("2026-11-03", 1)])
        d = rows[0]
        self.assertAlmostEqual(d["notional"], 199.9)
        self.assertAlmostEqual(d["fees"], 0.09)
        self.assertAlmostEqual(d["funding"], -0.03)
        self.assertAlmostEqual(d["slippage_usd"], 0.1 + 0.2)
        self.assertAlmostEqual(d["slippage_bps"], 0.3 / 199.9 * 1e4)
        self.assertAlmostEqual(d["maker_share"], 99.8 / 199.9)


class TestTrades(unittest.TestCase):
    def test_a_round_trip_nets_its_cash_fees_and_funding(self):
        fills = [fill(1, 100.0, ts=T0), fill(-1, 110.0, ts=T0 + 3600, fee=0.05)]
        t = A.trades(fills, [A.FundingPayment("59", "hl", "BTC", T0 + 100, -0.5, "t1")])["t1"]
        self.assertEqual(t["closed"], T0 + 3600)
        self.assertAlmostEqual(t["gross"], 10.0)
        self.assertAlmostEqual(t["net"], 10.0 - 0.095 - 0.5)
        self.assertAlmostEqual(t["net_bps"], t["net"] / 100.0 * 1e4)
        self.assertNotIn("cash", t)

    def test_an_open_trade_has_no_gross_yet(self):
        t = A.trades([fill(1, 100.0)])["t1"]
        self.assertIsNone(t["closed"])
        self.assertTrue(math.isnan(t["gross"]))

    def test_the_twin_gap_is_for_closed_trades_the_twin_took(self):
        live = A.trades([fill(1, 100.0), fill(-1, 101.0, ts=T0 + 1, fee=0.0), fill(1, 100.0, trade="open")])
        gap = A.twin_gap(live, {"t1": 50.0, "open": 0.0, "other": 9.0})
        self.assertEqual(list(gap), ["t1"])
        self.assertAlmostEqual(gap["t1"], live["t1"]["net_bps"] - 50.0)


class TestEquity(unittest.TestCase):
    def test_a_dollar_or_a_tenth_of_a_percent(self):
        self.assertIsNone(A.reconcile_equity(1_000.5, 1_000.0))
        self.assertIsNone(A.reconcile_equity(100_090.0, 100_000.0))
        self.assertIn("equity break", A.reconcile_equity(100_200.0, 100_000.0))
        self.assertIn("+2.00", A.reconcile_equity(1_002.0, 1_000.0))

    def test_a_break_pauses_the_sleeve_and_the_gate_refuses_its_entries(self):
        with tempfile.TemporaryDirectory() as d:
            told = []
            self.assertIsNone(A.check_equity(Path(d), "59", 1_000.0, 1_000.4, tell=lambda *a: told.append(a)))
            self.assertFalse(A.paused(Path(d), "59"))
            why = A.check_equity(Path(d), "59", 1_000.0, 990.0, tell=lambda *a: told.append(a))
            self.assertIn("equity break", why)
            self.assertTrue(A.paused(Path(d), "59"))
            self.assertEqual(len(told), 1)
            acct = risk.Account(capital=1_000.0, equity=1_000.0, equity_by_venue={"hl": 1_000.0},
                                sleeve_scale={"59": 1.0}, paused=A.paused(Path(d), "59"))
            self.assertFalse(risk.check(risk.Order("59", "59", "hl", "BTC", 1, 100.0), acct).allowed)

    def test_the_pause_stands_when_the_message_fails(self):
        with tempfile.TemporaryDirectory() as d:
            def broken(*a):
                raise RuntimeError("webhook down")
            A.pause(Path(d), "59", "x", tell=broken)
            self.assertTrue(A.paused(Path(d), "59"))

    def test_the_venues_own_record_by_address(self):
        fake = lambda body: {"marginSummary": {"accountValue": "1234.5"}, "assetPositions": []}   # noqa: E731
        self.assertEqual(A.venue_equity_hl("0x" + "0" * 40, fetch=fake), 1234.5)


class TestTestnetJournal(unittest.TestCase):
    def test_entries_and_exits_become_fills_against_the_testnet_mid(self):
        with tempfile.TemporaryDirectory() as d:
            db = Path(d) / "hlp2-testnet.db"
            con = sqlite3.connect(db)
            con.executescript(hlp_testnet.SCHEMA)
            cols = "coin, signal_ts, status, entry_ts, entry_mid, entry_px, qty, entry_fee"
            con.execute(f"INSERT INTO hlp_testnet ({cols}, exit_ts, exit_mid, exit_px, exited, exit_fee) VALUES "
                        "('ETH', 100, 'closed', 160, 2000, 2001, 0.05, 0.045, 14560, 2010, 2009, 0.05, 0.045)")
            con.execute(f"INSERT INTO hlp_testnet ({cols}) VALUES ('SOL', 200, 'open', 260, 150, 150.3, 0.6, 0.04)")
            con.commit()
            con.close()
            fills = A.from_hlp_testnet(db)
            self.assertEqual([(f.coin, f.side) for f in fills], [("ETH", 1), ("ETH", -1), ("SOL", 1)])
            self.assertAlmostEqual(A.slippage_bps(fills[0]), 5.0)
            self.assertAlmostEqual(A.slippage_bps(fills[1]), (2010 - 2009) / 2010 * 1e4)
            t = A.trades(fills)
            self.assertIsNotNone(t["ETH-100"]["closed"])
            self.assertIsNone(t["SOL-200"]["closed"])

    def test_render(self):
        self.assertEqual(A.render([]), "no fills")
        self.assertIn("| 2026-11-02 | 59 | hl |", A.render(A.daily([fill()])))


if __name__ == "__main__":
    unittest.main()
