"""#60's rule, trades and verdict, on made-up data only."""
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import numpy as np
import pandas as pd

from espero import hlpbook as hb
from espero import ladder as la

HOUR = 3600
# the slot under test: its fall ends one hour after its band is known, inside the window
TS = hb.WINDOW_START + 10 * HOUR
KNOWN = TS + la.KNOWN_AFTER_S
DONE = KNOWN + la.FALL_S
COIN = "BTC"


def rows(*positions):
    """(szi, value, liq) tuples."""
    return pd.DataFrame(positions, columns=["szi", "value", "liq"])


def slot(ts, value, coin=COIN, px=100.0):
    """A slot whose band holds exactly `value` dollars at price px."""
    return la.Slot(ts, {coin: rows((1.0, value, px * 0.995))})


def market(fall=0.02, before=100.0, coin=COIN, start=TS - 400 * HOUR, end=TS + 12 * HOUR):
    """One candle a minute at `before`, then at before * (1 - fall) for candles ending after KNOWN.
    Each opens one unit below its close, so open and close can't be confused."""
    starts = np.arange(start, end, 60)
    closes = np.where(starts + 60 <= KNOWN, before, before * (1 - fall))
    p = hb.Prices()
    p.add(coin, pd.DataFrame({"ts": starts, "open": closes - 1, "close": closes}))
    return p


def past(values, end=TS):
    """Hourly slots right before `end`, oldest first, holding these band values."""
    n = len(values)
    return [slot(end - (n - k) * HOUR, v) for k, v in enumerate(values)]


RAMP = [float(v) for v in np.random.default_rng(1).permutation(np.arange(1, 101))]    # 90th percentile 90.1


class TheRegisteredNumbers(unittest.TestCase):
    def test_numbers(self):
        self.assertEqual((la.KNOWN_AFTER_S, la.FALL_S, la.BAND, la.HISTORY_S, la.MIN_HISTORY, la.DENSE_PCT,
                          la.THIN_PCT, la.MIN_THIN), (1800, 3600, 0.01, 168 * 3600, 84, 90.0, 50.0, 30))
        self.assertEqual((hb.ENTRY_DELAY_S, hb.HOLD_S, hb.FILL_TOLERANCE_S, hb.COST_BPS, hb.MIN_TRADES, hb.PASS_T),
                         (60, 14400, 300, 18.0, 100, 3.0))
        self.assertEqual(len(hb.COINS), 14)


class TheBand(unittest.TestCase):
    def test_edges(self):
        self.assertEqual(la.band_usd(rows((1.0, 5.0, 99.0)), 100.0), 5.0)       # exactly 1% below: in
        self.assertEqual(la.band_usd(rows((1.0, 5.0, 98.99)), 100.0), 0.0)      # past the band: out
        self.assertEqual(la.band_usd(rows((1.0, 5.0, 100.0)), 100.0), 0.0)      # at the price: out
        self.assertEqual(la.band_usd(rows((1.0, 5.0, 99.99)), 100.0), 5.0)

    def test_only_longs_with_a_liquidation_price(self):
        self.assertEqual(la.band_usd(rows((-1.0, 5.0, 99.5)), 100.0), 0.0)
        self.assertEqual(la.band_usd(rows((1.0, 5.0, float("nan"))), 100.0), 0.0)
        self.assertEqual(la.band_usd(rows((1.0, 5.0, 99.5), (2.0, 7.0, 99.1), (-1.0, 9.0, 99.2)), 100.0), 12.0)
        self.assertEqual(la.band_usd(None, 100.0), 0.0)


class TheSignal(unittest.TestCase):
    def run_it(self, value, prices=None, history=RAMP):
        return la.walk(past(history) + [slot(TS, value)], prices or market())

    def test_must_be_above_the_90th_percentile(self):
        self.assertEqual(len(self.run_it(90.0)["signals"]), 0)
        got = self.run_it(91.0)["signals"]
        self.assertEqual(len(got), 1)
        self.assertEqual((got[0].coin, got[0].ts, got[0].jump), (COIN, DONE, 91.0))

    def test_equal_to_the_90th_percentile_is_not_above_it(self):
        out = self.run_it(10.0, history=[10.0] * 100)
        self.assertEqual(out["signals"], [])
        self.assertEqual(len(self.run_it(10.5, history=[10.0] * 100)["signals"]), 1)

    def test_an_empty_band_is_never_dense(self):
        out = self.run_it(0.0, history=[0.0] * 100)
        self.assertEqual(out["signals"], [])
        self.assertEqual(len(out["thin"]), 1)

    def test_the_fall_must_reach_one_percent(self):
        self.assertEqual(len(self.run_it(200.0, market(fall=0.0099))["signals"]), 0)
        self.assertEqual(len(self.run_it(200.0, market(fall=0.0101))["signals"]), 1)

    def test_a_fall_of_exactly_the_band_counts(self):
        # powers of two, so 1% below the price is exact in floating point
        p = market(fall=0.01, before=256.0)
        s = [la.Slot(t.ts, {COIN: rows((1.0, t.rows[COIN]["value"].iloc[0], 255.0))}) for t in past(RAMP)]
        now = la.Slot(TS, {COIN: rows((1.0, 200.0, 255.0))})
        self.assertEqual(len(la.walk(s + [now], p)["signals"]), 1)

    def test_a_rise_is_not_a_fall(self):
        self.assertEqual(len(self.run_it(200.0, market(fall=-0.02))["signals"]), 0)

    def test_needs_84_trailing_slots_exactly(self):
        self.assertEqual(len(self.run_it(200.0, history=RAMP[:83])["signals"]), 0)
        self.assertEqual(len(self.run_it(200.0, history=RAMP[:84])["signals"]), 1)

    def test_trailing_slots_older_than_168_hours_drop_out(self):
        # 100 huge values, then a gap: all older than 168 hours, so too little history remains
        old = past([1e9] * 100, end=TS - 169 * HOUR)
        recent = past(RAMP[:84])
        self.assertEqual(len(la.walk(old + recent + [slot(TS, 200.0)], market())["signals"]), 1)
        self.assertEqual(len(la.walk(old + [slot(TS, 200.0)], market())["signals"]), 0)

    def test_a_trailing_slot_exactly_168_hours_old_stays(self):
        s = past(RAMP[:83]) + [slot(TS - 168 * HOUR, 1.0)]
        self.assertEqual(len(la.walk(s + [slot(TS, 200.0)], market())["signals"]), 1)

    def test_a_slot_is_not_in_its_own_history(self):
        # the 90th percentile of 1..84 is 75.7, so 75.8 is dense. Counting itself would lift the bar to 75.92
        out = self.run_it(75.8, history=[float(v) for v in range(1, 85)])
        self.assertEqual(len(out["signals"]), 1)

    def test_only_inside_the_window(self):
        before = hb.WINDOW_START - la.KNOWN_AFTER_S - la.FALL_S
        for ts, want in ((before - 1, 0), (before, 1), (hb.WINDOW_END - la.KNOWN_AFTER_S - la.FALL_S - 1, 1),
                         (hb.WINDOW_END - la.KNOWN_AFTER_S - la.FALL_S, 0)):
            known = ts + la.KNOWN_AFTER_S
            starts = np.arange(ts - 110 * HOUR, known + 2 * la.FALL_S, 60)
            closes = np.where(starts + 60 <= known, 100.0, 98.0)
            p = hb.Prices()
            p.add(COIN, pd.DataFrame({"ts": starts, "open": closes, "close": closes}))
            s = past(RAMP, end=ts) + [slot(ts, 200.0)]
            self.assertEqual(len(la.walk(s, p)["signals"]), want, ts)


class ItCannotLookAhead(unittest.TestCase):
    def test_the_band_is_priced_at_ts_plus_30_minutes(self):
        """The price moves between ts and A. A band read at ts's price would be somewhere else."""
        starts = np.arange(TS - 400 * HOUR, TS + 12 * HOUR, 60)
        closes = np.where(starts + 60 <= TS, 200.0, np.where(starts + 60 <= KNOWN, 100.0, 98.0))
        p = hb.Prices()
        p.add(COIN, pd.DataFrame({"ts": starts, "open": closes, "close": closes}))
        # the band sits just under 100, which is 50% under the price at ts
        hist = [la.Slot(TS - (100 - k) * HOUR, {COIN: rows((1.0, RAMP[k], 199.5))}) for k in range(100)]
        self.assertEqual(len(la.walk(hist + [slot(TS, 200.0)], p)["signals"]), 1)

    def test_the_fall_starts_only_once_the_band_is_known(self):
        """A fall that ended by A has already happened, so it can't be the signal."""
        starts = np.arange(TS - 400 * HOUR, TS + 12 * HOUR, 60)
        closes = np.where(starts + 60 <= KNOWN - 600, 102.0, 100.0)
        p = hb.Prices()
        p.add(COIN, pd.DataFrame({"ts": starts, "open": closes, "close": closes}))
        self.assertEqual(la.walk(past(RAMP) + [slot(TS, 200.0)], p)["signals"], [])

    def test_the_fall_is_measured_at_the_hour_not_later(self):
        starts = np.arange(TS - 400 * HOUR, TS + 12 * HOUR, 60)
        closes = np.where(starts + 60 <= DONE, 100.0, 90.0)
        p = hb.Prices()
        p.add(COIN, pd.DataFrame({"ts": starts, "open": closes, "close": closes}))
        self.assertEqual(la.walk(past(RAMP) + [slot(TS, 200.0)], p)["signals"], [])

    def test_the_ledger_refuses_before_the_window_closes(self):
        with tempfile.TemporaryDirectory() as d:
            with mock.patch.object(la, "read_slot") as read:
                with self.assertRaises(RuntimeError):
                    la.ledger(Path(d), fetch=lambda b: [], now=hb.WINDOW_END - 1)
                read.assert_not_called()


class TheThinGroup(unittest.TestCase):
    def test_at_or_below_the_median(self):
        def thin(v):
            return len(la.walk(past(RAMP) + [slot(TS, v)], market())["thin"])
        self.assertEqual(thin(50.5), 1)     # the median of 1..100
        self.assertEqual(thin(50.6), 0)
        self.assertEqual(thin(0.0), 1)

    def test_needs_the_fall_and_the_history(self):
        self.assertEqual(la.walk(past(RAMP) + [slot(TS, 1.0)], market(fall=0.0))["thin"], [])
        self.assertEqual(la.walk(past(RAMP[:83]) + [slot(TS, 1.0)], market())["thin"], [])

    def test_a_slot_between_is_neither(self):
        out = la.walk(past(RAMP) + [slot(TS, 70.0)], market())
        self.assertEqual((out["signals"], out["thin"]), ([], []))


class TheTrade(unittest.TestCase):
    def test_entry_and_exit_times(self):
        found = la.walk(past(RAMP) + [slot(TS, 200.0)], market())
        t = hb.trades(found["signals"], market(), final=True)[0]
        self.assertEqual(t["status"], "closed")
        self.assertEqual(t["entry_ts"], DONE + 60)
        self.assertEqual(t["exit_ts"], DONE + 60 + 4 * HOUR)
        self.assertEqual(t["entry_px"], 97.0)   # the open, one unit below the close of 98

    def test_net_takes_costs_and_funding(self):
        rows_ = [{"coin": COIN, "status": "closed", "entry_ts": DONE, "exit_ts": DONE + 3600, "entry_px": 100.0,
                  "exit_px": 101.0, "signal_ts": DONE}, {"coin": COIN, "status": "ignored"}]
        got = la.closed_trades(rows_, lambda b: [{"time": (DONE + 1800) * 1000, "fundingRate": "0.0002"}])
        self.assertEqual(len(got), 1)
        self.assertAlmostEqual(got["net_bps"].iloc[0], 100 - 18 - 2)

    def test_no_closed_trades_is_an_empty_frame(self):
        self.assertTrue(la.closed_trades([], None).empty)


def frame(mean, n=300, coins=("BTC", "ETH", "SOL", "XRP", "DOGE", "LINK"), first=hb.WINDOW_START):
    days = np.linspace(first, hb.WINDOW_END - 86400, n).astype(int)
    noise = np.random.default_rng(3).normal(0, 1, n)
    return pd.DataFrame({"coin": [coins[k % len(coins)] for k in range(n)], "entry_ts": days,
                         "net_bps": mean + noise})


class TheVerdict(unittest.TestCase):
    def test_pass_needs_the_band(self):
        out = la.evaluate(frame(50.0), frame(10.0, n=40))
        self.assertEqual(out["verdict"], "PASS")
        self.assertTrue(out["checks"]["band"])

    def test_it_bounces_but_the_band_adds_nothing(self):
        out = la.evaluate(frame(50.0), frame(60.0, n=40))
        self.assertEqual(out["verdict"], "FAIL (it bounces, but the band adds nothing)")

    def test_equal_to_thin_is_not_above(self):
        self.assertFalse(la.evaluate(frame(50.0), frame(50.0))["checks"]["band"])

    def test_too_few_thin_events_cannot_meet_it(self):
        self.assertFalse(la.evaluate(frame(50.0), frame(10.0, n=29))["checks"]["band"])
        self.assertTrue(la.evaluate(frame(50.0), frame(10.0, n=30))["checks"]["band"])
        none = pd.DataFrame(columns=["coin", "entry_ts", "net_bps"])
        self.assertFalse(la.evaluate(frame(50.0), none)["checks"]["band"])

    def test_a_loss_is_a_plain_fail_even_if_above_thin(self):
        self.assertEqual(la.evaluate(frame(-5.0), frame(-50.0, n=40))["verdict"], "FAIL")

    def test_under_100_trades_is_inconclusive(self):
        self.assertEqual(la.evaluate(frame(50.0, n=99), frame(1.0, n=40))["verdict"], "INCONCLUSIVE")
        self.assertEqual(la.evaluate(frame(50.0, n=100), frame(1.0, n=40))["verdict"], "PASS")


class TheFiles(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.data = Path(self.tmp.name)

    def write(self, ts, positions):
        day = pd.Timestamp(ts, unit="s", tz="UTC")
        path = self.data / "positions" / day.strftime("%Y-%m-%d") / f"{day.strftime('%H')}00.csv.gz"
        path.parent.mkdir(parents=True, exist_ok=True)
        pd.DataFrame([{"ts": ts, "address": "a", "coin": c, "szi": s, "entry": 1, "value": v, "liq": q, "lev": 1,
                       "lev_type": "cross", "margin": 1, "upnl": 0, "account_value": 1} for c, s, v, q in positions],
                     columns=["ts", "address", "coin", "szi", "entry", "value", "liq", "lev", "lev_type", "margin",
                              "upnl", "account_value"]).to_csv(path, index=False)
        return path

    def test_read_slot_keeps_the_14_coins_and_its_ts(self):
        path = self.write(TS + 7, [("BTC", 1.0, 5.0, 99.5), ("DOGEFI", 1.0, 5.0, 99.5), ("kSHIB", 1.0, 3.0, "")])
        s = la.read_slot(path)
        self.assertEqual(s.ts, TS + 7)
        self.assertEqual(sorted(s.rows), ["BTC", "kSHIB"])
        self.assertEqual(la.band_usd(s.rows["kSHIB"], 100.0), 0.0)

    def test_an_empty_file_is_missing(self):
        self.assertIsNone(la.read_slot(self.write(TS, [])))

    def test_the_ledger_end_to_end(self):
        for k, v in enumerate(RAMP):
            self.write(TS - (100 - k) * HOUR, [("BTC", 1.0, v, 99.5)])
        self.write(TS, [("BTC", 1.0, 200.0, 99.5)])
        self.write(TS + 1 * HOUR, [("BTC", 1.0, 1.0, 97.5)])
        p = market()
        candles = self.data / "candles"
        candles.mkdir()
        c = p.frames[COIN][0]
        c.assign(coin=COIN, high=0, low=0, volume=0, trades=0).to_csv(candles / "2026-11-05.csv.gz", index=False)

        def no_network(body):
            return [{"time": (DONE + HOUR) * 1000, "fundingRate": "0.0001"}] if body["type"] == "fundingHistory" else []
        out = la.ledger(self.data, fetch=no_network, now=hb.WINDOW_END + 1)
        self.assertEqual(out["slots"], 102)
        self.assertEqual(out["empty_slots"], 0)
        self.assertEqual(len([r for r in out["rows"] if r["signal_ts"] == DONE]), 1)
        self.assertEqual(out["verdict"]["verdict"], "INCONCLUSIVE")


class TestCommand(unittest.TestCase):
    """`espero ladder` shows counts by file name before the window and refuses the verdict until it closes."""

    def test_status_counts_files_without_opening_them(self):
        with tempfile.TemporaryDirectory() as d:
            data = Path(d)
            (data / "positions" / "2026-11-05").mkdir(parents=True)
            (data / "positions" / "2026-11-05" / "00.csv.gz").write_bytes(b"not even gzip")
            (data / "candles").mkdir()
            (data / "candles" / "BTC.csv.gz").write_bytes(b"not even gzip")
            lines = la.status(data, now=hb.WINDOW_START - 1)
            self.assertIn("not open yet", lines[0])
            self.assertEqual(lines[1:], ["position slots on disk: 1", "candle files on disk: 1"])
            self.assertIn("closed", la.status(data, now=hb.WINDOW_END + 1)[0])

    def test_verdict_refuses_before_the_window_closes_and_runs_after(self):
        from espero import cli
        with tempfile.TemporaryDirectory() as d, mock.patch.object(la, "ledger") as ledger, \
                mock.patch("espero.cli.time") as clock:
            ledger.return_value = {"verdict": {"verdict": "INCONCLUSIVE"}, "slots": 0, "rows": [], "thin_rows": []}
            clock.time.return_value = hb.WINDOW_END - 1
            self.assertEqual(cli.main(["ladder", "--verdict", "--data", d]), 2)
            ledger.assert_not_called()
            clock.time.return_value = hb.WINDOW_END + 1
            self.assertEqual(cli.main(["ladder", "--verdict", "--data", d]), 0)
            ledger.assert_called_once()


if __name__ == "__main__":
    unittest.main()
