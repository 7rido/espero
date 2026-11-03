"""The daily runner: isolated steps, a lock, a pause switch, and a health file
that tells the truth."""
from __future__ import annotations

import json
import os
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

from espero import board as brd
from espero import runner


class RunnerCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.state = Path(self.tmp.name) / "state"
        self.logs = Path(self.tmp.name) / "logs"
        # the #8 account fetches 42 coins; a test that wants it to fail patches it again
        mf = mock.patch.object(runner.mfm, "run", return_value={"note": "mark", "equity": 100.0})
        self.mf_run = mf.start()
        self.addCleanup(mf.stop)
        # #22 records aggr's bars over the network
        lf = mock.patch.object(runner.lfm, "run", return_value={"note": "mark", "equity": None})
        self.lf_run = lf.start()
        self.addCleanup(lf.stop)
        lw = mock.patch.object(runner.lwf, "run", return_value={"note": "mark", "equity": None})
        lw.start()
        self.addCleanup(lw.stop)
        lb = mock.patch.object(runner.lbk, "run", return_value={"note": "mark", "equity": None})
        lb.start()
        self.addCleanup(lb.stop)
        # #29 reads the repo's recorded files: not in tests
        pc = mock.patch.object(runner.pcl, "run", return_value={"note": "mark: 3 trading days", "equity": None})
        self.pc_run = pc.start()
        self.addCleanup(pc.stop)
        fsp = mock.patch.object(runner.fsp, "run", return_value={"note": "mark: no breaks yet", "equity": None})
        self.fsp_run = fsp.start()
        self.addCleanup(fsp.stop)
        lpu = mock.patch.object(runner.lpu, "run", return_value={"note": "mark: 0 trading days", "equity": None})
        self.lpu_run = lpu.start()
        self.addCleanup(lpu.stop)
        sfw = mock.patch.object(runner.sfw, "run", return_value={"note": "mark: 0", "equity": None})
        self.sfw_run = sfw.start()
        self.addCleanup(sfw.stop)
        lhd = mock.patch.object(runner.lhd, "run", return_value={"note": "mark: 0", "equity": None})
        self.lhd_run = lhd.start()
        self.addCleanup(lhd.stop)
        bf = mock.patch.object(runner.bfw, "run", return_value={"note": "mark: 0 fills", "equity": None})
        self.bf_run = bf.start()
        self.addCleanup(bf.stop)
        # the Monday publish shells out to gh: never from a test, whatever .env says
        pub = mock.patch.object(runner, "publish_data", return_value={"note": "off"})
        self.pub_run = pub.start()
        self.addCleanup(pub.stop)
        # the dashboard's signal board fetches 55 Yahoo series: no network in tests
        board = mock.patch.object(brd, "fetch_frames", return_value=({}, {}))
        board.start()
        self.addCleanup(board.stop)
        # run_daily loads the checkout's .env: a test never reads the operator's real configuration
        env = mock.patch("espero.broker.load_env")
        env.start()
        self.addCleanup(env.stop)

    def tearDown(self):
        self.tmp.cleanup()

    def run_daily(self, **kw):
        kw.setdefault("notify", False)
        kw.setdefault("log_dir", self.logs)
        return runner.run_daily(state_dir=self.state, **kw)


class TestDryRun(RunnerCase):
    def test_dry_run_touches_no_network_and_writes_health(self):
        with mock.patch.object(runner.tsm, "run", side_effect=AssertionError("network")), \
             mock.patch.object(runner.xsm, "run", side_effect=AssertionError("network")):
            res = self.run_daily(dry_run=True)
        self.assertTrue(res.ok)
        self.assertEqual(res.exit_code, 0)
        self.assertTrue(res.steps["tsmom"].skipped)
        self.assertTrue(res.steps["mf"].skipped)
        self.assertTrue(res.steps["liqfwd"].skipped)
        self.assertTrue(res.steps["lowsfwd"].skipped)
        self.assertTrue(res.steps["postclose"].skipped)
        self.pc_run.assert_not_called()
        self.assertTrue(res.steps["bidsfwd"].skipped)
        self.assertTrue(res.steps["fundsplit"].skipped)
        self.assertTrue(res.steps["levpush"].skipped)
        self.assertTrue(res.steps["settlefwd"].skipped)
        self.assertTrue(res.steps["liqhold"].skipped)
        self.lhd_run.assert_not_called()
        self.fsp_run.assert_not_called()
        self.bf_run.assert_not_called()
        self.mf_run.assert_not_called()
        self.lf_run.assert_not_called()
        health = json.loads((self.state / "health.json").read_text())
        self.assertTrue(health["ok"])
        self.assertTrue(health["dry_run"])
        # a dry run skips the real steps, so it is not a success of the real job
        self.assertIsNone(health["last_success"])
        self.assertTrue((self.state / "dashboard.html").exists())
        self.assertTrue((self.logs / "daily.log").exists())


class TestIsolation(RunnerCase):
    def test_one_failing_step_does_not_stop_the_others(self):
        with mock.patch.object(runner.tsm, "run", side_effect=RuntimeError("yahoo down")), \
             mock.patch.object(runner.xsm, "run", return_value={"note": "mark", "equity": 101.0}):
            res = self.run_daily()
        self.assertFalse(res.ok)
        self.assertEqual(res.exit_code, 1)
        self.assertFalse(res.steps["tsmom"].ok)
        self.assertIn("yahoo down", res.steps["tsmom"].error)
        self.assertTrue(res.steps["xs"].ok)
        self.assertTrue(res.steps["mf"].ok)
        self.assertTrue(res.steps["dashboard"].ok)
        health = json.loads((self.state / "health.json").read_text())
        self.assertFalse(health["ok"])
        self.assertIsNone(health["last_success"])

    def test_last_success_survives_a_later_failure(self):
        with mock.patch.object(runner.tsm, "run", return_value={"note": "mark", "equity": 1.0}), \
             mock.patch.object(runner.xsm, "run", return_value={"note": "mark", "equity": 1.0}):
            self.run_daily()
        first = json.loads((self.state / "health.json").read_text())["last_success"]
        with mock.patch.object(runner.tsm, "run", side_effect=RuntimeError("x")), \
             mock.patch.object(runner.xsm, "run", return_value={"note": "mark", "equity": 1.0}):
            self.run_daily()
        health = json.loads((self.state / "health.json").read_text())
        self.assertEqual(health["last_success"], first)
        self.assertFalse(health["ok"])

    def test_rebalance_sends_a_notification_and_failure_too(self):
        sent = []
        with mock.patch.object(runner.notifier, "notify", side_effect=lambda t, m: sent.append(t)), \
             mock.patch.object(runner.tsm, "run", return_value={"note": "rebalance", "equity": 1.0}), \
             mock.patch.object(runner.xsm, "run", side_effect=RuntimeError("x")):
            self.run_daily(notify=True)
        self.assertTrue(any("rebalance" in t for t in sent))
        self.assertTrue(any("failed" in t for t in sent))

    def test_a_notification_that_raises_on_a_trade_note_does_not_fail_the_run(self):
        """The trade note is sent outside the step's own try: a webhook that raises must still leave the step ok."""
        with mock.patch.object(runner.notifier, "notify", side_effect=ValueError("unknown url type")), \
             mock.patch.object(runner.tsm, "run", return_value={"note": "rebalance", "equity": 1.0}):
            res = self.run_daily(notify=True)
        self.assertTrue(res.steps["tsmom"].ok)
        self.assertTrue(res.ok)
        self.assertTrue((self.state / "health.json").exists())

    def test_mf_runs_twice_once_on_hyperliquid_prices(self):
        from espero import hyperliquid as hl
        with mock.patch.object(runner.tsm, "run", return_value={"note": "mark", "equity": 1.0}), \
             mock.patch.object(runner.xsm, "run", return_value={"note": "mark", "equity": 1.0}):
            res = self.run_daily()
        self.assertTrue(res.steps["mf-hl"].ok)
        calls = self.mf_run.call_args_list
        self.assertEqual([Path(c.args[0]).name for c in calls], ["mf.db", "mf-hl.db"])
        self.assertIsNone(calls[0].kwargs.get("fetch"))           # #8 itself stays on Yahoo
        self.assertIs(calls[1].kwargs["fetch"], hl.daily)

    def test_postclose_runs_after_the_files_are_recorded(self):
        order = []
        runner.lwf.run.side_effect = lambda *a, **k: order.append("lowsfwd") or {"note": "mark", "equity": None}
        self.pc_run.side_effect = lambda *a, **k: order.append("postclose") or {"note": "mark", "equity": None}
        self.bf_run.side_effect = lambda *a, **k: order.append("bidsfwd") or {"note": "mark", "equity": None}
        self.lpu_run.side_effect = lambda *a, **k: order.append("levpush") or {"note": "mark", "equity": None}
        with mock.patch.object(runner.tsm, "run", return_value={"note": "mark", "equity": 1.0}), \
             mock.patch.object(runner.xsm, "run", return_value={"note": "mark", "equity": 1.0}):
            res = self.run_daily()
        self.assertTrue(res.steps["postclose"].ok)
        self.assertTrue(res.steps["bidsfwd"].ok)
        self.assertEqual(order, ["lowsfwd", "postclose", "levpush", "bidsfwd"])
        self.assertEqual(Path(self.pc_run.call_args.args[0]), self.state)

    def test_trade_note_without_equity_does_not_crash_the_run(self):
        sent = []
        with mock.patch.object(runner.notifier, "notify", side_effect=lambda t, m: sent.append((t, m))), \
             mock.patch.object(runner.tsm, "run", return_value={"note": "rebalance", "equity": None}), \
             mock.patch.object(runner.xsm, "run", return_value={"note": "init", "equity": 5.0,
                                                                "message": "bought 3 coins"}):
            res = self.run_daily(notify=True)
        self.assertTrue(res.ok)
        self.assertIn(("espero tsmom: rebalance", "rebalance"), sent)
        self.assertIn(("espero xs: init", "bought 3 coins"), sent)


class TestGuards(RunnerCase):
    def test_kill_file_pauses_everything(self):
        self.state.mkdir(parents=True)
        (self.state / "KILL").write_text("")
        with mock.patch.object(runner.tsm, "run", side_effect=AssertionError("must not run")):
            res = self.run_daily()
        self.assertTrue(res.paused)
        self.assertEqual(res.exit_code, 0)
        self.assertEqual(res.steps, {})

    def test_live_lock_aborts_and_stale_lock_is_removed(self):
        self.state.mkdir(parents=True)
        lock = self.state / "daily.lock"
        lock.write_text(str(os.getpid()))         # this very process: alive
        with self.assertRaises(RuntimeError):
            self.run_daily(dry_run=True)
        lock.write_text("999999999")               # nobody: stale
        res = self.run_daily(dry_run=True)
        self.assertTrue(res.ok)
        self.assertFalse(lock.exists())


if __name__ == "__main__":
    unittest.main(verbosity=2)


class TestPublishData(unittest.TestCase):
    """The Monday release: off unless the maintainer opts in, never on other days, and the
    token goes to the script alone."""
    MONDAY = datetime(2026, 11, 2, 11, 30, tzinfo=timezone.utc)

    def fake_run(self):
        calls = []

        def run(cmd, **kw):
            calls.append((cmd, kw))
            out = "tok-123" if cmd[1:3] == ["auth", "token"] else "x\npublished: https://example/data-2026-11-02"
            return mock.Mock(stdout=out)
        return calls, run

    def test_off_without_the_opt_in(self):
        calls, run = self.fake_run()
        out = runner.publish_data(self.MONDAY, env={"PATH": "/usr/bin"}, run=run)
        self.assertIn("off", out["note"])
        self.assertEqual(calls, [])

    def test_only_on_mondays(self):
        calls, run = self.fake_run()
        tuesday = self.MONDAY + timedelta(days=1)
        out = runner.publish_data(tuesday, env={"ESPERO_PUBLISH_AS": "7rido"}, run=run)
        self.assertEqual(out["note"], "not Monday")
        self.assertEqual(calls, [])

    def test_monday_passes_that_accounts_token_to_the_script_only(self):
        calls, run = self.fake_run()
        out = runner.publish_data(self.MONDAY, env={"ESPERO_PUBLISH_AS": "7rido", "PATH": "/usr/bin"}, run=run)
        (token_cmd, _), (script_cmd, kw) = calls
        self.assertEqual(token_cmd[1:], ["auth", "token", "-u", "7rido"])
        self.assertEqual(script_cmd, [str(runner.PUBLISH_SCRIPT)])
        self.assertEqual(kw["env"]["GH_TOKEN"], "tok-123")
        self.assertNotIn("switch", " ".join(c for cmd, _ in calls for c in cmd))
        self.assertTrue(out["note"].startswith("published:"))



class TestPublishStep(RunnerCase):
    def test_runs_after_liqhold_and_lands_in_health(self):
        res = self.run_daily()
        self.pub_run.assert_called_once()
        names = list(res.steps)
        self.assertEqual(names.index("publish"), names.index("liqhold") + 1)
        health = json.loads((self.state / "health.json").read_text())
        self.assertIn("publish", health["steps"])
