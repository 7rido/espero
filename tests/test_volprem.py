"""#81's rule on made-up data only: a Friday with ten strikes worked out by hand, and weeks built to hit each branch."""
import datetime as dt
import math
import unittest
from unittest import mock

import numpy as np

from espero import volprem as V

FRI = dt.date(2024, 3, 1)                       # a Friday; its options expire Friday 2024-03-08
F = 100_000.0
STRIKES = [80_000, 85_000, 88_000, 95_000, 100_000, 105_000, 112_000, 115_000, 120_000, 125_000]
SW = 0.5 * math.sqrt(V.TAU)                     # the weekly standard deviation at 50% volatility


def ms(day, hour=0, minute=0, second=0, milli=0):
    d = dt.datetime(day.year, day.month, day.day, hour, minute, second, tzinfo=dt.timezone.utc)
    return int(d.timestamp()) * 1000 + milli


def name(strike, kind="C", expiry=dt.date(2024, 3, 8)):
    return f"BTC-{expiry.day}{expiry.strftime('%b').upper()}{expiry.strftime('%y')}-{strike}-{kind}"


def trade(strike, kind="C", ts=None, tid="1", iv=50.0, index=F, mark=0.01, expiry=dt.date(2024, 3, 8)):
    return V.Trade(ts if ts is not None else ms(FRI, 10), tid, name(strike, kind, expiry), iv, index, mark)


def chain(strikes=STRIKES, iv=50.0, index=F):
    """One call trade a strike through the window, the last one's index F."""
    return [trade(k, "C", ms(FRI, 9, i), str(100 + i), iv, index) for i, k in enumerate(strikes)]


def deliveries(path_after=(100_000,) * 7):
    return {FRI + dt.timedelta(days=k + 1): p for k, p in enumerate(path_after)}


class TestBlack76(unittest.TestCase):
    def test_known_value_and_parity(self):
        # at the money, no interest: price = F (2 N(sigma sqrt(tau) / 2) - 1); with sigma 20%, tau 1: 7.9656
        self.assertAlmostEqual(V.black76(100, 100, 0.2, 1.0, "C"), 7.9656, places=3)
        self.assertAlmostEqual(V.black76(100, 100, 0.2, 1.0, "P"), 7.9656, places=3)
        for K in (70.0, 100.0, 140.0):
            c, p = V.black76(100, K, 0.35, 0.3, "C"), V.black76(100, K, 0.35, 0.3, "P")
            self.assertAlmostEqual(c - p, 100 - K, places=9)               # put-call parity with r = 0

    def test_delta(self):
        self.assertAlmostEqual(V.delta(100, 100, 0.2, 1.0, "C"), V.ncdf(0.1), places=12)
        self.assertAlmostEqual(V.delta(100, 100, 0.2, 1.0, "P"), V.ncdf(0.1) - 1, places=12)
        self.assertAlmostEqual(V.delta(100, 1, 0.5, 0.02, "C"), 1.0, places=9)           # deep in the money
        self.assertAlmostEqual(V.delta(100, 1000, 0.5, 0.02, "C"), 0.0, places=9)
        # the delta is the slope of the price
        h = 1e-4
        slope = (V.black76(100 + h, 95, 0.4, 0.1, "P") - V.black76(100 - h, 95, 0.4, 0.1, "P")) / (2 * h)
        self.assertAlmostEqual(V.delta(100, 95, 0.4, 0.1, "P"), slope, places=6)

    def test_tau_is_163_hours_of_a_365_day_year(self):
        self.assertAlmostEqual(V.TAU, 163 / 8760)


class TestInputs(unittest.TestCase):
    def test_instrument_names(self):
        self.assertEqual(V.parse_instrument("BTC-10JAN20-7250-C"), (dt.date(2020, 1, 10), 7250.0, "C"))
        self.assertEqual(V.parse_instrument("BTC-8MAR24-88000-P"), (dt.date(2024, 3, 8), 88000.0, "P"))
        self.assertIsNone(V.parse_instrument("BTC-PERPETUAL"))
        self.assertIsNone(V.parse_instrument("ETH-8MAR24-3000-C"))

    def test_the_window_is_09_to_13_and_the_expiry_is_next_friday(self):
        ts = [ms(FRI, 8, 59, 59, 999), ms(FRI, 9), ms(FRI, 12, 59, 59, 999), ms(FRI, 13)]
        trades = [trade(100_000, "C", t, str(i)) for i, t in enumerate(ts)]
        kept = V.window_trades(trades, FRI)
        self.assertEqual([t.ts_ms for t in kept], ts[1:3])  # 13:00:00.000 is out, 09:00:00.000 in
        other = [trade(100_000, "C", ms(FRI, 10), "9", expiry=dt.date(2024, 3, 15)),
                 trade(100_000, "C", ms(FRI, 10), "8", expiry=dt.date(2024, 3, 1))]
        self.assertEqual(V.window_trades(other, FRI), [])                           # the week after's, and today's
        self.assertEqual(V.window_trades(trades, FRI + dt.timedelta(days=7)), [])   # a different Friday's window

    def test_a_trade_id_counts_once_and_the_last_of_a_millisecond_is_the_highest_id(self):
        a = trade(100_000, "C", ms(FRI, 10), "9", index=100_001.0)
        b = trade(100_000, "P", ms(FRI, 10), "10", index=100_002.0)  # "10" > "9" as a number, not as text
        c = trade(100_000, "C", ms(FRI, 9, 59), "99", index=100_003.0)
        kept = V.window_trades([b, a, c, a], FRI)
        self.assertEqual([t.index for t in kept], [100_003.0, 100_001.0, 100_002.0])
        wk = V.evaluate_week(FRI, chain() + [a, b], deliveries())
        self.assertEqual(wk.F, 100_002.0)

    def test_a_strike_is_the_median_iv_of_its_calls_and_puts_together(self):
        trades = [trade(100_000, "C", iv=40.0), trade(100_000, "P", iv=50.0), trade(100_000, "C", iv=70.0),
                  trade(105_000, "C", iv=60.0)]
        tab = V.strike_table(trades)
        self.assertEqual(tab, {100_000.0: 0.5, 105_000.0: 0.6})

    def test_a_trade_without_a_usable_iv_prices_nothing_but_can_be_the_last_for_F(self):
        bad = [V.Trade(ms(FRI, 11), f"50{i}", name(k), iv, 100_123.0, 0.01)
               for i, (k, iv) in enumerate(((70_000, 0.0), (71_000, float("nan")), (72_000, -3.0),
                                            (73_000, float("inf"))))]
        self.assertEqual(V.strike_table(bad), {})
        wk = V.evaluate_week(FRI, chain() + bad, deliveries())
        self.assertEqual((wk.F, wk.n_unusable, wk.n_trades, wk.n_strikes), (100_123.0, 4, 14, 10))


class TestStrikes(unittest.TestCase):
    def test_the_body_is_the_traded_strike_nearest_F_and_the_lower_on_a_tie(self):
        self.assertEqual(V.nearest([100.0, 110.0], 105.0), 100.0)
        self.assertEqual(V.nearest([110.0, 100.0], 105.0), 100.0)
        self.assertEqual(V.nearest([100.0, 110.0], 105.1), 110.0)
        self.assertEqual(V.nearest([100.0, 120.0], 109.0), 100.0)  # nearest in dollars, not in log distance

    def test_the_wings_are_nearest_two_sigma_inside_one_and_a_half_to_three(self):
        tab = {float(k): 0.5 for k in STRIKES}
        self.assertEqual(V.pick_strikes(tab, F), (100_000.0, 115_000.0, 88_000.0))
        self.assertAlmostEqual(F * math.exp(2 * SW), 114_613, delta=5)  # 115,000 is nearer than 112,000 or 120,000
        self.assertAlmostEqual(F * math.exp(-2 * SW), 87_246, delta=5)              # 88,000 is nearer than 85,000

    def test_a_wing_outside_its_range_is_not_taken(self):
        lo, hi = F * math.exp(1.5 * SW), F * math.exp(3 * SW)
        self.assertAlmostEqual(lo, 110_770, delta=5)
        self.assertAlmostEqual(hi, 122_700, delta=5)
        no_call = {float(k): 0.5 for k in (80_000, 85_000, 88_000, 95_000, 100_000, 105_000, 108_000, 125_000)}
        self.assertIsNone(V.pick_strikes(no_call, F))                               # 108k is under the range, 125k over
        no_put = {float(k): 0.5 for k in (78_000, 92_000, 95_000, 100_000, 105_000, 112_000, 115_000)}
        self.assertIsNone(V.pick_strikes(no_put, F))
        # a strike exactly on a bound is in range, on all four bounds; it is the only strike in its wing's range
        for e in (1.5, 3.0):
            B = F * math.exp(e * SW)
            self.assertEqual(V.pick_strikes({100_000.0: 0.5, B: 0.5, 85_000.0: 0.5}, F)[1], B, e)
        for e in (-1.5, -3.0):
            B = F * math.exp(e * SW)
            self.assertEqual(V.pick_strikes({100_000.0: 0.5, B: 0.5, 115_000.0: 0.5}, F)[2], B, e)

    def test_wing_ties_go_to_the_lower_strike(self):
        for e in (2.0, -2.0):
            t = F * math.exp(e * SW)
            lo, hi = t - 1024.0, t + 1024.0  # exact in floating point: a true tie
            self.assertEqual(abs(lo - t), abs(hi - t))
            tab = {100_000.0: 0.5, lo: 0.5, hi: 0.5, 85_000.0 if e > 0 else 118_000.0: 0.5}
            got = V.pick_strikes(tab, F)
            self.assertEqual(got[1 if e > 0 else 2], lo)

    def test_fewer_than_five_traded_strikes_skips_with_its_reason(self):
        few = chain(STRIKES[3:7])                                                    # four strikes
        sk = V.evaluate_week(FRI, few, deliveries())
        self.assertIsInstance(sk, V.Skip)
        self.assertEqual((sk.reason, sk.n_trades), (V.FEW_STRIKES, 4))
        self.assertEqual(V.evaluate_week(FRI, [], deliveries()).reason, V.FEW_STRIKES)   # no trades is the same reason
        # five strikes is enough: a trade at each of five strikes with wings present prices
        five = chain([85_000, 88_000, 100_000, 115_000, 120_000])
        self.assertIsInstance(V.evaluate_week(FRI, five, deliveries()), V.Week)

    def test_a_missing_wing_skips_with_its_reason(self):
        sk = V.evaluate_week(FRI, chain([80_000, 85_000, 88_000, 95_000, 100_000, 105_000, 108_000]), deliveries())
        self.assertEqual(sk.reason, V.NO_WING)

    def test_a_missing_delivery_price_skips_for_any_of_the_seven_days(self):
        for k in range(1, 8):
            d = deliveries()
            del d[FRI + dt.timedelta(days=k)]
            self.assertEqual(V.evaluate_week(FRI, chain(), d).reason, V.NO_DELIVERY, k)
        d = deliveries()
        d[FRI + dt.timedelta(days=3)] = 0.0
        self.assertEqual(V.evaluate_week(FRI, chain(), d).reason, V.NO_DELIVERY)
        extra = deliveries()
        extra[FRI] = None  # the entry day's own price is not needed
        self.assertIsInstance(V.evaluate_week(FRI, chain(), extra), V.Week)

    def test_M_not_above_zero_skips(self):
        with mock.patch.object(V, "risk", return_value=0.0):
            self.assertEqual(V.evaluate_week(FRI, chain(), deliveries()).reason, V.NO_RISK)
        with mock.patch.object(V, "risk", return_value=-5.0):
            self.assertEqual(V.evaluate_week(FRI, chain(), deliveries()).reason, V.NO_RISK)
        with mock.patch.object(V, "risk", return_value=1e-9):
            self.assertIsInstance(V.evaluate_week(FRI, chain(), deliveries()), V.Week)


class TestCosts(unittest.TestCase):
    def test_half_gap_is_the_larger_of_the_bps_and_the_percent_of_price(self):
        self.assertAlmostEqual(V.half_gap(70_000, 1_000, -1), 0.04 * 1_000)         # short: 5 bps = 35 < 40
        self.assertAlmostEqual(V.half_gap(70_000, 500, -1), 35.0)                   # 4% = 20 < 35
        self.assertAlmostEqual(V.half_gap(70_000, 50, -1), 35.0)
        self.assertAlmostEqual(V.half_gap(70_000, 200, 1), 20.0)                    # long: 1.5 bps = 10.5 < 10% = 20
        self.assertAlmostEqual(V.half_gap(70_000, 50, 1), 10.5)

    def test_trading_fee_is_the_lesser_of_3_bps_and_12_5_percent_of_price(self):
        self.assertAlmostEqual(V.trade_fee(70_000, 1_000), 21.0)                    # 12.5% = 125
        self.assertAlmostEqual(V.trade_fee(70_000, 100), 12.5)                      # 3 bps = 21
        self.assertAlmostEqual(V.trade_fee(70_000, 168), 21.0)

    def test_settlement_fee_is_the_lesser_of_1_5_bps_of_S_and_12_5_percent_of_the_payoff(self):
        self.assertAlmostEqual(V.settle_fee(70_000, 5_000), 10.5)
        self.assertAlmostEqual(V.settle_fee(70_000, 40), 5.0)
        self.assertEqual(V.settle_fee(70_000, 0.0), 0.0)                            # out of the money pays nothing

    def test_a_leg_in_the_money_only(self):
        self.assertEqual(V.payoff("C", 100, 110), 10)
        self.assertEqual(V.payoff("C", 100, 100), 0)
        self.assertEqual(V.payoff("P", 100, 90), 10)
        self.assertEqual(V.payoff("P", 100, 110), 0)

    def test_the_week_charges_each_leg_its_own_costs(self):
        wk = V.evaluate_week(FRI, chain(), deliveries())
        tab = {float(k): 0.5 for k in STRIKES}
        lg = V.legs(wk.K0, wk.Kc, wk.Kp, tab)
        prices = [V.black76(F, K, s, V.TAU, kind) for kind, K, _, s in lg]
        self.assertAlmostEqual(wk.credit, prices[0] + prices[1] - prices[2] - prices[3])
        self.assertAlmostEqual(wk.gap, sum(V.half_gap(F, p, s) for (_, _, s, _), p in zip(lg, prices)))
        self.assertAlmostEqual(wk.fee, sum(min(0.0003 * F, 0.125 * p) for p in prices))


class TestSettlement(unittest.TestCase):
    def test_payout_below_between_and_above_the_wings(self):
        K0, Kc, Kp = 100.0, 120.0, 80.0
        pay = lambda S: V.settlement_payout(K0, Kc, Kp, S)                           # noqa: E731
        self.assertEqual(pay(70.0), 20.0)                  # put at 100 pays 30, the 80 put gives back 10
        self.assertEqual(pay(80.0), 20.0)
        self.assertEqual(pay(90.0), 10.0)                  # between the put wing and the body
        self.assertEqual(pay(100.0), 0.0)
        self.assertEqual(pay(110.0), 10.0)
        self.assertEqual(pay(120.0), 20.0)
        self.assertEqual(pay(150.0), 20.0)                 # above the call wing
        self.assertEqual(pay(60.0), 20.0)

    def test_the_unhedged_loss_never_exceeds_M_before_settlement_fees_and_exceeds_it_by_those_fees_at_most(self):
        for S in (1_000, 60_000, 80_000, 86_000, 88_000, 99_000, 100_000, 101_000, 115_000, 150_000, 400_000):
            wk = V.evaluate_week(FRI, chain(), deliveries((100_000,) * 6 + (S,)))
            loss = -wk.profit_u
            before_fees = loss - wk.settle_fee
            self.assertLessEqual(before_fees, wk.M + 1e-6, S)
            self.assertLessEqual(loss, wk.M + wk.settle_fee + 1e-6, S)
            if S in (115_000, 150_000, 400_000):  # at or past the call wing: the worst case, to the dollar
                self.assertAlmostEqual(before_fees, wk.M, places=6)
                self.assertGreater(wk.settle_fee, 0)  # which is why the fees can push it over

    def test_M_is_the_wider_wing_less_the_credit_net_of_the_entry_costs(self):
        self.assertEqual(V.risk(100.0, 120.0, 85.0, 12.0, 2.0), 20.0 - 10.0)
        self.assertEqual(V.risk(100.0, 110.0, 70.0, 5.0, 1.0), 30.0 - 4.0)
        wk = V.evaluate_week(FRI, chain(), deliveries())
        self.assertAlmostEqual(wk.M, max(wk.Kc - wk.K0, wk.K0 - wk.Kp) - (wk.credit - wk.gap - wk.fee))
        self.assertEqual((wk.K0, wk.Kc, wk.Kp), (100_000.0, 115_000.0, 88_000.0))

    def test_the_weeks_profit_and_returns(self):
        for S in (70_000, 100_000, 130_000):
            wk = V.evaluate_week(FRI, chain(), deliveries((99_000, 101_000, 98_000, 102_000, 97_000, 103_000, S)))
            self.assertAlmostEqual(wk.profit_u, wk.credit - wk.gap - wk.fee - wk.payout - wk.settle_fee)
            self.assertAlmostEqual(wk.profit_h, wk.profit_u + wk.hedge_pnl - wk.hedge_cost)
            self.assertAlmostEqual(wk.ret_h, wk.profit_h / wk.M)
            self.assertAlmostEqual(wk.ret_u, wk.profit_u / wk.M)
            self.assertAlmostEqual(wk.payout, V.settlement_payout(wk.K0, wk.Kc, wk.Kp, S))


class TestHedge(unittest.TestCase):
    def test_the_holding_is_minus_the_position_delta(self):
        short_call = [("C", 100.0, -1, 0.5)]
        long_put = [("P", 100.0, 1, 0.5)]
        up = V.position_delta(short_call, 100.0, 163)
        self.assertAlmostEqual(up, -V.delta(100.0, 100.0, 0.5, V.TAU, "C"))
        pnl, traded, cost, hold = V.hedge(short_call, [100.0] * 8)
        self.assertGreater(hold[0], 0)                                               # short a call: long BTC against it
        self.assertAlmostEqual(hold[0], V.delta(100.0, 100.0, 0.5, V.TAU, "C"))
        self.assertAlmostEqual(hold[3], V.delta(100.0, 100.0, 0.5, 96 / 8760, "C"))  # time left shrinks by the day
        self.assertGreater(V.hedge(long_put, [100.0] * 8)[3][0], 0)                  # long a put: long BTC against it
        self.assertEqual(pnl, 0.0)

    def test_the_seven_holdings_use_the_hours_left_at_entry_and_each_morning(self):
        self.assertEqual(V.HOURS_LEFT, (163, 144, 120, 96, 72, 48, 24))
        lg = [("C", 100.0, -1, 0.5), ("P", 95.0, 1, 0.4)]
        path = [100.0, 99.0, 101.0, 98.0, 102.0, 97.0, 103.0, 100.0]
        hold = V.hedge(lg, path)[3]
        for i, hours in enumerate((163, 144, 120, 96, 72, 48, 24)):
            tau = hours / 8760
            expect = -(-V.delta(path[i], 100.0, 0.5, tau, "C") + V.delta(path[i], 95.0, 0.4, tau, "P"))
            self.assertAlmostEqual(hold[i], expect, places=12)

    def test_the_hedge_closes_at_settlement_and_is_charged_on_every_dollar_traded(self):
        deep = [("C", 1.0, 1, 0.5)]                                                  # a long call with delta exactly 1
        path = [100.0, 101.0, 102.0, 103.0, 104.0, 105.0, 106.0, 107.0]
        pnl, traded, cost, hold = V.hedge(deep, path)
        self.assertEqual(hold, [-1.0] * 7)
        self.assertAlmostEqual(pnl, -7.0)                                            # short one BTC from 100 to 107
        self.assertAlmostEqual(traded, 100.0 + 107.0)  # opened at F, closed at the settlement price
        self.assertAlmostEqual(cost, 6e-4 * 207.0)

    def test_every_change_in_the_holding_is_charged_at_that_days_price(self):
        lg = [("C", 100.0, -1, 0.5)]
        path = [100.0, 90.0, 80.0, 100.0, 120.0, 110.0, 100.0, 100.0]
        _, traded, cost, hold = V.hedge(lg, path)
        expect = (abs(hold[0]) * path[0] + sum(abs(hold[i] - hold[i - 1]) * path[i] for i in range(1, 7))
                  + abs(hold[6]) * path[7])
        self.assertAlmostEqual(traded, expect)
        self.assertGreater(sum(abs(hold[i] - hold[i - 1]) for i in range(1, 7)), 0.5)      # it really moves
        self.assertAlmostEqual(cost, 0.0006 * expect)
        pnl = sum(hold[i] * (path[i + 1] - path[i]) for i in range(7))
        self.assertAlmostEqual(V.hedge(lg, path)[0], pnl)

    def test_a_flat_week_with_the_hedge_still_pays_to_trade_it(self):
        wk = V.evaluate_week(FRI, chain(), deliveries())
        self.assertAlmostEqual(wk.hedge_pnl, 0.0, places=6)
        self.assertGreater(wk.hedge_traded, 0.0)
        self.assertAlmostEqual(wk.hedge_cost, 0.0006 * wk.hedge_traded)

    def test_realized_volatility_is_the_root_of_the_squared_steps_over_tau(self):
        path = [100.0] + [100.0 * math.exp(0.01 * (-1) ** k) for k in range(7)]
        steps = [math.log(b / a) for a, b in zip(path, path[1:])]
        self.assertAlmostEqual(V.realized_vol(path), math.sqrt(sum(s * s for s in steps) / V.TAU))


class TestDoubledCosts(unittest.TestCase):
    def test_doubling_the_gaps_and_the_hedge_cost_keeps_M(self):
        for path in ((100_000,) * 7, (99_000, 104_000, 95_000, 110_000, 90_000, 108_000, 120_000)):
            wk = V.evaluate_week(FRI, chain(), deliveries(path))
            self.assertAlmostEqual(wk.ret_h2 * wk.M, wk.profit_h - wk.gap - wk.hedge_cost)
            self.assertAlmostEqual(wk.M, V.risk(wk.K0, wk.Kc, wk.Kp, wk.credit, wk.gap + wk.fee))  # single costs
            self.assertLess(wk.ret_h2, wk.ret_h)
            # the trading fee and the settlement fee are not doubled
            self.assertAlmostEqual(wk.profit_h - wk.ret_h2 * wk.M, wk.gap + wk.hedge_cost)


class TestMarkCredit(unittest.TestCase):
    def test_the_marks_credit_uses_each_legs_last_mark_times_its_index(self):
        trades = chain()
        for kind, k, mark, ix in (("C", 100_000, 0.03, 101_000.0), ("P", 100_000, 0.028, 100_500.0),
                                  ("C", 115_000, 0.004, 100_100.0), ("P", 88_000, 0.005, 100_200.0)):
            trades.append(V.Trade(ms(FRI, 12, 30), f"9{k}{kind}", name(k, kind), 50.0, ix, mark))
        trades.append(V.Trade(ms(FRI, 12, 31), "1", name(100_000, "C"), 50.0, F, 0.02))  # a later trade wins
        wk = V.evaluate_week(FRI, trades, deliveries())
        self.assertAlmostEqual(wk.mark_credit, 0.02 * F + 0.028 * 100_500.0 - 0.004 * 100_100.0 - 0.005 * 100_200.0)
        self.assertIsNone(V.evaluate_week(FRI, chain(), deliveries()).mark_credit)       # no put traded: no readout


def weeks_with(ret_h, ret_u=None, ret_h2=None, start=None):
    """One week per value, ending on 2026-10-30 unless `start` says where the first Friday is."""
    start = start or dt.date(2026, 10, 30) - dt.timedelta(days=7 * (len(ret_h) - 1))
    out = []
    for i, r in enumerate(ret_h):
        out.append(V.Week(start + dt.timedelta(days=7 * i), F, F, F, F, F, 0.5, 10, 0, 10,
                          0, 0, 0, 0, 0, 0, 0, 0, 1.0, 0, 0, r,
                          r if ret_u is None else ret_u[i], r if ret_h2 is None else ret_h2[i], 0.5, None))
    return out


def good_series(n=300, mean=0.06, sd=0.2, seed=3):
    return list(np.random.default_rng(seed).normal(mean, sd, n))


class TestCriteria(unittest.TestCase):
    def test_the_statistics_are_the_registered_ones(self):
        r = good_series()
        _, _, st = V.criteria(weeks_with(r), [])
        self.assertAlmostEqual(st["lags"], V.nw_lags(300))
        self.assertAlmostEqual(st["t"], V.nw_t(np.array(r), V.nw_lags(300)))
        self.assertAlmostEqual(st["p"] / math.erfc(abs(st["t"]) / math.sqrt(2)), 1.0)       # relative: p is tiny
        self.assertAlmostEqual(V.two_sided_p(3.0), 0.0026998, places=6)
        self.assertAlmostEqual(V.two_sided_p(-3.0), 0.0026998, places=6)
        self.assertEqual((V.MIN_PF, V.MIN_T, V.MAX_Q, V.MIN_WEEKS), (1.5, 3.0, 0.05, 200))
        self.assertEqual((V.MIN_YEAR_WEEKS, V.MAX_LOSING_YEARS, V.SINCE), (20, 2, dt.date(2025, 1, 3)))

    def test_the_t_and_q_edges_and_the_sign(self):
        r = good_series()
        ws = weeks_with(r)
        def patched(t, q):
            return mock.patch.object(V, "nw_t", return_value=t), mock.patch.object(V, "bh", return_value=np.array([q]))
        with patched(3.0, 0.0499)[0], patched(3.0, 0.0499)[1]:
            self.assertTrue(V.criteria(ws, [])[1][1].ok)                                    # t of exactly 3 meets it
        with patched(2.999, 0.01)[0], patched(2.999, 0.01)[1]:
            self.assertFalse(V.criteria(ws, [])[1][1].ok)
        with patched(5.0, 0.05)[0], patched(5.0, 0.05)[1]:
            self.assertFalse(V.criteria(ws, [])[1][1].ok)                                   # q must be under 0.05
        with patched(5.0, 0.0)[0], patched(5.0, 0.0)[1]:
            self.assertFalse(V.criteria(weeks_with([0.0] * 300), [])[1][1].ok)  # a zero mean is not above zero
            self.assertFalse(V.criteria(weeks_with([-x for x in r]), [])[1][1].ok)

    def test_since_2025_counts_the_first_friday_of_2025_and_nothing_before(self):
        n = 300
        dates = [dt.date(2026, 10, 30) - dt.timedelta(days=7 * (n - 1 - i)) for i in range(n)]
        j = dates.index(dt.date(2025, 1, 3))
        only_edge = [0.5 if i < j else (100.0 if i == j else -0.1) for i in range(n)]
        self.assertTrue(V.criteria(weeks_with(only_edge), [])[1][2].ok)                      # the Jan-3 week is in
        before = [-0.1 if i < j else (0.5 if i == j - 1 else 0.01) for i in range(n)]
        self.assertTrue(V.criteria(weeks_with(before), [])[1][2].ok)
        lose_since = [0.5 if i < j else -0.01 for i in range(n)]
        self.assertFalse(V.criteria(weeks_with(lose_since), [])[1][2].ok)  # not the whole history's mean
        win_since = [-0.5 if i < j else 0.01 for i in range(n)]
        self.assertTrue(V.criteria(weeks_with(win_since), [])[1][2].ok)
        _, _, st = V.criteria(weeks_with(lose_since), [])
        self.assertEqual(st["n_since"], n - j)

    def test_means_are_means_and_each_check_reads_its_own_series(self):
        skew = [0.5] * 100 + [-0.1] * 200                                                    # mean +0.0100, median -0.1
        c = V.criteria(weeks_with([0.1] * 300, ret_u=skew, ret_h2=skew), [])[1]
        self.assertTrue(c[4].ok and c[5].ok)
        pos = [0.1] * 300
        ends = dt.date(2026, 10, 30)
        by_year_bad = [-0.5 if (ends - dt.timedelta(days=7 * (299 - i))).year in (2021, 2022, 2023) else 0.3
                       for i in range(300)]
        c = V.criteria(weeks_with(by_year_bad, ret_u=pos, ret_h2=pos), [])[1]
        self.assertFalse(c[3].ok)  # the years follow the hedged return
        c = V.criteria(weeks_with(pos, ret_u=by_year_bad, ret_h2=pos), [])[1]
        self.assertTrue(c[3].ok)
        zero = V.criteria(weeks_with([0.1] * 300, ret_h2=[0.0] * 300), [])[1]
        self.assertFalse(zero[4].ok)

    def test_all_six_hold_is_a_pass(self):
        r = good_series()
        verdict, checks, st = V.criteria(weeks_with(r), [0.5] * 20)
        self.assertEqual([c.n for c in checks], [1, 2, 3, 4, 5, 6])
        self.assertTrue(all(c.ok for c in checks), [c.text for c in checks])
        self.assertEqual(verdict, "PASS")
        self.assertGreaterEqual(st["t"], 3.0)

    def test_under_200_priced_weeks_is_inconclusive_whatever_they_say(self):
        self.assertEqual(V.criteria(weeks_with(good_series(199)), [])[0], "INCONCLUSIVE")
        self.assertEqual(V.criteria(weeks_with([-0.1] * 150), [])[0], "INCONCLUSIVE")
        self.assertEqual(V.criteria(weeks_with(good_series(200)), [])[0], "PASS")

    def test_the_profit_factor_needs_1_5(self):
        self.assertAlmostEqual(V.profit_factor([3.0, -2.0]), 1.5)
        self.assertTrue(V.criteria(weeks_with([3.0, -2.0] * 110), [])[1][0].ok)               # exactly 1.5 meets it
        self.assertFalse(V.criteria(weeks_with([2.9, -2.0] * 110), [])[1][0].ok)
        self.assertEqual(V.profit_factor([1.0, 2.0]), math.inf)
        self.assertIsNone(V.profit_factor([0.0, 0.0]))

    def test_t_and_q_are_both_needed(self):
        r = good_series()
        self.assertTrue(V.criteria(weeks_with(r), [])[1][1].ok)
        mid = good_series(mean=0.0255)
        t = V.criteria(weeks_with(mid), [])[2]["t"]
        self.assertTrue(3.0 <= t < 3.5, t)
        self.assertTrue(V.criteria(weeks_with(mid), [])[1][1].ok)
        self.assertFalse(V.criteria(weeks_with(mid), [1.0] * 100)[1][1].ok)  # t holds, q = p x 101 does not
        weak = good_series(mean=0.02)
        t = V.criteria(weeks_with(weak), [])[2]["t"]
        self.assertTrue(2.0 < t < 3.0, t)
        self.assertFalse(V.criteria(weeks_with(weak), [])[1][1].ok)                        # q < 0.05 but t < 3
        self.assertFalse(V.criteria(weeks_with([-x for x in r]), [])[1][1].ok)             # the wrong sign
        _, _, st = V.criteria(weeks_with(r), [0.5, 0.01])
        self.assertEqual(st["fam"], 3)                                                      # this test is counted in

    def test_still_there_now_looks_at_weeks_from_2025_01_03(self):
        r = good_series()
        ws = weeks_with(r)
        i = next(k for k, w in enumerate(ws) if w.friday >= dt.date(2025, 1, 3))
        self.assertEqual(ws[i].friday, dt.date(2025, 1, 3))
        bad = r[:i] + [-0.01] * (len(r) - i)
        c3 = V.criteria(weeks_with(bad), [])[1][2]
        self.assertFalse(c3.ok)
        self.assertTrue(V.criteria(weeks_with(r[:i] + [0.01] * (len(r) - i)), [])[1][2].ok)
        # the week before 2025-01-03 is not in "since"
        edge = r[:i - 1] + [-9.0] + [0.01] * (len(r) - i)
        self.assertTrue(V.criteria(weeks_with(edge), [])[1][2].ok)

    def test_at_most_two_losing_years_among_those_with_20_priced_weeks(self):
        def series(by_year, n=300):
            dates = [dt.date(2020, 1, 3) + dt.timedelta(days=7 * i) for i in range(n)]
            return weeks_with([by_year.get(d.year, 0.3) for d in dates], start=dates[0])
        self.assertTrue(V.criteria(series({2020: -0.3, 2021: -0.3}), [])[1][3].ok)
        c = V.criteria(series({2020: -0.3, 2021: -0.3, 2022: -0.3}), [])[1][3]
        self.assertFalse(c.ok)
        self.assertIn("3 of 6", c.text)
        # a year with fewer than 20 weeks is not counted, however bad: 2025 holds 19 of them here
        n = (dt.date(2025, 5, 16) - dt.date(2020, 1, 3)).days // 7 + 1
        ws = series({2020: -0.3, 2021: -0.3, 2025: -0.3}, n=n)
        self.assertEqual(sum(1 for w in ws if w.friday.year == 2025), 20)
        self.assertFalse(V.criteria(ws, [])[1][3].ok)  # 20 weeks: counted, three losers
        ws = ws[:-1]
        self.assertEqual(sum(1 for w in ws if w.friday.year == 2025), 19)
        self.assertTrue(V.criteria(ws, [])[1][3].ok)  # 19 weeks: left out, two losers
        # a year at exactly zero is a loss
        c = V.criteria(series({2023: 0.0}), [])[1][3]
        self.assertIn("2023", c.text)
        self.assertTrue(c.ok)

    def test_doubled_costs_and_the_unhedged_form_each_need_a_positive_mean(self):
        r = good_series()
        ok = V.criteria(weeks_with(r), [])[1]
        self.assertTrue(ok[4].ok and ok[5].ok)
        bad2 = V.criteria(weeks_with(r, ret_h2=[-0.01] * 300), [])[1]
        self.assertFalse(bad2[4].ok)
        self.assertTrue(bad2[5].ok)
        badu = V.criteria(weeks_with(r, ret_u=[-0.01] * 300), [])[1]
        self.assertFalse(badu[5].ok)
        self.assertTrue(badu[4].ok)
        self.assertFalse(V.criteria(weeks_with(r, ret_u=[0.0] * 300), [])[1][5].ok)         # zero is not above zero

    def test_any_missed_criterion_is_a_fail(self):
        r = good_series()
        self.assertEqual(V.criteria(weeks_with(r, ret_u=[-0.01] * 300), [])[0], "FAIL")
        self.assertEqual(V.criteria(weeks_with(r, ret_h2=[-0.01] * 300), [])[0], "FAIL")


if __name__ == "__main__":
    unittest.main()
