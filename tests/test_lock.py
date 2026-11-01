"""A second writer on the same journal must be refused, and the lock must not
outlive its owner."""
from __future__ import annotations

import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from espero.lock import JournalBusy, JournalLock


class TestJournalLock(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = Path(self.tmp.name) / "paper.db"

    def tearDown(self):
        self.tmp.cleanup()

    def test_second_holder_is_refused(self):
        with JournalLock(self.db):
            with self.assertRaises(JournalBusy):
                with JournalLock(self.db):
                    pass

    def test_released_on_exit(self):
        with JournalLock(self.db):
            pass
        with JournalLock(self.db):
            pass

    def test_different_journals_do_not_block(self):
        with JournalLock(self.db):
            with JournalLock(Path(self.tmp.name) / "other.db"):
                pass

    def test_other_process_is_refused_and_named(self):
        with JournalLock(self.db):
            code = ("import sys\nfrom espero.lock import JournalLock, JournalBusy\n"
                    "try:\n    JournalLock(sys.argv[1]).__enter__()\n"
                    "except JournalBusy as e:\n    print(e); sys.exit(3)\n")
            r = subprocess.run([sys.executable, "-c", code, str(self.db)],
                               capture_output=True, text=True)
        self.assertEqual(r.returncode, 3, r.stderr)
        self.assertIn("already running", r.stdout)

    def test_a_dead_owner_leaves_no_stale_lock(self):
        code = ("import sys, os\nfrom espero.lock import JournalLock\n"
                "JournalLock(sys.argv[1]).__enter__()\nos._exit(0)\n")
        subprocess.run([sys.executable, "-c", code, str(self.db)], check=True)
        self.assertTrue(Path(str(self.db) + ".lock").exists())   # file left behind...
        with JournalLock(self.db):                                 # ...but not the lock
            pass

    def test_a_journal_in_a_folder_that_does_not_exist_yet(self):
        with tempfile.TemporaryDirectory() as t:
            db = Path(t) / "paper-books" / "p.db"
            with JournalLock(db):
                self.assertTrue(db.parent.is_dir())


if __name__ == "__main__":
    unittest.main(verbosity=2)
