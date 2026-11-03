"""#70's live stop rule, on synthetic series only: no sleeve has a verdict, so no real series is read."""
import unittest

import numpy as np

from espero import edgewatch as E


def series(n=150, mu=0.3, seed=1):
    return np.random.default_rng(seed).normal(mu, 1.0, n)


class TestStatistic(unittest.TestCase):
    def test_the_registered_edge_adds_no_evidence_and_nothing_adds_it_fast(self):
        path, alarms = E.cusum([0.3] * 50, 0.3, 1.0)
        self.assertTrue(np.allclose(path, 0.0))
        self.assertEqual(alarms, [])
        path, _ = E.cusum([0.0] * 10, 0.3, 1.0)
        self.assertTrue(np.allclose(path, np.arange(1, 11) * 0.15))     # (0.3 - 0) / 1 - 0.15 a step

    def test_an_alarm_restarts_the_statistic(self):
        path, alarms = E.cusum([0.0] * 30, 0.3, 1.0, h=1.5)
        self.assertEqual(alarms, [9, 19, 29])
        self.assertAlmostEqual(path[9], 1.5)
        self.assertAlmostEqual(path[10], 0.15)

    def test_a_missing_observation_adds_nothing(self):
        a, _ = E.cusum([0.0, np.nan, 0.0], 0.3, 1.0)
        self.assertAlmostEqual(a[1], a[0])
        self.assertAlmostEqual(a[2], 0.3)

    def test_good_days_wear_the_evidence_down_but_never_below_zero(self):
        path, _ = E.cusum([0.0, 0.0, 1.0, 1.0, 1.0], 0.3, 1.0)
        self.assertAlmostEqual(path[1], 0.3)
        self.assertAlmostEqual(path[2], 0.0)
        self.assertTrue((path >= 0).all())

    def test_a_sleeve_without_a_positive_edge_has_nothing_to_watch(self):
        for mu0, sd in ((0.0, 1.0), (-0.1, 1.0), (0.2, 0.0)):
            with self.assertRaises(ValueError):
                E.reference_k(mu0, sd)


class TestThreshold(unittest.TestCase):
    def test_the_false_alarm_rate_holds_on_fresh_draws_from_the_same_distribution(self):
        x = series()
        h = E.calibrate_h(x, per_year=365, paths=4_000)
        rng = np.random.default_rng(99)
        mu0, sd = x.mean(), x.std(ddof=1)
        hits = sum(bool(E.cusum(rng.choice(x, 365), mu0, sd, h)[1]) for _ in range(400))
        self.assertLess(hits / 400, 0.09)
        self.assertGreater(hits / 400, 0.01)

    def test_the_threshold_is_the_larger_of_the_two_bootstraps(self):
        x = series()
        both = E.calibrate_h(x, 365, paths=2_000)
        each = [E.calibrate_h(x, 365, paths=2_000, blocks=(b,)) for b in E.BLOCKS]
        self.assertEqual(both, max(each))
        self.assertNotEqual(each[0], each[1])

    def test_a_vanished_edge_is_seen(self):
        x = series()
        h = E.calibrate_h(x, per_year=365, paths=4_000)
        _, alarms = E.cusum(np.random.default_rng(5).normal(0.0, 1.0, 365), x.mean(), x.std(ddof=1), h)
        self.assertTrue(alarms)
        self.assertLess(E.delay(x, h, paths=500), 365)

    def test_the_threshold_is_fixed_by_its_seed_and_rises_with_the_horizon(self):
        x = series()
        self.assertEqual(E.calibrate_h(x, 365, paths=2_000), E.calibrate_h(x, 365, paths=2_000))
        self.assertGreater(E.calibrate_h(x, 730, paths=2_000), E.calibrate_h(x, 90, paths=2_000))
        self.assertGreater(E.calibrate_h(x, 365, 0.01, paths=2_000), E.calibrate_h(x, 365, 0.10, paths=2_000))

    def test_too_short_a_registered_series_sets_no_threshold(self):
        with self.assertRaises(ValueError):
            E.calibrate_h(series(n=E.MIN_OBS - 1), 365)
        E.calibrate_h(series(n=E.MIN_OBS), 365, paths=500)

    def test_params_record_everything_a_sizing_document_quotes(self):
        x = series()
        p = E.params(x, per_year=250, paths=2_000)
        self.assertAlmostEqual(p.mu0, x.mean())
        self.assertAlmostEqual(p.k, x.mean() / (2 * x.std(ddof=1)))
        self.assertEqual((p.per_year, p.false_alarm), (250.0, 0.05))
        self.assertGreater(p.h, 0)
        self.assertGreater(p.delay_median, 0)

    def test_the_blocks_average_five_observations(self):
        rows = np.array(list(E.bootstrap_paths(np.arange(10_000.0), 2_000, paths=20, block=E.BLOCK)))
        continued = (np.diff(rows, axis=0) == 1).mean()             # a step that continues its block
        self.assertAlmostEqual(1 / (1 - continued), E.BLOCK, delta=0.3)

    def test_the_bootstrap_draws_only_from_the_series(self):
        x = [1.0, 2.0, 3.0, np.nan]
        rows = list(E.bootstrap_paths(x, 20, paths=50))
        self.assertEqual(len(rows), 20)
        self.assertTrue(set(np.concatenate(rows)) <= {1.0, 2.0, 3.0})


class TestActions(unittest.TestCase):
    def test_first_alarm_halves_and_the_second_flattens(self):
        self.assertEqual([E.scale(n) for n in (0, 1, 2, 3)], [1.0, 0.5, 0.0, 0.0])
        self.assertIn("halve", E.action("live-from-tape", 1))
        self.assertIn("call the operator", E.action("live-from-tape", 1))
        self.assertIn("silence halves", E.action("operator-paced", 1))
        for klass in ("live-from-tape", "operator-paced"):
            self.assertIn("flat", E.action(klass, 2))
            self.assertEqual(E.action(klass, 0), "nothing")

    def test_rules_not_traded_live_are_never_acted_on(self):
        for klass in ("next-day-batch", "not tradable live"):
            with self.assertRaises(ValueError):
                E.action(klass, 1)

    def test_binding_from_the_canary_on(self):
        self.assertEqual([E.binding(r) for r in ("paper", "testnet", "canary", "scaled", "target")],
                         [False, False, True, True, True])

    def test_the_registered_numbers(self):
        self.assertEqual((E.FALSE_ALARM, E.BLOCK, E.PATHS, E.SEED, E.MIN_OBS), (0.05, 5.0, 20_000, 0, 30))
        self.assertIs(E.rule(), E.cusum)


if __name__ == "__main__":
    unittest.main()
