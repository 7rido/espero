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


def ruling(notional=30.0, allowed=True, policy_hash=None, coin="BTC", side=1, rule="8", venue="hyperliquid",
           reduce_only=False):
    """A fresh ruling, as risk.check gives one: made for one order, good for that order once."""
    order = risk.Order("mf-canary", rule, venue, coin, side, notional, reduce_only=reduce_only)
    return risk.Ruling(allowed, notional, () if allowed else ("a reason",), {}, policy_hash or risk.policy_hash(),
                       order)


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
        kw.setdefault("signers", self.signers)
        kw.setdefault("policy_committed", lambda: True)
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
        self.refused("does not verify", signers=inside)
        self.refused("does not verify", signers=Path("allowed_signers"))          # a relative path: refused
        self.refused("does not verify", signers=self.r.base / "missing")

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


class RaisingEx(FakeEx):
    def order(self, coin, is_buy, sz, px, kind, reduce_only=False, **kw):
        self.sent.append((coin, is_buy, sz, px, kind["limit"]["tif"], reduce_only))
        raise TimeoutError("read timed out")


@unittest.skipUnless(HAVE_SSH_KEYGEN, "needs ssh-keygen")
class TestTheAuditOf20261109(unittest.TestCase):
    """docs/AUDIT_2026-11-09.md, M1 to M12: each finding as the reviewer reproduced it, now refused."""

    def setUp(self):
        self.r = Repo()

    def refused(self, needle, **kw):
        with self.assertRaises(M.MainnetRefused) as cm:
            self.r.exchange(**kw)
        self.assertIn(needle, str(cm.exception))

    def live(self, orders=(), held=(), fx=None, info=None):
        fx = fx or FakeEx()
        ex = self.r.exchange(dry_run=False, exchange=fx, info=info or FakeInfo(orders), meta={"BTC": 5, "ETH": 4},
                             positions=lambda: {"positions": list(held)})
        return ex, fx

    # ---- M1
    def test_m1_resting_orders_count_against_the_position_and_venue_caps(self):
        ex, fx = self.live(orders=[{"coin": "BTC", "oid": 1, "sz": "0.0005", "limitPx": "60000"}])
        res = ex.limit("BTC", "buy", 0.0004, 60_000.0, ruling=ruling())           # 30 resting + 24 > 50
        self.assertIn("held and resting", res.error)
        self.assertEqual(ex.limit("BTC", "buy", 0.0003, 60_000.0, ruling=ruling()).status, "filled")  # 30 + 18
        ex, fx = self.live(orders=[{"coin": "ETH", "oid": 2, "sz": "0.02", "limitPx": "2250"}])      # $45 resting
        self.assertIn("venue_loss_usd", ex.limit("BTC", "buy", 0.0002, 60_000.0, ruling=ruling()).error)
        self.assertEqual(fx.sent, [])

    def test_m1_under_kill_resting_orders_are_cancelled(self):
        ex, fx = self.live(orders=[{"coin": "BTC", "oid": 9, "sz": "0.0001", "limitPx": "60000"}])
        (self.r.base / "state" / "KILL").write_text("")
        self.assertIn("KILL", ex.limit("BTC", "buy", 0.0002, 60_000.0, ruling=ruling()).error)
        self.assertEqual(fx.cancelled, [("BTC", 9)])

    # ---- M2
    def test_m2_a_sell_priced_far_below_the_market_counts_at_the_market(self):
        ex, fx = self.live()
        res = ex.limit("BTC", "sell", 0.001, 20.0, tif="Ioc", ruling=ruling(side=-1))   # "$0.02", really $59.99
        self.assertIn("largest order", res.error)
        self.assertEqual(fx.sent, [])
        self.assertEqual(ex.limit("BTC", "sell", 0.0004, 20.0, tif="Ioc", ruling=ruling(side=-1)).status, "filled")

    def test_m2_no_book_no_order(self):
        class NoBook(FakeInfo):
            def l2_snapshot(self, coin):
                raise ConnectionError("down")
        ex, fx = self.live(info=NoBook())
        self.assertIn("could not be read", ex.limit("BTC", "sell", 0.0002, 60_000.0, ruling=ruling(side=-1)).error)
        self.assertEqual(fx.sent, [])

    # ---- M3
    def stranger_lift(self, sign=True):
        self.r.lift(dict(FIELDS, max_order_usd="100000", max_position_usd="100000"))
        self.r.commit("not the holder's", sign=sign, key="stranger")
        other = self.r.base / "other_signers"                   # trusts the holder and the stranger alike
        other.write_text(self.r.signers.read_text() + f"holder {(self.r.keys / 'stranger.pub').read_text()}")
        return other

    def test_m3_git_config_does_not_choose_the_signers(self):
        other = self.stranger_lift()
        self.r.git("config", "gpg.ssh.allowedSignersFile", str(other))
        self.refused("does not verify")

    def test_m3_the_environment_does_not_choose_the_signers_or_the_repository(self):
        import os
        from unittest import mock
        other = self.stranger_lift()
        with mock.patch.dict(os.environ, {"GIT_CONFIG_COUNT": "1", "GIT_CONFIG_KEY_0": "gpg.ssh.allowedSignersFile",
                                          "GIT_CONFIG_VALUE_0": str(other)}):
            self.refused("does not verify")

    def test_m3_git_dir_cannot_point_at_a_copy_that_still_holds_an_older_lift(self):
        import os
        from unittest import mock
        old = self.r.base / "old"
        shutil.copytree(self.r.root, old)                        # a copy from before the holder tightened the lift
        loose = (self.r.root / "research" / "MAINNET_LIFT.md").read_text()
        self.r.lift(dict(FIELDS, max_order_usd="11", max_position_usd="12"))
        self.r.commit("tighter", sign=True)
        (self.r.root / "research" / "MAINNET_LIFT.md").write_text(loose)           # an uncommitted edit back
        with mock.patch.dict(os.environ, {"GIT_DIR": str(old / ".git")}):
            self.refused("uncommitted")

    def test_m3_a_relative_signers_path_is_refused_even_when_a_file_of_that_name_is_here(self):
        import os
        here = os.getcwd()
        os.chdir(self.r.base)                                    # allowed_signers, the good one, is in this folder
        self.addCleanup(os.chdir, here)
        self.refused("does not verify", signers=Path("allowed_signers"))

    def test_m3_a_program_that_says_good_signature_is_not_asked(self):
        fake = self.r.base / "yes.sh"
        fake.write_text('#!/bin/sh\necho holder\necho \'Good "git" signature for holder with ED25519 key SHA256:x\'\n'
                        'echo \'Good "git" signature for holder with ED25519 key SHA256:x\' >&2\nexit 0\n')
        fake.chmod(0o755)
        for sign in (True, False):                                # signed by a stranger, then not signed at all
            for key in ("gpg.ssh.program", "gpg.program"):
                self.r.git("config", "--unset", key, check=False)
            self.r.lift(dict(FIELDS, max_order_usd="100000", max_position_usd="100000" + "0" * (not sign)))
            self.r.commit("not the holder's", sign=sign, key="stranger")
            for key in ("gpg.ssh.program", "gpg.program"):
                self.r.git("config", key, str(fake))
            self.refused("does not verify")

    def test_m3_a_replaced_object_is_not_read(self):
        lift = self.r.root / "research" / "MAINNET_LIFT.md"
        old = self.r.git("rev-parse", "HEAD:research/MAINNET_LIFT.md").stdout.strip()
        lift.write_text(F.lift_document(STATEMENT, dict(FIELDS, max_order_usd="100000",
                                                        max_position_usd="100000"), TODAY))
        new = self.r.git("hash-object", "-w", str(lift)).stdout.strip()
        self.r.git("replace", old, new)
        self.refused("uncommitted")

    # ---- M4
    def test_m4_the_holder_page_is_the_holders_only(self):
        self.r.page({"mainnet_lift": "research/MAINNET_LIFT.md", "venue_loss_usd": "5000000", "stop_drawdown": "-3%",
                     "capital_usd": "50"})
        self.r.commit("a bigger venue limit, unsigned", sign=False)
        self.refused("HOLDER_INPUTS.md's commit")

    def test_m4_a_venue_limit_that_does_not_read_is_no_limit_and_no_order(self):
        for answer in ("50 USD", ""):
            self.r.page({"mainnet_lift": "research/MAINNET_LIFT.md", "venue_loss_usd": answer,
                         "stop_drawdown": "-3%", "capital_usd": "50"})
            self.r.commit(f"venue limit {answer!r}", sign=True)
            self.refused("venue_loss_usd")

    # ---- M5
    def test_m5_a_merge_that_brings_an_older_signed_lift_back_is_refused(self):
        v1 = self.r.git("rev-parse", "HEAD").stdout.strip()
        self.r.lift(dict(FIELDS, max_order_usd="11", max_position_usd="12"))
        self.r.commit("tighter", sign=True)
        v2 = self.r.git("rev-parse", "HEAD").stdout.strip()
        merge = self.r.git("commit-tree", f"{v1}^{{tree}}", "-p", v2, "-p", v1, "-m", "back to v1").stdout.strip()
        self.r.git("reset", "-q", "--hard", merge)
        self.refused("does not verify")

    def test_m5_a_checkout_of_an_older_signed_lift_is_refused_once_a_newer_one_was_accepted(self):
        v1 = self.r.git("rev-parse", "HEAD").stdout.strip()
        self.r.lift(dict(FIELDS, max_order_usd="11", max_position_usd="12"))
        self.r.commit("tighter", sign=True)
        self.assertEqual(self.r.exchange().lift.max_order_usd, 11.0)              # accepted, and remembered
        self.r.git("reset", "-q", "--hard", v1)
        self.refused("accepted here before")
        self.r.git("reset", "-q", "--hard", "HEAD@{1}")
        self.assertEqual(self.r.exchange().lift.max_order_usd, 11.0)              # the newer one still passes

    # ---- M6
    def test_m6_a_running_exchange_stops_when_the_lift_lapses_or_is_tightened(self):
        ex = self.r.exchange(positions=lambda: {"positions": []})
        self.assertEqual(ex.limit("BTC", "buy", 0.0004, 60_000.0, sz_decimals=5, ruling=ruling()).status, "dry")
        self.r.lift(dict(FIELDS, max_order_usd="11", max_position_usd="12"))
        self.r.commit("tighter", sign=True)
        self.assertIn("largest order", ex.limit("BTC", "buy", 0.0004, 60_000.0, sz_decimals=5,
                                                ruling=ruling()).error)             # $24 > $11 now
        self.r.allow([])
        self.r.commit("nothing allowed", sign=True)
        self.assertIn("allow-list", ex.limit("BTC", "buy", 0.0001, 60_000.0, sz_decimals=5, ruling=ruling()).error)
        ex._today = date(2027, 2, 1)
        self.assertIn("lapsed", ex.limit("BTC", "buy", 0.0001, 60_000.0, sz_decimals=5, ruling=ruling()).error)
        self.assertEqual(ex.limit("BTC", "sell", 0.0001, 60_000.0, sz_decimals=5, reduce_only=True).status, "dry")

    def test_m6_expiry_is_judged_on_the_utc_day(self):
        self.assertEqual(M.utc_today(), __import__("datetime").datetime.now(__import__("datetime").timezone.utc).date())

    # ---- M7
    def test_m7_a_ruling_passes_its_own_order_once(self):
        ex = self.r.exchange(positions=lambda: {"positions": []})

        def send(r, coin="BTC", side="buy"):
            return ex.limit(coin, side, 0.0002, 60_000.0, sz_decimals=5, ruling=r)
        one = ruling()
        self.assertEqual(send(one).status, "dry")
        self.assertIn("already used", send(one).error)
        self.assertIn("another order", send(ruling(coin="ETH")).error)
        self.assertIn("another order", send(ruling(side=-1)).error)
        self.assertIn("another order", send(ruling(venue="binance")).error)
        self.assertIn("another order", send(ruling(reduce_only=True)).error)
        self.assertIn("rule 999", send(ruling(rule="999")).error)
        bare = risk.Ruling(True, 30.0, (), {}, risk.policy_hash())
        self.assertIn("names no order", send(bare).error)
        refused = ruling()
        ex.limit("BTC", "buy", 0.001, 60_000.0, sz_decimals=5, ruling=refused)     # refused: too large
        self.assertEqual(send(refused).status, "dry")                              # a refusal does not spend it

    def test_m7_an_uncommitted_risk_gate_is_a_different_policy(self):
        ex = self.r.exchange(positions=lambda: {"positions": []}, policy_committed=lambda: False)
        self.assertIn("different policy", ex.limit("BTC", "buy", 0.0002, 60_000.0, sz_decimals=5,
                                                   ruling=ruling()).error)
        self.assertIsInstance(M.policy_at_head(), bool)

    # ---- M8
    def test_m8_an_order_whose_answer_never_came_is_journaled_with_its_client_id(self):
        ex, fx = self.live(fx=RaisingEx())
        res = ex.limit("BTC", "buy", 0.0002, 60_000.0, tif="Ioc", ruling=ruling())
        self.assertEqual(res.status, "unknown")
        self.assertEqual(len(fx.sent), 1)
        status, cloid, error = ex.db.execute("SELECT status, cloid, error FROM mainnet_orders").fetchone()
        self.assertEqual(status, "unknown")
        self.assertRegex(cloid, r"^0x[0-9a-f]{32}$")
        self.assertIn(cloid, error)

    def test_m8_flatten_closes_the_other_coins_when_one_fails_and_says_when_it_is_not_flat(self):
        class OneBadBook(FakeInfo):
            def l2_snapshot(self, coin):
                if coin == "ETH":
                    raise ConnectionError("down")
                return super().l2_snapshot(coin)
        held = [{"coin": "ETH", "size": 0.01, "notional": 22.0}, {"coin": "BTC", "size": -0.0005, "notional": 30.0}]
        ex, fx = self.live(held=held, info=OneBadBook())
        with self.assertRaises(M.NotFlat) as cm:
            ex.flatten(tries=2, sleep=lambda s: None)
        self.assertIn("BTC, ETH", str(cm.exception))
        self.assertEqual([(s[0], s[1], s[5]) for s in fx.sent], [("BTC", True, True)] * 2)   # the short is bought back
        self.assertEqual(len(cm.exception.tries), 4)

    # ---- M9
    def test_m9_live_needs_the_account_named(self):
        self.refused("HL_WALLET_ADDRESS", env=dict(ENV, HL_MAINNET_PRIVATE_KEY="0x" + "1" * 64), dry_run=False)
        self.refused("HL_WALLET_ADDRESS", env=dict(ENV, HL_MAINNET_PRIVATE_KEY="0x" + "1" * 64,
                                                   HL_WALLET_ADDRESS="not-an-address"), dry_run=False)

    def test_m9_a_position_row_without_its_value_is_sized_from_its_entry(self):
        ex = self.r.exchange(positions=lambda: {"positions": [{"coin": "BTC", "size": -0.0005, "entry": 60_000.0}]})
        self.assertAlmostEqual(ex.held_usd("BTC"), 30.0)
        self.assertIn("largest position", ex.limit("BTC", "buy", 0.0004, 60_000.0, sz_decimals=5,
                                                   ruling=ruling()).error)

    # ---- M10
    def test_m10_the_lift_says_which_rule_and_who_approves(self):
        import re
        lift = self.r.root / "research" / "MAINNET_LIFT.md"
        good = lift.read_text()
        for field in ("approval", "rule"):                        # the form refuses these; a hand-edited lift may not
            blank = re.sub(rf"^(\|\s*`?{field}`?\s*\|)[^|\n]*\|", r"\1  |", good, flags=re.M)
            self.assertNotEqual(blank, good)
            lift.write_text(blank)
            self.r.commit(f"no {field}", sign=True)
            self.refused("which rule")

    # ---- M11
    def test_m11_a_dry_run_with_a_reader_builds_nothing_of_the_testnets(self):
        ex = self.r.exchange(meta={"BTC": 5})
        self.assertIsNone(ex.venue.ex)
        self.assertEqual(ex.limit("BTC", "buy", 0.0002, 60_000.0, ruling=ruling()).status, "dry")
        fx = FakeEx()
        dry = self.r.exchange(exchange=fx, info=FakeInfo(), meta={"BTC": 5}, positions=lambda: {"positions": []})
        self.assertEqual(dry.limit("BTC", "buy", 0.0002, 60_000.0, ruling=ruling()).status, "dry")
        self.assertEqual(fx.sent, [])                                             # a dry run sends nothing
        self.assertTrue((self.r.base / "state" / M.DRY_DB).exists())
        self.assertFalse((self.r.base / "state" / M.LIVE_DB).exists())

    # ---- M12
    def test_m12_the_tighter_of_the_lift_and_the_allow_list_binds_each_cap(self):
        def error(lift, allow, size, held=()):
            r = Repo()
            r.lift(dict(FIELDS, max_order_usd=str(lift[0]), max_position_usd=str(lift[1])))
            r.allow([dict(row, max_order_usd=allow[0], max_position_usd=allow[1]) for row in ROWS])
            if r.git("status", "--porcelain").stdout.strip():
                r.commit("caps", sign=True)
            ex = r.exchange(positions=lambda: {"positions": list(held)})
            return ex.limit("BTC", "buy", size, 60_000.0, sz_decimals=5, ruling=ruling()).error or ""
        self.assertIn("largest order ($20.00)", error((30, 50), (20, 50), 0.0004))
        self.assertIn("largest order ($20.00)", error((20, 50), (30, 50), 0.0004))
        short = [{"coin": "BTC", "size": -0.0003, "notional": -18.0}]              # a short is held too
        self.assertIn("largest position", error((30, 50), (30, 40), 0.0004, short))   # 18 + 24 > 40
        self.assertIn("largest position", error((30, 40), (30, 50), 0.0004, short))
        self.assertEqual(error((30, 50), (30, 50), 0.0004, short), "")

    def test_m12_a_kill_file_that_cannot_be_read_still_kills(self):
        import os
        if os.geteuid() == 0:
            self.skipTest("root reads any file")
        ex = self.r.exchange()
        k = self.r.base / "state" / "KILL"
        k.write_text("")
        k.chmod(0)
        self.addCleanup(lambda: k.chmod(0o600))
        self.assertEqual(ex.kill_state(), "kill")


class TestPure(unittest.TestCase):
    def test_the_url_is_a_constant_on_mainnet(self):
        self.assertEqual(M.MAINNET_URL, "https://api.hyperliquid.xyz")
        self.assertEqual(M.MAINNET_HOST, "api.hyperliquid.xyz")

    def test_holder_limits_read_the_page(self):
        lim = M.holder_limits()
        self.assertEqual(set(lim), {"holder_stop", "venue_loss_usd"})


if __name__ == "__main__":
    unittest.main()
