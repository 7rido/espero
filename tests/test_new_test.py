"""scripts/new-test.py writes the three files a test needs, nothing else, and refuses a taken number."""
from __future__ import annotations

import contextlib
import importlib.util
import io
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def load():
    spec = importlib.util.spec_from_file_location("new_test_script", ROOT / "scripts" / "new-test.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class TestScaffold(unittest.TestCase):
    def setUp(self):
        self.s = load()
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        for d in ("research", "espero", "tests"):
            (self.root / d).mkdir()
        (self.root / "research" / "trials.csv").write_text("test,name,status\n60,ladder,forward_pending\n")

    def tearDown(self):
        self.tmp.cleanup()

    def run_it(self, *argv):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            rc = self.s.main(list(argv), root=self.root)
        return rc, out.getvalue(), err.getvalue()

    def test_writes_exactly_three_files_with_the_discipline_in_them(self):
        rc, out, _ = self.run_it("61", "depthday")
        self.assertEqual(rc, 0)
        written = sorted(p.relative_to(self.root).as_posix() for p in self.root.rglob("*") if p.is_file())
        self.assertEqual(written, ["espero/depthday.py", "research/PREREGISTRATION_DEPTHDAY.md", "research/trials.csv",
                                   "tests/test_depthday.py"])
        prereg = (self.root / "research" / "PREREGISTRATION_DEPTHDAY.md").read_text()
        for must in ("#61", "Benjamini-Hochberg q < 0.05", "|t| ≥ 3", "next bar's open", "FORWARD_FAMILY.md",
                     "never zero"):
            self.assertIn(must, prereg)
        self.assertNotIn("## Forward", prereg)
        self.assertIn("NotImplementedError", (self.root / "espero" / "depthday.py").read_text())
        self.assertIn("espero/layers.py", out)
        self.assertIn('research/index.py (TESTS["61"])', out)
        self.assertIn("RESULTS_DEPTHDAY.md", out)

    def test_forward_adds_the_window_and_the_runner_step(self):
        rc, out, _ = self.run_it("62", "funding_lag", "--forward")
        self.assertEqual(rc, 0)
        prereg = (self.root / "research" / "PREREGISTRATION_FUNDING_LAG.md").read_text()
        self.assertIn("## Forward", prereg)
        self.assertIn("state/funding_lag_trades.csv", prereg)
        self.assertIn("runner.PLANS", out)

    def test_refuses_a_taken_number_a_bad_name_and_an_existing_file(self):
        rc, _, err = self.run_it("60", "again")
        self.assertEqual(rc, 2)
        self.assertIn("already in research/trials.csv", err)
        rc, _, err = self.run_it("61", "Bad-Name")
        self.assertEqual(rc, 2)
        (self.root / "espero" / "taken.py").write_text("")
        rc, _, err = self.run_it("61", "taken")
        self.assertEqual(rc, 2)
        self.assertIn("exists; nothing written", err)
        self.assertFalse((self.root / "research" / "PREREGISTRATION_TAKEN.md").exists())


if __name__ == "__main__":
    unittest.main()
