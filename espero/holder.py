"""The account holder's answers, read from docs/HOLDER_INPUTS.md itself; until one is answered, its default holds.

Only the holder fills in the answers, in their own words, in a commit. Every default is the safe one: no capital,
no venue, no operator, no lift of the no-mainnet rule, no unattended orders. The risk gate takes its allocation
from `allocated_usd`, and the latency audit its operator's response time from `operator_response_s`, which an
answer can raise above the protocol's 4 hours but never lower.
"""
from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path
from typing import Dict, List, Optional, Tuple

ROOT = Path(__file__).resolve().parents[1]
DOC = ROOT / "docs" / "HOLDER_INPUTS.md"
START, END = "<!-- answers:start -->", "<!-- answers:end -->"
PROTOCOL_RESPONSE_S = 4 * 3600.0     # espero.latency.OPERATOR_RESPONSE_S, kept here so this module imports nothing

# id -> (kind, default until answered)
QUESTIONS: Dict[str, Tuple[str, object]] = {
    "capital_usd": ("usd", 0.0),
    "stop_drawdown": ("fraction", None),
    "venues_eligible": ("list", ()),
    "tax_and_licensing_checked": ("yesno", False),
    "operator_hours_per_week": ("number", 0.0),
    "operator_response_hours": ("number", None),
    "min_capital_usd": ("usd", None),
    "venue_loss_usd": ("usd", None),
    "data_budget_usd_month": ("usd", 0.0),
    "totp_set_up": ("yesno", False),
    "autonomy": ("yesno", False),
    "mainnet_lift": ("path", None),
}
YES, NO = ("yes", "y", "true"), ("no", "n", "false")


def rows(doc: Path = DOC) -> Dict[str, str]:
    """The raw answers between the markers: | `id` | question | answer | default |, by id."""
    text = doc.read_text(encoding="utf-8")
    a, b = text.find(START), text.find(END)
    if a < 0 or b < 0:
        return {}
    out = {}
    for line in text[a:b].splitlines():
        m = re.match(r"^\|\s*`([a-z_]+)`\s*\|([^|]*)\|([^|]*)\|", line)
        if m:
            out[m.group(1)] = m.group(3).strip()
    return out


def parse(kind: str, raw: str):
    """One answer as its kind, or ValueError. An empty answer is None: not answered."""
    raw = raw.strip()
    if not raw:
        return None
    if kind in ("usd", "number"):
        v = float(raw.replace(",", "").replace("$", ""))
        if v < 0:
            raise ValueError("a negative amount")
        return v
    if kind == "fraction":
        v = float(raw.rstrip("%")) / (100.0 if raw.endswith("%") else 1.0)
        if not -1.0 < v < 0.0:
            raise ValueError("a drawdown is a loss between 0 and -100 %")
        return v
    if kind == "list":
        return tuple(x.strip().lower() for x in raw.split(",") if x.strip())
    if kind == "yesno":
        if raw.lower() in YES:
            return True
        if raw.lower() in NO:
            return False
        raise ValueError("answer yes or no")
    if kind == "path":
        return raw.strip("`")
    raise ValueError(f"unknown kind {kind}")


def answers(doc: Path = DOC) -> Dict[str, object]:
    """Every question's answer, or its default when unanswered or unreadable (problems() says which)."""
    raw = rows(doc)
    out = {}
    for qid, (kind, default) in QUESTIONS.items():
        try:
            v = parse(kind, raw.get(qid, ""))
        except ValueError:
            v = None
        out[qid] = default if v is None else v
    return out


def problems(doc: Path = DOC, root: Path = ROOT) -> List[str]:
    raw = rows(doc)
    out = [f"{qid}: not a question here" for qid in raw if qid not in QUESTIONS]
    if doc == DOC and not committed(doc, root):
        out.append(f"{doc.name}: not what HEAD holds (or no git): an answer counts only once it is committed")
    out += [f"{qid}: missing from the answers table" for qid in QUESTIONS if qid not in raw]
    for qid, (kind, _) in QUESTIONS.items():
        try:
            v = parse(kind, raw.get(qid, ""))
        except ValueError as exc:
            out.append(f"{qid}: {raw.get(qid)!r} is not an answer ({exc})")
            continue
        if kind == "path" and v and not (root / v).is_file():
            out.append(f"{qid}: {v} does not exist")
    return out


def committed(doc: Path = DOC, root: Path = ROOT) -> bool:
    """True when the page on disk is byte for byte what HEAD holds. An answer counts only in the holder's own
    commit, so an edit not yet committed, a page outside a git checkout, or no git at all count as unanswered."""
    try:
        rel = Path(doc).resolve().relative_to(Path(root).resolve()).as_posix()
        r = subprocess.run(["git", "-C", str(root), "show", f"HEAD:{rel}"], capture_output=True, timeout=30)
        return r.returncode == 0 and r.stdout == Path(doc).read_bytes()
    except (ValueError, OSError, subprocess.SubprocessError):
        return False


def allocated_usd(doc: Optional[Path] = None) -> float:
    """The capital the risk gate may size against: 0 until the holder writes a number, and commits it."""
    doc = DOC if doc is None else doc
    if doc == DOC and not committed(doc, ROOT):
        return 0.0
    return float(answers(doc)["capital_usd"] or 0.0)


def operator_response_s(doc: Path = DOC) -> float:
    """The operator's response time: the protocol's 4 hours, or the holder's slower answer. Never faster."""
    hours: Optional[float] = answers(doc)["operator_response_hours"]
    return max(PROTOCOL_RESPONSE_S, hours * 3600.0) if hours else PROTOCOL_RESPONSE_S


def eligible(venue: str, doc: Optional[Path] = None) -> bool:
    """A venue the holder has checked against its current terms, and whose tax and licensing they have checked,
    in a commit."""
    doc = DOC if doc is None else doc
    if doc == DOC and not committed(doc, ROOT):
        return False
    a = answers(doc)
    return bool(a["tax_and_licensing_checked"]) and venue.lower() in a["venues_eligible"]


def main(argv=None) -> int:
    for p in problems():
        print(p, file=sys.stderr)
    for qid, v in answers().items():
        print(f"{qid:28s} {v!r}")
    return 1 if problems() else 0


if __name__ == "__main__":
    sys.exit(main())
