"""research/INDEX.md claims every file in research/ exactly once, and the committed copy is current."""
from __future__ import annotations

import contextlib
import importlib.util
import io
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]


def load():
    spec = importlib.util.spec_from_file_location("research_index", ROOT / "research" / "index.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class TestTheRealFolder(unittest.TestCase):
    def setUp(self):
        self.ix = load()

    def test_every_file_has_exactly_one_owner_and_every_pattern_matches(self):
        self.assertEqual(self.ix.problems(self.ix.files()), [])

    def test_every_judged_test_has_an_entry(self):
        covered = {t.strip() for entry in self.ix.TESTS for t in entry.split(",")}
        missing = sorted(t for t in self.ix.statuses() if t not in covered)
        self.assertEqual(missing, [])

    def test_the_committed_index_is_current(self):
        self.assertEqual(self.ix.INDEX.read_text(), self.ix.render(self.ix.files()),
                         "research/INDEX.md is stale: run research/index.py")

    def test_check_mode_passes_here(self):
        self.assertEqual(self.ix.main(["--check"]), 0)


class TestTheChecker(unittest.TestCase):
    """On a made-up folder: an orphan, a double claim and a pattern with no file are each reported."""

    def setUp(self):
        self.ix = load()
        self.tmp = tempfile.TemporaryDirectory()
        self.folder = Path(self.tmp.name)
        for name in ("PREREGISTRATION_A.md", "RESULTS_A.md", "a.py", "a_run.txt", "trials.csv", "stray.txt"):
            (self.folder / name).write_text("x")
        (self.folder / "trials.csv").write_text("test,status,doc\n1,fail,research/RESULTS_A.md\n")

    def tearDown(self):
        self.tmp.cleanup()

    def run_with(self, tests, cross):
        with mock.patch.object(self.ix, "RESEARCH", self.folder), mock.patch.object(self.ix, "TESTS", tests), \
                mock.patch.object(self.ix, "CROSS_CUTTING", cross):
            return self.ix.problems(self.ix.files()), self.ix.render(self.ix.files())

    def test_clean_mapping_has_no_problems_and_renders_each_file_once(self):
        problems, text = self.run_with({"1": ("A", ["PREREGISTRATION_A.md", "RESULTS_A.md", "a.py", "a_run.txt"])},
                                       {"ledger": ["trials.csv", "stray.txt"]})
        self.assertEqual(problems, [])
        self.assertEqual(text.count("`a_run.txt`"), 1)
        self.assertIn("*#1 fail*", text)

    def test_an_orphan_a_double_claim_and_a_dead_pattern_are_reported(self):
        problems, _ = self.run_with({"1": ("A", ["PREREGISTRATION_A.md", "RESULTS_A.md", "a*", "b_run.txt"])},
                                    {"ledger": ["trials.csv", "a.py"]})
        self.assertIn("unclaimed: stray.txt", problems)
        self.assertTrue(any(p.startswith("claimed twice: a.py") for p in problems), problems)
        self.assertIn("1: nothing matches b_run.txt", problems)

    def test_check_mode_fails_on_a_stale_index(self):
        tests = {"1": ("A", ["PREREGISTRATION_A.md", "RESULTS_A.md", "a.py", "a_run.txt"])}
        cross = {"ledger": ["trials.csv", "stray.txt"]}
        with mock.patch.object(self.ix, "RESEARCH", self.folder), mock.patch.object(self.ix, "TESTS", tests), \
                mock.patch.object(self.ix, "CROSS_CUTTING", cross), \
                mock.patch.object(self.ix, "INDEX", self.folder / "INDEX.md"), \
                contextlib.redirect_stdout(io.StringIO()):               # its report lines are not check.sh's
            self.assertEqual(self.ix.main(["--check"]), 1)          # no INDEX.md yet
            self.assertEqual(self.ix.main([]), 0)                   # writes it
            self.assertEqual(self.ix.main(["--check"]), 0)
            (self.folder / "new_thing.txt").write_text("x")
            self.assertEqual(self.ix.main(["--check"]), 1)          # an unclaimed file


if __name__ == "__main__":
    unittest.main()
