"""The Deribit recorder against a fake API: names parsed, each file in its slot, nothing fetched twice,
a failed currency never half-written, the gamma helper against a known value."""
from __future__ import annotations

import gzip
import io
import json
import math
import tempfile
import unittest
from pathlib import Path

import pandas as pd

from espero import deribit as dr

NOW = int(pd.Timestamp("2026-11-02 14:07:12", tz="UTC").timestamp())


def row(name, oi=1.5, iv=40.0, under=78000.0, mark=0.05):
    return {"instrument_name": name, "open_interest": oi, "mark_iv": iv, "mark_price": mark, "underlying_price": under,
            "estimated_delivery_price": under, "bid_price": 0.04, "ask_price": 0.06, "volume": 2.0, "volume_usd": 100.0,
            "interest_rate": 0.0}


class Fake:
    """Deribit's public endpoint, recorded; `fail` names currencies whose option call raises."""

    def __init__(self, fail=()):
        self.calls, self.fail = [], set(fail)

    def __call__(self, url: str) -> bytes:
        self.calls.append(url)
        currency = url.split("currency=")[1].split("&")[0]
        kind = url.split("kind=")[1]
        if currency in self.fail and kind == "option":
            raise OSError("down")
        if kind == "option":
            rows = [row(f"{currency}-13NOV26-83000-P"), row(f"{currency}-13NOV26-83000-C", oi=0.0)]
            if currency == "USDC":
                rows = [row("XRP_USDC-13NOV26-1d16-C", under=1.2), row("SOL_USDC-27NOV26-170-C", under=94.0)]
        else:
            rows = [row(f"{currency}-PERPETUAL", iv=None), row(f"{currency}-29JAN27", iv=None)]
        return json.dumps({"result": rows}).encode()


class Names(unittest.TestCase):
    def test_shapes(self):
        e = int(pd.Timestamp("2026-11-13 08:00", tz="UTC").timestamp())
        self.assertEqual(dr.parse_name("BTC-13NOV26-83000-P"), ("BTC", e, 83000.0, "P"))
        self.assertEqual(dr.parse_name("XRP_USDC-13NOV26-1d16-C"), ("XRP", e, 1.16, "C"))
        self.assertEqual(dr.parse_name("AVAX_USDC-6NOV26-7d5-C"), ("AVAX", e - 7 * 86400, 7.5, "C"))
        self.assertEqual(dr.parse_name("BTC-29JAN27"), ("BTC", int(pd.Timestamp("2027-01-29 08:00", tz="UTC").timestamp()), None, None))
        self.assertEqual(dr.parse_name("SOL_USDC-PERPETUAL"), ("SOL", None, None, None))
        self.assertEqual(dr.parse_name("BTC-PERPETUAL"), ("BTC", None, None, None))

    def test_summary_columns_and_missing_values(self):
        df = dr.summary("ETH", "future", Fake(), NOW)
        self.assertEqual(list(df.columns), dr.COLS)
        self.assertEqual(df["instrument"].tolist(), ["ETH-PERPETUAL", "ETH-29JAN27"])
        self.assertTrue(math.isnan(df["mark_iv"].iloc[0]))
        self.assertTrue(pd.isna(df["strike"].iloc[0]))
        self.assertEqual((df["ts"].iloc[0], df["currency"].iloc[0], df["kind"].iloc[0]), (NOW, "ETH", "future"))


class TheRecorder(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.data = Path(self.tmp.name)
        self.api = Fake()
        self.rec = dr.Recorder(self.data, get=self.api, sleep=lambda s: None)

    def tearDown(self):
        self.tmp.cleanup()

    def test_each_file_belongs_to_its_slot(self):
        self.assertEqual(self.rec.path("BTC", NOW), self.data / "BTC" / "2026-11-02" / "1405.csv.gz")
        self.assertEqual(self.rec.path("USDC", NOW + 180), self.data / "USDC" / "2026-11-02" / "1410.csv.gz")

    def test_a_step_writes_every_currency_once_with_both_kinds(self):
        notes = self.rec.step(NOW)
        self.assertEqual(len(notes), 3)
        self.assertEqual(len(self.api.calls), 6)
        df = pd.read_csv(self.data / "BTC" / "2026-11-02" / "1405.csv.gz")
        self.assertEqual(df["kind"].tolist(), ["option", "option", "future", "future"])
        self.assertEqual(int(df["ts"].iloc[0]), NOW)
        self.assertEqual(df["strike"].iloc[0], 83000.0)
        usdc = pd.read_csv(self.data / "USDC" / "2026-11-02" / "1405.csv.gz")
        self.assertEqual(usdc["base"].tolist()[:2], ["XRP", "SOL"])
        self.assertEqual(self.rec.step(NOW + 60), [])
        self.assertEqual(len(self.api.calls), 6)
        self.assertEqual(len(self.rec.step(NOW + 300)), 3)

    def test_a_failed_currency_writes_nothing_and_the_rest_still_land(self):
        rec = dr.Recorder(self.data, get=Fake(fail=("ETH",)), sleep=lambda s: None)
        notes = rec.step(NOW)
        self.assertTrue(any(n.startswith("ETH: FAILED") for n in notes))
        self.assertFalse((self.data / "ETH").exists())
        self.assertTrue(rec.path("BTC", NOW).exists())
        self.assertEqual(list((self.data / "BTC" / "2026-11-02").iterdir()), [rec.path("BTC", NOW)])
        self.assertEqual(rec.due(NOW), ["ETH"])

    def test_the_loop_ticks_the_clock(self):
        clock = iter([NOW, NOW + 30, NOW + 300])
        rec = dr.Recorder(self.data, get=self.api, sleep=lambda s: None, currencies=("BTC",))
        with self.assertRaises(StopIteration):
            rec.loop(tick=30, clock=lambda: next(clock))
        self.assertEqual(sorted(p.name for p in (self.data / "BTC" / "2026-11-02").iterdir()), ["1405.csv.gz", "1410.csv.gz"])

    def test_status(self):
        self.rec.step(NOW)
        s = dr.status(self.data)
        self.assertEqual(s["BTC"]["files"], 1)
        self.assertEqual(s["BTC"]["latest"], "BTC/2026-11-02/1405.csv.gz")
        self.assertGreater(s["USDC"]["bytes"], 0)


class Gamma(unittest.TestCase):
    def test_known_value(self):
        self.assertAlmostEqual(dr.black76_gamma(100.0, 100.0, 0.2, 1.0), 0.0198476, places=7)
        self.assertAlmostEqual(dr.black76_gamma(100.0, 100.0, 0.2, 1.0, rate=0.05), 0.0198476 * math.exp(-0.05), places=7)
        self.assertAlmostEqual(dr.black76_gamma(100.0, 100.0, 0.2, 0.25), 0.0398444, places=7)   # v = 0.1, d1 = 0.05
        self.assertEqual(dr.black76_gamma(100.0, 100.0, 0.2, 0.0), 0.0)
        self.assertEqual(dr.black76_gamma(100.0, 100.0, 0.0, 1.0), 0.0)
        self.assertAlmostEqual(dr.black76_gamma(100.0, 80.0, 0.2, 1.0), dr.black76_gamma(100.0, 80.0, 0.2, 1.0))

    def test_by_strike_sums_open_interest_times_gamma_times_underlying_squared(self):
        now = int(pd.Timestamp("2026-11-12 08:00", tz="UTC").timestamp())      # one day to expiry
        df = dr.summary("BTC", "option", Fake(), now)
        out = dr.gamma_by_strike(df, now)
        self.assertEqual(len(out), 2)
        put = out[out["type"] == "P"].iloc[0]
        g = dr.black76_gamma(78000.0, 83000.0, 0.40, 1 / 365.25)
        self.assertAlmostEqual(put["gamma_usd_per_pct"], 1.5 * g * 78000.0 ** 2 * 0.01, places=3)
        self.assertEqual(out[out["type"] == "C"].iloc[0]["gamma_usd_per_pct"], 0.0)




class TheAgent(unittest.TestCase):
    def test_the_installer_renders_the_recorder(self):
        import plistlib
        import shutil
        import subprocess
        if not (shutil.which("bash") and shutil.which("sed")):
            self.skipTest("needs bash and sed")
        root = Path(dr.__file__).resolve().parents[1]
        out = subprocess.run(["bash", str(root / "scripts" / "install-deribit-launchd.sh"), "--print"],
                             capture_output=True, text=True, check=True,
                             env={"PATH": "/usr/bin:/bin", "HOME": "/tmp", "PYTHON": "/x/python"}).stdout
        p = plistlib.loads(out.encode())
        self.assertEqual(p["Label"], "com.espero.deribit")
        self.assertEqual(p["ProgramArguments"], ["/x/python", "-m", "espero", "deribit", "--loop", "--data",
                                                 str(root / "data" / "deribit")])
        self.assertEqual(p["WorkingDirectory"], str(root))
        self.assertTrue(p["KeepAlive"])
        self.assertTrue(p["StandardOutPath"].endswith("/deribit.log"))


if __name__ == "__main__":
    unittest.main()
