"""docs/STATUS.md: where the project stands, from the ledger and the last daily run. Nothing is typed by hand.

    .venv/bin/python scripts/status.py          # rewrite docs/STATUS.md
    .venv/bin/python scripts/status.py --print  # to stdout only

It reads research/trials.csv (every test's committed status), state/health.json (the last `espero daily`),
and counts the recorded files on disk. It computes no return and judges nothing: a forward test's running
numbers are not shown, because they decide nothing until 2027-03-31.
"""
from __future__ import annotations

import csv
import json
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from espero.cli import state_dir  # noqa: E402

OUT = ROOT / "docs" / "STATUS.md"
RECORDED = ("data/hlcollect", "data/deribit", "data/hlbook", "data/aggr/forward", "data/aggr/forward5m", "data/lows/forward")
JUDGED = "2027-03-31"


def trials(path: Path = ROOT / "research" / "trials.csv") -> List[dict]:
    with path.open() as f:
        return list(csv.DictReader(f))


def health(path: Optional[Path] = None) -> Optional[dict]:
    path = path or state_dir() / "health.json"
    if not Path(path).is_file():
        return None
    return json.loads(Path(path).read_text())


def recorded(root: Path = ROOT) -> Dict[str, int]:
    return {p: sum(1 for f in (root / p).rglob("*") if f.is_file() and f.name != "MANIFEST.sha256")
            if (root / p).is_dir() else 0 for p in RECORDED}


def render(rows: List[dict], h: Optional[dict], files: Dict[str, int], now: Optional[datetime] = None) -> str:
    now = now or datetime.now(timezone.utc)
    counts = Counter(r["status"] for r in rows)
    tally = ", ".join(f"{n} {s}" for s, n in sorted(counts.items(), key=lambda x: (-x[1], x[0])))
    lines = [f"# Status — generated {now:%Y-%m-%d %H:%M} UTC by `scripts/status.py`", "",
             "Nothing here is typed by hand. The ledger is `research/trials.csv`; the run is `state/health.json`.", "",
             "## The ledger", "",
             f"{len(rows)} tests: {tally}.", ""]
    kept = [r for r in rows if r["status"] in ("pass", "provisional")]
    if kept:
        lines.append("| # | status | what | document |")
        lines.append("|---|---|---|---|")
        for r in kept:
            lines.append(f"| {r['test']} | {r['status']} | {r['name']} | `{r['doc']}` |")
        lines.append("")
    pending = [r for r in rows if r["status"] == "forward_pending"]
    if pending:
        lines.append(f"**Forward, judged once after {JUDGED}:** " + ", ".join(f"#{r['test']}" for r in pending) +
                     ". Their running numbers decide nothing and are not shown here.")
        lines.append("")
    lines += ["## The last daily run", ""]
    if h is None:
        lines.append("No `health.json` yet: `espero daily` has not run in this state folder.")
    else:
        kind = "dry run (nothing marked)" if h.get("dry_run") else "ok" if h.get("ok") else "FAILED"
        lines.append(f"`last_run` {h.get('last_run', '-')} — {kind}; `last_success` {h.get('last_success', '-')}"
                     + ("; **paused** by KILL" if h.get("paused") else ""))
        lines.append("")
        lines.append("| step | ok | note |")
        lines.append("|---|---|---|")
        for name, s in (h.get("steps") or {}).items():
            note = (s.get("error") or s.get("note") or "").replace("|", "/")
            lines.append(f"| {name} | {'yes' if s.get('ok') else 'NO'} | {note} |")
    lines += ["", "## Recorded on disk (cannot be fetched again)", "", "| folder | files |", "|---|---|"]
    for p, n in files.items():
        lines.append(f"| `{p}` | {n} |")
    lines += ["", "Verdicts, costs and what a pass leads to: `research/INDEX.md`, `research/FORWARD_FAMILY.md`."]
    return "\n".join(lines) + "\n"


def main(argv=None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    text = render(trials(), health(), recorded())
    if "--print" in argv:
        print(text, end="")
        return 0
    OUT.write_text(text)
    print(f"wrote {OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
