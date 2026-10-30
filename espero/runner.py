"""`espero daily`: the one command a scheduler runs.

    tsmom -> xs -> mf (#8) -> mf-hl -> liqfwd (#22/#23) -> lowsfwd (#24) -> liqbreak (#27)
          -> fundsplit (#32) -> postclose (#29) -> levpush (#34) -> bidsfwd (#31) -> settlefwd (#38)
          -> liqhold (#45) -> publish (Mondays, maintainer only)
          -> dashboard -> health.json

Rules:

* one run at a time -- a lock file with the owner's pid; a stale lock from a
  dead process is removed, a live one aborts the run
* a KILL file in the state directory pauses everything, including marks
* each step is isolated: a failure is logged, notified, and recorded in
  health.json, and the remaining steps still run (a broken Yahoo symbol must
  not stop the dashboard from showing yesterday's numbers)
* the exit code is non-zero when any step failed, so launchd and CI notice
* `--dry-run` is a preflight: it checks the directory, the lock, the logging
  and renders the dashboard from whatever databases exist, without touching
  the network or the accounts. It is what CI runs
"""
from __future__ import annotations

import json
import logging
import logging.handlers
import os
import sys
import time
import traceback
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Dict, Optional

from . import bidsfwd as bfw
from . import dashboard as dash
from . import fundsplit as fsp
from . import levpush as lpu
from . import liqbreak as lbk
from . import liqfwd as lfm
from . import liqhold as lhd
from . import lowsfwd as lwf
from . import mf as mfm
from . import notify as notifier
from . import postclose as pcl
from . import settlefwd as sfw
from . import tsmom as tsm
from . import xs as xsm

log = logging.getLogger("espero.daily")

LOG_DIR = Path(os.environ.get("ESPERO_LOG_DIR", Path.home() / "Library" / "Logs" / "espero"))
TRADE_NOTES = ("init", "rebalance", "deposit")


@dataclass
class StepResult:
    ok: bool
    seconds: float
    note: str = ""
    equity: Optional[float] = None
    error: str = ""
    skipped: bool = False


@dataclass
class DailyResult:
    started: str
    steps: Dict[str, StepResult] = field(default_factory=dict)
    paused: bool = False
    dry_run: bool = False

    @property
    def ok(self) -> bool:
        return not self.paused and all(s.ok for s in self.steps.values())

    @property
    def exit_code(self) -> int:
        return 0 if self.ok or self.paused else 1


# ------------------------------------------------------------------ logging
def setup_logging(log_dir: Path = LOG_DIR, level: int = logging.INFO) -> Path:
    log_dir = Path(log_dir)
    log_dir.mkdir(parents=True, exist_ok=True)
    path = log_dir / "daily.log"
    root = logging.getLogger()
    root.setLevel(level)
    fmt = logging.Formatter("%(asctime)s %(levelname)-7s %(name)s: %(message)s")
    if not any(getattr(h, "_espero", False) for h in root.handlers):
        fh = logging.handlers.RotatingFileHandler(path, maxBytes=2_000_000, backupCount=5)
        fh.setFormatter(fmt)
        fh._espero = True  # type: ignore[attr-defined]
        root.addHandler(fh)
        sh = logging.StreamHandler(sys.stderr)
        sh.setFormatter(fmt)
        sh._espero = True  # type: ignore[attr-defined]
        root.addHandler(sh)
    return path


# --------------------------------------------------------------------- lock
def _pid_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


class Lock:
    def __init__(self, path: Path):
        self.path = Path(path)

    def __enter__(self):
        if self.path.exists():
            try:
                pid = int(self.path.read_text().strip() or 0)
            except ValueError:
                pid = 0
            if pid and _pid_alive(pid):
                raise RuntimeError(f"another run holds {self.path} (pid {pid})")
            log.warning("removing stale lock %s (pid %s is gone)", self.path, pid)
            self.path.unlink(missing_ok=True)
        try:
            # O_EXCL: of two runs racing here, exactly one creates the file
            fd = os.open(self.path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o644)
        except FileExistsError:
            raise RuntimeError(f"another run took {self.path} at the same moment") from None
        with os.fdopen(fd, "w") as fh:
            fh.write(str(os.getpid()))
        return self

    def __exit__(self, *exc):
        try:
            self.path.unlink()
        except FileNotFoundError:
            pass
        return False


def _hl_daily():
    from . import hyperliquid as hl
    return hl.daily


PUBLISH_SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "publish-data.sh"


def publish_data(now: datetime, env: Optional[dict] = None, run=None) -> dict:
    """Mondays (UTC) only: publish the live recordings as a GitHub release (scripts/publish-data.sh)
    so teammates can fetch them. Off unless ESPERO_PUBLISH_AS names the gh account that owns the
    repo, so a teammate's daily run never publishes. The token is that account's, passed to the
    script alone: the machine's active gh account is never switched."""
    import shutil
    import subprocess
    env = dict(os.environ if env is None else env)
    run = run or subprocess.run
    account = (env.get("ESPERO_PUBLISH_AS") or "").strip()
    if not account:
        return {"note": "off (ESPERO_PUBLISH_AS not set)"}
    if now.weekday() != 0:
        return {"note": "not Monday"}
    gh = shutil.which("gh", path=env.get("PATH")) or "gh"
    token = run([gh, "auth", "token", "-u", account], capture_output=True, text=True, check=True).stdout.strip()
    out = run([str(PUBLISH_SCRIPT)], capture_output=True, text=True, check=True,
              env={**env, "GH_TOKEN": token})
    last = (out.stdout.strip().splitlines() or [""])[-1]
    return {"note": last}


# -------------------------------------------------------------------- steps
def _step(name: str, fn: Callable[[], dict], result: DailyResult, notify: bool) -> Optional[dict]:
    t0 = time.time()
    try:
        out = fn()
    except Exception as exc:  # noqa: BLE001 - every step is isolated on purpose
        err = f"{type(exc).__name__}: {exc}"
        log.error("%s FAILED: %s\n%s", name, err, traceback.format_exc())
        result.steps[name] = StepResult(False, time.time() - t0, error=err)
        if notify:
            notifier.notify(f"espero {name} failed", err[:200])
        return None
    note = str(out.get("note", "")) if isinstance(out, dict) else ""
    equity = out.get("equity") if isinstance(out, dict) else None
    result.steps[name] = StepResult(True, time.time() - t0, note=note, equity=equity)
    log.info("%s ok in %.1fs: %s equity=%s", name, time.time() - t0, note,
             f"{equity:.2f}" if equity is not None else "-")
    if notify and note.split(" ")[0] in TRADE_NOTES:
        # a step may say what it did; outside the try above, so it must not raise
        message = out.get("message") if isinstance(out, dict) else None
        if not message:
            message = f"equity ${equity:,.2f}" if isinstance(equity, (int, float)) else note
        notifier.notify(f"espero {name}: {note}", str(message))
    return out


def write_health(state_dir: Path, result: DailyResult) -> Path:
    path = state_dir / "health.json"
    prev = {}
    if path.exists():
        try:
            prev = json.loads(path.read_text())
        except ValueError:
            prev = {}
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    doc = {
        "last_run": now,
        # a dry run or preflight skips the real steps: it proves nothing about them
        "last_success": now if result.ok and not result.dry_run else prev.get("last_success"),
        "ok": result.ok,
        "paused": result.paused,
        "dry_run": result.dry_run,
        "steps": {k: {"ok": v.ok, "seconds": round(v.seconds, 1), "note": v.note,
                      "equity": v.equity, "error": v.error, "skipped": v.skipped}
                  for k, v in result.steps.items()},
    }
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(doc, indent=2))
    os.replace(tmp, path)   # a reader never sees a half-written file
    return path


def run_daily(state_dir: Path = Path("."), cash_tsmom: float = 100.0, cash_xs: float = 100.0,
              cash_mf: float = 100.0,
              force: bool = False, dry_run: bool = False, notify: bool = True,
              now: Optional[datetime] = None, log_dir: Path = LOG_DIR) -> DailyResult:
    state_dir = Path(state_dir)
    state_dir.mkdir(parents=True, exist_ok=True)
    log_path = setup_logging(log_dir)
    from .broker import load_env
    load_env()      # launchd starts in the repo, where .env lives: the webhook needs it
    result = DailyResult(started=datetime.now(timezone.utc).isoformat(timespec="seconds"), dry_run=dry_run)
    log.info("daily run start (state=%s, log=%s, dry_run=%s)", state_dir.resolve(), log_path, dry_run)

    if (state_dir / "KILL").exists():
        log.warning("KILL file present in %s: paused, nothing runs", state_dir)
        result.paused = True
        write_health(state_dir, result)
        return result

    tsmom_db, xs_db, mf_db = state_dir / "tsmom.db", state_dir / "xs.db", state_dir / "mf.db"
    paper_db, live_db = state_dir / "paper.db", state_dir / "live.db"

    with Lock(state_dir / "daily.lock"):
        if dry_run:
            for name in ("tsmom", "xs", "mf", "mf-hl", "liqfwd", "lowsfwd", "liqbreak", "fundsplit", "postclose",
                         "levpush", "bidsfwd", "settlefwd", "liqhold", "publish"):
                result.steps[name] = StepResult(True, 0.0, note="skipped (dry run)", skipped=True)
                log.info("%s skipped (dry run)", name)
        else:
            _step("tsmom", lambda: tsm.run(str(tsmom_db), cash_tsmom, force=force, now=now),
                  result, notify)
            _step("xs", lambda: xsm.run(str(xs_db), cash_xs, force=force, now=now), result, notify)
            # no --force: #8's calendar is frozen (FORWARD_MF.md); it fills only its own Mondays
            _step("mf", lambda: mfm.run(str(mf_db), cash_mf), result, notify)
            # #8 on Hyperliquid prices beside it, information only (FORWARD_MF.md, amendment 2026-10-29)
            _step("mf-hl", lambda: mfm.run(str(state_dir / "mf-hl.db"), cash_mf, fetch=_hl_daily()),
                  result, notify)
            # #22's forward paper test: record aggr's hourly bars, rebuild the ledger (FORWARD_LIQ.md)
            _step("liqfwd", lambda: lfm.run(state_dir), result, notify)
            # #24's forward paper test: record Binance's 5-minute archive, rebuild the ledger (FORWARD_LOWS.md)
            _step("lowsfwd", lambda: lwf.run(state_dir), result, notify)
            # #27: #26's rule forward on aggr's 5-minute liquidations (FORWARD_LIQBREAK.md); after
            # lowsfwd, whose Binance bars it reads
            _step("liqbreak", lambda: lbk.run(state_dir), result, notify)
            # #32: #27's forced down-breaks split by Binance funding (FORWARD_FUNDSPLIT.md); reads
            # the ledger liqbreak just wrote
            _step("fundsplit", lambda: fsp.run(state_dir), result, notify)
            # #29: the US session's move after 16:00 ET (FORWARD_POSTCLOSE.md); reads lowsfwd's files,
            # downloads nothing
            _step("postclose", lambda: pcl.run(state_dir), result, notify)
            # #34 part B: SOL and XRP's push into the close, read from the rows postclose just wrote
            _step("levpush", lambda: lpu.run(state_dir), result, notify)
            # #31: 2-ATR resting bids under breakdowns (FORWARD_BIDS2.md); reads lowsfwd's files too
            _step("bidsfwd", lambda: bfw.run(state_dir), result, notify)
            # #38: the price after settlements where shorts pay hard (FORWARD_SHORTSPAY.md); reads
            # lowsfwd's bars and the funding archive #32 caches
            _step("settlefwd", lambda: sfw.run(state_dir), result, notify)
            # #45: #27's forced down-breaks held 4 h, 12 h, 1 day (FORWARD_LIQHOLD.md); reads the ledger
            # liqbreak wrote, lowsfwd's bars and the funding archive
            _step("liqhold", lambda: lhd.run(state_dir), result, notify)
            # Mondays: the live recordings as a release, after every step that writes them (docs/DATA.md)
            _step("publish", lambda: publish_data(now or datetime.now(timezone.utc)), result, notify)

        def render():
            out = dash.write(state_dir / "dashboard.html", tsmom_db=tsmom_db, paper_db=paper_db,
                             live_db=live_db, xs_db=xs_db, mf_db=mf_db, mf_hl_db=state_dir / "mf-hl.db",
                             board=True, offline=dry_run)
            return {"note": f"wrote {out}"}

        _step("dashboard", render, result, notify)

    path = write_health(state_dir, result)
    log.info("daily run %s (%s)", "ok" if result.ok else "FAILED", path)
    return result
