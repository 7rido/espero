"""research/INDEX.md: every file in research/, claimed by the test it belongs to.

The folder is flat on purpose. 47 scripts find their inputs and outputs by name under `research/`,
twelve tests load scripts and reference rows by path, #48 seals files by path, and 229 links in
the documents point at each other, so moving a file would rewrite committed artifacts. This index
is the structure instead: one section per test number, listing its documents, script, run log,
events and manifests, with the status `trials.csv` records. `tests/test_research_index.py` holds
every file in the folder to exactly one claim and holds the committed INDEX.md to this script's
output, so a new file without an owner fails CI.

    .venv/bin/python research/index.py          # rewrite INDEX.md
    .venv/bin/python research/index.py --check  # exit 1 if INDEX.md is stale or a file is unclaimed
"""
from __future__ import annotations

import csv
import sys
from fnmatch import fnmatch
from pathlib import Path
from typing import Dict, List, Tuple

ROOT = Path(__file__).resolve().parents[1]
RESEARCH = ROOT / "research"
INDEX = RESEARCH / "INDEX.md"

# test number -> (name, patterns of the files that belong to it). A pattern is a file name or a
# glob, relative to research/. "16, 17" is one entry: the two tests share one script and one result.
TESTS: Dict[str, Tuple[str, List[str]]] = {
    "1": ("Funding extremes, directional", ["FINDINGS.md", "funding_edge.py"]),
    "2": ("Cross-sectional momentum, top-1", ["PREREGISTRATION.md", "RESULTS.md", "momentum.py"]),
    "3": ("Polymarket liquidity provision", ["LP_NOTES.md", "lp_sim.py", "lp_scan.py"]),
    "4": ("Cross-asset TSMOM", ["PREREGISTRATION_TSMOM.md", "RESULTS_TSMOM.md", "tsmom.py"]),
    "5": ("Post-earnings announcement drift", ["PREREGISTRATION_PEAD.md", "RESULTS_PEAD.md", "pead.py"]),
    "6": ("Crypto-policy odds composite", ["PREREGISTRATION_ODDS.md", "RESULTS_ODDS.md", "odds_signal.py",
                                           "odds_basket.json"]),
    "7": ("Cross-sectional momentum, top-5 of 21", ["PREREGISTRATION_XS20.md", "RESULTS_XS20.md", "xs20.py"]),
    "8": ("Multi-factor cross-sectional crypto", ["PREREGISTRATION_MF.md", "RESULTS_MF.md", "FORWARD_MF.md",
                                                   "multifactor.py"]),
    "9": ("BTC lead-lag into altcoins", ["PREREGISTRATION_LEADLAG.md", "RESULTS_LEADLAG.md", "leadlag.py",
                                         "leadlag_run_*.txt"]),
    "9b": ("BTC lead-lag, beta-scaled", ["PREREGISTRATION_LEADLAG2.md", "RESULTS_LEADLAG2.md"]),
    "10": ("Altcoin breakout chasing, 5-minute", ["PREREGISTRATION_DEGEN.md", "RESULTS_DEGEN.md",
                                                  "degen_backtest.txt"]),
    "11": ("Perp funding carry, delta-neutral", ["PREREGISTRATION_CARRY.md", "RESULTS_CARRY.md", "carry.py",
                                                 "carry_fetch.txt", "carry_run.txt"]),
    "12": ("Carry with swap gap and maker execution", ["PREREGISTRATION_CARRY2.md", "RESULTS_CARRY2.md",
                                                       "carry2_run.txt"]),
    "13": ("Altcoin breakout chasing, 1-hour", ["PREREGISTRATION_DEGEN2.md", "RESULTS_DEGEN2.md",
                                                "degen2_backtest.txt", "degen2_control.txt"]),
    "14": ("#12's carry rule on Kraken Futures", ["PREREGISTRATION_CARRY3.md", "RESULTS_CARRY3.md",
                                                  "carry_kraken.py", "carry_kraken_run.txt"]),
    "15": ("Multi-asset trend, vol-sized", ["PREREGISTRATION_TREND.md", "RESULTS_TREND.md", "trend.py",
                                            "trend_run.txt"]),
    "16, 17": ("Altcoins led by their peer basket; ETH-ecosystem coins led by ETH",
               ["PREREGISTRATION_PEERS.md", "RESULTS_PEERS.md", "peers.py", "peers_run.txt"]),
    "18": ("Liquidations as a breakout filter", ["PREREGISTRATION_LIQ.md", "RESULTS_LIQ.md", "liq.py",
                                                 "liq_events.csv", "liq_manifest.json", "liq_run.txt"]),
    "19": ("The funding settlement as a price event", ["PREREGISTRATION_SETTLE.md", "RESULTS_SETTLE.md",
                                                       "settle.py", "settle_events.csv", "settle_manifest.json",
                                                       "settle_run.txt"]),
    "20": ("New 4-hour lows on volume bounce", ["PREREGISTRATION_LOWS.md", "RESULTS_LOWS.md", "lows.py",
                                                "lows_events.csv.gz", "lows_manifest.json", "lows_run.txt"]),
    "21": ("Liquidation spikes reverse, and the exploration that suggested it",
           ["PREREGISTRATION_LIQSPIKE.md", "RESULTS_LIQSPIKE.md", "liqspike.py", "liqspike_events.csv",
            "liqspike_run.txt", "EXPLORE_AGGR_LIQ.md", "aggr_explore.py", "aggr_explore_run.txt",
            "aggr_holdout_manifest.json", "aggr_explore/*"]),
    "22": ("Forward: long-liquidation spikes bought", ["FORWARD_LIQ.md"]),
    "23": ("Forward: short-liquidation spikes", ["FORWARD_LIQSHORT.md"]),
    "24": ("Forward: new 4-hour lows", ["FORWARD_LOWS.md"]),
    "25": ("Breakdowns made of closing positions", ["PREREGISTRATION_OI.md", "RESULTS_OI.md", "oi.py",
                                                    "oi_events.csv.gz", "oi_manifest.json", "oi_run.txt"]),
    "26": ("#18's rule on COIN-M liquidations", ["PREREGISTRATION_LIQ2.md", "RESULTS_LIQ2.md", "liq2.py",
                                                 "liq2_events.csv.gz", "liq2_manifest.json", "liq2_run.txt"]),
    "27": ("Forward: #26's rule on live data", ["FORWARD_LIQBREAK.md"]),
    "28": ("Leveraged ETFs push crypto into the US close", ["PREREGISTRATION_LEVETF.md", "RESULTS_LEVETF.md",
                                                            "levetf.py", "levetf_days.csv.gz", "levetf_manifest.json",
                                                            "levetf_run.txt"]),
    "29": ("Forward: the US session's move after the close", ["FORWARD_POSTCLOSE.md"]),
    "30": ("Resting bids catch forced sellers", ["PREREGISTRATION_BIDS.md", "RESULTS_BIDS.md", "bids.py",
                                                 "bids_events.csv.gz", "bids_manifest.json", "bids_run.txt"]),
    "31": ("Forward: resting bids two ATRs under breakdowns", ["FORWARD_BIDS2.md"]),
    "32": ("Forward: forced down-breaks split by funding", ["FORWARD_FUNDSPLIT.md"]),
    "33": ("What the 00:00 UTC fills cost", ["PREREGISTRATION_FILLCOST.md", "RESULTS_FILLCOST.md", "fillcost.py",
                                             "fillcost_events.csv.gz", "fillcost_run.txt"]),
    "34": ("2x funds push small coins into the close", ["PREREGISTRATION_LEVPUSH.md", "RESULTS_LEVPUSH.md",
                                                        "levpush.py", "levpush_days.csv.gz", "levpush_run.txt"]),
    "35": ("Stop runs at yesterday's low reverse", ["PREREGISTRATION_SWEEPS.md", "RESULTS_SWEEPS.md", "sweeps.py",
                                                    "sweeps_events.csv.gz", "sweeps_run.txt"]),
    "36": ("Ethena's USDe flows forecast funding", ["PREREGISTRATION_ETHENA.md", "RESULTS_ETHENA.md", "ethena.py",
                                                    "ethena_run.txt", "ethena_usde.json.gz"]),
    "37": ("Polymarket's hourly crowd against a random walk", ["PREREGISTRATION_POLYHOUR.md", "RESULTS_POLYHOUR.md",
                                                               "polyhour.py", "polyhour_markets.csv.gz",
                                                               "polyhour_run.txt"]),
    "38": ("Forward: the price after a settlement where shorts pay", ["FORWARD_SHORTSPAY.md"]),
    "39": ("What a fill costs, measured on prints", ["PREREGISTRATION_MARKOUT.md", "RESULTS_MARKOUT.md", "markout.py",
                                                     "markout_days.csv.gz", "markout_fetch.txt",
                                                     "markout_fetch_liqfix.txt", "markout_manifest.json",
                                                     "markout_run.txt", "markout_run_liqfix.txt",
                                                     "markout_settle.csv.gz", "markout_stats.csv.gz"]),
    "40": ("Fill reconciliation on the Hyperliquid testnet", ["PREREGISTRATION_TESTNET.md", "RESULTS_TESTNET.md",
                                                              "testnet_check.py", "testnet_run.txt",
                                                              "testnet_session.json"]),
    "41": ("#39 on eight smaller coins", ["PREREGISTRATION_MARKOUT_SMALL.md", "RESULTS_MARKOUT_SMALL.md",
                                          "markout_small.py", "markout_small_*"]),
    "42": ("Dress rehearsal of a real-fill test on testnet", ["PREREGISTRATION_REHEARSAL.md", "RESULTS_REHEARSAL.md",
                                                              "rehearsal.py", "rehearsal_run.txt",
                                                              "rehearsal_session.json"]),
    "43": ("At which holding period do real signals pay", ["PREREGISTRATION_HORIZONS.md", "RESULTS_HORIZONS.md",
                                                           "horizons.py", "horizons_*"]),
    "44": ("Day-mean against trade-weighted summaries", ["PREREGISTRATION_DAYMEAN_AUDIT.md",
                                                         "RESULTS_DAYMEAN_AUDIT.md", "daymean_audit.py",
                                                         "daymean_audit.csv", "daymean_audit_run.txt"]),
    "45": ("Forward: forced down-breaks held 4 h, 12 h, 1 day", ["FORWARD_LIQHOLD.md"]),
    "48": ("The point-in-time store and the execution answer", ["RESULTS_SUBSTRATE.md",
                                                                "PREREGISTRATION_EXEC_ANSWER.md", "substrate_*",
                                                                "pit_*"]),
    "49": ("A day of book imbalance and the next day", ["PREREGISTRATION_DEPTHDAY.md"]),
    "50": ("The 1-10 rating, and the regime follow-on that closed at its power bar",
           ["RATING.md", "PLAN_REGIMES.md", "REGIME_*.md", "regime_count.py", "regime_gate.py",
            "regime_inventory.csv"]),
    "51": ("What a market order costs walking a recorded book", ["PREREGISTRATION_BOOKWALK.md", "RESULTS_BOOKWALK.md",
                                                                 "bookwalk.py", "bookwalk_*"]),
    "52, 53, 54, 55, 56": ("Descriptive patterns for the operator", ["PREREGISTRATION_PATTERNS.md",
                                                                     "RESULTS_PATTERNS.md", "patterns.py",
                                                                     "patterns_info.py", "patterns_5*"]),
    "57": ("What is left of Hyperliquid's catch-up after a delay", ["PREREGISTRATION_CATCHUP.md",
                                                                    "RESULTS_CATCHUP.md", "catchup.py",
                                                                    "catchup_events.csv.gz", "catchup_output.txt"]),
    "58": ("Forward: HLP's absorbed inventory, and the mechanism memo behind it",
           ["FORWARD_HLP.md", "MECHANISM_LIQUIDATION.md", "RESULTS_HLABSORB.md"]),
    "59": ("Forward: #58 with a guard against failed reads", ["FORWARD_HLP2.md"]),
    "60": ("Forward: the liquidation ladder", ["FORWARD_LADDER.md"]),
    "61": ("aggr's forward bars rebuilt from the raw streams", ["PREREGISTRATION_RAWBARS.md",
                                                                "PREREGISTRATION_RAWBARS.md.ots", "rawbars.py",
                                                                "rawbars_*"]),
    "62": ("The paper fills replayed on the recorded book", ["PREREGISTRATION_REPLAYSIM.md",
                                                             "PREREGISTRATION_REPLAYSIM.md.ots", "replaysim.py",
                                                             "replaysim_*"]),
    "63": ("The portfolio layer: how passes combine, fixed before any two exist", ["PREREGISTRATION_SLEEVES.md",
                                                                                   "PREREGISTRATION_SLEEVES.md.ots",
                                                                                   "sleeves.py"]),
    "64": ("Forward: the liquidator vault's inventory", ["FORWARD_LIQVAULT.md", "FORWARD_LIQVAULT.md.ots"]),
    "65": ("Forward: a sharp 5-minute fall read by its open interest", ["FORWARD_OI5M.md", "FORWARD_OI5M.md.ots"]),
    "66": ("A HAR volatility forecast against the books' trailing variance", ["EXPLORE_VOLF.md", "volf.py", "volf_design_run.txt",
                                                                         "PREREGISTRATION_VOLF.md", "PREREGISTRATION_VOLF.md.ots",
                                                                         "RESULTS_VOLF.md", "volf_run.txt", "volf_series.csv"]),
    "67": ("New Binance USD-M perps after they list, short against BTC", ["EXPLORE_LISTDRIFT.md", "listdrift.py", "listdrift_events.csv",
                                                                            "listdrift_manifest.csv", "listdrift_design_run.txt",
                                                                            "listdrift_design_run_onboard.txt",
                                                                            "listdrift_design_run_nocover.txt",
                                                                            "listdrift_design_run_cover.txt", "PREREGISTRATION_LISTDRIFT.md",
                                                                            "PREREGISTRATION_LISTDRIFT.md.ots",
                                                                            "RESULTS_LISTDRIFT.md", "listdrift_run.txt", "listdrift_series.csv"]),
    "68": ("A cost curve by order size on Hyperliquid, from #51's book files", ["PREREGISTRATION_COSTCURVE.md", "costcurve.py",
                                                                                  "costcurve_run.txt", "costcurve_days.csv",
                                                                                  "costcurve_buckets.csv", "RESULTS_COSTCURVE.md"]),
    "69": ("Operator alpha: what the operator's overrides earned against the rule", ["PREREGISTRATION_OPALPHA.md",
                                                                                    "PREREGISTRATION_OPALPHA.md.ots"]),
    "70": ("Edgewatch: the live stop rule, is this sleeve still the registered edge?", ["PREREGISTRATION_EDGEWATCH.md",
                                                                                      "PREREGISTRATION_EDGEWATCH.md.ots"]),
    "72": ("Open interest as a next-day cascade forecast, beyond volatility", ["EXPLORE_CASCADE.md", "cascade.py", "cascade_design_run.txt", "PREREGISTRATION_CASCADE.md", "PREREGISTRATION_CASCADE.md.ots",
                                                                           "RESULTS_CASCADE.md", "cascade_run.txt", "cascade_series.csv", "cascade_cells.csv.gz"]),
}

# files that belong to the project as a whole, not to one test
CROSS_CUTTING: Dict[str, List[str]] = {
    "The ledger of every test": ["trials.csv", "trials_dsr.csv", "trials_scored.csv", "trials_spa_series.csv",
                                 "trials_summary.json", "fdr_rescore.py", "FDR_STANDARD.md", "ROBUSTNESS_STANDARD.md"],
    "What a pass leads to, and what is still untested": ["FORWARD_FAMILY.md", "IDEAS_NOVEL.md", "ERRATA.md",
                                                        "EXPLORE_OI5M.md", "oi5m_explore.py", "oi5m_explore_run.txt",
                                                          "OPERATOR_READOUT.md"],
    "Costs and venues": ["RECHECK_COSTS.md", "VENUE_CONFIRMATION.md", "VENUE_NONUS.md", "HL_ARCHIVE.md"],
    "From a verdict to an order": ["LIVE_LATENCY.md", "RISK_POLICY.md", "DEPLOYMENT_LADDER.md", "TEMPLATE_SIZING.md",
                                   "ROBUSTNESS_LIVE.md", "DESIGN_MAINNET_PATH.md"],
    "This index": ["index.py"],
}

# bytecode, the scripts' download caches, and the index itself, so its output doesn't depend on itself
IGNORED = ("__pycache__/*", "data/*", "INDEX.md")


def files() -> List[str]:
    """Every file under research/, relative POSIX path, caches and bytecode left out."""
    out = []
    for p in sorted(RESEARCH.rglob("*")):
        if not p.is_file():
            continue
        rel = p.relative_to(RESEARCH).as_posix()
        if not any(fnmatch(rel, pat) for pat in IGNORED):
            out.append(rel)
    return out


def claims(all_files: List[str]) -> Dict[str, List[str]]:
    """File -> the entries that claim it. Every file should have exactly one."""
    owners: Dict[str, List[str]] = {f: [] for f in all_files}
    for owner, (_, patterns) in list(TESTS.items()) + [(k, ("", v)) for k, v in CROSS_CUTTING.items()]:
        for pat in patterns:
            matched = [f for f in all_files if f == pat or fnmatch(f, pat)]
            for f in matched:
                owners[f].append(owner)
    return owners


def problems(all_files: List[str]) -> List[str]:
    owners = claims(all_files)
    out = [f"unclaimed: {f}" for f, o in owners.items() if not o]
    out += [f"claimed twice: {f} by {o}" for f, o in owners.items() if len(o) > 1]
    for owner, (_, patterns) in list(TESTS.items()) + [(k, ("", v)) for k, v in CROSS_CUTTING.items()]:
        for pat in patterns:
            if not any(f == pat or fnmatch(f, pat) for f in all_files):
                out.append(f"{owner}: nothing matches {pat}")
    return out


def statuses() -> Dict[str, Tuple[str, str]]:
    """test -> (status, doc) from trials.csv."""
    out = {}
    with (RESEARCH / "trials.csv").open() as f:
        for r in csv.DictReader(f):
            out[r["test"]] = (r["status"], r["doc"])
    return out


def _sort_key(entry: str) -> Tuple[int, str]:
    head = entry.split(",")[0].strip()
    digits = "".join(ch for ch in head if ch.isdigit())
    return (int(digits) if digits else 0, head)


def render(all_files: List[str]) -> str:
    owners = claims(all_files)
    st = statuses()
    lines = ["# research/ — every file, by the test it belongs to", "",
             "Generated by `research/index.py`; do not edit by hand. The folder is flat because scripts, tests,",
             "#48's seal and 229 links address these files by name. This is the structure. Names follow one",
             "convention: `PREREGISTRATION_<NAME>.md` is the contract, `RESULTS_<NAME>.md` the verdict,",
             "`FORWARD_<NAME>.md` a forward plan, `<name>.py` the script, `<name>_run.txt` its output,",
             "`<name>_events.*` and `<name>_manifest.json` what it computed on. Status is `trials.csv`'s.", ""]
    for entry in sorted(TESTS, key=_sort_key):
        name, _ = TESTS[entry]
        owned = sorted(f for f, o in owners.items() if o == [entry])
        tests = [t.strip() for t in entry.split(",")]
        status = ", ".join(f"#{t} {st[t][0]}" if t in st else f"#{t} (not in trials.csv)" for t in tests)
        lines.append(f"## #{entry} — {name}")
        lines.append("")
        lines.append(f"*{status}*")
        lines.append("")
        for f in owned:
            mod = ROOT / "espero" / Path(f).name
            extra = f"  (rule: `espero/{mod.name}`)" if f.endswith(".py") and mod.exists() else ""
            lines.append(f"- `{f}`{extra}")
        lines.append("")
    lines.append("## Cross-cutting")
    lines.append("")
    for group in CROSS_CUTTING:
        lines.append(f"**{group}**")
        lines.append("")
        for f in sorted(f for f, o in owners.items() if o == [group]):
            lines.append(f"- `{f}`")
        lines.append("")
    return "\n".join(lines)


def main(argv=None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    all_files = files()
    bad = problems(all_files)
    for b in bad:
        print(b)
    text = render(all_files)
    if "--check" in argv:
        stale = not INDEX.exists() or INDEX.read_text() != text
        if stale:
            print("INDEX.md is stale: run research/index.py")
        return 1 if bad or stale else 0
    INDEX.write_text(text)
    print(f"wrote {INDEX} ({len(all_files)} files, {len(TESTS)} test entries)")
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(main())
