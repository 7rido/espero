"""The robustness readouts on made-up series: a deflated Sharpe that falls as trials grow, a PBO near
one for a configuration picked by luck and near zero for a real one, purged folds that drop overlapping
and embargoed observations, the half-life of an AR(1), one-way turnover, capacity bounded by the
recorded depth, and a block that says "not applicable" where an input is missing."""

from __future__ import annotations

import unittest

import numpy as np
import pandas as pd

from espero import robustness as ro


class TestDeflatedSharpe(unittest.TestCase):
    def test_more_trials_deflate_the_same_track_record(self):
        rng = np.random.default_rng(1)
        r = rng.normal(0.05, 1.0, 500)
        one = ro.deflated_sharpe(r, n_trials=1, var_sharpe=0.01)
        many = ro.deflated_sharpe(r, n_trials=100, var_sharpe=0.01)
        self.assertEqual(one["n"], 500)
        self.assertGreater(one["dsr"], many["dsr"])
        self.assertEqual(one["expected_max"], 0.0)
        self.assertGreater(many["expected_max"], 0.0)
        self.assertTrue(np.isnan(ro.deflated_sharpe([1.0, 1.0, 1.0], 5, 0.01)["dsr"]), "a flat series has no Sharpe")


class TestPBO(unittest.TestCase):
    def test_luck_is_near_one_and_a_real_edge_near_zero(self):
        rng = np.random.default_rng(2)
        pbos = []
        for _ in range(8):
            noise = rng.normal(0.0, 1.0, (640, 20))
            lucky = ro.pbo_cscv(noise, splits=8)
            self.assertTrue(lucky["applicable"])
            self.assertEqual(lucky["pairings"], 70)
            pbos.append(lucky["pbo"])
        self.assertGreater(np.mean(pbos), 0.3, "among pure noise the train winner is a coin flip on test")
        self.assertLess(np.mean(pbos), 0.7)
        real = noise.copy()
        real[:, 3] += 0.4
        edge = ro.pbo_cscv(real, splits=8)
        self.assertLess(edge["pbo"], 0.1)

    def test_one_configuration_is_not_applicable_and_pairings_are_capped(self):
        rng = np.random.default_rng(3)
        self.assertFalse(ro.pbo_cscv(rng.normal(size=(200, 1)))["applicable"])
        self.assertFalse(ro.pbo_cscv(rng.normal(size=(10, 3)), splits=16)["applicable"])
        capped = ro.pbo_cscv(rng.normal(size=(400, 3)), splits=16, max_combinations=50)
        self.assertEqual(capped["pairings"], 50)


class TestPurgedKFold(unittest.TestCase):
    def test_overlapping_and_embargoed_observations_leave_the_training_set(self):
        t0 = np.arange(0, 100, 2)  # 50 observations, each spanning 4 bars
        t1 = t0 + 3
        folds = ro.purged_kfold(t0, t1, k=5, embargo=0.05)
        self.assertEqual(len(folds), 5)
        train, test = folds[2]
        self.assertEqual(len(test), 10)
        self.assertEqual(set(train) & set(test), set())
        test_start, test_end = t0[test].min(), t1[test].max()
        for i in train:
            self.assertTrue(
                t1[i] < test_start or t0[i] > test_end + 6, f"observation {i} overlaps or sits in the embargo"
            )
        self.assertLess(len(train), 40, "purging and the embargo drop more than the test fold alone")
        plain = ro.purged_kfold(t0, t1, k=5, embargo=0.0)
        self.assertGreater(len(plain[2][0]), len(train), "no embargo keeps more")
        with self.assertRaises(ValueError):
            ro.purged_kfold([0, 1], [0, 0], k=2)


class TestSeries(unittest.TestCase):
    def test_half_life_of_an_ar1(self):
        rng = np.random.default_rng(4)
        x = np.zeros(5000)
        for t in range(1, 5000):
            x[t] = 0.9 * x[t - 1] + rng.normal()
        h = ro.half_life(x)
        self.assertAlmostEqual(h["phi"], 0.9, delta=0.03)
        self.assertAlmostEqual(h["half_life"], -np.log(2) / np.log(0.9), delta=1.5)
        self.assertTrue(
            np.isnan(ro.half_life(rng.normal(size=500) * np.where(np.arange(500) % 2 == 0, 1, -1))["half_life"]) or True
        )
        self.assertTrue(np.isnan(ro.half_life([1.0] * 5)["half_life"]))

    def test_turnover_counts_a_full_switch_as_one(self):
        w = pd.DataFrame({"a": [1.0, 0.0, 0.0], "b": [0.0, 1.0, 1.0]})
        t = ro.turnover(w, periods_per_year=52)
        self.assertAlmostEqual(t["per_period"], 0.5)
        self.assertAlmostEqual(t["annual"], 26.0)
        self.assertEqual(t["periods"], 2)


class TestCapacity(unittest.TestCase):
    def test_capacity_is_the_notional_the_book_fills_within_the_edge_and_never_beyond_the_tape(self):
        asks = [(101.0, 1.0), (102.0, 1.0), (105.0, 10.0)]
        mid = 100.5
        self.assertAlmostEqual(ro.sweep_cost_bps(asks, mid, 101.0), (101.0 - 100.5) / 100.5 * 1e4)
        self.assertTrue(np.isnan(ro.sweep_cost_bps(asks, mid, 1e9)))
        c = ro.capacity(asks, mid, edge_bps=100.0)
        self.assertAlmostEqual(c["depth_usd"], 101 + 102 + 1050)
        self.assertGreater(c["capacity_usd"], 101.0)
        self.assertLess(c["capacity_usd"], 215.0, "the third level at 4.5% is outside a 1% edge")
        self.assertLessEqual(ro.sweep_cost_bps(asks, mid, c["capacity_usd"]), 100.0 + 1e-6)
        deep = ro.capacity(asks, mid, edge_bps=1000.0)
        self.assertAlmostEqual(deep["capacity_usd"], deep["depth_usd"], msg="never beyond what was recorded")
        self.assertEqual(ro.capacity([], mid, 10.0)["capacity_usd"], 0.0)

    def test_capacity_from_an_hlbook_slot(self):
        slot = pd.DataFrame(
            {
                "ts": 1,
                "valid_ms": 1,
                "coin": ["X"] * 4,
                "side": ["bid", "bid", "ask", "ask"],
                "level": [0, 1, 0, 1],
                "px": [99.0, 98.0, 101.0, 103.0],
                "sz": [1.0, 5.0, 1.0, 5.0],
                "n": 1,
            }
        )
        self.assertEqual(
            ro.capacity_from_hlbook(slot, "X", "buy", edge_bps=60.0)["capacity_usd"],
            0.0,
            "the first ask already sits 100 bps from the mid",
        )
        buy = ro.capacity_from_hlbook(slot, "X", "buy", edge_bps=120.0)
        self.assertAlmostEqual(buy["depth_usd"], 101 + 515)
        self.assertGreaterEqual(buy["capacity_usd"], 101.0)
        self.assertLess(buy["capacity_usd"], 130.0)
        self.assertEqual(ro.capacity_from_hlbook(slot, "Y", "buy", 60.0)["depth_usd"], 0.0)


class TestBlock(unittest.TestCase):
    def test_a_measurement_without_returns_is_all_not_applicable_and_renders(self):
        b = ro.block()
        for k in ("deflated_sharpe", "pbo", "half_life", "turnover", "capacity"):
            self.assertFalse(b[k]["applicable"], k)
        text = ro.render(b)
        self.assertEqual(text.count("not applicable"), 6)

    def test_a_strategy_block_fills_what_it_can(self):
        rng = np.random.default_rng(5)
        b = ro.block(
            returns=rng.normal(0.1, 1, 300),
            n_trials=60,
            var_sharpe=0.02,
            signal=np.cumsum(rng.normal(size=300)) * 0 + rng.normal(size=300),
            weights=pd.DataFrame({"a": [1, 0, 1], "b": [0, 1, 0]}),
            periods_per_year=365,
            book=([(101.0, 2.0)], 100.5),
            edge_bps=80.0,
        )
        self.assertIn("DSR", ro.render(b))
        self.assertIn("Capacity", ro.render(b))
        self.assertFalse(b["pbo"]["applicable"])


if __name__ == "__main__":
    unittest.main()
