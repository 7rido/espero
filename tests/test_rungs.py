"""The ladder's scaling rule, on made-up blocks of fills: no sleeve has climbed it."""
import unittest

from espero import rungs as G


def block(fills=30, shortfall=4.0, budget=6.0, breaks=0, alarm=False):
    return G.Block(fills, shortfall, budget, breaks, alarm)


class TestBreach(unittest.TestCase):
    def test_a_block_inside_budget_with_no_break_passes(self):
        self.assertIsNone(G.breach(block()))
        self.assertIsNone(G.breach(block(shortfall=6.0)))

    def test_shortfall_breaks_and_alarms_are_breaches(self):
        self.assertIn("over the", G.breach(block(shortfall=6.1)))
        self.assertIn("break", G.breach(block(breaks=1)))
        self.assertIn("edgewatch", G.breach(block(alarm=True)))
        self.assertIn("over the", G.breach(block(shortfall=float("nan"))))


class TestStep(unittest.TestCase):
    def test_the_climb_from_canary_to_target(self):
        s = G.State("canary")
        s = G.step(s, block())
        self.assertEqual((s.rung, s.fraction), ("scaled", 0.10))
        fractions = []
        for _ in range(10):                                  # bounded: a rule that never arrives must fail, not hang
            if s.rung != "scaled":
                break
            s = G.step(s, block())
            fractions.append(s.fraction)
        self.assertEqual(fractions, [0.2, 0.4, 0.8, 1.0])
        self.assertEqual(s.rung, "target")
        self.assertEqual(G.step(s, block()), G.State("target", 1.0, 0))

    def test_a_short_block_does_not_move_but_a_breach_needs_no_full_block(self):
        s = G.State("scaled", 0.4)
        self.assertEqual(G.step(s, block(fills=29)), s)
        self.assertEqual(G.step(s, block(fills=5, breaks=1)), G.State("scaled", 0.2, 1))

    def test_a_breach_halves_and_two_in_a_row_go_back_to_the_canary(self):
        s = G.step(G.State("scaled", 0.4), block(shortfall=9.0))
        self.assertEqual(s, G.State("scaled", 0.2, 1))
        self.assertEqual(G.step(s, block(shortfall=9.0)), G.State("canary", 0.0, 0))
        self.assertEqual(G.step(s, block()), G.State("scaled", 0.4, 0))       # a pass resets the count

    def test_the_halving_has_a_floor(self):
        self.assertEqual(G.step(G.State("scaled", 0.1), block(breaks=1)).fraction, 0.05)
        self.assertEqual(G.step(G.State("scaled", 0.05), block(breaks=1)).fraction, 0.05)    # not 2.5 %

    def test_a_breach_at_target_steps_down_to_half(self):
        self.assertEqual(G.step(G.State("target", 1.0), block(alarm=True)), G.State("scaled", 0.5, 1))

    def test_two_canary_breaches_in_a_row_go_back_to_testnet(self):
        s = G.step(G.State("canary"), block(breaks=1))
        self.assertEqual(s, G.State("canary", 0.0, 1))
        self.assertEqual(G.step(s, block(breaks=1)), G.State("testnet", 0.0, 0))

    def test_an_empty_block_is_not_judged(self):
        """No fills means no median (NaN): that is nothing measured, not a breach, so two empty blocks in a row
        must not send a canary back to testnet. A break or an alarm in an empty block still counts."""
        s = G.State("canary")
        empty = block(fills=0, shortfall=float("nan"))
        self.assertEqual(G.step(s, empty), s)
        self.assertEqual(G.step(G.step(s, empty), empty), s)
        self.assertEqual(G.step(s, block(fills=0, shortfall=float("nan"), breaks=1)), G.State("canary", 0.0, 1))

    def test_a_block_with_no_budget_is_a_breach(self):
        self.assertIn("no budget", G.breach(block(budget=float("nan"))))
        self.assertIn("no budget", G.breach(block(shortfall=50.0, budget=float("nan"))))

    def test_paper_and_testnet_move_by_the_holders_decision_only(self):
        for r in ("paper", "testnet"):
            with self.assertRaises(ValueError):
                G.step(G.State(r), block())


class TestFraction(unittest.TestCase):
    def test_only_scaled_and_target_carry_size(self):
        self.assertEqual([G.size_fraction(G.State(r, 0.3)) for r in G.RUNGS], [0.0, 0.0, 0.0, 0.3, 1.0])

    def test_the_registered_numbers(self):
        self.assertEqual((G.TESTNET_ROUND_TRIPS, G.CANARY_FILLS, G.START_FRACTION, G.STEP_UP, G.STEP_DOWN,
                          G.BREACHES_TO_CANARY), (50, 30, 0.10, 2.0, 0.5, 2))


class TestTheCanaryAmendment(unittest.TestCase):
    def test_only_rule_8s_canary_needs_ten_testnet_round_trips(self):
        self.assertEqual(G.testnet_round_trips(G.CANARY_MF), 10)
        self.assertEqual(G.CANARY_MF, "mf-canary")
        for other in ("mf", "carry", "hlp2", "", "MF-CANARY"):
            self.assertEqual(G.testnet_round_trips(other), 50, other)

if __name__ == "__main__":
    unittest.main()
