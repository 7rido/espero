"""#76's rule, on made-up data only."""
import unittest

from espero import nightshift


class TestRule(unittest.TestCase):
    def test_the_rule_exists(self):
        """Replace with the rule's behaviour, then break the rule and confirm this fails."""
        self.assertTrue(callable(nightshift.rule))


if __name__ == "__main__":
    unittest.main()
