"""The tabbed home screen (espero/tui.py), driven by a simulated keyboard on made-up data and a real ledger."""
import tempfile
import unittest
from pathlib import Path

from espero import approvals
from espero import screen_data as D

try:
    from espero import tui
except ImportError:            # the tui extra is missing
    tui = None

NOW = 1793750400.0


def coin(name, px=100.0, ch=0.01, f=0.0000125, vol=1e8):
    return D.Coin(name, px, ch, f, 1e6, vol)


def sources(**kw):
    base = dict(contexts=lambda: [coin("BTC", 77_000.0, 0.009), coin("ETH", 2_280.0, -0.014), coin("RUNE", 1.2, 0.15)],
                closes=lambda c: [100.0, 101.0] * 15,
                liquidations=lambda: {"at": NOW, "coins": {"BTC": {"longs": 3e4, "shorts": 4.5e6}}},
                outlook=lambda: [D.Outlook("BTC", 0.057, 0.035, "stormier")],
                now=lambda: NOW)
    base.update(kw)
    return tui.Sources(**base)


def ledger_with(state: Path, *coins):
    led = approvals.Ledger.open(state / approvals.LEDGER)
    for i, c in enumerate(coins):
        led.record(approvals.Proposal(f"p{i}", "machine", "8", "mf-canary", c, "buy", "entry", 12.0, 1.0, 9.9, None,
                                      "operator-paced", int(NOW), int(NOW) + 86_100))
    led.db.close()


@unittest.skipIf(tui is None, "needs the tui extra")
class TestTheScreen(unittest.IsolatedAsyncioTestCase):
    async def test_tabs_switch_with_the_arrows_and_the_numbers(self):
        app = tui.EsperoApp(Path(tempfile.mkdtemp()), sources())
        async with app.run_test() as pilot:
            tabs = app.query_one(tui.TabbedContent)
            self.assertEqual(tabs.active, "today")
            await pilot.press("right")
            self.assertEqual(tabs.active, "market")
            await pilot.press("left", "left")
            self.assertEqual(tabs.active, "settings")
            await pilot.press("3")
            self.assertEqual(tabs.active, "books")

    async def test_today_lists_what_waits_and_says_when_nothing_does(self):
        state = Path(tempfile.mkdtemp())
        ledger_with(state, "BTC", "ETH")
        app = tui.EsperoApp(state, sources())
        async with app.run_test():
            table = app.query_one("#waiting", tui.DataTable)
            self.assertEqual(table.row_count, 2)
            self.assertEqual(table.get_row_at(0)[1], "Buy BTC $12")
        empty = tui.EsperoApp(Path(tempfile.mkdtemp()), sources())
        async with empty.run_test():
            self.assertIn("Nothing waits", str(empty.query_one("#waiting-note", tui.Static).render()))
            self.assertFalse(empty.query_one("#waiting", tui.DataTable).display)

    async def test_approving_asks_for_the_code_and_leaves_the_answer_for_the_canary(self):
        state = Path(tempfile.mkdtemp())
        ledger_with(state, "BTC", "ETH")
        posted = []
        app = tui.EsperoApp(state, sources(), post=lambda st, reply: posted.append(reply))
        async with app.run_test() as pilot:
            await pilot.press("down", "a")
            self.assertIsInstance(app.screen, tui.AnswerScreen)
            await pilot.press("right")                                        # the arrow belongs to the dialog now
            self.assertEqual(app.query_one(tui.TabbedContent).active, "today")
            await pilot.press(*"12345", "enter")                              # five digits: refused, still open
            self.assertIsInstance(app.screen, tui.AnswerScreen)
            await pilot.press("6", "enter")
            await pilot.pause()
            self.assertEqual(len(posted), 1)
            r = posted[0]
            self.assertEqual((r.proposal, r.answer, r.code, r.channel), ("p1", "approve", "123456", "tui"))
            self.assertEqual(app.sent["p1"], "approval sent")

    async def test_a_rejection_needs_a_reason_and_escape_sends_nothing(self):
        state = Path(tempfile.mkdtemp())
        ledger_with(state, "BTC")
        posted = []
        app = tui.EsperoApp(state, sources(), post=lambda st, reply: posted.append(reply))
        async with app.run_test() as pilot:
            await pilot.press("a", "escape")
            await pilot.pause()
            self.assertEqual(posted, [])
            await pilot.press("x", *"too risky", "enter", *"654321", "enter")
            await pilot.pause()
            self.assertEqual((posted[0].answer, posted[0].reason, posted[0].code), ("reject", "too risky", "654321"))

    async def test_a_rejection_without_a_reason_is_not_sent(self):
        state = Path(tempfile.mkdtemp())
        ledger_with(state, "BTC")
        posted = []
        app = tui.EsperoApp(state, sources(), post=lambda st, reply: posted.append(reply))
        async with app.run_test() as pilot:
            await pilot.press("x", "tab", *"654321", "enter")                  # skip the reason, give a good code
            await pilot.pause()
            self.assertEqual(posted, [])
            self.assertIsInstance(app.screen, tui.AnswerScreen)
            self.assertIn("needs a reason", str(app.screen.query_one("#dialog-hint", tui.Label).render()))

    async def test_a_fresh_copy_is_not_called_broken(self):
        app = tui.EsperoApp(Path(tempfile.mkdtemp()), sources())
        async with app.run_test():
            self.assertIn("a fresh copy", str(app.query_one("#topbar", tui.Static).render()))
            self.assertNotIn("need", str(app.query_one("#topbar", tui.Static).render()))
            self.assertIn("install-launchd", str(app.query_one("#system", tui.Static).render()))

    async def test_answer_keys_do_nothing_off_the_today_tab(self):
        state = Path(tempfile.mkdtemp())
        ledger_with(state, "BTC")
        app = tui.EsperoApp(state, sources())
        async with app.run_test() as pilot:
            await pilot.press("2", "a")
            self.assertNotIsInstance(app.screen, tui.AnswerScreen)

    async def test_the_market_tab_draws_prices_movers_funding_liquidations_and_volatility(self):
        app = tui.EsperoApp(Path(tempfile.mkdtemp()), sources())
        async with app.run_test() as pilot:
            await app.workers.wait_for_complete()
            await pilot.pause()
            text = {i: str(app.query_one(f"#{i}", tui.Static).render()) for i in ("funding", "liqs", "vol")}
            self.assertIn("Longs pay shorts", text["funding"])
            self.assertIn("$4.5M of shorts", text["liqs"])
            self.assertIn("shorts squeezed", text["liqs"])
            self.assertIn("stormier", text["vol"])
            self.assertEqual([c.coin for c in app.market_rows], ["BTC", "ETH", "RUNE"])

    async def test_a_market_that_does_not_answer_says_so(self):
        app = tui.EsperoApp(Path(tempfile.mkdtemp()), sources(contexts=lambda: 1 / 0, liquidations=lambda: None,
                                                              outlook=lambda: []))
        async with app.run_test() as pilot:
            await app.workers.wait_for_complete()
            await pilot.pause()
            self.assertIn("did not answer", str(app.query_one("#prices", tui.Static).render()))
            self.assertIn("aggr did not answer", str(app.query_one("#liqs", tui.Static).render()))


class TestWords(unittest.TestCase):
    @unittest.skipIf(tui is None, "needs the tui extra")
    def test_plain_words_for_numbers(self):
        self.assertEqual(tui.size_word(0.5), "normal (0.5× a normal day)")
        self.assertEqual(tui.size_word(-2.4), "very large (2.4× a normal day)")
        self.assertEqual(tui.size_word(3.1), "extreme (3.1× a normal day)")
        self.assertEqual(tui.size_word(None), "")
        self.assertEqual(tui.money(4_454_551), "$4.5M")
        self.assertEqual(tui.money(37_579), "$38K")
        self.assertEqual(tui.money(3.2e9), "$3.2B")
        self.assertEqual(tui.price(77_407), "77,407.00")
        self.assertEqual(tui.price(0.2345), "0.2345")


if __name__ == "__main__":
    unittest.main()
