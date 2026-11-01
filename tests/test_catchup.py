"""#57's event rule, fills and verdict, on made-up data only."""
import unittest

import numpy as np

from espero import catchup as cu


def book_of(ms, mid, half=0.01, qty=1e6, levels=5):
    n = len(ms)
    asks = np.tile(np.asarray(mid, dtype=float).reshape(-1, 1) + half, (1, levels))
    bids = np.tile(np.asarray(mid, dtype=float).reshape(-1, 1) - half, (1, levels))
    return {"ms": np.asarray(ms, dtype=float), "asks_px": asks, "bids_px": bids,
            "asks_qty": np.full((n, levels), float(qty)), "bids_qty": np.full((n, levels), float(qty))}


class EventTests(unittest.TestCase):
    def test_up_move_of_ten_bps_is_an_up_event(self):
        out = cu.events(np.array([0.0, 1500.0]), np.array([100.0, 100.105]))
        self.assertEqual(out.tolist(), [[1.0, 1.0]])

    def test_down_move_is_a_down_event(self):
        out = cu.events(np.array([0.0, 1500.0]), np.array([100.0, 99.895]))
        self.assertEqual(out.tolist(), [[1.0, -1.0]])

    def test_small_move_is_not_an_event(self):
        self.assertEqual(len(cu.events(np.array([0.0, 1500.0]), np.array([100.0, 100.095]))), 0)

    def test_reference_is_the_last_trade_at_or_before_one_second_earlier(self):
        # At 3,000 ms the reference is 1,500's 100.05, under 10 bps; against 0's 100.0 it would be 15.
        out = cu.events(np.array([0.0, 1500.0, 3000.0]), np.array([100.0, 100.05, 100.15]))
        self.assertEqual(len(out), 0)

    def test_reference_includes_a_trade_exactly_one_second_earlier(self):
        self.assertEqual(len(cu.events(np.array([0.0, 1000.0]), np.array([100.0, 100.105]))), 1)

    def test_no_reference_means_no_event(self):
        self.assertEqual(len(cu.events(np.array([0.0, 500.0]), np.array([100.0, 100.2]))), 0)

    def test_spacing_runs_from_the_last_kept_event(self):
        ms = np.array([0.0, 1500.0, 21500.0, 23000.0, 40000.0, 41500.0])
        px = np.array([100.0, 100.2, 100.2, 100.4, 100.4, 100.6])
        self.assertEqual(cu.events(ms, px)[:, 0].tolist(), [1.0, 5.0])

    def test_event_exactly_at_the_gap_is_kept(self):
        ms = np.array([0.0, 1500.0, 30000.0, 31500.0])
        px = np.array([100.0, 100.2, 100.2, 100.4])
        self.assertEqual(cu.events(ms, px)[:, 0].tolist(), [1.0, 3.0])


class SnapshotTests(unittest.TestCase):
    def test_takes_the_first_at_or_after_never_before(self):
        ms = np.array([100.0, 200.0])
        self.assertEqual(cu.snapshot_at(ms, 150.0), 1)
        self.assertEqual(cu.snapshot_at(ms, 200.0), 1)

    def test_nothing_after_the_last_snapshot(self):
        self.assertIsNone(cu.snapshot_at(np.array([100.0]), 101.0))

    def test_too_stale_a_snapshot_is_refused(self):
        self.assertIsNone(cu.snapshot_at(np.array([6001.0]), 1000.0))
        self.assertEqual(cu.snapshot_at(np.array([6000.0]), 1000.0), 0)


class TradeTests(unittest.TestCase):
    def setUp(self):
        self.book = book_of([0.0, 1000.0, 31000.0], [100.0, 100.0, 100.5])

    def test_up_event_net_of_mid_move_walk_and_fees(self):
        out = cu.trade(self.book, 0.0, 1.0, 1000.0, 30000.0, 1000.0)
        gross = (100.5 / 100.0 - 1) * 1e4
        walk = 0.01 / 100.0 * 1e4 + 0.01 / 100.5 * 1e4
        self.assertAlmostEqual(out["gross"], gross)
        self.assertAlmostEqual(out["walk"], walk)
        self.assertEqual(out["fees"], 9.0)
        self.assertAlmostEqual(out["net"], gross - walk - 9.0)

    def test_down_event_loses_when_price_rises(self):
        out = cu.trade(self.book, 0.0, -1.0, 1000.0, 30000.0, 1000.0)
        self.assertAlmostEqual(out["gross"], -(100.5 / 100.0 - 1) * 1e4)
        self.assertGreater(out["walk"], 0)

    def test_delay_decides_the_entry_snapshot(self):
        book = book_of([0.0, 1000.0, 2000.0, 31000.0, 32000.0], [100.0, 100.0, 100.2, 100.5, 100.5])
        slow = cu.trade(book, 0.0, 1.0, 2000.0, 30000.0, 1000.0)
        self.assertAlmostEqual(slow["gross"], (100.5 / 100.2 - 1) * 1e4)

    def test_hold_runs_from_the_entry_time(self):
        book = book_of([1000.0, 5000.0, 6000.0, 31000.0], [100.0, 100.1, 100.2, 100.9])
        self.assertAlmostEqual(cu.trade(book, 0.0, 1.0, 1000.0, 5000.0, 1000.0)["gross"], (100.2 / 100.0 - 1) * 1e4)

    def test_missing_snapshot_is_counted_not_priced(self):
        no_entry, no_exit = book_of([0.0], [100.0]), book_of([1000.0], [100.0])
        self.assertEqual(cu.trade(no_entry, 0.0, 1.0, 1000.0, 30000.0, 1000.0)["status"], "no_snapshot")
        self.assertEqual(cu.trade(no_exit, 0.0, 1.0, 1000.0, 30000.0, 1000.0)["status"], "no_snapshot")
        late = book_of([31000.0], [100.0])
        self.assertEqual(cu.trade(late, 0.0, 1.0, 1000.0, 30000.0, 1000.0)["status"], "no_snapshot")

    def test_book_too_small_on_either_leg_is_unfillable(self):
        book = book_of([1000.0, 31000.0], [100.0, 100.0], qty=1.0)
        self.assertEqual(cu.trade(book, 0.0, 1.0, 1000.0, 30000.0, 1000.0)["status"], "unfillable")
        book = book_of([1000.0, 31000.0], [100.0, 100.0], qty=1e6)
        book["bids_qty"][1] = 1.0
        self.assertEqual(cu.trade(book, 0.0, 1.0, 1000.0, 30000.0, 1000.0)["status"], "unfillable")
        self.assertEqual(cu.trade(book, 0.0, -1.0, 1000.0, 30000.0, 1000.0)["status"], "ok")

    def test_entry_side_follows_the_direction(self):
        book = book_of([1000.0, 31000.0], [100.0, 100.0], qty=1e6)
        book["asks_qty"][0] = 1.0
        self.assertEqual(cu.trade(book, 0.0, 1.0, 1000.0, 30000.0, 1000.0)["status"], "unfillable")
        self.assertEqual(cu.trade(book, 0.0, -1.0, 1000.0, 30000.0, 1000.0)["status"], "ok")


class VerdictTests(unittest.TestCase):
    def test_not_captured_when_the_upper_end_is_at_or_below_zero(self):
        self.assertEqual(cu.verdict(-5, -1, 1, 1, 6, 0), "NOT CAPTURED")
        self.assertEqual(cu.verdict(-5, 0.0, 1, 1, 6, 0), "NOT CAPTURED")

    def test_worth_testing_needs_everything(self):
        self.assertEqual(cu.verdict(1, 2, 1, 1, 4, 0.05), "WORTH TESTING ON UNREAD DAYS")
        self.assertEqual(cu.verdict(0.0, 2, 1, 1, 4, 0.05), "CAN'T SAY")
        self.assertEqual(cu.verdict(1, 2, -1, 1, 4, 0.05), "CAN'T SAY")
        self.assertEqual(cu.verdict(1, 2, 1, -1, 4, 0.05), "CAN'T SAY")
        self.assertEqual(cu.verdict(1, 2, 1, 1, 3, 0.05), "CAN'T SAY")
        self.assertEqual(cu.verdict(1, 2, 1, 1, 4, 0.051), "CAN'T SAY")

    def test_interval_spanning_zero_cannot_say(self):
        self.assertEqual(cu.verdict(-1, 1, 1, 1, 6, 0), "CAN'T SAY")


if __name__ == "__main__":
    unittest.main()
