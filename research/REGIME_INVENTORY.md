# What this repo's finished tests already say about regimes — step 1 of [PLAN_REGIMES.md](PLAN_REGIMES.md)

**Written 2026-10-31. It runs nothing, proves nothing and spends no trial.** It collects what finished result documents
already state. No forward running number, ledger or data file was read.

**Answer: no finished test has cut the rating's signals by these four regimes, so this inventory can't say that any regime
works.** What exists points mostly the other way: where a state was tested directly, it helped risk, or it was real but
too small to trade, or it faded with time.

**Every row:** [regime_inventory.csv](regime_inventory.csv), 416 rows from 33 of the 37 documents read. Each has its source line and an exact
quote, and every quote was checked by script against that line.

| regime | rows | defined at the time | hindsight | unclear |
|---|---|---|---|---|
| calendar period (often standing in for a regime) | 169 | 104 | 65 | 0 |
| other states (forced share, busy days, coin traits) | 90 | 40 | 44 | 6 |
| funding | 83 | 40 | 16 | 27 |
| trend | 38 | 23 | 14 | 1 |
| volatility | 27 | 16 | 2 | 9 |
| market stress | 9 | 1 | 7 | 1 |

309 of the 416 rows are information-only, not pass criteria. So this is mostly a list of things noticed, and that's how to
read it. The timing column is a reviewer's classification from the documents, and only the rows quoted below were re-read.

## By regime

### Trend (above or below a long average)

- **As a timing filter it added no return.** #15: "mean(e) −0.44 bps/wk; NW t −0.18", and "Trend timing bought drawdown
  protection and nothing else" ([RESULTS_TREND.md:21](RESULTS_TREND.md), [:26](RESULTS_TREND.md)).
- **As a per-coin trade it showed nothing.** #43, long, 1 week: "+155 (1.3)", with no horizon reaching t ≥ 2
  ([RESULTS_HORIZONS.md:39](RESULTS_HORIZONS.md)).
- **Some strong results were mostly a rising market.** #21: "The long leg's profit is mostly the market"
  ([RESULTS_LIQSPIKE.md:41](RESULTS_LIQSPIKE.md)). A regime test has to separate the signal from the market's own drift.
- **Never tested:** a signal's result split above and below the 200-day average. #2 only named it as a possible idea
  ([RESULTS.md:61](RESULTS.md)).

### Volatility

- **Sizing helps risk, not direction.** #15: "holding less when volatility is high does the work; the signal adds little or
  nothing to it" ([RESULTS_TREND.md:30-31](RESULTS_TREND.md)). #4 and #8 say the same.
- **The calm-coin tilt rests on weak ground.** #8 credits it, and calls it "one contaminated window" ([RESULTS_MF.md:132](RESULTS_MF.md)).
- **Never tested:** whether a directional signal's hit rate changes with the volatility regime.

### Funding

This has the most evidence, and it is also the most used up.

- **Settlement effect, real and too small.** #19: "real, not tradable after costs", growing with the rate up to "+86.4 bps at
  0.2% and above" (information only) ([RESULTS_SETTLE.md:3](RESULTS_SETTLE.md), [:43](RESULTS_SETTLE.md)).
- **Shorts paying hard is fragile.** #33's "−34.0 bps, t −2.62" becomes "−20.1 (−0.77)" under #44's audit
  ([RESULTS_FILLCOST.md:30](RESULTS_FILLCOST.md), [RESULTS_DAYMEAN_AUDIT.md:30](RESULTS_DAYMEAN_AUDIT.md)).
  #43 finds that the fall reverses, a large loss for the short from 4 hours on ([RESULTS_HORIZONS.md:44-45](RESULTS_HORIZONS.md)).
- **Longs paying failed.** #33: "+16.3 bps, t 0.92" ([RESULTS_FILLCOST.md:28](RESULTS_FILLCOST.md)).
- **Extreme negative funding failed.** #1: "25 trades in 7.5 years, t = 0.91" ([FINDINGS.md:62](FINDINGS.md)).
- **Carry depends on the period.** #11: "regime faded after 2024" ([RESULTS_CARRY.md:110](RESULTS_CARRY.md)), judged in hindsight.

### Market stress

The thinnest regime: 9 rows, and only 1 defined at the time. That one is negative.

- **Crowded sell-offs did not bounce.** #43, counting other coins' triggers before entry, on the holdout: "+8.3 (none before),
  +4.4 (1–2) and **−13.8 (3 or more, 78% of trades)**", and "No causal bucket is clearly positive"
  ([RESULTS_HORIZONS.md:85-86](RESULTS_HORIZONS.md)).
- **#21 agrees, in hindsight.** "busy days, when many coins cascaded together, did not" revert ([RESULTS_LIQSPIKE.md:40](RESULTS_LIQSPIKE.md)).
- **Never tested:** a large fall from the high, as this plan defines stress.

## Time as a warning

Effects fading with time recur. #20: "the bounce is weaker since 2022" ([RESULTS_LOWS.md:37](RESULTS_LOWS.md)). #25: "the
difference has faded" ([RESULTS_OI.md:5](RESULTS_OI.md)). #33's mirror criterion fails "not one era" ([RESULTS_FILLCOST.md:31](RESULTS_FILLCOST.md)).
**This is why step 5's two-halves test matters: a regime and a period are easy to confuse.** Most period labels are hindsight, and
this inventory doesn't treat them as regimes.

## Documents that disagree

- **What drove #4's pass:** a trend filter sitting in cash ([RESULTS_TSMOM.md:39-40](RESULTS_TSMOM.md)), or the book halving when
  volatility doubles ([RESULTS_MF.md:53](RESULTS_MF.md)).
- **Quiet and busy days:** #26's forced effect is "about half as large on the quiet days" ([RESULTS_LIQ2.md:38](RESULTS_LIQ2.md)),
  while #21 and #43 see quiet events revert and busy days not. These are different statistics, so it isn't a direct conflict.
- **"Extreme" funding is defined differently:** z below −2 in #1, an absolute 0.05% in #19 and #33. #1 also shows its cut fires very
  differently by venue ([FINDINGS.md:66](FINDINGS.md)).
- **Small mismatches:** #33's shorts-paying count is 198 in [RESULTS_FILLCOST.md:30](RESULTS_FILLCOST.md) and 197 in
  [RESULTS_DAYMEAN_AUDIT.md:30](RESULTS_DAYMEAN_AUDIT.md). #2's design period is covered in ERRATA, 2026-10-30.

## What step 3 must carry forward

- **Overlap with frozen tests.** A funding candidate overlaps #32 and #38. A stress candidate overlaps the forced-selling and dip
  tests (#22, #24, #27, #45). Their forward windows can't be read, and a pass here would not be independent of them.
- **The author is no longer blind.** The four regime names were written down before this read, but cut-offs and candidates
  will be chosen knowing everything above. Each registration must say so.
- **Coverage is uneven.** Four documents have no regime evidence: DEGEN, LEADLAG, REHEARSAL and TESTNET.

## Not verified

- The 416 rows came from one reviewer's read. Their quotes were checked by script, and not every row's reading or timing label was
  checked by hand. A row may be missing, and "never tested" means not found in these documents.
- `PREREGISTRATION_*` files were not opened, so "pre-registered" rests on what result documents say.
