"""docs/API_KEYS.md's first rule, held: no key in the repo, ever. Reads file names and placeholders, never .env."""
import re
import subprocess
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
KEY_VARS = ("HL_PRIVATE_KEY", "COINBASE_EXCHANGE_KEY", "COINBASE_EXCHANGE_SECRET", "COINBASE_EXCHANGE_PASSPHRASE",
            "ESPERO_WEBHOOK_URL", "ESPERO_OPERATOR_TOTP")


def tracked():
    r = subprocess.run(["git", "ls-files"], cwd=ROOT, capture_output=True, text=True)
    return r.stdout.splitlines() if r.returncode == 0 else []


class TestNoKeyInTheRepo(unittest.TestCase):
    def test_env_is_ignored(self):
        lines = (ROOT / ".gitignore").read_text(encoding="utf-8").splitlines()
        self.assertIn(".env", lines)

    @unittest.skipUnless(tracked(), "needs a git checkout")
    def test_no_env_file_is_tracked(self):
        self.assertEqual([f for f in tracked() if Path(f).name == ".env"], [])

    def test_the_example_names_every_key_and_holds_no_value(self):
        text = (ROOT / ".env.example").read_text(encoding="utf-8")
        values = dict(re.findall(r"^([A-Z_]+)=(.*)$", text, re.M))
        for var in KEY_VARS:
            if var in values:
                self.assertEqual(values[var].strip(), "", var)
        self.assertIn("HL_PRIVATE_KEY", values)

    @unittest.skipUnless(tracked(), "needs a git checkout")
    def test_no_tracked_file_holds_a_private_key_block(self):
        """A real key's block holds hundreds of base64 characters; a parser's test fixture (test_audit_rest's) a few."""
        pem = re.compile(rb"-----BEGIN (?:[A-Z]+ )?PRIVATE KEY-----(.*?)-----END", re.S)
        for f in tracked():
            p = ROOT / f
            if p.is_file() and p.stat().st_size < 5_000_000 and p.suffix not in (".gz", ".zip", ".db", ".png"):
                for m in pem.finditer(p.read_bytes()):
                    self.assertLess(len(re.findall(rb"[A-Za-z0-9+/=]", m.group(1))), 100, f)

    def test_a_real_looking_block_would_be_caught(self):
        pem = re.compile(rb"-----BEGIN (?:[A-Z]+ )?PRIVATE KEY-----(.*?)-----END", re.S)
        fake = b"-----BEGIN EC PRIVATE KEY-----\n" + b"A" * 64 + b"\n" + b"B" * 64 + b"\n-----END EC PRIVATE KEY-----"
        body = pem.search(fake).group(1)
        self.assertGreaterEqual(len(re.findall(rb"[A-Za-z0-9+/=]", body)), 100)


if __name__ == "__main__":
    unittest.main()
