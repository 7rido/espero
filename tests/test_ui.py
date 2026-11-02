"""The home screen renders from the databases alone and never writes to them."""
from __future__ import annotations

import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import pandas as pd

from espero import tsmom, xs

try:
    from rich.console import Console

    from espero import ui
    HAVE_TUI = ui.questionary is not None
except ImportError:  # the tui extra is optional
    HAVE_TUI = False


@unittest.skipUnless(HAVE_TUI, "tui extra not installed")
class TestRender(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.state = Path(self.tmp.name)
        acc = tsmom.Account(self.state / "tsmom.db")
        acc.cash = 100.0
        px = pd.Series({"SPY": 10.0})
        acc.rebalance(px, {"SPY": 1 / 6})
        acc.save(1_700_000_000, acc.equity(px), {"SPY": 1 / 6}, "init", positions={"SPY": 16.6},
                 deposit=100.0, traded=16.6)
        x = xs.XSAccount(self.state / "xs.db")
        x.cash = 100.0
        x.rebalance(pd.Series({"A": 1.0, "B": 2.0}), {"A": 0.5, "B": 0.5})
        x.save(1_700_000_000, 99.9, {"A": 0.5, "B": 0.5}, {}, {"A": 49.95, "B": 49.95}, 100.0, "init")
        (self.state / "health.json").write_text(json.dumps({
            "last_run": "2026-10-27T09:45:38+00:00", "last_success": "2026-10-27T09:45:38+00:00",
            "ok": False, "steps": {"tsmom": {"ok": True, "seconds": 1.0, "note": "init"},
                                   "xs": {"ok": False, "seconds": 0.1, "error": "RuntimeError: x"}}}))

    def tearDown(self):
        self.tmp.cleanup()

    def render(self, *renderables) -> str:
        buf = io.StringIO()
        c = Console(file=buf, width=120, force_terminal=False)
        for r in renderables:
            c.print(r)
        return buf.getvalue()

    def test_header_shows_total_and_failing_step(self):
        out = self.render(ui.header(self.state))
        self.assertIn("$199.88", out.replace("\n", ""))
        self.assertIn("FAILED", out)
        self.assertIn("failing: xs", out)

    def test_mf_account_is_listed_and_counted(self):
        from espero import mf
        acc = mf.MFAccount(self.state / "mf.db", cash=100.0)
        acc.save(1_700_000_000, 100.0, {}, {}, 100.0, "init", {}, 0.0)
        acc.close()
        out = self.render(ui.header(self.state), ui.accounts_table(self.state)).replace("\n", " ")
        self.assertIn("#8     multifactor fwd", out)
        self.assertIn("cash until its first fill 2026-11-02", out)
        self.assertIn("$299.88", out)                      # 199.88 + 100

    def test_paused_is_loud(self):
        (self.state / "KILL").write_text("")
        self.assertIn("PAUSED", self.render(ui.header(self.state)))

    def test_accounts_and_history_tables(self):
        out = self.render(ui.accounts_table(self.state), ui.history_table(self.state, "tsmom"),
                          ui.history_table(self.state, "xs"))
        self.assertIn("SPY", out)
        self.assertIn("2023-11-14", out)      # 1_700_000_000 as a date, not an epoch
        self.assertIn("init", out)

    def test_forward_tests_table_reads_the_daily_notes(self):
        h = json.loads((self.state / "health.json").read_text())
        h["steps"]["postclose"] = {"ok": True, "seconds": 0.2, "note": "mark: 3 trading days"}
        h["steps"]["liqbreak"] = {"ok": False, "seconds": 0.1, "error": "RuntimeError: aggr down"}
        (self.state / "health.json").write_text(json.dumps(h))
        buf = io.StringIO()
        Console(file=buf, width=200, force_terminal=False).print(ui.forward_table(self.state))
        out = buf.getvalue()
        for text in ("#22 #23", "#24", "#27", "#29", "#31", "#32", "#34", "#38", "#45", "mark: 3 trading days",
                     "aggr down", "not run yet"):
            self.assertIn(text, out)
        label = next(lbl for lbl, fn in ui.MENU if fn is ui.act_forward)
        for tests, _, _ in ui.FORWARD:                  # the menu names every forward test the table lists
            for t in tests.split():
                self.assertIn(t, label)

    def test_findings_reads_number_and_verdict_newest_first(self):
        folder = self.state / "research"
        folder.mkdir()
        (folder / "RESULTS_A.md").write_text("# Result — a (#9)\n\n**Verdict: FAIL.** more\n")
        (folder / "RESULTS_B.md").write_text("# Result — b (#9b)\n\n**Verdict: PASS.**\n")
        (folder / "RESULTS_C.md").write_text("# Results — c (#12)\n\nintro\n\n## Verdict: FAIL on criterion 1\n"
                                             "**What it means.**\n")
        (folder / "RESULTS_D.md").write_text("# Result — d\n\n**Not evidence.**\n")
        rows = ui.findings(folder)
        self.assertEqual([r["test"] for r in rows], ["#12", "#9b", "#9", ""])
        self.assertEqual([r["verdict"] for r in rows],
                         ["FAIL on criterion 1", "PASS", "FAIL", "Not evidence"])
        (folder / "RESULTS_E.md").write_text("# Results — e (#20–#30)\n\n**Five things.** more\n")
        (folder / "RESULTS_F.md").write_text("# Results — f (#25)\n\n**One thing.** more\n")
        ranged = ui.findings(folder)                    # a range sorts by its last number
        self.assertEqual([r["test"] for r in ranged], ["#20–#30", "#25", "#12", "#9b", "#9", ""])
        real = ui.findings()                            # the repo's own files all parse
        self.assertTrue(real and all(r["verdict"] for r in real))
        self.assertIn("#44", [r["test"] for r in real])
        self.assertEqual([r["test"] for r in real][:3], ["#57", "#52–#56", "#51"])

    def test_readout_is_on_the_menu_and_opens_the_real_file(self):
        self.assertIn(ui.act_readout, [fn for _, fn in ui.MENU])
        with mock.patch.object(ui, "_page") as page:
            ui.act_readout(Console(file=io.StringIO(), width=120), self.state)
        self.assertEqual(page.call_args[0][1].name, "OPERATOR_READOUT.md")
        self.assertTrue(page.call_args[0][1].exists())

    def test_costs_table_lists_measured_round_trips(self):
        buf = io.StringIO()
        Console(file=buf, width=200, force_terminal=False).print(ui.costs_table())
        out = buf.getvalue()
        self.assertIn("hyperliquid", out)
        self.assertIn("BTC 9.9", out)
        self.assertIn(ui.act_findings, [fn for _, fn in ui.MENU])

    def test_status_action_does_not_write(self):
        # compare contents, not bytes: SQLite folds a WAL file into the main file
        # whenever the last connection closes, which changes bytes but no data
        def dump(name):
            import sqlite3
            con = sqlite3.connect(f"file:{self.state / name}?mode=ro", uri=True)
            try:
                return list(con.iterdump())
            finally:
                con.close()
        before = dump("tsmom.db"), dump("xs.db")
        c = Console(file=io.StringIO(), width=120)
        ui.act_status(c, self.state)
        ui.act_logs(c, self.state)
        self.assertEqual(before, (dump("tsmom.db"), dump("xs.db")))

    def test_sparkline_and_pnl_curve(self):
        self.assertEqual(ui.sparkline([]), "")
        self.assertEqual(ui.sparkline([5, 5, 5]), "▄▄▄")
        bars = ui.sparkline([0, 1, 2, 3])
        self.assertEqual(len(bars), 4)
        self.assertLess(bars[0], bars[-1])
        rows = [{"ts": 1, "id": 1, "equity": 100.0, "deposit": 100.0},
                {"ts": 2, "id": 2, "equity": 101.0, "deposit": 0.0},
                {"ts": 3, "id": 3, "equity": 601.0, "deposit": 500.0}]
        self.assertEqual(ui.pnl_curve(rows), [0.0, 1.0, 1.0])   # a deposit is not profit

    def test_next_rebalance_follows_each_calendar(self):
        from datetime import datetime, timezone
        now = datetime(2026, 10, 27, 12, tzinfo=timezone.utc)          # Tuesday
        nxt = ui.next_rebalance(self.state, now)
        self.assertIn("Nov 2", nxt["xs"])                               # next Monday
        self.assertIn("in 6 d", nxt["xs"])
        self.assertIn("Nov 2", nxt["tsmom"])                            # first weekday of November
        # once November's rebalance is done, the next one is December
        from espero import tsmom
        acc = tsmom.Account(self.state / "tsmom.db")
        acc.save(int(datetime(2026, 11, 2, 12, tzinfo=timezone.utc).timestamp()), 100.0, {}, "rebalance")
        nxt = ui.next_rebalance(self.state, datetime(2026, 11, 3, 12, tzinfo=timezone.utc))
        self.assertIn("Dec 1", nxt["tsmom"])

    def test_decision_table_reads_the_stored_row(self):
        out = self.render(ui.decision_table(self.state, "tsmom"))
        self.assertIn("SPY", out)
        self.assertIn("hold", out)
        self.assertIn("costs", out)
        out = self.render(ui.decision_table(self.state, "xs"))
        self.assertIn("A", out)
        with tempfile.TemporaryDirectory() as d:
            self.assertIn("no decision stored", self.render(ui.decision_table(Path(d), "xs")))

    def test_empty_state_renders(self):
        with tempfile.TemporaryDirectory() as d:
            out = self.render(ui.header(Path(d)), ui.accounts_table(Path(d)))
        self.assertIn("not started", out)
        self.assertIn("no run recorded", out)


if __name__ == "__main__":
    unittest.main(verbosity=2)


class TestStateDir(unittest.TestCase):
    """Started from the wrong folder, the screens showed $0.00 as if the accounts were gone."""

    def setUp(self):
        import os
        import tempfile
        self.tmp = tempfile.TemporaryDirectory()
        self.old = os.getcwd()
        os.chdir(self.tmp.name)

    def tearDown(self):
        import os
        os.chdir(self.old)
        self.tmp.cleanup()

    def project(self):
        """A stand-in project folder, so the rungs below don't depend on this checkout's state."""
        import tempfile
        from unittest import mock

        from espero import cli
        d = Path(tempfile.mkdtemp(dir=self.tmp.name))
        (d / "pyproject.toml").write_text("")
        return mock.patch.object(cli, "PROJECT_DIR", d), d

    def test_an_empty_folder_falls_back_to_the_project_state_folder(self):
        from espero import cli
        patch, d = self.project()
        with patch:
            self.assertEqual(cli.state_dir(env={}), d / "state")

    def test_a_folder_with_accounts_is_used(self):
        from espero import cli
        Path(self.tmp.name, "xs.db").write_text("")
        self.assertEqual(cli.state_dir(env={}), Path("."))

    def test_the_project_state_folder_wins_over_the_project_root(self):
        from espero import cli
        patch, d = self.project()
        (d / "tsmom.db").write_text("")
        with patch:
            self.assertEqual(cli.state_dir(env={}), d)       # before the move: the root holds the books
            (d / "state").mkdir()
            (d / "state" / "tsmom.db").write_text("")
            self.assertEqual(cli.state_dir(env={}), d / "state")

    def test_the_environment_wins_over_folders(self):
        from espero import cli
        Path(self.tmp.name, "xs.db").write_text("")
        self.assertEqual(cli.state_dir(env={"ESPERO_STATE_DIR": "/elsewhere"}), Path("/elsewhere"))

    def test_an_explicit_folder_wins(self):
        from espero import cli
        self.assertEqual(cli.state_dir("/somewhere", env={"ESPERO_STATE_DIR": "/elsewhere"}), Path("/somewhere"))

    def test_bare_names_land_in_the_state_folder_and_paths_stay(self):
        import argparse

        from espero import cli
        env = {"ESPERO_STATE_DIR": "/st"}
        self.assertEqual(cli.state_path("tsmom.db", env=env), Path("/st/tsmom.db"))
        self.assertEqual(cli.state_path("books/p.db", env=env), Path("books/p.db"))
        self.assertEqual(cli.state_path("/abs/p.db", env=env), Path("/abs/p.db"))
        args = argparse.Namespace(state="xs.db", state_dir=".", tsmom_db="/abs/t.db", out="dashboard.html",
                                  cmd="x")
        cli.place_state(args, env=env)
        self.assertEqual((args.state, str(args.state_dir), args.tsmom_db, args.out),
                         ("/st/xs.db", "/st", "/abs/t.db", "/st/dashboard.html"))
