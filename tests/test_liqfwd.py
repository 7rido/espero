"""#22's recorder and paper ledger: complete days only, nothing fetched twice, the
same panel as the exploration, trades from the spike hour's close to 4 hours later."""
from __future__ import annotations

import importlib.util
import tempfile
import unittest
from pathlib import Path

import numpy as np
import pandas as pd

from espero import aggr
from espero import liqfwd as lf

ROOT = Path(__file__).resolve().parents[1]


def fake_fetch(calls):
    def fetch(start, end):
        calls.append(start)
        hours = pd.date_range(start, end, freq="h", inclusive="left")
        return pd.DataFrame([{"time": int(t.timestamp()), "market": "BINANCE_FUTURES:btcusdt", "open": 1, "high": 1,
                              "low": 1, "close": 1, "vbuy": 1, "vsell": 1, "cbuy": 1, "csell": 1, "lbuy": 0,
                              "lsell": 0} for t in hours])
    return fetch


class TestRecord(unittest.TestCase):
    def test_complete_days_once(self):
        with tempfile.TemporaryDirectory() as d:
            calls = []
            now = pd.Timestamp("2026-11-02 10:00", tz="UTC")
            saved = lf.record(Path(d), now, fake_fetch(calls))
            self.assertEqual(saved, ["2026-10-30", "2026-10-31", "2026-11-01"])      # not today, still forming
            self.assertEqual(lf.record(Path(d), now, fake_fetch(calls)), [])
            self.assertEqual(len(calls), 3)
            self.assertEqual(len(pd.read_csv(lf.day_path(Path(d), pd.Timestamp("2026-10-31")))), 24)

    def test_a_day_aggr_returns_empty_is_not_saved_and_the_step_says_so(self):
        """An empty answer saved as the day's file would mark the day done for ever; a gap must stay visible."""
        def fetch(start, end):
            if start == pd.Timestamp("2026-10-31", tz="UTC"):
                return pd.DataFrame(columns=aggr.COLUMNS)
            return fake_fetch([])(start, end)
        with tempfile.TemporaryDirectory() as d:
            now = pd.Timestamp("2026-11-02 10:00", tz="UTC")
            empty = []
            saved = lf.record(Path(d), now, fetch, empty=empty)
            self.assertEqual(saved, ["2026-10-30", "2026-11-01"])
            self.assertEqual(empty, ["2026-10-31"])
            self.assertFalse(lf.day_path(Path(d), pd.Timestamp("2026-10-31")).exists())
            calls = []
            self.assertEqual(lf.record(Path(d), now, fake_fetch(calls)), ["2026-10-31"])   # asked again, then saved


class TestLedger(unittest.TestCase):
    def test_spike_bought_at_close_sold_4_hours_later(self):
        idx = pd.date_range("2026-09-01", periods=24 * 70, freq="h", tz="UTC")
        close = 100 * np.exp(np.cumsum(np.random.default_rng(0).normal(0, 0.002, len(idx))))
        df = pd.DataFrame({"open": close, "close": close, "volume": 1e6, "long": 1e3, "short": 1e3}, index=idx)
        h = idx.get_loc(pd.Timestamp("2026-11-03 05:00", tz="UTC"))
        df.iloc[h, df.columns.get_loc("long")] = 9e4
        led = lf.ledger({"BTC": df})
        self.assertEqual(len(led), 1)
        e = led.iloc[0]
        self.assertEqual(e["spike_hour"], idx[h])
        self.assertAlmostEqual(e["ret"], close[h + 4] / close[h] - 1)

    def test_a_short_spike_is_a_paper_short_in_its_own_ledger(self):
        idx = pd.date_range("2026-09-01", periods=24 * 70, freq="h", tz="UTC")
        close = 100 * np.exp(np.cumsum(np.random.default_rng(1).normal(0, 0.002, len(idx))))
        df = pd.DataFrame({"open": close, "close": close, "volume": 1e6, "long": 1e3, "short": 1e3}, index=idx)
        h = idx.get_loc(pd.Timestamp("2026-11-05 09:00", tz="UTC"))
        df.iloc[h, df.columns.get_loc("short")] = 9e4
        self.assertEqual(len(lf.ledger({"BTC": df}, "long")), 0)
        e = lf.ledger({"BTC": df}, "short").iloc[0]
        self.assertAlmostEqual(e["ret"], -(close[h + 4] / close[h] - 1))      # a short gains when it falls

    def test_spikes_before_the_forward_window_are_not_trades(self):
        idx = pd.date_range("2026-09-01", periods=24 * 70, freq="h", tz="UTC")
        df = pd.DataFrame({"open": 1.0, "close": 1.0, "volume": 1e6, "long": 1e3, "short": 1e3}, index=idx)
        df.iloc[idx.get_loc(pd.Timestamp("2026-10-29 05:00", tz="UTC")), df.columns.get_loc("long")] = 9e4
        self.assertEqual(len(lf.ledger({"BTC": df})), 0)


class TestSameAsExplored(unittest.TestCase):
    def test_coins_and_panel_match_the_exploration(self):
        spec = importlib.util.spec_from_file_location("aggr_explore", ROOT / "research" / "aggr_explore.py")
        ax = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(ax)
        self.assertEqual(aggr.COINS, ax.COINS)
        if not (ax.DATA / "explore").exists():
            self.skipTest("explored bars not on this machine")
        raw = ax.load_explore()
        a, b = aggr.panel(raw), ax.panel(raw)
        self.assertEqual(sorted(a), sorted(b))
        for c in a:
            pd.testing.assert_frame_equal(a[c], b[c], check_freq=False)


if __name__ == "__main__":
    unittest.main(verbosity=2)
