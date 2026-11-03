"""The mainnet order path's guards, each refusing on its own (research/DESIGN_MAINNET_PATH.md).

Every test builds a throwaway git repository signed with a throwaway SSH key, whose allowed-signers file sits outside
it, and never touches the holder's key, the real lift or the network.
"""
import json
import shutil
import subprocess
import tempfile
import unittest
from datetime import date
from pathlib import Path

from espero import hl_mainnet as M
from espero import holderform as F
from espero import risk

TODAY = date(2026, 11, 3)
MACHINE = "2fe1955570d2c740"
FIELDS = {"venue": "hyperliquid", "coins": "BTC, ETH, SOL, ETC, NEAR, BCH", "max_order_usd": "30",
          "max_position_usd": "50", "expiry": "2027-01-31", "rule": "8", "approval": "me", "machine": MACHINE}
STATEMENT = "I lift the no-mainnet rule for a plumbing canary on rule 8, Hyperliquid only, every trade mine."
ENV = {"HL_NETWORK": "mainnet", "ESPERO_ALLOW_HL_MAINNET": "1"}
ROWS = [{"venue": "hyperliquid", "coin": c, "max_order_usd": 30, "max_position_usd": 50}
        for c in ("BTC", "ETH", "SOL", "ETC", "NEAR", "BCH")]
HAVE_SSH_KEYGEN = shutil.which("ssh-keygen") is not None


def ruling(notional=30.0, allowed=True, policy_hash=None):
    return risk.Ruling(allowed, notional, () if allowed else ("a reason",), {}, policy_hash or risk.policy_hash())


def blank_page() -> str:
    text = subprocess.run(["git", "-C", str(M.ROOT), "show", "HEAD:docs/HOLDER_INPUTS.md"], capture_output=True,
                          text=True, check=True).stdout
    out = []
    for line in text.split("\n"):
        if line.startswith("| `") and line.count("|") == 5:
            cells = line.split("|")
            cells[3] = " "
            line = "|".join(cells)
        out.append(line)
    return "\n".join(out)


class Repo:
    """A git repository with the holder page, a lift and an allow-list, each committable signed or not."""

    def __init__(self):
        self.base = Path(tempfile.mkdtemp())
        self.root = self.base / "repo"
        self.root.mkdir()
        self.keys = self.base / "keys"
        self.keys.mkdir()
        for name in ("holder", "stranger"):
            subprocess.run(["ssh-keygen", "-q", "-t", "ed25519", "-N", "", "-C", name, "-f", str(self.keys / name)],
                           check=True)
        self.signers = self.base / "allowed_signers"
        self.signers.write_text(f"holder {(self.keys / 'holder.pub').read_text()}")
        self.git("init", "-q")
        for k, v in (("user.name", "t"), ("user.email", "t@t"), ("gpg.format", "ssh"), ("commit.gpgsign", "false"),
                     ("user.signingkey", str(self.keys / "holder.pub")),
                     ("gpg.ssh.allowedSignersFile", str(self.signers))):
            self.git("config", k, v)
        (self.root / "docs").mkdir()
        (self.root / "research").mkdir()
        (self.root / "config").mkdir()
        self.page({"mainnet_lift": "research/MAINNET_LIFT.md", "venue_loss_usd": "50", "stop_drawdown": "-3%",
                   "capital_usd": "50"})
        self.lift(FIELDS)
        self.allow(ROWS)
        self.commit("the holder's lift", sign=True)

    def git(self, *args, check=True):
        return subprocess.run(["git", "-C", str(self.root), *args], capture_output=True, text=True, check=check)

    def page(self, answers):
        (self.root / "docs" / "HOLDER_INPUTS.md").write_text(F.set_answers(blank_page(), answers))

    def lift(self, fields, statement=STATEMENT):
        (self.root / "research" / "MAINNET_LIFT.md").write_text(F.lift_document(statement, fields, TODAY))

    def allow(self, rows):
        (self.root / "config" / "mainnet_allowlist.json").write_text(json.dumps({"rows": rows}, indent=1))

    def commit(self, msg, sign=True, key="holder"):
        self.git("add", "-A")
        args = ["-c", f"user.signingkey={self.keys / (key + '.pub')}", "commit", "-q", "-m", msg]
        if sign:
            args.insert(-3, "-S")
        self.git(*args)

    def exchange(self, env=None, **kw):
        kw.setdefault("today", TODAY)
        kw.setdefault("machine", MACHINE)
        kw.setdefault("state", self.base / "state")
        return M.MainnetExchange(env=dict(ENV) if env is None else env, root=self.root, **kw)


@unittest.skipUnless(HAVE_SSH_KEYGEN, "needs ssh-keygen")
class TestTheGuardsInOrder(unittest.TestCase):
    def setUp(self):
        self.r = Repo()

    def refused(self, needle, **kw):
        with self.assertRaises(M.MainnetRefused) as cm:
            self.r.exchange(**kw)
        self.assertIn(needle, str(cm.exception))

    def test_a_signed_lift_and_allow_list_build_a_dry_run(self):
        ex = self.r.exchange()
        self.assertTrue(ex.dry_run)
        self.assertEqual(ex.lift.coins, ("BTC", "ETH", "SOL", "ETC", "NEAR", "BCH"))
        self.assertEqual(ex.lift.commit, self.r.git("rev-parse", "HEAD").stdout.strip())
        self.assertEqual(set(ex.allowed), {"BTC", "ETH", "SOL", "ETC", "NEAR", "BCH"})
        self.assertIsNone(ex.venue)                                      # nothing built, nothing to sign with

    def test_guard_1_network(self):
        self.refused("HL_NETWORK", env={"ESPERO_ALLOW_HL_MAINNET": "1"})
        self.refused("HL_NETWORK", env={"HL_NETWORK": "testnet", "ESPERO_ALLOW_HL_MAINNET": "1"})

    def test_guard_2_the_second_opt_in(self):
        self.refused("ESPERO_ALLOW_HL_MAINNET", env={"HL_NETWORK": "mainnet"})
        self.refused("ESPERO_ALLOW_HL_MAINNET", env={"HL_NETWORK": "mainnet", "ESPERO_ALLOW_HL_TESTNET": "1"})

    def test_guard_3_an_unsigned_lift(self):
        self.r.lift(dict(FIELDS, max_order_usd="20"))
        self.r.commit("an unsigned change", sign=False)
        self.refused("does not verify")

    def test_guard_3_a_lift_signed_by_another_key(self):
        self.r.lift(dict(FIELDS, max_order_usd="20"))
        self.r.commit("signed by a stranger", sign=True, key="stranger")
        self.refused("does not verify")

    def test_guard_3_an_uncommitted_edit_counts_for_nothing(self):
        self.r.lift(dict(FIELDS, max_order_usd="20"))
        self.refused("uncommitted")

    def test_guard_3_the_holder_page_must_be_committed_and_name_the_lift(self):
        self.r.page({"venue_loss_usd": "50"})
        self.refused("HEAD holds")
        self.r.commit("no lift named", sign=True)
        self.refused("no lift")

    def test_guard_3_a_lapsed_lift(self):
        self.refused("lapsed", today=date(2027, 2, 1))
        self.assertTrue(self.r.exchange(today=date(2027, 1, 31)))       # the expiry day itself still counts

    def test_guard_3_another_machine(self):
        self.refused("machine", machine="0000000000000000")

    def test_guard_3_another_venue(self):
        self.r.lift(dict(FIELDS, venue="coinbase"))
        self.r.commit("coinbase", sign=True)
        self.refused("covers coinbase")

    def test_guard_3_the_allowed_signers_must_live_outside_the_repo(self):
        inside = self.r.root / "allowed_signers"
        inside.write_text(self.r.signers.read_text())
        self.r.git("config", "gpg.ssh.allowedSignersFile", str(inside))
        self.refused("does not verify")
        self.r.git("config", "--unset", "gpg.ssh.allowedSignersFile")
        self.refused("does not verify")

    def test_guard_4_the_allow_list_is_signed_and_committed(self):
        self.r.allow(ROWS[:1])
        self.refused("mainnet_allowlist.json is not at HEAD")
        self.r.commit("unsigned allow-list", sign=False)
        self.refused("mainnet_allowlist.json's commit")

    def test_guard_4_a_malformed_allow_list(self):
        self.r.allow([{"venue": "hyperliquid", "coin": "BTC", "max_order_usd": 60, "max_position_usd": 50}])
        self.r.commit("order above position", sign=True)
        self.refused("does not read")


@unittest.skipUnless(HAVE_SSH_KEYGEN, "needs ssh-keygen")
class TestEveryOrder(unittest.TestCase):
    def setUp(self):
        self.r = Repo()
        self.held = []
        self.ex = self.r.exchange(positions=lambda: {"positions": list(self.held)})

    def send(self, coin="BTC", side="buy", size=0.0002, price=60_000.0, reduce_only=False, rul="default"):
        return self.ex.limit(coin, side, size, price, reduce_only=reduce_only, sz_decimals=5,
                             ruling=ruling() if rul == "default" else rul)

    def test_a_good_order_is_journaled_as_dry_with_its_lift_and_policy(self):
        res = self.send()
        self.assertEqual(res.status, "dry")
        row = self.ex.db.execute("SELECT mode, coin, policy_hash, lift_commit, allow_commit, status "
                                 "FROM mainnet_orders").fetchone()
        self.assertEqual(row[:2], ("dry", "BTC"))
        self.assertEqual(row[2], risk.policy_hash())
        self.assertEqual(row[3], self.ex.lift.commit)
        self.assertEqual(row[4], self.ex.allow_commit)
        self.assertEqual(row[5], "dry")

    def test_coins_outside_the_lift_or_the_allow_list(self):
        self.assertIn("lift's coins", self.send(coin="DOGE", price=0.2, size=50).error)
        self.r.allow(ROWS[1:])
        self.r.commit("BTC off the allow-list", sign=True)
        ex = self.r.exchange(positions=lambda: {"positions": []})
        self.assertIn("allow-list", ex.limit("BTC", "buy", 0.0002, 60_000.0, sz_decimals=5, ruling=ruling()).error)

    def test_order_and_position_sizes(self):
        self.assertIn("largest order", self.send(size=0.0006).error)            # $36 > $30
        self.assertEqual(self.send(size=0.0005).status, "dry")                 # $30 exactly
        self.held.append({"coin": "BTC", "size": 0.0005, "notional": 30.0})
        self.assertIn("largest position", self.send(size=0.0004).error)        # 30 + 24 > 50

    def test_the_holders_venue_limit(self):
        self.held.extend([{"coin": "ETH", "size": 0.01, "notional": 25.0},
                          {"coin": "SOL", "size": 0.1, "notional": 20.0}])
        self.assertIn("venue_loss_usd", self.send(size=0.0001).error)          # 45 + 6 > 50
        self.assertEqual(self.send(size=0.00008).status, "dry")                # 45 + 4.8

    def test_the_ruling(self):
        self.assertIn("no ruling", self.send(rul=None).error)
        self.assertIn("refused", self.send(rul=ruling(allowed=False)).error)
        self.assertIn("different policy", self.send(rul=ruling(policy_hash="0" * 64)).error)
        self.assertIn("above the ruling", self.send(rul=ruling(notional=5.0)).error)

    def test_the_kill_switch_lets_only_reduce_only_through(self):
        (self.r.base / "state" / "KILL").write_text("")
        self.assertEqual(self.ex.kill_state(), "kill")
        self.assertIn("KILL", self.send().error)
        self.assertEqual(self.send(side="sell", reduce_only=True, rul=None).status, "dry")
        (self.r.base / "state" / "KILL").write_text("flatten\n")
        self.assertEqual(self.ex.kill_state(), "flatten")

    def test_reduce_only_passes_the_caps_but_not_a_bad_side_or_size(self):
        self.assertEqual(self.send(coin="DOGE", side="sell", size=1000, price=0.2, reduce_only=True,
                                   rul=None).status, "dry")
        self.assertIn("side", self.send(side="hold", reduce_only=True).error)
        self.assertIn("positive", self.send(size=float("nan"), reduce_only=True).error)

    def test_every_refusal_is_journaled(self):
        self.send(coin="DOGE", price=0.2, size=50)
        self.send(rul=None)
        rows = self.ex.db.execute("SELECT status FROM mainnet_orders").fetchall()
        self.assertEqual([r[0] for r in rows], ["refused", "refused"])


class FakeEx:
    base_url = M.MAINNET_URL

    def __init__(self):
        self.sent = []
        self.cancelled = []

    def order(self, coin, is_buy, sz, px, kind, reduce_only=False, **kw):
        self.sent.append((coin, is_buy, sz, px, kind["limit"]["tif"], reduce_only))
        return {"response": {"data": {"statuses": [{"filled": {"oid": len(self.sent), "totalSz": str(sz),
                                                               "avgPx": str(px)}}]}}}

    def cancel(self, coin, oid):
        self.cancelled.append((coin, oid))
        return {"status": "ok"}


class FakeInfo:
    def __init__(self, orders=()):
        self.orders = list(orders)

    def l2_snapshot(self, coin):
        return {"levels": [[{"px": "59990"}], [{"px": "60010"}]]}

    def open_orders(self, address):
        return list(self.orders)


@unittest.skipUnless(HAVE_SSH_KEYGEN, "needs ssh-keygen")
class TestLive(unittest.TestCase):
    def setUp(self):
        self.r = Repo()

    def test_live_sends_through_the_client_and_journals_the_fill(self):
        fx = FakeEx()
        ex = self.r.exchange(dry_run=False, exchange=fx, info=FakeInfo(), meta={"BTC": 5},
                             positions=lambda: {"positions": []})
        res = ex.limit("BTC", "buy", 0.0002, 60_000.0, tif="Ioc", ruling=ruling())
        self.assertEqual(res.status, "filled")
        self.assertEqual(fx.sent, [("BTC", True, 0.0002, 60000.0, "Ioc", False)])
        self.assertEqual(ex.db.execute("SELECT mode FROM mainnet_orders").fetchone()[0], "live")
        self.assertTrue((self.r.base / "state" / M.LIVE_DB).exists())

    def test_a_refused_order_never_reaches_the_client(self):
        fx = FakeEx()
        ex = self.r.exchange(dry_run=False, exchange=fx, info=FakeInfo(), meta={"BTC": 5},
                             positions=lambda: {"positions": []})
        ex.limit("BTC", "buy", 0.001, 60_000.0, ruling=ruling())                # $60 > $30
        self.assertEqual(fx.sent, [])

    def test_live_without_a_client_needs_the_key_and_refuses_under_ci(self):
        with self.assertRaises(M.MainnetRefused) as cm:
            self.r.exchange(env=dict(ENV, CI="true"), dry_run=False)
        self.assertIn("CI", str(cm.exception))
        with self.assertRaises(M.MainnetRefused) as cm:
            self.r.exchange(env=dict(ENV), dry_run=False)
        self.assertIn("HL_MAINNET_PRIVATE_KEY", str(cm.exception))
        with self.assertRaises(M.MainnetRefused) as cm:
            self.r.exchange(env=dict(ENV, HL_API_URL="https://api.hyperliquid-testnet.xyz",
                                     HL_MAINNET_PRIVATE_KEY="0x" + "1" * 64), dry_run=False)
        self.assertIn("HL_API_URL", str(cm.exception))

    def test_flatten_cancels_and_closes_with_reduce_only_ioc_crossing_further(self):
        fx = FakeEx()
        state = {"positions": [{"coin": "BTC", "size": 0.0005, "notional": 30.0}]}

        def positions():
            return state if not fx.sent else {"positions": []}
        ex = self.r.exchange(dry_run=False, exchange=fx, info=FakeInfo([{"coin": "ETH", "oid": 7}]),
                             meta={"BTC": 5}, positions=positions)
        out = ex.flatten(sleep=lambda s: None)
        self.assertEqual(len(out), 1)
        coin, is_buy, sz, px, tif, reduce_only = fx.sent[0]
        self.assertEqual((coin, is_buy, sz, tif, reduce_only), ("BTC", False, 0.0005, "Ioc", True))
        self.assertLess(px, 59990)                                            # below the bid: crossing to close
        self.assertEqual(fx.cancelled, [("ETH", 7)])                         # resting orders go first


class TestPure(unittest.TestCase):
    def test_the_url_is_a_constant_on_mainnet(self):
        self.assertEqual(M.MAINNET_URL, "https://api.hyperliquid.xyz")
        self.assertEqual(M.MAINNET_HOST, "api.hyperliquid.xyz")

    def test_holder_limits_read_the_page(self):
        lim = M.holder_limits()
        self.assertEqual(set(lim), {"holder_stop", "venue_loss_usd"})


if __name__ == "__main__":
    unittest.main()
