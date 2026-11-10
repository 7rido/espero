"""How late each forward rule and pass may act, how late the pipeline is, and the class that follows.

research/LIVE_LATENCY.md is the audit; this table is its code, and `tests/test_latency.py` holds them together.
Every rule's budget is the latency between its signal event and its order that still makes the live trade the
tested one: the document's own tolerance where it states one, else the registered entry delay plus 5 % of the
hold (the live trade then shares at least 95 % of the tested trade's window). Every rule's feed is the best
existing, measured way its inputs arrive; `today` is what the pipeline delivers now. The class is derived from
those numbers by `classify`, never chosen by hand:

    python -m espero.latency           # rewrite the table in research/LIVE_LATENCY.md
    python -m espero.latency --check   # exit 1 if a row is missing or wrong, or the document is stale
"""
from __future__ import annotations

import csv
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Tuple

from . import carry_paper, hlpbook, holder, rawrec

ROOT = Path(__file__).resolve().parents[1]
DOC = ROOT / "research" / "LIVE_LATENCY.md"
TRIALS = ROOT / "research" / "trials.csv"
START, END = "<!-- latency:start -->", "<!-- latency:end -->"

MIN, HOUR, DAY = 60.0, 3600.0, 86400.0

# The protocol's operator: a person who answers within this long, or not at all (docs/OPERATOR.md). The account
# holder's own answer (docs/HOLDER_INPUTS.md) may raise it, never lower it.
OPERATOR_RESPONSE_S = 4 * HOUR

# Feeds, measured where the repo measures them
TAPE_S = rawrec.FLUSH_EVERY_S + 1.0          # the raw tape is flushed every second; a second of venue lag on top
COLLECTOR_POLL_S = 60.0                      # an evaluator reading hlcollect's files once a minute, as #58's book does
HLP_BOOK_S = 180.0                           # #58/#59's books see a signal 2-3 minutes after the slot (RUNBOOK)
CARRY_LOOP_S = float(carry_paper.PUBLISH_GRACE_S)   # the carry loop books an hour within its publish grace
DAILY_CLOSE_S = HOUR                         # a daily close read from Yahoo after it prints: not measured, an hour
BATCH_BEST_S = 12.5 * HOUR                   # an event at 23:55 UTC, seen at the next 07:30 New York run (12:30 UTC)
BATCH_WORST_S = 36.5 * HOUR                  # an event at 00:00 UTC, seen at the 12:30 UTC run the day after
FUNDING_ARCHIVE_S = 31 * DAY                 # Binance's monthly funding archive, which #32 and #38 read

# The Hyperliquid template (#58-#60, #64, #65): the entry candle must start within this long of the signal time
HL_FILL_WINDOW_S = float(hlpbook.FILL_TOLERANCE_S)

NOT_TRADABLE, OPERATOR_PACED, LIVE_FROM_TAPE, NEXT_DAY_BATCH = (
    "not tradable live", "operator-paced", "live-from-tape", "next-day-batch")
CLASSES = (LIVE_FROM_TAPE, OPERATOR_PACED, NEXT_DAY_BATCH, NOT_TRADABLE)
TAPES = ("rawrec", "hlcollect")             # running recorders that write as it happens
FEEDS = TAPES + ("rest", "batch", "none")

# On the raw tape today (coins.json): 13 of the 42 coins #24 and #31 trade
TAPE_BINANCE = ("BTC", "ETH", "SOL", "BNB", "XRP", "ADA", "DOGE", "AVAX", "LINK", "TRX", "LTC", "XLM", "HBAR")

# What every tradable rule still needs, in the order it would be met (research/DEPLOYMENT_LADDER.md)
COMMON_DISTANCE = (
    "its verdict, judged once after 2027-03-31 by its frozen criteria (and its tier's confirmation window)",
    "a sizing-and-execution document from research/TEMPLATE_SIZING.md, one at a time in order of t",
    "the account holder's inputs (docs/HOLDER_INPUTS.md); until then the capital is 0",
    "a venue the holder has checked as eligible, with its costs measured (research/VENUE_NONUS.md)",
    "the ladder's rungs: paper twin, testnet mechanics, then a mainnet canary",
    "the holder's written lift of the no-mainnet rule and a mainnet module built from DESIGN_MAINNET_PATH.md",
    "edgewatch's parameters from its verdict window (#70)",
)
CLASS_DISTANCE = {
    LIVE_FROM_TAPE: ("auto-only: its budget is shorter than an operator's answer, so it needs the holder's "
                     "separate decision to let the machine place orders unattended",),
    OPERATOR_PACED: ("an operator with a TOTP code (docs/OPERATOR.md) during the hours the holder gives",),
    NEXT_DAY_BATCH: ("its inputs on a tape: today only the 07:30 batch carries them, later than its budget",),
}


@dataclass(frozen=True)
class Row:
    test: str
    name: str
    doc: str                       # the frozen document that defines the event
    event: str                     # the signal event, as that document defines it
    needs: str                     # the data it needs live
    venue: str
    budget_s: Optional[float]      # None: not a trade
    budget_why: str
    feed: str                      # one of FEEDS: the best existing, measured feed for every input
    feed_s: Optional[float]
    on_tape: bool                  # every input is on a running recorder's tape
    today: str                     # what the pipeline delivers now
    today_s: Optional[float]       # None: nothing computes the event before the verdict
    tradable: bool                 # a trade, knowable at its decision time, as registered
    why: str
    klass: str
    distance: Tuple[str, ...] = ()


def classify(r: Row, operator_s: float = OPERATOR_RESPONSE_S) -> str:
    """The class from the row's numbers: a human if one has time, else the machine from a tape, else the batch."""
    if not r.tradable or r.budget_s is None or r.feed_s is None:
        return NOT_TRADABLE
    if r.feed_s + operator_s <= r.budget_s:
        return OPERATOR_PACED
    if r.on_tape and r.feed in TAPES and r.feed_s <= r.budget_s:
        return LIVE_FROM_TAPE
    return NEXT_DAY_BATCH


def _today_batch(extra: str = "") -> str:
    return "the 07:30 New York batch, next day (12.5 h at best)" + (f"; {extra}" if extra else "")


B5 = "Binance USD-M 5-minute bars"
HL_TEMPLATE = (f"the entry candle must start within {HL_FILL_WINDOW_S / MIN:.0f} min of the signal time "
               "(hlpbook.FILL_TOLERANCE_S, the rule's own drop clause)")
FORCED_DAY = ("the 'forced' label ranks the break's forced share within its whole UTC day (liq.py, terciles on "
              "days with 6+ breaks), so it is not known when the break happens")

ROWS: Tuple[Row, ...] = (
    Row("4", "cross-asset trend (TSMOM)", "research/PREREGISTRATION_TSMOM.md",
        "the month-end close; each asset long if its 12-month return is positive, else flat",
        "daily closes of SPY, TLT, GLD, USO, BTC, ETH", "an ETF broker and a crypto venue",
        17.5 * HOUR + 0.05 * 30 * DAY,
        "registered fill at the next month's first open (17.5 h after the 16:00 ET close, more over a weekend) "
        "+ 5 % of a month",
        "batch", 15.5 * HOUR, False, "the daily step on the month's first weekday",
        15.5 * HOUR, True, "a month-end decision with a day and a half of slack", OPERATOR_PACED,
        ("the live account fills at the latest close, the pre-registration at the next open: the order must "
         "follow the registration", "a broker that sells US ETFs to the holder's country (some do not)",
         "its pass is thin: drawdown control, not alpha (RESULTS_TSMOM.md)")),
    Row("7", "weekly cross-sectional account (XS20)", "research/PREREGISTRATION_XS20.md",
        "Monday's ranking of 42 coins", "daily closes", "paper only", None, "an exploratory account, not a rule",
        "batch", BATCH_BEST_S, False, "the xs daily step", BATCH_BEST_S, False,
        "exploratory: a paper account kept for watching (runner.PLANS 'xs'), no registered strategy", NOT_TRADABLE),
    Row("8", "multi-factor crypto (MF)", "research/FORWARD_MF.md",
        "the Sunday UTC close: weekly rebalance of the vol-targeted factor book",
        "daily closes of the universe", "a crypto venue (its costs are Binance.US's)", 0.05 * 7 * DAY,
        "fill at Monday 00:00 UTC (FORWARD_MF.md) + 5 % of a week", "rest", DAILY_CLOSE_S, False,
        "the mf step at 07:30 New York, after its registered fill", BATCH_BEST_S, True,
        "a weekly rebalance a human can approve if a run proposes it soon after Monday 00:00 UTC", OPERATOR_PACED,
        ("a run shortly after Monday 00:00 UTC: today's is 12.5 h after the fill, past its 8.4 h budget",
         "FORWARD_FAMILY rule 4: a pass is never by itself a reason for capital",
         "costs re-measured on the holder's venue (the registered ones are Binance.US's)",
         "its forward window runs to 2027-05-03")),
    Row("12", "funding carry, maker execution", "research/PREREGISTRATION_CARRY2.md",
        "each settled hour: trailing-168 h funding over 15 % a year enters (short perp, long spot), under 5 % or "
        "30 days exits; swaps after a 7-day hold",
        "Hyperliquid hourly funding and perp prices, Coinbase spot prices", "Hyperliquid perp + a spot venue",
        0.05 * 7 * DAY, "fill at the settled hour's close + 5 % of the registered 7-day minimum hold", "rest",
        CARRY_LOOP_S, False, "the carry loop, live, inside its publish grace", CARRY_LOOP_S, True,
        "an hourly decision on a trade held for days", OPERATOR_PACED,
        ("its verdict on 2026-11-27, then a confirmation window of 153 days or more (FORWARD_FAMILY rule 5)",
         "a spot venue for the long leg: Coinbase spot is not a candidate at 60-90 bps (VENUE_NONUS.md)",
         "both legs priced and placed together: the paper book prices them at different moments",
         "the maker fill rate, measured by #62 and the testnet mirror, not assumed")),
    Row("22", "long-liquidation spikes, 4 h", "research/FORWARD_LIQ.md",
        "an aggr hour whose long-liquidation share is above the coin's 98th percentile of 720 h, first of a 6-h "
        "cascade", "aggr's hourly bars: Binance futures prices, liquidations from Binance, Bybit and OKX",
        "Binance USD-M or Hyperliquid", MIN, "the document: entry at the close 'assumes acting within a minute'",
        "batch", BATCH_WORST_S, False, _today_batch(), BATCH_WORST_S, True,
        "the tape lacks Binance's liquidations (forceOrder is silent from this Mac), so only aggr's day has them",
        NEXT_DAY_BATCH,
        ("Binance's liquidation stream on a tape (a recorder where it is not silent, or a vendor)",
         "it fills at the spike bar's own close, which a live order cannot: the testnet rung measures the gap",
         "a live evaluator for hourly liquidation bars")),
    Row("23", "short-liquidation spikes, 4 h", "research/FORWARD_LIQSHORT.md",
        "#22 mirrored on short liquidations; a paper short", "as #22", "Hyperliquid", MIN,
        "#22's: 'acting within a minute'", "batch", BATCH_WORST_S, False, _today_batch(), BATCH_WORST_S, True,
        "as #22: Binance's liquidations are not on this Mac's tape", NEXT_DAY_BATCH,
        ("Binance's liquidation stream on a tape", "it fills at the spike bar's own close")),
    Row("24", "new 4-hour lows bought, 4 h", "research/FORWARD_LOWS.md",
        "a 5-minute close below the prior 48-bar low on a volume z of 2+, the last hour down, ATR > 0, one a "
        "coin an hour", f"{B5} for 42 coins", "Binance USD-M, then Hyperliquid", 0.05 * 4 * HOUR,
        "fill at the next bar's open + 5 % of 4 h", "rawrec", TAPE_S, True,
        _today_batch("Binance's archive can add days; lowsfwd gives up after 7"), BATCH_WORST_S, True,
        "5-minute bars rebuilt from the tape's Binance trades", LIVE_FROM_TAPE,
        ("29 of its 42 coins are not recorded: the tape carries 13 Binance symbols",
         "the streaming engine's events agreeing with the batch's (#71)",
         "the next-open fill after a crash bar 'is optimistic' (FORWARD_LOWS.md): the testnet rung measures it")),
    Row("26", "#18's rule on Binance COIN-M liquidations", "research/PREREGISTRATION_LIQ2.md",
        "a 5-minute break whose COIN-M forced share is in the day's top tercile", "COIN-M liquidations, USD-M bars",
        "none", 0.05 * HOUR, "fill at the next bar's open + 5 % of 1 h", "batch", BATCH_WORST_S, False,
        "a historical result, continued forward as #27", None, False,
        f"{FORCED_DAY}; COIN-M is not where the bot would trade (RESULTS_LIQ2.md)", NOT_TRADABLE),
    Row("27", "forced down-breaks bought, 1 h", "research/FORWARD_LIQBREAK.md",
        "a 5-minute break whose forced share is in its day's top tercile", "aggr 5-minute liquidations, "
        f"{B5}", "Binance USD-M", 0.05 * HOUR, "fill at the next bar's open + 5 % of 1 h", "batch",
        BATCH_WORST_S, False, _today_batch(), BATCH_WORST_S, False, FORCED_DAY, NOT_TRADABLE),
    Row("29", "the US session's move after 16:00 ET", "research/FORWARD_POSTCLOSE.md",
        "NYSE day: r from the previous close (R) to 16:00 ET on BTC and ETH; trade against r, 16:00 to 16:15",
        f"{B5} for BTC and ETH", "Binance USD-M", 0.05 * 15 * MIN, "fill at the 16:00 bar's open + 5 % of 15 min",
        "rawrec", TAPE_S, True, "the 07:30 New York batch after 16:00 ET", 15.5 * HOUR, True,
        "the 15:55 bar closes at 16:00 ET on the tape", LIVE_FROM_TAPE,
        ("the streaming engine's events agreeing with the batch's (#71)",
         "the NYSE calendar in espero/levetf.py extended through the live period")),
    Row("31", "bids 2 ATR under breakdowns", "research/FORWARD_BIDS2.md",
        "#20's 5-minute breakdown; a maker bid 2 ATR under its close rests 12 bars", f"{B5} for 42 coins",
        "Hyperliquid (maker)", 0.05 * 12 * 5 * MIN, "the bid placed at the next bar's open + 5 % of its 1-hour life",
        "rawrec", TAPE_S, True, _today_batch("Binance's archive can add days"), BATCH_WORST_S, True,
        "5-minute bars rebuilt from the tape's Binance trades", LIVE_FROM_TAPE,
        ("29 of its 42 coins are not recorded", "the streaming engine's events agreeing with the batch's (#71)",
         "resting maker orders on the order path, their queue position measured (#62), testnet first")),
    Row("32", "forced down-breaks after crowded funding", "research/FORWARD_FUNDSPLIT.md",
        "#27's forced down-breaks, split by the last settled funding", "#27's ledger, Binance's funding archive",
        "Binance USD-M", 0.05 * HOUR, "fill at the next bar's open + 5 % of 1 h", "batch", FUNDING_ARCHIVE_S, False,
        "the 07:30 batch with Binance's monthly funding archive", FUNDING_ARCHIVE_S, False,
        f"it inherits #27's label: {FORCED_DAY}", NOT_TRADABLE),
    Row("34", "SOL and XRP pushed into 16:00 ET", "research/PREREGISTRATION_LEVPUSH.md",
        "NYSE day, known at 15:45 ET: sign of the day's move, held 15:45 to 16:00", f"{B5} for SOL and XRP",
        "Binance USD-M", 0.05 * 15 * MIN, "fill at the 15:45 bar's open + 5 % of 15 min", "rawrec", TAPE_S, True,
        "the 07:30 New York batch after 15:45 ET", 15.75 * HOUR, True,
        "the 15:40 bar closes at 15:45 ET on the tape", LIVE_FROM_TAPE,
        ("Tier B: a confirmation window before any order (FORWARD_FAMILY rule 3)",
         "the streaming engine's events agreeing with the batch's (#71)")),
    Row("38", "after settlements where shorts pay hard", "research/FORWARD_SHORTSPAY.md",
        "a 00/08/16 UTC Binance settlement at a rate of -0.0005 or below: short at P(t), 30 min",
        f"{B5} and the settled funding rate", "Binance USD-M", 0.05 * 30 * MIN,
        "fill at the open of the bar at t + 5 % of 30 min", "batch", FUNDING_ARCHIVE_S, False,
        "the 07:30 batch with the monthly funding archive", FUNDING_ARCHIVE_S, True,
        "the rate is not live here: Binance's markPrice stream is silent and its REST answers 451 from this Mac",
        NEXT_DAY_BATCH,
        ("Binance's funding rate live, from a machine where it is reachable",
         "it enters at P(t) with the rate settled at t: a live order comes after the settlement",
         "Tier B: a confirmation window before any order")),
    Row("40", "fill-reconciliation plumbing on testnet", "research/PREREGISTRATION_TESTNET.md",
        "a scripted testnet session", "testnet fills", "Hyperliquid testnet", None, "plumbing, not a rule",
        "none", None, False, "done once; send to acknowledgement about 0.9 s", None, False,
        "plumbing with no edge: the testnet rung's evidence, not a strategy", NOT_TRADABLE),
    Row("42", "dress rehearsal on testnet", "research/PREREGISTRATION_REHEARSAL.md",
        "a scripted testnet session", "testnet fills", "Hyperliquid testnet", None, "plumbing, not a rule", "none",
        None, False, "done once; median send to acknowledgement 872 ms", None, False,
        "plumbing with no edge", NOT_TRADABLE),
    Row("43", "which holding period pays", "research/PREREGISTRATION_HORIZONS.md",
        "signals measured at 1 h to 2 weeks", "Binance bars", "none", None, "a measurement", "none", None, False,
        "done once", None, False, "a measurement: 'Economically: not tradable' (RESULTS_HORIZONS.md)",
        NOT_TRADABLE),
    Row("45", "forced down-breaks held 4 h, 12 h, 1 d", "research/FORWARD_LIQHOLD.md",
        "#27's forced down-breaks", "#27's ledger, Binance 5-minute bars, funding", "Binance USD-M",
        0.05 * 4 * HOUR, "fill at the next bar's open + 5 % of 4 h", "batch", BATCH_WORST_S, False, _today_batch(),
        BATCH_WORST_S, False, f"it inherits #27's label: {FORCED_DAY}", NOT_TRADABLE),
    Row("49", "the day after a deep-book imbalance", "research/PREREGISTRATION_DEPTHDAY.md",
        "day D-1's mean ±1 % bookDepth imbalance", "Binance's bookDepth archive", "Binance USD-M", None,
        "never run", "none", None, False, "never run: no module, no step", None, False,
        "never run; trials.csv says it is not a forward test", NOT_TRADABLE),
    Row("58", "HLP's jumps into falling coins, 4 h", "research/FORWARD_HLP.md",
        "adjacent 15-minute HLP slots: a net-size jump above the 99th percentile into a fall at or below the 10th",
        "hlcollect's HLP slots, 1-minute candles", "Hyperliquid", HL_FILL_WINDOW_S, HL_TEMPLATE, "hlcollect",
        HLP_BOOK_S, True, "the HLP paper book, live, 2-3 minutes after the slot", HLP_BOOK_S, True,
        "the collector's slot and a 60-second loop", LIVE_FROM_TAPE,
        ("one sleeve with #59 (#63's clusters)",
         "HLP's positions are mostly hidden from the API: the collector sees about 4 % of the vault (ERRATA)")),
    Row("59", "HLP's jumps, failed reads guarded", "research/FORWARD_HLP2.md",
        "as #58, voiding only pairs touched by a failed read", "hlcollect's HLP slots and read records, candles",
        "Hyperliquid", HL_FILL_WINDOW_S, HL_TEMPLATE, "hlcollect", HLP_BOOK_S, True,
        "the HLP2 paper book, live; testnet orders inside 5 minutes", HLP_BOOK_S, True,
        "the collector's slot; its testnet executor already trades it", LIVE_FROM_TAPE,
        ("one sleeve with #58", "the testnet executor's mechanics are rung 1's model, already running")),
    Row("60", "falls through a dense liquidation band", "research/FORWARD_LADDER.md",
        "an hourly positions file: a band of long liquidations within 1 % below the price at A = ts + 1800 s, "
        "then the price 1 % lower at B = A + 3600 s", "hlcollect's positions, the price at B", "Hyperliquid",
        HL_FILL_WINDOW_S, HL_TEMPLATE + ", from B", "hlcollect", COLLECTOR_POLL_S, True,
        "nothing before its verdict (espero ladder --verdict)", None, True,
        "the positions file is on disk before A; the price at B is on the tape", LIVE_FROM_TAPE,
        ("a live evaluator: today it is computed only at the verdict",
         "the positions are stale by up to an hour and a half (FORWARD_LADDER.md)")),
    Row("61", "aggr's bars rebuilt from the raw tape", "research/PREREGISTRATION_RAWBARS.md",
        "each aggr bar against one rebuilt from the tape", "aggr's bars, the tape", "none", None, "a measurement",
        "none", None, False, "judged at 30 comparable days", None, False, "a measurement", NOT_TRADABLE),
    Row("62", "paper fills replayed on the recorded book", "research/PREREGISTRATION_REPLAYSIM.md",
        "each paper or testnet fill", "the journals, the tape", "none", None, "a measurement", "none", None, False,
        "judged at 30 taker and 10 maker fills", None, False, "a measurement", NOT_TRADABLE),
    Row("63", "the portfolio layer", "research/PREREGISTRATION_SLEEVES.md",
        "the first weekday of each month: vol-target weights of the sleeves", "the sleeves' daily net returns",
        "every sleeve's", 0.05 * 30 * DAY, "the monthly rebalance + 5 % of a month", "batch", BATCH_BEST_S, False,
        "nothing until two passes exist", None, True,
        "a monthly change of sizes, through its sleeves' own orders", OPERATOR_PACED,
        ("two or more passes that FORWARD_FAMILY lets proceed: alone, a pass follows its own plan",)),
    Row("64", "the liquidator vault's side, 4 h", "research/FORWARD_LIQVAULT.md",
        "a 15-minute HLP slot where a liquidator vault holds a new position of $50k+; signal at A = ts + 120 s",
        "hlcollect's HLP slots and read records, candles", "Hyperliquid", HL_FILL_WINDOW_S, HL_TEMPLATE + ", from A",
        "hlcollect", COLLECTOR_POLL_S, True, "nothing before its verdict (espero liqvault --verdict)", None,
        True, "the slot is on disk before A", LIVE_FROM_TAPE,
        ("a live evaluator: today it is computed only at the verdict",
         "the vault is seen 0 to 15 minutes after it is handed the position (FORWARD_LIQVAULT.md)")),
    Row("65", "a sharp 5-minute fall read by open interest", "research/FORWARD_OI5M.md",
        "a 5-minute context slot: a fall in the coin's 2 % tail with open interest down 1 % (long) or up 1 % "
        "(short), day volume $5M+; known at A = ts + 120 s", "hlcollect's context slots, candles", "Hyperliquid",
        HL_FILL_WINDOW_S, HL_TEMPLATE + ", from A", "hlcollect", COLLECTOR_POLL_S, True,
        "nothing before its verdict (espero oi5m --verdict)", None, True, "the slot is on disk before A",
        LIVE_FROM_TAPE, ("a live evaluator: today it is computed only at the verdict",)),
    Row("66", "HAR volatility forecast", "research/PREREGISTRATION_VOLF.md",
        "Sunday's forecast of next week's variance", "Binance 5-minute bars", "none", None, "a forecast, no trade",
        "none", None, False, "done once", None, False,
        "a forecast: 'No trade'; it changes no running book unless a new number says so", NOT_TRADABLE),
    Row("69", "operator alpha", "research/PREREGISTRATION_OPALPHA.md",
        "each override of an operator-paced proposal, against the paper twin", "the approvals ledger, the twin",
        "none", None, "a measurement", "none", None, False, "nothing until a sleeve is live", None, False,
        "a measurement, information only", NOT_TRADABLE),
    Row("70", "edgewatch, the live stop rule", "research/PREREGISTRATION_EDGEWATCH.md",
        "each live observation of a sleeve, against its registered edge", "the sleeve's net series",
        "none", None, "a rule acting through the risk gate", "none", None, False, "nothing until a sleeve is live",
        None, False, "a rule, not a trade: it halves or flattens a live sleeve through its scale", NOT_TRADABLE),
    Row("71", "the streaming engine against the batch", "research/PREREGISTRATION_LIVESIG.md",
        "each live-from-tape event the engine emits, against the next day's batch", "the raw tape, the archive",
        "none", None, "a measurement", "none", None, False, "nothing until the engine runs", None, False,
        "a measurement, information only", NOT_TRADABLE),
    Row("73", "a trade.xyz perp against its listed ticker", "research/PREREGISTRATION_HIP3TRACK.md",
        "each hour's return of the perp against the ticker's", "Hyperliquid's candles, Yahoo's bars",
        "none", None, "a measurement", "none", None, False, "nothing until it is run once", None, False,
        "a measurement, information only", NOT_TRADABLE),
    Row("74", "what a fill costs on trade.xyz perps", "research/PREREGISTRATION_HIP3COST.md",
        "each minute's recorded book, walked for three order sizes", "the second raw tape",
        "none", None, "a measurement", "none", None, False, "nothing until the recorder has 14 days", None, False,
        "a measurement, information only", NOT_TRADABLE),
)


def by_test(rows: Iterable[Row] = ROWS) -> Dict[str, Row]:
    return {r.test: r for r in rows}


def ledger_numbers(trials: Path = TRIALS, statuses=("pass", "provisional", "forward_pending")) -> List[str]:
    with open(trials, newline="", encoding="utf-8") as fh:
        return [r["test"] for r in csv.DictReader(fh) if r["status"] in statuses]


def problems(rows: Iterable[Row] = ROWS, trials: Path = TRIALS, root: Path = ROOT,
             operator_s: Optional[float] = None) -> List[str]:
    """Everything that would make the table wrong: a forward rule or pass without a row, a class that does not
    follow from the numbers, a feed that is not one, a document that does not exist. The operator is the holder's
    (docs/HOLDER_INPUTS.md): the protocol's 4 hours, or slower if the holder says so."""
    operator_s = holder.operator_response_s() if operator_s is None else operator_s
    rows = list(rows)
    out = []
    have = by_test(rows)
    if len(have) != len(rows):
        out.append("a test has two rows")
    out += [f"#{t} is pass, provisional or forward_pending in trials.csv and has no row here"
            for t in ledger_numbers(trials) if t not in have]
    for r in rows:
        if r.klass not in CLASSES:
            out.append(f"#{r.test}: {r.klass!r} is not a class")
        if r.feed not in FEEDS:
            out.append(f"#{r.test}: feed {r.feed!r} is not one of {FEEDS}")
        derived = classify(r, operator_s)
        if derived != r.klass:
            out.append(f"#{r.test}: the numbers give {derived!r}, the row says {r.klass!r}")
        if r.klass == NEXT_DAY_BATCH and r.feed != "batch":
            out.append(f"#{r.test}: next-day-batch, but its best feed is {r.feed!r}: say which class it is")
        if r.klass == OPERATOR_PACED and r.budget_s is not None and r.budget_s < operator_s:
            out.append(f"#{r.test}: a budget under the operator's response time is never operator-paced")
        if not r.tradable and not r.why:
            out.append(f"#{r.test}: not tradable without saying why")
        if not (root / r.doc).is_file():
            out.append(f"#{r.test}: {r.doc} does not exist")
    return out


def fmt_s(s: Optional[float]) -> str:
    """45 s, 12 min, 8.4 h, 2.2 d; a dash for None."""
    if s is None:
        return "—"
    if s < 2 * MIN:
        return f"{s:.0f} s"
    if s < 2 * HOUR:
        return f"{s / MIN:.0f} min"
    if s < 2 * DAY:
        return f"{s / HOUR:.1f} h".replace(".0 h", " h")
    return f"{s / DAY:.1f} d".replace(".0 d", " d")


def _cell(text: str) -> str:
    return text.replace("|", "/")


def render(rows: Iterable[Row] = ROWS) -> str:
    rows = sorted(rows, key=lambda r: int(r.test))
    lines = ["| # | rule | event | needs live | budget | best feed | today | class |",
             "|---|---|---|---|---|---|---|---|"]
    for r in rows:
        feed = "—" if r.feed == "none" else f"{r.feed}, {fmt_s(r.feed_s)}"
        today = r.today if r.today_s is None else f"{fmt_s(r.today_s)}, {r.today}"
        lines.append(f"| {r.test} | {_cell(r.name)} | {_cell(r.event)} | {_cell(r.needs)} | {fmt_s(r.budget_s)} "
                     f"| {feed} | {_cell(today)} | **{r.klass}** |")
    lines += ["", "**Why each class, and what stands between a PASS and a live order, rule by rule.** The steps "
              "every tradable rule shares are listed after this table; these are its own.", "",
              "| # | class | why | budget from | its own distance |", "|---|---|---|---|---|"]
    for r in rows:
        own = list(r.distance) + list(CLASS_DISTANCE.get(r.klass, ()))
        dist = "; ".join(own) if own else "—"
        lines.append(f"| {r.test} | {r.klass} | {_cell(r.why)} | {_cell(r.budget_why)} | {_cell(dist)} |")
    lines += ["", "**Shared by every tradable rule, in the order they would be met:**", ""]
    lines += [f"{i}. {step}" for i, step in enumerate(COMMON_DISTANCE, 1)]
    counts = {k: sum(1 for r in rows if r.klass == k) for k in CLASSES}
    lines += ["", "Counts: " + ", ".join(f"{k} {n}" for k, n in counts.items()) + "."]
    return "\n".join(lines)


def block(doc: Path = DOC) -> str:
    text = doc.read_text(encoding="utf-8")
    a, b = text.find(START), text.find(END)
    return text[a + len(START):b].strip("\n") if a >= 0 and b >= 0 else ""


def write(doc: Path = DOC, rows: Iterable[Row] = ROWS) -> None:
    text = doc.read_text(encoding="utf-8")
    a, b = text.find(START), text.find(END)
    if a < 0 or b < 0:
        raise RuntimeError(f"{doc} has no {START} / {END} markers")
    doc.write_text(text[:a + len(START)] + "\n" + render(rows) + "\n" + text[b:], encoding="utf-8")


def main(argv=None, doc: Optional[Path] = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    doc = DOC if doc is None else doc
    bad = problems()
    for p in bad:
        print(p, file=sys.stderr)
    if "--check" in argv:
        stale = block(doc) != render()
        if stale:
            print(f"{doc.name} is stale: python -m espero.latency", file=sys.stderr)
        return 1 if bad or stale else 0
    if bad:
        return 1
    write(doc)
    print(f"wrote {doc.name}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
