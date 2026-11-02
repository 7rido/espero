"""scripts/move-state.sh moves the root's state into state/ once, and refuses when it isn't safe."""
from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "move-state.sh"
STATE = ["tsmom.db", "tsmom.db-wal", "xs.db", "carry-maker.db.lock", "liqhold_trades.csv", "health.json",
         "dashboard.html", "KILL"]


@unittest.skipUnless(shutil.which("bash"), "needs bash")
class TestMoveState(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.repo = Path(self.tmp.name)
        for name in STATE + ["features.db", "pyproject.toml"]:
            (self.repo / name).write_text(name)
        (self.repo / "paper-books").mkdir()
        (self.repo / "paper-books" / "paper-eth-usd.db").write_text("book")

    def tearDown(self):
        self.tmp.cleanup()

    def run_script(self, *flags, **env):
        full = {"PATH": os.environ["PATH"], "HOME": self.tmp.name, "REPO": str(self.repo),
                "LAUNCHCTL": "/usr/bin/false", **env}
        return subprocess.run(["bash", str(SCRIPT), *flags], capture_output=True, text=True, env=full)

    def test_dry_run_lists_the_state_and_moves_nothing(self):
        r = self.run_script()
        self.assertEqual(r.returncode, 0, r.stderr)
        for name in STATE + ["paper-books"]:
            self.assertIn(f"  {name}\n", r.stdout)
            self.assertTrue((self.repo / name).exists(), name)
        self.assertNotIn("features.db", r.stdout)
        self.assertIn("dry run", r.stdout)
        self.assertFalse((self.repo / "state").exists())

    def test_apply_moves_everything_but_the_fixture(self):
        r = self.run_script("--apply")
        self.assertEqual(r.returncode, 0, r.stderr)
        for name in STATE:
            self.assertFalse((self.repo / name).exists(), name)
            self.assertEqual((self.repo / "state" / name).read_text(), name)
        self.assertEqual((self.repo / "state" / "paper-books" / "paper-eth-usd.db").read_text(), "book")
        self.assertTrue((self.repo / "features.db").exists())
        self.assertTrue((self.repo / "pyproject.toml").exists())

    def test_apply_honours_state_dir(self):
        r = self.run_script("--apply", ESPERO_STATE_DIR=str(self.repo / "elsewhere"))
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertTrue((self.repo / "elsewhere" / "tsmom.db").exists())

    def test_apply_refuses_a_loaded_writer(self):
        r = self.run_script("--apply", LAUNCHCTL="/usr/bin/true")
        self.assertEqual(r.returncode, 1)
        self.assertIn("loaded in launchd", r.stderr)
        self.assertTrue((self.repo / "tsmom.db").exists())

    def test_apply_refuses_to_overwrite(self):
        (self.repo / "state").mkdir()
        (self.repo / "state" / "xs.db").write_text("older")
        r = self.run_script("--apply")
        self.assertEqual(r.returncode, 1)
        self.assertIn("already exists", r.stderr)
        self.assertTrue((self.repo / "tsmom.db").exists())
        self.assertEqual((self.repo / "state" / "xs.db").read_text(), "older")

    def test_nothing_to_move_is_not_an_error(self):
        for name in STATE:
            (self.repo / name).unlink()
        shutil.rmtree(self.repo / "paper-books")
        r = self.run_script("--apply")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("nothing to move", r.stdout)


@unittest.skipUnless(shutil.which("bash") and shutil.which("sed"), "needs bash and sed")
class TestInstallersRefuseABookLeftInTheRoot(unittest.TestCase):
    """Reinstalling a loop before the move would start a fresh book and abandon the old one."""

    BOOKS = {"install-launchd.sh": "tsmom.db", "install-carry-launchd.sh": "carry-maker.db",
             "install-hlp-launchd.sh": "hlp-book.db", "install-hlp2-launchd.sh": "hlp2-book.db",
             "install-hlp2-testnet-launchd.sh": "hlp2-testnet.db",
             "install-paper-launchd.sh": "paper-btc-usd-hl.db"}

    def test_each_installer_stops_before_touching_launchd(self):
        import sys
        for script, book in self.BOOKS.items():
            with self.subTest(script=script), tempfile.TemporaryDirectory() as t:
                repo = Path(t)
                shutil.copytree(ROOT / "deploy", repo / "deploy")
                (repo / book).write_text("the book")
                # LAUNCHCTL=false: a regression here must never reach the machine's real launchd
                env = {"PATH": os.environ["PATH"], "HOME": t, "REPO": t, "PYTHON": sys.executable,
                       "STATE_DIR": str(repo / "state"), "LAUNCHCTL": "/usr/bin/false"}
                r = subprocess.run(["bash", str(ROOT / "scripts" / script)], capture_output=True, text=True, env=env)
                self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
                self.assertIn("move-state.sh first", r.stderr)
                self.assertFalse((repo / "Library").exists())      # no plist written under HOME


if __name__ == "__main__":
    unittest.main()
