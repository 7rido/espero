"""Every module sits in exactly one layer, and the README's layout block is what the table renders."""
from __future__ import annotations

import contextlib
import io
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from espero import layers


class TestThePackage(unittest.TestCase):
    def test_every_module_claimed_once_and_every_claim_exists(self):
        self.assertEqual(layers.problems(), [])

    def test_the_readme_block_is_current(self):
        self.assertEqual(layers.block(), layers.render(), "run python -m espero.layers")

    def test_check_mode_passes_here(self):
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(layers.main(["--check"]), 0)


class TestOnAMadeUpPackage(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.pkg = Path(self.tmp.name) / "pkg"
        self.pkg.mkdir()
        (self.pkg / "a.py").write_text('"""Rule A: the first line.\n\nMore."""\n')
        (self.pkg / "b.py").write_text("x = 1\n")
        self.readme = Path(self.tmp.name) / "README.md"
        self.readme.write_text(f"# t\n\n{layers.START}\nold\n{layers.END}\n\nafter\n")

    def tearDown(self):
        self.tmp.cleanup()

    def test_render_uses_the_first_docstring_line_and_write_replaces_only_the_block(self):
        with mock.patch.object(layers, "LAYERS", {"rules": ("r", ["a"]), "operate": ("o", ["b"])}):
            self.assertEqual(layers.problems(self.pkg), [])
            text = layers.render(self.pkg)
            self.assertIn("    a.py              # Rule A: the first line.", text)
            self.assertIn("    b.py\n", text + "\n")
            layers.write(self.readme, self.pkg)
            out = self.readme.read_text()
            self.assertTrue(out.startswith("# t\n\n"))
            self.assertTrue(out.endswith("\n\nafter\n"))
            self.assertEqual(layers.block(self.readme), text)

    def test_an_orphan_a_double_claim_and_a_ghost_are_reported(self):
        with mock.patch.object(layers, "LAYERS", {"rules": ("r", ["a", "c"]), "operate": ("o", ["a"])}):
            p = layers.problems(self.pkg)
            self.assertIn("unclaimed: espero/b.py (add it to a layer in espero/layers.py)", p)
            self.assertTrue(any(x.startswith("claimed twice: a") for x in p), p)
            self.assertIn("rules lists c, which does not exist", p)


if __name__ == "__main__":
    unittest.main()
