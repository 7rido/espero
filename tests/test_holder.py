"""The holder's answers: read from the document, defaults that refuse, and an operator never made faster."""
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from espero import holder as H
from espero import latency, risk


def doc(answers: dict) -> Path:
    """A copy of the real page with some answers filled in."""
    text = H.DOC.read_text(encoding="utf-8")
    for qid, value in answers.items():
        lines = text.splitlines()
        for i, line in enumerate(lines):
            if line.startswith(f"| `{qid}` |"):
                cells = line.split("|")
                cells[3] = f" {value} "
                lines[i] = "|".join(cells)
        text = "\n".join(lines) + "\n"
    d = Path(tempfile.mkdtemp()) / "HOLDER_INPUTS.md"
    d.write_text(text, encoding="utf-8")
    return d


class TestThePageAsItIs(unittest.TestCase):
    def test_every_question_is_there_and_readable(self):
        self.assertEqual(H.problems(), [])
        self.assertEqual(set(H.rows()), set(H.QUESTIONS))

    def test_nothing_is_answered_so_every_default_refuses(self):
        a = H.answers()
        self.assertEqual(H.allocated_usd(), 0.0)
        self.assertEqual(H.operator_response_s(), 4 * 3600.0)
        self.assertFalse(a["autonomy"] or a["totp_set_up"] or a["tax_and_licensing_checked"])
        self.assertEqual(a["venues_eligible"], ())
        self.assertIsNone(a["mainnet_lift"])
        self.assertFalse(H.eligible("hyperliquid"))

    def test_the_gate_refuses_on_the_holders_default(self):
        acct = risk.Account(capital=H.allocated_usd(), equity=1_000.0, equity_by_venue={"hyperliquid": 1_000.0},
                            sleeve_scale={"s": 1.0})
        r = risk.check(risk.Order("s", "12", "hyperliquid", "BTC", 1, 100.0), acct)
        self.assertFalse(r.allowed)
        self.assertIn("no capital allocated", r.reasons[0])

    def test_the_protocols_response_time_is_the_latency_audits(self):
        self.assertEqual(H.PROTOCOL_RESPONSE_S, latency.OPERATOR_RESPONSE_S)


class TestAnswers(unittest.TestCase):
    def test_answers_are_read_as_their_kinds(self):
        d = doc({"capital_usd": "$25,000", "stop_drawdown": "-15%", "venues_eligible": "Binance, Hyperliquid",
                 "tax_and_licensing_checked": "yes", "operator_response_hours": "6", "autonomy": "no"})
        a = H.answers(d)
        self.assertEqual(H.problems(d), [])
        self.assertEqual(H.allocated_usd(d), 25_000.0)
        self.assertAlmostEqual(a["stop_drawdown"], -0.15)
        self.assertEqual(a["venues_eligible"], ("binance", "hyperliquid"))
        self.assertTrue(H.eligible("Hyperliquid", d))
        self.assertFalse(H.eligible("okx", d))
        self.assertEqual(H.operator_response_s(d), 6 * 3600.0)
        self.assertFalse(a["autonomy"])

    def test_a_stop_at_zero_or_beyond_a_total_loss_is_not_a_stop(self):
        for bad in ("0", "0%", "-100%", "-1.5"):
            self.assertIn("stop_drawdown", " ".join(H.problems(doc({"stop_drawdown": bad}))), bad)

    def test_a_faster_operator_does_not_lower_the_protocols_four_hours(self):
        self.assertEqual(H.operator_response_s(doc({"operator_response_hours": "1"})), 4 * 3600.0)

    def test_a_venue_needs_the_tax_check_too(self):
        self.assertFalse(H.eligible("binance", doc({"venues_eligible": "binance"})))

    def test_unreadable_answers_are_problems_and_fall_back_to_the_default(self):
        d = doc({"capital_usd": "lots", "stop_drawdown": "15%", "autonomy": "maybe", "operator_hours_per_week": "-3"})
        out = " ".join(H.problems(d))
        for qid in ("capital_usd", "stop_drawdown", "autonomy", "operator_hours_per_week"):
            self.assertIn(qid, out)
        self.assertEqual(H.allocated_usd(d), 0.0)
        self.assertIsNone(H.answers(d)["stop_drawdown"])

    def test_a_lift_must_point_at_a_committed_file(self):
        self.assertIn("does not exist", " ".join(H.problems(doc({"mainnet_lift": "research/NO_SUCH_LIFT.md"}))))
        self.assertEqual(H.problems(doc({"mainnet_lift": "AGENTS.md"})), [])

    def test_a_question_added_or_dropped_is_a_problem(self):
        text = H.DOC.read_text(encoding="utf-8").replace("| `autonomy` |", "| `autonomous` |")
        d = Path(tempfile.mkdtemp()) / "x.md"
        d.write_text(text, encoding="utf-8")
        out = H.problems(d)
        self.assertIn("autonomous: not a question here", out)
        self.assertIn("autonomy: missing from the answers table", out)

    def test_a_page_without_markers_answers_nothing(self):
        d = Path(tempfile.mkdtemp()) / "x.md"
        d.write_text("no table here\n", encoding="utf-8")
        self.assertEqual(H.rows(d), {})
        self.assertEqual(H.allocated_usd(d), 0.0)


@unittest.skipUnless(shutil.which("git"), "needs git")
class TestOnlyACommittedAnswerCounts(unittest.TestCase):
    """The page says an answer is given in a commit; the code reads nothing an uncommitted edit says."""

    def setUp(self):
        self.root = Path(tempfile.mkdtemp())
        (self.root / "docs").mkdir()
        self.doc = self.root / "docs" / "HOLDER_INPUTS.md"
        self.doc.write_bytes(doc({"capital_usd": "25000", "venues_eligible": "hyperliquid",
                                  "tax_and_licensing_checked": "yes"}).read_bytes())
        git = ["git", "-C", str(self.root), "-c", "user.name=t", "-c", "user.email=t@example.invalid"]
        subprocess.run(git + ["init", "-q"], check=True)
        subprocess.run(git + ["add", "docs/HOLDER_INPUTS.md"], check=True)
        subprocess.run(git + ["commit", "-q", "-m", "the holder answers"], check=True)
        self._real = H.DOC, H.ROOT
        H.DOC, H.ROOT = self.doc, self.root

    def tearDown(self):
        H.DOC, H.ROOT = self._real

    def test_the_committed_page_counts(self):
        self.assertTrue(H.committed(self.doc, self.root))
        self.assertEqual(H.allocated_usd(), 25_000.0)
        self.assertTrue(H.eligible("hyperliquid"))
        self.assertEqual(H.problems(self.doc, self.root), [])

    def test_an_uncommitted_edit_counts_for_nothing(self):
        self.doc.write_text(self.doc.read_text(encoding="utf-8").replace("| 25000 |", "| 50000 |"), encoding="utf-8")
        self.assertFalse(H.committed(self.doc, self.root))
        self.assertEqual(H.allocated_usd(), 0.0)
        self.assertFalse(H.eligible("hyperliquid"))
        self.assertTrue(any("not what HEAD holds" in p for p in H.problems(self.doc, self.root)))
        self.assertEqual(H.answers(self.doc)["capital_usd"], 50_000.0)     # the raw read still says what it says

    def test_a_page_outside_a_checkout_counts_for_nothing(self):
        loose = Path(tempfile.mkdtemp()) / "HOLDER_INPUTS.md"
        loose.write_bytes(self.doc.read_bytes())
        self.assertFalse(H.committed(loose, loose.parent))
        H.DOC, H.ROOT = loose, loose.parent
        self.assertEqual(H.allocated_usd(), 0.0)

    def test_a_copy_given_explicitly_is_read_as_before(self):
        """tests and tools read a copy by path; only the real page is held to HEAD."""
        copy = Path(tempfile.mkdtemp()) / "x.md"
        copy.write_bytes(self.doc.read_bytes())
        self.assertEqual(H.allocated_usd(copy), 25_000.0)


class TestTheLatencyAuditFollowsTheHolder(unittest.TestCase):
    def test_a_slow_enough_operator_changes_classes_and_the_audit_says_so(self):
        self.assertEqual(latency.problems(operator_s=4 * 3600.0), [])
        slow = latency.problems(operator_s=8 * 3600.0)
        self.assertTrue(any(p.startswith("#8: the numbers give") for p in slow), slow)


if __name__ == "__main__":
    unittest.main()
