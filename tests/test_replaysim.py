"""#62's rule, on made-up data only."""
import unittest

from espero import replaysim


class TestRule(unittest.TestCase):
    def test_the_rule_exists(self):
        """Replace with the rule's behaviour, then break the rule and confirm this fails."""
        self.assertTrue(callable(replaysim.rule))


if __name__ == "__main__":
    unittest.main()
