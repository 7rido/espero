"""The raw recorder against fake sockets: the folder guard, the line format, append-on-restart as a second
zstd frame, a truncated frame read as far as it goes, channels named from each venue's frame, gaps read
from the tape, manifests only into closed days, and the coin lists frozen then appended."""
from __future__ import annotations

import asyncio
import json
import os
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from espero import manifest
from espero import rawrec as rr

try:
    import zstandard  # noqa: F401
    HAVE_ZSTD = True
except ImportError:
    HAVE_ZSTD = False

T0 = 1_793_600_000_000      # 2026-11-02 06:13:20 UTC


class TestWhere(unittest.TestCase):
    def test_unset_is_refused(self):
        with self.assertRaises(RuntimeError):
            rr.raw_dir(env={})

    def test_inside_the_repos_data_is_refused(self):
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp)
            (project / "data").mkdir()
            with self.assertRaises(RuntimeError):
                rr.raw_dir(env={rr.ENV: str(project / "data" / "raw")}, project=project)
            with self.assertRaises(RuntimeError):
                rr.raw_dir(env={rr.ENV: str(project / "data")}, project=project)
            self.assertEqual(rr.raw_dir(env={rr.ENV: str(project / "raw")}, project=project),
                             (project / "raw").resolve())

    def test_hour_file_is_named_by_utc_hour(self):
        self.assertEqual(rr.hour_path(Path("/r"), "okx", T0), Path("/r/okx/2026-11-02/06.ndjson.zst"))


class TestLine(unittest.TestCase):
    def test_frame_is_embedded_verbatim(self):
        frame = b'{"topic":"publicTrade.BTCUSDT","data":[{"p":"1.50","v":"2"}]}'
        got = json.loads(rr.line(T0, "publicTrade", "BTCUSDT", frame))
        self.assertEqual(got, {"rt": T0, "ch": "publicTrade", "s": "BTCUSDT",
                               "d": {"topic": "publicTrade.BTCUSDT", "data": [{"p": "1.50", "v": "2"}]}})
        self.assertIn(b'"d":' + frame + b"}", rr.line(T0, "publicTrade", "BTCUSDT", frame))

    def test_classify_names_each_venues_frames(self):
        cases = [
            ("bybit", b'{"topic":"orderbook.50.BTCUSDT","type":"delta","data":{}}', ("orderbook.50", "BTCUSDT")),
            ("bybit", b'{"topic":"allLiquidation.ETHUSDT","data":[]}', ("allLiquidation", "ETHUSDT")),
            ("bybit", b'{"success":true,"op":"subscribe"}', ("_ctrl", "")),
            ("okx", b'{"arg":{"channel":"books","instId":"BTC-USDT-SWAP"},"data":[]}', ("books", "BTC-USDT-SWAP")),
            ("okx", b'{"arg":{"channel":"liquidation-orders","instType":"SWAP"},"data":[]}',
             ("liquidation-orders", "SWAP")),
            ("okx", b'{"event":"subscribe","arg":{"channel":"trades","instId":"X"}}', ("_ctrl", "")),
            ("hyperliquid", b'{"channel":"trades","data":[{"coin":"BTC","px":"1"}]}', ("trades", "BTC")),
            ("hyperliquid", b'{"channel":"l2Book","data":{"coin":"ETH","levels":[[],[]]}}', ("l2Book", "ETH")),
            ("hyperliquid_testnet", b'{"channel":"pong"}', ("_ctrl", "")),
            ("binance", b'{"stream":"btcusdt@depth@100ms","data":{}}', ("depth@100ms", "BTCUSDT")),
            ("binance", b'{"result":null,"id":1}', ("_ctrl", "")),
            ("okx", b"pong", ("_ctrl", "")),
            ("coinbase", b'{"type":"match","product_id":"BTC-USD","side":"sell"}', ("match", "BTC-USD")),
            ("coinbase", b'{"type":"l2update","product_id":"HYPE-USD","changes":[]}', ("l2update", "HYPE-USD")),
            ("coinbase", b'{"type":"heartbeat","product_id":"BTC-USD"}', ("_ctrl", "")),
            ("coinbase", b'{"type":"ticker","product_id":"BTC-USD","best_bid":"1"}', ("ticker", "BTC-USD")),
            ("coinbase", b'{"type":"subscriptions","channels":[]}', ("_ctrl", "")),
        ]
        self.assertEqual(json.loads(rr.line(T0, "_ctrl", "", b"pong"))["d"], "pong", "a text frame stays valid JSON")
        self.assertEqual(rr.listed_only("hyperliquid_testnet", ["HYPE", "UNI"], ["HYPE", "BTC"]), (["HYPE"], ["UNI"]))
        self.assertEqual(rr.listed_only("hyperliquid", ["HYPE", "UNI"], None), (["HYPE", "UNI"], []))
        self.assertEqual(rr.listed_only("bybit", ["X"], ["Y"]), (["X"], []))
        for venue, frame, want in cases:
            with self.subTest(venue=venue, frame=frame):
                self.assertEqual(rr.classify(venue, frame), want)


@unittest.skipUnless(HAVE_ZSTD, "needs zstandard")
class TestFiles(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.raw = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_lines_round_trip_and_roll_over_at_the_hour(self):
        w = rr.HourWriter(self.raw, "okx")
        w.write(rr.line(T0, "trades", "A", b'{"n":1}'))
        w.write(rr.line(T0 + 1, "trades", "A", b'{"n":2}'))
        w.write(rr.line(T0 + 3_600_000, "trades", "A", b'{"n":3}'))
        w.close()
        files = sorted(p.relative_to(self.raw).as_posix() for p in self.raw.rglob("*" + rr.SUFFIX))
        self.assertEqual(files, ["okx/2026-11-02/06.ndjson.zst", "okx/2026-11-02/07.ndjson.zst"])
        got = [r["d"]["n"] for r in rr.read_day(self.raw, "okx", "2026-11-02")]
        self.assertEqual(got, [1, 2, 3])

    def test_restart_appends_a_second_frame_that_reads_back_in_order(self):
        for n in (1, 2):
            w = rr.HourWriter(self.raw, "bybit")
            w.write(rr.line(T0 + n, "publicTrade", "B", json.dumps({"n": n}).encode()))
            w.close()
        path = rr.hour_path(self.raw, "bybit", T0)
        self.assertEqual([r["d"]["n"] for r in rr.read_lines(path)], [1, 2])
        with path.open("rb") as fh:
            self.assertEqual(fh.read().count(b"\x28\xb5\x2f\xfd"), 2, "two sessions, two zstd frames")

    def test_a_truncated_last_frame_reads_as_far_as_it_goes(self):
        w = rr.HourWriter(self.raw, "bybit")
        for n in range(200):
            w.write(rr.line(T0 + n, "publicTrade", "B", json.dumps({"n": n, "pad": "x" * 50}).encode()))
            if n % 50 == 49:
                w.flush()                       # the loop flushes a block every second
        path = rr.hour_path(self.raw, "bybit", T0)
        w._fh.close()                           # a crash: the frame never gets its end
        data = path.read_bytes()
        path.write_bytes(data[: len(data) - 7])
        recs = list(rr.read_lines(path))
        self.assertTrue(recs[-1].get("truncated"))
        self.assertGreaterEqual(len(recs), 151, "every block but the one being written survives")
        self.assertEqual([r["d"]["n"] for r in recs[:-1]], list(range(len(recs) - 1)))

    def test_a_killed_session_does_not_hide_the_next_one(self):
        w = rr.HourWriter(self.raw, "bybit")
        for n in range(100):
            w.write(rr.line(T0 + n, "publicTrade", "B", json.dumps({"n": n, "pad": "x" * 50}).encode()))
            if n == 49:
                w.flush()
        w.flush()
        path = rr.hour_path(self.raw, "bybit", T0)
        w._fh.close()                               # killed: no frame end
        data = path.read_bytes()
        path.write_bytes(data[: len(data) - 7])
        w2 = rr.HourWriter(self.raw, "bybit")      # launchd's next session appends its own frame
        for n in range(100, 110):
            w2.write(rr.line(T0 + n, "publicTrade", "B", json.dumps({"n": n}).encode()))
        w2.close()
        recs = list(rr.read_lines(path))
        ns = [r["d"]["n"] for r in recs if "d" in r]
        self.assertEqual(ns[:50], list(range(50)))
        self.assertEqual(ns[-10:], list(range(100, 110)), "the second session's frame is read after the cut")
        self.assertEqual(sum(1 for r in recs if r.get("truncated")), 1)

    def test_sigterm_closes_the_frame(self):
        import os
        import signal
        import threading

        class Quick(rr.Recorder):
            async def _run(self):
                self.writers["okx"].write(rr.line(T0, "trades", "A", b"{}"))
                await asyncio.sleep(30)
        rec = Quick(self.raw, state=self.raw / "nostate")
        threading.Timer(0.3, lambda: os.kill(os.getpid(), signal.SIGTERM)).start()
        with mock.patch.object(rr, "Recorder", lambda raw, state=None: rec):
            self.assertEqual(rr.main_loop(self.raw), 0)
        recs = list(rr.read_lines(rr.hour_path(self.raw, "okx", T0)))
        self.assertEqual([r.get("ch") for r in recs], ["trades"], "the frame got its end: no truncated marker")

    def test_gaps_come_from_the_tape(self):
        w = rr.HourWriter(self.raw, "okx")
        day0 = T0 - T0 % 86_400_000
        for rt in (day0 + 10_000, day0 + 70_000, day0 + 500_000, day0 + 560_000):
            w.write(rr.meta(rt, "heartbeat"))
        w.close()
        got = rr.gaps(self.raw, "okx", "2026-11-02", max_silence_s=120, now_ms=day0 + 1_000_000)
        self.assertEqual(got, [(day0 + 70_000, day0 + 500_000), (day0 + 560_000, day0 + 1_000_000)])

    def test_manifests_go_only_into_closed_days(self):
        w = rr.HourWriter(self.raw, "okx")
        w.write(rr.line(T0, "trades", "A", b"{}"))
        w.write(rr.line(T0 + 86_400_000, "trades", "A", b"{}"))
        w.close()
        written = rr.write_manifests(self.raw, today="2026-11-03")
        self.assertEqual([p.parent.name for p in written], ["2026-11-02"])
        self.assertTrue((self.raw / "okx" / "2026-11-02" / manifest.NAME).exists())
        self.assertFalse((self.raw / "okx" / "2026-11-03" / manifest.NAME).exists())
        self.assertEqual(rr.write_manifests(self.raw, today="2026-11-03"), [], "nothing new, nothing rewritten")
        self.assertEqual(manifest.check(self.raw / "okx" / "2026-11-02")["ok"], 1)

    def test_status_counts_files_and_the_last_clock_only(self):
        w = rr.HourWriter(self.raw, "hyperliquid")
        w.write(rr.line(T0, "trades", "BTC", b'{"px":"99"}'))
        w.write(rr.line(T0 + 5, "trades", "BTC", b'{"px":"100"}'))
        w.close()
        s = rr.status(self.raw, ["hyperliquid"])
        self.assertEqual(s["hyperliquid"]["2026-11-02"]["files"], 1)
        self.assertEqual(s["hyperliquid"]["2026-11-02"]["last_rt"], T0 + 5)
        self.assertNotIn("px", json.dumps(s))


class TestCoins(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.raw = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_plan_puts_each_coin_on_the_venues_that_list_it(self):
        coins = {"BTC": {"price": [], "all": ["BINANCE_FUTURES:btcusdt", "BYBIT:BTCUSDT", "OKEX:BTC-USDT-SWAP"]},
                 "SHIB": {"price": [], "all": ["OKEX:SHIB-USDT-SWAP"]}}
        p = rr.plan(coins, hl_extra=["HYPE"], testnet=["HYPE"], coinbase=["HYPE"])
        self.assertEqual(p, {"bybit": ["BTCUSDT"], "okx": ["BTC-USDT-SWAP", "SHIB-USDT-SWAP"],
                             "hyperliquid": ["BTC", "HYPE", "kSHIB"], "hyperliquid_testnet": ["HYPE"],
                             "binance": ["BTCUSDT"], "coinbase": ["BTC-USD", "ETH-USD", "HYPE-USD"]})

    def test_book_coins_read_the_journals_read_only(self):
        state = self.raw / "state"
        state.mkdir()
        con = sqlite3.connect(state / "carry-maker.db")
        con.execute("CREATE TABLE positions (coin TEXT, exit_ts INTEGER)")
        con.executemany("INSERT INTO positions VALUES (?, ?)", [("HYPE", None), ("OLD", 5), ("ZRO", None)])
        con.commit()
        con.close()
        con = sqlite3.connect(state / "paper-btc-usd-hl.db")
        con.execute("CREATE TABLE bars (product TEXT)")
        con.execute("INSERT INTO bars VALUES ('BTC-USD')")
        con.commit()
        con.close()
        self.assertEqual(rr.book_coins(state), {"carry": ["HYPE", "ZRO"], "paper": ["BTC"]})
        self.assertEqual(rr.book_coins(self.raw / "nowhere"), {"carry": [], "paper": []})

    def test_coin_lists_are_frozen_then_only_appended(self):
        base = {"hyperliquid": ["BTC"], "hyperliquid_testnet": []}
        doc = rr.coins_file(self.raw, base, now=100)
        later = rr.coins_file(self.raw, {"hyperliquid": ["ETH"]}, now=200)
        self.assertEqual(later["venues"]["hyperliquid"], ["BTC"], "a later start reads the frozen list")
        self.assertEqual(rr.add_coins(self.raw, doc, "hyperliquid", ["BTC", "HYPE"], now=300), ["HYPE"])
        again = json.loads((self.raw / "coins.json").read_text())
        self.assertEqual(again["venues"]["hyperliquid"], ["BTC", "HYPE"])
        self.assertEqual(again["added"], {"hyperliquid:HYPE": 300})
        self.assertEqual(rr.add_coins(self.raw, doc, "hyperliquid", ["HYPE"], now=400), [])

    def test_a_venue_added_after_the_file_was_frozen_joins_from_the_plan(self):
        rr.coins_file(self.raw, {"hyperliquid": ["BTC"]}, now=100)              # frozen before coinbase existed
        rec = rr.Recorder(self.raw, state=self.raw / "nostate")
        lists = rec.lists()
        self.assertIn("BTC-USD", lists["coinbase"])
        again = json.loads((self.raw / "coins.json").read_text())
        self.assertIn("coinbase:BTC-USD", again["added"])
        self.assertEqual(again["venues"]["hyperliquid"], ["BTC"], "the frozen lists stay frozen")


class TestSubscriptions(unittest.TestCase):
    def test_each_venue_asks_for_trades_books_and_liquidations(self):
        by = [json.loads(m) for m in rr.bybit_subscribe(["BTCUSDT"] * 1)]
        self.assertEqual(by[0]["args"], ["publicTrade.BTCUSDT", "allLiquidation.BTCUSDT", "orderbook.50.BTCUSDT"])
        self.assertTrue(all(len(m["args"]) <= 10 for m in [json.loads(x) for x in rr.bybit_subscribe(["A%d" % i for i in range(9)])]))
        ok = [json.loads(m) for m in rr.okx_subscribe(["BTC-USDT-SWAP"])]
        self.assertEqual(ok[0]["args"], [{"channel": "liquidation-orders", "instType": "SWAP"},
                                         {"channel": "trades", "instId": "BTC-USDT-SWAP"},
                                         {"channel": "books", "instId": "BTC-USDT-SWAP"}])
        hl = [json.loads(m) for m in rr.hl_subscribe(["BTC"])]
        self.assertEqual([m["subscription"]["type"] for m in hl], ["trades", "l2Book"])
        self.assertEqual(rr.binance_url(["BTCUSDT"]), rr.BINANCE_WS + "btcusdt@trade/btcusdt@aggTrade/btcusdt@depth@100ms/"
                         "btcusdt@depth20@100ms/btcusdt@forceOrder/btcusdt@markPrice@1s/btcusdt@bookTicker")
        self.assertEqual(rr.Feed("binance", ["BTCUSDT"], None).subscriptions(), [],
                         "Binance refuses a subscribe message: its streams are in the URL")
        self.assertEqual(rr.classify("binance", b'{"stream":"btcusdt@depth20@100ms","data":{}}'),
                         ("depth20@100ms", "BTCUSDT"))
        self.assertNotIn("depth", rr.binance_url(["BTCUSDT"], books=False))
        self.assertNotIn("orderbook", "".join(rr.bybit_subscribe(["BTCUSDT"], books=False)))
        cb = json.loads(rr.coinbase_subscribe(["BTC-USD", "HYPE-USD"])[0])
        self.assertEqual(cb, {"type": "subscribe", "product_ids": ["BTC-USD", "HYPE-USD"],
                              "channels": ["matches", "heartbeat", "ticker", "level2_batch"]})
        self.assertNotIn("level2", "".join(rr.coinbase_subscribe(["BTC-USD"], books=False)))
        self.assertEqual(rr.Feed("coinbase", ["BTC-USD"], None).url(), rr.COINBASE_WS)


class FakeSocket:
    """A websocket that serves canned frames, then closes."""

    def __init__(self, frames, log):
        self.frames, self.log = list(frames), log

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def send(self, msg):
        self.log.append(json.loads(msg) if msg.startswith("{") else msg)

    def __aiter__(self):
        return self

    async def __anext__(self):
        if not self.frames:
            raise StopAsyncIteration
        return self.frames.pop(0)

    async def recv(self):
        if not self.frames:
            raise asyncio.TimeoutError
        return self.frames.pop(0)


@unittest.skipUnless(HAVE_ZSTD, "needs zstandard")
class TestFeed(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.raw = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_a_session_subscribes_then_records_every_frame_with_its_channel(self):
        sent, calls = [], []
        frames = ['{"success":true,"op":"subscribe"}',
                  '{"topic":"publicTrade.BTCUSDT","data":[{"p":"1"}]}',
                  '{"topic":"orderbook.50.BTCUSDT","type":"snapshot","data":{"b":[],"a":[]}}']

        def connect(url, **kw):
            calls.append(url)
            return FakeSocket(frames, sent)

        import itertools
        clock = itertools.count(T0)
        w = rr.HourWriter(self.raw, "bybit")
        feed = rr.Feed("bybit", ["BTCUSDT"], w, connect=connect, clock=lambda: next(clock))

        async def one_session():
            task = asyncio.create_task(feed.run())
            await asyncio.sleep(0.05)
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
        asyncio.run(one_session())
        w.close()
        self.assertEqual(calls[0], rr.BYBIT_WS)
        self.assertEqual(sent[0]["args"], ["publicTrade.BTCUSDT", "allLiquidation.BTCUSDT", "orderbook.50.BTCUSDT"])
        recs = list(rr.read_day(self.raw, "bybit", "2026-11-02"))
        self.assertEqual([(r["ch"], r["s"]) for r in recs[:4]],
                         [("_meta", ""), ("_ctrl", ""), ("publicTrade", "BTCUSDT"), ("orderbook.50", "BTCUSDT")])
        self.assertEqual(recs[4]["d"]["ev"], "closed", "the end of a session is on the tape")
        self.assertEqual(recs[0]["d"]["ev"], "open")
        self.assertEqual(recs[2]["d"]["data"], [{"p": "1"}])

    def test_under_the_floor_book_frames_are_dropped_and_trades_kept(self):
        flag = {"books": True}
        w = rr.HourWriter(self.raw, "okx")
        feed = rr.Feed("okx", ["BTC-USDT-SWAP"], w, clock=lambda: T0, books_on=lambda: flag["books"])
        feed.record(b'{"arg":{"channel":"books","instId":"BTC-USDT-SWAP"},"data":[]}')
        flag["books"] = False
        feed.record(b'{"arg":{"channel":"books","instId":"BTC-USDT-SWAP"},"data":[]}')
        feed.record(b'{"arg":{"channel":"trades","instId":"BTC-USDT-SWAP"},"data":[]}')
        w.close()
        self.assertEqual([r["ch"] for r in rr.read_day(self.raw, "okx", "2026-11-02")], ["books", "trades"])
        self.assertEqual(feed.dropped, 1)
        bn = rr.Feed("binance", ["BTCUSDT"], w, books_on=lambda: False)
        for ch in ("bookTicker", "depth@100ms", "depth20@100ms"):
            bn.record(('{"stream":"btcusdt@%s","data":{}}' % ch).encode())
        self.assertEqual(bn.dropped, 3)

    def test_a_second_recorder_on_the_same_tape_is_refused(self):
        from espero.lock import JournalBusy, JournalLock
        ran = []

        async def fake_run(self_):
            ran.append(True)
        rec = rr.Recorder(self.raw, state=self.raw / "nostate")
        rec._run = fake_run.__get__(rec)
        with JournalLock(self.raw / "rawrec"):
            with self.assertRaises(JournalBusy):
                asyncio.run(rec.run())
        self.assertEqual(ran, [], "nothing ran while the lock was held")
        asyncio.run(rec.run())
        self.assertEqual(ran, [True], "the lock freed, the recorder runs")
        with open(self.raw / "rawrec.lock") as f:
            self.assertTrue(f.read().strip().isdigit())

    def test_bybit_snapshot_keeps_only_the_snapshot_frame_per_symbol(self):
        sent = []
        frames = ['{"success":true}', '{"topic":"orderbook.50.BTCUSDT","type":"delta","data":{}}',
                  '{"topic":"orderbook.50.BTCUSDT","type":"snapshot","data":{"b":[["1","2"]]}}']
        w = rr.HourWriter(self.raw, "bybit")
        got = asyncio.run(rr.bybit_snapshots(["BTCUSDT"], w, connect=lambda url, **kw: FakeSocket(frames, sent),
                                             clock=lambda: T0, timeout=1.0))
        w.close()
        self.assertEqual(got, 1)
        recs = list(rr.read_day(self.raw, "bybit", "2026-11-02"))
        self.assertEqual([r["ch"] for r in recs], ["_meta", "orderbook.50"])
        self.assertEqual(recs[1]["d"]["type"], "snapshot")


class TestInstaller(unittest.TestCase):
    def test_plist_runs_the_loop_with_the_raw_folder_from_the_environment(self):
        import plistlib
        import shutil
        import subprocess
        if not (shutil.which("bash") and shutil.which("sed")):
            self.skipTest("needs bash and sed")
        root = Path(__file__).resolve().parents[1]
        env = {"PATH": "/usr/bin:/bin", "HOME": "/tmp", "PYTHON": "/x/python", rr.ENV: "/somewhere/raw"}
        out = subprocess.run(["bash", str(root / "scripts" / "install-rawrec-launchd.sh"), "--print"],
                             capture_output=True, text=True, check=True, env=env).stdout
        p = plistlib.loads(out.encode())
        self.assertEqual(p["Label"], "com.espero.rawrec")
        self.assertEqual(p["ProgramArguments"], ["/x/python", "-m", "espero", "rawrec", "--loop"])
        self.assertEqual(p["EnvironmentVariables"][rr.ENV], "/somewhere/raw")
        self.assertEqual(p["WorkingDirectory"], str(root))
        self.assertTrue(p["KeepAlive"] and p["RunAtLoad"])
        self.assertNotIn("pgrep", (root / "scripts" / "install-rawrec-launchd.sh").read_text(),
                         "the lock in the module, not a process name, keeps the tape to one writer")
        r = subprocess.run(["bash", str(root / "scripts" / "install-rawrec-launchd.sh"), "--print"],
                           capture_output=True, text=True, env={k: v for k, v in env.items() if k != rr.ENV})
        self.assertNotEqual(r.returncode, 0, "no ESPERO_RAW_DIR, no agent")
        r = subprocess.run(["bash", str(root / "scripts" / "install-rawrec-launchd.sh"), "--print"],
                           capture_output=True, text=True, env={**env, rr.ENV: str(root / "data" / "raw")})
        self.assertNotEqual(r.returncode, 0, "a folder under data/ is refused")


if __name__ == "__main__":
    unittest.main()
