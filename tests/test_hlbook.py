"""The order-book recorder against a fake API: the frozen coin list, the slot each file belongs to,
nothing fetched twice, a bad slot kept from the disk, a lone failed coin left as a gap."""
from __future__ import annotations

import gzip
import json
import tempfile
import unittest
from pathlib import Path

import pandas as pd

from espero import hlbook as hb

NOW = int(pd.Timestamp("2026-10-31 14:07:12", tz="UTC").timestamp())
BOOK = {"coin": "X", "time": 1_793_000_000_000,
        "levels": [[{"px": "100", "sz": "2", "n": 3}, {"px": "99", "sz": "5", "n": 1}],
                   [{"px": "101", "sz": "1", "n": 2}]]}


class Fake:
    def __init__(self, volumes=None, fail=()):
        self.volumes = volumes if volumes is not None else {f"C{k}": 100.0 - k for k in range(12)}
        self.fail = set(fail)
        self.calls = []

    def __call__(self, body):
        self.calls.append(body)
        if body["type"] == "metaAndAssetCtxs":
            names = list(self.volumes)
            return [{"universe": [{"name": n} for n in names]}, [{"dayNtlVlm": str(self.volumes[n])} for n in names]]
        if body["coin"] in self.fail:
            raise RuntimeError("boom")
        return BOOK


def read(path: Path) -> pd.DataFrame:
    with gzip.open(path, "rt") as f:
        return pd.read_csv(f)


class RecorderTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.data = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def rec(self, fake):
        return hb.Recorder(self.data, fake, sleep=lambda s: None, pace=0.0)

    def test_top_coins_by_volume(self):
        fake = Fake({"A": 1.0, "B": 3.0, "C": 2.0})
        self.assertEqual(hb.top_coins(fake, 2), ["B", "C"])

    def test_delisted_coin_is_not_chosen(self):
        def fetch(_):
            return [{"universe": [{"name": "OLD", "isDelisted": True}, {"name": "NEW"}]},
                    [{"dayNtlVlm": "9"}, {"dayNtlVlm": "1"}]]
        self.assertEqual(hb.top_coins(fetch, 2), ["NEW"])

    def test_rows_keep_side_level_and_both_clocks(self):
        rows = hb.book_rows("X", BOOK, 5)
        self.assertEqual([(r["side"], r["level"], r["px"]) for r in rows],
                         [("bid", 0, 100.0), ("bid", 1, 99.0), ("ask", 0, 101.0)])
        self.assertEqual((rows[0]["ts"], rows[0]["valid_ms"], rows[0]["n"]), (5, BOOK["time"], 3))

    def test_slot_file_and_contents(self):
        self.rec(Fake()).step(NOW)
        path = self.data / "2026-10-31" / "1405.csv.gz"
        got = read(path)
        self.assertEqual(list(got.columns), hb.COLS)
        self.assertEqual(got["coin"].nunique(), hb.COINS)

    def test_coin_list_is_frozen_at_the_first_run(self):
        self.rec(Fake()).step(NOW)
        first = json.loads((self.data / "coins.json").read_text())["coins"]
        later = Fake({"NEW": 1e9, **{f"C{k}": 1.0 for k in range(12)}})
        self.rec(later).step(NOW + hb.EVERY_S)
        self.assertEqual(json.loads((self.data / "coins.json").read_text())["coins"], first)
        self.assertNotIn({"type": "l2Book", "coin": "NEW"}, later.calls)

    def test_a_slot_on_disk_is_not_fetched_again(self):
        fake = Fake()
        r = self.rec(fake)
        r.step(NOW)
        n = len(fake.calls)
        self.assertEqual(r.step(NOW + 30), "nothing due")
        self.assertEqual(len(fake.calls), n)
        self.assertNotEqual(r.step(NOW + hb.EVERY_S), "nothing due")

    def test_a_failed_coin_is_a_gap(self):
        note = self.rec(Fake(fail=["C0"])).step(NOW)
        self.assertIn("C0", note)
        got = read(self.data / "2026-10-31" / "1405.csv.gz")
        self.assertNotIn("C0", set(got["coin"]))
        self.assertEqual(got["coin"].nunique(), hb.COINS - 1)

    def test_most_coins_failing_saves_nothing(self):
        note = self.rec(Fake(fail=[f"C{k}" for k in range(6)])).step(NOW)
        self.assertIn("FAILED", note)
        self.assertFalse((self.data / "2026-10-31" / "1405.csv.gz").exists())

    def test_half_failing_still_saves(self):
        self.rec(Fake(fail=[f"C{k}" for k in range(5)])).step(NOW)
        self.assertTrue((self.data / "2026-10-31" / "1405.csv.gz").exists())

    def test_status_counts_slots(self):
        r = self.rec(Fake())
        r.step(NOW)
        s = hb.status(self.data, NOW)
        self.assertEqual(s["files"], 1)
        self.assertEqual(s["days"]["2026-10-31"], {"slots": 1, "expected": (14 * 60 + 7) // 5 + 1})
        self.assertEqual(s["days"]["2026-10-30"], {"slots": 0, "expected": 288})


if __name__ == "__main__":
    unittest.main()
