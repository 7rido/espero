"""The trade.xyz recorder: its own folder, a list that only grows, one feed; on fake sockets and made-up markets."""
import asyncio
import json
import tempfile
import unittest
from pathlib import Path

from espero import hip3
from espero import hip3rec as R
from espero import rawrec as rr

try:
    import zstandard  # noqa: F401
    HAVE_ZSTD = True
except ImportError:
    HAVE_ZSTD = False

T0 = 1_793_577_600_000 + 3_600_000            # 2026-11-02 01:00 UTC


def market(coin, volume):
    return hip3.Market(coin, 100.0, 0.0, 0.0, 1e6, volume, 10, 0.9, 0.3, True, 1.0)


MAPPED = ("NVDA", "GOLD", "INTC", "IBM")


class TestFolder(unittest.TestCase):
    def test_it_needs_its_own_folder(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d).resolve()
            with self.assertRaises(RuntimeError):
                R.raw_dir({})
            with self.assertRaises(RuntimeError):
                R.raw_dir({R.ENV: str(root / "tape"), rr.ENV: str(root / "tape")})
            with self.assertRaises(RuntimeError):
                R.raw_dir({R.ENV: str(root / "tape" / "hip3"), rr.ENV: str(root / "tape")})
            with self.assertRaises(RuntimeError):
                R.raw_dir({R.ENV: str(root), rr.ENV: str(root / "tape")})
            with self.assertRaises(RuntimeError):
                R.raw_dir({R.ENV: str(root / "data" / "x")}, project=root)
            self.assertEqual(R.raw_dir({R.ENV: str(root / "hip3"), rr.ENV: str(root / "tape")}), root / "hip3")
            self.assertEqual(R.raw_dir({R.ENV: str(root / "hip3")}), root / "hip3")


class TestCoins(unittest.TestCase):
    def test_mapped_markets_at_the_bar(self):
        got = R.qualifying([market("xyz:NVDA", 7e8), market("xyz:IBM", 4.9e6), market("xyz:GOLD", 5e6),
                            market("xyz:NEWCO", 9e9)], MAPPED)
        self.assertEqual(got, ["xyz:GOLD", "xyz:NVDA"])

    def test_the_list_only_grows_and_only_listed_coins_are_asked_for(self):
        with tempfile.TemporaryDirectory() as d:
            raw = Path(d)
            first = R.coins(raw, [market("xyz:NVDA", 7e8), market("xyz:GOLD", 6e6)], MAPPED, 100)
            self.assertEqual(first, ["xyz:GOLD", "xyz:NVDA"])
            later = R.coins(raw, [market("xyz:NVDA", 1.0), market("xyz:INTC", 8e7)], MAPPED, 200)
            self.assertEqual(later, ["xyz:NVDA", "xyz:INTC"])            # NVDA stays though thin; GOLD is delisted
            doc = json.loads((raw / "coins.json").read_text())
            self.assertEqual(doc["venues"]["hyperliquid"], ["xyz:GOLD", "xyz:NVDA", "xyz:INTC"])
            self.assertEqual(doc["added"], {"hyperliquid:xyz:GOLD": 100, "hyperliquid:xyz:NVDA": 100,
                                            "hyperliquid:xyz:INTC": 200})
            self.assertEqual(doc["chosen_ts"], 100)
            again = R.coins(raw, [market("xyz:NVDA", 7e8), market("xyz:INTC", 8e7)], MAPPED, 250)
            self.assertEqual(again, ["xyz:NVDA", "xyz:INTC"])                # qualifying twice lists it once
            self.assertEqual(json.loads((raw / "coins.json").read_text()), doc)
            self.assertEqual(R.coins(raw, None, MAPPED, 300), ["xyz:GOLD", "xyz:NVDA", "xyz:INTC"])
            self.assertEqual([p.name for p in raw.iterdir()], ["coins.json"])

    def test_a_venue_that_does_not_answer_writes_no_list(self):
        with tempfile.TemporaryDirectory() as d:
            self.assertEqual(R.coins(Path(d), None, MAPPED, 100), [])
            self.assertEqual(list(Path(d).iterdir()), [])


class FakeSocket:
    def __init__(self, frames, sent):
        self.frames, self.sent = list(frames), sent

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def send(self, msg):
        self.sent.append(json.loads(msg))

    def __aiter__(self):
        return self

    async def __anext__(self):
        if not self.frames:
            raise StopAsyncIteration
        return self.frames.pop(0)


@unittest.skipUnless(HAVE_ZSTD, "needs zstandard")
class TestRecorder(unittest.TestCase):
    def run_once(self, rec):
        async def session():
            task = asyncio.create_task(rec.run())
            await asyncio.sleep(0.1)
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass

        asyncio.run(session())

    def test_one_feed_on_mainnet_for_the_qualifying_markets_readable_as_the_first_tape_is(self):
        sent, urls = [], []
        book = json.dumps({"channel": "l2Book", "data": {"coin": "xyz:NVDA", "time": T0, "levels": [[], []]}})
        trade = json.dumps({"channel": "trades", "data": [{"coin": "xyz:NVDA", "px": "180", "sz": "1"}]})

        def connect(url, **kw):
            urls.append(url)
            return FakeSocket([book, trade], sent)

        with tempfile.TemporaryDirectory() as d:
            raw = Path(d)
            rec = R.Hip3Recorder(raw, markets=lambda: [market("xyz:NVDA", 7e8), market("xyz:IBM", 1e5)], mapped=MAPPED,
                                 connect=connect, clock=lambda: T0, free=lambda p: 100.0)
            self.run_once(rec)
            self.assertEqual(urls[0], rr.HL_MAINNET_WS)
            self.assertEqual([m["subscription"] for m in sent[:2]],
                             [{"type": "trades", "coin": "xyz:NVDA"}, {"type": "l2Book", "coin": "xyz:NVDA"}])
            self.assertEqual(sorted(p.name for p in raw.iterdir() if p.is_dir()), ["hyperliquid"])
            recs = [(r["ch"], r["s"]) for r in rr.read_day(raw, "hyperliquid", "2026-11-02")]
            self.assertIn(("l2Book", "xyz:NVDA"), recs)
            self.assertIn(("trades", "xyz:NVDA"), recs)
            self.assertEqual(json.loads((raw / "coins.json").read_text())["venues"], {"hyperliquid": ["xyz:NVDA"]})

    def test_with_no_answer_it_records_what_the_folder_lists_and_with_nothing_it_stops(self):
        with tempfile.TemporaryDirectory() as d:
            raw = Path(d)
            rec = R.Hip3Recorder(raw, markets=lambda: 1 / 0, mapped=MAPPED, clock=lambda: T0, free=lambda p: 100.0,
                                 connect=lambda url, **kw: FakeSocket([], []))
            with self.assertRaises(RuntimeError):
                asyncio.run(rec.run())
            R.coins(raw, [market("xyz:GOLD", 6e6)], MAPPED, 100)
            sent = []
            rec = R.Hip3Recorder(raw, markets=lambda: 1 / 0, mapped=MAPPED,
                                 connect=lambda url, **kw: FakeSocket([], sent), clock=lambda: T0, free=lambda p: 100.0)
            self.run_once(rec)
            self.assertEqual(sent[0]["subscription"], {"type": "trades", "coin": "xyz:GOLD"})

    def test_under_the_free_space_floor_only_trades_are_asked_for(self):
        sent = []
        with tempfile.TemporaryDirectory() as d:
            rec = R.Hip3Recorder(Path(d), markets=lambda: [market("xyz:NVDA", 7e8)], mapped=MAPPED,
                                 connect=lambda url, **kw: FakeSocket([], sent), clock=lambda: T0,
                                 free=lambda p: rr.FREE_FLOOR_GB - 1)
            self.run_once(rec)
            self.assertEqual([m["subscription"]["type"] for m in sent[:1]], ["trades"])
            self.assertNotIn("l2Book", [m["subscription"]["type"] for m in sent])


if __name__ == "__main__":
    unittest.main()
