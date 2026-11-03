# From event to order: the latency each rule allows, and what the pipeline delivers

**Written 2026-11-02, before any forward verdict exists. Information only:** it changes no test's rule,
criteria or verdict. It fixes, while no verdict can be seen, how late each forward rule and each pass may act
on its own signal, how its inputs could reach a live order, and how late they reach one today, so that a PASS
meets a pipeline audited before anyone knew which rule would pass. `espero/latency.py` holds the table as code;
`tests/test_latency.py` fails when a forward rule or a pass has no row, when a row's class does not follow
from its numbers, or when the table below is stale.

## Why

Every forward step rebuilds yesterday at the 07:30 New York run (12:30 UTC). An event at 00:00 UTC is first seen
36.5 hours later, one at 23:55 UTC 12.5 hours later, and Binance's archive or its monthly funding file can add
days to that. No one can trade yesterday's 5-minute bar. The forward plans say so themselves: #22's entry at
the spike hour's close "assumes acting within a minute; the bot will see it a day later from the recorder, so
this is a test of the effect, not of the execution" (FORWARD_LIQ.md). A pass is therefore a pass of the
effect. Whether it can be traded depends on the latency below, and that question is settled here, not after
the verdict.

## The terms, fixed now

- **Budget.** The longest delay between the signal event and the order at which the live trade is still the
  tested one. Where the rule's document states a tolerance, that is the budget: #22's "within a minute"; the
  Hyperliquid template's entry candle, which must start within 5 minutes of the signal time or the trade is
  dropped (`hlpbook.FILL_TOLERANCE_S`). Otherwise the budget is the registered entry delay plus **5 % of the
  hold**: a trade entered and exited that much late still shares at least 95 % of the tested trade's window.
  The 5 % is a convention set here, the same for every rule, and not fitted to any.
- **Feed.** The best existing, measured way every input of the rule arrives:
  - **tape**: what a running recorder writes as it happens. Here that means `espero rawrec`'s raw tape, flushed
    to disk every second, with `tapewatch`'s book rebuilds, and `espero hlcollect`'s 5- and 15-minute slots.
    hlcollect counts as tape because it records the venue's present state as it is, and #59's testnet
    executor already trades from it within 5 minutes;
  - **rest**: a public endpoint the repo already reads live (Yahoo's daily closes, Hyperliquid's funding
    through the carry loop); a daily close's delay after it prints is not measured and is taken as an hour;
  - **batch**: the 07:30 run, nothing sooner.
- **Today.** What the pipeline delivers now: the batch, a live loop, or nothing until the verdict.
- **Operator response.** A person answers within **4 hours** or not at all (docs/OPERATOR.md). The account
  holder's answer in docs/HOLDER_INPUTS.md may raise this, never lower it.
- **Class**, derived by `espero.latency.classify` in this order and never chosen by hand:
  1. **not tradable live**: not a trade (a measurement, plumbing, a forecast, never run), or its signal uses
     information later than its decision time;
  2. **operator-paced**: the feed's delay plus the operator's response fits in the budget, so a human can answer
     in time;
  3. **live-from-tape**: every input is on a tape and the tape is inside the budget, but a human is not:
     **auto-only**. Under docs/OPERATOR.md such a rule is never operator-paced; it runs unattended or not at all;
  4. **next-day-batch**: only the 07:30 rebuild carries its inputs, and it is later than the budget. As it stands
     it can be traded only a day late, which is not the tested trade.

## The table

<!-- latency:start -->
| # | rule | event | needs live | budget | best feed | today | class |
|---|---|---|---|---|---|---|---|
| 4 | cross-asset trend (TSMOM) | the month-end close; each asset long if its 12-month return is positive, else flat | daily closes of SPY, TLT, GLD, USO, BTC, ETH | 2.2 d | batch, 15.5 h | 15.5 h, the daily step on the month's first weekday | **operator-paced** |
| 7 | weekly cross-sectional account (XS20) | Monday's ranking of 42 coins | daily closes | — | batch, 12.5 h | 12.5 h, the xs daily step | **not tradable live** |
| 8 | multi-factor crypto (MF) | the Sunday UTC close: weekly rebalance of the vol-targeted factor book | daily closes of the universe | 8.4 h | rest, 60 min | 12.5 h, the mf step at 07:30 New York, after its registered fill | **operator-paced** |
| 12 | funding carry, maker execution | each settled hour: trailing-168 h funding over 15 % a year enters (short perp, long spot), under 5 % or 30 days exits; swaps after a 7-day hold | Hyperliquid hourly funding and perp prices, Coinbase spot prices | 8.4 h | rest, 20 min | 20 min, the carry loop, live, inside its publish grace | **operator-paced** |
| 22 | long-liquidation spikes, 4 h | an aggr hour whose long-liquidation share is above the coin's 98th percentile of 720 h, first of a 6-h cascade | aggr's hourly bars: Binance futures prices, liquidations from Binance, Bybit and OKX | 60 s | batch, 36.5 h | 36.5 h, the 07:30 New York batch, next day (12.5 h at best) | **next-day-batch** |
| 23 | short-liquidation spikes, 4 h | #22 mirrored on short liquidations; a paper short | as #22 | 60 s | batch, 36.5 h | 36.5 h, the 07:30 New York batch, next day (12.5 h at best) | **next-day-batch** |
| 24 | new 4-hour lows bought, 4 h | a 5-minute close below the prior 48-bar low on a volume z of 2+, the last hour down, ATR > 0, one a coin an hour | Binance USD-M 5-minute bars for 42 coins | 12 min | rawrec, 2 s | 36.5 h, the 07:30 New York batch, next day (12.5 h at best); Binance's archive can add days; lowsfwd gives up after 7 | **live-from-tape** |
| 26 | #18's rule on Binance COIN-M liquidations | a 5-minute break whose COIN-M forced share is in the day's top tercile | COIN-M liquidations, USD-M bars | 3 min | batch, 36.5 h | a historical result, continued forward as #27 | **not tradable live** |
| 27 | forced down-breaks bought, 1 h | a 5-minute break whose forced share is in its day's top tercile | aggr 5-minute liquidations, Binance USD-M 5-minute bars | 3 min | batch, 36.5 h | 36.5 h, the 07:30 New York batch, next day (12.5 h at best) | **not tradable live** |
| 29 | the US session's move after 16:00 ET | NYSE day: r from the previous close (R) to 16:00 ET on BTC and ETH; trade against r, 16:00 to 16:15 | Binance USD-M 5-minute bars for BTC and ETH | 45 s | rawrec, 2 s | 15.5 h, the 07:30 New York batch after 16:00 ET | **live-from-tape** |
| 31 | bids 2 ATR under breakdowns | #20's 5-minute breakdown; a maker bid 2 ATR under its close rests 12 bars | Binance USD-M 5-minute bars for 42 coins | 3 min | rawrec, 2 s | 36.5 h, the 07:30 New York batch, next day (12.5 h at best); Binance's archive can add days | **live-from-tape** |
| 32 | forced down-breaks after crowded funding | #27's forced down-breaks, split by the last settled funding | #27's ledger, Binance's funding archive | 3 min | batch, 31 d | 31 d, the 07:30 batch with Binance's monthly funding archive | **not tradable live** |
| 34 | SOL and XRP pushed into 16:00 ET | NYSE day, known at 15:45 ET: sign of the day's move, held 15:45 to 16:00 | Binance USD-M 5-minute bars for SOL and XRP | 45 s | rawrec, 2 s | 15.8 h, the 07:30 New York batch after 15:45 ET | **live-from-tape** |
| 38 | after settlements where shorts pay hard | a 00/08/16 UTC Binance settlement at a rate of -0.0005 or below: short at P(t), 30 min | Binance USD-M 5-minute bars and the settled funding rate | 90 s | batch, 31 d | 31 d, the 07:30 batch with the monthly funding archive | **next-day-batch** |
| 40 | fill-reconciliation plumbing on testnet | a scripted testnet session | testnet fills | — | — | done once; send to acknowledgement about 0.9 s | **not tradable live** |
| 42 | dress rehearsal on testnet | a scripted testnet session | testnet fills | — | — | done once; median send to acknowledgement 872 ms | **not tradable live** |
| 43 | which holding period pays | signals measured at 1 h to 2 weeks | Binance bars | — | — | done once | **not tradable live** |
| 45 | forced down-breaks held 4 h, 12 h, 1 d | #27's forced down-breaks | #27's ledger, Binance 5-minute bars, funding | 12 min | batch, 36.5 h | 36.5 h, the 07:30 New York batch, next day (12.5 h at best) | **not tradable live** |
| 49 | the day after a deep-book imbalance | day D-1's mean ±1 % bookDepth imbalance | Binance's bookDepth archive | — | — | never run: no module, no step | **not tradable live** |
| 58 | HLP's jumps into falling coins, 4 h | adjacent 15-minute HLP slots: a net-size jump above the 99th percentile into a fall at or below the 10th | hlcollect's HLP slots, 1-minute candles | 5 min | hlcollect, 3 min | 3 min, the HLP paper book, live, 2-3 minutes after the slot | **live-from-tape** |
| 59 | HLP's jumps, failed reads guarded | as #58, voiding only pairs touched by a failed read | hlcollect's HLP slots and read records, candles | 5 min | hlcollect, 3 min | 3 min, the HLP2 paper book, live; testnet orders inside 5 minutes | **live-from-tape** |
| 60 | falls through a dense liquidation band | an hourly positions file: a band of long liquidations within 1 % below the price at A = ts + 1800 s, then the price 1 % lower at B = A + 3600 s | hlcollect's positions, the price at B | 5 min | hlcollect, 60 s | nothing before its verdict (espero ladder --verdict) | **live-from-tape** |
| 61 | aggr's bars rebuilt from the raw tape | each aggr bar against one rebuilt from the tape | aggr's bars, the tape | — | — | judged at 30 comparable days | **not tradable live** |
| 62 | paper fills replayed on the recorded book | each paper or testnet fill | the journals, the tape | — | — | judged at 30 taker and 10 maker fills | **not tradable live** |
| 63 | the portfolio layer | the first weekday of each month: vol-target weights of the sleeves | the sleeves' daily net returns | 36 h | batch, 12.5 h | nothing until two passes exist | **operator-paced** |
| 64 | the liquidator vault's side, 4 h | a 15-minute HLP slot where a liquidator vault holds a new position of $50k+; signal at A = ts + 120 s | hlcollect's HLP slots and read records, candles | 5 min | hlcollect, 60 s | nothing before its verdict (espero liqvault --verdict) | **live-from-tape** |
| 65 | a sharp 5-minute fall read by open interest | a 5-minute context slot: a fall in the coin's 2 % tail with open interest down 1 % (long) or up 1 % (short), day volume $5M+; known at A = ts + 120 s | hlcollect's context slots, candles | 5 min | hlcollect, 60 s | nothing before its verdict (espero oi5m --verdict) | **live-from-tape** |
| 66 | HAR volatility forecast | Sunday's forecast of next week's variance | Binance 5-minute bars | — | — | done once | **not tradable live** |
| 69 | operator alpha | each override of an operator-paced proposal, against the paper twin | the approvals ledger, the twin | — | — | nothing until a sleeve is live | **not tradable live** |
| 70 | edgewatch, the live stop rule | each live observation of a sleeve, against its registered edge | the sleeve's net series | — | — | nothing until a sleeve is live | **not tradable live** |

**Why each class, and what stands between a PASS and a live order, rule by rule.** The steps every tradable rule shares are listed after this table; these are its own.

| # | class | why | budget from | its own distance |
|---|---|---|---|---|
| 4 | operator-paced | a month-end decision with a day and a half of slack | registered fill at the next month's first open (17.5 h after the 16:00 ET close, more over a weekend) + 5 % of a month | the live account fills at the latest close, the pre-registration at the next open: the order must follow the registration; a broker that sells US ETFs to the holder's country (some do not); its pass is thin: drawdown control, not alpha (RESULTS_TSMOM.md); an operator with a TOTP code (docs/OPERATOR.md) during the hours the holder gives |
| 7 | not tradable live | exploratory: a paper account kept for watching (runner.PLANS 'xs'), no registered strategy | an exploratory account, not a rule | — |
| 8 | operator-paced | a weekly rebalance a human can approve if a run proposes it soon after Monday 00:00 UTC | fill at Monday 00:00 UTC (FORWARD_MF.md) + 5 % of a week | a run shortly after Monday 00:00 UTC: today's is 12.5 h after the fill, past its 8.4 h budget; FORWARD_FAMILY rule 4: a pass is never by itself a reason for capital; costs re-measured on the holder's venue (the registered ones are Binance.US's); its forward window runs to 2027-05-03; an operator with a TOTP code (docs/OPERATOR.md) during the hours the holder gives |
| 12 | operator-paced | an hourly decision on a trade held for days | fill at the settled hour's close + 5 % of the registered 7-day minimum hold | its verdict on 2026-11-27, then a confirmation window of 153 days or more (FORWARD_FAMILY rule 5); a spot venue for the long leg: Coinbase spot is not a candidate at 60-90 bps (VENUE_NONUS.md); both legs priced and placed together: the paper book prices them at different moments; the maker fill rate, measured by #62 and the testnet mirror, not assumed; an operator with a TOTP code (docs/OPERATOR.md) during the hours the holder gives |
| 22 | next-day-batch | the tape lacks Binance's liquidations (forceOrder is silent from this Mac), so only aggr's day has them | the document: entry at the close 'assumes acting within a minute' | Binance's liquidation stream on a tape (a recorder where it is not silent, or a vendor); it fills at the spike bar's own close, which a live order cannot: the testnet rung measures the gap; a live evaluator for hourly liquidation bars; its inputs on a tape: today only the 07:30 batch carries them, later than its budget |
| 23 | next-day-batch | as #22: Binance's liquidations are not on this Mac's tape | #22's: 'acting within a minute' | Binance's liquidation stream on a tape; it fills at the spike bar's own close; its inputs on a tape: today only the 07:30 batch carries them, later than its budget |
| 24 | live-from-tape | 5-minute bars rebuilt from the tape's Binance trades | fill at the next bar's open + 5 % of 4 h | 29 of its 42 coins are not recorded: the tape carries 13 Binance symbols; the streaming engine's events agreeing with the batch's (#71); the next-open fill after a crash bar 'is optimistic' (FORWARD_LOWS.md): the testnet rung measures it; auto-only: its budget is shorter than an operator's answer, so it needs the holder's separate decision to let the machine place orders unattended |
| 26 | not tradable live | the 'forced' label ranks the break's forced share within its whole UTC day (liq.py, terciles on days with 6+ breaks), so it is not known when the break happens; COIN-M is not where the bot would trade (RESULTS_LIQ2.md) | fill at the next bar's open + 5 % of 1 h | — |
| 27 | not tradable live | the 'forced' label ranks the break's forced share within its whole UTC day (liq.py, terciles on days with 6+ breaks), so it is not known when the break happens | fill at the next bar's open + 5 % of 1 h | — |
| 29 | live-from-tape | the 15:55 bar closes at 16:00 ET on the tape | fill at the 16:00 bar's open + 5 % of 15 min | the streaming engine's events agreeing with the batch's (#71); the NYSE calendar in espero/levetf.py extended through the live period; auto-only: its budget is shorter than an operator's answer, so it needs the holder's separate decision to let the machine place orders unattended |
| 31 | live-from-tape | 5-minute bars rebuilt from the tape's Binance trades | the bid placed at the next bar's open + 5 % of its 1-hour life | 29 of its 42 coins are not recorded; the streaming engine's events agreeing with the batch's (#71); resting maker orders on the order path, their queue position measured (#62), testnet first; auto-only: its budget is shorter than an operator's answer, so it needs the holder's separate decision to let the machine place orders unattended |
| 32 | not tradable live | it inherits #27's label: the 'forced' label ranks the break's forced share within its whole UTC day (liq.py, terciles on days with 6+ breaks), so it is not known when the break happens | fill at the next bar's open + 5 % of 1 h | — |
| 34 | live-from-tape | the 15:40 bar closes at 15:45 ET on the tape | fill at the 15:45 bar's open + 5 % of 15 min | Tier B: a confirmation window before any order (FORWARD_FAMILY rule 3); the streaming engine's events agreeing with the batch's (#71); auto-only: its budget is shorter than an operator's answer, so it needs the holder's separate decision to let the machine place orders unattended |
| 38 | next-day-batch | the rate is not live here: Binance's markPrice stream is silent and its REST answers 451 from this Mac | fill at the open of the bar at t + 5 % of 30 min | Binance's funding rate live, from a machine where it is reachable; it enters at P(t) with the rate settled at t: a live order comes after the settlement; Tier B: a confirmation window before any order; its inputs on a tape: today only the 07:30 batch carries them, later than its budget |
| 40 | not tradable live | plumbing with no edge: the testnet rung's evidence, not a strategy | plumbing, not a rule | — |
| 42 | not tradable live | plumbing with no edge | plumbing, not a rule | — |
| 43 | not tradable live | a measurement: 'Economically: not tradable' (RESULTS_HORIZONS.md) | a measurement | — |
| 45 | not tradable live | it inherits #27's label: the 'forced' label ranks the break's forced share within its whole UTC day (liq.py, terciles on days with 6+ breaks), so it is not known when the break happens | fill at the next bar's open + 5 % of 4 h | — |
| 49 | not tradable live | never run; trials.csv says it is not a forward test | never run | — |
| 58 | live-from-tape | the collector's slot and a 60-second loop | the entry candle must start within 5 min of the signal time (hlpbook.FILL_TOLERANCE_S, the rule's own drop clause) | one sleeve with #59 (#63's clusters); HLP's positions are mostly hidden from the API: the collector sees about 4 % of the vault (ERRATA); auto-only: its budget is shorter than an operator's answer, so it needs the holder's separate decision to let the machine place orders unattended |
| 59 | live-from-tape | the collector's slot; its testnet executor already trades it | the entry candle must start within 5 min of the signal time (hlpbook.FILL_TOLERANCE_S, the rule's own drop clause) | one sleeve with #58; the testnet executor's mechanics are rung 1's model, already running; auto-only: its budget is shorter than an operator's answer, so it needs the holder's separate decision to let the machine place orders unattended |
| 60 | live-from-tape | the positions file is on disk before A; the price at B is on the tape | the entry candle must start within 5 min of the signal time (hlpbook.FILL_TOLERANCE_S, the rule's own drop clause), from B | a live evaluator: today it is computed only at the verdict; the positions are stale by up to an hour and a half (FORWARD_LADDER.md); auto-only: its budget is shorter than an operator's answer, so it needs the holder's separate decision to let the machine place orders unattended |
| 61 | not tradable live | a measurement | a measurement | — |
| 62 | not tradable live | a measurement | a measurement | — |
| 63 | operator-paced | a monthly change of sizes, through its sleeves' own orders | the monthly rebalance + 5 % of a month | two or more passes that FORWARD_FAMILY lets proceed: alone, a pass follows its own plan; an operator with a TOTP code (docs/OPERATOR.md) during the hours the holder gives |
| 64 | live-from-tape | the slot is on disk before A | the entry candle must start within 5 min of the signal time (hlpbook.FILL_TOLERANCE_S, the rule's own drop clause), from A | a live evaluator: today it is computed only at the verdict; the vault is seen 0 to 15 minutes after it is handed the position (FORWARD_LIQVAULT.md); auto-only: its budget is shorter than an operator's answer, so it needs the holder's separate decision to let the machine place orders unattended |
| 65 | live-from-tape | the slot is on disk before A | the entry candle must start within 5 min of the signal time (hlpbook.FILL_TOLERANCE_S, the rule's own drop clause), from A | a live evaluator: today it is computed only at the verdict; auto-only: its budget is shorter than an operator's answer, so it needs the holder's separate decision to let the machine place orders unattended |
| 66 | not tradable live | a forecast: 'No trade'; it changes no running book unless a new number says so | a forecast, no trade | — |
| 69 | not tradable live | a measurement, information only | a measurement | — |
| 70 | not tradable live | a rule, not a trade: it halves or flattens a live sleeve through its scale | a rule acting through the risk gate | — |

**Shared by every tradable rule, in the order they would be met:**

1. its verdict, judged once after 2027-03-31 by its frozen criteria (and its tier's confirmation window)
2. a sizing-and-execution document from research/TEMPLATE_SIZING.md, one at a time in order of t
3. the account holder's inputs (docs/HOLDER_INPUTS.md); until then the capital is 0
4. a venue the holder has checked as eligible, with its costs measured (research/VENUE_NONUS.md)
5. the ladder's rungs: paper twin, testnet mechanics, then a mainnet canary
6. the holder's written lift of the no-mainnet rule and a mainnet module built from DESIGN_MAINNET_PATH.md
7. edgewatch's parameters from its verdict window (#70)

Counts: live-from-tape 9, operator-paced 4, next-day-batch 3, not tradable live 14.
<!-- latency:end -->

## What the audit found, information only

Each item is a fact about the registered rules or the machine they run on. None changes a verdict; each is
on the distance list of the rule it touches.

1. **Four rules label a break by its rank within its whole UTC day:** #26, #27, #32 and #45 call a break
   "forced" by the tercile of its forced share among that day's breaks, on days with 6 or more (`liq.py`,
   `liqbreak.py`). The forced share is known at the break; the label is not. A live version would need a label
   from data before the break, which is a new rule and a new number.
2. **#22 and #23 fill at the spike bar's own close**, which AGENTS.md's next-open rule would not allow; their
   plans say so. A live order comes after the close, and the testnet rung measures by how much.
3. **#38 enters at P(t) with the rate settled at t.** #19 treated that rate as not known beforehand; a live
   order can only follow the settlement.
4. **Every Binance-bar test assumes a fill at the next bar's open with no delay.** The Hyperliquid tests allow
   60 seconds and a 5-minute window.
5. **#4's paper account fills at the latest close;** its registration fills at the next month's first open.
6. **#12's two legs are priced at different moments** in the paper book (Hyperliquid's forming candle, Coinbase's
   completed one), read from the code and not checked on data.
7. **#61 and #62 are written as judged "at the first daily run after" their counts are reached**, but no
   daily step runs them: their research scripts do.
8. **#49 is `forward_pending` in trials.csv, and its note says it is not a forward test;** it was never run.
9. **From this Mac,** Binance's `forceOrder`, `aggTrade` and `markPrice` streams are silent and its REST answers
   451, and Bybit's REST is blocked. #22's and #23's liquidations and #38's funding rate cannot be fed live
   from here.
10. **The raw tape carries 13 Binance symbols** (BTC ETH SOL BNB XRP ADA DOGE AVAX LINK TRX LTC XLM HBAR), so 29
    of the 42 coins #24 and #31 trade are not recorded.
11. **#8's daily run comes 12.5 hours after its registered Monday 00:00 UTC fill,** past its 8.4-hour budget;
    a run shortly after midnight UTC would make it operator-paced (ERRATA notes the gap).
12. **#60, #64 and #65 have no live evaluator:** their events are computed only by `--verdict`, after
    2027-03-31. Their inputs are recorded live, so a live evaluator is the missing piece.

## How the table is held

- **A new rule cannot be added without a row:** the test reads `research/trials.csv` and fails for any `pass`,
  `provisional` or `forward_pending` test missing from `espero.latency.ROWS`. A new pre-registration adds its row
  in the same commit.
- **A class cannot be asserted:** each row states its class, and the test fails when `classify` gives another
  from the row's own budget, feed and the operator's response time.
- **This page cannot drift:** `python -m espero.latency` rewrites the table between the markers;
  `--check` and the test fail when it is stale.

## Limits

- The 5 % convention is a judgment about how much of a tested trade a live one must share. A rule whose
  edge sits in its first seconds (#57 found the Binance catch-up gone at one second) tolerates less than
  the table says; the testnet rung measures placement against the budget for each sleeve.
- Feed delays are measured where the repo measures them (the tape's one-second flush, the HLP books' two to
  three minutes, the carry loop's publish grace); a daily close's hour from Yahoo is assumed.
- live-from-tape says the inputs could arrive in time. It needs a live evaluator: #71's streaming engine for the
  Binance bar rules, the HLP books for #58 and #59, none yet for #60, #64 and #65.
- An operator-paced rule trades only the events whose window meets the operator's hours: silence means no
  entry, so the live sleeve is a subsample of the registered one. #69 reports what silence cost.
