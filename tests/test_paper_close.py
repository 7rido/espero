"""Manual close (take profit early): queued for the running loop and filled at the
next open as "manual", or closed at once when no loop holds the journal."""
from __future__ import annotations

import contextlib
import importlib.util
import io
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import espero.paper as paper_mod
from espero import cli
from espero.journal import Journal
from espero.lock import JournalLock
from tests.test_paper import GRAN, PaperTestCase, ScriptedSignal, bar


class TestManualClose(PaperTestCase):
    def opened(self):
        t = self.trader()
        paper_mod.combine = ScriptedSignal(nth=1)
        self.prime(t)
        t.on_bar(bar(3, 100.0))                       # the BUY fills here
        self.assertIsNotNone(t.position)
        return t

    def test_queued_then_filled_at_the_next_open(self):
        t = self.opened()
        self.assertEqual(t.request_close(bar(3, 0)["ts"]), "queued manual SELL for the next open")
        self.assertIsNotNone(t.position, "nothing fills before the next bar")
        events = t.on_bar(bar(4, 108.0, 109.0))
        self.assertTrue(any("filled SELL (manual) @ 108.00" in e for e in events), events)
        self.assertIsNone(t.position)
        row = t.journal.closed_positions()[-1]
        self.assertEqual((row["reason"], row["exit_px"]), ("manual", 108.0))

    def test_nothing_to_close_and_no_double_sell(self):
        t = self.trader()
        self.assertEqual(t.request_close(1), "manual close: no open position")
        t = self.opened()
        t.request_close(bar(3, 0)["ts"])
        self.assertIn("already queued", t.request_close(bar(3, 0)["ts"]))

    def test_close_now_books_fee_and_slippage(self):
        self.cfg.fee, self.cfg.slippage = 0.001, 0.0005
        t = self.opened()
        entry = t.position
        event = t.close_now(110.0, bar(4, 0)["ts"])
        px = 110.0 * (1 - 0.0005)
        self.assertIn(f"exit manual @ {px:.2f}", event)
        row = t.journal.closed_positions()[-1]
        self.assertAlmostEqual(row["pnl"], (px - entry.entry_px) * entry.size - px * entry.size * 0.001
                               - entry.entry_fee)


class TestCommand(PaperTestCase):
    def run_cli(self, *argv):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = cli.main(["paper-close", "--state", str(self.db), *argv])
        return code, out.getvalue()

    def test_with_a_loop_running_it_leaves_a_request(self):
        t = TestManualClose.opened(self)
        t.journal.close()
        with JournalLock(self.db):                     # the running loop holds the journal
            code, text = self.run_cli()
        self.assertEqual(code, 0)
        self.assertIn("queued: it sells at the next bar's open", text)
        self.assertTrue(Path(str(self.db) + ".close").exists())

    def test_without_a_loop_it_closes_now_at_the_last_close(self):
        t = TestManualClose.opened(self)
        t.journal.close()
        code, text = self.run_cli()
        self.assertEqual(code, 0)
        self.assertIn("exit manual @ 99.95", text)                # the usual 5 bps slippage
        from espero.journal import Journal
        j = Journal(self.db)
        self.assertEqual(j.open_positions(), [])
        self.assertEqual(j.closed_positions()[-1]["reason"], "manual")
        j.close()

    def test_the_loop_picks_up_the_request(self):
        t = TestManualClose.opened(self)
        t.journal.close()
        Path(str(self.db) + ".close").write_text("x")
        args = cli.build_parser().parse_args(["paper", "--product", self.cfg.product, "--state", str(self.db),
                                              "--granularity", str(GRAN), "--fee-bps", "0"])
        from unittest import mock

        import pandas as pd
        nxt = bar(4, 105.0)
        df = pd.DataFrame([dict(nxt, dt=pd.Timestamp(nxt["ts"], unit="s", tz="UTC"))])
        with mock.patch("espero.data.recent_closed_bars", return_value=df), \
                contextlib.redirect_stdout(io.StringIO()) as out:
            cli._paper_loop(args)
        self.assertIn("queued manual SELL", out.getvalue())
        self.assertIn("filled SELL (manual) @ 104.95", out.getvalue())   # next open less slippage
        self.assertFalse(Path(str(self.db) + ".close").exists())


if __name__ == "__main__":
    unittest.main()


class TestManualOpen(PaperTestCase):
    def test_queued_buy_fills_at_the_next_open_with_the_usual_stop_and_target(self):
        t = self.trader()
        t.on_bar(bar(0, 100.0))
        self.assertEqual(t.request_open(bar(0, 0)["ts"], 200.0, 100.0), "queued manual BUY of 200.00 for the next open")
        t.on_bar(bar(1, 101.0))
        self.assertIsNotNone(t.position)
        self.assertAlmostEqual(t.position.entry_px, 101.0)
        self.assertAlmostEqual(t.position.size, 2.0)
        self.assertAlmostEqual(t.position.stop, 101.0 * (1 - self.cfg.stop_pct))
        self.assertIn("holding 2.000000 @ 101.00  now 110.00  P&L +18.00", t.holding(110.0))

    def test_never_more_than_the_cash_and_never_on_top_of_a_position(self):
        t = self.trader()
        t.on_bar(bar(0, 100.0))
        self.assertIn("queued manual BUY of 500.00", t.request_open(bar(0, 0)["ts"], 9999.0, 100.0))
        t.on_bar(bar(1, 100.0))
        self.assertIn("already open", t.request_open(bar(1, 0)["ts"], 50.0, 100.0))

    def test_command_needs_a_running_loop(self):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            self.assertEqual(cli.main(["paper-open", "--state", str(self.db), "--usd", "50"]), 2)
        with JournalLock(self.db), contextlib.redirect_stdout(out):
            self.assertEqual(cli.main(["paper-open", "--state", str(self.db), "--usd", "50"]), 0)
        self.assertEqual(Path(str(self.db) + ".open").read_text(), '{"usd": 50.0}')

    def test_the_loop_buys_on_request_then_shows_the_holding(self):
        t = self.trader()
        t.on_bar(bar(0, 100.0))
        t.journal.close()
        Path(str(self.db) + ".open").write_text('{"usd": 100}')
        args = cli.build_parser().parse_args(["paper", "--product", self.cfg.product, "--state", str(self.db),
                                              "--granularity", str(GRAN), "--fee-bps", "0"])
        from unittest import mock

        import pandas as pd
        nxt = bar(1, 102.0)
        df = pd.DataFrame([dict(nxt, dt=pd.Timestamp(nxt["ts"], unit="s", tz="UTC"))])
        with mock.patch("espero.data.recent_closed_bars", return_value=df), \
                contextlib.redirect_stdout(io.StringIO()) as out:
            cli._paper_loop(args)
        text = out.getvalue()
        self.assertIn("queued manual BUY of 100.00", text)
        self.assertIn("filled BUY", text)
        self.assertIn("holding", text)
        self.assertFalse(Path(str(self.db) + ".open").exists())


@unittest.skipUnless(importlib.util.find_spec("rich") and importlib.util.find_spec("questionary"), "tui extra")
class TestPaperBooks(PaperTestCase):
    def test_lists_open_positions_queued_orders_and_whether_a_loop_runs(self):
        from espero import ui
        t = TestManualClose.opened(self)                 # writes paper.db with an open position
        t.request_close(bar(3, 0)["ts"])
        t.journal.close()
        Path(self.db).rename(Path(self.tmp.name) / "paper-x.db")
        db = Path(self.tmp.name) / "paper-x.db"
        with JournalLock(db):
            books = ui.paper_books(Path(self.tmp.name))
        self.assertEqual(len(books), 1)
        b = books[0]
        self.assertTrue(b["running"])
        self.assertIsNotNone(b["position"])
        self.assertEqual(b["queued"], "SELL")
        self.assertFalse(ui.paper_books(Path(self.tmp.name))[0]["running"])

    def test_home_screen_sees_books_in_its_folder_and_in_the_state_folder_once_each(self):
        from espero import ui
        with tempfile.TemporaryDirectory() as t, tempfile.TemporaryDirectory() as s:
            Journal(Path(t) / "paper-a.db").close()
            Journal(Path(s) / "paper-b.db").close()
            with mock.patch.object(ui, "PAPER_DIR", Path(t)):
                self.assertEqual(sorted(b["path"].name for b in ui.all_paper_books(s)), ["paper-a.db", "paper-b.db"])
                self.assertEqual([b["path"].name for b in ui.all_paper_books(t)], ["paper-a.db"])

    def test_a_home_screen_loop_keeps_its_book_beside_the_accounts_not_in_a_temp_folder(self):
        from espero import ui
        self.assertEqual(ui.paper_dir("/st"), Path("/st/paper-books"))
        answers = iter(["Run a paper loop (stays here; ctrl-c returns)", "1 hour",
                        "Hyperliquid perp (its fees and actual hourly funding)"])
        with tempfile.TemporaryDirectory() as t, \
                mock.patch.object(ui.questionary, "select") as select, \
                mock.patch.object(ui.questionary, "text") as text, mock.patch.object(ui, "_run") as run:
            select.side_effect = lambda *a, **k: mock.Mock(ask=lambda: next(answers))
            text.return_value.ask.return_value = "BCH-USD"
            ui.act_paper(mock.Mock(), Path(t))
            cmd = run.call_args[0][1]
            book = Path(cmd[cmd.index("--state") + 1])
            self.assertEqual(book, Path(t) / "paper-books" / "paper-bch-usd-hl.db")
            self.assertTrue(book.parent.is_dir())
