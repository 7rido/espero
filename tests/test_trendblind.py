"""#79's list and bar helper on made-up frames."""
import unittest

import numpy as np
import pandas as pd

from espero import trendblind as B


class TestList(unittest.TestCase):
    def test_thirty_distinct_symbols_in_order(self):
        self.assertEqual(len(B.DOW), 30)
        self.assertEqual(len(set(B.DOW)), 30)
        self.assertEqual(list(B.DOW), sorted(B.DOW))
        for s in ("AAPL", "WMT", "DOW", "WBA", "V"):
            self.assertIn(s, B.DOW)
        for later in ("NVDA", "AMZN", "CSX", "DOW.US"):
            self.assertNotIn(later, B.DOW)

    def test_bars_in_time_order_without_missing_prices(self):
        df = pd.DataFrame({"ts": [30, 10, 20, 40], "open": [3.0, 1.0, np.nan, 4.0], "close": [3.5, 1.5, 2.5, np.nan]})
        ts, o, c = B.bars_of(df)
        self.assertEqual((ts, o, c), ([10, 30], [1.0, 3.0], [1.5, 3.5]))
        self.assertIsInstance(ts[0], int)


if __name__ == "__main__":
    unittest.main()
