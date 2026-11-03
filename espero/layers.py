"""The package's layers: every module in exactly one, rendered into the README and held there by a test.

`espero/` is one flat folder on purpose: twelve tests, #48's seal and every loop address modules by
their current path. This table is the structure. A new module goes in one layer here, its first
docstring line becomes its description, and `tests/test_layers.py` fails until both are true and the
README's layout block has been regenerated:

    python -m espero.layers           # rewrite the block in README.md
    python -m espero.layers --check   # exit 1 if a module is unclaimed or the README is stale
"""
from __future__ import annotations

import re
import sys
from pathlib import Path
from typing import Dict, List, Tuple

PACKAGE = Path(__file__).resolve().parent
README = PACKAGE.parent / "README.md"
START, END = "<!-- layers:start -->", "<!-- layers:end -->"

# layer -> (what it is, its modules). Order is the order a reader meets them: data in, rules on it,
# the daily steps that apply them forward, the books that hold positions, what gets recorded, what
# gets measured, the path from a verdict to an order, and the commands that run it all.
LAYERS: Dict[str, Tuple[str, List[str]]] = {
    "core": ("market data, venues and the causal primitives every rule is built from",
             ["data", "hyperliquid", "kraken_futures", "coinbase_fees", "aggr", "coinm", "panel", "features",
              "indicators", "ops", "venues", "costs", "costs_table", "cash"]),
    "rules": ("one module per hypothesis: the frozen rule and its criteria, pure, no I/O",
              ["liq", "liqspike", "lows", "bids", "settle", "oi", "levetf", "levpush", "sweeps", "fillcost", "carry",
               "degen", "polyhour", "ethena", "horizons", "catchup", "bookwalk", "patterns", "trend", "factors",
               "signals", "regimes", "rate", "ladder", "liqvault", "oi5m", "volf", "edgewatch",
               "listdrift", "cascade"]),
    "forward": ("the daily job's steps: record a day, rebuild a ledger, decide nothing until 2027-03-31",
                ["liqfwd", "lowsfwd", "liqbreak", "fundsplit", "postclose", "bidsfwd", "settlefwd", "liqhold"]),
    "accounts": ("paper books and the machinery that holds a position honestly",
                 ["tsmom", "xs", "mf", "carry_paper", "hlpbook", "paper", "journal", "portfolio",
                  "execution", "backtest"]),
    "record": ("what Hyperliquid and aggr show only in the present, saved so it can be read later",
               ["hlcollect", "hlbook", "book", "manifest", "rawrec", "binance_archive", "tapewatch", "deribit"]),
    "measure": ("costs on prints, fills on tape, the point-in-time store and the ledger of every trial",
                ["markout", "execsim", "pit", "trials", "factor_eval", "detector", "audit", "tca", "reconcile",
                 "hl_exchange", "hlp_testnet", "rawbars", "replaysim", "robustness", "sleeves", "opalpha",
                 "costcurve", "costcurve_table"]),
    "live": ("from a verdict to a sized order, built and tested before any verdict; no mainnet path",
             ["latency", "approvals", "risk", "rungs", "holder"]),
    "operate": ("the commands, the screens, the scheduler and this table",
                ["cli", "ui", "runner", "loop", "lock", "notify", "dashboard", "report", "board", "carry_view",
                 "fast", "broker", "layers", "__init__", "__main__"]),
}

# the rest of the tree, by hand: it changes rarely
TAIL = """  tests/            # one test file per module, mutation-checked; test_layers.py holds this block current
  research/         # one pre-registration and one results file per test; INDEX.md claims every file
  data/             # committed fixtures, caches, tick days and recordings, by class (.gitignore says which)
  state/            # every account, journal, ledger, health.json and the dashboard (not in git)
  scripts/          # install the loops, move the state, fetch and publish data, scaffold a test
  deploy/launchd/   # the LaunchAgent templates the install scripts render
  docs/             # STATUS.md (generated), HOW_IT_WORKS.md, RUNBOOK.md, DATA.md, CHEATSHEET.md"""


def modules(package: Path = PACKAGE) -> List[str]:
    return sorted(p.stem for p in package.glob("*.py"))


def first_line(path: Path) -> str:
    """The first line of the module's docstring, or '' when it has none."""
    text = path.read_text(encoding="utf-8")
    m = re.search(r'^\s*(?:r|u)?"""(.*?)(?:"""|$)', text, re.S | re.M)
    code = re.search(r"^(?:import |from |def |class )", text, re.M)
    if not m or (code and m.start() > code.start()):
        return ""       # a docstring further down belongs to a function, not the module
    line = m.group(1).strip().splitlines()[0].strip() if m.group(1).strip() else ""
    if len(line) > 96:
        line = line[:96].rsplit(" ", 1)[0].rstrip(",;:") + " …"
    return line


def problems(package: Path = PACKAGE) -> List[str]:
    claimed: Dict[str, List[str]] = {}
    for layer, (_, mods) in LAYERS.items():
        for m in mods:
            claimed.setdefault(m, []).append(layer)
    out = [f"unclaimed: espero/{m}.py (add it to a layer in espero/layers.py)" for m in modules(package)
           if m not in claimed]
    out += [f"claimed twice: {m} in {layers}" for m, layers in claimed.items() if len(layers) > 1]
    present = set(modules(package))
    out += [f"{layer} lists {m}, which does not exist" for layer, (_, mods) in LAYERS.items() for m in mods
            if m not in present]
    return out


def render(package: Path = PACKAGE) -> str:
    lines = ["```", "espero/", "  espero/"]
    for layer, (what, mods) in LAYERS.items():
        lines.append(f"    # {layer}: {what}")
        for m in mods:
            if m in ("__init__", "__main__"):
                continue
            desc = first_line(package / f"{m}.py")
            lines.append(f"    {m + '.py':<18}# {desc}" if desc else f"    {m}.py")
    lines.append(TAIL)
    lines.append("```")
    return "\n".join(lines)


def block(readme: Path = README) -> str:
    text = readme.read_text(encoding="utf-8")
    a, b = text.find(START), text.find(END)
    if a < 0 or b < 0:
        return ""
    return text[a + len(START):b].strip("\n")


def write(readme: Path = README, package: Path = PACKAGE) -> None:
    text = readme.read_text(encoding="utf-8")
    a, b = text.find(START), text.find(END)
    if a < 0 or b < 0:
        raise RuntimeError(f"{readme} has no {START} / {END} markers")
    readme.write_text(text[:a + len(START)] + "\n" + render(package) + "\n" + text[b:], encoding="utf-8")


def main(argv=None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    bad = problems()
    for b in bad:
        print(b)
    if "--check" in argv:
        stale = block() != render()
        if stale:
            print("README.md's layout block is stale: run python -m espero.layers")
        return 1 if bad or stale else 0
    write()
    print(f"wrote the layout block in {README} ({len(modules())} modules in {len(LAYERS)} layers)")
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(main())
