"""The full-stack replay: each fault in replay_stack.FAULTS does what the table says, on synthetic books only.

One test per row; the assertions are on the journal and the orders sent, never on P&L.
"""
import sqlite3
import tempfile
import unittest
from pathlib import Path

from espero import replay_stack as R

T = 1_794_000_000                         # an event's time, unix seconds
NOW = T * 1000 + 5_000                    # the decision, 5 s after the event


def books(coin="BTC", start_ms=NOW - 600_000, end_ms=NOW + 4 * 3_600_000, every_ms=1_000):
    """A whole Hyperliquid-like book every second: 100 at the touch, 5 coins on each of three levels."""
    return {coin: [{"t": t, "rt": t, "bids": [(99.99, 5.0), (99.98, 5.0), (99.97, 5.0)],
                    "asks": [(100.01, 5.0), (100.02, 5.0), (100.03, 5.0)]} for t in range(start_ms, end_ms, every_ms)]}


def signal(rule="24", ts=T, coin="BTC"):
    return R.Signal(rule, "s", coin, 1, ts, 1_000.0)


def stack(venue=None, offset=0.0, db=None):
    st = R.Stack(db or sqlite3.connect(":memory:"), venue or R.RecordedVenue(books()), R.replay_account(10_000, "s"),
                 clock_offset_s=lambda: offset)
    st.startup(NOW)
    return st


def kinds(st):
    return [e["kind"] for e in st.events()]


class TestThePath(unittest.TestCase):
    def test_a_fresh_signal_is_sized_by_the_gate_sent_once_and_journaled(self):
        st = stack()
        out = st.step(signal(), NOW)
        self.assertTrue(out["placed"])
        self.assertAlmostEqual(out["filled"], 1_000.0 / 100.0)
        self.assertEqual(len(st.venue.sent), 1)
        self.assertEqual(st.venue.sent[0], R.cloid("24", "BTC", T, "entry"))
        self.assertIn("filled", kinds(st))
        again = st.step(signal(), NOW + 1_000)
        self.assertFalse(again["placed"])
        self.assertEqual(len(st.venue.sent), 1)                          # the same event never trades twice

    def test_the_gate_still_rules(self):
        st = R.Stack(sqlite3.connect(":memory:"), R.RecordedVenue(books()), R.replay_account(0.0, "s"))
        st.startup(NOW)
        self.assertIn("no capital allocated", st.step(signal(), NOW)["reason"])

    def test_the_order_is_the_gate_s_size_not_the_sleeve_s(self):
        st = R.Stack(sqlite3.connect(":memory:"), R.RecordedVenue(books()), R.replay_account(2_000.0, "s"))
        st.startup(NOW)
        out = st.step(signal(), NOW)                                     # asks $1,000; per coin is 20% of $2,000
        self.assertAlmostEqual(out["filled"], 400.0 / 100.0)
        self.assertAlmostEqual(st.journal_positions()["BTC"], 4.0)


class TestFaults(unittest.TestCase):
    def test_every_fault_has_its_test(self):
        for name in R.FAULTS:
            self.assertTrue(hasattr(self, f"test_{name}"), name)

    def test_the_runbook_lists_every_fault(self):
        text = (Path(R.__file__).resolve().parents[1] / "docs" / "RUNBOOK.md").read_text(encoding="utf-8")
        for name in R.FAULTS:
            self.assertIn(f"| {name.replace('_', ' ')} |", text, name)

    def test_dropped_frames(self):
        venue = R.RecordedVenue(books(end_ms=NOW - 60_000))              # the last book is a minute old
        st = stack(venue)
        out = st.step(signal(rule="29", ts=T), NOW)                       # #29's budget is 45 s
        self.assertFalse(out["placed"])
        self.assertIn("stale book", out["reason"])
        self.assertEqual(venue.sent, [])

    def test_venue_silent(self):
        venue = R.RecordedVenue(books(end_ms=NOW - 300_000))             # five minutes without a frame
        st = stack(venue)
        for k in range(2):
            self.assertEqual(st.step(signal(ts=T + k), NOW + k * 1_000)["reason"], "venue silent")
        self.assertEqual(kinds(st).count("silence"), 1)                  # journaled once
        self.assertEqual(venue.sent, [])                                 # nothing was closed blind either

    def test_partial_fill(self):
        venue = R.RecordedVenue(books(), fill_share=0.4)
        st = stack(venue)
        out = st.step(signal(), NOW)
        self.assertAlmostEqual(out["filled"], 0.4 * 10.0)
        self.assertAlmostEqual(st.journal_positions()["BTC"], 4.0)
        self.assertEqual(len(venue.sent), 1)                             # the rest is not chased
        venue.fill_share = 1.0                                           # the fault was the entry's
        exit_ = st.exit(signal(), NOW + 4 * 3_600_000)
        self.assertAlmostEqual(exit_["filled"], 4.0)                     # the exit sells what was bought
        self.assertAlmostEqual(st.journal_positions()["BTC"], 0.0, places=9)
        self.assertAlmostEqual(venue.positions["BTC"], 0.0, places=9)

    def test_restart(self):
        class CrashAfterSend(R.RecordedVenue):
            def market(self, *a, **k):
                super().market(*a, **k)
                raise RuntimeError("the process died after the venue took the order")

        venue = CrashAfterSend(books())
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "stack.db"
            db = sqlite3.connect(path)
            st = stack(venue, db=db)
            with self.assertRaises(RuntimeError):
                st.step(signal(), NOW)
            db.close()                                                   # the process died: the uncommitted is lost
            db = sqlite3.connect(path)
            inflight = db.execute("SELECT status FROM stack_orders").fetchone()
            self.assertEqual(inflight[0], "inflight")                    # journaled before the send
            again = stack(venue, db=db)                                  # the restart, a new process
            self.assertEqual(again.breaks, [])                           # its own fill found first, no false break
            self.assertAlmostEqual(again.journal_positions()["BTC"], 10.0)
            out = again.step(signal(), NOW + 30_000)
            self.assertFalse(out["placed"])
            self.assertEqual(len(venue.sent), 1)                         # no second order
            db.close()

    def test_unknown_position(self):
        venue = R.RecordedVenue(books(), positions={"ETH": 1.5})
        st = stack(venue)
        self.assertEqual(len(st.breaks), 1)
        self.assertIn("break", kinds(st))
        out = st.step(signal(), NOW)
        self.assertIn("an open break", out["reason"])
        self.assertEqual(venue.sent, [])

    def test_clock_skew(self):
        st = stack(offset=1.5)
        self.assertIn("clock off by +1.50 s", st.step(signal(), NOW)["reason"])
        self.assertTrue(stack(offset=0.9).step(signal(), NOW)["placed"])

    def test_stale_input(self):
        st = stack()
        old = st.step(signal(ts=T - 721), NOW)                           # #24's budget is 720 s
        self.assertFalse(old["placed"])
        self.assertIn("stale", old["reason"])
        self.assertTrue(st.step(signal(ts=T - 700), NOW)["placed"])


def frame(coin, t, ch="l2Book"):
    """A recorded Hyperliquid line as rawrec writes it."""
    return {"ch": ch, "s": coin, "rt": t + 300,
            "d": {"data": {"time": t, "levels": [[{"px": "99.99", "sz": "5"}], [{"px": "100.01", "sz": "5"}]]}}}


class TestRecordedBooks(unittest.TestCase):
    def test_keeps_each_coin_s_books_near_its_decisions_only(self):
        at = {"BTC": [1_000_000, 5_000_000]}
        frames = [frame("BTC", t) for t in (870_000, 880_000, 1_000_000, 1_060_000, 1_070_000, 3_000_000,
                                            4_879_000, 5_000_000)]
        frames += [frame("ETH", 1_000_000), frame("BTC", 1_000_000, ch="trades"), {"ch": "l2Book", "s": "BTC"}]
        books, seen = R.recorded_books(frames, at, before_ms=121_000, after_ms=60_000)
        self.assertEqual([b["t"] for b in books["BTC"]], [880_000, 1_000_000, 1_060_000, 4_879_000, 5_000_000])
        self.assertEqual(seen, {"BTC", "ETH"})                           # ETH recorded, though not wanted
        self.assertEqual(set(books), {"BTC"})

    def test_a_coin_the_tape_never_recorded_has_no_books(self):
        books, seen = R.recorded_books([frame("ETH", 1_000)], {"HBAR": [1_000]})
        self.assertEqual(books, {"HBAR": []})
        self.assertNotIn("HBAR", seen)


class TestSummary(unittest.TestCase):
    def test_counts_by_outcome(self):
        st = stack(R.RecordedVenue(books(end_ms=NOW - 300_000)))
        st.step(signal(), NOW)
        self.assertEqual(R.summary(st.events()), {"silence": 1, "refused: venue silent": 1})

    def test_a_silent_venue_at_send_is_asked_again_before_any_resend(self):
        venue = R.RecordedVenue(books(), silent=(NOW, NOW + 10_000))
        st = stack(venue)
        out = st.step(signal(), NOW)
        self.assertEqual(out["reason"], "sent, no answer yet")
        later = st.step(signal(), NOW + 20_000)
        self.assertEqual(later["reason"], "filled")                     # the venue had never seen it: sent again
        self.assertEqual(len(venue.sent), 2)
        self.assertEqual(venue.sent[0], venue.sent[1])                  # the same client order id

    def test_a_book_older_than_a_minute_but_inside_the_budget_is_refused_not_a_crash(self):
        """The window between replaysim's 60 s default book age and the 120 s silence limit, inside #24's 720 s
        budget: book_at found no book and the step raised TypeError. The decision now reads the last book inside
        the rule's budget, as the step's own stale-book rule says, and the recorded venue answers for the fill."""
        venue = R.RecordedVenue(books(end_ms=NOW - 90_000))
        st = stack(venue)
        out = st.step(signal(), NOW)
        self.assertTrue(out["placed"])
        self.assertEqual(out["reason"], "rejected")                      # no frame within a minute of arrival
        self.assertEqual(len(venue.sent), 1)
        self.assertNotIn("refused", kinds(st))

    def test_a_one_sided_book_is_refused(self):
        b = books()
        for frame in b["BTC"]:
            frame["asks"] = []
        st = stack(R.RecordedVenue(b))
        self.assertIn("no usable book", st.step(signal(), NOW)["reason"])

    def test_the_exit_refuses_on_a_skewed_clock_too(self):
        off = [0.0]
        st = R.Stack(sqlite3.connect(":memory:"), R.RecordedVenue(books()), R.replay_account(10_000, "s"),
                     clock_offset_s=lambda: off[0])
        st.startup(NOW)
        self.assertEqual(st.step(signal(), NOW)["reason"], "filled")
        off[0] = 5.0
        out = st.exit(signal(), NOW + 10_000)
        self.assertFalse(out["placed"])
        self.assertIn("clock off", out["reason"])
        off[0] = 0.0
        self.assertEqual(st.exit(signal(), NOW + 20_000)["reason"], "filled")

    def test_a_rule_with_no_latency_budget_is_refused_outright(self):
        st = stack()
        out = st.step(R.Signal("zz", "s", "BTC", 1, T, 1_000.0), T * 1000)
        self.assertFalse(out["placed"])
        self.assertIn("no latency budget", out["reason"])

    def test_a_silent_venue_after_a_restart_sends_nothing_and_does_not_crash(self):
        """FAULTS restart + venue_silent together: the order is journaled, the venue goes quiet, the lookup by
        client id gets no answer. The step refuses, journals it, resends nothing, and asks again later."""
        venue = R.RecordedVenue(books(), silent=(NOW + 20_000, NOW + 40_000))
        st = stack(venue)
        self.assertEqual(st.step(signal(), NOW)["reason"], "filled")
        quiet = st.step(signal(), NOW + 30_000)                          # the row exists; the venue is silent
        self.assertFalse(quiet["placed"])
        self.assertEqual(quiet["reason"], "sent before, no answer yet")
        self.assertEqual(len(venue.sent), 1)                            # nothing resent blind
        self.assertIn("no answer", kinds(st))
        later = st.step(signal(), NOW + 50_000)
        self.assertEqual(later["reason"], "already sent: recovered from the venue")
        self.assertEqual(len(venue.sent), 1)


if __name__ == "__main__":
    unittest.main()
