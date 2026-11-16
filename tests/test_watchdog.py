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
            off, rtt = W.sntp_sample("127.0.0.1", timeout=2.0, port=port)
        finally:
            th.join()
            srv.close()
        self.assertAlmostEqual(off, -2.0, delta=0.1)
        self.assertTrue(0 <= rtt < 1.0)                                      # a local round trip, never negative

    def test_the_shortest_round_trip_is_trusted_and_a_lost_sample_is_not_fatal(self):
        slept = []
        samples = iter([(-5.9, 1.8), (-0.01, 0.04), (-2.5, 0.9)])
        with mock.patch.object(W, "sntp_sample", lambda *a, **k: next(samples)):
            self.assertEqual(W.sntp_offset(gap=0.1, sleep=slept.append), -0.01)
        self.assertEqual(slept, [0.1, 0.1])                                  # between samples, not after the last
        mixed = iter([OSError("lost"), (0.2, 0.5), (0.3, 0.5)])
        def next_or_raise(*a, **k):
            v = next(mixed)
            if isinstance(v, OSError):
                raise v
            return v
        with mock.patch.object(W, "sntp_sample", next_or_raise):
            self.assertEqual(W.sntp_offset(sleep=lambda s: None), 0.2)       # the first of two equal trips
        def lost(*a, **k):
            raise socket.timeout("none")
        with mock.patch.object(W, "sntp_sample", lost):
            with self.assertRaises(OSError):
                W.sntp_offset(sleep=lambda s: None)
        self.assertEqual(W.SNTP_SAMPLES, 3)


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

    def test_the_ack_command_keeps_the_last_checks(self):
        """`--ack` rewrote watchdog.json with no checks, so --status showed none until the next pass."""
        with tempfile.TemporaryDirectory() as d:
            state = Path(d)
            checks = [W.Check("rawrec:okx", False, "newest 900 s ago", 900.0, 120.0)]
            W.write_state(state, checks, {"rawrec:okx": {"since": 1.0, "macos": 1.0, "webhook": None,
                                                         "acked": False}}, 2.0)
            self.assertEqual(W.main(["--ack", "rawrec:okx", "--state-dir", d]), 0)
            doc = json.loads((state / W.STATE).read_text())
            self.assertTrue(doc["alarms"]["rawrec:okx"]["acked"])
            self.assertEqual([c["name"] for c in doc["checks"]], ["rawrec:okx"])

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


class TestLivesig(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.state = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def beat(self, started, written, tape):
        hb = {"started_ms": started * 1000, "written_ms": written * 1000,
              "tape_ms": None if tape is None else tape * 1000}
        (self.state / W.LIVESIG_HEARTBEAT).write_text(json.dumps(hb))

    def ok(self, tape_newest):
        return W.check_livesig(NOW, self.state, tape_newest).ok

    def test_the_file_is_the_one_the_engine_writes(self):
        from espero import livesig
        self.assertEqual(W.LIVESIG_HEARTBEAT, livesig.HEARTBEAT)

    def test_no_heartbeat_is_an_engine_from_before_it_and_no_alarm(self):
        self.assertTrue(self.ok(NOW))

    def test_an_unreadable_heartbeat_is_an_alarm(self):
        (self.state / W.LIVESIG_HEARTBEAT).write_text("{")
        self.assertFalse(self.ok(NOW))

    def test_a_start_has_fifteen_minutes(self):
        self.beat(NOW - 900, NOW - 900, None)
        self.assertTrue(self.ok(NOW))
        self.beat(NOW - 901, NOW - 901, None)
        self.assertFalse(self.ok(NOW))

    def test_a_loop_that_stops_reporting_is_stuck_or_gone(self):
        self.beat(NOW - 3_600, NOW - 601, NOW - 601)
        self.assertFalse(self.ok(None))                                  # with no tape to compare, too
        self.beat(NOW - 3_600, NOW - 600, NOW - 30)
        self.assertTrue(self.ok(NOW - 1))

    def test_an_engine_behind_a_tape_being_written_is_stuck(self):
        self.beat(NOW - 3_600, NOW - 10, NOW - 601)
        self.assertFalse(self.ok(NOW - 1))
        self.assertFalse(self.ok(NOW - 120))
        self.assertTrue(self.ok(NOW - 121))                              # a silent tape: rawrec's alarm, not this one
        self.beat(NOW - 3_600, NOW - 10, NOW - 600)
        self.assertTrue(self.ok(NOW - 1))

    def test_no_frame_read_while_the_tape_is_written_is_stuck(self):
        self.beat(NOW - 3_600, NOW - 10, None)
        self.assertFalse(self.ok(NOW - 1))
        self.assertTrue(self.ok(None))

    def test_the_pass_compares_the_engine_with_the_binance_tape(self):
        with tempfile.TemporaryDirectory() as r:
            raw = Path(r)
            touch(raw / "binance" / "2026-11-02" / "03.ndjson.zst", NOW - 1)
            self.beat(NOW - 3_600, NOW - 10, NOW - 601)
            got = {c.name: c.ok for c in W.run_checks(NOW, self.state, self.state, raw, clock=False,
                                                      state_of=lambda label: "running")}
        self.assertFalse(got["livesig"])


class TestTheTapeOnAnotherMac(unittest.TestCase):
    """2026-11-16: the raw recorder and #71's engine moved to a second Mac; the watchdog checks them there by ssh."""

    CFG = {"host": "fredo", "raw": "/Users/fredo/espero-raw", "state": "/Users/fredo/espero/state"}

    def found(self, age=10.0, agents="running", hb="fresh", free=700.0, ahead=0.0):
        there = NOW + ahead
        beat = {"started_ms": (there - 3600) * 1000, "written_ms": (there - 30) * 1000, "tape_ms": (NOW - 20) * 1000}
        return ({"now": there, "mtime": {v: there - age for v in W.rawrec.VENUES},
                 "agents": {a: agents for a in W.REMOTE_AGENTS}, "free_gb": free,
                 "heartbeat": beat if hb == "fresh" else hb}, ahead)

    def checks(self, **kw):
        return {c.name: c for c in W.check_remote(NOW, self.CFG, probe_fn=lambda cfg: self.found(**kw))}

    def test_a_healthy_tape_there_passes_every_check(self):
        c = self.checks()
        self.assertTrue(all(x.ok for x in c.values()), [x for x in c.values() if not x.ok])
        self.assertEqual({f"rawrec:{v}" for v in W.rawrec.VENUES} - set(c), set())
        self.assertIn("agent:com.espero.rawrec@fredo", c)
        self.assertIn("disk@fredo", c)

    def test_its_times_are_moved_onto_this_macs_clock(self):
        c = self.checks(age=10.0, ahead=-900.0)                  # fresh there, though its clock runs 900 s behind
        self.assertTrue(c["rawrec:binance"].ok)
        self.assertTrue(c["livesig"].ok)
        self.assertFalse(c["clock@fredo"].ok)
        self.assertEqual(c["clock@fredo"].severity, "warn")
        self.assertNotIn("clock@fredo", self.checks(ahead=0.3))

    def test_a_silent_tape_a_stopped_job_a_full_disk_and_a_stuck_engine_each_alarm(self):
        self.assertFalse(self.checks(age=600.0)["rawrec:okx"].ok)
        self.assertFalse(self.checks(agents="not loaded")["agent:com.espero.livesig@fredo"].ok)
        self.assertFalse(self.checks(free=20.0)["disk@fredo"].ok)
        stuck = self.found()
        stuck[0]["heartbeat"]["written_ms"] = (NOW - 3600) * 1000
        c = {x.name: x for x in W.check_remote(NOW, self.CFG, probe_fn=lambda cfg: stuck)}
        self.assertFalse(c["livesig"].ok)
        self.assertFalse(self.checks(hb="unreadable")["livesig"].ok)
        self.assertTrue(self.checks(hb=None)["livesig"].ok)      # no heartbeat yet, as here

    def test_an_unreachable_mac_is_one_alarm_not_one_per_venue(self):
        def down(cfg):
            raise RuntimeError("ssh: connect to host 10.99.0.2 port 22: Operation timed out")
        c = W.check_remote(NOW, self.CFG, probe_fn=down)
        self.assertEqual([(x.name, x.ok) for x in c], [("remote:fredo", False)])
        self.assertIn("timed out", c[0].note)

    def test_with_the_config_the_tape_is_not_looked_for_here_and_its_jobs_not_asked_of_this_launchd(self):
        with tempfile.TemporaryDirectory() as d:
            state, data = Path(d) / "state", Path(d) / "data"
            state.mkdir()
            (state / W.REMOTE).write_text(json.dumps(self.CFG))
            asked = []
            checks = W.run_checks(NOW, data, state, Path(d) / "gone", clock=False,
                                  state_of=lambda label: asked.append(label) or "running",
                                  probe_fn=lambda cfg: self.found())
            names = {c.name for c in checks}
            self.assertTrue(set(W.REMOTE_AGENTS).isdisjoint(asked))
            self.assertIn("com.espero.mf-canary", asked)
            self.assertIn("rawrec:binance", names)
            self.assertIn("disk", names)                         # this Mac's own disk is still checked
            self.assertTrue(all(c.ok for c in checks if c.name.startswith("rawrec:")))

    def test_without_the_config_nothing_changes_and_a_bad_config_alarms(self):
        with tempfile.TemporaryDirectory() as d:
            state = Path(d)
            self.assertIsNone(W.remote_config(state))
            (state / W.REMOTE).write_text('{"host": "fredo"}')
            with self.assertRaises(ValueError):
                W.remote_config(state)
            checks = W.run_checks(NOW, state / "data", state, None, clock=False, state_of=lambda label: "running")
            self.assertIn(("remote", False), [(c.name, c.ok) for c in checks])

    def test_the_probe_runs_one_ssh_with_stock_python_and_reads_its_answer(self):
        calls = []

        class R:
            returncode, stderr = 0, ""
            stdout = json.dumps({"now": 105.0, "mtime": {}, "agents": {}, "free_gb": 1.0, "heartbeat": None})

        def run(cmd, **kw):
            calls.append((cmd, kw))
            return R()
        times = iter([100.0, 102.0])
        found, ahead = W.probe(self.CFG, ["binance"], run=run, clock=lambda: next(times))
        self.assertEqual(ahead, 4.0)                             # 105 against the midpoint, 101
        cmd, kw = calls[0]
        self.assertEqual(cmd[:6], ["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=10", "fredo"])
        self.assertEqual(cmd[6:8], ["/usr/bin/python3", "-"])
        import shlex
        self.assertEqual(json.loads(shlex.split(cmd[8])[0])["venues"], ["binance"])   # quoted for the remote shell
        self.assertIn("def newest_mtime", kw["input"])

        class Bad(R):
            returncode, stderr, stdout = 255, "ssh: Could not resolve hostname fredo\n", ""
        with self.assertRaises(RuntimeError):
            W.probe(self.CFG, run=lambda *a, **k: Bad())

        class Nonsense(R):
            stdout = "hello"
        with self.assertRaises(RuntimeError):
            W.probe(self.CFG, run=lambda *a, **k: Nonsense())

    def test_the_probe_script_is_valid_python_and_judges_the_tape_as_this_module_does(self):
        import subprocess
        import sys
        with tempfile.TemporaryDirectory() as d:
            raw, st = Path(d) / "raw", Path(d) / "state"
            touch(raw / "binance" / "2026-11-16" / "00.jsonl.zst", NOW - 30)
            touch(raw / "binance" / "2026-11-15" / "23.jsonl.zst", NOW + 30)   # an older day, newer mtime: ignored
            st.mkdir()
            arg = json.dumps({"raw": str(raw), "state": str(st), "venues": ["binance"], "agents": []})
            r = subprocess.run([sys.executable, "-", arg], input=W.probe_script(), capture_output=True, text=True)
            self.assertEqual(r.returncode, 0, r.stderr)
            out = json.loads(r.stdout)
            self.assertEqual(out["mtime"]["binance"], W.newest_mtime(raw / "binance"))
            self.assertIsNone(out["heartbeat"])


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
