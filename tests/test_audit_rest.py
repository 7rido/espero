"""Regression tests for the 2026-10-27 audit, sections B, D and E (A is in
test_forward_fixes, C in test_hl_exchange)."""
from __future__ import annotations

import importlib.util
import io
import logging
import math
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import numpy as np
import pandas as pd

from espero import backtest, broker, carry, data, fast, notify, runner
from espero import book as bk
from espero import degen as dg
from espero import factor_eval as fe
from espero.execution import PaperExchange
from espero.journal import Journal, Position

ROOT = Path(__file__).resolve().parents[1]


# ------------------------------------------------------------------ B: .env
class TestEnvParser(unittest.TestCase):
    def test_the_audit_cases(self):
        text = "\n".join([
            "export A=1",
            'B="two" # comment',
            "C=plain value # comment",
            'PEM="-----BEGIN EC PRIVATE KEY-----',
            "MHcCAQEEIabc=",
            '-----END EC PRIVATE KEY-----"',
            "RAW=-----BEGIN KEY-----",
            "AwEHoUQDQgAE=",
            "-----END KEY-----",
            "AwEHoUQDQgAE=",                 # a stray base64 line with padding
            "lower=1",
            "EMPTY=",
        ])
        v, w = broker.parse_env(text)
        self.assertEqual(v["A"], "1")
        self.assertEqual(v["B"], "two")
        self.assertEqual(v["C"], "plain value")
        self.assertEqual(v["PEM"].splitlines(), ["-----BEGIN EC PRIVATE KEY-----", "MHcCAQEEIabc=",
                                                  "-----END EC PRIVATE KEY-----"])
        self.assertEqual(v["RAW"].count("\n"), 2)
        self.assertEqual(v["EMPTY"], "")
        self.assertNotIn("AwEHoUQDQgAE", v)
        self.assertNotIn("lower", v)
        self.assertTrue(all("AwEH" not in x and "MHc" not in x for x in w))   # warnings never quote values

    def test_shell_variables_still_win(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / ".env"
            p.write_text("ESPERO_AUDIT_Y=file\n")
            with mock.patch.dict(os.environ, {"ESPERO_AUDIT_Y": "shell"}):
                broker.load_env(str(p))
                self.assertEqual(os.environ["ESPERO_AUDIT_Y"], "shell")


class TestWebhook(unittest.TestCase):
    def test_failure_log_never_contains_the_secret_path(self):
        url = "https://hooks.example.com/services/T00/B00/SECRETTOKEN"
        logging.disable(logging.NOTSET)                 # tests/__init__ silences logging
        self.addCleanup(logging.disable, logging.CRITICAL)
        with mock.patch.object(data, "http_get", side_effect=data.FetchError(f"{url}: HTTP 500")) as get, \
                self.assertLogs("espero.notify", logging.WARNING) as logs:
            self.assertFalse(notify.webhook("t", "m", url=url))
        self.assertNotIn("SECRETTOKEN", "\n".join(logs.output))
        self.assertIn("hooks.example.com", "\n".join(logs.output))
        self.assertEqual(get.call_args.kwargs["retries"], 1)        # never sent twice


class TestWebhookMalformedUrl(unittest.TestCase):
    def test_a_malformed_url_is_a_failed_notification_not_a_crash(self):
        """urllib raises ValueError before any request on a URL with no scheme; the daily run must not die on it."""
        logging.disable(logging.NOTSET)
        self.addCleanup(logging.disable, logging.CRITICAL)
        with self.assertLogs("espero.notify", logging.WARNING):
            self.assertFalse(notify.webhook("t", "m", url="hooks.example.com/no/scheme"))


class TestRunnerLock(unittest.TestCase):
    def test_a_held_lock_refuses_and_a_stale_one_is_taken(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "daily.lock"
            with runner.Lock(path):
                with self.assertRaises(RuntimeError):
                    runner.Lock(path).__enter__()
            path.write_text("999999")                                # a pid that is gone
            with runner.Lock(path):
                self.assertEqual(path.read_text(), str(os.getpid()))
            self.assertFalse(path.exists())


# ------------------------------------------------------------- D: statistics
class TestStatistics(unittest.TestCase):
    def test_newey_west_t_tames_overlap_on_a_null(self):
        rng = np.random.default_rng(1)
        h, n = 5, 600
        plain, nw = [], []
        for _ in range(200):
            ic = pd.Series(np.convolve(rng.normal(size=n + h), np.ones(h), "valid")[:n])
            s = fe.summarize(ic, lags=2 * (h - 1))
            plain.append(s.t)
            nw.append(s.t_nw)
        self.assertGreater(np.std(plain), 1.8)        # the plain t is about twice too wide
        self.assertLess(np.std(nw), 1.35)

    def test_newey_west_equals_plain_t_without_lags(self):
        x = pd.Series(np.random.default_rng(2).normal(0.1, 1, 300))
        s = fe.summarize(x, lags=0)
        # zero lags is the plain t with the population variance in place of the sample one
        self.assertAlmostEqual(s.t_nw, s.t * math.sqrt(len(x) / (len(x) - 1)), places=6)

    def test_carry_daily_sharpe_reported_beside_the_hourly_criterion(self):
        idx = pd.date_range("2025-01-01", periods=24 * 60, freq="h", tz="UTC")
        rng = np.random.default_rng(3)
        noise = np.where(np.arange(len(idx)) % 2, 1, -1) * 0.002 * rng.random(len(idx))
        eq = pd.Series(1.0 + 0.0001 * np.arange(len(idx)) + noise, index=idx)
        hourly = carry.sharpe_of(eq, carry.HOURS_PER_YEAR)
        self.assertGreater(carry.daily_sharpe(eq), 3 * hourly)   # mean-reverting marks
        res = carry.Result(equity=eq, trades=[], funding_received=1.0, funding_paid=0.0,
                           fees=0.0, hours_in_position=0)
        m = carry.metrics(res)
        self.assertAlmostEqual(m["sharpe"], hourly)
        self.assertIn("sharpe_daily", m)

    def test_backtest_annualises_by_bar_spacing(self):
        self.assertEqual(backtest.bars_per_day(pd.date_range("2025", periods=10, freq="D")), 1.0)
        self.assertEqual(backtest.bars_per_day(pd.date_range("2025", periods=10, freq="h")), 24.0)
        self.assertEqual(backtest.bars_per_day([1, 2]), 1.0)

    def test_lp_sim_trading_pnl_is_not_reduced_by_rewards(self):
        spec = importlib.util.spec_from_file_location("lp_sim", ROOT / "research" / "lp_sim.py")
        lp = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(lp)
        idx = pd.date_range("2026-01-01", periods=200, freq="h", tz="UTC")
        prices = pd.Series(0.5 + 0.03 * np.sin(np.arange(200) / 3), index=idx)
        r = lp.simulate(prices, bankroll=500.0, spread=0.01, reward_per_day=100.0, liquidity=1e4, days=30)
        self.assertAlmostEqual(r["net"], r["equity"] - 500.0)
        self.assertGreater(r["rewards"], 0)


# ---------------------------------------------------------- E: execution
def snap(ts, bid=100.0, ask=100.2, trades=()):
    s = bk.BookSnapshot(ts, "X-USD", bids=[(bid, 1.0)], asks=[(ask, 1.0)])
    s.trades = [bk.Trade(i, ts, side, px, size) for i, (side, px, size) in enumerate(trades)]
    return s


class TestPaperExchange(unittest.TestCase):
    def test_one_print_fills_our_orders_once_best_price_first(self):
        ex = PaperExchange(cash=1000.0)
        s0 = bk.BookSnapshot(0, "X-USD", bids=[(99.0, 0.0)], asks=[(101.0, 1.0)])
        hi = ex.place_post_only(s0, "buy", 100.0, 1.0)
        lo = ex.place_post_only(s0, "buy", 99.5, 1.0)
        hi.queue_ahead = lo.queue_ahead = 0.0
        fills = ex.on_snapshot(snap(1, trades=[("sell", 99.0, 1.0)]))
        self.assertEqual([(f.order_id, f.size) for f in fills], [(hi.id, 1.0)])
        self.assertEqual(ex.inventory, 1.0)

    def test_the_same_snapshot_twice_fills_nothing_more(self):
        ex = PaperExchange(cash=1000.0)
        o = ex.place_post_only(snap(0), "buy", 100.0, 2.0)
        o.queue_ahead = 0.0
        s1 = snap(1, trades=[("sell", 100.0, 1.0)])
        ex.on_snapshot(s1)
        ex.on_snapshot(s1)                                           # a feed retry
        self.assertEqual(o.filled, 1.0)

    def test_resting_orders_and_fees_count_against_cash_and_inventory(self):
        ex = PaperExchange(cash=150.0, maker_fee=0.006)
        self.assertEqual(ex.place_post_only(snap(0), "buy", 100.0, 1.0).status, "resting")
        self.assertEqual(ex.place_post_only(snap(0), "buy", 100.0, 1.0).status, "rejected")
        ex.inventory = 1.0
        self.assertEqual(ex.place_post_only(snap(0), "sell", 100.2, 1.0).status, "resting")
        self.assertEqual(ex.place_post_only(snap(0), "sell", 100.3, 0.5).status, "rejected")

    def test_equity_keeps_the_last_mid_on_a_one_sided_book(self):
        ex = PaperExchange(cash=0.0)
        ex.inventory = 1.0
        ex.on_snapshot(snap(1))
        one_sided = bk.BookSnapshot(2, "X-USD", bids=[(100.0, 1.0)], asks=[])
        ex.on_snapshot(one_sided)
        self.assertAlmostEqual(ex.equity(), 100.1)


class TestFastScreen(unittest.TestCase):
    def fb(self, d, **kw):
        return fast.FastBook("X-USD", PaperExchange(cash=1000.0), venue="binanceus",
                             journal_path=Path(d) / "f.db", **kw)

    def test_a_failed_candle_fetch_clears_the_signal(self):
        sig = fast.CandleSignal("X-USD", fetch=mock.Mock(side_effect=OSError("down")))
        sig.state.value, sig.state.updated = 0.01, 1.0
        st = sig.update(now=1e9)
        self.assertIsNone(st.value)
        self.assertIn("down", st.error)

    def test_decline_holds_until_the_signal_updates(self):
        with tempfile.TemporaryDirectory() as d:
            fb = self.fb(d, threshold=0.003, check_feed_age=False)
            st = fast.SignalState(value=0.01, beta=1.0, updated=100.0)
            fb.on_snapshot(snap(1), st)
            self.assertIsNotNone(fb.proposal)
            fb.decline()
            fb.on_snapshot(snap(2), st)
            self.assertIsNone(fb.proposal)                            # same signal: stays declined
            fb.on_snapshot(snap(3), fast.SignalState(value=0.01, beta=1.0, updated=160.0))
            self.assertIsNotNone(fb.proposal)                         # a new signal may propose

    def test_stale_book_and_inventory_limit_refuse_enter(self):
        import time as _t
        with tempfile.TemporaryDirectory() as d:
            fb = self.fb(d, threshold=0.003)
            st = fast.SignalState(value=0.01, beta=1.0, updated=100.0)
            fb.on_snapshot(snap(_t.time() - 60), st)
            self.assertEqual(fb.accept(), "stale feed")
            fb2 = self.fb(d, threshold=0.003, order_notional=50.0)
            fb2.limits.max_inventory_notional = 20.0
            fb2.on_snapshot(snap(_t.time()), st)
            self.assertEqual(fb2.accept(), "inventory limit")

    def test_flat_leader_is_no_signal_not_nan(self):
        n = 300
        lead = pd.Series(np.full(n, 100.0))
        coin = pd.Series(100 + np.random.default_rng(0).normal(0, 1, n))
        st = fast.compute_signal(coin, lead, window=168)
        self.assertIsNone(st.value)


# ---------------------------------------------------------- E: books and data
class TestDayPnlUsesBarTime(unittest.TestCase):
    def test_degen_replay_sees_the_days_losses(self):
        with tempfile.TemporaryDirectory() as d:
            j = Journal(Path(d) / "d.db")
            t = dg.DegenTrader(j, dg.DegenConfig(initial=1000.0))
            day = 1_600_000_000 // 86400 * 86400
            j.mark_equity(day + 60, 1000.0, 0.0)
            self.assertAlmostEqual(t._day_pnl(950.0, day + 3600), -50.0)
            self.assertEqual(t._day_pnl(950.0, day + 86400 + 60), 0.0)   # the next day starts fresh
            j.close()


class TestDegenTrailAfterRestart(unittest.TestCase):
    def test_restart_does_not_count_the_fill_bars_high(self):
        with tempfile.TemporaryDirectory() as d:
            j = Journal(Path(d) / "d.db")
            j.open_position(Position("p", "AAA-USD", 1000, 1.0, 10.0, 0.98, 1.03))
            j.add_bar("AAA-USD", {"ts": 1000, "open": 1.0, "high": 1.05, "low": 1.0, "close": 1.0})
            j.add_bar("AAA-USD", {"ts": 1300, "open": 1.0, "high": 1.01, "low": 1.0, "close": 1.0})
            t = dg.DegenTrader(j, dg.DegenConfig())
            self.assertAlmostEqual(t.high_water["AAA-USD"], 1.01)
            j.close()


class TestCandleFetch(unittest.TestCase):
    def test_the_unfinished_candle_is_not_kept(self):
        now = 1_800_000_000 // 3600 * 3600 + 1200          # 20 minutes into an hour
        rows = [[now // 3600 * 3600 - 3600 * k, 1, 2, 1, 1.5, 10] for k in range(3, -1, -1)]
        with mock.patch.object(data, "fetch_page", return_value=rows), \
                mock.patch.object(data.time, "time", return_value=now), mock.patch.object(data.time, "sleep"):
            df = data.fetch("X-USD", 1, 3600)
        last = pd.Timestamp(df["time"].iloc[-1]).timestamp()
        self.assertLessEqual(last + 3600, now)
        self.assertEqual(len(df), 3)


class TestDashboard(unittest.TestCase):
    def test_names_are_escaped(self):
        from espero import dashboard
        self.assertEqual(dashboard.esc("<b>x</b>&'"), "&lt;b&gt;x&lt;/b&gt;&amp;&#x27;")


class TestCarryStatus(unittest.TestCase):
    def test_a_mistyped_path_is_refused_not_created(self):
        from espero import cli
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "typo.db"
            args = cli.build_parser().parse_args(["carry", "status", "--state", str(path)])
            with mock.patch("sys.stdout", io.StringIO()):
                self.assertEqual(cli._cmd_carry_status(args), 2)
            self.assertFalse(path.exists())


class TestUiDailyTime(unittest.TestCase):
    def test_reads_the_plist_and_falls_back(self):
        try:
            from espero import ui
        except ImportError:
            self.skipTest("tui extra not installed")
        import plistlib
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "x.plist"
            p.write_bytes(plistlib.dumps({"StartCalendarInterval": {"Hour": 6, "Minute": 5}}))
            self.assertEqual(ui.daily_time(p), "06:05")
            self.assertEqual(ui.daily_time(Path(d) / "missing.plist"), "07:30")


if __name__ == "__main__":
    unittest.main()
