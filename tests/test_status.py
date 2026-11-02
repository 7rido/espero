"""scripts/status.py renders the ledger, the last run and the recordings, and types nothing by hand."""
from __future__ import annotations

import importlib.util
import unittest
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def load():
    spec = importlib.util.spec_from_file_location("status_script", ROOT / "scripts" / "status.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


ROWS = [
    {"test": "4", "name": "TSMOM", "status": "pass", "doc": "research/RESULTS_TSMOM.md"},
    {"test": "12", "name": "Carry", "status": "provisional", "doc": "research/RESULTS_CARRY2.md"},
    {"test": "18", "name": "Liq", "status": "fail", "doc": "research/RESULTS_LIQ.md"},
    {"test": "22", "name": "Forward liq", "status": "forward_pending", "doc": "research/FORWARD_LIQ.md"},
]
HEALTH = {"last_run": "2026-11-02T07:30:00+00:00", "last_success": "2026-11-02T07:30:00+00:00", "ok": True,
          "dry_run": False, "paused": False,
          "steps": {"tsmom": {"ok": True, "note": "mark", "error": ""},
                    "liqfwd": {"ok": False, "note": "", "error": "HTTP 503 | aggr"}}}
NOW = datetime(2026, 11, 2, 8, 0, tzinfo=timezone.utc)


class TestRender(unittest.TestCase):
    def setUp(self):
        self.s = load()

    def test_counts_passes_pending_and_the_run(self):
        text = self.s.render(ROWS, HEALTH, {"data/hlcollect": 1449, "data/hlbook": 0}, now=NOW)
        self.assertIn("generated 2026-11-02 08:00 UTC", text)
        self.assertIn("4 tests: 1 fail, 1 forward_pending, 1 pass, 1 provisional.", text)
        self.assertIn("| 4 | pass | TSMOM | `research/RESULTS_TSMOM.md` |", text)
        self.assertIn("| 12 | provisional |", text)
        self.assertNotIn("| 18 |", text)                                   # fails are counted, not listed
        self.assertIn("judged once after 2027-03-31:** #22.", text)
        self.assertIn("`last_run` 2026-11-02T07:30:00+00:00 — ok", text)
        self.assertIn("| liqfwd | NO | HTTP 503 / aggr |", text)           # errors shown, pipes escaped
        self.assertIn("| `data/hlcollect` | 1449 |", text)
        self.assertNotIn("bps", text)                                      # no running number of any forward test

    def test_no_health_and_a_dry_run_are_said_plainly(self):
        self.assertIn("has not run in this state folder", self.s.render(ROWS, None, {}, now=NOW))
        text = self.s.render(ROWS, {**HEALTH, "dry_run": True}, {}, now=NOW)
        self.assertIn("dry run (nothing marked)", text)
        text = self.s.render(ROWS, {**HEALTH, "paused": True}, {}, now=NOW)
        self.assertIn("**paused** by KILL", text)

    def test_the_real_inputs_render(self):
        text = self.s.render(self.s.trials(), self.s.health(), self.s.recorded(), now=NOW)
        self.assertIn("## The ledger", text)
        self.assertIn("## Recorded on disk", text)


if __name__ == "__main__":
    unittest.main()
