"""The latency audit: every forward rule and pass has a row, and every class follows from its row's numbers."""
from __future__ import annotations

import contextlib
import csv
import io
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path

from espero import latency as L
from espero import runner

ROOT = Path(__file__).resolve().parents[1]


def row(**kw) -> L.Row:
    base = dict(test="99", name="x", doc="research/FORWARD_LIQ.md", event="e", needs="n", venue="v",
                budget_s=300.0, budget_why="b", feed="rawrec", feed_s=2.0, on_tape=True, today="t",
                today_s=None, tradable=True, why="w", klass=L.LIVE_FROM_TAPE)
    base.update(kw)
    return L.Row(**base)


class TestClassify(unittest.TestCase):
    def test_a_human_when_one_has_time(self):
        r = row(budget_s=L.OPERATOR_RESPONSE_S + 60.0, feed="rest", feed_s=60.0, on_tape=False)
        self.assertEqual(L.classify(r), L.OPERATOR_PACED)

    def test_one_second_short_of_a_human_is_auto_only_from_a_tape(self):
        r = row(budget_s=L.OPERATOR_RESPONSE_S + 59.0, feed="hlcollect", feed_s=60.0)
        self.assertEqual(L.classify(r), L.LIVE_FROM_TAPE)

    def test_the_tape_exactly_at_the_budget_still_counts(self):
        self.assertEqual(L.classify(row(budget_s=2.0, feed_s=2.0)), L.LIVE_FROM_TAPE)

    def test_a_tape_slower_than_the_budget_leaves_the_batch(self):
        r = row(budget_s=45.0, feed="batch", feed_s=L.BATCH_WORST_S, on_tape=False)
        self.assertEqual(L.classify(r), L.NEXT_DAY_BATCH)
        self.assertEqual(L.classify(row(budget_s=1.0, feed_s=2.0)), L.NEXT_DAY_BATCH)

    def test_inputs_off_the_tape_are_never_live(self):
        self.assertEqual(L.classify(row(on_tape=False)), L.NEXT_DAY_BATCH)
        self.assertEqual(L.classify(row(feed="rest")), L.NEXT_DAY_BATCH)

    def test_not_a_trade_is_not_tradable_whatever_its_numbers(self):
        self.assertEqual(L.classify(row(tradable=False)), L.NOT_TRADABLE)
        self.assertEqual(L.classify(row(budget_s=None)), L.NOT_TRADABLE)
        self.assertEqual(L.classify(row(feed_s=None)), L.NOT_TRADABLE)

    def test_a_slower_operator_moves_a_rule_out_of_operator_pacing(self):
        r = row(budget_s=5 * L.HOUR, feed="rest", feed_s=L.HOUR, on_tape=False)
        self.assertEqual(L.classify(r), L.OPERATOR_PACED)
        self.assertEqual(L.classify(r, operator_s=4.5 * L.HOUR), L.NEXT_DAY_BATCH)


class TestTheTable(unittest.TestCase):
    def test_no_problems(self):
        self.assertEqual(L.problems(), [])

    def test_every_forward_rule_and_pass_has_a_row(self):
        with open(ROOT / "research" / "trials.csv", newline="", encoding="utf-8") as fh:
            want = {r["test"] for r in csv.DictReader(fh)
                    if r["status"] in ("pass", "provisional", "forward_pending")}
        self.assertTrue({"4", "8", "12", "22", "65"} <= want)
        self.assertEqual(want - set(L.by_test()), set())

    def test_a_missing_row_is_reported(self):
        rows = [r for r in L.ROWS if r.test != "24"]
        self.assertIn("#24 is pass, provisional or forward_pending in trials.csv and has no row here",
                      L.problems(rows))

    def test_a_class_asserted_against_its_numbers_is_reported(self):
        rows = [replace(r, klass=L.OPERATOR_PACED) if r.test == "24" else r for r in L.ROWS]
        self.assertTrue(any(p.startswith("#24: the numbers give") for p in L.problems(rows)))

    def test_next_day_batch_needs_the_batch_as_its_feed(self):
        bad = row(test="24", feed="rest", feed_s=L.BATCH_WORST_S, on_tape=False, klass=L.NEXT_DAY_BATCH)
        rows = [bad if r.test == "24" else r for r in L.ROWS]
        self.assertTrue(any("say which class it is" in p for p in L.problems(rows)))

    def test_unknown_feed_and_class_and_document_are_reported(self):
        bad = row(test="24", feed="pigeon", klass="maybe", doc="research/NOPE.md")
        out = " ".join(L.problems([bad if r.test == "24" else r for r in L.ROWS]))
        for text in ("'pigeon' is not one of", "'maybe' is not a class", "research/NOPE.md does not exist"):
            self.assertIn(text, out)

    def test_a_duplicate_row_is_reported(self):
        self.assertIn("a test has two rows", L.problems(list(L.ROWS) + [L.ROWS[0]]))

    def test_no_budget_under_the_operators_answer_is_operator_paced(self):
        for r in L.ROWS:
            if r.klass == L.OPERATOR_PACED:
                self.assertGreaterEqual(r.budget_s, L.OPERATOR_RESPONSE_S, r.test)
        short = row(test="24", budget_s=L.HOUR, feed="rest", feed_s=60.0, on_tape=False, klass=L.OPERATOR_PACED)
        self.assertIn("#24: a budget under the operator's response time is never operator-paced",
                      L.problems([short if r.test == "24" else r for r in L.ROWS]))

    def test_the_registered_operator_answers_within_four_hours(self):
        self.assertEqual(L.OPERATOR_RESPONSE_S, 4 * 3600)       # docs/OPERATOR.md; the holder may raise it

    def test_every_daily_step_of_a_forward_rule_or_pass_has_a_row(self):
        docs = {r.doc for r in L.ROWS}
        for step, doc in runner.PLANS.items():
            if step in ("publish", "dashboard"):
                continue
            self.assertIn(doc, docs, step)

    def test_the_known_facts_are_in_the_rows(self):
        t = L.by_test()
        for n in ("26", "27", "32", "45"):
            self.assertEqual(t[n].klass, L.NOT_TRADABLE)
            self.assertIn("whole UTC day", t[n].why)
        for n in ("24", "31"):
            self.assertTrue(any("29 of its 42 coins" in d for d in t[n].distance), n)
        self.assertEqual(len(L.TAPE_BINANCE), 13)
        self.assertEqual(t["22"].budget_s, 60.0)
        self.assertEqual(t["58"].budget_s, 300.0)

    def test_a_tape_row_names_a_tape(self):
        for r in L.ROWS:
            if r.klass == L.LIVE_FROM_TAPE:
                self.assertIn(r.feed, L.TAPES, r.test)
                self.assertTrue(r.on_tape, r.test)

    def test_not_tradable_rows_say_why(self):
        for r in L.ROWS:
            if r.klass == L.NOT_TRADABLE:
                self.assertTrue(r.why, r.test)
        self.assertTrue(any("without saying why" in p for p in L.problems([row(tradable=False, why="",
                                                                                klass=L.NOT_TRADABLE)])))


class TestTheDocument(unittest.TestCase):
    def test_the_document_holds_the_current_table(self):
        self.assertEqual(L.block(), L.render())

    def test_check_passes(self):
        self.assertEqual(L.main(["--check"]), 0)

    def test_check_fails_on_a_stale_document(self):
        with tempfile.TemporaryDirectory() as d:
            doc = Path(d) / "x.md"
            doc.write_text(f"{L.START}\n| an old table |\n{L.END}\n", encoding="utf-8")
            self.assertEqual(L.main(["--check"], doc=doc), 1)
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(L.main([], doc=doc), 0)
            self.assertEqual(L.main(["--check"], doc=doc), 0)

    def test_write_replaces_only_the_block(self):
        with tempfile.TemporaryDirectory() as d:
            doc = Path(d) / "x.md"
            doc.write_text(f"before\n{L.START}\nold\n{L.END}\nafter\n", encoding="utf-8")
            L.write(doc)
            text = doc.read_text(encoding="utf-8")
            self.assertTrue(text.startswith("before\n") and text.endswith("after\n"))
            self.assertNotIn("\nold\n", text)
            self.assertEqual(L.block(doc), L.render())

    def test_render_has_both_tables_and_the_shared_steps(self):
        out = L.render()
        self.assertIn("| # | rule | event |", out)
        self.assertIn("| # | class | why |", out)
        for step in L.COMMON_DISTANCE:
            self.assertIn(step, out)

    def test_durations(self):
        self.assertEqual([L.fmt_s(x) for x in (None, 45.0, 720.0, 30240.0, 36 * L.HOUR, 31 * L.DAY)],
                         ["—", "45 s", "12 min", "8.4 h", "36 h", "31 d"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
