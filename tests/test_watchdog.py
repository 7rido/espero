"""The silence alarm, on temporary folders and fake clocks: it reads no real recorder and notifies no one."""
import contextlib
import io
import json
import os
import re
import socket
import struct
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest import mock

from espero import watchdog as W

NOW = 1_800_000_000.0


def touch(path: Path, mtime: float) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"x")
    os.utime(path, (mtime, mtime))


class TestNewest(unittest.TestCase):
    def test_the_latest_day_folder_and_every_other_branch(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            touch(root / "2026-11-01" / "a.csv.gz", NOW - 90_000)
            touch(root / "2026-11-02" / "b.csv.gz", NOW - 100)
            touch(root / "MANIFEST.sha256", NOW)                            # not data
            self.assertEqual(W.newest_mtime(root), NOW - 100)
            touch(root / "BTC" / "2026-11-02" / "c.csv.gz", NOW - 50)        # a currency branch, as deribit's
            self.assertEqual(W.newest_mtime(root), NOW - 50)
            self.assertIsNone(W.newest_mtime(root / "missing"))

    def test_an_older_day_is_not_read_when_a_later_one_exists(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            touch(root / "2026-11-01" / "late-write.csv.gz", NOW)
            touch(root / "2026-11-02" / "b.csv.gz", NOW - 500)
            self.assertEqual(W.newest_mtime(root), NOW - 500)


class TestChecks(unittest.TestCase):
    def test_ages_against_their_allowance(self):
        self.assertTrue(W.check_age("x", NOW - 120, 120, NOW).ok)
        self.assertFalse(W.check_age("x", NOW - 121, 120, NOW).ok)
        self.assertEqual(W.check_age("x", None, 120, NOW).note, "nothing recorded")

    def test_recorders_and_raw_venues(self):
        ages = {"hlcollect/ctx": NOW - 100, "hlbook": NOW - 1_000, "deribit": NOW - 10,
                "binance": NOW - 30, "okx": NOW - 500}
        checks = W.check_recorders(NOW, Path("/d"), Path("/r"), venues=("binance", "okx"),
                                   mtime=lambda p: ages.get(str(p).split("/d/")[-1].split("/r/")[-1]))
        got = {c.name: c.ok for c in checks}
        self.assertEqual(got, {"recorder:hlcollect": True, "recorder:hlbook": False, "recorder:deribit": True,
                               "rawrec:binance": True, "rawrec:okx": False})

    def test_the_daily_run_fresh_stale_or_failed(self):
        with tempfile.TemporaryDirectory() as d:
            state = Path(d)
            self.assertFalse(W.check_daily(NOW, state).ok)
            stamp = time.strftime("%Y-%m-%dT%H:%M:%S+00:00", time.gmtime(NOW - 3600))
            (state / "health.json").write_text(json.dumps({"last_run": stamp, "ok": True, "steps": {}}))
            self.assertTrue(W.check_daily(NOW, state).ok)
            (state / "health.json").write_text(json.dumps({"last_run": stamp, "ok": False,
                                                           "steps": {"liqfwd": {"ok": False}}}))
            c = W.check_daily(NOW, state)
            self.assertFalse(c.ok)
            self.assertIn("liqfwd", c.note)
            old = time.strftime("%Y-%m-%dT%H:%M:%S+00:00", time.gmtime(NOW - 27 * 3600))
            (state / "health.json").write_text(json.dumps({"last_run": old, "ok": True}))
            self.assertFalse(W.check_daily(NOW, state).ok)

    def test_agents_by_launchds_own_word(self):
        states = {"a": "running", "b": "not loaded", "c": "waiting"}
        got = {c.name: c.ok for c in W.check_agents(lambda label: states[label], agents=("a", "b", "c"))}
        self.assertEqual(got, {"agent:a": True, "agent:b": False, "agent:c": False})

    def test_every_always_on_launchd_template_is_watched(self):
        templates = sorted((Path(W.__file__).resolve().parents[1] / "deploy" / "launchd").glob("*.plist.template"))
        self.assertTrue(templates)
        for p in templates:
            if not re.search(r"<key>KeepAlive</key>\s*<true/>", p.read_text(encoding="utf-8")):
                continue                                                 # the timed jobs are judged by their output
            label = p.name.removesuffix(".plist.template")               # carry's becomes carry-maker, carry-taker
            self.assertTrue(any(a == label or a.startswith(label + "-") for a in W.AGENTS), label)

    def test_disk_floor(self):
        self.assertTrue(W.check_disk(Path("/"), free_gb=lambda p: 31.0).ok)
        self.assertFalse(W.check_disk(Path("/"), free_gb=lambda p: 29.0).ok)
        self.assertTrue(W.check_disk(Path("/"), free_gb=lambda p: 30.0).ok)


class TestClock(unittest.TestCase):
    def test_warn_then_refuse(self):
        self.assertTrue(W.check_clock(lambda: 0.1).ok)
        warn = W.check_clock(lambda: -0.3)
        self.assertEqual((warn.ok, warn.severity), (False, "warn"))
        refuse = W.check_clock(lambda: 1.5)
        self.assertEqual((refuse.ok, refuse.severity), (False, "refuse trading"))
        self.assertTrue(W.clock_ok(-1.0) and not W.clock_ok(1.01))
        self.assertEqual(W.check_clock(lambda: 1.0).severity, "warn")              # a second is still a warning
        self.assertTrue(W.check_clock(lambda: 0.25).ok)

    def test_no_answer_is_a_warning_not_a_crash(self):
        def silent():
            raise socket.timeout("no answer")
        self.assertEqual(W.check_clock(silent).severity, "warn")

    def test_the_sntp_answer_is_read_right(self):
        srv = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        srv.bind(("127.0.0.1", 0))
        port = srv.getsockname()[1]

        def answer():
            data, addr = srv.recvfrom(48)
            t = time.time() + 2.0                                            # the server runs two seconds ahead
            secs = int(t) + 2_208_988_800
            frac = int((t % 1) * 2 ** 32)
            srv.sendto(b"\x24" + 39 * b"\0" + struct.pack("!II", secs, frac), addr)
        th = threading.Thread(target=answer)
        th.start()
        try:
            off = W.sntp_offset("127.0.0.1", timeout=2.0, port=port)
        finally:
            th.join()
            srv.close()
        self.assertAlmostEqual(off, -2.0, delta=0.1)


class TestEscalation(unittest.TestCase):
    def failing(self, name="rawrec:okx"):          # not `fail`: that is TestCase's own, which raises
        return [W.Check(name, False, "newest 500 s ago")]

    def test_screen_at_once_webhook_after_ten_minutes_both_every_hour(self):
        sends, st = W.escalate(self.failing(), {}, NOW)
        self.assertEqual([s[0] for s in sends], ["macos"])
        sends, st = W.escalate(self.failing(), st, NOW + 599)
        self.assertEqual(sends, [])
        sends, st = W.escalate(self.failing(), st, NOW + 600)
        self.assertEqual([s[0] for s in sends], ["webhook"])
        sends, st = W.escalate(self.failing(), st, NOW + 3_599)
        self.assertEqual(sends, [])
        sends, st = W.escalate(self.failing(), st, NOW + 3_600)
        self.assertEqual(sorted(s[0] for s in sends), ["macos", "webhook"])

    def test_an_acknowledged_alarm_is_quiet_until_it_recovers(self):
        _, st = W.escalate(self.failing(), {}, NOW)
        self.assertTrue(W.ack(st, "rawrec:okx"))
        self.assertFalse(W.ack(st, "nope"))
        sends, st = W.escalate(self.failing(), st, NOW + 7_200)
        self.assertEqual(sends, [])
        sends, st = W.escalate([W.Check("rawrec:okx", True, "ok")], st, NOW + 7_300)
        self.assertEqual([s[1] for s in sends], ["recovered: rawrec:okx"])
        self.assertEqual(st, {})

    def test_a_healthy_check_says_nothing(self):
        self.assertEqual(W.escalate([W.Check("disk", True, "ok")], {}, NOW), ([], {}))


class TestOnce(unittest.TestCase):
    def test_a_pass_checks_notifies_and_remembers(self):
        with tempfile.TemporaryDirectory() as d:
            state, data = Path(d) / "state", Path(d) / "data"
            state.mkdir()
            touch(data / "hlcollect" / "ctx" / "2026-11-02" / "a.csv.gz", NOW - 10)
            sent = []
            with contextlib.redirect_stdout(io.StringIO()):
                rc = W.once(state, data, None, clock=False, now=NOW, send=lambda *a: sent.append(a),
                            state_of=lambda label: "running")
            self.assertEqual(rc, 1)                                  # no health.json, no hlbook, no deribit
            memory = json.loads((state / W.STATE).read_text())
            self.assertIn("daily", memory["alarms"])
            self.assertTrue(any("daily" in s[1] for s in sent))

    def test_a_failing_notification_never_fails_the_check(self):
        with tempfile.TemporaryDirectory() as d:
            state = Path(d)

            def broken(*a):
                raise RuntimeError("webhook down")
            with contextlib.redirect_stdout(io.StringIO()):
                rc = W.once(state, Path(d) / "data", None, clock=False, now=NOW, send=broken,
                            state_of=lambda label: "running")
            self.assertEqual(rc, 1)


class TestDrill(unittest.TestCase):
    def test_missing_collector_slots_are_counted(self):
        with tempfile.TemporaryDirectory() as d:
            data = Path(d)
            since = 1_793_577_600.0                                  # 2026-11-02 00:00 UTC
            for k in range(1, 13):
                if k in (4, 5, 6):                                   # 15 minutes lost in the drill
                    continue
                t = time.gmtime(since + 300 * k)
                touch(data / "hlcollect" / "ctx" / time.strftime("%Y-%m-%d", t) / time.strftime("%H%M.csv.gz", t),
                      since + 300 * k)
            r = W.drill_report(since, since + 3_900, data, None)["recorder:hlcollect"]
            self.assertEqual((r["expected_slots"], r["missing_slots"], r["lost_s"]), (12, 3, 900.0))
            self.assertEqual(r["first_missing"], ["2026-11-02 0020"])


class TestMain(unittest.TestCase):
    def test_a_check_loads_the_repo_s_env_for_the_webhook_and_reading_the_status_does_not(self):
        loaded = []
        with (tempfile.TemporaryDirectory() as d, contextlib.redirect_stdout(io.StringIO()),
              mock.patch("espero.broker.load_env", side_effect=lambda path=".env": loaded.append(path)),
              mock.patch.object(W, "once", return_value=0) as once):
            self.assertEqual(W.main(["--status", "--state-dir", d]), 0)
            self.assertEqual(loaded, [])                                 # reading sends nothing, so loads nothing
            self.assertEqual(W.main(["--once", "--no-clock", "--state-dir", d]), 0)
            self.assertEqual(loaded, [str(W.ROOT / ".env")])             # launchd gives the process no .env
            once.assert_called_once()


if __name__ == "__main__":
    unittest.main()
