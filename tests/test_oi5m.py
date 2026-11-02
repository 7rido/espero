"""#65's rule, trades and verdict, on made-up data only."""

import math
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import numpy as np
import pandas as pd

from espero import hlpbook as hb
from espero import oi5m as m

COIN = "SOL"
T0 = m.WINDOW_START + 2 * 86400  # the slot under test, inside the window
HIST = 1100  # slots of history before it, more than the 1,008 required


def slot(at, mark=100.0, oi=1000.0, volume=20e6, ts=None, coin=COIN):
    return m.Slot(at, at if ts is None else ts, {coin: mark}, {coin: oi}, {coin: volume})


def history(n=HIST, end=T0, coin=COIN, seed=0):
    """Quiet slots before `end`: marks wandering by at most 0.3% a slot, so a 5% fall is far in the tail."""
    rng = np.random.default_rng(seed)
    marks = 100.0 * np.cumprod(1 + rng.uniform(-0.003, 0.003, n))
    return [slot(end - (n - k) * m.SLOT_S, float(marks[k]), 1000.0, coin=coin) for k in range(n)]


def market(coin=COIN, start=T0 - 3600, end=T0 + 6 * 3600, px=100.0, later=103.0, turn=None):
    """One candle a minute: px before `turn`, `later` from it; each opens one unit below its close."""
    turn = T0 + m.KNOWN_AFTER_S + 600 if turn is None else turn
    starts = np.arange(start, end, 60)
    closes = np.where(starts < turn, px, later)
    p = hb.Prices()
    p.add(coin, pd.DataFrame({"ts": starts, "open": closes - 1, "close": closes}))
    return p


def run(cur_mark, cur_oi, prev_mark=100.0, prev_oi=1000.0, volume=20e6, hist=None):
    hist = history() if hist is None else hist
    prev = m.Slot(T0 - m.SLOT_S, T0 - m.SLOT_S, {COIN: prev_mark}, {COIN: prev_oi}, {COIN: volume})
    hist = hist[:-1] + [prev]
    return m.walk(hist + [slot(T0, cur_mark, cur_oi, volume)])


class TheRegisteredNumbers(unittest.TestCase):
    def test_numbers(self):
        self.assertEqual(
            (
                m.SLOT_S,
                m.KNOWN_AFTER_S,
                m.TAIL_PCT,
                m.FLOOR,
                m.HISTORY_S,
                m.MIN_HISTORY,
                m.MIN_VOLUME,
                m.LIQUID,
                m.HOLD_S,
                m.MIN_TRADES,
                m.PASS_T,
                m.SIDE_T,
                m.LAGS,
                m.COST_BPS,
            ),
            (300, 120, 2.0, 0.01, 7 * 86400, 1008, 5e6, 50e6, 3600, 100, 3.0, 2.0, 12, 18.0),
        )
        self.assertEqual(m.WINDOW_START, hb._utc(2026, 11, 3))
        self.assertEqual(m.WINDOW_END, hb._utc(2027, 4, 1))
        self.assertEqual(m.INFO_HOLDS, {"15m": 900, "4h": 14400})


class TheSignal(unittest.TestCase):
    def test_a_tail_fall_with_oi_down_is_a_long_and_with_oi_up_a_short(self):
        got = run(95.0, 985.0)["signals"]
        self.assertEqual(len(got), 1)
        s = got[0]
        self.assertEqual((s.coin, s.ts, s.side, s.slot, s.kind), (COIN, T0 + 120, 1, T0, "fall"))
        self.assertAlmostEqual(s.r, -0.05)
        self.assertAlmostEqual(s.d, -0.015)
        got = run(95.0, 1015.0)["signals"]
        self.assertEqual([g.side for g in got], [-1])

    def test_the_floor_edges(self):
        self.assertEqual([s.side for s in run(95.0, 990.0)["signals"]], [1])  # exactly -1%: in, long
        self.assertEqual(len(run(95.0, 990.01)["signals"]), 0)  # inside the floor: out
        self.assertEqual(len(run(95.0, 1010.0)["signals"]), 1)  # exactly +1%: in
        self.assertEqual(len(run(95.0, 1009.99)["signals"]), 0)

    def test_the_fall_must_be_in_the_tail(self):
        self.assertEqual(len(run(99.9, 985.0)["signals"]), 0)  # an ordinary move
        found = run(99.9, 985.0)
        self.assertEqual(found["counts"]["signals"], 0)

    def test_history_is_required_and_excludes_the_slot(self):
        # n slots give n - 1 returns: the first has no previous slot
        found = run(95.0, 985.0, hist=history(n=1008))
        self.assertEqual((len(found["signals"]), found["counts"]["short_history"]), (0, 1))
        self.assertEqual(len(run(95.0, 985.0, hist=history(n=1009))["signals"]), 1)

    def test_old_history_falls_out_of_the_window(self):
        old = history(n=1100, end=T0 - m.HISTORY_S - 10 * m.SLOT_S)  # all older than 7 days
        found = m.walk(old + [slot(T0 - m.SLOT_S), slot(T0, 95.0, 985.0)])
        self.assertEqual(len(found["signals"]), 0)

    def test_thin_coins_go_to_their_own_list(self):
        found = run(95.0, 985.0, volume=4_999_999.0)
        self.assertEqual((len(found["signals"]), len(found["thin"])), (0, 1))
        self.assertEqual(len(run(95.0, 985.0, volume=5e6)["signals"]), 1)

    def test_the_mirror_reverses_the_sides(self):
        found = run(105.0, 985.0)  # a rise with OI down: short
        self.assertEqual((len(found["signals"]), [s.side for s in found["mirror"]]), (0, [-1]))
        self.assertEqual([s.side for s in run(105.0, 1015.0)["mirror"]], [1])
        self.assertEqual(run(105.0, 985.0)["mirror"][0].kind, "rise")

    def test_no_previous_slot_means_no_signal(self):
        hist = history()
        found = m.walk(hist[:-1] + [slot(T0, 95.0, 985.0)])  # T0 - 300 missing
        self.assertEqual((len(found["signals"]), found["counts"]["no_previous_slot"]), (0, 2))  # and the first slot

    def test_outside_the_window_and_the_known_time(self):
        before = m.WINDOW_START - 50 * m.SLOT_S
        hist = history(end=before)
        found = m.walk(hist[:-1] + [slot(before - m.SLOT_S), slot(before, 95.0, 985.0)])
        self.assertEqual(len(found["signals"]), 0)
        edge = m.WINDOW_START - 100  # ts + 120 is inside the window
        hist = history(end=edge)
        found = m.walk(hist[:-1] + [slot(edge - m.SLOT_S), slot(edge, 95.0, 985.0, ts=edge)])
        self.assertEqual(len(found["signals"]), 1)
        self.assertEqual(found["signals"][0].ts, edge + 120)

    def test_the_hour_before(self):
        hist = history()
        hist[-12] = slot(hist[-12].slot, hist[-12].mark[COIN], 900.0)
        s = run(95.0, 985.0, hist=hist)["signals"][0]
        self.assertAlmostEqual(s.d1h, 985.0 / 900.0 - 1)


class TheTrades(unittest.TestCase):
    def test_hold_is_one_hour_and_side_kept(self):
        s = m.Signal(COIN, T0 + 120, -1, T0, -0.05, 0.02, 0.0, 20e6, "fall")
        rows = m.trades([s], market(), final=True)
        r = rows[0]
        self.assertEqual(
            (r["status"], r["side"], r["entry_ts"], r["exit_ts"]), ("closed", -1, T0 + 180, T0 + 180 + 3600)
        )
        self.assertEqual((r["entry_px"], r["exit_px"]), (99.0, 102.0))
        rows = m.trades([s], market(), hold_s=900, final=True)
        self.assertEqual(rows[0]["exit_ts"], T0 + 180 + 900)

    def test_one_at_a_time_and_dropped_entry(self):
        a = m.Signal(COIN, T0 + 120, 1, T0, -0.05, -0.02, 0.0, 20e6, "fall")
        b = m.Signal(COIN, T0 + 420, 1, T0 + 300, -0.05, -0.02, 0.0, 20e6, "fall")
        rows = m.trades([b, a], market(), final=True)
        self.assertEqual([r["status"] for r in rows], ["closed", "ignored"])
        late = m.Signal(
            COIN, T0 + 7 * 3600 + 120, 1, T0 + 7 * 3600, -0.05, -0.02, 0.0, 20e6, "fall"
        )  # past the candles
        self.assertEqual(m.trades([late], market(), final=True)[0]["status"], "dropped_entry")


class TheT(unittest.TestCase):
    def test_clusters_by_slot_and_lags(self):
        x = pd.Series([10.0, 10.0, -10.0, -10.0])
        self.assertEqual(m.cluster_t(x, pd.Series([0, 0, 300, 300]))["slots"], 2)
        same = m.cluster_t(pd.Series([5.0, 5.0, 5.0]), pd.Series([0, 300, 600]))
        self.assertAlmostEqual(same["mean"], 5.0)
        self.assertTrue(math.isnan(same["t"]))  # no residual variance
        self.assertTrue(math.isnan(m.cluster_t(pd.Series([1.0]), pd.Series([0]))["t"]))

    def test_one_slot_with_everything_in_it_has_no_power(self):
        rng = np.random.default_rng(1)
        x = pd.Series(50 + 10 * rng.standard_normal(40))
        one = m.cluster_t(x, pd.Series([0] * 40))
        spread = m.cluster_t(x, pd.Series([300 * k for k in range(40)]))
        self.assertTrue(math.isnan(one["t"]))  # one cluster: the residual sum is 0
        self.assertGreater(spread["t"], 3)


def frame(nets, sides, coins=None, days=None, volumes=None, slots=None):
    n = len(nets)
    coins = coins or [f"C{i % 7}" for i in range(n)]
    days = days or [m.WINDOW_START + (i * 3 % 140) * 86400 for i in range(n)]
    return pd.DataFrame(
        {
            "coin": coins,
            "entry_ts": days,
            "side": sides,
            "slot": slots or [d + 300 * (i % 12) for i, d in enumerate(days)],
            "volume": volumes or [60e6 if i % 2 else 10e6 for i in range(n)],
            "net_bps": nets,
        }
    )


class TheVerdict(unittest.TestCase):
    def good(self, n=240, seed=3, mean=40.0):
        rng = np.random.default_rng(seed)
        return frame(list(mean + 10.0 * rng.standard_normal(n)), [1 if i % 2 else -1 for i in range(n)])

    def test_fewer_than_100_a_side_is_inconclusive(self):
        f = self.good(n=240)
        self.assertEqual(m.evaluate(f)["verdict"], "PASS")
        short = f[(f["side"] == 1) | (f.index < 99 * 2)]  # 99 continuation trades
        self.assertEqual(m.evaluate(short)["verdict"], "INCONCLUSIVE")

    def test_checks(self):
        out = m.evaluate(self.good())
        self.assertEqual(set(out["checks"]), {"pays", "reversal", "continuation", "both_halves", "coins", "liquid"})

    def test_one_side_failing_is_named(self):
        f = self.good()
        f.loc[f["side"] == -1, "net_bps"] = -5.0 + 0.0 * f.loc[f["side"] == -1, "net_bps"]
        f.loc[f["side"] == 1, "net_bps"] += 100.0
        out = m.evaluate(f)
        self.assertTrue(out["checks"]["reversal"])
        self.assertFalse(out["checks"]["continuation"])
        self.assertEqual(out["verdict"], "FAIL (one side only: reversal pays)")

    def test_liquid_and_coins_and_halves(self):
        f = self.good()
        f.loc[f["volume"] >= 50e6, "net_bps"] = -1.0
        self.assertFalse(m.evaluate(f)["checks"]["liquid"])
        f = self.good()
        f["coin"] = ["BIG"] * 20 + [f"C{i}" for i in range(220)]  # only BIG has 10 trades
        f.loc[f["coin"] == "BIG", "net_bps"] = -1.0
        self.assertFalse(m.evaluate(f)["checks"]["coins"])
        f = self.good()
        f["entry_ts"] = [m.WINDOW_START + 86400 * (i % 30) for i in range(240)]
        self.assertFalse(m.evaluate(f)["checks"]["both_halves"])

    def test_t_below_3_fails(self):
        rng = np.random.default_rng(4)
        f = frame(list(10.0 + 150.0 * rng.standard_normal(300)), [1 if i % 2 else -1 for i in range(300)])
        out = m.evaluate(f)
        self.assertLess(out["t"], 3)
        self.assertEqual(out["verdict"], "FAIL")


class TheNet(unittest.TestCase):
    def test_closed_trades_sign_the_gross_and_the_funding(self):
        rows = [
            {
                "status": "closed",
                "coin": COIN,
                "entry_ts": 1,
                "exit_ts": 2,
                "entry_px": 100.0,
                "exit_px": 98.0,
                "side": -1,
                "slot": 0,
                "volume": 1.0,
                "d1h": 0.0,
            }
        ]
        with mock.patch.object(hb, "funding_bps", return_value=5.0):
            closed = m.closed_trades(rows)
        self.assertAlmostEqual(float(closed["gross_bps"].iloc[0]), 200.0)
        self.assertAlmostEqual(float(closed["net_bps"].iloc[0]), 200 - 18 + 5)


class TheLedger(unittest.TestCase):
    def test_refuses_before_the_window_closes(self):
        with self.assertRaises(RuntimeError):
            m.ledger(Path("/nonexistent"), now=m.WINDOW_END - 1)

    def test_runs_on_made_up_files_after(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "candles").mkdir()
            slots = history() + [slot(T0, 95.0, 985.0)]
            for s in slots:
                day = pd.Timestamp(s.slot, unit="s").strftime("%Y-%m-%d")
                (root / "ctx" / day).mkdir(parents=True, exist_ok=True)
                hhmm = pd.Timestamp(s.slot, unit="s").strftime("%H%M")
                pd.DataFrame(
                    [
                        {
                            "ts": s.ts,
                            "coin": COIN,
                            "mark": s.mark[COIN],
                            "open_interest": s.oi[COIN],
                            "day_volume": s.volume[COIN],
                        }
                    ]
                ).to_csv(root / "ctx" / day / f"{hhmm}.csv.gz", index=False)
            p = market()
            starts, opens, closes = p._arrays(COIN)
            day = pd.Timestamp(T0, unit="s").strftime("%Y-%m-%d")
            pd.DataFrame({"ts": starts, "coin": COIN, "open": opens, "close": closes}).to_csv(
                root / "candles" / f"{day}.csv.gz", index=False
            )
            with (
                mock.patch.object(m.lv, "fetch_recent", return_value=0),
                mock.patch.object(hb, "funding_bps", return_value=1.0),
            ):
                out = m.ledger(root, now=m.WINDOW_END + 10)
        self.assertEqual(out["verdict"]["verdict"], "INCONCLUSIVE")
        self.assertEqual(out["statuses"], {"closed": 1})
        self.assertEqual(out["counts"]["signals"], 1)
        self.assertEqual(out["rows"][0]["side"], 1)
        self.assertEqual(out["information"]["hold_15m"]["n"], 1)
        self.assertAlmostEqual(out["information"]["by_side"][1]["mean"], 1e4 * (102 / 99 - 1) - 18 - 1)

    def test_status_opens_nothing(self):
        with tempfile.TemporaryDirectory() as tmp:
            lines = m.status(Path(tmp), now=m.WINDOW_START - 1)
        self.assertIn("not open yet", lines[0])
        self.assertIn("context slots on disk: 0", lines[1])


if __name__ == "__main__":
    unittest.main()
