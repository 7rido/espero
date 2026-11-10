"""Rule 8's plumbing canary (research/CANARY_MF.md), on a fake testnet with a real approvals ledger and real codes."""
import json
import tempfile
import unittest
from pathlib import Path

from espero import approvals
from espero import mf_canary as C
from espero.hl_exchange import OrderResult

MON = 1793577600                      # Monday 2026-11-02 00:00 UTC
SUN = "2026-11-01"
W2, W3 = MON + 7 * 86_400 + 3600, MON + 14 * 86_400 + 3600
KEY = b"0123456789abcdefghij"
PX = {"BTC": 60_000.0, "ETH": 3_000.0, "SOL": 150.0, "ETC": 20.0, "NEAR": 3.0, "BCH": 400.0}


class FakeTestnet:
    """The venue: fills an IOC fully unless told otherwise, keeps every order by client id, reports fills."""

    def __init__(self):
        self.meta = {"BTC": 5, "ETH": 4, "SOL": 2, "ETC": 2, "NEAR": 1}            # no BCH, as on the testnet
        self.sent, self.orders, self.fill_log = [], {}, []
        self.fill_ratio = 1.0
        self.next_oid = 100

    def book(self, coin):
        if coin in getattr(self, "no_book", ()):
            raise ValueError(f"{coin}: empty testnet book")
        return PX[coin] * 0.999, PX[coin] * 1.001

    def limit(self, coin, side, size, price, tif="Alo", reduce_only=False, cloid=None):
        self.sent.append({"coin": coin, "side": side, "size": size, "price": price, "tif": tif,
                          "reduce_only": reduce_only, "cloid": cloid})
        self.next_oid += 1
        filled = round(size * self.fill_ratio, 8)
        self.orders[cloid] = {"oid": self.next_oid, "origSz": size, "sz": size - filled}
        if filled > 0:
            self.fill_log.append({"oid": self.next_oid, "coin": coin, "sz": str(filled), "px": str(price),
                                  "crossed": True, "time": 0})
        return OrderResult(coin, side, size, price, tif, "filled" if filled else "canceled", self.next_oid,
                           filled, price if filled else None, None if filled else "no liquidity")

    def order_status(self, cloid):
        o = self.orders.get(cloid)
        if o is None:
            return {"status": "unknownOid"}
        return {"status": "order", "order": {"order": dict(o), "status": "filled" if o["sz"] == 0 else "canceled"}}

    def fills(self, since_ts=0):
        return list(self.fill_log)


class Run:
    def __init__(self, picks=("BTC", "ETH", "BCH"), shadow=None, holder_capital=50.0):
        self.state = Path(tempfile.mkdtemp())
        self.ex = FakeTestnet()
        self.picks = list(picks) if picks is not None else None
        self.shadow = shadow
        self.decided = []
        self.notes = []
        self.canary = C.Canary(self.state, self.ex, self.decide, key=KEY, holder_capital=holder_capital,
                               notify=lambda t, m: self.notes.append((t, m)), log=lambda s: None)

    def decide(self, sunday):
        self.decided.append(sunday)
        if self.picks is None:
            return None
        held = self.shadow if self.shadow is not None else sorted(self.canary.held())
        return list(self.picks), list(held), dict(PX)

    def answer(self, pid, answer, now, code=None, reason="", notional=None):
        approvals.post(self.state, approvals.Reply(pid, answer, code or approvals.totp(KEY, now), reason,
                                                   notional, "cli", now))

    def leg(self, coin, kind="entry"):
        rows = self.canary.legs("coin=? AND kind=?", (coin, kind))
        return rows[-1] if rows else None


class TestTheClock(unittest.TestCase):
    def test_monday_and_the_deadline(self):
        self.assertEqual(C.monday_of(MON), MON)
        self.assertEqual(C.monday_of(MON + 6 * 86_400 + 86_399), MON)          # Sunday 23:59:59
        self.assertEqual(C.monday_of(MON - 1), MON - 7 * 86_400)
        self.assertEqual(C.deadline(MON), MON + 86_400 - 300)                    # a day, less the 5-minute allowance
        self.assertEqual(C.ANSWER_WINDOW_S, 86_100)


class TestPure(unittest.TestCase):
    def test_exits_are_never_reduce_only_on_the_shared_netted_account(self):
        self.assertFalse(C.REDUCE_ONLY_EXITS)

    def test_plan_adds_and_drops(self):
        self.assertEqual(C.plan(["BTC", "ETH"], {"ETH": 1.0, "SOL": 2.0}), (["BTC"], ["SOL"]))

    def test_cloid_is_fixed_by_week_coin_leg_and_try_and_is_the_canarys_own(self):
        a = C.cloid(SUN, "BTC", "entry", 0)
        self.assertEqual(a, C.cloid(SUN, "BTC", "entry", 0))
        self.assertEqual(len(a), 34)
        self.assertTrue(a.startswith("0x"))
        self.assertEqual(len({a, C.cloid(SUN, "BTC", "entry", 1), C.cloid(SUN, "BTC", "exit", 0),
                              C.cloid(SUN, "ETH", "entry", 0), C.cloid("2026-11-08", "BTC", "entry", 0)}), 5)
        from espero import hlp_testnet
        self.assertNotEqual(a, hlp_testnet.cloid("BTC", MON, "entry", 0))

    def test_round_trip_cost_is_measured_or_the_assumed_18(self):
        self.assertGreater(C.round_trip_bps("BTC"), 0)
        self.assertEqual(C.round_trip_bps("NEAR"), C.ASSUMED_ROUND_TRIP_BPS)


class TestTheWeek(unittest.TestCase):
    def test_a_code_answers_one_reply_only(self):
        r = Run(picks=("BTC", "ETH"))
        r.canary.step(MON + 3600)
        r.answer(r.leg("BTC")["proposal"], "approve", MON + 3660)
        r.answer(r.leg("ETH")["proposal"], "approve", MON + 3660)            # the same code twice
        r.canary.step(MON + 3660)
        # the inbox is read in file order and two replies of one second tie: whichever comes first spends the code
        self.assertEqual(sorted([r.leg("BTC")["status"], r.leg("ETH")["status"]]), ["filled", "proposed"])
        self.assertEqual(len(r.ex.sent), 1)

    def test_entries_are_proposed_announced_and_never_traded_unanswered(self):
        r = Run()
        r.canary.step(MON + 3600)
        self.assertEqual(r.decided, [SUN])
        self.assertEqual(r.leg("BTC")["status"], "proposed")
        self.assertEqual(r.leg("ETH")["status"], "proposed")
        self.assertEqual(r.leg("BCH")["status"], "not_on_testnet")
        self.assertEqual(r.ex.sent, [])
        self.assertEqual(len(r.notes), 1)
        self.assertEqual(r.notes[0][1].count("espero approve"), 2)
        p = r.canary.ledger.proposal(r.leg("BTC")["proposal"])
        self.assertEqual((p.rule, p.sleeve, p.side, p.notional), ("8", "mf-canary", "buy", C.ENTRY_USD))
        self.assertEqual(p.expires, C.deadline(MON))
        self.assertEqual(p.event_ts, MON)
        r.canary.step(MON + 7200)
        self.assertEqual(r.decided, [SUN])                                   # decided once a week

    def test_an_answer_at_7am_eastern_on_monday_is_in_time(self):
        r = Run(picks=("BTC",))
        r.canary.step(MON + 300)                                             # 00:05 UTC, 7:05 p.m. Sunday Eastern
        noon = MON + 12 * 3600                                               # 12:00 UTC, 7:00 a.m. Monday Eastern
        r.answer(r.leg("BTC")["proposal"], "approve", noon)
        r.canary.step(noon)
        self.assertEqual(r.leg("BTC")["status"], "filled")

    def test_an_approved_entry_is_bought_and_silence_is_no(self):
        r = Run()
        r.canary.step(MON + 3600)
        r.answer(r.leg("BTC")["proposal"], "approve", MON + 3700)
        r.canary.step(MON + 3700)
        btc = r.leg("BTC")
        self.assertEqual(btc["status"], "filled")
        self.assertEqual(len(r.ex.sent), 1)
        o = r.ex.sent[0]
        self.assertEqual((o["coin"], o["side"], o["tif"], o["reduce_only"]), ("BTC", "buy", "Ioc", False))
        self.assertEqual(o["cloid"], C.cloid(SUN, "BTC", "entry", 0))
        self.assertGreaterEqual(o["size"] * PX["BTC"], 10.0)
        self.assertGreater(o["price"], PX["BTC"])                            # an IOC over the ask
        self.assertIn("BTC", r.canary.held())
        r.canary.step(C.deadline(MON))
        self.assertEqual(r.leg("ETH")["status"], "silence")
        self.assertEqual(len(r.ex.sent), 1)

    def test_an_approval_not_filled_by_the_deadline_is_late_and_never_sent(self):
        r = Run(picks=("BTC",))
        r.canary.step(MON + 3600)
        r.ex.no_book = {"BTC"}
        r.answer(r.leg("BTC")["proposal"], "approve", C.deadline(MON) - 30)
        r.canary.step(C.deadline(MON) - 30)
        self.assertEqual(r.leg("BTC")["status"], "approved")              # approved, but no book to buy from
        r.ex.no_book = set()
        r.canary.step(C.deadline(MON) + 60)
        self.assertEqual(r.leg("BTC")["status"], "late")
        self.assertEqual(r.ex.sent, [])

    def test_a_rejection_and_a_bad_code_take_nothing(self):
        r = Run()
        r.canary.step(MON + 3600)
        r.answer(r.leg("BTC")["proposal"], "reject", MON + 3700, reason="not today")
        r.answer(r.leg("ETH")["proposal"], "approve", MON + 3700, code="000000")
        r.canary.step(MON + 3700)
        self.assertEqual(r.leg("BTC")["status"], "rejected")
        self.assertEqual(r.leg("ETH")["status"], "proposed")                 # an unauthenticated reply is silence
        self.assertEqual(r.ex.sent, [])

    def test_a_modified_entry_is_bought_at_the_smaller_size(self):
        r = Run(picks=("BTC",))
        r.canary.step(MON + 3600)
        r.answer(r.leg("BTC")["proposal"], "modify", MON + 3700, reason="smaller", notional=11.0)
        r.canary.step(MON + 3700)
        self.assertEqual(r.leg("BTC")["usd"], 11.0)
        self.assertLessEqual(r.ex.sent[0]["size"] * PX["BTC"], 11.0 + 1e-9)

    def test_a_decision_after_the_budget_proposes_nothing(self):
        r = Run()
        r.canary.step(C.deadline(MON))
        self.assertEqual(r.decided, [])
        self.assertEqual(r.canary.legs(), [])
        w = r.canary.db.execute("SELECT status FROM weeks").fetchone()
        self.assertEqual(w["status"], "late")

    def test_an_undecidable_week_is_tried_again(self):
        r = Run(picks=None)
        r.canary.step(MON + 3600)
        self.assertIsNone(r.canary.db.execute("SELECT 1 FROM weeks").fetchone())
        r.picks = ["BTC"]
        r.canary.step(MON + 3900)
        self.assertEqual(r.decided, [SUN, SUN])
        self.assertEqual(r.leg("BTC")["status"], "proposed")

    def test_a_disagreement_with_the_shadow_book_is_noted(self):
        r = Run(picks=("BTC",), shadow=["ETH"])
        r.canary.step(MON + 3600)
        note = r.canary.db.execute("SELECT note FROM weeks").fetchone()["note"]
        self.assertIn("shadow book", note)

    def test_both_rulings_are_journaled(self):
        r = Run(picks=("BTC",), holder_capital=0.0)
        r.canary.step(MON + 3600)
        leg = r.leg("BTC")
        self.assertTrue(json.loads(leg["ruling_testnet"])["allowed"])
        holder = json.loads(leg["ruling_holder"])
        self.assertFalse(holder["allowed"])
        self.assertIn("no capital", " ".join(holder["reasons"]))


class TestExitsAndTheRung(unittest.TestCase):
    def own(self, r, now=MON + 3600):
        """Approve every proposal, each with its own code: a code answers one reply only."""
        r.canary.step(now)
        t = now
        for coin in ("BTC", "ETH"):
            leg = r.leg(coin)
            if leg and leg["status"] == "proposed":
                t += 30
                r.answer(leg["proposal"], "approve", t)
        r.canary.step(t)

    def test_a_dropped_coin_is_sold_at_once_with_an_ioc_of_its_own_size_and_counts_a_round_trip(self):
        r = Run(picks=("BTC", "ETH"))
        self.own(r)
        r.picks = ["ETH"]
        r.canary.step(MON + 7 * 86_400 + 3600)
        exit_leg = r.leg("BTC", "exit")
        self.assertEqual(exit_leg["status"], "filled")
        sell = r.ex.sent[-1]
        self.assertEqual((sell["coin"], sell["side"], sell["tif"], sell["reduce_only"]), ("BTC", "sell", "Ioc", False))
        self.assertLess(sell["price"], PX["BTC"] * 0.999)                   # under the bid
        self.assertIsNone(exit_leg["proposal"])                              # exits never wait
        self.assertNotIn("BTC", r.canary.held())
        rung = r.canary.rung()
        self.assertEqual((rung["round_trips"], rung["needed"], rung["breaks"]), (1, 10, []))

    def test_a_fill_the_venue_does_not_have_is_a_break_and_does_not_count(self):
        r = Run(picks=("BTC",))
        self.own(r)
        r.picks = []
        r.canary.step(MON + 7 * 86_400 + 3600)
        r.ex.fill_log = r.ex.fill_log[:1]                                    # the exit's fill is missing at the venue
        rung = r.canary.rung()
        self.assertEqual(rung["round_trips"], 0)
        self.assertEqual(rung["breaks"], [r.leg("BTC", "exit")["id"]])

    def test_an_unfilled_exit_crosses_further_and_then_is_stuck(self):
        r = Run(picks=("BTC",))
        self.own(r)
        r.picks = []
        r.ex.fill_ratio = 0.0
        prices = []
        for k in range(C.EXIT_TRIES):
            r.canary.step(MON + 7 * 86_400 + 3600 + 60 * k)
            prices.append(r.ex.sent[-1]["price"])
        self.assertEqual(prices, sorted(prices, reverse=True))
        self.assertGreater(prices[0], prices[-1])
        self.assertEqual(r.leg("BTC", "exit")["status"], "stuck")
        self.assertTrue(any("stuck" in t for t, _ in r.notes))

    def test_a_partial_exit_under_the_minimum_waits_as_dust_then_sells_and_both_orders_count(self):
        r = Run(picks=("ETH",))
        self.own(r)
        r.picks = []
        held = r.canary.held()["ETH"]
        r.ex.fill_ratio = 0.5
        r.canary.step(W2)
        first = r.ex.sent[-1]["size"]
        self.assertAlmostEqual(first, held)
        r.ex.fill_ratio = 1.0
        n = len(r.ex.sent)
        r.canary.step(W2 + 300)
        r.canary.step(W2 + 600)
        self.assertEqual(len(r.ex.sent), n)                      # about $6 left: the venue would refuse it
        self.assertEqual(r.leg("ETH", "exit")["status"], "dust")
        self.assertEqual(len([t for t, _ in r.notes if "waiting" in t]), 1)       # told once, not every step
        self.assertIn("ETH", r.canary.held())
        was = PX["ETH"]
        PX["ETH"] = was * 2
        try:
            r.canary.step(W2 + 900)
        finally:
            PX["ETH"] = was
        self.assertAlmostEqual(r.ex.sent[-1]["size"], round(held - round(first * 0.5, 8), 4), places=4)
        leg = r.leg("ETH", "exit")
        self.assertEqual(leg["status"], "filled")
        self.assertEqual(len(C.leg_oids(leg)), 2)
        rung = r.canary.rung()
        self.assertEqual((rung["round_trips"], rung["breaks"]), (1, []))

    def test_a_leg_journaled_before_oids_counts_by_its_last_order(self):
        self.assertEqual(C.leg_oids({"oid": 7, "oids": None}), [7])
        self.assertEqual(C.leg_oids({"oid": 7, "oids": "[5, 7]"}), [5, 7])
        self.assertEqual(C.leg_oids({"oid": None}), [])
        fills = [{"oid": 5, "sz": "1", "px": "1", "crossed": True}, {"oid": 7, "sz": "2", "px": "1", "crossed": True}]
        leg = {"id": 1, "coin": "X", "filled": 3.0, "oid": 7, "oids": "[5, 7]"}
        self.assertEqual(C.matched([leg], fills, {"X": 1.0}), {1: True})
        self.assertEqual(C.matched([leg], fills[1:], {"X": 1.0}), {1: False})      # one of its orders is missing
        self.assertEqual(C.matched([dict(leg, oids=None)], fills, {"X": 1.0}), {1: False})

    def test_an_old_journal_gains_the_oids_column(self):
        import sqlite3
        d = Path(tempfile.mkdtemp())
        db = sqlite3.connect(d / C.DB)
        db.executescript(C.SCHEMA)                               # the schema as journals had it before 2026-11-09
        self.assertNotIn("oids", {r[1] for r in db.execute("PRAGMA table_info(legs)")})
        db.commit()
        db.close()
        c = C.Canary(d, FakeTestnet(), lambda s: None, key=KEY, log=lambda s: None)
        self.assertIn("oids", {r[1] for r in c.db.execute("PRAGMA table_info(legs)")})
        c.close()

    def test_an_exit_waiting_on_an_empty_book_is_not_written_twice_and_sells_once(self):
        r = Run(picks=("BTC", "ETH"))
        self.own(r)
        held = r.canary.held()["ETH"]
        r.picks = ["BTC"]
        r.ex.no_book = ("ETH",)
        r.canary.step(W2)                                        # dropped, but no book all week
        r.canary.step(W3)                                        # dropped still: no second leg
        self.assertEqual(len(r.canary.legs("coin='ETH' AND kind='exit'")), 1)
        r.ex.no_book = ()
        r.canary.step(W3 + 300)
        r.canary.step(W3 + 600)
        sells = [o for o in r.ex.sent if o["side"] == "sell" and o["coin"] == "ETH"]
        self.assertEqual(len(sells), 1)
        self.assertAlmostEqual(sells[0]["size"], held)
        self.assertNotIn("ETH", r.canary.held())

    def test_a_pending_exit_is_withdrawn_when_rule_8_picks_the_coin_again(self):
        r = Run(picks=("BTC", "ETH"))
        self.own(r)
        r.picks = ["BTC"]
        r.ex.no_book = ("ETH",)
        r.canary.step(W2)
        r.picks = ["BTC", "ETH"]
        r.canary.step(W3)
        r.ex.no_book = ()
        r.canary.step(W3 + 300)
        self.assertEqual(r.leg("ETH", "exit")["status"], "withdrawn")
        self.assertEqual([o for o in r.ex.sent if o["side"] == "sell"], [])
        self.assertIn("ETH", r.canary.held())
        self.assertEqual(len(r.canary.legs("coin='ETH' AND kind='entry'")), 1)      # held already: not bought again

    def test_a_coin_the_testnet_dropped_is_never_called_sold(self):
        r = Run(picks=("BTC", "ETH"))
        self.own(r)
        r.picks = ["BTC"]
        sd = r.ex.meta.pop("ETH")
        r.canary.step(W2)
        r.canary.step(W2 + 300)
        leg = r.leg("ETH", "exit")
        self.assertEqual((leg["status"], leg["filled"] or 0.0), ("unlisted", 0.0))
        self.assertIn("ETH", r.canary.held())
        self.assertEqual(len([t for t, _ in r.notes if "waiting" in t]), 1)
        r.canary.step(W3)
        self.assertEqual(len(r.canary.legs("coin='ETH' AND kind='exit'")), 1)
        r.ex.meta["ETH"] = sd                                    # listed again: it sells
        r.canary.step(W3 + 300)
        self.assertEqual(r.leg("ETH", "exit")["status"], "filled")
        self.assertNotIn("ETH", r.canary.held())

    def test_a_late_week_proposes_nothing_and_still_sells_what_rule_8_dropped(self):
        r = Run(picks=("BTC", "ETH"))
        self.own(r)
        r.picks = ["BTC", "SOL"]
        r.canary.step(W2 + C.ANSWER_WINDOW_S + 60)               # the Mac slept through Monday
        w = r.canary.db.execute("SELECT status FROM weeks ORDER BY sunday DESC").fetchone()
        self.assertEqual(w["status"], "late")
        self.assertIsNone(r.leg("SOL"))                          # no entry, no proposal
        self.assertEqual(r.leg("ETH", "exit")["status"], "filled")
        self.assertEqual(sorted(r.canary.held()), ["BTC"])


class TestStopAndRestart(unittest.TestCase):
    def test_the_stop_file_proposes_nothing_and_sells_only_what_the_canary_holds(self):
        r = Run(picks=("BTC",))
        r.canary.step(MON + 3600)
        r.answer(r.leg("BTC")["proposal"], "approve", MON + 3660)
        r.canary.step(MON + 3660)
        (r.state / C.STOP).write_text("")
        r.picks = ["BTC", "ETH"]
        r.canary.step(MON + 7 * 86_400 + 3600)
        self.assertEqual(r.leg("ETH")["status"], "stopped")
        sells = [o for o in r.ex.sent if o["side"] == "sell"]
        self.assertEqual([(o["coin"], o["reduce_only"]) for o in sells], [("BTC", False)])
        self.assertEqual(r.canary.held(), {})

    def test_the_kill_file_counts_as_a_stop(self):
        r = Run(picks=("BTC",))
        (r.state / C.KILL).write_text("")
        r.canary.step(MON + 3600)
        self.assertEqual(r.leg("BTC")["status"], "stopped")

    def test_an_order_sent_before_a_restart_is_found_by_its_client_id_and_never_sent_twice(self):
        r = Run(picks=("BTC",))
        r.canary.step(MON + 3600)
        r.answer(r.leg("BTC")["proposal"], "approve", MON + 3660)
        r.canary.step(MON + 3660)
        sent = list(r.ex.sent)
        leg = r.leg("BTC")
        # the crash: the venue filled it, but the journal still says it is in flight with nothing recorded
        r.canary._set(leg["id"], status="approved", inflight=leg["cloid"] or C.cloid(SUN, "BTC", "entry", 0),
                      filled=0, oid=None, avg_px=None)
        r.canary.db.commit()
        r.canary.step(MON + 3720)
        self.assertEqual(r.ex.sent, sent)
        leg = r.leg("BTC")
        self.assertEqual(leg["status"], "filled")
        self.assertGreater(leg["filled"], 0)
        self.assertIsNotNone(leg["avg_px"])
        self.assertIn("client id", leg["note"])

    def test_an_order_that_never_arrived_is_sent_again(self):
        r = Run(picks=("BTC",))
        r.canary.step(MON + 3600)
        # the crash: approved and journaled as in flight under try 0, but the order never reached the venue
        leg = r.leg("BTC")
        r.canary._set(leg["id"], status="approved", inflight="0x" + "f" * 32, tries=1)
        r.canary.db.commit()
        r.canary.step(MON + 3720)
        self.assertEqual(len(r.ex.sent), 1)
        self.assertEqual(r.ex.sent[0]["cloid"], C.cloid(SUN, "BTC", "entry", 1))
        self.assertEqual(r.leg("BTC")["status"], "filled")


class TestSummary(unittest.TestCase):
    def test_the_summary_reads_the_journal(self):
        r = Run()
        r.canary.step(MON + 3600)
        r.canary.close()
        lines = C.summary(r.state)
        self.assertIn("week of 2026-11-01: decided", lines[0])
        self.assertTrue(any("entry proposed: 2" in s for s in lines))
        self.assertEqual(C.summary(Path(tempfile.mkdtemp())), ["#8 canary: no journal yet"])


if __name__ == "__main__":
    unittest.main()
