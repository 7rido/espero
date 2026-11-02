"""The launchd agents render to valid plists that run what the docs say they run."""
from __future__ import annotations

import plistlib
import re
import shutil
import subprocess
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


@unittest.skipUnless(shutil.which("bash") and shutil.which("sed"), "needs bash and sed")
class TestCarryAgents(unittest.TestCase):
    def render(self):
        out = subprocess.run(["bash", str(ROOT / "scripts" / "install-carry-launchd.sh"), "--print"],
                             capture_output=True, text=True, check=True,
                             env={"PATH": "/usr/bin:/bin", "HOME": "/tmp", "PYTHON": "/x/python"}).stdout
        docs = re.findall(r"<\?xml.*?</plist>", out, re.S)
        return {p["Label"]: p for p in (plistlib.loads(d.encode()) for d in docs)}

    def test_two_books_kept_alive_from_the_repo(self):
        agents = self.render()
        self.assertEqual(sorted(agents), ["com.espero.carry-maker", "com.espero.carry-taker"])
        for label, p in agents.items():
            costs = label.rsplit("-", 1)[1]
            args = p["ProgramArguments"]
            self.assertEqual(args[:5], ["/x/python", "-m", "espero", "carry", "paper"])
            self.assertEqual(args[args.index("--costs") + 1], costs)
            self.assertEqual(args[args.index("--state") + 1], str(ROOT / "state" / f"carry-{costs}.db"))
            self.assertIn("--loop", args)
            self.assertEqual(p["WorkingDirectory"], str(ROOT))          # where .env is read
            self.assertTrue(p["KeepAlive"] and p["RunAtLoad"])
            self.assertTrue(p["StandardOutPath"].endswith(f"carry-{costs}.log"))

    def test_only_the_maker_book_trades_on_testnet(self):
        agents = self.render()
        self.assertIn("--execute-testnet", agents["com.espero.carry-maker"]["ProgramArguments"])
        self.assertNotIn("--execute-testnet", agents["com.espero.carry-taker"]["ProgramArguments"])


@unittest.skipUnless(shutil.which("bash") and shutil.which("sed"), "needs bash and sed")
class TestCollectorAgent(unittest.TestCase):
    def test_kept_alive_reading_public_data_into_the_repo(self):
        out = subprocess.run(["bash", str(ROOT / "scripts" / "install-hlcollect-launchd.sh"), "--print"],
                             capture_output=True, text=True, check=True,
                             env={"PATH": "/usr/bin:/bin", "HOME": "/tmp", "PYTHON": "/x/python"}).stdout
        p = plistlib.loads(out.encode())
        self.assertEqual(p["Label"], "com.espero.hlcollect")
        self.assertEqual(p["ProgramArguments"], ["/x/python", "-m", "espero", "hlcollect", "--loop", "--data",
                                                 str(ROOT / "data" / "hlcollect")])
        self.assertEqual(p["WorkingDirectory"], str(ROOT))
        self.assertTrue(p["KeepAlive"] and p["RunAtLoad"])
        self.assertTrue(p["StandardOutPath"].endswith("hlcollect.log"))


@unittest.skipUnless(shutil.which("bash") and shutil.which("sed"), "needs bash and sed")
class TestHlpAgent(unittest.TestCase):
    def test_kept_alive_with_its_own_journal_and_no_testnet(self):
        out = subprocess.run(["bash", str(ROOT / "scripts" / "install-hlp-launchd.sh"), "--print"],
                             capture_output=True, text=True, check=True,
                             env={"PATH": "/usr/bin:/bin", "HOME": "/tmp", "PYTHON": "/x/python"}).stdout
        p = plistlib.loads(out.encode())
        self.assertEqual(p["Label"], "com.espero.hlp")
        self.assertEqual(p["ProgramArguments"], ["/x/python", "-m", "espero", "hlp", "--loop", "--state",
                                                 str(ROOT / "state" / "hlp-book.db")])
        self.assertEqual(p["WorkingDirectory"], str(ROOT))
        self.assertTrue(p["KeepAlive"] and p["RunAtLoad"])
        self.assertTrue(p["StandardOutPath"].endswith("hlp.log"))


@unittest.skipUnless(shutil.which("bash") and shutil.which("sed"), "needs bash and sed")
class TestHlp2Agent(unittest.TestCase):
    def test_runs_59_in_its_own_journal(self):
        out = subprocess.run(["bash", str(ROOT / "scripts" / "install-hlp2-launchd.sh"), "--print"],
                             capture_output=True, text=True, check=True,
                             env={"PATH": "/usr/bin:/bin", "HOME": "/tmp", "PYTHON": "/x/python"}).stdout
        p = plistlib.loads(out.encode())
        self.assertEqual(p["Label"], "com.espero.hlp2")
        self.assertEqual(p["ProgramArguments"], ["/x/python", "-m", "espero", "hlp", "--test", "59", "--loop",
                                                 "--state", str(ROOT / "state" / "hlp2-book.db")])
        self.assertEqual(p["WorkingDirectory"], str(ROOT))
        self.assertTrue(p["KeepAlive"] and p["RunAtLoad"])
        self.assertTrue(p["StandardOutPath"].endswith("hlp2.log"))


@unittest.skipUnless(shutil.which("bash") and shutil.which("sed"), "needs bash and sed")
class TestPaperAgent(unittest.TestCase):
    def test_kept_alive_on_hyperliquid_with_its_journal_in_the_repo(self):
        out = subprocess.run(["bash", str(ROOT / "scripts" / "install-paper-launchd.sh"), "--print"],
                             capture_output=True, text=True, check=True,
                             env={"PATH": "/usr/bin:/bin", "HOME": "/tmp", "PYTHON": "/x/python"}).stdout
        p = plistlib.loads(out.encode())
        self.assertEqual(p["Label"], "com.espero.paper")
        self.assertEqual(p["ProgramArguments"], ["/x/python", "-m", "espero", "paper", "--product", "BTC-USD",
                                                 "--source", "hyperliquid", "--state",
                                                 str(ROOT / "state" / "paper-btc-usd-hl.db"), "--loop"])
        self.assertEqual(p["WorkingDirectory"], str(ROOT))
        self.assertTrue(p["KeepAlive"] and p["RunAtLoad"])
        self.assertTrue(p["StandardOutPath"].endswith("paper.log"))


if __name__ == "__main__":
    unittest.main(verbosity=2)
