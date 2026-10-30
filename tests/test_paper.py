"""The paper trader must obey the same rules as the backtest, plus survive restarts."""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import espero.paper as paper_mod
from espero.journal import Journal
from espero.paper import PaperConfig, PaperTrader
from espero.signals import Signal

GRAN = 1000


def bar(i: int, open_px: float, close_px: float | None = None, high=None, low=None) -> dict:
    close_px = open_px if close_px is None else close_px
    return {
        "ts": 1_000_000 + i * GRAN,
        "open": open_px,
        "high": high if high is not None else max(open_px, close_px) * 1.001,
        "low": low if low is not None else min(open_px, close_px) * 0.999,
        "close": close_px,
        "volume": 1.0,
    }


class ScriptedSignal:
    """Emit one signal on the nth call of combine()."""

    def __init__(self, nth: int = 1, side: str = "BUY", confidence: float = 0.9):
        self.nth, self.calls, self.side, self.confidence = nth, 0, side, confidence

    def __call__(self, sigs):
        self.calls += 1
        if self.calls == self.nth:
            return Signal(self.side, self.confidence, "test")
        return None


class PaperTestCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = Path(self.tmp.name) / "paper.db"
        self.orig_combine = paper_mod.combine
        self.cfg = PaperConfig(granularity=GRAN, initial=500.0, fee=0.0,
                               slippage=0.0, warmup=1, stop_pct=0.10, target_pct=0.20)

    def tearDown(self):
        paper_mod.combine = self.orig_combine
        self.tmp.cleanup()

    def trader(self) -> PaperTrader:
        self.journal = Journal(self.db)
        return PaperTrader(self.journal, self.cfg)

    def prime(self, t: PaperTrader, price: float = 100.0) -> None:
        """Three bars: warmup satisfied, signal fires on the third close."""
        for i in range(3):
            t.on_bar(bar(i, price))


class TestPaperFills(PaperTestCase):
    def test_signal_under_the_backtest_floor_is_ignored(self):
        # combine() can return 0.60 (one Bollinger vote); the backtest needs 0.65.
        # The paper book must apply the same floor or it trades a different rule.
        t = self.trader()
        paper_mod.combine = ScriptedSignal(nth=1, confidence=0.60)
        self.prime(t)
        self.assertIsNone(t.pending)
        self.assertIsNone(t.position)

    def test_signal_queues_instead_of_filling(self):
        t = self.trader()
        paper_mod.combine = ScriptedSignal(nth=1)
        self.prime(t)
        self.assertIsNotNone(t.pending)
        self.assertIsNone(t.position, "a signal must not fill on its own bar")

    def test_fill_happens_on_the_next_bar(self):
        t = self.trader()
        paper_mod.combine = ScriptedSignal(nth=1)
        self.prime(t)
        queued_at = t.pending.created_ts

        t.on_bar(bar(3, 103.0))
        self.assertIsNone(t.pending)
        self.assertIsNotNone(t.position)
        self.assertEqual(t.position.entry_ts, bar(3, 0)["ts"])
        self.assertGreater(t.position.entry_ts, queued_at)
        self.assertAlmostEqual(t.position.entry_px, 103.0)

    def test_duplicate_bar_is_ignored(self):
        t = self.trader()
        self.assertEqual(t.on_bar(bar(0, 100)), [])
        self.assertEqual(t.on_bar(bar(0, 100)), ["duplicate bar ignored"])
        self.assertEqual(t.journal.db.execute("SELECT COUNT(*) FROM bars").fetchone()[0], 1)

    def test_stop_exits_at_the_stop_price(self):
        t = self.trader()
        paper_mod.combine = ScriptedSignal(nth=1)
        self.prime(t)
        t.on_bar(bar(3, 100.0))                    # fill at 100, stop 90
        events = t.on_bar(bar(4, 100.0, low=85.0))  # trades through the stop
        self.assertTrue(any("stop" in e for e in events), events)
        self.assertIsNone(t.position)

    def test_stale_order_is_cancelled_not_filled(self):
        t = self.trader()
        paper_mod.combine = ScriptedSignal(nth=1)
        self.prime(t)
        self.assertIsNotNone(t.pending)
        t.on_bar(bar(10, 150.0))  # the bot was down for ten bars
        self.assertIsNone(t.position, "a stale order must not fill at a new price")
        status = t.journal.db.execute("SELECT status FROM orders").fetchone()["status"]
        self.assertEqual(status, "stale")


class TestRestart(PaperTestCase):
    def _open_position(self) -> PaperTrader:
        t = self.trader()
        paper_mod.combine = ScriptedSignal(nth=1)
        self.prime(t)
        t.on_bar(bar(3, 100.0))
        self.assertIsNotNone(t.position)
        return t

    def test_position_survives_a_restart(self):
        t = self._open_position()
        position_id, cash = t.position.id, t.cash
        self.journal.close()

        self.journal = Journal(self.db)  # new process, same file
        t2 = PaperTrader(self.journal, self.cfg)
        self.assertIsNotNone(t2.position)
        self.assertEqual(t2.position.id, position_id)
        self.assertAlmostEqual(t2.cash, cash)

    def test_equity_survives_a_restart(self):
        t = self._open_position()
        expected = t._equity(100.0)
        curve_len = len(t.journal.equity_curve())
        self.journal.close()

        j2 = Journal(self.db)
        cash, equity = j2.latest_equity()
        self.assertAlmostEqual(equity, expected, places=6)
        self.assertEqual(len(j2.equity_curve()), curve_len)
        self.assertGreater(cash, 0)


class TestPerpFunding(PaperTestCase):
    """Funding is charged once per 8h settlement held through, persists, and
    lands in the realised P&L. Bar i has ts 1_000_000 + 1000*i, so the first
    settlement (35 * 28800 = 1_008_000) falls on bar 8."""

    def _long(self, funding=0.0001) -> PaperTrader:
        self.cfg.funding_8h = funding
        t = self.trader()
        paper_mod.combine = ScriptedSignal(nth=1)
        self.prime(t)
        t.on_bar(bar(3, 100.0))                     # long from bar 3
        self.assertIsNotNone(t.position)
        return t

    def test_charged_once_at_the_settlement(self):
        t = self._long()
        size, cash = t.position.size, t.cash
        paid = [e for i in range(4, 10) for e in t.on_bar(bar(i, 100.0)) if "funding" in e]
        self.assertEqual(len(paid), 1)
        self.assertAlmostEqual(cash - t.cash, size * 100.0 * 0.0001)

    def test_spot_pays_no_funding(self):
        t = self._long(funding=0.0)
        cash = t.cash
        for i in range(4, 10):
            t.on_bar(bar(i, 100.0))
        self.assertAlmostEqual(t.cash, cash)

    def test_funding_survives_a_restart_and_reaches_the_pnl(self):
        t = self._long()
        size = t.position.size
        for i in range(4, 10):
            t.on_bar(bar(i, 100.0))
        self.journal.close()
        t2 = self.trader()                          # new process, same file
        self.assertAlmostEqual(t2.position.entry_fee, size * 100.0 * 0.0001)
        t2.on_bar(bar(10, 100.0, low=85.0))         # stop out at 90
        pnl = t2.journal.closed_positions()[-1]["pnl"]
        self.assertAlmostEqual(pnl, (90.0 - 100.0) * size - size * 100.0 * 0.0001)


class TestActualFunding(PaperTestCase):
    """With the venue's published rates (Hyperliquid, hourly): each settlement after
    entry is charged at its own rate, a negative rate is received, and an unpublished
    one rolls the bar back. Settlements every 3600 s fall at 1_004_400 (bar 5),
    1_008_000 (bar 8) and 1_011_600 (bar 12)."""

    RATES = {1_000_800: 0.5, 1_004_400: 0.0001, 1_008_000: -0.0003, 1_011_600: 0.0002}

    def _long(self, rates) -> PaperTrader:
        self.asked = []

        def lookup(start, end):
            self.asked.append((start, end))
            return {t: r for t, r in rates.items() if start <= t <= end}
        self.cfg.funding_rates, self.cfg.funding_period = lookup, 3600
        t = self.trader()
        paper_mod.combine = ScriptedSignal(nth=1)
        self.prime(t)                               # bar 1 holds the 1_000_800 settlement: not held, not charged
        t.on_bar(bar(3, 100.0))
        self.assertIsNotNone(t.position)
        return t

    def test_each_settlement_at_its_own_rate(self):
        t = self._long(self.RATES)
        size, cash = t.position.size, t.cash
        events = [e for i in range(4, 9) for e in t.on_bar(bar(i, 100.0)) if "funding" in e]
        self.assertEqual(events, [f"funding paid {size * 100 * 0.0001:.4f}",
                                  f"funding received {size * 100 * 0.0003:.4f}"])
        self.assertAlmostEqual(cash - t.cash, size * 100.0 * (0.0001 - 0.0003))

    def test_no_charge_before_entry_or_without_a_settlement(self):
        t = self._long(self.RATES)
        cash = t.cash
        t.on_bar(bar(4, 100.0))                     # (1_003_000, 1_004_000]: no settlement
        self.assertAlmostEqual(t.cash, cash)
        self.assertEqual(self.asked, [])            # nothing to look up, nothing asked

    def test_unpublished_rate_rolls_the_bar_back(self):
        rates = {k: v for k, v in self.RATES.items() if k != 1_004_400}
        t = self._long(rates)
        t.on_bar(bar(4, 100.0))
        cash = t.cash
        with self.assertRaises(paper_mod.FundingNotPublished):
            t.on_bar(bar(5, 100.0))
        self.assertAlmostEqual(t.cash, cash)
        self.assertEqual(t.journal.last_bar_ts(self.cfg.product), bar(4, 100.0)["ts"])
        rates[1_004_400] = 0.0001                   # published now: the same bar goes through
        t.on_bar(bar(5, 100.0))
        self.assertLess(t.cash, cash)


class TestVenueCompare(unittest.TestCase):
    def test_same_trades_different_bill(self):
        orig = paper_mod.combine
        try:
            from espero.signals import Signal as S
            calls = {"n": 0}

            def alternate(_sigs):
                calls["n"] += 1
                if calls["n"] % 6 == 1:
                    return S("BUY", 0.9, "t")
                if calls["n"] % 6 == 4:
                    return S("SELL", 0.9, "t")
                return None
            paper_mod.combine = alternate
            bars = [bar(i, 100.0 + (i % 5)) for i in range(120)]
            # the daily cap now applies in replay too (bar time, not wall clock); lift
            # it here so both venues take the same trades and only the bill differs
            from espero.risk import RiskLimits
            rows = {r["venue"]: r for r in paper_mod.compare_venues(
                bars, ["coinbase", "perp"], granularity=GRAN,
                limits=RiskLimits(daily_loss_cap_pct=1.0))}
        finally:
            paper_mod.combine = orig
        self.assertGreater(rows["coinbase"]["trades"], 0)
        self.assertEqual(rows["coinbase"]["trades"], rows["perp"]["trades"])
        self.assertGreater(rows["coinbase"]["fees"], 10 * rows["perp"]["fees"])
        # entry and exit fees both count, so the bills scale with the taker rates
        from espero.venues import VENUES
        ratio = VENUES["coinbase"].taker_bps / VENUES["perp"].taker_bps
        self.assertAlmostEqual(rows["coinbase"]["fees"] / rows["perp"]["fees"], ratio, delta=0.05 * ratio)
        self.assertEqual(rows["coinbase"]["funding"], 0.0)
        self.assertGreater(rows["perp"]["pnl"], rows["coinbase"]["pnl"])

    def test_for_venue_reads_the_table(self):
        cfg = PaperConfig.for_venue("perp")
        self.assertAlmostEqual(cfg.fee, 0.0005)
        self.assertAlmostEqual(cfg.funding_8h, 0.0001)
        self.assertEqual(PaperConfig.for_venue("coinbase").funding_8h, 0.0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
