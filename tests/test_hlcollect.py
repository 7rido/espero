"""The Hyperliquid collector against a fake API: what it reads, the slot each file
belongs to, nothing fetched twice, failures kept from the disk, nothing half-written."""
from __future__ import annotations

import gzip
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import pandas as pd

from espero import hlcollect as hc

NOW = int(pd.Timestamp("2026-10-30 14:07:12", tz="UTC").timestamp())
KID = "0x00000000000000000000000000000000000000k1"


def state(*positions, value="1000"):
    return {"marginSummary": {"accountValue": value},
            "assetPositions": [{"type": "oneWay", "position": p} for p in positions]}


POS = {"coin": "BTC", "szi": "-2.5", "leverage": {"type": "cross", "value": 10}, "entryPx": "80000",
       "positionValue": "200000", "liquidationPx": "88000", "marginUsed": "20000", "unrealizedPnl": "-50"}


class Fake:
    """Hyperliquid's info endpoint, recorded."""

    def __init__(self, fail=()):
        self.calls, self.fail = [], set(fail)

    def __call__(self, body):
        self.calls.append(body)
        t = body["type"]
        if t == "clearinghouseState":
            if body["user"] in self.fail:
                raise RuntimeError("HTTP 500")
            return state(POS, {**POS, "coin": "ETH", "szi": "0"}, value="5000")
        if t == "vaultDetails":
            return {"relationship": {"type": "parent", "data": {"childAddresses": [KID.upper().replace("0X", "0x")]}}}
        if t == "metaAndAssetCtxs":
            return [{"universe": [{"name": "BTC"}, {"name": "OLD", "isDelisted": True}, {"name": "ETH"}]},
                    [{"funding": "0.0000125", "premium": "-0.0001", "openInterest": "100", "markPx": "80000",
                      "oraclePx": "80010", "midPx": "80001", "impactPxs": ["79999", "80003"], "dayNtlVlm": "1e9"},
                     {"funding": "0", "premium": "0", "openInterest": "0", "markPx": "1", "oraclePx": "1",
                      "midPx": "1", "impactPxs": None, "dayNtlVlm": "0"},
                     {"funding": "0.00002", "premium": "0.0002", "openInterest": "50", "markPx": "3000",
                      "oraclePx": "3001", "midPx": "3000.5", "impactPxs": ["2999", "3002"], "dayNtlVlm": "5e8"}]]
        if t == "candleSnapshot":
            s = body["req"]["startTime"]
            bar = lambda t: {"t": t, "o": "1", "h": "2", "l": "0.5", "c": "1.5", "v": "10", "n": 3}  # noqa: E731
            return [bar(s - 60_000), bar(s), bar(s + 60_000), bar(s + 86_400_000)]   # one either side of the day
        raise AssertionError(body)


def lb_get(url):
    rows = [{"ethAddress": f"0xA{k}", "accountValue": str(v)} for k, v in enumerate([5, 50, 500, 0.5])]
    return json.dumps({"leaderboardRows": rows}).encode()


def read(path: Path) -> pd.DataFrame:
    return pd.read_csv(io.BytesIO(gzip.decompress(path.read_bytes())))


class TestReading(unittest.TestCase):
    def test_top_addresses_largest_first(self):
        rows = json.loads(lb_get(""))["leaderboardRows"]
        self.assertEqual(hc.top_addresses(rows, 2), ["0xa2", "0xa1"])

    def test_hlp_accounts(self):
        self.assertEqual(hc.hlp_accounts(Fake()), [hc.HLP, KID])

    def test_position_rows_skip_closed_and_keep_the_liquidation_price(self):
        rows = hc.position_rows("0xabc", state(POS, {**POS, "szi": "0"}), NOW)
        self.assertEqual(len(rows), 1)
        r = rows[0]
        self.assertEqual((r["coin"], r["szi"], r["liq"], r["lev"], r["lev_type"]),
                         ("BTC", -2.5, 88000.0, 10.0, "cross"))
        self.assertEqual(r["account_value"], 1000.0)

    def test_a_missing_liquidation_price_is_nan(self):
        r = hc.position_rows("0xabc", state({**POS, "liquidationPx": None}), NOW)[0]
        self.assertNotEqual(r["liq"], r["liq"])

    def test_a_failing_account_is_counted_not_fatal(self):
        slept = []
        out = hc.positions(["0x1", "0x2", "0x3"], Fake(fail={"0x2"}), NOW, sleep=slept.append, pace=0.3)
        self.assertEqual((out["accounts"], out["failed"], len(out["frame"])), (3, 1, 2))
        self.assertEqual(slept, [0.3, 0.3])                  # paced between calls, not after the last

    def test_contexts_skip_delisted(self):
        df = hc.contexts(Fake(), NOW)
        self.assertEqual(list(df["coin"]), ["BTC", "ETH"])
        self.assertEqual(df.loc[0, "impact_ask"], 80003.0)

    def test_candles_keep_only_the_day(self):
        out = hc.day_candles(["BTC"], "2026-10-29", Fake(), sleep=lambda s: None)
        self.assertEqual(len(out["frame"]), 2)
        start = int(pd.Timestamp("2026-10-29", tz="UTC").timestamp())
        self.assertEqual(list(out["frame"]["ts"]), [start, start + 60])


class TestCollector(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.data = Path(self.tmp.name)
        self.fake = Fake()
        self.c = hc.Collector(self.data, fetch=self.fake, get=lb_get, top=3, sleep=lambda s: None)

    def tearDown(self):
        self.tmp.cleanup()

    def test_each_file_belongs_to_its_slot(self):
        self.assertEqual(self.c.ctx_path(NOW).relative_to(self.data).as_posix(), "ctx/2026-10-30/1405.csv.gz")
        self.assertEqual(self.c.hlp_path(NOW).relative_to(self.data).as_posix(), "hlp/2026-10-30/1400.csv.gz")
        self.assertEqual(self.c.positions_path(NOW).relative_to(self.data).as_posix(),
                         "positions/2026-10-30/1400.csv.gz")

    def test_a_step_writes_everything_once(self):
        notes = self.c.step(NOW)
        self.assertEqual(len(notes), 4, notes)
        self.assertFalse(any("FAILED" in n for n in notes), notes)
        pos = read(self.c.positions_path(NOW))
        self.assertEqual(sorted(pos["address"].unique()), ["0xa0", "0xa1", "0xa2"])  # the top 3 of 4
        self.assertEqual(read(self.c.hlp_path(NOW))["address"].nunique(), 2)
        self.assertEqual(len(read(self.c.ctx_path(NOW))), 2)
        for day in ("2026-10-28", "2026-10-29"):
            self.assertTrue(self.c.candles_path(day).exists())
        self.assertEqual(list(self.data.rglob("*.tmp")), [])
        n = len(self.fake.calls)
        self.assertEqual(self.c.step(NOW + 30), [])             # the same slots: nothing fetched again
        self.assertEqual(len(self.fake.calls), n)

    def test_the_next_five_minutes_is_a_new_context_slot_only(self):
        self.c.step(NOW)
        self.assertEqual(self.c.due(NOW + 300), ["ctx"])
        self.assertEqual(self.c.due(NOW + 900), ["ctx", "hlp"])
        self.assertEqual(self.c.due(NOW + 3600), ["ctx", "hlp", "positions"])

    def test_the_ranking_is_read_once_a_day(self):
        got = []
        c = hc.Collector(self.data, fetch=self.fake, get=lambda u: got.append(u) or lb_get(u), top=3,
                         sleep=lambda s: None)
        c.run("positions", NOW)
        c.run("positions", NOW + 3600)
        self.assertEqual(len(got), 1)
        self.assertTrue(c.addresses_path(NOW).exists())

    def reads(self, c=None):
        return json.loads((c or self.c).hlp_reads_path(NOW).read_text())

    def test_each_hlp_slot_records_the_accounts_asked_and_none_failed(self):
        self.c.attempt("hlp", NOW)
        self.assertEqual(self.c.hlp_reads_path(NOW).relative_to(self.data).as_posix(),
                         "hlp_reads/2026-10-30/1400.json")
        self.assertEqual(self.reads(), {"ts": NOW, "accounts": [hc.HLP, KID], "failed": []})

    def test_a_failed_read_is_named_and_the_slot_still_saved(self):
        c = hc.Collector(self.data, fetch=Fake(fail={KID}), get=lb_get, top=3, sleep=lambda s: None)
        c.attempt("hlp", NOW)
        self.assertEqual(self.reads(c)["failed"], [KID])
        self.assertTrue(c.hlp_path(NOW).exists())

    def test_the_record_lands_before_the_positions(self):
        with mock.patch.object(hc, "write", side_effect=RuntimeError("disk")):
            self.assertIn("FAILED", self.c.attempt("hlp", NOW))
        self.assertTrue(self.c.hlp_reads_path(NOW).exists())
        self.assertFalse(self.c.hlp_path(NOW).exists())

    def test_a_record_that_cannot_be_written_never_costs_the_positions(self):
        with mock.patch.object(hc, "write_reads", side_effect=OSError("disk")):
            self.assertNotIn("FAILED", self.c.attempt("hlp", NOW))
        self.assertTrue(self.c.hlp_path(NOW).exists())

    def test_the_hourly_positions_write_no_record(self):
        self.c.attempt("positions", NOW)
        self.assertFalse((self.data / "hlp_reads").exists())

    def test_a_record_is_not_taken_for_a_data_file(self):
        self.c.attempt("hlp", NOW)
        self.assertEqual(hc.status(self.data, NOW)["hlp"]["files"], 1)

    def test_a_snapshot_mostly_failed_is_not_saved(self):
        c = hc.Collector(self.data, fetch=Fake(fail={"0xa2", "0xa1"}), get=lb_get, top=3, sleep=lambda s: None)
        note = c.attempt("positions", NOW)
        self.assertIn("FAILED", note)
        self.assertFalse(c.positions_path(NOW).exists())
        self.assertIn("positions", c.due(NOW))                   # tried again on the next tick

    def test_status(self):
        self.c.step(NOW)
        s = hc.status(self.data, NOW)
        self.assertEqual(s["positions"]["files"], 1)
        self.assertEqual(s["candles"]["files"], 2)


if __name__ == "__main__":
    unittest.main()
