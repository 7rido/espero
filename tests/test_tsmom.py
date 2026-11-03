"""TSMOM paper account: weights, cash, and no money appearing from nowhere."""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import numpy as np
import pandas as pd

from espero import tsmom as T


class TestLookback(unittest.TestCase):
    def test_lookback_is_52_weeks_on_the_calendar_not_252_rows(self):
        idx = pd.date_range("2024-01-01", periods=500, freq="D")
        s = pd.Series(np.linspace(100, 200, 500), index=idx)
        sig = T.signals({"X": s})["X"]
        ref = s[s.index <= s.index[-1] - pd.Timedelta(days=T.LOOKBACK_DAYS)].iloc[-1]
        self.assertAlmostEqual(sig, s.iloc[-1] / ref - 1, places=10)
        # the old row-based version would have used the price 252 rows back
        old = s.iloc[-1] / s.iloc[-253] - 1
        self.assertNotAlmostEqual(sig, old, places=3)


class TestWeights(unittest.TestCase):
    def test_four_positive_assets_get_one_sixth_each(self):
        sig = {"SPY": 0.1, "TLT": -0.1, "GLD": -0.05, "USO": 1.2, "BTC": 0.16, "ETH": 0.15}
        w, cash = T.target_weights(sig)
        for a in ("SPY", "USO", "BTC", "ETH"):
            self.assertAlmostEqual(w[a], 1 / 6)
        for a in ("TLT", "GLD"):
            self.assertEqual(w[a], 0.0)
        self.assertAlmostEqual(cash, 1 - 4 / 6)

    def test_all_cash_when_nothing_is_positive(self):
        sig = {a: -0.01 for a in ("SPY", "TLT", "GLD", "USO", "BTC", "ETH")}
        w, cash = T.target_weights(sig)
        self.assertEqual(sum(w.values()), 0)
        self.assertAlmostEqual(cash, 1.0)

    def test_single_asset_is_capped_at_one_sixth(self):
        sig = {"SPY": 0.1, "TLT": -0.1, "GLD": -0.1, "USO": -0.1, "BTC": -0.1, "ETH": -0.1}
        w, cash = T.target_weights(sig)
        self.assertAlmostEqual(w["SPY"], 1 / 6)
        self.assertAlmostEqual(cash, 5 / 6)


class TestAccount(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / "acct.db"

    def tearDown(self):
        self.tmp.cleanup()

    def test_rebalance_conserves_cash_minus_costs(self):
        acc = T.Account(self.path)
        acc.cash = 100.0
        prices = pd.Series({"SPY": 100.0, "BTC": 100.0})
        weights = {"SPY": 1 / 6, "BTC": 1 / 6}
        traded = acc.rebalance(prices, weights)
        equity = acc.equity(prices)
        self.assertAlmostEqual(traded, 100 / 3, places=6)
        self.assertAlmostEqual(equity, 100 - (100 / 3) * T.COST, places=6)

    def test_state_survives_restart(self):
        acc = T.Account(self.path)
        acc.cash = 50.0
        acc.rebalance(pd.Series({"SPY": 10.0}), {"SPY": 1 / 6})
        units = dict(acc.units)
        acc.save(1_700_000_000, acc.equity(pd.Series({"SPY": 10.0})), {"SPY": 1 / 6}, "test")

        reopened = T.Account(self.path)
        self.assertAlmostEqual(reopened.cash, acc.cash)
        self.assertAlmostEqual(reopened.units["SPY"], units["SPY"])

    def test_decision_snapshot_survives_restart(self):
        acc = T.Account(self.path)
        acc.cash = 100.0
        acc.rebalance(pd.Series({"SPY": 10.0}), {"SPY": 1 / 6})
        acc.save(1_700_000_000, acc.equity(pd.Series({"SPY": 10.0})), {"SPY": 1 / 6},
                 "init", positions={"SPY": 10.0}, signals={"SPY": 0.139, "TLT": -0.1})
        reopened = T.Account(self.path)
        import json
        row = reopened.last()
        self.assertEqual(json.loads(row["signals"])["SPY"], 0.139)

    def test_deposit_and_mark_can_share_a_day(self):
        acc = T.Account(self.path)
        acc.cash = 100.0
        acc.rebalance(pd.Series({"SPY": 10.0}), {"SPY": 1 / 6})
        acc.save(1_700_000_000, 100.0, {"SPY": 1 / 6}, "init", deposit=100.0)
        acc.cash += 500.0
        acc.save(1_700_000_000, 600.0, {"SPY": 1 / 6}, "deposit", deposit=500.0)
        acc.save(1_700_000_000, 599.0, {"SPY": 1 / 6}, "mark")
        rows = acc.history()
        self.assertEqual(len(rows), 3)
        self.assertAlmostEqual(sum(float(r["deposit"] or 0) for r in rows), 600.0)

    def test_mark_replaces_itself_not_duplicates(self):
        acc = T.Account(self.path)
        acc.cash = 100.0
        acc.save(1_700_000_000, 100.0, {}, "mark")
        acc.save(1_700_000_000, 101.0, {}, "mark")
        self.assertEqual(len(acc.history()), 1)

    def test_no_leverage(self):
        acc = T.Account(self.path)
        acc.cash = 100.0
        acc.rebalance(pd.Series({"SPY": 10.0}), {"SPY": 1 / 6})
        self.assertGreaterEqual(acc.cash, -1e-9)

    def test_fully_invested_rebalance_does_not_borrow_the_fees(self):
        # one-pass costing left cash at exactly -(traded * COST)
        acc = T.Account(self.path)
        acc.cash = 100.0
        px = pd.Series({"SPY": 10.0, "GLD": 20.0})
        acc.rebalance(px, {"SPY": 0.5, "GLD": 0.5})
        self.assertGreaterEqual(acc.cash, -1e-9)
        self.assertAlmostEqual(acc.equity(px), 100.0 * (1 - T.COST), places=6)


class TestCalendar(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / "acct.db"

    def tearDown(self):
        self.tmp.cleanup()

    def test_rebalances_once_per_month_not_once_per_day_of_the_window(self):
        from datetime import datetime, timezone
        acc = T.Account(self.path)
        acc.cash = 100.0
        day1 = datetime(2026, 12, 1, 12, tzinfo=timezone.utc)   # Tuesday
        day2 = datetime(2026, 12, 2, 12, tzinfo=timezone.utc)
        self.assertTrue(T.rebalance_due(acc, day1))
        acc.save(int(day1.timestamp()), 100.0, {}, "rebalance")
        self.assertFalse(T.rebalance_due(acc, day2))
        self.assertTrue(T.rebalance_due(acc, datetime(2027, 1, 1, 12, tzinfo=timezone.utc)))

    def test_weekend_is_never_a_rebalance_day(self):
        from datetime import datetime, timezone
        self.assertFalse(T.first_trading_day(datetime(2026, 11, 1, tzinfo=timezone.utc)))  # Sunday


if __name__ == "__main__":
    unittest.main(verbosity=2)


def total_return_fetch(end, spy_dividend=0.0, uso_split=1.0):
    """yahoo_daily(adjusted=True) for the six assets, rising, ending on `end`. SPY can pay
    `spy_dividend` dollars going ex on `end`; USO's whole history can be restated by a split."""
    def fetch(symbol, span):
        crypto = symbol.endswith("-USD")
        dates = (pd.date_range if crypto else pd.bdate_range)(end=end, periods=400 if crypto else 300, tz="UTC")
        path = 100 * np.exp(0.001 * np.arange(len(dates)))
        close, adj = path.copy(), path.copy()
        if symbol == "SPY" and spy_dividend:
            close[-1] -= spy_dividend                         # ex-date: the price drops by the payout
            adj[:-1] *= 1 - spy_dividend / path[-2]           # Yahoo scales the history down instead
            adj[-1] = close[-1]
        if symbol == "USO":
            close, adj = close * uso_split, adj * uso_split   # a restatement moves every past price
        return pd.DataFrame({"dt": dates, "close": close, "adj_close": adj})
    return fetch


class TestTotalReturn(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.state = str(Path(self.tmp.name) / "tsmom.db")
        self.day1 = T.run(self.state, 100.0, fetch=total_return_fetch("2026-10-27"))
        self.wed = pd.Timestamp("2026-10-28", tz="UTC").to_pydatetime()   # not a rebalance day

    def tearDown(self):
        self.tmp.cleanup()

    def grown(self, asset, ratio):
        return self.day1["positions"][asset] * ratio

    def test_a_dividend_is_credited_not_lost(self):
        res = T.run(self.state, 100.0, now=self.wed, fetch=total_return_fetch("2026-10-28", spy_dividend=2.0))
        p27, p28 = 100 * np.exp(0.001 * 298), 100 * np.exp(0.001 * 299)
        self.assertEqual(res["note"], "mark")
        self.assertAlmostEqual(res["positions"]["SPY"], self.grown("SPY", (p28 - 2) / (p27 - 2)), places=9)
        self.assertGreater(res["positions"]["SPY"], self.grown("SPY", (p28 - 2) / p27))   # what raw marks gave

    def test_a_split_restated_into_the_history_does_not_multiply_the_position(self):
        res = T.run(self.state, 100.0, now=self.wed, fetch=total_return_fetch("2026-10-28", uso_split=8.0))
        self.assertAlmostEqual(res["positions"]["USO"], self.grown("USO", np.exp(0.001)), places=9)

    def test_a_forming_bar_does_not_move_the_share_counts(self):
        """Yahoo serves the current day's bar while it is forming. The old roll took the last run's mark price as
        the bar's close, so every run moved the counts by (partial / final) with no trade."""
        final = {sym: 100 * np.exp(0.001 * np.arange(400)) for sym in T.UNIVERSE}
        days = pd.date_range(end="2026-11-10", periods=400, tz="UTC")
        state = {"today": None, "partial": 1.0}

        def fetch(symbol, span):
            hist = pd.Series(final[symbol], index=days)
            done = hist[hist.index < state["today"]]
            forming = hist[hist.index == state["today"]] * state["partial"]
            s = pd.concat([done, forming])
            return pd.DataFrame({"dt": s.index, "close": s.to_numpy(), "adj_close": s.to_numpy()})

        db = str(Path(self.tmp.name) / "forming.db")
        counts = []
        for k, partial in enumerate((0.98, 1.03, 0.97, 1.02, 0.99)):
            state["today"] = pd.Timestamp("2026-11-03", tz="UTC") + pd.Timedelta(days=k)
            state["partial"] = partial
            res = T.run(db, 100.0, now=state["today"].to_pydatetime(), fetch=fetch)
            counts.append(dict(res["account"].units))
        self.assertEqual(counts[0]["BTC"] > 0, True)
        for later in counts[1:]:
            for a, u in counts[0].items():
                self.assertAlmostEqual(later[a], u, places=9, msg=a)

    def test_a_row_without_an_anchor_rolls_as_before(self):
        """The first run after the upgrade: the last row has no stored closes, so the old roll applies once."""
        acc = T.Account(self.state)
        acc.db.execute("UPDATE account SET closes=NULL")
        acc.db.commit()
        res = T.run(self.state, 100.0, now=self.wed, fetch=total_return_fetch("2026-10-28", spy_dividend=2.0))
        p27, p28 = 100 * np.exp(0.001 * 298), 100 * np.exp(0.001 * 299)
        self.assertAlmostEqual(res["positions"]["SPY"], self.grown("SPY", (p28 - 2) / (p27 - 2)), places=9)

    def test_a_rerun_on_the_same_data_changes_nothing(self):
        again = T.run(self.state, 100.0, now=self.wed, fetch=total_return_fetch("2026-10-27"))
        for a, v in self.day1["positions"].items():
            self.assertAlmostEqual(again["positions"][a], v, places=9)
