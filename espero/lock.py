"""One writer per journal.

A paper or live loop keeps cash and the open position in memory and writes them
to its journal. Two processes on one journal each believe they own the money,
and both will act on the same signal. This lock makes the second one refuse to
start.

It uses ``flock`` rather than a pid file: the kernel releases the lock when the
process exits for any reason, including a crash or a closed terminal, so there
is never a stale lock to clean up and no window between "check" and "take".
"""
from __future__ import annotations

import fcntl
import os
from pathlib import Path


class JournalBusy(RuntimeError):
    pass


class JournalLock:
    def __init__(self, journal_path):
        self.path = Path(str(journal_path) + ".lock")
        self._fh = None

    def __enter__(self) -> "JournalLock":
        self.path.parent.mkdir(parents=True, exist_ok=True)     # the journal makes it too, but after this
        fh = open(self.path, "a+")
        try:
            fcntl.flock(fh.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            fh.seek(0)
            owner = fh.read().strip() or "unknown"
            fh.close()
            raise JournalBusy(
                f"another process (pid {owner}) is already running on this journal; "
                f"stop it first, or use a different --state") from None
        fh.seek(0)
        fh.truncate()
        fh.write(str(os.getpid()))
        fh.flush()
        self._fh = fh
        return self

    def __exit__(self, *exc) -> bool:
        if self._fh is not None:
            fcntl.flock(self._fh.fileno(), fcntl.LOCK_UN)
            self._fh.close()
            self._fh = None
        return False
