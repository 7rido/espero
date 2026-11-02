"""#64's rule, trades and verdict, on made-up data only."""
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import numpy as np
import pandas as pd

from espero import hlpbook as hb
from espero import liqvault as lv

V1, V2 = lv.VAULTS[0], lv.VAULTS[1]
SLOT = lv.WINDOW_START + 40 * lv.SLOT_S          # a slot inside the window
PREV = SLOT - lv.SLOT_S
COIN = "XPL"


def slot(at, positions=None, ts=None, clean=True):
    """A slot whose vault rows are {(address, coin): (szi, value)}."""
    return lv.Slot(at, at if ts is None else ts, dict(positions or {}), clean)


def market(coin=COIN, start=SLOT - 2 * 3600, end=SLOT + 8 * 3600, px=100.0, later=110.0, turn=None):
    """One candle a minute: px before `turn`, `later` from it; each candle opens one unit below its close."""
    turn = SLOT + lv.KNOWN_AFTER_S + 600 if turn is None else turn
    starts = np.arange(start, end, 60)
    closes = np.where(starts < turn, px, later)
    p = hb.Prices()
    p.add(coin, pd.DataFrame({"ts": starts, "open": closes - 1, "close": closes}))
    return p


class TheRegisteredNumbers(unittest.TestCase):
    def test_numbers(self):
        self.assertEqual((lv.SLOT_S, lv.KNOWN_AFTER_S, lv.MIN_VALUE_USD, lv.MIN_TRADES, lv.PASS_T, lv.COST_BPS,
                          lv.LATER_FRACTION), (900, 120, 50_000.0, 30, 3.0, 18.0, 0.25))
        self.assertEqual(len(lv.VAULTS), 4)
        self.assertEqual(lv.WINDOW_START, hb._utc(2026, 11, 4))
        self.assertEqual(lv.WINDOW_END, hb._utc(2027, 4, 1))
        self.assertEqual((hb.ENTRY_DELAY_S, hb.HOLD_S, hb.FILL_TOLERANCE_S), (60, 14400, 300))


class TheReadRecord(unittest.TestCase):
    def write(self, failed):
        root = Path(self.tmp.name)
        (root / "hlp" / "2026-11-04").mkdir(parents=True, exist_ok=True)
        (root / "hlp_reads" / "2026-11-04").mkdir(parents=True, exist_ok=True)
        path = root / "hlp" / "2026-11-04" / "1000.csv.gz"
        pd.DataFrame(columns=["ts", "address", "coin", "szi", "value"]).to_csv(path, index=False)
        record = root / "hlp_reads" / "2026-11-04" / "1000.json"
        if failed is None:
            record.unlink(missing_ok=True)
        else:
            record.write_text(json.dumps({"ts": 1, "failed": failed}))
        return path

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()

    def tearDown(self):
        self.tmp.cleanup()

    def test_only_a_vault_failure_voids(self):
        self.assertIs(lv.read_record(self.write([])), True)
        self.assertIs(lv.read_record(self.write(["0x010461c14e146ac35fe42271bdc1134ee31c703a"])), True)
        self.assertIs(lv.read_record(self.write([V2.upper()])), False)
        self.assertIsNone(lv.read_record(self.write(None)))

    def test_read_slot_keeps_vault_rows_only(self):
        root = Path(self.tmp.name)
        path = self.write([])
        pd.DataFrame([{"ts": 123, "address": V1.upper(), "coin": COIN, "szi": 5.0, "value": 60_000.0},
                      {"ts": 123, "address": "0x0104", "coin": COIN, "szi": 9.0, "value": 1e6}]).to_csv(path, index=False)
        s = lv.read_slot(path)
        self.assertEqual((s.slot, s.ts, s.clean), (hb.slot_of(path), 123, True))
        self.assertEqual(s.positions, {(V1, COIN): (5.0, 60_000.0)})


class NewInventory(unittest.TestCase):
    def test_new_absent_before(self):
        got = lv.new_positions(slot(PREV), slot(SLOT, {(V1, COIN): (5.0, 60_000.0)}))
        self.assertEqual(got, [lv.Signal(COIN, SLOT + 120, 1, V1, 60_000.0, SLOT)])

    def test_persisting_position_is_not_new(self):
        self.assertEqual(lv.new_positions(slot(PREV, {(V1, COIN): (5.0, 60_000.0)}),
                                          slot(SLOT, {(V1, COIN): (9.0, 90_000.0)})), [])

    def test_a_flip_is_new_and_short_has_its_sign(self):
        got = lv.new_positions(slot(PREV, {(V1, COIN): (5.0, 60_000.0)}), slot(SLOT, {(V1, COIN): (-7.0, 80_000.0)}))
        self.assertEqual([(g.side, g.value) for g in got], [(-1, 80_000.0)])

    def test_dust_and_zero_are_not_signals(self):
        self.assertEqual(lv.new_positions(slot(PREV), slot(SLOT, {(V1, COIN): (5.0, 49_999.99)})), [])
        self.assertEqual(len(lv.new_positions(slot(PREV), slot(SLOT, {(V1, COIN): (5.0, 50_000.0)}))), 1)
        self.assertEqual(lv.new_positions(slot(PREV), slot(SLOT, {(V1, COIN): (0.0, 60_000.0)})), [])

    def test_signal_time_is_the_read_start_plus_120(self):
        got = lv.new_positions(slot(PREV), slot(SLOT, {(V1, COIN): (5.0, 60_000.0)}, ts=SLOT + 7))
        self.assertEqual(got[0].ts, SLOT + 7 + 120)


class TheWalk(unittest.TestCase):
    def test_signal_needs_the_previous_slot_and_clean_records(self):
        cur = slot(SLOT, {(V1, COIN): (5.0, 60_000.0)})
        self.assertEqual(len(lv.walk([slot(PREV), cur])["signals"]), 1)
        self.assertEqual(len(lv.walk([cur])["signals"]), 0)
        self.assertEqual(lv.walk([cur])["counts"]["no_previous_slot"], 1)
        self.assertEqual(len(lv.walk([slot(PREV - lv.SLOT_S), cur])["signals"]), 0)
        for prev_clean, cur_clean in ((False, True), (True, False), (None, True)):
            found = lv.walk([slot(PREV, clean=prev_clean), slot(SLOT, {(V1, COIN): (5.0, 60_000.0)}, clean=cur_clean)])
            self.assertEqual((len(found["signals"]), found["counts"]["void"]), (0, 1))

    def test_outside_the_window_nothing_counts(self):
        before = lv.WINDOW_START - 100 * lv.SLOT_S
        found = lv.walk([slot(before - lv.SLOT_S), slot(before, {(V1, COIN): (5.0, 60_000.0)})])
        self.assertEqual((len(found["signals"]), found["counts"]["outside_window"]), (0, 2))
        last = lv.WINDOW_END - 60                        # ts + 120 falls past the window's end
        found = lv.walk([slot(last - lv.SLOT_S), slot(last, {(V1, COIN): (5.0, 60_000.0)})])
        self.assertEqual(len(found["signals"]), 0)
        first = lv.WINDOW_START - 100                    # ts + 120 is 20 s into the window
        found = lv.walk([slot(first - lv.SLOT_S), slot(first, {(V1, COIN): (5.0, 60_000.0)})])
        self.assertEqual(len(found["signals"]), 1)

    def test_later_entry_and_unwind(self):
        slots = [slot(PREV), slot(SLOT, {(V1, COIN): (100.0, 60_000.0)}),
                 slot(SLOT + 900, {(V1, COIN): (60.0, 36_000.0)}), slot(SLOT + 1800, {(V1, COIN): (25.0, 15_000.0)}),
                 slot(SLOT + 2700, {(V1, COIN): (25.0, 15_000.0)}), slot(SLOT + 3600)]
        found = lv.walk(slots)
        self.assertEqual(found["later"], [lv.Signal(COIN, SLOT + 1800 + 120, 1, V1, 60_000.0, SLOT + 1800)])
        self.assertEqual(found["unwind"], {(COIN, SLOT + 120): 4})
        found = lv.walk(slots[:3])
        self.assertEqual((found["later"], found["unwind"]), ([], {(COIN, SLOT + 120): None}))


class TheTrades(unittest.TestCase):
    def test_side_is_kept_and_fills_follow_58(self):
        s = lv.Signal(COIN, SLOT + 120, -1, V2, 70_000.0, SLOT)
        rows = lv.trades([s], market(), final=True)
        self.assertEqual(len(rows), 1)
        r = rows[0]
        self.assertEqual((r["status"], r["side"], r["address"], r["entry_ts"]), ("closed", -1, V2, SLOT + 180))
        self.assertEqual(r["exit_ts"], SLOT + 180 + hb.HOLD_S)
        self.assertEqual((r["entry_px"], r["exit_px"]), (99.0, 109.0))

    def test_one_at_a_time_across_vaults(self):
        a = lv.Signal(COIN, SLOT + 120, 1, V1, 70_000.0, SLOT)
        b = lv.Signal(COIN, SLOT + 900 + 120, 1, V2, 70_000.0, SLOT + 900)
        rows = lv.trades([b, a], market(), final=True)
        self.assertEqual([(r["address"], r["status"]) for r in rows], [(V1, "closed"), (V2, "ignored")])


class TheNet(unittest.TestCase):
    def test_sides_and_funding(self):
        self.assertAlmostEqual(lv.net_bps(1, 100.0, 101.0, 2.0), 100 - 18 - 2)
        self.assertAlmostEqual(lv.net_bps(-1, 100.0, 101.0, 2.0), -100 - 18 + 2)
        self.assertAlmostEqual(lv.net_bps(-1, 100.0, 99.0, -3.0), 100 - 18 - 3)

    def test_closed_trades_use_the_side(self):
        rows = [{"status": "closed", "coin": COIN, "entry_ts": 1, "exit_ts": 2, "entry_px": 100.0, "exit_px": 98.0,
                 "side": -1, "address": V1, "value": 1.0, "slot": 0},
                {"status": "dropped_entry", "coin": COIN, "entry_ts": None, "exit_ts": None, "entry_px": None,
                 "exit_px": None, "side": 1, "address": V1, "value": 1.0, "slot": 0}]
        with mock.patch.object(hb, "funding_bps", return_value=5.0):
            closed = lv.closed_trades(rows)
        self.assertEqual(len(closed), 1)
        self.assertAlmostEqual(float(closed["gross_bps"].iloc[0]), 200.0)
        self.assertAlmostEqual(float(closed["net_bps"].iloc[0]), 200 - 18 + 5)


def frame(nets, coins=None, days=None):
    n = len(nets)
    coins = coins or [f"C{i % 7}" for i in range(n)]
    days = days or [lv.WINDOW_START + (i * 3 % 140) * 86400 for i in range(n)]
    return pd.DataFrame({"coin": coins, "entry_ts": days, "net_bps": nets})


class TheVerdict(unittest.TestCase):
    def test_fewer_than_30_is_inconclusive(self):
        self.assertEqual(lv.evaluate(frame([50.0] * 29))["verdict"], "INCONCLUSIVE")
        self.assertNotEqual(lv.evaluate(frame([50.0] * 30))["verdict"], "INCONCLUSIVE")

    def test_pass_needs_every_check(self):
        rng = np.random.default_rng(3)
        nets = list(60.0 + 10.0 * rng.standard_normal(40))
        out = lv.evaluate(frame(nets))
        self.assertEqual(out["verdict"], "PASS", out)
        self.assertEqual(set(out["checks"]), {"pays", "both_halves", "coins", "median"})

    def test_t_below_3_fails(self):
        rng = np.random.default_rng(4)
        nets = list(20.0 + 100.0 * rng.standard_normal(40))
        out = lv.evaluate(frame(nets))
        self.assertLess(out["t"], 3)
        self.assertFalse(out["checks"]["pays"])
        self.assertEqual(out["verdict"], "FAIL")

    def test_one_coin_carrying_it_fails(self):
        nets = [-5.0] * 35 + [2000.0] * 5
        coins = [f"C{i % 7}" for i in range(35)] + ["BIG"] * 5
        out = lv.evaluate(frame(nets, coins))
        self.assertGreater(out["mean"], 0)
        self.assertFalse(out["checks"]["coins"])
        self.assertEqual(out["verdict"], "FAIL")

    def test_a_few_trades_carrying_it_fails_on_the_median(self):
        rng = np.random.default_rng(5)
        nets = [-1.0 - abs(x) for x in rng.standard_normal(25)] + [300.0 + abs(x) for x in rng.standard_normal(15)]
        out = lv.evaluate(frame(nets))
        self.assertFalse(out["checks"]["median"])
        self.assertEqual(out["verdict"], "FAIL")

    def test_one_half_fails(self):
        days = [lv.WINDOW_START + 86400 * (i % 30) for i in range(40)]          # all before 2027-01-17
        out = lv.evaluate(frame([60.0] * 40, days=days))
        self.assertFalse(out["checks"]["both_halves"])


class TheLedger(unittest.TestCase):
    def test_refuses_before_the_window_closes(self):
        with self.assertRaises(RuntimeError):
            lv.ledger(Path("/nonexistent"), now=lv.WINDOW_END - 1)

    def test_runs_on_made_up_files_after(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            day = pd.Timestamp(SLOT, unit="s").strftime("%Y-%m-%d")
            for sub in ("hlp", "hlp_reads", "ctx"):
                (root / sub / day).mkdir(parents=True)
            (root / "candles").mkdir()
            for at, rows in ((PREV, []), (SLOT, [{"ts": SLOT + 3, "address": V1, "coin": COIN, "szi": 5.0, "value": 60_000.0}]),
                             (SLOT + 900, [])):
                hhmm = pd.Timestamp(at, unit="s").strftime("%H%M")
                pd.DataFrame(rows, columns=["ts", "address", "coin", "szi", "value"]).to_csv(root / "hlp" / day / f"{hhmm}.csv.gz", index=False)
                (root / "hlp_reads" / day / f"{hhmm}.json").write_text(json.dumps({"ts": at, "failed": []}))
                pd.DataFrame([{"coin": COIN, "day_volume": 7e6}]).to_csv(root / "ctx" / day / f"{hhmm}.csv.gz", index=False)
            p = market()
            starts, opens, closes = p._arrays(COIN)
            pd.DataFrame({"ts": starts, "coin": COIN, "open": opens, "close": closes}).to_csv(root / "candles" / f"{day}.csv.gz", index=False)
            with mock.patch.object(lv, "fetch_recent", return_value=0), mock.patch.object(hb, "funding_bps", return_value=1.0):
                out = lv.ledger(root, now=lv.WINDOW_END + 10)
        self.assertEqual(out["verdict"]["verdict"], "INCONCLUSIVE")
        self.assertEqual(out["statuses"], {"closed": 1})
        self.assertEqual(out["counts"]["signals"], 1)
        self.assertEqual(out["information"]["by_tier"], {"$5M–$50M": {"n": 1, "mean": 1e4 * (109 / 99 - 1) - 18 - 1}})
        self.assertEqual(out["information"]["unwind_slots_median"], 1.0)
        self.assertEqual(out["rows"][0]["side"], 1)

    def test_status_opens_nothing(self):
        with tempfile.TemporaryDirectory() as tmp:
            lines = lv.status(Path(tmp), now=lv.WINDOW_START - 1)
        self.assertIn("not open yet", lines[0])
        self.assertIn("HLP slots on disk: 0", lines[1])


if __name__ == "__main__":
    unittest.main()
