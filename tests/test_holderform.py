"""The guided form for the holder's answers and the lift: what it stores, what it refuses, what it leaves alone."""
import subprocess
import tempfile
import unittest
from datetime import date
from pathlib import Path

from espero import holder as H
from espero import holderform as F

TODAY = date(2026, 11, 3)
FIELDS = {"venue": "hyperliquid", "coins": "BTC, ETH", "max_order_usd": "12", "max_position_usd": "24",
          "expiry": "2027-01-31", "rule": "8", "approval": "every trade", "machine": "2fe1955570d2c740"}
STATEMENT = "I lift the no-mainnet rule for a canary at the venue's minimum size, approved by me trade by trade."


def page() -> str:
    """The page as the last commit holds it with every answer cleared, so no answer of the holder's, committed or
    not, ever changes a test. Cleared here by hand, not by the module under test."""
    text = subprocess.run(["git", "-C", str(H.ROOT), "show", "HEAD:docs/HOLDER_INPUTS.md"], capture_output=True,
                          text=True, check=True).stdout
    out = []
    for line in text.split("\n"):
        if line.startswith("| `") and line.count("|") == 5:
            cells = line.split("|")
            cells[3] = " "
            line = "|".join(cells)
        out.append(line)
    return "\n".join(out)


class TestToStored(unittest.TestCase):
    def test_a_drawdown_typed_any_way_is_stored_as_a_loss(self):
        for typed in ("3", "3%", "-3%", " 3 % ", "-3"):
            self.assertEqual(F.to_stored("stop_drawdown", typed), "-3%", typed)
        self.assertEqual(F.to_stored("stop_drawdown", "12.5"), "-12.5%")
        self.assertAlmostEqual(H.parse("fraction", F.to_stored("stop_drawdown", "3")), -0.03)

    def test_a_duration_in_minutes_is_stored_in_hours(self):
        self.assertEqual(F.to_stored("operator_response_hours", "10 minutes"), "0.1667")
        self.assertEqual(F.to_stored("operator_response_hours", "30 min"), "0.5")
        self.assertEqual(F.to_stored("operator_response_hours", "2 hours"), "2")
        self.assertEqual(F.to_stored("operator_response_hours", "1.5"), "1.5")
        with self.assertRaises(ValueError):
            F.to_stored("operator_response_hours", "soon")

    def test_dollars_lose_their_signs_and_commas(self):
        self.assertEqual(F.to_stored("capital_usd", "$1,000"), "1000")
        self.assertEqual(F.to_stored("capital_usd", "100.50"), "100.5")
        with self.assertRaises(ValueError):
            F.to_stored("capital_usd", "-5")
        with self.assertRaises(ValueError):
            F.to_stored("capital_usd", "a hundred")

    def test_yes_no_and_venues(self):
        self.assertEqual(F.to_stored("totp_set_up", True), "yes")
        self.assertEqual(F.to_stored("totp_set_up", False), "no")
        self.assertEqual(F.to_stored("venues_eligible", ["Hyperliquid", " coinbase ", ""]), "hyperliquid, coinbase")
        with self.assertRaises(ValueError):
            F.to_stored("tax_and_licensing_checked", "0")

    def test_empty_is_not_answered_and_unknown_ids_are_refused(self):
        self.assertEqual(F.to_stored("min_capital_usd", "  "), "")
        with self.assertRaises(ValueError):
            F.to_stored("not_a_question", "1")

    def test_an_answer_that_would_break_the_table_is_refused(self):
        with self.assertRaises(ValueError):
            F.to_stored("venues_eligible", "hyperliquid | coinbase")


class TestSetAnswers(unittest.TestCase):
    def test_only_the_answer_column_changes_and_the_code_reads_it(self):
        text = page()
        out = F.set_answers(text, {"capital_usd": "100", "stop_drawdown": "-3%", "venues_eligible": "hyperliquid"})
        changed = [(a, b) for a, b in zip(text.splitlines(), out.splitlines()) if a != b]
        self.assertEqual(len(changed), 3)
        for before, after in changed:
            self.assertEqual(before.split("|")[:3], after.split("|")[:3])     # the id and the question stay
            self.assertEqual(before.split("|")[4:], after.split("|")[4:])     # the default stays
        d = Path(tempfile.mkdtemp()) / "HOLDER_INPUTS.md"
        d.write_text(out, encoding="utf-8")
        a = H.answers(d)
        self.assertEqual(a["capital_usd"], 100.0)
        self.assertAlmostEqual(a["stop_drawdown"], -0.03)
        self.assertEqual(a["venues_eligible"], ("hyperliquid",))
        self.assertEqual([p for p in H.problems(d) if "missing" in p or "not an answer" in p], [])

    def test_an_empty_value_clears_an_answer(self):
        text = F.set_answers(page(), {"capital_usd": "100"})
        out = F.set_answers(text, {"capital_usd": ""})
        self.assertEqual(out, page())

    def test_unknown_ids_and_broken_values_are_refused(self):
        with self.assertRaises(KeyError):
            F.set_answers(page(), {"no_such_id": "1"})
        with self.assertRaises(ValueError):
            F.set_answers(page(), {"capital_usd": "1 | 2"})
        with self.assertRaises(KeyError):
            F.set_answers("no table here", {"capital_usd": "1"})

    def test_every_plain_question_is_a_question_on_the_page(self):
        self.assertEqual(set(F.PLAIN) | {"mainnet_lift"}, set(H.QUESTIONS))


class TestLift(unittest.TestCase):
    def test_the_statement_is_kept_verbatim_and_the_block_reads_back(self):
        doc = F.lift_document(STATEMENT, FIELDS, TODAY)
        self.assertIn(STATEMENT, doc)
        self.assertEqual(F.lift_answers(doc), FIELDS)
        self.assertIn("2026-11-03", doc)

    def test_the_form_never_supplies_the_words(self):
        for statement in ("", "   ", "I lift it."):
            with self.assertRaises(ValueError):
                F.lift_document(statement, FIELDS, TODAY)
        self.assertEqual(F.check_lift("x" * F.MIN_STATEMENT, FIELDS, TODAY), [])
        self.assertTrue(F.check_lift("x" * (F.MIN_STATEMENT - 1), FIELDS, TODAY))

    def test_every_field_is_required(self):
        for k in F.LIFT_FIELDS:
            short = dict(FIELDS)
            short[k] = " "
            self.assertTrue(any(p.startswith(f"{k}:") for p in F.check_lift(STATEMENT, short, TODAY)), k)

    def test_every_problem_names_a_field_the_form_can_ask_again(self):
        for bad in (dict(FIELDS, venue="hyperliquid, coinbase", max_order_usd="60", expiry="0"),
                    dict(FIELDS, venue="alpaca", max_order_usd="x", expiry="2026-11-01")):
            problems = F.check_lift("too short", bad, TODAY, ["hyperliquid"])
            self.assertEqual(len(problems), 4, problems)
            for p in problems:
                self.assertIn(p.split(":", 1)[0], ["statement"] + list(F.LIFT_FIELDS), p)

    def test_the_lift_covers_one_venue_the_holder_marked_open(self):
        def venue_problems(v, eligible=("hyperliquid", "coinbase")):
            return [p for p in F.check_lift(STATEMENT, dict(FIELDS, venue=v), TODAY, eligible) if p.startswith("venue")]
        self.assertEqual(venue_problems("hyperliquid"), [])
        self.assertEqual(venue_problems("Hyperliquid"), [])
        self.assertTrue(venue_problems("hyperliquid, coinbase"))
        self.assertTrue(venue_problems("hyperliquid coinbase"))
        self.assertTrue(venue_problems("alpaca"))
        self.assertEqual(venue_problems("alpaca", eligible=None), [])       # no list given: only the one-venue rule
        self.assertTrue(venue_problems("hyperliquid coinbase", eligible=None))   # two venues, whatever the list

    def test_sizes_and_expiry_are_checked(self):
        bigger = dict(FIELDS, max_order_usd="30")
        self.assertTrue(F.check_lift(STATEMENT, bigger, TODAY))
        self.assertEqual(F.check_lift(STATEMENT, dict(FIELDS, max_order_usd="24"), TODAY), [])
        self.assertTrue(F.check_lift(STATEMENT, dict(FIELDS, max_order_usd="0"), TODAY))
        self.assertTrue(F.check_lift(STATEMENT, dict(FIELDS, expiry="2026-11-03"), TODAY))
        self.assertTrue(F.check_lift(STATEMENT, dict(FIELDS, expiry="next year"), TODAY))
        self.assertTrue(F.check_lift(STATEMENT, dict(FIELDS, coins="BTC | ETH"), TODAY))


class _Ask:
    def __init__(self, value):
        self.value = value

    def ask(self):
        return self.value


try:
    import questionary as _questionary  # noqa: F401  the tui extra; CI installs only chart and dev
except ImportError:
    _questionary = None


@unittest.skipIf(_questionary is None, "needs the tui extra (questionary)")
class TestTheFormEndToEnd(unittest.TestCase):
    """The whole form with scripted answers, in a copy of the page: what it writes, and that a no writes nothing."""

    def setUp(self):
        import questionary  # noqa: F401  the tui extra; the form refuses without it

        self.root = Path(tempfile.mkdtemp())
        (self.root / "docs").mkdir()
        (self.root / "research").mkdir()
        (self.root / "docs" / "HOLDER_INPUTS.md").write_text(page(), encoding="utf-8")

    def walk(self, texts, selects, checkbox, confirms):
        from unittest import mock

        import questionary

        texts, selects, confirms = list(texts), list(selects), list(confirms)
        with mock.patch.object(questionary, "text", side_effect=lambda *a, **k: _Ask(texts.pop(0))), \
                mock.patch.object(questionary, "select", side_effect=lambda *a, **k: _Ask(selects.pop(0))), \
                mock.patch.object(questionary, "checkbox", side_effect=lambda *a, **k: _Ask(checkbox)), \
                mock.patch.object(questionary, "confirm", side_effect=lambda *a, **k: _Ask(confirms.pop(0))), \
                mock.patch.object(F, "machine_hash", return_value="2fe1955570d2c740"), \
                mock.patch.object(F, "commit_signed", return_value=subprocess.CompletedProcess([], 0)) as commit:
            code = F.run(root=self.root, today=TODAY)
        return code, commit

    # the text questions in PLAIN's order: capital, drawdown, hours a week, response, min capital, venue loss, budget
    TEXTS = ["100", "3", "40", "10 minutes", "100", "10", "0"]
    SELECTS = ["no", "no", "no"]          # tax and licensing, the one-time code, autonomy

    def test_answers_are_written_in_the_stored_form_and_nothing_is_committed_unasked(self):
        code, commit = self.walk(self.TEXTS, self.SELECTS, ["hyperliquid", "coinbase"], [False, True, False])
        self.assertEqual(code, 0)
        commit.assert_not_called()
        a = H.answers(self.root / "docs" / "HOLDER_INPUTS.md")
        self.assertEqual(a["capital_usd"], 100.0)
        self.assertAlmostEqual(a["stop_drawdown"], -0.03)
        self.assertEqual(a["venues_eligible"], ("hyperliquid", "coinbase"))
        self.assertAlmostEqual(a["operator_response_hours"], 0.1667)
        self.assertFalse(a["tax_and_licensing_checked"])
        self.assertIsNone(a["mainnet_lift"])
        self.assertFalse((self.root / F.LIFT).exists())

    def test_declining_to_save_writes_nothing(self):
        code, _ = self.walk(self.TEXTS, self.SELECTS, ["hyperliquid"], [False, False])
        self.assertEqual(code, 1)
        self.assertEqual((self.root / "docs" / "HOLDER_INPUTS.md").read_text(), page())

    def test_a_refused_lift_is_asked_again_not_dropped(self):
        # first pass: a one-line statement and an expiry of 0, as typed on 2026-11-03; second pass fixes both
        first = ["i lift the rules"] + [("0" if k == "expiry" else FIELDS[k]) for k in F.LIFT_FIELDS]
        again = [STATEMENT, FIELDS["expiry"]]
        code, commit = self.walk(self.TEXTS + first + again + ["a plumbing canary"], self.SELECTS, ["hyperliquid"],
                                 [True, True, True, True])
        self.assertEqual(code, 0)
        doc = (self.root / F.LIFT).read_text()
        self.assertIn(STATEMENT, doc)
        self.assertEqual(F.lift_answers(doc), FIELDS)
        self.assertEqual(commit.call_args[0][1], ["docs/HOLDER_INPUTS.md", "research/MAINNET_LIFT.md"])

    def test_a_size_problem_asks_both_sizes_again_and_a_venue_not_marked_open_is_asked_again(self):
        first = [STATEMENT] + [{"venue": "alpaca", "max_order_usd": "60", "max_position_usd": "50"}.get(k, FIELDS[k])
                               for k in F.LIFT_FIELDS]
        again = ["hyperliquid", "12", "24"]        # in the order the problems name them: venue, then both sizes
        code, _ = self.walk(self.TEXTS + first + again + ["a plumbing canary"], self.SELECTS, ["hyperliquid"],
                            [True, True, True, True])
        self.assertEqual(code, 0)
        self.assertEqual(F.lift_answers((self.root / F.LIFT).read_text()), FIELDS)

    def test_declining_to_fix_a_refused_lift_saves_the_answers_without_it(self):
        first = ["i lift the rules"] + [FIELDS[k] for k in F.LIFT_FIELDS]
        code, commit = self.walk(self.TEXTS + first, self.SELECTS, ["hyperliquid"], [True, False, True, False])
        self.assertEqual(code, 0)
        self.assertFalse((self.root / F.LIFT).exists())
        self.assertIsNone(H.answers(self.root / "docs" / "HOLDER_INPUTS.md")["mainnet_lift"])

    def test_the_lift_is_written_from_the_holder_s_words_and_named_on_the_page(self):
        lift_texts = [STATEMENT] + [FIELDS[k] for k in F.LIFT_FIELDS]
        reason = ["a plumbing canary"]
        code, commit = self.walk(self.TEXTS + lift_texts + reason, self.SELECTS, ["hyperliquid"], [True, True, True])
        self.assertEqual(code, 0)
        doc = (self.root / F.LIFT).read_text()
        self.assertIn(STATEMENT, doc)
        self.assertEqual(F.lift_answers(doc), FIELDS)
        self.assertEqual(H.answers(self.root / "docs" / "HOLDER_INPUTS.md")["mainnet_lift"], "research/MAINNET_LIFT.md")
        commit.assert_called_once()
        self.assertEqual(commit.call_args[0][1], ["docs/HOLDER_INPUTS.md", "research/MAINNET_LIFT.md"])
        self.assertEqual(commit.call_args[0][2], "The holder's answers: a plumbing canary")


if __name__ == "__main__":
    unittest.main()
