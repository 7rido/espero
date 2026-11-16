"""#83's book and criteria, on synthetic books and funding only: nothing is read from the network."""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from espero import spotcarry as S

T0 = S._utc(2026, 11, 22, 23, 33)        # a pass before the window: records only
ENTRY = S._utc(2026, 11, 23, 0, 33)      # the first pass in the window
NEXT = S._utc(2026, 11, 23, 1, 33)
HOUR_1 = S._utc(2026, 11, 23, 1, 0)
HOUR_0 = S._utc(2026, 11, 23, 0, 0)


def raw_book(bids, asks):
    return {"levels": [[{"px": str(p), "sz": str(s)} for p, s in bids],
                       [{"px": str(p), "sz": str(s)} for p, s in asks]]}


def flat_book(bid, ask, size=10.0):
    return ([(bid, size), (bid - 1, size)], [(ask, size), (ask + 1, size)])


def books_for(spot_mid=100.0, perp_mid=100.0, spot_size=10.0, perp_size=10.0):
    sb, sa = flat_book(spot_mid - 0.05, spot_mid + 0.05, spot_size)
    pb, pa = flat_book(perp_mid - 0.05, perp_mid + 0.05, perp_size)
    return {c: (sb, sa, pb, pa) for c in S.COINS}


def fake_post(books, funding, meta=None, fail=()):
    """A stand-in for Hyperliquid's info endpoint: books, funding, the pair list, and the reads that fail."""
    calls = []

    def post(body):
        calls.append(body)
        if body["type"] in fail:
            raise OSError(f"{body['type']} failed")
        if body["type"] == "spotMeta":
            return meta or SPOT_META
        if body["type"] == "l2Book":
            coin = body["coin"]
            name = {v: k for k, v in S.PAIR_HINT.items()}
            key = name.get(coin, coin)
            sb, sa, pb, pa = books[key] if key in books else books[coin]
            return raw_book(sb, sa) if coin.startswith("@") else raw_book(pb, pa)
        if body["type"] == "fundingHistory":
            return [{"time": ms, "fundingRate": str(r)} for ms, r in funding.get(body["coin"], [])]
        raise AssertionError(body)
    post.calls = calls
    return post


SPOT_META = {
    "tokens": [{"index": 0, "name": "USDC"}, {"index": 197, "name": "UBTC"}, {"index": 221, "name": "UETH"}],
    "universe": [{"name": "@142", "index": 142, "tokens": [197, 0]},
                 {"name": "@151", "index": 151, "tokens": [221, 0]}],
}


def ms(ts):
    return ts * 1000


class TestBooks(unittest.TestCase):
    def test_buying_dollars_walks_the_asks_across_levels(self):
        asks = [(100.0, 0.5), (101.0, 1.0)]
        qty, spent = S.fill_usd(asks, 100.0)
        self.assertAlmostEqual(qty, 0.5 + 50.0 / 101.0)
        self.assertEqual(spent, 100.0)

    def test_selling_coins_walks_the_bids_across_levels(self):
        bids = [(100.0, 0.5), (99.0, 1.0)]
        self.assertAlmostEqual(S.fill_qty(bids, 1.0), 50.0 + 49.5)

    def test_a_thin_book_raises_rather_than_trading_on_a_fill_it_cannot_see(self):
        with self.assertRaises(ValueError):
            S.fill_qty([(100.0, 0.5)], 1.0)
        with self.assertRaises(ValueError):
            S.fill_usd([(100.0, 0.5)], 100.0)

    def test_mid_is_the_middle_of_the_top_of_book(self):
        self.assertEqual(S.mid([(99.0, 1)], [(101.0, 1)]), 100.0)


class TestAccounting(unittest.TestCase):
    def test_funding_positive_rate_pays_the_short(self):
        leg = S.Leg("BTC", entry_ts=T0)
        leg.perp = 2.0
        self.assertAlmostEqual(leg.credit(HOUR_1, 0.0001, 100.0), 0.02)
        self.assertGreater(leg.funding, 0)

    def test_funding_negative_rate_charges_the_short(self):
        leg = S.Leg("BTC", entry_ts=T0)
        leg.perp = 2.0
        self.assertAlmostEqual(leg.credit(HOUR_1, -0.0001, 100.0), -0.02)

    def test_an_hour_settled_before_entry_is_not_paid(self):
        leg = S.Leg("BTC")
        leg.enter(ENTRY, [(100.0, 10.0)], [(100.0, 10.0)])
        self.assertEqual(leg.credit(HOUR_0, 0.0001, 100.0), 0.0)     # 00:00 settled before the 00:33 entry
        self.assertGreater(leg.credit(HOUR_1, 0.0001, 100.0), 0.0)

    def test_entry_buys_a_hundred_dollars_of_spot_and_shorts_the_same_coins(self):
        leg = S.Leg("BTC")
        leg.enter(ENTRY, [(100.0, 10.0)], [(100.0, 10.0)])
        self.assertAlmostEqual(leg.spot, 1.0)
        self.assertAlmostEqual(leg.perp, 1.0)
        self.assertAlmostEqual(leg.cash, CAP - 100.0 + 100.0)     # spot paid, perp proceeds in
        self.assertAlmostEqual(leg.fees, 100.0 * S.FEE_SPOT + 100.0 * S.FEE_PERP)

    def test_rebalance_fires_above_five_percent_and_not_at_it(self):
        leg = S.Leg("BTC", cash=0.0, spot=1.0, perp=1.0)
        self.assertEqual(leg.rebalance(100.0, 105.0, [(105.0, 10)], [(105.0, 10)]), 0.0)   # exactly 5%: no trade
        self.assertEqual(leg.perp, 1.0)
        leg = S.Leg("BTC", cash=0.0, spot=1.0, perp=0.8)
        moved = leg.rebalance(100.0, 100.0, [(100.0, 10)], [(100.0, 10)])   # 20% gap: sell 0.2 more on the perp
        self.assertAlmostEqual(moved, 0.2)
        self.assertAlmostEqual(leg.perp, 1.0)
        self.assertGreater(leg.cash, 0.0)

    def test_the_exit_is_charged(self):
        leg = S.Leg("BTC")
        leg.enter(ENTRY, [(100.0, 10.0)], [(100.0, 10.0)])
        before = leg.fees
        leg.exit(S.WINDOW_END, [(100.0, 10.0)], [(100.0, 10.0)])
        self.assertGreater(leg.fees, before)
        self.assertEqual((leg.spot, leg.perp), (0.0, 0.0))
        self.assertTrue(leg.exited)

    def test_marks_equal_cash_plus_spot_minus_perp_plus_funding_minus_fees(self):
        leg = S.Leg("BTC")
        leg.enter(ENTRY, [(100.0, 10.0)], [(100.0, 10.0)])
        leg.credit(HOUR_1, 0.0001, 100.0)
        spot_mid, perp_mid = 102.0, 101.0
        expected = leg.cash + leg.spot * spot_mid - leg.perp * perp_mid + leg.funding - leg.fees
        self.assertAlmostEqual(leg.equity(spot_mid, perp_mid), expected)
        self.assertAlmostEqual(leg.equity(100.0, 100.0), CAP - leg.fees + leg.funding, places=6)


CAP = S.CAPITAL


class TestPassAndStore(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.state = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def run_at(self, ts, post):
        return S.run_pass(self.state, post=post, sleep=lambda s: None, clock=lambda: ts)

    def test_nothing_enters_before_the_window_and_a_pass_only_records(self):
        self.run_at(T0, fake_post(books_for(), {}))
        legs = S.Store(self.state / "spotcarry.db").legs()
        self.assertFalse(any(l.entered for l in legs.values()))
        raw = self.state / "spotcarry" / "2026-11-22.jsonl"
        self.assertTrue(raw.exists())
        self.assertEqual(len(raw.read_text().splitlines()), 1)

    def test_the_book_enters_at_the_first_pass_in_the_window(self):
        self.run_at(ENTRY, fake_post(books_for(), {}))
        legs = S.Store(self.state / "spotcarry.db").legs()
        self.assertTrue(all(l.entered for l in legs.values()))
        self.assertAlmostEqual(legs["BTC"].spot, 100.0 / 100.05)     # $100 walked up the asks at 100.05

    def test_an_hour_is_credited_once_across_a_restart(self):
        funding = {"BTC": [(HOUR_1 * 1000, 0.0001)], "ETH": []}
        self.run_at(ENTRY, fake_post(books_for(), funding))
        self.run_at(NEXT, fake_post(books_for(), funding))
        once = S.Store(self.state / "spotcarry.db").legs()["BTC"].funding
        # a restart: a fresh process reads the same hour again from the endpoint
        self.run_at(NEXT + 60, fake_post(books_for(), funding))
        again = S.Store(self.state / "spotcarry.db").legs()["BTC"].funding
        self.assertGreater(once, 0)
        self.assertAlmostEqual(again, once)
        db = S.Store(self.state / "spotcarry.db")
        n = db.db.execute("SELECT COUNT(*) FROM credits WHERE coin='BTC' AND hour=?", (HOUR_1,)).fetchone()[0]
        self.assertEqual(n, 1)

    def test_a_failed_read_is_a_gap_and_trades_nothing(self):
        self.run_at(ENTRY, fake_post(books_for(), {}, fail=("l2Book",)))
        store = S.Store(self.state / "spotcarry.db")
        self.assertFalse(any(l.entered for l in store.legs().values()))
        row = store.db.execute("SELECT ok FROM passes WHERE ts=?", (ENTRY,)).fetchone()
        self.assertEqual(row["ok"], 0)

    def test_the_pair_names_are_resolved_from_spotmeta_by_token(self):
        self.assertEqual(S.resolve_pairs(SPOT_META), {"BTC": "@142", "ETH": "@151"})
        renamed = {"tokens": SPOT_META["tokens"],
                   "universe": [{"name": "@900", "index": 900, "tokens": [197, 0]},
                                {"name": "@901", "index": 901, "tokens": [221, 0]}]}
        self.assertEqual(S.resolve_pairs(renamed), {"BTC": "@900", "ETH": "@901"})

    def test_the_raw_pass_is_written_before_the_book_uses_it(self):
        self.run_at(ENTRY, fake_post(books_for(), {}))
        line = json.loads((self.state / "spotcarry" / "2026-11-23.jsonl").read_text().splitlines()[0])
        self.assertIn("l2:BTC", line["raw"])
        self.assertIn("funding:ETH", line["raw"])


def weekly_with_t(target):
    """Nineteen weekly returns whose Newey-West t is `target`: a mean shift on an alternating pattern, bisected."""
    z = [(-1.0) ** k for k in range(19)]
    lo, hi = 0.0, 0.1
    for _ in range(80):
        mid_ = (lo + hi) / 2
        t, _ = S.p_of_t([mid_ + 0.001 * v for v in z])
        lo, hi = (mid_, hi) if t < target else (lo, mid_)
    return [(lo + 0.001 * v) for v in z]


class TestVerdict(unittest.TestCase):
    def passing(self, **over):
        weekly = [0.01 + (0.001 if k % 2 else -0.001) for k in range(19)]
        kw = dict(weekly=weekly, complete=18, book_return=0.05, days=129.0,
                  coin_returns={"BTC": 0.02, "ETH": 0.03}, hedge_gap=0.001, ok_slots=3000, slots=S.HOURS_IN_WINDOW,
                  family_p=[0.3, 0.5], closed=True)
        kw.update(over)
        return kw

    def test_everything_holding_passes(self):
        r = S.judge(**self.passing())
        self.assertTrue(all(r["criteria"].values()), r["criteria"])
        self.assertEqual(r["verdict"], "PASS")

    def test_each_criterion_misses_on_its_own(self):
        misses = {
            "1_pays": dict(book_return=-0.01),
            "2_rate": dict(book_return=0.001, days=129.0),
            "3_stat": dict(weekly=[0.01, -0.01] * 9 + [0.0]),
            "4_hedge": dict(hedge_gap=0.02),
            "5_both": dict(coin_returns={"BTC": -0.01, "ETH": 0.03}),
            "6_record": dict(ok_slots=2000),
        }
        for name, over in misses.items():
            r = S.judge(**self.passing(**over))
            self.assertFalse(r["criteria"][name], name)
            self.assertEqual(r["verdict"], "FAIL", name)

    def test_under_twelve_complete_weeks_is_inconclusive(self):
        self.assertEqual(S.judge(**self.passing(complete=11))["verdict"], "INCONCLUSIVE")
        self.assertEqual(S.judge(**self.passing(complete=12))["verdict"], "PASS")

    def test_nothing_is_judged_before_the_window_closes(self):
        self.assertEqual(S.judge(**self.passing(closed=False))["verdict"], "running")

    def test_the_bh_bar_is_a_second_bar_on_the_same_t(self):
        weekly = weekly_with_t(3.1)              # t >= 3 holds, p about 0.005
        t, p = S.p_of_t(weekly)
        self.assertGreaterEqual(t, 3.0)
        alone = S.judge(**self.passing(weekly=weekly, family_p=[]))
        self.assertTrue(alone["criteria"]["3_stat"])
        crowded = S.judge(**self.passing(weekly=weekly, family_p=[0.5] * 40))   # 41 tests: q = 41 p, far above 0.05
        self.assertGreater(crowded["bh_q"], 0.05)
        self.assertFalse(crowded["criteria"]["3_stat"])

    def test_week_returns_cover_eighteen_full_weeks_and_a_stub(self):
        pts = [(S.WINDOW_START - 1800, 300.0), (S.WINDOW_END - 1800, 303.0)]
        rets, complete = S.week_returns(pts, S.WINDOW_END)
        self.assertEqual(len(rets), 19)
        self.assertEqual(complete, 18)
        self.assertAlmostEqual(sum(rets), 0.01)

    def test_the_window_is_129_days_and_3096_hours(self):
        self.assertEqual(S.HOURS_IN_WINDOW, 129 * 24)
        self.assertEqual(len(S.MONDAYS), 19)
        self.assertEqual(S.dt.datetime.fromtimestamp(S.WINDOW_START, S.UTC).strftime("%A"), "Monday")


class TestBoundaries(unittest.TestCase):
    """Each bar at its exact value: the registered word is 'at or above', 'above', 'at most' or 'under'."""

    def test_rebalance_does_not_fire_at_exactly_the_bar(self):
        with mock.patch.object(S, "REBALANCE", 0.25):            # 25% is exact in binary: 25 of 100 is the bar
            leg = S.Leg("BTC", spot=1.0, perp=0.75)
            self.assertEqual(leg.rebalance(100.0, 100.0, [(100.0, 10)], [(100.0, 10)]), 0.0)
            self.assertEqual(leg.perp, 0.75)
            leg = S.Leg("BTC", spot=1.0, perp=0.74)
            self.assertAlmostEqual(leg.rebalance(100.0, 100.0, [(100.0, 10)], [(100.0, 10)]), 0.26)

    def test_an_hour_after_the_exit_is_not_paid(self):
        leg = S.Leg("BTC")
        leg.enter(ENTRY, [(100.0, 10.0)], [(100.0, 10.0)])
        leg.exit(NEXT, [(100.0, 10.0)], [(100.0, 10.0)])
        self.assertFalse(leg.held_at(NEXT + 3600))      # an hour after the exit is not the position's
        self.assertTrue(leg.held_at(NEXT))              # the exit's own hour still is

    def test_the_exit_is_the_last_pass_whose_next_pass_would_be_outside_the_window(self):
        legs = {c: S.Leg(c) for c in S.COINS}
        books = books_for()
        S.apply_pass(legs, ENTRY, books, {}, set())
        S.apply_pass(legs, S._utc(2027, 3, 31, 22, 33), books, {}, set())
        self.assertFalse(any(l.exited for l in legs.values()))
        S.apply_pass(legs, S._utc(2027, 3, 31, 23, 33), books, {}, set())
        self.assertTrue(all(l.exited for l in legs.values()))

    def test_the_rate_bar_is_at_or_above(self):
        with mock.patch.object(S, "RATE_MIN", 0.125):
            weekly = [0.01 + (0.001 if k % 2 else -0.001) for k in range(19)]
            r = S.judge(weekly=weekly, complete=18, book_return=0.125, days=365.0,
                        coin_returns={"BTC": 0.1, "ETH": 0.1}, hedge_gap=0.0, ok_slots=100, slots=100,
                        family_p=[], closed=True)
            self.assertTrue(r["criteria"]["2_rate"])

    def test_the_t_bar_is_at_or_above(self):
        weekly = weekly_with_t(3.1)
        t, _ = S.p_of_t(weekly)
        with mock.patch.object(S, "T_MIN", t):
            r = S.judge(weekly=weekly, complete=18, book_return=0.05, days=129.0, coin_returns={"BTC": 0.1},
                        hedge_gap=0.0, ok_slots=100, slots=100, family_p=[], closed=True)
            self.assertTrue(r["criteria"]["3_stat"])

    def test_the_hedge_and_record_bars_are_inclusive(self):
        weekly = [0.01 + (0.001 if k % 2 else -0.001) for k in range(19)]
        r = S.judge(weekly=weekly, complete=18, book_return=0.05, days=129.0, coin_returns={"BTC": 0.1},
                    hedge_gap=S.HEDGE_MAX, ok_slots=95, slots=100, family_p=[], closed=True)
        self.assertTrue(r["criteria"]["4_hedge"])
        self.assertTrue(r["criteria"]["6_record"])

    def test_the_pacer_waits_out_the_quiet_minutes_including_minute_27(self):
        clock_vals = iter([S._utc(2026, 11, 23, 0, 27), S._utc(2026, 11, 23, 0, 28), S._utc(2026, 11, 23, 0, 28)])
        sleeps = []
        pacer = S.Pacer(lambda body: "ok", sleep=sleeps.append, clock=lambda: next(clock_vals))
        self.assertEqual(pacer({"type": "x"}), "ok")
        self.assertEqual(sleeps, [20])

    def test_the_pacer_spaces_calls_at_least_two_seconds_apart(self):
        sleeps = []
        pacer = S.Pacer(lambda body: "ok", sleep=sleeps.append, clock=lambda: S._utc(2026, 11, 23, 0, 33))
        pacer({"type": "a"})
        pacer({"type": "b"})
        self.assertEqual(len(sleeps), 1)
        self.assertAlmostEqual(sleeps[0], S.GAP_S)

    def test_a_week_counts_once_its_closing_monday_has_come(self):
        pts = [(S.WINDOW_START - 1800, 300.0)]
        _, complete = S.week_returns(pts, S.MONDAYS[5])
        self.assertEqual(complete, 5)
        _, complete = S.week_returns(pts, S.MONDAYS[5] - 1)
        self.assertEqual(complete, 4)


if __name__ == "__main__":
    unittest.main()
