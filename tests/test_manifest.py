"""The manifest lists every recorded file, and a check tells a missing file from a changed one."""
from __future__ import annotations

import hashlib
import re
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from espero import manifest

ROOT = Path(__file__).resolve().parents[1]
UNRECOVERABLE = ["data/hlcollect", "data/hlbook", "data/book", "data/aggr/forward", "data/aggr/forward5m"]


class TestWrite(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.folder = Path(self.tmp.name)
        (self.folder / "b.csv").write_text("2\n")
        (self.folder / "sub").mkdir()
        (self.folder / "sub" / "a.json").write_bytes(b"{}")

    def tearDown(self):
        self.tmp.cleanup()

    def test_every_file_listed_once_sorted_in_shasum_format(self):
        path = manifest.write(self.folder)
        lines = path.read_text().splitlines()
        self.assertEqual(len(lines), 2)
        for line in lines:
            self.assertRegex(line, r"^[0-9a-f]{64}  \S+$")
        self.assertEqual([ln.split("  ")[1] for ln in lines], ["b.csv", "sub/a.json"])
        self.assertEqual(lines[0].split("  ")[0], hashlib.sha256(b"2\n").hexdigest())

    def test_manifest_leaves_itself_out_and_rewrites_the_same(self):
        first = manifest.write(self.folder).read_text()
        second = manifest.write(self.folder).read_text()
        self.assertEqual(first, second)
        self.assertNotIn(manifest.NAME, first)


class TestCheck(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.folder = Path(self.tmp.name)
        (self.folder / "day1.csv").write_text("1\n")
        (self.folder / "day2.csv").write_text("2\n")
        manifest.write(self.folder)

    def tearDown(self):
        self.tmp.cleanup()

    def test_untouched_folder_is_all_ok(self):
        self.assertEqual(manifest.check(self.folder),
                         {"ok": 2, "missing": [], "differs": [], "extra": []})

    def test_missing_changed_and_extra_are_told_apart(self):
        (self.folder / "day1.csv").unlink()
        (self.folder / "day2.csv").write_text("2 changed\n")
        (self.folder / "day3.csv").write_text("3\n")
        r = manifest.check(self.folder)
        self.assertEqual(r, {"ok": 0, "missing": ["day1.csv"], "differs": ["day2.csv"], "extra": ["day3.csv"]})

    def test_main_fails_only_on_a_missing_file(self):
        self.assertEqual(manifest.main(["check", str(self.folder)]), 0)
        (self.folder / "day2.csv").write_text("changed\n")
        self.assertEqual(manifest.main(["check", str(self.folder)]), 0)
        (self.folder / "day1.csv").unlink()
        self.assertEqual(manifest.main(["check", str(self.folder)]), 1)

    def test_main_refuses_a_folder_without_a_manifest(self):
        (self.folder / manifest.NAME).unlink()
        self.assertEqual(manifest.main(["check", str(self.folder)]), 1)


class TestProvenance(unittest.TestCase):
    """Every folder that can't be recorded again is ignored by git, published, and manifested."""

    def test_gitignore_lists_every_unrecoverable_folder(self):
        ignored = (ROOT / ".gitignore").read_text()
        for folder in UNRECOVERABLE:
            self.assertIn(f"{folder}/", ignored, folder)

    def test_publish_script_tars_and_manifests_every_unrecoverable_folder(self):
        script = (ROOT / "scripts" / "publish-data.sh").read_text()
        paths = re.search(r"^PATHS=\((.*?)\)", script, re.M).group(1).split()
        for folder in UNRECOVERABLE:
            self.assertIn(folder, paths, folder)
        self.assertIn("espero.manifest write", script)

    @unittest.skipUnless(shutil.which("bash") and shutil.which("tar"), "needs bash and tar")
    def test_fetch_script_refuses_a_release_with_a_file_outside_the_live_folders(self):
        """A release is integrity-checked against its own sha256, never authenticated: a member outside data/'s
        live folders (a .pth under .venv/ would run on the next python start) refuses the whole archive."""
        script = ROOT / "scripts" / "fetch-data.sh"
        with tempfile.TemporaryDirectory() as d:
            src = Path(d) / "src"
            (src / "data" / "hlbook").mkdir(parents=True)
            (src / "data" / "hlbook" / "a.csv").write_text("x")
            good = Path(d) / "good.tar.gz"
            subprocess.run(["tar", "-czf", str(good), "-C", str(src), "data"], check=True)
            (src / ".venv" / "lib").mkdir(parents=True)
            (src / ".venv" / "lib" / "evil.pth").write_text("import os")
            evil = Path(d) / "evil.tar.gz"
            subprocess.run(["tar", "-czf", str(evil), "-C", str(src), "data", ".venv"], check=True)
            (src / "data" / "cache").mkdir()
            (src / "data" / "cache" / "x.csv").write_text("x")
            stray = Path(d) / "stray.tar.gz"
            subprocess.run(["tar", "-czf", str(stray), "-C", str(src), "data"], check=True)
            env = {"PATH": "/usr/bin:/bin", "HOME": d}
            ok = subprocess.run(["bash", str(script), "check-archive", str(good)], capture_output=True, text=True,
                                env=env)
            self.assertEqual(ok.returncode, 0, ok.stderr)
            for bad in (evil, stray):
                r = subprocess.run(["bash", str(script), "check-archive", str(bad)], capture_output=True,
                                   text=True, env=env)
                self.assertEqual(r.returncode, 1, bad.name)
                self.assertIn("outside the live folders", r.stderr)
        self.assertNotIn("2>/dev/null || true", script.read_text())      # a tar error is shown, not hidden

    def test_fetch_script_checks_the_manifests(self):
        script = (ROOT / "scripts" / "fetch-data.sh").read_text()
        self.assertIn("espero.manifest check", script)
        for folder in UNRECOVERABLE:
            self.assertIn(folder, script, folder)


if __name__ == "__main__":
    unittest.main()
