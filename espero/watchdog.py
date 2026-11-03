"""The silence alarm: every recorder, loop and daily run checked against its period, a silence escalated until acked.

    espero watchdog --once            # check everything, notify by escalation, write state/watchdog.json
    espero watchdog --status          # the last checks, notifying no one
    espero watchdog --ack NAME        # stop repeating NAME's alarm until it recovers
    espero watchdog --drill-report T  # after a recovery drill that began at T (UTC): how long, and what was lost

Recorders are judged by the newest file in their latest day folder against their period: the raw tape per venue
(120 s, the silence `rawrec.gaps` calls a gap), hlcollect's 5-minute contexts, hlbook and Deribit (15 minutes).
The always-on loops are judged by launchd's own word that they are running; the daily run by health.json (26 hours).
The clock is checked against an NTP server: off by 250 ms is a warning, by a second it refuses trading
(`clock_ok`). Escalation: a macOS notification at once, the webhook after 10 minutes, both again every hour, until
the check recovers or the operator acknowledges it. A notification that fails never fails the check.
"""
from __future__ import annotations

import calendar
import json
import os
import re
import socket
import struct
import subprocess
import sys
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Callable, Dict, Iterable, List, Optional, Tuple

from . import rawrec

ROOT = Path(__file__).resolve().parents[1]
RAW_MAX_AGE_S = 120.0                  # rawrec.gaps' silence
RECORDERS = {                           # folder under data/ -> its period's allowance
    "hlcollect": ("hlcollect/ctx", 900.0),
    "hlbook": ("hlbook", 900.0),
    "deribit": ("deribit", 900.0),
}
DAILY_MAX_AGE_S = 26 * 3600.0
AGENTS = ("com.espero.rawrec", "com.espero.hlcollect", "com.espero.hlbook", "com.espero.deribit",
          "com.espero.carry-maker", "com.espero.carry-taker", "com.espero.hlp", "com.espero.hlp2",
          "com.espero.hlp2-testnet", "com.espero.paper",
          "com.espero.livesig")                                # KeepAlive: launchd should say "running"
LIVESIG_HEARTBEAT = "livesig.heartbeat.json"   # livesig.HEARTBEAT, not imported: that loads pandas every minute
LIVESIG_LAG_S = 600.0                  # the engine's last frame may trail a tape being written by two bars
LIVESIG_START_S = 900.0                # a start reads yesterday's whole tape first: about five minutes on this Mac
DISK_FLOOR_GB = rawrec.FREE_FLOOR_GB
CLOCK_WARN_S, CLOCK_REFUSE_S = 0.25, 1.0
NTP_SERVER = "time.apple.com"
ESCALATE_AFTER_S = 600.0
REPEAT_S = 3600.0
STATE = "watchdog.json"
DAY = re.compile(r"^\d{4}-\d{2}-\d{2}$")
NOT_DATA = ("MANIFEST.sha256", "coins.json", "rawrec.lock", "instruments.json")


@dataclass(frozen=True)
class Check:
    name: str
    ok: bool
    note: str
    age_s: Optional[float] = None
    limit_s: Optional[float] = None
    severity: str = "alarm"             # "warn", "alarm", or "refuse trading"


def newest_mtime(folder: Path, depth: int = 4) -> Optional[float]:
    """The newest data file's mtime: in the latest day folder where folders are dated, in every other subfolder
    (a currency, a venue) otherwise. Manifests and lists are not data."""
    if depth < 0 or not folder.is_dir():
        return None
    best = None
    entries = [e for e in folder.iterdir() if not e.name.startswith(".")]
    days = sorted(e for e in entries if e.is_dir() and DAY.match(e.name))
    subs = ([days[-1]] if days else []) + [e for e in entries if e.is_dir() and not DAY.match(e.name)]
    for e in entries:
        if e.is_file() and e.name not in NOT_DATA:
            best = max(best or 0.0, e.stat().st_mtime)
    for s in subs:
        m = newest_mtime(s, depth - 1)
        if m is not None:
            best = max(best or 0.0, m)
    return best


def check_age(name: str, newest: Optional[float], limit: float, now: float, severity: str = "alarm") -> Check:
    if newest is None:
        return Check(name, False, "nothing recorded", None, limit, severity)
    age = now - newest
    return Check(name, age <= limit, f"newest {age:,.0f} s ago, allowed {limit:,.0f} s", age, limit, severity)


def check_recorders(now: float, data: Path, raw: Optional[Path], venues: Iterable[str] = rawrec.VENUES,
                    mtime: Callable[[Path], Optional[float]] = newest_mtime) -> List[Check]:
    out = [check_age(f"recorder:{name}", mtime(data / sub), limit, now) for name, (sub, limit) in RECORDERS.items()]
    if raw is not None:
        out += [check_age(f"rawrec:{v}", mtime(raw / v), RAW_MAX_AGE_S, now) for v in venues]
    return out


def check_daily(now: float, state: Path) -> Check:
    try:
        h = json.loads((state / "health.json").read_text(encoding="utf-8"))
        last = calendar.timegm(time.strptime(h["last_run"][:19], "%Y-%m-%dT%H:%M:%S"))
    except (OSError, ValueError, KeyError):
        return Check("daily", False, "no readable health.json", None, DAILY_MAX_AGE_S)
    c = check_age("daily", last, DAILY_MAX_AGE_S, now)
    if c.ok and not h.get("ok", False):
        return Check("daily", False, "the last run had a failed step: " + ", ".join(
            k for k, s in (h.get("steps") or {}).items() if not s.get("ok", True)), c.age_s, c.limit_s)
    return c


def launchd_state(label: str) -> str:
    """launchd's own word on an agent: 'running', another state, or 'not loaded'."""
    r = subprocess.run(["launchctl", "print", f"gui/{os.getuid()}/{label}"], capture_output=True, text=True)
    if r.returncode != 0:
        return "not loaded"
    m = re.search(r"^\s*state = (\S+)", r.stdout, re.M)
    return m.group(1) if m else "unknown"


def check_agents(state_of: Callable[[str], str] = launchd_state, agents: Iterable[str] = AGENTS) -> List[Check]:
    out = []
    for label in agents:
        s = state_of(label)
        out.append(Check(f"agent:{label}", s == "running", f"launchd says {s}"))
    return out


def check_livesig(now: float, state: Path, tape_newest: Optional[float]) -> Check:
    """#71's engine writes nothing until an event fires, so it says where it is (livesig.beat). It is stuck when it
    has not said so for ten minutes, or when the Binance tape is being written and its last frame trails it by
    more; a silent tape is rawrec:binance's alarm, not this one. A start gets fifteen minutes. No heartbeat at all
    is an engine that has not run since it began writing one; launchd's word on it (AGENTS) still holds."""
    try:
        hb = json.loads((state / LIVESIG_HEARTBEAT).read_text(encoding="utf-8"))
        started, written, tape = hb["started_ms"] / 1000, hb["written_ms"] / 1000, hb["tape_ms"]
    except FileNotFoundError:
        return Check("livesig", True, "no heartbeat yet")
    except (OSError, ValueError, KeyError, TypeError):
        return Check("livesig", False, "the heartbeat cannot be read")
    if now - started <= LIVESIG_START_S:
        return Check("livesig", True, f"started {now - started:,.0f} s ago, reading the tape so far",
                     now - started, LIVESIG_START_S)
    if now - written > LIVESIG_LAG_S:
        return Check("livesig", False, f"no heartbeat for {now - written:,.0f} s: the engine is stuck or gone",
                     now - written, LIVESIG_LAG_S)
    lag = None if tape is None else now - tape / 1000
    if tape_newest is not None and now - tape_newest <= RAW_MAX_AGE_S and (lag is None or lag > LIVESIG_LAG_S):
        behind = "has read no frame" if lag is None else f"is {lag:,.0f} s behind it"
        return Check("livesig", False, f"the tape is being written but the engine {behind}", lag, LIVESIG_LAG_S)
    return Check("livesig", True, "no frame read yet" if lag is None else f"last frame {lag:,.0f} s ago",
                 lag, LIVESIG_LAG_S)


def check_disk(path: Path, free_gb: Callable[[Path], float] = rawrec.free_gb) -> Check:
    try:
        gb = free_gb(path)
    except OSError:
        return Check("disk", False, f"cannot read free space at {path}")
    return Check("disk", gb >= DISK_FLOOR_GB, f"{gb:,.0f} GB free, floor {DISK_FLOOR_GB:.0f} GB")


def sntp_offset(server: str = NTP_SERVER, timeout: float = 2.0, port: int = 123) -> float:
    """This machine's clock minus the server's, in seconds (SNTP, RFC 4330): positive means we run ahead."""
    packet = b"\x23" + 47 * b"\0"                       # LI 0, version 4, mode 3 (client)
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
        s.settimeout(timeout)
        t0 = time.time()
        s.sendto(packet, (server, port))
        data, _ = s.recvfrom(48)
        t3 = time.time()
    secs, frac = struct.unpack("!II", data[40:48])
    server_tx = secs - 2_208_988_800 + frac / 2 ** 32
    return (t0 + t3) / 2 - server_tx


def check_clock(offset: Callable[[], float] = sntp_offset) -> Check:
    try:
        off = offset()
    except OSError as exc:
        return Check("clock", False, f"no answer from the time server ({exc.__class__.__name__})", severity="warn")
    if abs(off) > CLOCK_REFUSE_S:
        return Check("clock", False, f"off by {off:+.3f} s: trading is refused", severity="refuse trading")
    if abs(off) > CLOCK_WARN_S:
        return Check("clock", False, f"off by {off:+.3f} s", severity="warn")
    return Check("clock", True, f"off by {off:+.3f} s")


def clock_ok(offset_s: float) -> bool:
    """An order may be placed only on a clock within a second of the time server's."""
    return abs(offset_s) <= CLOCK_REFUSE_S


def escalate(checks: List[Check], state: Dict[str, dict], now: float) -> Tuple[List[Tuple[str, str, str]], dict]:
    """Pure: what to send now, and the state to keep. A new failure goes to the screen at once and to the webhook
    after ESCALATE_AFTER_S; both repeat every REPEAT_S until it recovers or is acknowledged; a recovery is said once."""
    sends: List[Tuple[str, str, str]] = []
    new: Dict[str, dict] = {}
    for c in checks:
        s = dict(state.get(c.name) or {})
        if c.ok:
            if s:
                sends.append(("macos", f"recovered: {c.name}", c.note))
            continue
        if not s:
            s = {"since": now, "macos": now, "webhook": None, "acked": False}
            sends.append(("macos", f"{c.severity}: {c.name}", c.note))
        elif not s.get("acked"):
            if s.get("webhook") is None and now - s["since"] >= ESCALATE_AFTER_S:
                s["webhook"] = now
                sends.append(("webhook", f"{c.severity}: {c.name} for {(now - s['since']) / 60:.0f} min", c.note))
            elif now - s["macos"] >= REPEAT_S:
                s["macos"] = now
                sends += [("macos", f"still {c.severity}: {c.name}", c.note),
                          ("webhook", f"still {c.severity}: {c.name}", c.note)]
        new[c.name] = s
    return sends, new


def ack(state: Dict[str, dict], name: str) -> bool:
    if name not in state:
        return False
    state[name]["acked"] = True
    return True


def run_checks(now: float, data: Path, state: Path, raw: Optional[Path], clock: bool = True,
               state_of: Callable[[str], str] = launchd_state) -> List[Check]:
    out = check_recorders(now, data, raw) + [check_daily(now, state)] + check_agents(state_of)
    out.append(check_livesig(now, state, newest_mtime(raw / "binance") if raw is not None else None))
    out.append(check_disk(raw if raw is not None else data))
    if clock:
        out.append(check_clock())
    return out


def write_state(state_dir: Path, checks: List[Check], memory: dict, now: float) -> Path:
    path = state_dir / STATE
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps({"at": now, "checks": [asdict(c) for c in checks], "alarms": memory}, indent=1),
                   encoding="utf-8")
    os.replace(tmp, path)
    return path


def read_checks(state_dir: Path) -> List[Check]:
    try:
        rows = json.loads((state_dir / STATE).read_text(encoding="utf-8")).get("checks", [])
        return [Check(**r) for r in rows]
    except (OSError, ValueError, TypeError):
        return []


def read_memory(state_dir: Path) -> dict:
    try:
        return json.loads((state_dir / STATE).read_text(encoding="utf-8")).get("alarms", {})
    except (OSError, ValueError):
        return {}


def once(state_dir: Path, data: Path, raw: Optional[Path], clock: bool = True, send=None, now: Optional[float] = None,
         state_of: Callable[[str], str] = launchd_state) -> int:
    """One pass: check, escalate, notify, remember. Exit 0 when every check holds."""
    from . import notify

    now = time.time() if now is None else now
    checks = run_checks(now, data, state_dir, raw, clock, state_of)
    sends, memory = escalate(checks, read_memory(state_dir), now)
    send = send or (lambda channel, title, msg: notify.macos(title, msg) if channel == "macos"
                    else notify.webhook(title, msg))
    for channel, title, msg in sends:
        try:
            send(channel, f"espero watchdog: {title}", msg)
        except Exception:  # noqa: BLE001 - a failed notification never fails the check
            pass
    write_state(state_dir, checks, memory, now)
    for c in checks:
        print(f"{'ok  ' if c.ok else 'FAIL'} {c.name:32s} {c.note}")
    return 0 if all(c.ok for c in checks) else 1


def drill_report(since: float, until: float, data: Path, raw: Optional[Path], venues: Iterable[str] = rawrec.VENUES
                 ) -> Dict[str, dict]:
    """After a recovery drill begun at `since`: per recorder, when data resumed and what was lost. The tape's own
    gaps (rawrec.gaps) give the raw venues' silences; the collector's 5-minute slots give its missing ones."""
    out: Dict[str, dict] = {}
    if raw is not None:
        days = sorted({time.strftime("%Y-%m-%d", time.gmtime(t)) for t in (since, until)})
        for v in venues:
            gaps = []
            for d in days:
                try:
                    gaps += [(a, b) for a, b in rawrec.gaps(raw, v, d, now_ms=int(until * 1000))
                             if b >= since * 1000 and a <= until * 1000]
                except (OSError, ValueError):
                    continue
            lost = sum(b - a for a, b in gaps) / 1000
            out[f"rawrec:{v}"] = {"gaps": len(gaps), "lost_s": lost,
                                  "resumed_s": (max(b for _, b in gaps) / 1000 - since) if gaps else 0.0}
    ctx = data / "hlcollect" / "ctx"
    slots = set()
    for day in sorted({time.strftime("%Y-%m-%d", time.gmtime(t)) for t in (since, until)}):
        for f in (ctx / day).glob("*.csv.gz") if (ctx / day).is_dir() else []:
            slots.add(f"{day} {f.name[:4]}")
    first = int(since // 300 * 300) + 300
    want = [time.strftime("%Y-%m-%d %H%M", time.gmtime(t)) for t in range(first, int(until), 300)]
    missing = [s for s in want if s not in slots]
    out["recorder:hlcollect"] = {"expected_slots": len(want), "missing_slots": len(missing),
                                 "lost_s": 300.0 * len(missing), "first_missing": missing[:1]}
    return out


def main(argv=None) -> int:
    import argparse

    ap = argparse.ArgumentParser(prog="espero watchdog")
    ap.add_argument("--once", action="store_true")
    ap.add_argument("--status", action="store_true")
    ap.add_argument("--ack")
    ap.add_argument("--drill-report", metavar="SINCE_UTC")
    ap.add_argument("--no-clock", action="store_true")
    ap.add_argument("--state-dir", default=str(ROOT / "state"))
    a = ap.parse_args(argv)
    state_dir, data = Path(a.state_dir), ROOT / "data"
    raw = Path(os.environ[rawrec.ENV]) if os.environ.get(rawrec.ENV) else None
    if a.ack:
        memory = read_memory(state_dir)
        if not ack(memory, a.ack):
            print(f"no alarm named {a.ack}", file=sys.stderr)
            return 2
        write_state(state_dir, read_checks(state_dir), memory, time.time())   # --status still shows the last pass
        return 0
    if a.drill_report:
        since = calendar.timegm(time.strptime(a.drill_report, "%Y-%m-%dT%H:%M"))
        print(json.dumps(drill_report(since, time.time(), data, raw), indent=1))
        return 0
    if a.status:
        try:
            print(json.dumps(json.loads((state_dir / STATE).read_text(encoding="utf-8")), indent=1))
        except OSError:
            print("no watchdog run yet")
        return 0
    from .broker import load_env

    load_env(str(ROOT / ".env"))            # launchd passes no .env, and the webhook's URL is there (as run_daily)
    return once(state_dir, data, raw, clock=not a.no_clock)


if __name__ == "__main__":
    sys.exit(main())
