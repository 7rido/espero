"""No mainnet order path: only espero/hl_exchange.py may build the signing SDK, and it stays testnet-only.

research/DESIGN_MAINNET_PATH.md is a design, not code; this holds it there until the account holder lifts the rule
in writing. Reading mainnet's public data (hyperliquid.py, rawrec.py) is not signing, and is allowed.
"""
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SIGNER = ROOT / "espero" / "hl_exchange.py"
SDK = r"(hyperliquid\.exchange|eth_account)\b"
SIGNING = re.compile(rf"^\s*(from\s+{SDK}|import\s+{SDK})|\bExchange\(\s*wallet", re.M)


def sources():
    for folder in ("espero", "research", "scripts"):
        yield from sorted((ROOT / folder).rglob("*.py"))


class TestNoMainnetPath(unittest.TestCase):
    def test_only_the_testnet_module_builds_a_signer(self):
        offenders = [str(p.relative_to(ROOT)) for p in sources()
                     if p != SIGNER and SIGNING.search(p.read_text(encoding="utf-8", errors="replace"))]
        self.assertEqual(offenders, [])

    def test_the_signer_is_built_on_the_testnet_constant_only(self):
        text = SIGNER.read_text(encoding="utf-8")
        self.assertIn('TESTNET_URL = "https://api.hyperliquid-testnet.xyz"', text)
        self.assertNotIn("api.hyperliquid.xyz", text)
        self.assertEqual(re.findall(r"base_url=([A-Za-z_]+)", text), ["TESTNET_URL", "TESTNET_URL"])
        self.assertIn('if network != "testnet":', text)

    def test_the_guard_refuses_mainnet(self):
        from espero import hl_exchange
        with self.assertRaises(hl_exchange.TestnetRefused):
            hl_exchange.guard({"HL_NETWORK": "mainnet", "ESPERO_ALLOW_HL_TESTNET": "1", "HL_PRIVATE_KEY": "x"})

    def test_no_mainnet_names_exist_in_code(self):
        for p in sources():
            text = p.read_text(encoding="utf-8", errors="replace")
            for name in ("MainnetExchange", "MainnetRefused", "ESPERO_ALLOW_HL_MAINNET", "HL_MAINNET_PRIVATE_KEY"):
                self.assertNotIn(name, text, f"{p.relative_to(ROOT)} names {name}")

    def test_the_design_says_it_is_one(self):
        text = (ROOT / "research" / "DESIGN_MAINNET_PATH.md").read_text(encoding="utf-8")
        self.assertIn("This is a design document. There is no mainnet order path in this repo", text)

    def test_the_pattern_would_catch_a_signer(self):
        self.assertTrue(SIGNING.search("from hyperliquid.exchange import Exchange\n"))
        self.assertTrue(SIGNING.search("import eth_account\n"))
        self.assertTrue(SIGNING.search("x = Exchange(wallet, base_url=URL)\n"))
        self.assertIsNone(SIGNING.search("MAINNET_URL = 'https://api.hyperliquid.xyz'\n"))


if __name__ == "__main__":
    unittest.main()
