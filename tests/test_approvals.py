"""The operator's protocol: one-time codes, proposals, refusals, silence, and a journal nobody can rewrite."""
from __future__ import annotations

import base64
import contextlib
import io
import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

from espero import approvals as A
from espero import latency as L

KEY = b"12345678901234567890"               # RFC 4226 / RFC 6238's test secret
NOW = 1_800_000_000


def code(t: float = NOW) -> str:
    return A.totp(KEY, t)


class TestCodes(unittest.TestCase):
    def test_rfc4226_hotp_vectors(self):
        want = ["755224", "287082", "359152", "969429", "338314", "254676", "287922", "162583", "399871", "520489"]
        self.assertEqual([A.hotp(KEY, c) for c in range(10)], want)

    def test_rfc6238_totp_vectors(self):
        for t, want in ((59, "94287082"), (1111111109, "07081804"), (1111111111, "14050471"),
                        (1234567890, "89005924"), (2000000000, "69279037"), (20000000000, "65353130")):
            self.assertEqual(A.totp(KEY, t, digits=8), want)

    def test_secret_is_read_from_the_environment_as_base32_and_never_echoed(self):
        b32 = base64.b32encode(KEY).decode()
        self.assertEqual(A.secret({A.SECRET_ENV: b32.lower()[:8] + " " + b32.lower()[8:]}), KEY)
        nine = base64.b32encode(b"x" * 9).decode()
        self.assertEqual(A.secret({A.SECRET_ENV: base64.b32encode(b"x" * 10).decode()}), b"x" * 10)
        for env in ({}, {A.SECRET_ENV: "  "}, {A.SECRET_ENV: "not*base32"}, {A.SECRET_ENV: "MFRGG==="},
                    {A.SECRET_ENV: nine}):
            with self.assertRaises(A.NoSecret) as cm:
                A.secret(env)
            value = env.get(A.SECRET_ENV, "").strip()
            if value:
                self.assertNotIn(value, str(cm.exception))

    def test_a_code_is_good_for_its_window_and_the_one_before_once(self):
        self.assertIsNotNone(A.matching_step(KEY, code(), NOW))
        self.assertIsNotNone(A.matching_step(KEY, code(NOW - 30), NOW))
        self.assertIsNone(A.matching_step(KEY, code(NOW - 60), NOW))
        self.assertIsNone(A.matching_step(KEY, code(NOW + 30), NOW))
        step = A.matching_step(KEY, code(), NOW)
        self.assertIsNone(A.matching_step(KEY, code(), NOW, used=[step]))
        for bad in ("", "12345", "1234567", "abcdef", None):
            self.assertIsNone(A.matching_step(KEY, bad, NOW))


class TestProposals(unittest.TestCase):
    def test_wait_is_the_budget_less_feed_and_allowance_capped_at_a_day(self):
        r12 = L.by_test()["12"]
        self.assertEqual(A.wait_s("12"), int(r12.budget_s - r12.feed_s - A.EXECUTION_ALLOWANCE_S))
        self.assertEqual(A.wait_s("4"), A.MAX_WAIT_S)

    def test_only_operator_paced_rules_wait_for_a_person(self):
        for t in ("24", "58", "22", "27", "999"):
            self.assertIsNone(A.wait_s(t))
            with self.assertRaises(A.NotOperatorPaced):
                A.propose(t, "s", "BTC", "buy", 100.0, 1.0, 9.0, None, NOW)

    def test_a_proposal_needs_a_size_from_the_gate_and_a_side(self):
        with self.assertRaises(ValueError):
            A.propose("12", "carry", "BTC", "sell", 0.0, 1.0, 9.0, None, NOW)
        with self.assertRaises(ValueError):
            A.propose("12", "carry", "BTC", "short", 100.0, 1.0, 9.0, None, NOW)
        p = A.propose("12", "carry", "BTC", "sell", 100.0, 1.0, 9.0, None, NOW)
        self.assertEqual((p.mode, p.kind, p.klass), ("machine", "entry", L.OPERATOR_PACED))
        self.assertEqual(p.expires, NOW + A.wait_s("12"))

    def test_silence_takes_no_entry_and_executes_an_exit(self):
        self.assertEqual(A.on_silence("entry"), "not taken")
        self.assertEqual(A.on_silence("exit"), "executed")

    def test_describe_says_how_to_answer(self):
        p = A.propose("12", "carry", "BTC", "sell", 100.0, 65000.0, 9.0, 70000.0, NOW)
        text = A.describe(p)
        self.assertIn(f"espero approve {p.id} approve CODE", text)
        self.assertIn("#12 sell BTC $100.00", text)
        self.assertIn("UTC", text)


class LedgerCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.led = A.Ledger.open(Path(self.tmp.name) / A.LEDGER)

    def tearDown(self):
        self.led.db.close()
        self.tmp.cleanup()

    def proposal(self, now: int = NOW, notional: float = 100.0) -> A.Proposal:
        p = A.propose("12", "carry", "BTC", "sell", notional, 65000.0, 9.0, None, now)
        self.led.record(p)
        return p

    def reply(self, p, answer="approve", t=NOW, reason="", notional=None, c=None):
        return self.led.answer(A.Reply(p.id, answer, c if c is not None else code(t), reason, notional), KEY, t)


class TestAnswers(LedgerCase):
    def test_approve_with_a_code_sends_the_gates_size_once(self):
        p = self.proposal()
        out = self.reply(p)
        self.assertEqual((out.event, out.notional), ("approved", 100.0))
        self.assertEqual(self.led.status(p.id), "approved")
        again = self.reply(p, t=NOW + 30)
        self.assertEqual((again.event, again.reason), ("refused", "already approved"))

    def test_a_code_is_spent_by_its_first_use(self):
        p, q = self.proposal(), self.proposal()
        self.assertEqual(self.reply(p).event, "approved")
        self.assertEqual(self.reply(q).event, "refused")
        self.assertEqual(self.led.status(q.id), "open")

    def test_an_unauthenticated_reply_is_journaled_and_leaves_the_proposal_open(self):
        p = self.proposal()
        out = self.reply(p, c="000000")
        self.assertEqual(out.event, "refused")
        self.assertIn("unauthenticated", out.reason)
        self.assertEqual(self.led.status(p.id), "open")
        self.assertEqual(self.led.answer(A.Reply(p.id, "approve", code()), None, NOW).event, "refused")
        self.assertEqual(self.reply(p).event, "approved")
        self.assertEqual([e["event"] for e in self.led.events()], ["proposed", "refused", "refused", "approved"])

    def test_an_override_needs_a_reason(self):
        p = self.proposal()
        self.assertEqual(self.reply(p, "reject").reason, "an override needs a reason")
        out = self.reply(p, "reject", t=NOW + 30, reason="funding about to flip")
        self.assertEqual((out.event, out.notional), ("rejected", 0.0))

    def test_modify_only_sizes_down(self):
        p = self.proposal()
        for n in (None, 0.0, 100.0, 150.0):
            self.assertEqual(self.reply(p, "modify", reason="smaller", notional=n).event, "refused")
        out = self.reply(p, "modify", reason="half", notional=50.0)
        self.assertEqual((out.event, out.notional), ("modified", 50.0))

    def test_an_exit_is_not_an_answer_to_an_entry(self):
        p = self.proposal()
        self.assertEqual(self.reply(p, "exit", reason="x").event, "refused")
        self.assertEqual(self.reply(p, "maybe", reason="x").event, "refused")

    def test_unknown_proposal_and_lapsed_ones_are_refused(self):
        self.assertEqual(self.led.answer(A.Reply("nope", "approve", code()), KEY, NOW).reason, "no such proposal")
        p = self.proposal()
        late = p.expires
        self.assertEqual(self.reply(p, t=late).reason, "too late: the proposal had lapsed")

    def test_silence_lapses_an_entry_unanswered(self):
        p = self.proposal()
        self.assertEqual(self.led.expire(p.expires - 1), [])
        self.assertEqual([x.id for x in self.led.pending(NOW)], [p.id])
        self.assertEqual(self.led.pending(p.expires), [])          # lapsed, though not yet journaled
        out = self.led.expire(p.expires)
        self.assertEqual(len(out), 1)
        self.assertEqual((out[0].event, out[0].notional), ("silence", 0.0))
        self.assertIn("not taken", out[0].reason)
        self.assertEqual(self.led.status(p.id), "silence")
        self.assertEqual(self.led.pending(NOW), [])
        self.assertEqual(self.led.expire(p.expires + 10), [])


class TestTheJournal(LedgerCase):
    def test_events_cannot_be_rewritten_or_removed(self):
        self.proposal()
        for sql in ("UPDATE approval_events SET reason='x'", "DELETE FROM approval_events"):
            with self.assertRaises(sqlite3.DatabaseError):
                self.led.db.execute(sql)
        self.assertEqual(self.led.verify(), [])

    def test_the_chain_shows_a_row_changed_behind_its_back(self):
        p = self.proposal()
        self.reply(p)
        self.assertEqual(self.led.verify(), [])
        self.led.db.execute("DROP TRIGGER approval_events_no_update")
        self.led.db.execute("UPDATE approval_events SET reason='forged' WHERE n=1")
        self.assertIn("event 1: its content no longer matches its hash", self.led.verify())

    def test_a_forger_who_rehashes_a_row_and_relinks_the_next_is_still_caught(self):
        for _ in range(2):
            self.proposal()
        self.led.db.execute("DROP TRIGGER approval_events_no_update")
        r1 = self.led.events()[0]
        forged = A.chain_hash(r1["prev"], r1["ts"], r1["event"], r1["proposal"], r1["body"], "forged")
        self.led.db.execute("UPDATE approval_events SET reason='forged', hash=? WHERE n=1", (forged,))
        self.led.db.execute("UPDATE approval_events SET prev=? WHERE n=2", (forged,))
        self.assertEqual(self.led.verify(), ["event 2: its content no longer matches its hash"])

    def test_the_chain_shows_a_row_taken_out(self):
        for _ in range(3):
            self.proposal()
        self.led.db.execute("DROP TRIGGER approval_events_no_delete")
        self.led.db.execute("DELETE FROM approval_events WHERE n=2")
        self.assertIn("event 3: does not follow the event before it", self.led.verify())

    def test_a_proposal_edited_after_it_was_recorded_is_caught(self):
        p = self.proposal()
        body = json.loads(self.led.db.execute("SELECT body FROM proposals").fetchone()["body"])
        body["notional"] = 1e6
        self.led.db.execute("UPDATE proposals SET body=?", (json.dumps(body),))
        with self.assertRaises(RuntimeError):
            self.led.proposal(p.id)

    def test_the_code_is_never_written_to_the_journal(self):
        p = self.proposal()
        c = code()
        self.reply(p, c=c)
        for e in self.led.events():
            self.assertNotIn(c, e["body"] or "")


class TestModeB(LedgerCase):
    def order(self, kind="entry", rule="24", side="buy", notional=50.0, reason="saw the event", t=NOW):
        return A.OperatorOrder(rule, "lows", "BTC", side, kind, notional, reason, code(t), at=t)

    def test_an_early_exit_is_accepted_with_a_code_and_a_reason(self):
        out = self.led.operator(self.order("exit"), [], KEY, NOW, None)
        self.assertEqual((out.event, out.notional), ("exit", 50.0))
        blank = self.led.operator(self.order("exit", reason=" ", t=NOW + 30), [], KEY, NOW + 30, None)
        self.assertEqual(blank.reason, "an operator's order is an override and needs a reason")

    def test_an_entry_must_follow_a_live_event_of_its_rule_inside_the_budget(self):
        budget = L.by_test()["24"].budget_s
        live = [A.LiveEvent("24", "BTC", "buy", NOW - int(budget))]
        self.assertEqual(self.led.operator(self.order(), [], KEY, NOW, 100.0).reason,
                         "no live event of a registered rule supports this entry")
        late = [A.LiveEvent("24", "BTC", "buy", NOW - int(budget) - 1)]
        self.assertEqual(self.led.operator(self.order(), late, KEY, NOW, 100.0).event, "refused")
        other = [A.LiveEvent("24", "BTC", "sell", NOW), A.LiveEvent("24", "ETH", "buy", NOW),
                 A.LiveEvent("29", "BTC", "buy", NOW)]
        self.assertEqual(self.led.operator(self.order(), other, KEY, NOW, 100.0).event, "refused")
        out = self.led.operator(self.order(), live, KEY, NOW, 100.0)
        self.assertEqual((out.event, out.notional), ("operator", 50.0))

    def test_an_entry_is_never_larger_than_the_gate_allows(self):
        live = [A.LiveEvent("24", "BTC", "buy", NOW)]
        self.assertIn("above the risk gate's size", self.led.operator(self.order(notional=150.0), live, KEY, NOW,
                                                                        100.0).reason)
        self.assertEqual(self.led.operator(self.order(), live, KEY, NOW, 0.0).reason, "the risk gate gave no size")
        self.assertEqual(self.led.operator(self.order(notional=100.0), live, KEY, NOW, 100.0).event, "operator")

    def test_a_rule_that_cannot_be_traded_live_supports_nothing(self):
        for rule in ("22", "27", "61"):
            live = [A.LiveEvent(rule, "BTC", "buy", NOW)]
            self.assertEqual(self.led.operator(self.order(rule=rule), live, KEY, NOW, 100.0).event, "refused")

    def test_an_order_without_a_code_is_refused(self):
        live = [A.LiveEvent("24", "BTC", "buy", NOW)]
        self.assertIn("unauthenticated", self.led.operator(self.order(), live, None, NOW, 100.0).reason)
        self.assertEqual(self.led.operator(self.order(kind="hedge"), live, KEY, NOW, 100.0).event, "refused")


class TestInbox(unittest.TestCase):
    def test_replies_and_orders_round_trip_oldest_first_and_are_taken_once(self):
        with tempfile.TemporaryDirectory() as d:
            a = A.Reply("abc", "approve", "123456", at=2)
            b = A.OperatorOrder("24", "lows", "BTC", "buy", "entry", 50.0, "r", "654321", at=1)
            A.post(d, a)
            A.post(d, b)
            (A.inbox(d) / "000000000003-reply-x.json").write_text("{not json", encoding="utf-8")
            self.assertEqual(A.take(d), [b, a])
            self.assertEqual(A.take(d), [])
            self.assertEqual(len(list(A.inbox(d).glob("*.unreadable"))), 1)

    def test_an_empty_state_has_nothing_waiting(self):
        with tempfile.TemporaryDirectory() as d:
            self.assertEqual(A.take(d), [])


class TestInboxFileMode(unittest.TestCase):
    def test_a_posted_reply_is_readable_by_its_owner_only(self):
        """The inbox file carries a live one-time code until the runner takes it."""
        import stat

        with tempfile.TemporaryDirectory() as d:
            path = A.post(d, A.Reply("p1", "approve", "123456", at=NOW))
            self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)
            self.assertEqual(len(A.take(d)), 1)


class TestTheCommand(unittest.TestCase):
    def run_cli(self, *argv):
        from espero import cli

        buf = io.StringIO()
        with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(io.StringIO()):
            rc = cli.main(["approve", *argv])
        return rc, buf.getvalue()

    def test_lists_what_waits_and_leaves_a_reply_for_the_runner(self):
        with tempfile.TemporaryDirectory() as d:
            rc, out = self.run_cli("--state-dir", d)
            self.assertEqual(rc, 0)
            self.assertIn("nothing waits", out)
            led = A.Ledger.open(Path(d) / A.LEDGER)
            p = A.propose("12", "carry", "BTC", "sell", 100.0, 65000.0, 9.0, None, int(__import__("time").time()))
            led.record(p)
            led.db.close()
            rc, out = self.run_cli("--state-dir", d)
            self.assertIn(p.id, out)
            rc, out = self.run_cli(p.id, "reject", "123456", "--reason", "too close to funding", "--state-dir", d)
            self.assertEqual(rc, 0)
            [reply] = A.take(d)
            self.assertEqual((reply.proposal, reply.answer, reply.reason, reply.channel),
                             (p.id, "reject", "too close to funding", "cli"))

    def test_an_answer_without_a_code_is_a_usage_error(self):
        with tempfile.TemporaryDirectory() as d:
            self.assertEqual(self.run_cli("abc", "approve", "--state-dir", d)[0], 2)
            self.assertEqual(A.take(d), [])

    def test_the_screens_read_the_ledger_without_writing_it(self):
        with tempfile.TemporaryDirectory() as d:
            A.Ledger.open(Path(d) / A.LEDGER).db.close()
            ro = A.Ledger.read_only(Path(d) / A.LEDGER)
            with self.assertRaises(sqlite3.OperationalError):
                ro.db.execute("INSERT INTO used_codes (step, ts) VALUES (1, 1)")


if __name__ == "__main__":
    unittest.main(verbosity=2)
