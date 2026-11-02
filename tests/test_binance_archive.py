"""The archive backfill against a fake server: a file is kept only when its SHA-256 matches the published
one, a 404 is recorded as missing and asked again, a verified file is never fetched twice, and the listing
says whether any dataset names liquidations."""
from __future__ import annotations

import csv
import hashlib
import tempfile
import unittest
from pathlib import Path

from espero import binance_archive as ba

BLOB = b"PK\x03\x04 not really a zip"
SHA = hashlib.sha256(BLOB).hexdigest()


class Server:
    def __init__(self, files=None, bad=()):
        self.files = files if files is not None else {}
        self.bad = set(bad)
        self.calls = []

    def __call__(self, url):
        self.calls.append(url)
        if url.endswith(".CHECKSUM"):
            name = url[: -len(".CHECKSUM")]
            if name not in self.files:
                raise ba.NotPublished(url)
            sha = "0" * 64 if name in self.bad else hashlib.sha256(self.files[name]).hexdigest()
            return f"{sha}  {name.rsplit('/', 1)[-1]}\n".encode()
        if url.startswith("https://s3-ap-northeast-1"):
            period = "monthly" if "monthly" in url else "daily"
            return ("<ListBucketResult>" + "".join(f"<Prefix>data/futures/um/{period}/{d}/</Prefix>"
                                                  for d in ("aggTrades", "bookTicker", "metrics")) +
                    "</ListBucketResult>").encode()
        if url not in self.files:
            raise ba.NotPublished(url)
        return self.files[url]


class TestBackfill(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.raw = Path(self.tmp.name)
        self.url = ba.url_for("aggTrades", "BTCUSDT", "2026-10-30")

    def tearDown(self):
        self.tmp.cleanup()

    def test_url_and_target_follow_the_archives_layout(self):
        self.assertEqual(self.url, "https://data.binance.vision/data/futures/um/daily/aggTrades/BTCUSDT/"
                                   "BTCUSDT-aggTrades-2026-10-30.zip")
        self.assertEqual(ba.url_for("premiumIndexKlines", "ETHUSDT", "2026-10-30"),
                         ba.BASE + "premiumIndexKlines/ETHUSDT/5m/ETHUSDT-5m-2026-10-30.zip")
        self.assertEqual(ba.target(self.raw, "aggTrades", "BTCUSDT", "2026-10-30"),
                         self.raw / "binance_archive" / "aggTrades" / "BTCUSDT" / "BTCUSDT-aggTrades-2026-10-30.zip")

    def test_verified_file_is_kept_and_never_fetched_twice(self):
        srv = Server({self.url: BLOB})
        got = ba.backfill(self.raw, ["BTCUSDT"], ["2026-10-30"], ["aggTrades"], get=srv, log=lambda s: None,
                          sleep=lambda s: None)
        self.assertEqual(got, {"kept": 0, "fetched": 1, "missing": 0})
        path = ba.target(self.raw, "aggTrades", "BTCUSDT", "2026-10-30")
        self.assertEqual(path.read_bytes(), BLOB)
        self.assertEqual((path.parent / (path.name + ".CHECKSUM")).read_text().split()[0], SHA)
        n = len(srv.calls)
        got = ba.backfill(self.raw, ["BTCUSDT"], ["2026-10-30"], ["aggTrades"], get=srv, log=lambda s: None,
                          sleep=lambda s: None)
        self.assertEqual(got, {"kept": 1, "fetched": 0, "missing": 0})
        self.assertEqual(len(srv.calls), n, "a verified file is not asked for again")

    def test_a_wrong_checksum_keeps_nothing(self):
        srv = Server({self.url: BLOB}, bad={self.url})
        with self.assertRaises(RuntimeError):
            ba.fetch_one(self.raw, "aggTrades", "BTCUSDT", "2026-10-30", get=srv)
        self.assertFalse(ba.target(self.raw, "aggTrades", "BTCUSDT", "2026-10-30").exists())
        self.assertEqual(list(self.raw.rglob("*.tmp")), [])

    def test_a_day_not_published_is_recorded_and_asked_again(self):
        srv = Server({})
        got = ba.backfill(self.raw, ["BTCUSDT"], ["2026-10-30", "2026-10-31"], ["aggTrades"], get=srv,
                          log=lambda s: None, sleep=lambda s: None)
        self.assertEqual(got["missing"], 2)
        with (self.raw / "binance_archive" / "missing.csv").open() as f:
            rows = list(csv.DictReader(f))
        self.assertEqual([(r["dataset"], r["symbol"], r["day"]) for r in rows],
                         [("aggTrades", "BTCUSDT", "2026-10-30"), ("aggTrades", "BTCUSDT", "2026-10-31")])
        srv.files[self.url] = BLOB
        got = ba.backfill(self.raw, ["BTCUSDT"], ["2026-10-30"], ["aggTrades"], get=srv, log=lambda s: None,
                          sleep=lambda s: None)
        self.assertEqual(got["fetched"], 1)

    def test_listing_records_that_no_dataset_names_liquidations(self):
        doc = ba.record_listing(self.raw, get=Server(), now=5)
        self.assertEqual(doc["datasets"]["daily"], ["aggTrades", "bookTicker", "metrics"])
        self.assertFalse(doc["liquidation_dataset"])
        self.assertTrue((self.raw / "binance_archive" / "datasets.json").exists())

    def test_days_between_is_inclusive(self):
        self.assertEqual(ba.days_between("2026-10-30", "2026-11-01"), ["2026-10-30", "2026-10-31", "2026-11-01"])


if __name__ == "__main__":
    unittest.main()
