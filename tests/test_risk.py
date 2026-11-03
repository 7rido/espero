"""The risk gate is the last thing between a signal and money."""
from __future__ import annotations

import contextlib
import io
import unittest
from dataclasses import replace

from espero import risk as R
from espero.risk import RiskLimits, check_buy, check_sell, size_position


class TestSizing(unittest.TestCase):
    def test_risk_based_size_is_capped_by_position_limit(self):
        limits = RiskLimits(risk_per_trade=0.01, stop_pct=0.05, max_position_pct=0.25)
        # 1% of 500 = $5 risk -> $100 notional at a 5% stop
        self.assertAlmostEqual(size_position(500, 0.9, limits), 100.0)

    def test_position_cap_wins_when_stop_is_tight(self):
        limits = RiskLimits(risk_per_trade=0.05, stop_pct=0.01, max_position_pct=0.10)
        self.assertAlmostEqual(size_position(1_000, 0.9, limits), 100.0)

    def test_no_equity_no_size(self):
        self.assertEqual(size_position(0, 0.9, RiskLimits()), 0.0)


class TestGate(unittest.TestCase):
    def setUp(self):
        self.limits = RiskLimits()

    def test_blocks_second_position(self):
        d = check_buy(500, 500, open_positions=1, day_pnl=0, confidence=0.9,
                      limits=self.limits)
        self.assertFalse(d.allowed)
        self.assertIn("max open", d.reason)

    def test_blocks_after_daily_loss_cap(self):
        d = check_buy(500, 500, open_positions=0, day_pnl=-16.0, confidence=0.9,
                      limits=self.limits)
        self.assertFalse(d.allowed)
        self.assertIn("daily loss", d.reason)

    def test_allows_a_normal_trade(self):
        d = check_buy(500, 500, open_positions=0, day_pnl=0, confidence=0.9,
                      limits=self.limits)
        self.assertTrue(d.allowed)
        self.assertAlmostEqual(d.notional, 100.0)

    def test_blocks_when_cash_is_too_small(self):
        d = check_buy(500, 5, open_positions=0, day_pnl=0, confidence=0.9,
                      limits=self.limits)
        self.assertFalse(d.allowed)

    def test_sell_requires_a_position(self):
        self.assertFalse(check_sell(0).allowed)
        self.assertTrue(check_sell(1).allowed)


# ---------------------------------------------------------------------- the account's gate
HL = "hyperliquid"


def account(**kw) -> R.Account:
    base = dict(capital=10_000.0, equity=10_000.0, equity_by_venue={HL: 5_000.0, "binance": 5_000.0},
                positions=(), day_start=10_000.0, week_start=10_000.0, peak=10_000.0,
                sleeve_scale={"s": 1.0}, sigma_daily={"BTC": 0.025, "ALT": 0.06})
    base.update(kw)
    return R.Account(**base)


def order(**kw) -> R.Order:
    base = dict(sleeve="s", rule="12", venue=HL, coin="BTC", side=1, notional=1_000.0)
    base.update(kw)
    return R.Order(**base)


def pos(**kw) -> R.Position:
    base = dict(venue=HL, coin="BTC", sleeve="s", side=1, notional=1_000.0)
    base.update(kw)
    return R.Position(**base)


class TestThePolicy(unittest.TestCase):
    def test_the_document_and_the_code_hold_the_same_numbers(self):
        self.assertEqual(R.doc_table(), R.policy_table())
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(R.main([]), 0)

    def test_a_number_changed_on_one_side_only_fails(self):
        import tempfile
        from pathlib import Path

        text = R.POLICY_DOC.read_text(encoding="utf-8").replace("| `per_coin` | 0.20 |", "| `per_coin` | 0.25 |")
        with tempfile.TemporaryDirectory() as d:
            doc = Path(d) / "RISK_POLICY.md"
            doc.write_text(text, encoding="utf-8")
            self.assertEqual(R.doc_table(doc)["per_coin"], 0.25)
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(R.main([], doc=doc), 1)

    def test_the_hash_names_the_numbers(self):
        self.assertEqual(R.policy_hash(), R.policy_hash(R.Policy()))
        self.assertNotEqual(R.policy_hash(), R.policy_hash(replace(R.POLICY, per_coin=0.25)))
        self.assertEqual(R.check(order(), account()).policy_hash, R.policy_hash())

    def test_the_registered_numbers(self):
        self.assertEqual((R.POLICY.leverage, R.POLICY.per_coin, R.POLICY.per_venue, R.POLICY.day_stop,
                          R.POLICY.week_stop), (1.0, 0.20, 0.50, -0.02, -0.05))


class TestRefusals(unittest.TestCase):
    def test_no_capital_no_order(self):
        r = R.check(order(), account(capital=0.0))
        self.assertFalse(r.allowed)
        self.assertIn("no capital allocated", r.reasons[0])

    def test_breaks_pauses_acks_and_unallocated_sleeves_refuse_entries(self):
        for kw, text in ((dict(breaks=("x: missing fill",)), "an open break"), (dict(paused=True), "paused"),
                         (dict(awaiting_ack=True), "acknowledgement"), (dict(sleeve_scale={}), "no allocation")):
            r = R.check(order(), account(**kw))
            self.assertFalse(r.allowed, kw)
            self.assertIn(text, r.reasons[0])

    def test_an_order_needs_a_side_and_a_size(self):
        """By the guard itself: a zero or negative size was otherwise refused by the minimum, for another reason."""
        for o in (order(side=0), order(notional=0.0), order(notional=-50.0), order(notional=float("nan"))):
            r = R.check(o, account())
            self.assertFalse(r.allowed)
            self.assertEqual(r.reasons[0], "an order needs a side and a size")

    def test_reduce_only_passes_every_pause_and_stop(self):
        """A flatten must go through whatever stopped the entries: no capital, a pause, a break, an ack awaited."""
        held = (pos(side=1, notional=1_000.0),)
        for kw in (dict(capital=0.0), dict(paused=True), dict(breaks=("x: off",)), dict(awaiting_ack=True),
                   dict(equity=9_400.0)):
            r = R.check(order(side=-1, notional=5_000.0, reduce_only=True), account(positions=held, **kw))
            self.assertTrue(r.allowed, kw)
            self.assertEqual(r.notional, 1_000.0, kw)
        spot = R.check(order(side=-1, reduce_only=True, leg="spot"), account(positions=held))
        self.assertFalse(spot.allowed)                       # the perp is held, not a spot leg


class TestCaps(unittest.TestCase):
    def test_a_small_order_passes_whole(self):
        r = R.check(order(notional=500.0), account())
        self.assertTrue(r.allowed)
        self.assertEqual((r.notional, r.reasons), (500.0, ("within every cap",)))

    def test_per_coin_cuts_to_twenty_percent_of_the_base(self):
        r = R.check(order(notional=5_000.0), account())
        self.assertTrue(r.allowed)
        self.assertAlmostEqual(r.notional, 2_000.0)
        self.assertTrue(any(x.startswith("per coin") for x in r.reasons))
        held = account(positions=(pos(notional=1_500.0),))
        self.assertAlmostEqual(R.check(order(notional=5_000.0), held).notional, 500.0)

    def test_the_base_is_the_smaller_of_allocation_and_equity(self):
        r = R.check(order(notional=5_000.0), account(equity=9_900.0, day_start=9_950.0, week_start=9_950.0))
        self.assertAlmostEqual(r.notional, 0.2 * 9_900.0)
        r = R.check(order(notional=5_000.0), account(capital=5_000.0))
        self.assertAlmostEqual(r.notional, 1_000.0)

    def test_per_venue_counts_every_leg(self):
        held = account(positions=(pos(coin="ETH", notional=2_000.0), pos(coin="SOL", leg="spot", notional=2_500.0)))
        r = R.check(order(notional=2_000.0), held)
        self.assertAlmostEqual(r.notional, 500.0)
        self.assertTrue(any(x.startswith("per venue") for x in r.reasons))

    def test_venue_leverage_uses_the_equity_held_there(self):
        r = R.check(order(notional=2_000.0), account(equity_by_venue={HL: 800.0}))
        self.assertAlmostEqual(r.notional, 800.0)
        self.assertTrue(any(x.startswith("venue leverage") for x in r.reasons))
        self.assertFalse(R.check(order(), account(equity_by_venue={})).allowed)

    def test_account_leverage_counts_perp_legs_only(self):
        held = account(equity_by_venue={HL: 10_000.0, "binance": 10_000.0},
                       positions=(pos(venue="binance", coin="ETH", notional=4_900.0),
                                  pos(venue="binance", coin="SOL", notional=4_900.0)))
        r = R.check(order(notional=2_000.0), held)
        self.assertAlmostEqual(r.notional, 200.0)
        self.assertTrue(any(x.startswith("leverage") for x in r.reasons))

    def test_a_sleeve_is_held_to_its_scale(self):
        r = R.check(order(notional=2_000.0), account(sleeve_scale={"s": 0.05}))
        self.assertAlmostEqual(r.notional, 500.0)
        self.assertTrue(any(x.startswith("per sleeve") for x in r.reasons))

    def test_below_the_venues_minimum_after_the_caps_is_refused(self):
        r = R.check(order(notional=2_000.0), account(sleeve_scale={"s": 0.0009}))
        self.assertFalse(r.allowed)
        self.assertIn("minimum", r.reasons[0])
        self.assertTrue(R.check(order(notional=10.0), account(sleeve_scale={"s": 0.001})).allowed)


class TestLiquidationAndFunding(unittest.TestCase):
    def test_at_one_times_the_liquidation_cap_never_binds(self):
        r = R.check(order(notional=5_000.0, coin="ALT"), account(equity_by_venue={HL: 1_000.0}))
        self.assertAlmostEqual(r.notional, 1_000.0)
        self.assertGreater(r.checks["liquidation distance"][0], r.checks["venue leverage"][0])

    def test_a_volatile_coin_needs_more_room(self):
        loose = replace(R.POLICY, venue_leverage=10.0, per_coin=10.0, per_venue=10.0, leverage=10.0)
        a = account(equity_by_venue={HL: 1_000.0})
        calm = R.check(order(notional=50_000.0, coin="BTC"), a, loose)
        wild = R.check(order(notional=50_000.0, coin="ALT"), a, loose)
        self.assertAlmostEqual(calm.notional, 1_000.0 / (0.25 + 0.005))         # the 25 % floor binds
        self.assertAlmostEqual(wild.notional, 1_000.0 / (8 * 0.06 + 0.005))     # eight daily sigmas bind
        self.assertTrue(any(x.startswith("liquidation distance") for x in wild.reasons))

    def test_a_sigma_or_margin_rate_that_is_not_a_number_is_refused(self):
        nan = float("nan")
        r = R.check(order(coin="BTC"), account(sigma_daily={"BTC": nan}))
        self.assertFalse(r.allowed)
        self.assertIn("not a number", r.reasons[0])
        self.assertFalse(R.check(order(mmr=-0.25), account()).allowed)          # would divide by zero
        self.assertFalse(R.check(order(mmr=nan), account()).allowed)
        self.assertTrue(R.check(order(coin="XYZ"), account()).allowed)          # a coin with no sigma: the floor

    def test_a_sleeve_scale_above_one_is_one(self):
        r = R.check(order(notional=100_000.0), account(sleeve_scale={"s": 3.0}))
        self.assertEqual(r.checks["per sleeve"][1], R.POLICY.per_sleeve * 10_000.0)

    def test_a_position_already_near_liquidation_blocks_entries_there(self):
        near = account(positions=(pos(coin="ETH", liq_px=1_800.0, mark=2_000.0),))
        r = R.check(order(), near)
        self.assertFalse(r.allowed)
        self.assertIn("liquidation price", r.reasons[0])
        far = account(positions=(pos(coin="ETH", liq_px=1_000.0, mark=2_000.0),))
        self.assertTrue(R.check(order(), far).allowed)

    def test_the_distance_is_the_whole_books(self):
        a = account(equity_by_venue={HL: 1_000.0}, positions=(pos(notional=2_000.0),))
        self.assertAlmostEqual(R.liq_distance(a, HL), (1_000.0 - 0.005 * 2_000.0) / 2_000.0)
        self.assertEqual(R.liq_distance(account(), HL), float("inf"))

    def test_paying_funding_is_capped_and_being_paid_is_not(self):
        hot = 0.003                                         # 0.3 % per 8 h: 0.9 % a day
        long_pays = R.check(order(notional=5_000.0, funding_8h=hot), account())
        self.assertAlmostEqual(long_pays.notional, 0.0010 * 10_000.0 / (3 * hot))
        self.assertTrue(any(x.startswith("funding, this position") for x in long_pays.reasons))
        short_paid = R.check(order(notional=1_500.0, side=-1, funding_8h=hot), account())   # under the coin cap
        self.assertAlmostEqual(short_paid.notional, 1_500.0)

    def test_a_position_already_held_uses_its_own_allowance(self):
        hot = 0.003
        held = account(positions=(pos(notional=500.0, funding_8h=hot),))
        r = R.check(order(notional=5_000.0, funding_8h=hot), held)
        self.assertAlmostEqual(r.notional, 0.0010 * 10_000.0 / (3 * hot) - 500.0)

    def test_the_accounts_whole_allowance_binds_when_others_use_it(self):
        hot = 0.003
        held = account(positions=(pos(coin="ETH", notional=2_000.0, funding_8h=hot),))   # pays $18 of $20 a day
        r = R.check(order(notional=5_000.0, funding_8h=hot), held)
        self.assertAlmostEqual(r.notional, (0.002 * 10_000.0 - 2_000.0 * 3 * hot) / (3 * hot))
        self.assertTrue(any(x.startswith("funding, all") for x in r.reasons))

    def test_funding_already_paid_uses_the_allowance(self):
        held = account(positions=(pos(coin="ETH", notional=1_500.0, funding_8h=0.0004),))
        paid = 1_500.0 * 0.0004 * 3
        r = R.check(order(notional=2_000.0, funding_8h=0.0004), held)
        self.assertAlmostEqual(r.notional, min(2_000.0, (0.002 * 10_000.0 - paid) / (3 * 0.0004)))


class TestStops(unittest.TestCase):
    def test_the_stops_fire_at_their_lines_most_severe_first(self):
        self.assertEqual(R.stop_state(account()), "ok")
        self.assertEqual(R.stop_state(account(equity=9_800.0)), "day")
        self.assertEqual(R.stop_state(account(equity=9_801.0)), "ok")
        self.assertEqual(R.stop_state(account(equity=9_500.0, day_start=9_600.0)), "week")
        self.assertEqual(R.stop_state(account(equity=9_501.0, day_start=9_600.0)), "ok")
        self.assertEqual(R.stop_state(account(equity=8_500.0, peak=10_000.0, holder_stop=-0.15)), "holder")
        self.assertEqual(R.stop_state(account(equity=8_501.0, day_start=8_600.0, week_start=8_600.0, peak=10_000.0,
                                              holder_stop=-0.15)), "ok")

    def test_the_most_severe_stop_wins(self):
        self.assertEqual(R.stop_state(account(equity=9_500.0)), "week")          # the day's -5 % too
        self.assertEqual(R.stop_state(account(equity=8_000.0, holder_stop=-0.15)), "holder")

    def test_a_stop_refuses_entries_and_says_what_it_does(self):
        r = R.check(order(), account(equity=9_800.0))
        self.assertFalse(r.allowed)
        self.assertIn("day stop", r.reasons[0])
        self.assertIn("run to their registered exits", r.reasons[0])
        self.assertIn("flatten", " ".join(R.on_stop("week")))
        self.assertIn("acknowledgement", " ".join(R.on_stop("week")))
        self.assertEqual(R.on_stop("ok"), ())

    def test_reduce_only_always_passes_cut_to_what_is_held(self):
        stopped = account(equity=9_000.0, positions=(pos(notional=700.0),))
        r = R.check(order(side=-1, notional=1_000.0, reduce_only=True), stopped)
        self.assertTrue(r.allowed)
        self.assertAlmostEqual(r.notional, 700.0)
        nothing = R.check(order(side=-1, coin="ETH", reduce_only=True), stopped)
        self.assertFalse(nothing.allowed)
        same_side = R.check(order(side=1, reduce_only=True), stopped)
        self.assertFalse(same_side.allowed)


class TestCarry(unittest.TestCase):
    def legs(self, spot=1_000.0, perp=1_000.0):
        return (pos(coin="BTC", leg="spot", side=1, notional=spot, group="c1", venue="spot"),
                pos(coin="BTC", leg="perp", side=-1, notional=perp, group="c1"))

    def test_balanced_legs_are_no_break_and_two_percent_is_the_line(self):
        self.assertEqual(R.hedge_breaks(self.legs()), [])
        self.assertEqual(R.hedge_breaks(self.legs(spot=1_020.0)), [])
        self.assertEqual(len(R.hedge_breaks(self.legs(spot=1_021.0))), 1)
        self.assertEqual(len(R.hedge_breaks(self.legs(perp=0.0))), 1)

    def test_a_spot_leg_uses_neither_leverage_nor_the_coins_perp_cap(self):
        held = account(equity_by_venue={HL: 5_000.0, "spot": 5_000.0},
                       positions=(pos(coin="BTC", leg="spot", venue="spot", notional=3_000.0),))
        r = R.check(order(notional=1_500.0), held)
        self.assertAlmostEqual(r.notional, 1_500.0)
        self.assertAlmostEqual(r.checks["per coin"][0], 2_000.0)
        self.assertAlmostEqual(r.checks["leverage"][0], 10_000.0)

    def test_flat_closes_the_perp_leg_first(self):
        orders = R.flatten_orders(self.legs() + (pos(coin="ETH", leg="spot", venue="spot"),))
        self.assertEqual([(o.leg, o.coin, o.side) for o in orders],
                         [("perp", "BTC", 1), ("spot", "BTC", -1), ("spot", "ETH", -1)])
        self.assertTrue(all(o.reduce_only for o in orders))

    def test_spot_legs_count_for_venue_and_sleeve_not_leverage(self):
        held = account(equity_by_venue={HL: 5_000.0, "spot": 5_000.0},
                       positions=(pos(coin="ETH", leg="spot", venue="spot", notional=4_000.0),))
        r = R.check(order(venue="spot", coin="SOL", leg="spot", notional=3_000.0), held)
        self.assertAlmostEqual(r.notional, 1_000.0)
        self.assertNotIn("leverage", r.checks)


if __name__ == "__main__":
    unittest.main(verbosity=2)
