"""#63: the portfolio layer's numbers, once, at the family's judgment (research/PREREGISTRATION_SLEEVES.md).

    .venv/bin/python research/sleeves.py research/sleeves_returns.csv

Refuses to run before 2027-04-01: the inputs are the forward ledgers' daily net returns, which are running
numbers until the family is judged. At judgment, the judging run writes `research/sleeves_returns.csv` (one
column per sleeve that passed, in return units, net of the costs its plan registered, one row per UTC day)
and `research/sleeves_t.json` ({test: main-criterion t}); this script prints what RESULTS_SLEEVES.md records.
It reads no ledger itself.
"""
from __future__ import annotations

import datetime as dt
import json
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from espero import sleeves as sl  # noqa: E402

JUDGMENT = dt.date(2027, 4, 1)


def main(argv=None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    today = dt.date.today()
    if today < JUDGMENT:
        print(f"#63 computes nothing before {JUDGMENT}: the sleeves' returns are running numbers until the family "
              f"is judged (today {today}). tests/test_sleeves.py is the only run before then.")
        return 2
    path = Path(argv[0]) if argv else ROOT / "research" / "sleeves_returns.csv"
    t_path = ROOT / "research" / "sleeves_t.json"
    if not path.exists() or not t_path.exists():
        print(f"needs {path} and {t_path}, written by the judging run")
        return 2
    returns = pd.read_csv(path, index_col=0, parse_dates=True)
    t_values = json.loads(t_path.read_text())
    sleeves = sl.sleeves_from_passes(t_values)
    print(f"passes {sorted(t_values)} -> sleeves {sleeves}")
    if len(sleeves) < 2:
        print("fewer than two sleeves: #63 does not apply; the single pass follows its own plan")
        return 0
    s = sl.summary(returns[list(sleeves)], t_values)
    print(json.dumps({k: v for k, v in s.items() if k != "correlations"}, indent=1, default=str))
    print(s["correlations"].to_string(index=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
