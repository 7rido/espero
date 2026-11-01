# Pre-registration — what does a market order cost on Hyperliquid as it gets larger? (#51)

Committed **before any new book file is read**. The download started moments before this commit, because a scripting
error made the commit fail while the download went ahead; no file was opened. A measurement, not a strategy: nothing
trades, no signal is used, and no return is computed. It claims no edge.

## Why

`espero.costs`, from #39 and #41, measures Hyperliquid's taker cost "for a fill too small to walk the book". Every
forward test charges that cost, or an assumed 18 bps round trip. How much a larger order adds has never been measured
on this venue. Tardis.dev's free days include the order book, the one file those tests didn't use.

**The question:** at $1,000, $10,000 and $100,000 a leg, what does a market order cost on each of #45's 14 coins, and
does an 18 bps round trip still cover it?

**This changes no frozen test.** #45, #27 and the others keep their committed costs and hurdles. The result can only
inform a later sizing document, as `research/FORWARD_FAMILY.md` describes.

## What the author already knew

- **Small-order costs on these same days.** `RESULTS_MARKOUT.md` and #41's results read Tardis's trades and quotes on
  the first of each month, 2024-11 to 2026-10. So this is not a sealed sample, and 10 of the coins' touch costs are
  already in `espero/costs_table.py`.
- **Part of this answer, for 9 coin-days.** A data-quality check on 2026-10-31 printed median ask-side walk costs and
  unfillable shares at all three sizes for BTC, SOL and DOGE on 2025-02-01, 2025-10-01 and 2026-10-01. Medians from
  mid, ask side only: BTC 0.04–0.06 bps at every size, SOL 0.22–0.78, DOGE 0.16–1.89. They stay in the sample, handled
  like every other day, and step 5 repeats the main result without them.
- **The book narrows.** That check, and a look at the first rows of later files for BTC and DOGE, found 20 levels a
  side through 2026-08-01 and 5 from 2026-09-01. The handling below was fixed after seeing this.
- **Which way the author expects it to go.** $1,000 and $10,000 covered almost everywhere; $100,000 covered on the
  largest coins, and unfillable or unknown on some small ones.

## Data — fixed

- **Source.** Tardis.dev `book_snapshot_25`, exchange `hyperliquid`, the free first-of-month days, no key. They are
  cached in `data/bookwalk/` (git-ignored). Tardis's file holds Hyperliquid's book feed, sampled about every 0.54 s.
- **Coins.** #45's 14: BTC, ETH, SOL, XRP, DOGE, LINK, ADA, AVAX, BNB, TRX, LTC, XLM, HBAR, and SHIB as Hyperliquid's
  `kSHIB`. Fixed from `research/FORWARD_LIQHOLD.md`, and checked against Tardis's symbol list: all are listed, and XLM
  starts 2024-11-23, so it has no 2024-11-01 file.
- **Days.** 24: the first of each month, 2024-11-01 to 2026-10-01.
  - **Main group:** the 22 days through 2026-08-01.
  - **Thin group:** 2026-09-01 and 2026-10-01. Reported separately, with the unfillable share first and cost only
    where the book could fill. Never pooled with the main group.
- **A missing file** is recorded as missing, not filled from elsewhere.

## The measurement — fixed

For each snapshot, each side and each size:

1. Mid = (best ask + best bid) / 2. A crossed or one-sided snapshot is dropped and counted.
2. Walk the visible levels from the best price until the dollars are spent, and take the average fill price.
3. Cost = (average fill / mid − 1) × 10,000 for a buy, and (1 − average fill / mid) × 10,000 for a sell.
4. If the visible levels hold fewer dollars than the size, the snapshot is **unfillable** for that side and size. It
   has no cost. Its true cost is above anything measured, so an unfillable share biases the mean cost low.

**A coin-day's value:** for each side, the mean over fillable snapshots, then the mean of the two sides. If either side
has no fillable snapshot, the coin-day has no cost. Its unfillable share is the mean over all snapshots of both sides.

**A coin-size's value:** the mean of its coin-days, with a 95% percentile bootstrap CI that resamples days (10,000
draws, seed 51). The day is the unit, because snapshots within a day aren't independent.

## The verdict, one per coin and size, main group only

The round trip is 2 × (4.5 bps Hyperliquid base taker fee + cost).

| verdict | rule, checked in this order |
|---|---|
| **UNKNOWN** | Mean unfillable share above 5%, or fewer than 10 days with a cost |
| **COVERED** | Round trip at the CI's upper end ≤ 18 bps |
| **NOT COVERED** | Round trip at the CI's lower end > 18 bps |
| **UNKNOWN** | Anything else: the CI spans 18 bps |

The test's result is the full table, 42 verdicts. No overall pass or fail, because this is a measurement.

## Reported alongside

1. Each coin-size's mean cost, CI, mean unfillable share and the mean of each day's 95th-percentile snapshot cost.
2. **Validation.** The $1,000 cost against the measured `taker` half-spread in `espero/costs_table.py`, for the coins
   both cover: BTC, ETH, SOL, XRP, DOGE, LINK. Tolerance 0.5 bp. A miss is named, not explained away, and the two differ
   in kind: one is the book at any moment, the other the spread actually paid by real trades.
3. Coin-days with fewer than 20 levels on either side in the main group, and dropped snapshots.
4. The thin group, as fixed above.
5. The main result without the 9 coin-days the author had already seen.

## What this can't show

- **Crashes.** First-of-month days are a fixed sample. No known cascade falls on one, so the cost in the moments a
  liquidation test trades is not measured here. COVERED means on these days.
- **A market that reacts.** It charges the book as displayed, with no other trader responding to the order, and with
  no latency. Depth beyond 20 levels is invisible.
- **Between snapshots.** Anything inside the 0.54 s isn't seen. Resting-order fills are outside this test.
- **Binance.** The forward tests price on Binance and charge Hyperliquid's costs. This says nothing about the price gap
  between the two.

## Run once

`python research/bookwalk.py fetch`, then `python research/bookwalk.py report` once. The output is saved as
`research/bookwalk_output.txt` and written up in `research/RESULTS_BOOKWALK.md`, whatever it shows. Anything looked at
afterwards is labelled information only. A row is added to `research/trials.csv` as a measurement, with no p-value.
