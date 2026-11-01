"""#58's rule, trades, verdict and book, on made-up data only."""
import gzip
import sqlite3
import tempfile
import unittest
from pathlib import Path

import numpy as np
import pandas as pd

from espero import hlpbook as hb

T0 = hb.WINDOW_START


def prices_from(coin, start, closes):
    """One candle a minute; each opens one unit below its close, so open and close can't be confused."""
    p = hb.Prices()
    p.add(coin, pd.DataFrame({"ts": start + 60 * np.arange(len(closes)), "open": np.asarray(closes, float) - 1,
                              "close": np.asarray(closes, float)}))
    return p


def history(n=400, end=T0, coin="BTC"):
    """n adjacent slots ending just before `end`, with small jumps in both directions."""
    sizes = np.cumsum(np.where(np.arange(n) % 2, 1.0, -1.0) * (1 + np.arange(n) % 5))
    return [hb.Slot(end - (n - k) * hb.SLOT_S, end - (n - k) * hb.SLOT_S + 5, frozenset({"a"}), {coin: float(sizes[k])})
            for k in range(n)]


def falling_market(n=400, drop=None, coin="BTC"):
    """Minute candles over the slots, drifting gently up and down, with an optional fall in the last slot."""
    start = T0 - (n + 1) * hb.SLOT_S
    minutes = (n + 1) * 15 + 600
    closes = 100 + np.sin(np.arange(minutes) / 40.0)
    if drop:
        fall_at = (T0 + 5 - start) // 60 - 14
        closes[fall_at:] = closes[fall_at:] * (1 - drop)
    return prices_from(coin, start, closes)


def with_event(slots, jump_size=1000.0, coin="BTC"):
    last = slots[-1]
    return slots + [hb.Slot(T0, T0 + 5, last.addresses, {coin: last.net.get(coin, 0.0) + jump_size})]


def scene(jumps, rets, end=T0, coin="BTC"):
    """Slots and candles giving exactly these dollar jumps and returns, the last pair ending at slot `end`."""
    n = len(jumps) + 1
    closes, sizes = [100.0], [0.0]
    for jump, ret in zip(jumps, rets):
        closes.append(closes[-1] * (1 + ret))
        sizes.append(sizes[-1] + jump / closes[-1])
    slots = [hb.Slot(end - (n - 1 - k) * hb.SLOT_S, end - (n - 1 - k) * hb.SLOT_S, frozenset({"a"}), {coin: sizes[k]})
             for k in range(n)]
    prices = hb.Prices()
    prices.add(coin, pd.DataFrame({"ts": [s.ts - 60 for s in slots], "open": closes, "close": closes}))
    return slots, prices


def ramp(n=400):
    """Past jumps of 1..n dollars and past returns of -n..-1 hundredths of a bp, in a fixed shuffle."""
    order = np.random.default_rng(1).permutation(n)
    return list(1.0 + order), list(-(1.0 + order[::-1]) * 1e-6)


class ThresholdTests(unittest.TestCase):
    """Exact edges. With n=400 values, the 99th percentile of jumps is 396.01, and the 10th of returns -360.1e-6."""
    FALL = -0.01

    def fires(self, jumps, rets, end=T0):
        slots, prices = scene(jumps, rets, end)
        return len(hb.walk(slots, prices, final=True)["signals"])

    def test_the_registered_numbers(self):
        self.assertEqual((hb.JUMP_PCT, hb.RET_PCT, hb.HISTORY_SLOTS, hb.MIN_HISTORY, hb.ENTRY_DELAY_S, hb.HOLD_S,
                          hb.FILL_TOLERANCE_S, hb.COST_BPS, hb.MIN_TRADES, hb.MIN_COIN_TRADES, hb.PASS_T),
                         (99.0, 10.0, 672, 336, 60, 14400, 300, 18.0, 100, 10, 3.0))

    def test_jump_must_clear_the_99th_percentile(self):
        j, r = ramp()
        self.assertEqual(self.fires(j + [396.0], r + [self.FALL]), 0)
        self.assertEqual(self.fires(j + [396.5], r + [self.FALL]), 1)

    def test_return_must_reach_the_10th_percentile(self):
        j, r = ramp()
        self.assertEqual(self.fires(j + [1000.0], r + [-300e-6]), 0)
        self.assertEqual(self.fires(j + [1000.0], r + [-400e-6]), 1)

    def test_a_jump_must_be_positive_even_above_the_percentile(self):
        j, r = ramp()
        self.assertEqual(self.fires([-x - 10 for x in j] + [-1.0], r + [self.FALL]), 0)

    def test_a_return_must_be_negative_even_below_the_percentile(self):
        j, r = ramp()
        self.assertEqual(self.fires(j + [1000.0], [-x + 1e-3 for x in r] + [1e-5]), 0)

    def test_needs_336_past_pairs_exactly(self):
        j, r = ramp(335)
        self.assertEqual(self.fires(j + [1000.0], r + [self.FALL]), 0)
        j, r = ramp(336)
        self.assertEqual(self.fires(j + [1000.0], r + [self.FALL]), 1)

    def test_a_pair_older_than_672_slots_leaves_the_history(self):
        big = [1e6] * 30                    # would set the bar if still counted
        j, r = ramp(672)
        self.assertEqual(self.fires(big + j + [1000.0], [-1e-6] * 30 + r + [self.FALL]), 1)
        self.assertEqual(self.fires(big + j[30:] + [1000.0], [-1e-6] * 30 + r[30:] + [self.FALL]), 0)

    def test_the_window_opens_and_closes_on_the_right_slot(self):
        j, r = ramp()
        ev = (j + [1000.0], r + [self.FALL])
        self.assertEqual(self.fires(*ev, end=hb.WINDOW_START - hb.SLOT_S), 0)
        self.assertEqual(self.fires(*ev, end=hb.WINDOW_START), 1)
        self.assertEqual(self.fires(*ev, end=hb.WINDOW_END - hb.SLOT_S), 1)
        self.assertEqual(self.fires(*ev, end=hb.WINDOW_END), 0)


class GuardTests(unittest.TestCase):
    """#59 voids failed reads, not real changes in which accounts hold positions; #58 voids both."""

    def walked(self, guard, change):
        j, r = ramp()
        slots, prices = scene(j + [1000.0], r + [-0.01])
        slots = [s._replace(clean=True) for s in slots]
        return hb.walk(change(slots), prices, final=True, guard=guard)

    @staticmethod
    def third_account(slots):
        slots[-1] = slots[-1]._replace(addresses=frozenset({"a", "liq"}))
        return slots

    def test_an_account_appearing_voids_58_but_not_59(self):
        self.assertEqual(len(self.walked("accounts", self.third_account)["signals"]), 0)
        self.assertEqual(len(self.walked("reads", self.third_account)["signals"]), 1)

    def test_a_failed_read_voids_59_in_either_slot_of_the_pair(self):
        for k in (-1, -2):
            def fail(slots, k=k):
                slots[k] = slots[k]._replace(clean=False)
                return slots
            out = self.walked("reads", fail)
            self.assertEqual(out["signals"], [])
            self.assertGreaterEqual(out["counts"]["invalid_pairs"], 1)

    def test_a_failed_read_does_not_void_58(self):
        def fail(slots):
            slots[-1] = slots[-1]._replace(clean=False)
            return slots
        self.assertEqual(len(self.walked("accounts", fail)["signals"]), 1)

    def test_a_missing_record_voids_59_from_the_first_record_on(self):
        def lost(slots):
            slots[-1] = slots[-1]._replace(clean=None)
            return slots
        self.assertEqual(self.walked("reads", lost)["signals"], [])

    def test_slots_before_the_first_record_are_unguarded_history(self):
        def late_start(slots):
            return [s._replace(clean=None) if k < len(slots) - 2 else s for k, s in enumerate(slots)]
        out = self.walked("reads", late_start)
        self.assertEqual(len(out["signals"]), 1)
        self.assertEqual(out["counts"]["invalid_pairs"], 0)

    def test_a_voided_pair_leaves_59s_history(self):
        j, r = ramp()
        slots, prices = scene(j + [1e6, 1000.0], r + [-0.5, -0.01])
        slots = [s._replace(clean=True) for s in slots]
        slots[-2] = slots[-2]._replace(clean=False)
        self.assertEqual(hb.walk(slots, prices, final=True, guard="reads")["counts"]["invalid_pairs"], 2)

    def test_a_record_is_read_beside_its_slot(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "hlp" / "2026-11-05" / "0015.csv.gz"
            path.parent.mkdir(parents=True)
            path.write_bytes(gzip.compress(b"ts,address,coin,szi\n1,a,BTC,2\n"))
            self.assertIsNone(hb.read_slot(path).clean)
            rec = Path(d) / "hlp_reads" / "2026-11-05" / "0015.json"
            rec.parent.mkdir(parents=True)
            rec.write_text('{"ts": 1, "accounts": ["a"], "failed": []}')
            self.assertIs(hb.read_slot(path).clean, True)
            rec.write_text('{"ts": 1, "accounts": ["a"], "failed": ["a"]}')
            self.assertIs(hb.read_slot(path).clean, False)
            rec.write_text("not json")
            self.assertIsNone(hb.read_slot(path).clean)

    def test_the_tests_guards(self):
        self.assertEqual(hb.GUARDS, {58: "accounts", 59: "reads"})


class PricesTests(unittest.TestCase):
    def test_close_at_uses_only_a_candle_that_has_ended(self):
        p = prices_from("BTC", 0, [10.0, 20.0, 30.0])
        self.assertEqual(p.close_at("BTC", 119), 10.0)      # the candle from 60 ends at 120
        self.assertEqual(p.close_at("BTC", 120), 20.0)
        self.assertTrue(np.isnan(p.close_at("BTC", 59)))

    def test_first_open_at_or_after_within_tolerance(self):
        p = prices_from("BTC", 0, [10.0, 20.0, 30.0])
        self.assertEqual(p.first_open("BTC", 60), (60, 19.0))
        self.assertEqual(p.first_open("BTC", 61), (120, 29.0))
        q = hb.Prices()
        q.add("BTC", pd.DataFrame({"ts": [1000], "open": [5.0], "close": [6.0]}))
        self.assertEqual(q.first_open("BTC", 1000 - hb.FILL_TOLERANCE_S), (1000, 5.0))
        self.assertEqual(q.first_open("BTC", 1000 - hb.FILL_TOLERANCE_S - 1), hb.MISSING)

    def test_a_candle_not_there_yet_is_pending_until_final(self):
        p = prices_from("BTC", 0, [10.0])
        self.assertEqual(p.first_open("BTC", 600), hb.PENDING)
        self.assertEqual(p.first_open("BTC", 600, final=True), hb.MISSING)

    def test_first_copy_of_a_candle_wins(self):
        p = prices_from("BTC", 0, [10.0])
        p.add("BTC", pd.DataFrame({"ts": [0], "open": [99.0], "close": [99.0]}))
        self.assertEqual(p.close_at("BTC", 60), 10.0)


class FetchTests(unittest.TestCase):
    def test_api_candles_land_on_the_right_second_and_an_unfinished_one_is_left_out(self):
        start = T0 - 120

        def fetch(body):
            if body["req"]["coin"] != "BTC":
                return []
            return [{"t": (start + 60 * k) * 1000, "o": "1", "h": "1", "l": "1", "c": str(10 + k), "v": "1"}
                    for k in range(3)]

        p = hb.Prices()
        self.assertEqual(hb.fetch_recent(p, T0 + 30, fetch, pace=0), 2)
        self.assertEqual(p.close_at("BTC", T0), 11.0)
        self.assertEqual(p.last_end("BTC"), T0)


class SignalTests(unittest.TestCase):
    def signals(self, slots, prices, final=True):
        return hb.walk(slots, prices, final=final)

    def test_a_jump_up_in_a_sharp_fall_signals(self):
        out = self.signals(with_event(history()), falling_market(drop=0.03))["signals"]
        self.assertEqual([(s.coin, s.ts) for s in out], [("BTC", T0 + 5)])
        self.assertGreater(out[0].jump, 0)
        self.assertLess(out[0].ret, 0)

    def test_no_fall_no_signal(self):
        self.assertEqual(self.signals(with_event(history()), falling_market())["signals"], [])

    def test_a_small_jump_no_signal(self):
        slots = with_event(history(), jump_size=0.001)
        self.assertEqual(self.signals(slots, falling_market(drop=0.03))["signals"], [])

    def test_a_jump_down_no_signal(self):
        slots = with_event(history(), jump_size=-1000.0)
        self.assertEqual(self.signals(slots, falling_market(drop=0.03))["signals"], [])

    def test_a_rally_no_signal(self):
        self.assertEqual(self.signals(with_event(history()), falling_market(drop=-0.03))["signals"], [])

    def test_too_little_history_no_signal(self):
        slots = with_event(history(n=hb.MIN_HISTORY))     # one short: n slots make n-1 pairs
        self.assertEqual(self.signals(slots, falling_market(n=hb.MIN_HISTORY, drop=0.03))["signals"], [])
        slots = with_event(history(n=hb.MIN_HISTORY + 1))
        self.assertEqual(len(self.signals(slots, falling_market(n=hb.MIN_HISTORY + 1, drop=0.03))["signals"]), 1)

    def test_history_stops_at_672_slots(self):
        # 30 huge old jumps, inside the history only if the 672-slot limit is broken, would hide the event
        slots = history(n=900)
        k = 900 - hb.HISTORY_SLOTS - 5
        slots = [s._replace(net={"BTC": s.net["BTC"] + 1e7 * min(max(i - k + 30, 0), 30)}) for i, s in enumerate(slots)]
        self.assertEqual(len(self.signals(with_event(slots), falling_market(n=900, drop=0.03))["signals"]), 1)

    def test_the_event_is_not_in_its_own_history(self):
        p = falling_market(n=400, drop=0.03)
        flat = [s._replace(net={"BTC": 0.0}) for s in history()]
        out = self.signals(with_event(flat, jump_size=1.0), p)["signals"]
        self.assertEqual(len(out), 1)       # every past jump is 0, so its own 1.0 would otherwise set the bar

    def test_before_the_window_no_signal(self):
        slots = with_event(history(end=T0 - hb.SLOT_S * 4))
        slots[-1] = slots[-1]._replace(slot=T0 - hb.SLOT_S * 4, ts=T0 - hb.SLOT_S * 4 + 5)
        self.assertEqual(self.signals(slots, falling_market(n=500, drop=0.03))["signals"], [])

    def test_a_gap_makes_no_pair(self):
        slots = with_event(history())
        out = self.signals(slots[:-2] + slots[-1:], falling_market(drop=0.03))
        self.assertEqual(out["signals"], [])
        self.assertEqual(out["counts"]["gaps"], 1)

    def test_a_vanished_account_voids_both_pairs_around_it(self):
        slots = with_event(history())
        slots = [s._replace(addresses=frozenset({"a", "b"})) for s in slots]
        slots[-2] = slots[-2]._replace(addresses=frozenset({"a"}))
        out = self.signals(slots, falling_market(drop=0.03))
        self.assertEqual(out["signals"], [])
        self.assertEqual(out["counts"]["invalid_pairs"], 2)

    def test_net_size_sums_every_address_and_ignores_other_coins(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "hlp" / "2026-11-05" / "0015.csv.gz"
            path.parent.mkdir(parents=True)
            csv = "ts,address,coin,szi\n1,a,BTC,2\n1,b,BTC,-0.5\n1,a,PEPE,9\n"
            path.write_bytes(gzip.compress(csv.encode()))
            s = hb.read_slot(path)
        self.assertEqual(s.net, {"BTC": 1.5})
        self.assertEqual(s.addresses, frozenset({"a", "b"}))
        self.assertEqual(s.slot, T0 + hb.SLOT_S)
        self.assertEqual(s.ts, 1)

    def test_a_coin_without_candles_waits_unless_final(self):
        slots = with_event(history())
        p = falling_market(drop=0.03)
        short = hb.Prices()
        starts = p._arrays("BTC")[0]
        keep = starts + 60 < T0 + 5
        short.add("BTC", pd.DataFrame({"ts": starts[keep], "open": p._arrays("BTC")[1][keep],
                                       "close": p._arrays("BTC")[2][keep]}))
        self.assertEqual(hb.walk(slots, short)["signals"], [])


class TradeTests(unittest.TestCase):
    def sig(self, ts):
        return hb.Signal("BTC", ts, 1.0, -0.01)

    def test_entry_waits_the_delay_and_exit_four_hours_later_at_opens(self):
        out = hb.trades([self.sig(T0)], prices_from("BTC", T0 - 60, 100.0 + np.arange(600)))
        t = out[0]
        self.assertEqual(t["status"], "closed")
        self.assertEqual(t["entry_ts"], T0 + 60)
        self.assertEqual(t["entry_px"], 100.0 + 2 - 1)      # the candle starting at T0+60 is the third
        self.assertEqual(t["exit_ts"], T0 + 60 + hb.HOLD_S)
        self.assertEqual(t["exit_px"], t["entry_px"] + 240)

    def test_a_signal_during_a_hold_is_ignored_and_one_after_it_trades(self):
        p = prices_from("BTC", T0 - 60, 100.0 + np.arange(900))
        hold_end = T0 + 60 + hb.HOLD_S
        out = hb.trades([self.sig(T0), self.sig(T0 + 900), self.sig(hold_end)], p)
        self.assertEqual([t["status"] for t in out], ["closed", "ignored", "closed"])

    def test_no_candle_near_the_entry_drops_it_and_does_not_hold(self):
        p = hb.Prices()
        far = T0 + 60 + hb.FILL_TOLERANCE_S + 60
        p.add("BTC", pd.DataFrame({"ts": far + 60 * np.arange(600), "open": 1.0, "close": 1.0}))
        out = hb.trades([self.sig(T0), self.sig(T0 + 900)], p)
        self.assertEqual([t["status"] for t in out], ["dropped_entry", "closed"])

    def test_entry_more_than_five_minutes_after_the_signal_is_dropped(self):
        p = hb.Prices()
        at = T0 + hb.FILL_TOLERANCE_S + 60
        p.add("BTC", pd.DataFrame({"ts": at + 60 * np.arange(600), "open": 1.0, "close": 1.0}))
        self.assertEqual(hb.trades([self.sig(T0)], p)[0]["status"], "dropped_entry")

    def test_no_candle_near_the_exit_drops_it(self):
        p = hb.Prices()
        late = T0 + 60 + hb.HOLD_S + hb.FILL_TOLERANCE_S + 60
        p.add("BTC", pd.DataFrame({"ts": [T0 + 60, late], "open": 1.0, "close": 1.0}))
        self.assertEqual(hb.trades([self.sig(T0)], p)[0]["status"], "dropped_exit")

    def test_a_dropped_exit_still_held_the_coin_for_four_hours(self):
        p = hb.Prices()
        late = T0 + 60 + hb.HOLD_S + hb.FILL_TOLERANCE_S + 60
        p.add("BTC", pd.DataFrame({"ts": [T0 + 60, T0 + 960, late, late + 60], "open": 1.0, "close": 1.0}))
        self.assertEqual([t["status"] for t in hb.trades([self.sig(T0), self.sig(T0 + 900)], p)],
                         ["dropped_exit", "ignored"])

    def test_open_until_the_exit_candle_exists(self):
        p = prices_from("BTC", T0, np.full(30, 100.0))
        self.assertEqual(hb.trades([self.sig(T0)], p)[0]["status"], "open")
        self.assertEqual(hb.trades([self.sig(T0)], p, final=True)[0]["status"], "dropped_exit")

    def test_exit_after_the_window_is_dropped(self):
        late = hb.WINDOW_END - 3600
        p = prices_from("BTC", late - 60, 100.0 + np.arange(600))
        self.assertEqual(hb.trades([self.sig(late)], p)[0]["status"], "dropped_after_window")


class MoneyTests(unittest.TestCase):
    def test_net_charges_18_and_funding(self):
        self.assertAlmostEqual(hb.net_bps(100.0, 101.0, 2.0), 100.0 - 18.0 - 2.0)

    def test_funding_sums_rates_after_entry_through_exit(self):
        def fetch(body):
            return [{"time": t * 1000, "fundingRate": "0.0001"} for t in (1000, 1001, 2000, 2001)]
        self.assertAlmostEqual(hb.funding_bps("BTC", 1000, 2000, fetch), 2.0)


class VerdictTests(unittest.TestCase):
    def closed(self, n=200, mean=60.0, spread=5.0, coins=hb.COINS, first=hb.WINDOW_START):
        days = np.arange(n) % 140
        return pd.DataFrame({"coin": [coins[k % len(coins)] for k in range(n)], "entry_ts": first + days * 86400,
                             "net_bps": mean + spread * np.where(np.arange(n) % 2, 1.0, -1.0)})

    def test_passes_when_every_criterion_holds(self):
        r = hb.evaluate(self.closed())
        self.assertEqual(r["verdict"], "PASS")

    def test_too_few_trades_is_inconclusive(self):
        self.assertEqual(hb.evaluate(self.closed(n=hb.MIN_TRADES - 1))["verdict"], "INCONCLUSIVE")
        self.assertNotEqual(hb.evaluate(self.closed(n=hb.MIN_TRADES))["verdict"], "INCONCLUSIVE")

    def test_a_loss_fails(self):
        self.assertEqual(hb.evaluate(self.closed(mean=-60.0))["verdict"], "FAIL")

    def test_weak_t_fails(self):
        r = hb.evaluate(self.closed(mean=1.0, spread=100.0))
        self.assertLess(r["t"], hb.PASS_T)
        self.assertEqual(r["verdict"], "FAIL")
        self.assertFalse(r["checks"]["pays"])

    def test_one_losing_half_fails(self):
        c = self.closed()
        c.loc[c["entry_ts"] >= hb.SECOND_HALF, "net_bps"] = -1.0
        c.loc[c["entry_ts"] < hb.SECOND_HALF, "net_bps"] += 200
        r = hb.evaluate(c)
        self.assertFalse(r["checks"]["both_halves"])
        self.assertEqual(r["verdict"], "FAIL")

    def test_half_the_coins_is_not_enough(self):
        c = self.closed(n=280)
        losers = list(hb.COINS[:7])
        c.loc[c["coin"].isin(losers), "net_bps"] = -1.0
        r = hb.evaluate(c)
        self.assertFalse(r["checks"]["coins"])
        self.assertEqual(r["verdict"], "FAIL")

    def test_coins_under_ten_trades_do_not_vote(self):
        c = self.closed(n=280, coins=hb.COINS[:4])
        extra = pd.DataFrame({"coin": list(hb.COINS[6:12]) * 9, "entry_ts": hb.WINDOW_START, "net_bps": -1.0})
        self.assertTrue(hb.evaluate(pd.concat([c, extra], ignore_index=True))["checks"]["coins"])

    def test_the_largest_coins_must_pay_together(self):
        c = self.closed(n=280)
        c.loc[c["coin"].isin(hb.LARGEST), "net_bps"] = -1.0
        c.loc[~c["coin"].isin(hb.LARGEST), "net_bps"] += 50
        r = hb.evaluate(c)
        self.assertFalse(r["checks"]["largest"])
        self.assertEqual(r["verdict"], "FAIL")


class BookTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.data = Path(self.tmp.name) / "data"
        self.state = Path(self.tmp.name) / "book.db"

    def write_slot(self, slot, ts, rows):
        day, hhmm = pd.Timestamp(slot, unit="s").strftime("%Y-%m-%d %H%M").split()
        path = self.data / "hlp" / day / f"{hhmm}.csv.gz"
        path.parent.mkdir(parents=True, exist_ok=True)
        body = "ts,address,coin,szi\n" + "".join(f"{ts},{a},{c},{s}\n" for a, c, s in rows)
        path.write_bytes(gzip.compress(body.encode()))

    def fill(self):
        for s in history():
            self.write_slot(s.slot, s.ts, [("a", "BTC", s.net["BTC"])])
        last = history()[-1]
        self.write_slot(T0, T0 + 5, [("a", "BTC", last.net["BTC"] + 1000.0)])
        p = falling_market(drop=0.03)
        starts, opens, closes = p._arrays("BTC")
        path = self.data / "candles" / "all.csv.gz"
        path.parent.mkdir(parents=True)
        body = "ts,coin,open,high,low,close,volume,trades\n" + "".join(
            f"{t},BTC,{o},{c},{c},{c},1,1\n" for t, o, c in zip(starts, opens, closes))
        path.write_bytes(gzip.compress(body.encode()))

    def no_network(self, body):
        if body["type"] == "fundingHistory":
            return [{"time": (T0 + 3600) * 1000, "fundingRate": "0.0001"}]
        return []

    def book(self):
        book = hb.Book(self.state, self.data, fetch=self.no_network, pace=0, log=lambda _: None)
        self.addCleanup(book.close)
        return book

    def test_before_the_window_it_reads_no_value(self):
        self.write_slot(T0, T0 + 5, [("a", "BTC", 1.0)])
        path = next(self.data.glob("hlp/*/*"))
        path.write_bytes(b"this is not a gzip file, and reading it would raise")
        self.assertEqual(self.book().step(now=T0 - 1), 0)

    def test_records_a_closed_trade_with_funding_and_pnl(self):
        self.fill()
        self.assertGreater(self.book().step(now=T0 + hb.HOLD_S + 3600), 0)
        rows = [dict(r) for r in sqlite3_rows(self.state)]
        self.assertEqual([(r["coin"], r["status"]) for r in rows], [("BTC", "closed")])
        r = rows[0]
        want = hb.net_bps(r["entry_px"], r["exit_px"], 1.0)
        self.assertAlmostEqual(r["net_bps"], want)
        self.assertAlmostEqual(r["usd_pnl"], 1000.0 * want / 1e4)

    def test_a_finished_trade_is_never_rewritten(self):
        self.fill()
        now = T0 + hb.HOLD_S + 3600
        book = self.book()
        book.step(now=now)
        db = sqlite3.connect(self.state)
        db.execute("UPDATE trades SET exit_px = 12345")
        db.commit()
        db.close()
        self.write_slot(T0 + hb.SLOT_S, T0 + hb.SLOT_S + 5, [("a", "BTC", 0.0)])
        book.step(now=now + 900)
        self.assertEqual({r["exit_px"] for r in sqlite3_rows(self.state)}, {12345.0})

    def test_nothing_new_on_disk_makes_no_api_call(self):
        self.fill()
        book = self.book()
        book.step(now=T0 + hb.HOLD_S + 3600)
        calls = []
        book.fetch = lambda body: calls.append(body) or []
        self.assertEqual(book.step(now=T0 + hb.HOLD_S + 3660), 0)
        self.assertEqual(calls, [])

    def test_each_test_uses_its_own_guard(self):
        self.fill()
        rec = self.data / "hlp_reads" / "2026-11-05" / "0000.json"
        rec.parent.mkdir(parents=True)
        rec.write_text('{"ts": 1, "accounts": ["a"], "failed": ["a"]}')
        now = T0 + hb.HOLD_S + 3600
        self.assertGreater(self.book().step(now=now), 0)
        two = hb.Book(Path(self.tmp.name) / "two.db", self.data, fetch=self.no_network, pace=0, log=lambda _: None,
                      test=59)
        self.addCleanup(two.close)
        self.assertEqual(two.step(now=now), 0)
        self.assertEqual(hb.ledger(self.data, self.no_network, guard="reads")["rows"], [])
        self.assertEqual(len(hb.ledger(self.data, self.no_network)["rows"]), 1)

    def test_the_ledger_agrees_with_the_book(self):
        self.fill()
        self.book().step(now=T0 + hb.HOLD_S + 3600)
        out = hb.ledger(self.data, fetch=self.no_network)
        book = list(sqlite3_rows(self.state))[0]
        row = [r for r in out["rows"] if r["status"] == "closed"][0]
        self.assertEqual((row["coin"], row["signal_ts"], row["entry_px"], row["exit_px"]),
                         (book["coin"], book["signal_ts"], book["entry_px"], book["exit_px"]))
        self.assertAlmostEqual(row["net_bps"], book["net_bps"])
        self.assertEqual(out["result"]["verdict"], "INCONCLUSIVE")


def sqlite3_rows(path):
    db = sqlite3.connect(path)
    db.row_factory = sqlite3.Row
    rows = db.execute("SELECT * FROM trades").fetchall()
    db.close()
    return rows


if __name__ == "__main__":
    unittest.main(verbosity=2)
