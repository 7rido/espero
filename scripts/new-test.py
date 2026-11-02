"""Scaffold a numbered test: the three files CI expects, and the checklist for the rest.

    .venv/bin/python scripts/new-test.py 61 depthday
    .venv/bin/python scripts/new-test.py 62 funding_lag --forward

Writes research/PREREGISTRATION_<NAME>.md (the contract, with every section the discipline needs),
espero/<name>.py (the rule, pure, empty) and tests/test_<name>.py (one test that fails until the rule
exists). It refuses a number already in research/trials.csv or a file that already exists, and writes
nothing else: claiming the files in espero/layers.py and research/index.py, the runner step for a forward
test, and the trials row at judgment are printed as the steps left, because each one is a decision.
"""
from __future__ import annotations

import argparse
import csv
import re
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

PREREG = """# Pre-registration — {title} (#{n})

Committed **before** any result is computed. This document is the contract; the result document will
say whether it was met, and nothing below is changed afterwards. A later idea takes a new number.

## Hypothesis

One sentence, with the mechanism: who is forced to trade, when, and why that leaves a return.

## Data

Which recordings or archives, which coins, which window, with the source named (docs/DATA.md).
What is excluded, and why, before looking.

## Rule

The signal, the fill (at the next bar's open, never the signal bar's close), the exit, the costs
(`espero.costs`, measured by #39 and #41, or a venue in `espero/venues.py`; never zero).

## Criteria, all required

1. **Statistical bar:** Benjamini-Hochberg q < 0.05 over every judged test in `research/trials.csv`,
   and |t| ≥ 3 on the same t, in the registered direction (research/FDR_STANDARD.md). The t is
   day-clustered or Newey-West where observations overlap.
2. **Pays after costs:** net > 0 against the round trip above.
3. **Not one stretch:** net > 0 in each half of the window.
4. **Not one coin:** among coins with enough trades, more than half net > 0.

## Power

How many events the window should hold, and the smallest effect those events could show at the bar.

## Outcomes

**PASS:** every criterion holds; what happens next is `research/FORWARD_FAMILY.md`, nothing more.
**FAIL:** any criterion misses; the rule is closed. **INCONCLUSIVE:** fewer than N events; no claim.

## Information only

Readouts that will be reported beside the verdict and never become a claim.
{forward}
"""

FORWARD_NOTE = """
## Forward

Window: {start} to 2027-03-31. The daily step `{name}` records one UTC day at a time and rewrites
`state/{name}_trades.csv`; the running numbers decide nothing. Judged once, after 2027-03-31.
"""

MODULE = '''"""#{n}: {title} (research/PREREGISTRATION_{upper}.md).

The frozen rule and its criteria, pure: arrays in, numbers out, no I/O. research/{name}.py fetches
and prints.
"""
from __future__ import annotations

HURDLE_BPS = 18.0   # replace with the measured round trip from espero.costs before the first run


def rule():
    """The registered rule. Written after the pre-registration is committed, never the other way."""
    raise NotImplementedError("#{n}: write the rule after committing its pre-registration")
'''

TEST = '''"""#{n}'s rule, on made-up data only."""
import unittest

from espero import {name}


class TestRule(unittest.TestCase):
    def test_the_rule_exists(self):
        """Replace with the rule's behaviour, then break the rule and confirm this fails."""
        self.assertTrue(callable({name}.rule))


if __name__ == "__main__":
    unittest.main()
'''


def taken(n: str, root: Path) -> bool:
    path = root / "research" / "trials.csv"
    if not path.is_file():
        return False
    with path.open() as f:
        return any(r["test"] == n for r in csv.DictReader(f))


def main(argv=None, root: Path = ROOT) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("number", help="the next test number; check research/INDEX.md")
    ap.add_argument("name", help="snake_case, becomes espero/<name>.py and PREREGISTRATION_<NAME>.md")
    ap.add_argument("--forward", action="store_true", help="a forward test: adds the forward section")
    args = ap.parse_args(argv)
    n, name = args.number, args.name
    if not re.fullmatch(r"[a-z][a-z0-9_]*", name):
        print(f"name must be snake_case, got {name!r}", file=sys.stderr)
        return 2
    if taken(n, root):
        print(f"#{n} is already in research/trials.csv; take the next number", file=sys.stderr)
        return 2
    upper = name.upper()
    files = {root / "research" / f"PREREGISTRATION_{upper}.md":
             PREREG.format(n=n, title=name.replace("_", " "),
                           forward=FORWARD_NOTE.format(start=date.today().isoformat(), name=name)
                           if args.forward else ""),
             root / "espero" / f"{name}.py": MODULE.format(n=n, title=name.replace("_", " "), upper=upper,
                                                           name=name),
             root / "tests" / f"test_{name}.py": TEST.format(n=n, name=name)}
    for path in files:
        if path.exists():
            print(f"{path.relative_to(root)} exists; nothing written", file=sys.stderr)
            return 2
    for path, text in files.items():
        path.write_text(text)
        print(f"wrote {path.relative_to(root)}")
    print(f"""
left to do, in order (docs/HOW_IT_WORKS.md, "Adding a test"):
  1. write research/PREREGISTRATION_{upper}.md and commit it before computing anything
  2. write the rule in espero/{name}.py and its test; mutation-check the test
  3. claim them: espero/layers.py (a layer) and research/index.py (TESTS["{n}"]); regenerate both
  4. {"add the step to runner.run_daily and runner.PLANS; the ledger decides nothing" if args.forward
     else "run research/" + name + ".py once; write RESULTS_" + upper + ".md with the verdict as committed"}
  5. add #{n}'s row to research/trials.csv when judged; python scripts/status.py; ./scripts/check.sh""")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
