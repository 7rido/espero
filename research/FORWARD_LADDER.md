# Forward test — buying after the price falls through a dense liquidation band (#60)

Committed **before any day of the forward window exists**: the window opens 2026-11-05, and this was
written on 2026-11-01. A paper test: nothing trades. The sixtieth test in this repo.

## Why

This is idea 3 in [IDEAS_NOVEL.md](IDEAS_NOVEL.md), Hyperliquid's exact liquidation ladder. Other venues
offer estimated liquidation heatmaps. On Hyperliquid, each open position's liquidation price is public, and
`espero hlcollect` has recorded those of about 2,000 large accounts every hour since 2026-10-29.

**The mechanism**, from #26: forced selling pushes a price further than ordinary selling does, and that
overshoot reverts. A dense band of long liquidation prices just below the market is forced selling waiting
to happen.

**The prediction.** After the price falls all the way through a dense band of long liquidation prices, it
rises over the next 4 hours, by more than the cost of trading it, and by more than after the same size of
fall through a thin band.

The idea note has a second part, that the price moves faster through a dense band. That part is
information only here. It isn't a trade, and it can't be measured well on hourly snapshots.

## Data — fixed

- **Coins.** #45's 14: BTC, ETH, SOL, XRP, DOGE, LINK, ADA, AVAX, BNB, TRX, LTC, XLM, HBAR, and SHIB as
  Hyperliquid's `kSHIB`.
- **Window.** Signals from 2026-11-05 00:00 UTC through 2027-03-31 23:59 UTC, 147 days. Slots from
  2026-10-29 until the window opens serve only as the first trailing history.
- **Positions.** `data/hlcollect/positions/`, one file per hourly slot. A file's `ts` is when its read
  **started**, and its accounts are read one after another over the next 20–28 minutes.
- **Prices.** `data/hlcollect/candles/`, Hyperliquid's own 1-minute candles. Candles missing from a file may
  be taken from Hyperliquid's public candle API while it still serves them, and the count is reported.
  No other venue's prices are used.
- **Funding.** Hyperliquid's settled hourly rates, from its public funding history.
- **Gaps.** A gap stays a gap. A slot missing from disk gives no signal and is never rebuilt.

## The rule — fixed

For each coin and each hourly positions file, with `ts` the file's value:

1. **When the band is known.** `A = ts + 1800 s`. The slowest of the 65 reads so far finished about 1,700 s
   after its `ts`, so nothing in the file is used before it could have been read.
2. **Price.** `C(s)` is the close of the last 1-minute candle that ended at or before `s`.
3. **The band.** `L`, in dollars, is the sum of `value` over the file's rows for this coin with `szi > 0`
   and `C(A) × 0.99 ≤ liq < C(A)`. A blank `liq` is left out.
4. **Trailing history.** `L` from the coin's slots with `ts` in the 168 hours before this one, not including
   this one. At least 84 are required, or the slot gives no signal.
5. **Dense.** `L > 0`, and `L` is above the 90th percentile of the trailing values.
6. **Through the band.** `C(B) ≤ C(A) × 0.99`, with `B = A + 3600 s`.
7. **Signal.** Rules 5 and 6 both hold. The signal's time is `B`.
8. **Entry.** Long, at the open of the first 1-minute candle starting at least 60 s after `B`. If that
   candle isn't within 5 minutes of `B`, the trade is dropped and counted.
9. **Exit.** At the open of the first 1-minute candle starting at least 4 hours after entry. If that candle
   isn't within 5 minutes of the 4-hour mark, the trade is dropped and counted. A trade whose exit falls
   after the window is dropped.
10. **One at a time.** A coin holds one trade. A signal during a hold is ignored, with no adding to it.

**The comparison group.** A slot where rule 6 holds and `L` is at or below the median of its trailing values
(including `L = 0`) gives a **thin** event. It goes through rules 8–10 in its own ledger, separate from the
signals' one-at-a-time. It's never traded.

**Net, in bps per trade** = gross − 18 − funding. A long pays positive rates settled in (entry, exit]. The
18 bps is the repo's forward hurdle, charged on every coin. #51's cost measurements exclude sharp falls, and
these entries come straight after one.

## Evaluation — once, after 2027-03-31

The headline is the **trade-weighted mean net**, with its t from `espero.audit.trade_weighted_nw`, lags = 1,
using the entry's UTC day.

**PASS requires all of these:**

1. **It pays.** Trade-weighted net > 0 with t ≥ 3.
2. **Not one stretch.** Net > 0 in each half: entries before 2027-01-17 00:00 UTC, and from then on.
3. **Not one coin.** Among coins with at least 10 trades, more than half have net > 0.
4. **On the largest coins too.** Net > 0 across BTC, ETH, SOL, XRP, DOGE and LINK together.
5. **The band matters.** The signals' trade-weighted net is above the thin events'. If there are fewer than
   30 thin events, this criterion can't be met.

**INCONCLUSIVE:** fewer than 100 trades. **Anything else: FAIL.** If 1–4 hold and 5 fails, the verdict is
"FAIL (it bounces, but the band adds nothing)".

**Information only**, never a claim (`FORWARD_FAMILY.md`):

- holds of 1 hour and 1 day;
- bands 0.5% and 2% wide, and the 75th and 95th percentiles;
- the mirror: short positions' liquidation prices above the market, with the price rising through them, shorted;
- how fast the price fell through dense and thin bands;
- the share of the band's positions gone from the next slot, which can't separate liquidations from closes,
  accounts that left the leaderboard or failed reads;
- gross and funding separately, and the hit rate;
- by coin, and by cross and isolated margin;
- each coin's share of rows with a blank `liq`, and counts of signals, dropped trades and missing slots.

## Power — stated now

There's no prior effect size, because nothing has tested this data, so these are planning numbers only.

- **Trades.** The window has about 49,400 coin-slots before gaps. The dense condition passes about 10% by
  construction. How often a coin falls 1% in an hour hasn't been measured for this; 5% is assumed. If the two
  were independent, that's about 250 signals. A dense band may attract falls, or calm periods may build
  bands, so the real number could differ either way. One-at-a-time removes some.
- **Noise.** About 150 bps per trade over 4 hours is assumed, not measured. Trades that cluster in one sell-off
  add to it.
- **What that detects.**

  | trades | net needed for t = 3, ignoring clustering |
  |---|---|
  | 200 | about +32 bps |
  | 500 | about +20 bps |

- **For scale.** #26's forced-liquidation bounce netted about +22 bps at 4 hours, in sample. At that size, 250
  trades give an expected t of about 2.3, a pass chance of roughly 25% on criterion 1 alone.

**A FAIL here is weak evidence against the idea, unless the estimate itself is near or below zero.** The
author expects this to fail more likely than pass: the bar is high, the data covers only part of the market,
and a 1% fall is common.

## Outcomes, fixed now

- **PASS**: treated as a Tier A pass under `FORWARD_FAMILY.md`, rule 2: a real-money sizing and execution
  document, written before any order, on a venue from [VENUE_NONUS.md](VENUE_NONUS.md). The account holder
  checks eligibility and places any order.
- **FAIL**: this rule is closed. A later idea on the ladder takes a new number and a new document.
- **INCONCLUSIVE**: no claim either way, and no extension of this test. Any continuation is a new document.

No stopping early on the running numbers, and no re-tuning of the band, the percentile, the hold or the coins.

The ledger's code doesn't exist yet. It's written and mutation-checked on made-up files before the verdict, and
the verdict is rebuilt from the recordings. There's no paper book, and this document starts no new process.

## Known confounds

- **Part of the market.** Only about 2,000 large accounts are recorded. Smaller accounts' liquidations, and every
  other venue's, are missing, and the list of accounts changes over time.
- **Blank liquidation prices.** About 35% of the rows in one recent file had none. They're left out, so `L`
  understates what's there.
- **Cross margin.** A cross-margined position's liquidation price depends on the rest of the account, so it can
  move after the read, and it may not be hit where it says.
- **Stale by up to an hour and a half.** The band is read over the half hour before `A`, then the fall is
  measured over the next hour. Positions can change in that time.
- **A slower read.** Rule 1 assumes a read ends within 1,800 s. The file doesn't record when it finished, so a
  slower one can't be detected from it.
- **No proof of liquidation.** Falling through the band doesn't show those positions were liquidated.
- **Costs in a sell-off.** 18 bps may be too low at these moments.
- **Related to the forced-liquidation family.** Signals may coincide with #27, #32, #45, #58 and #59's events.
  A pass alongside those isn't fully independent. The overlap is reported.
- **Coverage.** Slots are lost when the Mac sleeps, and sleep during sell-offs would remove the events this test
  needs.
- **The thresholds have no data behind them.** The 1% band, the 90th percentile, the 7-day history and the
  1-hour fall are the author's choices. The 4 hours follows #45 and #58.

## Transparency — what was seen before this

- **Seen in writing this, from the positions files:** the column names; one row, the first of the 0700 file on
  2026-11-01, a large BTC short with its liquidation price far above its entry, which plays no part in a
  long-side band; row counts; the share of blank `liq` in that file; which of the 14 coins it holds; and each
  file's start and finish times.
- **Not seen:** any band, any `L`, any return after a band, any candle value from the recordings.
- **A limit on that.** Earlier work may have opened these files. This can only speak to what the repo records.
- **Already known:** #26's and #44's forced-liquidation results, #51's costs, and #52–#57's microstructure
  measurements. None uses the positions files.
- **A related prompt.** The user asked about a public liquidation heatmap site on 2026-11-01. It gave no data used
  here.
- **No day of the forward window exists yet.**
