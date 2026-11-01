# Pre-registration — five patterns for the operator to read on Hyperliquid (#52–#56)

All five are committed together **before any of their new files is downloaded or read**, so no result can shape a later
rule. They run in the order #52, #53, #54, #55, #56, each once.

**These are measurements, not edge tests.** The account holder asked for patterns and direction that help an operator
read the market, not necessarily an edge. There is no "it pays" criterion and no pass or fail. No result becomes a rule,
a label, or an input to `espero rate` or the UI. As `research/PLAN_REGIMES.md` sets out, that takes a forward window.
Nothing here changes a frozen test.

## What the author already knew

- **These days have been read.** #39, #41, #51 and a data-quality check all used Tardis's first-of-month Hyperliquid days:
  touch costs, markouts, book walks, and day-level volume and ranges. No test on these days has measured any of the five
  relationships below. The check's cross-check of trades against the book showed only how far trades printed from mid.
- **Earlier leads in the repo.** #33 and #38 looked at moves after funding settlements, #18 and #26 at forced breaks, and
  #39 at markouts, mostly on Binance. They may colour expectations but are different measurements.
- **#53 is partly mechanical.** Hyperliquid builds its mark price partly from the index, so some mark–index reversion is
  definitional. It only adds something if the next move is larger or more reliable than that.
- **Which way the author expects it to go:** Binance moving first (#52) on most coin-days; a small reversion in #53;
  short continuation in #54 and #55 that fades within minutes and stays below the fee; refill in seconds (#56).

## Shared data and rules

- **Source.** Tardis.dev free first-of-month days, 2024-11-01 to 2026-10-01, no key. New files are cached in
  `data/patterns/`. Book files are the ones #51 cached in `data/bookwalk/`. A missing file is recorded, not filled.
- **Coins.** #45's 14 (BTC, ETH, SOL, XRP, DOGE, LINK, ADA, AVAX, BNB, TRX, LTC, XLM, HBAR, kSHIB), except #52, which uses
  the six with measured costs on Hyperliquid and the most liquid Binance markets among them: BTC, ETH, SOL, XRP, DOGE, LINK.
- **Book depth.** #51 found `book_snapshot_25` has 5 levels from 2026-07-01, so every book measure uses only the top 5
  levels on all days. Mid is from the best bid and ask, last value in each second.
- **No lookahead.** A state uses only data up to its decision time. Its cut-offs come from the previous 120 minutes,
  excluding the current minute, with at least 60 minutes of history.

## The state studies: #53, #54 and #55

Decision times are each whole minute of the day. At each one:

- **High state:** the signal is at or above the 80th percentile of its previous 120 minutes.
- **Low state:** at or below the 20th percentile. Anything else is neither.
- **The move:** the forward change in bps over each horizon. A move running past the end of the day is dropped.
- **A coin-day's value:** mean move after high minus mean move after low, needing at least 20 of each. **Positive means
  the signal's direction continued.**
- **A horizon's value:** average the coins within each day, then the mean of the days. The CI is a percentile bootstrap
  over days, 10,000 draws, at **98.75%** (5% split across 4 horizons).

**CLEAR PATTERN** needs all of: the CI excludes zero, the first 12 days and last 12 days have the same sign, and at least
9 of 14 coins' means have that sign. Otherwise **NO CLEAR PATTERN**. Reported alongside: the size against the $1,000 round
trip of about 9–12 bps from #51, whether it's above that, and the share of high and low states followed by an up move.

**Power.** With 24 days, a clear result needs an effect of about 0.6 standard deviations of the day-level value or more.
Smaller effects can't be told from noise here. A NO CLEAR PATTERN doesn't show there's no effect.

### #53 — mark price against index

- **Signal:** premium = (mark / index − 1) × 10,000, the last value in each minute, from `derivative_ticker`.
- **The move:** the change in mark price. Horizons 1, 5, 15 and 60 minutes.
- **Also reported:** the same table for the premium's own change, which shows how much is the definitional reversion.
- **The sentence it fills:** "When the premium is high for the last two hours, mark over the next N minutes moved X bps
  against / with it compared with when it's low."

### #54 — aggressive buying and selling

- **Signal:** (buy notional − sell notional) / total notional over the previous 60 seconds, from `trades`. A minute with no
  trades has no signal.
- **The move:** the change in mid. Horizons 10 seconds, 1, 5 and 15 minutes.
- **The sentence it fills:** "After unusually one-sided buying, the next N minutes moved X bps more than after unusually
  one-sided selling."

### #55 — book imbalance

- **Signal:** bid notional / (bid + ask notional) across the top 5 levels, the mean of the previous 10 seconds of
  snapshots.
- **The move:** the change in mid. Horizons 10 seconds, 1, 5 and 15 minutes.
- **Separate from #49.** `PREREGISTRATION_DEPTHDAY.md` is Binance's ±1% book predicting the next day. This is Hyperliquid's
  top of book over seconds to minutes. The free days fall inside #49's sealed window, but on a different venue and file.
  No Binance book file is read here, and #49 stays sealed.
- **The sentence it fills:** "When the visible book leans to bids, the next N minutes moved X bps more than when it leans
  to asks."

## #52 — who moves first, Hyperliquid or Binance

Six coins, 24 days. **Data:** Hyperliquid and Binance USDⓈ-M `trades`, because Hyperliquid's quotes arrive only about every
half second.

- **The clock.** Primary: `local_timestamp`, Tardis's one receipt clock. It includes each venue's network path to the
  recorder, so it's the lead **as a recorder sees it**, which is the question for an operator. Robustness: the exchanges'
  own `timestamp`, which adds clock skew. If the two disagree, that's reported as the result, without choosing.
- **Peak lag.** Last trade price on a 100 ms grid, then the correlation of the two venues' returns at each lag up to ±5 s.
  The peak lag is the lag with the highest correlation. **Positive means Binance first.**
- **A day's value:** the median peak lag across coins. CI: percentile bootstrap over days, 95%, 10,000 draws.
- **CLEAR LEADER** if the CI excludes zero, both halves have the same sign, and at least 4 of 6 coins' medians have that
  sign. Otherwise **NO CLEAR LEADER**. A lag at or below 100 ms is below what this grid can resolve, and is reported as such.
- **Also reported:**
  - **As a stand-in:** per coin, the median and 99th-percentile absolute price gap between venues on a 1-minute grid, and
    the correlation of 5-minute returns.
  - **After a large move:** when one venue moves at least 10 bps in one second (at least 30 s since its last such event),
    the other venue's mean move in that direction over the next 1, 5 and 30 s.
- **The sentence it fills:** "Binance moved first on N of M coin-days by about X ms; after a 10 bps move on one venue, the
  other moved Y bps further in the next Z seconds."

**Limits.** The lead depends on where Tardis's recorder sits, and an operator elsewhere will differ. It can't show a
tradable lag, because our own reaction time and fees aren't in it.

## #56 — how fast the book refills

14 coins, 24 days, from `trades` and book snapshots. Descriptive, with no CLEAR label.

- **Burst.** Taker notional in one second on one side, in the top 1% of that coin-day's seconds with trades, and at least
  60 s after the coin's previous burst. The day-level cut-off is descriptive: it isn't known in real time.
- **Baseline.** The median over 60 s to 5 s before the burst of the hit side's top-5 notional and of the spread.
- **Refilled.** The first snapshot at or after the burst when the hit side's top-5 notional is at least 90% of its baseline.
  A burst not refilled within 300 s is censored at 300 s.
- **Reported per coin:** the number of bursts, the median refill time, the share refilled by 1, 5, 30, 60 and 300 s, depth
  at its lowest as a share of baseline, and the mean mid move in the burst's direction after 1, 5, 30 and 60 s, with a 95%
  bootstrap CI over days for the last.
- **The sentence it fills:** "After a large burst, the hit side's depth returned in about X seconds at the median, and price
  moved Y bps with or against the burst over the next minute."

**Limits.** Top-5 depth is what's visible, and snapshots are half a second apart, so a refill under a second can't be
resolved. It covers calm days only.

## What all five can't show

First-of-month days include no known cascade. Effects are averages and don't say what the next instance will do. Costs,
latency and funding aren't included. A CLEAR label is about these 24 days, not a forecast. **None of this is investment
advice, and nothing here places an order.**

## Run once

`python research/patterns.py fetch`, **then read its log**, then `python research/patterns.py run 52`, 53, 54, 55 and 56
in order. Each writes `research/patterns_<n>_output.txt` and refuses a second run. They're written up in
`research/RESULTS_PATTERNS.md` and summed up for the operator in `research/OPERATOR_READOUT.md`, whatever they show. Anything
looked at afterwards is labelled information only. Each gets a row in `research/trials.csv` as a measurement, with no p-value.
