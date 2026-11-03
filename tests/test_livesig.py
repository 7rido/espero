"""#71's rule, on made-up data only."""
import unittest

from espero import livesig


class TestRule(unittest.TestCase):
    def test_the_rule_exists(self):
        """Replace with the rule's behaviour, then break the rule and confirm this fails."""
        self.assertTrue(callable(livesig.rule))


if __name__ == "__main__":
    unittest.main()
