"""#32: each forced down-break gets the funding settled at or before it, above 0.01% is
crowded, and the criteria compare crowded against not."""
from __future__ import annotations

import io
import tempfile
import unittest
import zipfile
from pathlib import Path

import numpy as np
import pandas as pd

from espero import fundsplit as fs

T0 = int(pd.Timestamp("2026-11-02", tz="UTC").timestamp())


def month_zip(rows, header=True):
    """An archive month: rows of (ts_seconds, interval_hours, rate)."""
    body = ("calc_time,funding_interval_hours,last_funding_rate\n" if header else "") + \
        "".join(f"{t * 1000 + 5},{h},{r}\n" for t, h, r in rows)
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("x.csv", body)
    return buf.getvalue()


def fake_get(published):
    """data.binance.vision over {month: zip bytes}; anything else is a 404 (None)."""
    calls = []

    def get(url):
        calls.append(url.rsplit("-fundingRate-", 1)[1][:7])
        return published.get(calls[-1])
    get.calls = calls
    return get


class TestFunding(unittest.TestCase):
    def test_months_from_the_one_before_the_window(self):
        now = pd.Timestamp("2026-12-03 07:30", tz="UTC")
        self.assertEqual(fs.months(now), ["2026-10", "2026-11", "2026-12"])
        self.assertEqual(fs.months(pd.Timestamp("2027-06-01", tz="UTC"))[-1], "2027-03")

    def test_a_4_hour_coin_is_scaled_to_8_hours(self):
        df = fs.parse(month_zip([(T0, 8, 0.0001), (T0 + 14400, 4, 0.00006)]))
        self.assertEqual(df["ts"].tolist(), [T0, T0 + 14400])
        self.assertAlmostEqual(df["rate"].iloc[1], 0.00012)
        self.assertEqual(fs.parse(month_zip([(T0, 8, 0.0002)], header=False))["rate"].tolist(), [0.0002])

    def test_cached_per_month_and_unpublished_months_retried(self):
        now = pd.Timestamp("2026-11-05", tz="UTC")
        with tempfile.TemporaryDirectory() as d:
            get = fake_get({"2026-10": month_zip([(T0 - 86400 * 5, 8, 0.0001)])})
            df = fs.rates("BTCUSDT", Path(d), now, get)
            self.assertEqual(len(df), 1)
            self.assertEqual(get.calls, ["2026-10", "2026-11"])         # November is not out yet
            get2 = fake_get({"2026-11": month_zip([(T0, 8, 0.0003)])})
            df = fs.rates("BTCUSDT", Path(d), now, get2)
            self.assertEqual(get2.calls, ["2026-11"])                   # October came from the cache
            self.assertEqual(df["rate"].tolist(), [0.0001, 0.0003])

    def test_the_last_settlement_at_or_before_the_break(self):
        f = pd.DataFrame({"ts": [T0, T0 + 28800], "rate": [0.0001, 0.0005]})
        ev = pd.DataFrame({"coin": "BTC", "ts": [T0 - 60, T0, T0 + 28799, T0 + 28800]})
        got = fs.attach(ev, {"BTC": f}).sort_values("ts")["funding"].tolist()
        self.assertTrue(np.isnan(got[0]))                  # nothing settled yet
        self.assertEqual(got[1:], [0.0001, 0.0001, 0.0005])

    def test_a_settlement_older_than_one_interval_is_not_the_one_before_the_break(self):
        """Until the archive publishes the current month, the last rate on disk is last month's final one."""
        f = pd.DataFrame({"ts": [T0], "rate": [0.0009]})
        ev = pd.DataFrame({"coin": "BTC", "ts": [T0 + 8 * 3600, T0 + 356 * 3600]})
        got = fs.attach(ev, {"BTC": f}).sort_values("ts")["funding"].tolist()
        self.assertEqual(got[0], 0.0009)                    # inside one interval: that settlement
        self.assertTrue(np.isnan(got[1]))                   # two weeks on: unknown, and dropped as the plan says

    def test_crowded_means_above_the_default(self):
        ev = pd.DataFrame({"direction": -1, "group": "forced", "funding": [0.0001, 0.00011, np.nan],
                           "y60": 0.0, "y240": 0.0, "day": "2026-11-02"})
        fd = fs.forced_down(ev)
        self.assertEqual(fd["crowded"].tolist(), [False, True])     # the missing rate is dropped


def ledger(crowded_gain, normal_gain, seed=0):
    rng = np.random.default_rng(seed)
    rows = []
    for d in pd.date_range(fs.FORWARD_FROM, fs.FORWARD_TO):
        for crowded in (True, False):
            g = crowded_gain if crowded else normal_gain
            rows.append({"day": d.strftime("%Y-%m-%d"), "direction": -1, "group": "forced",
                         "funding": 0.0005 if crowded else 0.0001,
                         "y60": -(g + rng.normal(0, 0.001)), "y240": -(g + rng.normal(0, 0.001))})
            rows.append({"day": d.strftime("%Y-%m-%d"), "direction": 1, "group": "forced", "funding": 0.0005,
                         "y60": 0.05, "y240": 0.05})           # up-breaks never count
            rows.append({"day": d.strftime("%Y-%m-%d"), "direction": -1, "group": "organic", "funding": 0.0005,
                         "y60": 0.05, "y240": 0.05})           # nor organic down-breaks
    return pd.DataFrame(rows)


class TestCriteria(unittest.TestCase):
    def test_all_four(self):
        crit = fs.criteria(ledger(0.004, 0.001))
        self.assertEqual([c["met"] for c in crit], [True, True, True, True])
        self.assertEqual(fs.verdict(crit), "PASS")

    def test_no_gap_fails(self):
        crit = fs.criteria(ledger(0.003, 0.003))
        self.assertFalse(crit[0]["met"])
        self.assertEqual(fs.verdict(crit), "FAIL")

    def test_a_gap_that_does_not_pay(self):
        crit = fs.criteria(ledger(0.001, -0.001))
        self.assertTrue(crit[0]["met"])
        self.assertFalse(crit[1]["met"])

    def test_the_long_return_is_minus_y(self):
        # y is in the break's direction: a down-break that bounces has y60 < 0
        crit = fs.criteria(ledger(0.004, 0.001))
        self.assertIn("+40", crit[1]["actual"])


class TestRun(unittest.TestCase):
    def test_no_ledger_yet(self):
        with tempfile.TemporaryDirectory() as s:
            self.assertEqual(fs.run(Path(s), get=lambda u: None)["note"], "mark: no breaks yet")

    def test_joins_and_writes(self):
        ev = pd.DataFrame({"coin": "BTC", "ts": [T0 + 100, T0 + 200], "day": "2026-11-02", "direction": -1,
                           "group": "forced", "y60": [-0.003, -0.001], "y240": [-0.004, -0.002]})
        with tempfile.TemporaryDirectory() as s, tempfile.TemporaryDirectory() as d:
            ev.to_csv(Path(s) / fs.LEDGER_IN, index=False)
            out = fs.run(Path(s), Path(d), get=fake_get({"2026-11": month_zip([(T0, 8, 0.0003)])}),
                         now=pd.Timestamp("2026-11-03", tz="UTC"))
            joined = pd.read_csv(Path(s) / fs.LEDGER)
        self.assertEqual(joined["funding"].tolist(), [0.0003, 0.0003])
        self.assertIn("2 forced down-breaks, 2 after crowded funding", out["note"])


if __name__ == "__main__":
    unittest.main()
