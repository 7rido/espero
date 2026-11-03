"""Only two modules may build the signing SDK: espero/hl_exchange.py, testnet-only, and espero/hl_mainnet.py, which may
exist only while the account holder's signed lift of the no-mainnet rule stands (research/DESIGN_MAINNET_PATH.md).

The holder lifted the rule in research/MAINNET_LIFT.md (cf109df, 88cd069). If the holder page stops naming a lift, or
the lift leaves HEAD, or its last commit carries no signature, this file fails while hl_mainnet.py exists. The full
`git verify-commit` against the holder's allowed signers runs in the module itself, every time it is built: CI has no
allowed-signers file and a shallow clone has no history, so here only the signature's presence is checked, and only
when the clone has the history. Reading mainnet's public data (hyperliquid.py, rawrec.py) is not signing.
"""
import re
import subprocess
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SIGNER = ROOT / "espero" / "hl_exchange.py"
MAINNET = ROOT / "espero" / "hl_mainnet.py"
MAINNET_NAMES = ("MainnetExchange", "MainnetRefused", "ESPERO_ALLOW_HL_MAINNET", "HL_MAINNET_PRIVATE_KEY")


def git(*args):
    return subprocess.run(["git", "-C", str(ROOT), *args], capture_output=True, text=True)


def lift_named_at_head():
    """The lift's path when HEAD's holder page names one and HEAD holds that file, else None."""
    page = git("show", "HEAD:docs/HOLDER_INPUTS.md")
    if page.returncode != 0:
        return None
    m = re.search(r"^\|\s*`mainnet_lift`\s*\|[^|]*\|([^|]*)\|", page.stdout, re.M)
    rel = m.group(1).strip().strip("`") if m else ""
    return rel if rel and git("cat-file", "-e", f"HEAD:{rel}").returncode == 0 else None
SDK = r"(hyperliquid\.exchange|eth_account)\b"
SIGNING = re.compile(
    rf"^\s*(from\s+{SDK}|import\s+{SDK})"                           # the SDK's signer or the account library
    rf"|^\s*from\s+hyperliquid\s+import\b[^\n]*\bexchange\b"        # the signer's module by its short name
    rf"|\b(import_module|__import__)\(\s*['\"](hyperliquid|eth_account)"  # imported by name at run time
    r"|\bExchange\(",                                                  # the signer built, whatever it is called
    re.M)


def sources():
    for folder in ("espero", "research", "scripts"):
        yield from sorted((ROOT / folder).rglob("*.py"))


class TestNoMainnetPath(unittest.TestCase):
    def test_only_the_two_order_modules_build_a_signer(self):
        offenders = [str(p.relative_to(ROOT)) for p in sources()
                     if p not in (SIGNER, MAINNET) and SIGNING.search(p.read_text(encoding="utf-8", errors="replace"))]
        self.assertEqual(offenders, [])

    def test_the_mainnet_module_exists_only_under_the_holders_signed_lift(self):
        if not MAINNET.exists():
            return
        rel = lift_named_at_head()
        self.assertIsNotNone(rel, "hl_mainnet.py exists but HEAD's holder page names no lift that HEAD holds")
        if git("rev-parse", "--is-shallow-repository").stdout.strip() == "true":
            return                                     # a shallow clone (CI) has no history to read a signature from
        commit = git("log", "-1", "--format=%H", "--", rel).stdout.strip()
        body = git("cat-file", "commit", commit).stdout
        self.assertIn("-----BEGIN SSH SIGNATURE-----", body, f"the lift's last commit {commit[:12]} is not signed")

    def test_the_mainnet_module_is_built_on_the_mainnet_constant_only(self):
        if not MAINNET.exists():
            return
        text = MAINNET.read_text(encoding="utf-8")
        self.assertIn('MAINNET_URL = "https://api.hyperliquid.xyz"', text)
        self.assertNotIn("hyperliquid-testnet", text)
        self.assertEqual(re.findall(r"base_url=([A-Za-z_]+)", text), ["MAINNET_URL", "MAINNET_URL"])
        for guard in ('!= "mainnet"', '"ESPERO_ALLOW_HL_MAINNET"', "read_lift(", "read_allowlist(", "verify-commit",
                      'env.get("CI")', "dry_run: bool = True"):
            self.assertIn(guard, text, guard)

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

    def test_mainnet_names_exist_only_in_the_mainnet_module(self):
        for p in sources():
            if p == MAINNET:
                continue
            text = p.read_text(encoding="utf-8", errors="replace")
            for name in MAINNET_NAMES:
                self.assertNotIn(name, text, f"{p.relative_to(ROOT)} names {name}")

    def test_the_design_says_what_it_was_and_what_lifted_it(self):
        text = (ROOT / "research" / "DESIGN_MAINNET_PATH.md").read_text(encoding="utf-8")
        self.assertIn("This was a design document", text)
        self.assertIn("research/MAINNET_LIFT.md", text)

    def test_the_pattern_would_catch_a_signer(self):
        for spelling in ("from hyperliquid.exchange import Exchange\n", "import eth_account\n",
                         "x = Exchange(wallet, base_url=URL)\n", "ex = exchange.Exchange(acct, base_url=U)\n",
                         "from hyperliquid import exchange\n", "from hyperliquid import info, exchange as ex\n",
                         "import hyperliquid.exchange as hx\n", "m = importlib.import_module('hyperliquid.exchange')\n",
                         'm = __import__("hyperliquid.exchange")\n', "__import__('eth_account')\n",
                         "from eth_account.signers.local import LocalAccount\n"):
            self.assertTrue(SIGNING.search(spelling), spelling)
        for innocent in ("MAINNET_URL = 'https://api.hyperliquid.xyz'\n", "from hyperliquid import info\n",
                         "ex = TestnetExchange(env)\n", "from . import hyperliquid as hl\n",
                         '__import__("espero.cash", fromlist=["x"])\n', "class FakeExchange:\n"):
            self.assertIsNone(SIGNING.search(innocent), innocent)


if __name__ == "__main__":
    unittest.main()
