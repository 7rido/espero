"""The holder's inputs and the mainnet lift, filled in by a guided form instead of by editing a table.

`espero holder --fill` (or "Your answers" on the home screen) asks each question of docs/HOLDER_INPUTS.md in plain
words, one at a time, with the current answer as the default, checks every answer with `espero.holder.parse` before
it is written, and writes only the answer column. It can then take down the holder's lift of the no-mainnet rule
(research/DESIGN_MAINNET_PATH.md, guard 3) and commit both, signed with the holder's own key.

The lift stays the holder's: the form offers no sentence, prefills no wording and refuses an empty statement. It
only lays the holder's own words and figures out in the form the mainnet module will read. An agent never runs it.
"""
from __future__ import annotations

import re
import subprocess
from datetime import date
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

from . import holder as H

START, END = "<!-- answers:start -->", "<!-- answers:end -->"
LIFT = Path("research") / "MAINNET_LIFT.md"
MIN_STATEMENT = 40          # characters: a sentence of the holder's own, not a word

# id -> (the question in plain words, a hint shown under it, how it is asked)
PLAIN: Dict[str, Tuple[str, str, str]] = {
    "capital_usd": ("How many dollars do you give this system to trade with?",
                    "only this money is ever at risk; 0 means nothing trades", "usd"),
    "stop_drawdown": ("How far may the account fall from its best point before everything stops?",
                      "a percent, like 10 for a 10% fall", "drawdown"),
    "venues_eligible": ("Which venues have you checked are open to you, in your country, under their current terms?",
                        "space to tick, enter when done", "venues"),
    "tax_and_licensing_checked": ("Have you checked your own country's tax and licensing rules for perpetual futures?",
                                  "until yes, no venue may be used", "yesno"),
    "operator_hours_per_week": ("How many hours a week will you be on hand to answer the system's proposals?",
                                "0 means rules that wait for you are not traded", "number"),
    "operator_response_hours": ("When you are on hand, how quickly do you answer a proposal?",
                                "like 10 minutes, 2 hours, or 1.5", "duration"),
    "min_capital_usd": ("Below how many dollars is running this not worth your time?",
                        "leave empty if you do not know yet", "usd"),
    "venue_loss_usd": ("How many dollars could you bear to lose if one venue failed outright?",
                       "leave empty if you do not know yet", "usd"),
    "data_budget_usd_month": ("How many dollars a month will you pay for data or an always-on machine?",
                              "0 means nothing is bought", "usd"),
    "totp_set_up": ("Have you set up the one-time code you approve trades with (docs/OPERATOR.md)?",
                    "until yes, no approval can be given", "yesno"),
    "autonomy": ("May the machine place orders on its own, without your yes, for rules too fast for a person?",
                 "no keeps every trade waiting for you", "yesno"),
}

LIFT_FIELDS: Dict[str, str] = {
    "venue": "the one venue the lift covers",
    "coins": "the coins, comma-separated",
    "max_order_usd": "the largest single order, in dollars",
    "max_position_usd": "the largest position in one coin, in dollars",
    "expiry": "the date the lift lapses, YYYY-MM-DD",
    "rule": "the test number of the rule the canary trades",
    "approval": "who approves each trade",
    "machine": "the hash of the one Mac allowed to sign",
}

_DURATION = re.compile(r"^\s*([0-9]*\.?[0-9]+)\s*(m|min|mins|minute|minutes|h|hr|hrs|hour|hours)?\s*$", re.I)


def _plain_number(x: float) -> str:
    return f"{x:.4f}".rstrip("0").rstrip(".") if x != int(x) else str(int(x))


def to_stored(qid: str, raw) -> str:
    """The holder's input as the table stores it, checked by espero.holder.parse; ValueError if it is not an answer.
    An empty input is "" (not answered). A drawdown typed as 10 or 10% is stored as -10%; a duration in minutes is
    stored in hours; a venue list is lower case, comma-separated; yes or no is a bool or the word."""
    if qid not in H.QUESTIONS:
        raise ValueError(f"{qid} is not a question on the page")
    kind = H.QUESTIONS[qid][0]
    how = PLAIN.get(qid, ("", "", kind))[2]
    if isinstance(raw, bool):
        stored = "yes" if raw else "no"
    elif isinstance(raw, (list, tuple)):
        stored = ", ".join(str(v).strip().lower() for v in raw if str(v).strip())
    else:
        text = str(raw).strip()
        if not text:
            return ""
        if how == "drawdown":
            v = float(text.rstrip("%").strip().lstrip("-").strip())
            stored = f"-{_plain_number(v)}%"
        elif how == "duration":
            m = _DURATION.match(text)
            if not m:
                raise ValueError("a time, like 10 minutes or 2 hours")
            v = float(m.group(1))
            unit = (m.group(2) or "h").lower()
            stored = _plain_number(v / 60.0 if unit.startswith("m") else v)
        elif how == "usd":
            stored = _plain_number(float(text.replace(",", "").replace("$", "")))
        else:
            stored = text
    if "|" in stored or "\n" in stored:
        raise ValueError("an answer cannot hold | or a line break")
    H.parse(kind, stored)
    return stored


def set_answers(text: str, answers: Dict[str, str]) -> str:
    """The page with the answer column of each id in `answers` replaced, and nothing else changed. KeyError for an
    id the table does not hold; ValueError for a value that would break the table."""
    a, b = text.find(START), text.find(END)
    if a < 0 or b < 0:
        raise KeyError("the answers table's markers are missing")
    left = dict(answers)
    lines = text[a:b].split("\n")
    for i, line in enumerate(lines):
        m = re.match(r"^\|\s*`([a-z_]+)`\s*\|", line)
        if not m or m.group(1) not in left:
            continue
        value = left.pop(m.group(1))
        if "|" in value or "\n" in value:
            raise ValueError(f"{m.group(1)}: an answer cannot hold | or a line break")
        cells = line.split("|")
        cells[3] = f" {value} " if value else " "
        lines[i] = "|".join(cells)
    if left:
        raise KeyError(f"not in the table: {sorted(left)}")
    return text[:a] + "\n".join(lines) + text[b:]


def check_lift(statement: str, fields: Dict[str, str], today: date,
               eligible: Optional[Sequence[str]] = None) -> List[str]:
    """What is wrong with a lift before it is written; empty when it can be. Each problem starts with the field it
    is about, or with "statement", so the form can ask that one again."""
    out = []
    if len(statement.strip()) < MIN_STATEMENT:
        out.append(f"statement: yours to write, in full sentences, at least {MIN_STATEMENT} characters")
    venue = str(fields.get("venue", "")).strip().lower()
    if "," in venue or " " in venue:
        out.append("venue: the lift covers one venue; a second venue takes a lift of its own")
    elif venue and eligible is not None and venue not in [v.lower() for v in eligible]:
        out.append(f"venue: {venue} is not among the venues you marked open to you")
    for k in LIFT_FIELDS:
        v = str(fields.get(k, "")).strip()
        if not v:
            out.append(f"{k}: missing")
        elif "|" in v or "\n" in v:
            out.append(f"{k}: cannot hold | or a line break")
    try:
        order, position = float(fields.get("max_order_usd", "")), float(fields.get("max_position_usd", ""))
        if not 0 < order <= position:
            out.append("max_order_usd: above 0 and no larger than the largest position")
    except ValueError:
        out.append("max_order_usd: the largest order and position are numbers of dollars")
    try:
        if date.fromisoformat(str(fields.get("expiry", ""))) <= today:
            out.append("expiry: a date after today")
    except ValueError:
        out.append("expiry: a date, YYYY-MM-DD, like 2027-01-31")
    return out


def lift_document(statement: str, fields: Dict[str, str], today: date) -> str:
    """The lift as the mainnet module reads it: the holder's own statement, verbatim, then the answers block."""
    problems = check_lift(statement, fields, today)
    if problems:
        raise ValueError("; ".join(problems))
    rows = "\n".join(f"| `{k}` | {str(fields[k]).strip()} |" for k in LIFT_FIELDS)
    return (f"# The holder lifts the no-mainnet rule\n\n**Written by the account holder on {today.isoformat()}, "
            f"in their own words, and committed with their signature.** research/DESIGN_MAINNET_PATH.md, guard 3, "
            f"reads the block below; the words above it are the holder's and nobody else's.\n\n{statement.strip()}\n\n"
            f"{START}\n| id | answer |\n|---|---|\n{rows}\n{END}\n")


def lift_answers(text: str) -> Dict[str, str]:
    """The lift's answers block, by id."""
    a, b = text.find(START), text.find(END)
    if a < 0 or b < 0:
        return {}
    out = {}
    for line in text[a:b].splitlines():
        m = re.match(r"^\|\s*`([a-z_]+)`\s*\|([^|]*)\|", line)
        if m:
            out[m.group(1)] = m.group(2).strip()
    return out


def machine_hash() -> str:
    """The first 16 hex characters of the SHA-256 of this Mac's platform UUID: not a secret, a name for the machine."""
    import hashlib

    out = subprocess.run(["ioreg", "-rd1", "-c", "IOPlatformExpertDevice"], capture_output=True, text=True, timeout=30)
    m = re.search(r'"IOPlatformUUID"\s*=\s*"([^"]+)"', out.stdout)
    if not m:
        raise OSError("no platform UUID: not a Mac, or ioreg refused")
    return hashlib.sha256((m.group(1) + "\n").encode()).hexdigest()[:16]


def commit_signed(root: Path, paths: Sequence[str], message: str) -> subprocess.CompletedProcess:
    """git add and a signed commit, run by the holder in their own terminal: git asks for their key's passphrase."""
    subprocess.run(["git", "-C", str(root), "add", "--", *paths], check=True)
    return subprocess.run(["git", "-C", str(root), "commit", "-S", "-m", message, "--", *paths])


# ------------------------------------------------------------------------------------------------- the form
def _ask_one(questionary, style, qid: str, current: str, venues: Iterable[str]) -> Optional[str]:
    question, hint, how = PLAIN[qid]
    prompt = f"{question}\n  ({hint})"
    while True:
        if how == "yesno":
            raw = questionary.select(prompt, choices=["yes", "no"], default="yes" if current == "yes" else "no",
                                     style=style, pointer="❯").ask()
        elif how == "venues":
            have = {v.strip().lower() for v in current.split(",") if v.strip()}
            raw = questionary.checkbox(prompt, choices=[questionary.Choice(v, checked=v in have) for v in venues],
                                       style=style).ask()
        else:
            raw = questionary.text(prompt, default=current, style=style).ask()
        if raw is None:
            return None
        try:
            return to_stored(qid, raw)
        except ValueError as exc:
            print(f"  not saved: {exc}. Try again, or leave it empty.")


def run(root: Path = H.ROOT, today: Optional[date] = None) -> int:
    """The guided form. Writes docs/HOLDER_INPUTS.md (and, if the holder chooses, research/MAINNET_LIFT.md) only
    after the holder confirms, and commits only if they choose to sign."""
    try:
        import questionary
        from questionary import Style
        from rich.console import Console
        from rich.table import Table
    except ImportError:
        print("the form needs the tui extra: pip install -e '.[tui]'")
        return 2
    from .venues import VENUES

    style = Style([("qmark", "fg:#7aa2f7 bold"), ("pointer", "fg:#7aa2f7 bold"), ("highlighted", "fg:#7aa2f7 bold")])
    console = Console()
    today = today or date.today()
    doc = root / "docs" / "HOLDER_INPUTS.md"
    text = doc.read_text(encoding="utf-8")
    current = H.rows(doc)
    venues = [v for v in sorted(VENUES) if v != "perp"]

    console.print("[bold]Your answers[/bold]: one question at a time. Enter keeps the answer shown; "
                  "Ctrl-C leaves without saving anything.\n")
    new: Dict[str, str] = {}
    for qid in PLAIN:
        v = _ask_one(questionary, style, qid, current.get(qid, ""), venues)
        if v is None:
            console.print("left; nothing saved")
            return 1
        new[qid] = v

    lift_text: Optional[str] = None
    if questionary.confirm("Do you want to write your lift of the no-mainnet rule now?", default=False,
                           style=style).ask():
        console.print("\nThe lift is yours: write in your own words that you lift the rule, why, and what the canary "
                      "may do. Nothing is filled in for you. Finish with Esc then Enter.")
        old = lift_answers((root / LIFT).read_text()) if (root / LIFT).is_file() else {}
        statement = ""
        fields: Dict[str, str] = {k: old.get(k, "") for k in LIFT_FIELDS}
        if not fields["machine"]:
            try:
                fields["machine"] = machine_hash()
            except OSError:
                pass
        eligible = [v.strip() for v in new.get("venues_eligible", "").split(",") if v.strip()]
        ask = ["statement"] + list(LIFT_FIELDS)
        while ask:
            for k in ask:
                if k == "statement":
                    statement = questionary.text("Your statement:", default=statement, multiline=True,
                                                 style=style).ask() or ""
                else:
                    fields[k] = (questionary.text(f"{k}: {LIFT_FIELDS[k]}", default=fields[k],
                                                  style=style).ask() or "").strip()
            problems = check_lift(statement, fields, today, eligible)
            if not problems:
                break
            console.print("\n[red bold]The lift is not written yet.[/red bold] Fix these, or choose to leave it:")
            for p in problems:
                console.print(f"  [red]-[/red] {p}")
            if not questionary.confirm("Fix them now?", default=True, style=style).ask():
                console.print("[red]The lift is left unwritten.[/red] Your other answers can still be saved.")
                break
            ask = []
            for k in (p.split(":", 1)[0] for p in problems):     # a size problem asks both sizes again
                for again in (("max_order_usd", "max_position_usd") if k == "max_order_usd" else (k,)):
                    if again not in ask:
                        ask.append(again)
        if not problems:
            lift_text = lift_document(statement, fields, today)
            new["mainnet_lift"] = LIFT.as_posix()

    table = Table(title="What will be saved", show_lines=False)
    table.add_column("question")
    table.add_column("answer")
    for qid, v in new.items():
        table.add_row(PLAIN[qid][0] if qid in PLAIN else qid, v or "[dim](not answered)[/dim]")
    console.print(table)
    if lift_text:
        console.print("\n[bold]Your lift, as it will be written:[/bold]\n" + lift_text)
    else:
        console.print("\n[bold]No lift in this save.[/bold] The no-mainnet rule stands.")
    if not questionary.confirm("Save these?", default=True, style=style).ask():
        console.print("nothing saved")
        return 1
    doc.write_text(set_answers(text, new), encoding="utf-8")
    paths = ["docs/HOLDER_INPUTS.md"]
    if lift_text:
        (root / LIFT).write_text(lift_text, encoding="utf-8")
        paths.append(LIFT.as_posix())
    console.print("saved. An answer counts only once it is committed.")
    if questionary.confirm("Commit and sign them now? (git asks for your key's passphrase)", default=True,
                           style=style).ask():
        reason = questionary.text("A short reason, for the commit message:", style=style).ask() or ""
        message = "The holder's answers" + (f": {reason.strip()}" if reason.strip() else "")
        r = commit_signed(root, paths, message)
        if r.returncode != 0:
            console.print("[red]the commit did not go through.[/red] Your answers are saved; commit them with:\n"
                          f"  git add {' '.join(paths)} && git commit -S -m \"{message}\"")
            return 1
        console.print("committed and signed.")
    return 0
