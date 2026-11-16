# Pre-registration — session swings: how big each coin's moves are, hour by hour of the week (#82)

Committed **before any swing is computed by hour, by day or by week.** A measurement, not a strategy: nothing trades, no
signal is used, and it claims no edge. It is not judged under the FDR bar (research/FDR_STANDARD.md) and enters
`research/trials.csv` as a measurement. The readouts below are fixed now and reported as stated; nothing below is
changed afterwards. A later idea takes a new number.

## Why

The account holder asked when the moves and swings come. Knowing **how big** the moves of an hour usually are is not
knowing **which way** they go, but it is what every entry and exit needs: when a resting order is likely to be filled
or run over, when a stop is likely to be hit, when a breakout rule should be awake, and when the Market tab should say
"this hour is usually busy". The questions, fixed now:

1. **Do the hours repeat?** Within weekdays, does each coin's profile of swing size by hour of the day, measured on
   2020 to 2024, still hold on 2025 to 2026?
2. **Which clock?** Are the busy hours set by the UTC clock (Asia's open, Hyperliquid's and Binance's funding at 00,
   08 and 16 UTC) or by New York's (the US equity open and close, which move an hour against UTC with daylight saving)?
   Measured both ways, which clock gives the sharper and more repeatable profile?
3. **How large?** How much bigger is the busiest weekday hour than the quietest, and how much quieter is the weekend?

## What the author already knew

- **The priors are well known**, and this test expects them: crypto is quieter at weekends; volume and volatility rise
  around the US equity open (9:30 a.m. New York: 14:30 UTC in winter, 13:30 UTC in summer) and around funding
  settlements; Asia's morning starts near 00:00 UTC. What is not known here is
  their size on these coins, whether they hold coin by coin in a later period, and which clock they follow.
- **Nothing in this repo has computed a swing profile by hour** on these files. #68 measured a market order's cost by
  hour on Hyperliquid's books and found it barely varies on SOL; #29 tests the US session's move after the close as a
  forward rule; #66 forecasts the week's volatility from daily bars. None of them sees the hour-of-week profile here.
- **The author has opened these files only for their columns and date ranges** (open, high, low, close, volume per
  hour; 17 coins), not their values, before this commit.

## Data — fixed

- **Files.** `data/pit/klines_1h/<COIN>USDT/<YYYY-MM>.parquet`, Binance USD-M perpetual hourly bars from Binance's
  public archive (docs/DATA.md). Nothing is fetched; nothing under `data/` is written.
- **Coins.** All 17 on disk: AAVE, ADA, AVAX, BNB, BTC, DOGE, ENA, ETH, LINK, LTC, NEAR, SOL, UNI, WLD, XRP, ZEC, ZRO.
- **Window.** Each coin's first month on disk to 2026-09 inclusive (2020-01 at the earliest).
- **The split, by date.** In-sample **2020-01-01 to 2024-12-31**; out-of-sample **2025-01-01 to 2026-09-30**. A coin
  with fewer than 12 months in either half (ENA from 2024-04, ZRO from 2024-06) is reported as information and left out
  of the readouts that compare the halves: 15 coins compare.
- **Bars kept.** A bar with zero volume, or high below low, or any price not positive, is dropped and counted. A coin's
  first 30 days are dropped (the normaliser below needs them). A missing hour stays missing.

## The measurement — fixed

- **Two swing sizes per bar:** the body, `|ln(close / open)|`, and the range, `ln(high / low)`.
- **Each normalised by the coin's own recent level:** divided by the mean of the same measure over the coin's previous
  720 bars (30 days), past bars only, the current bar excluded. A normalised swing of 1.5 is an hour 50 % bigger than
  the coin's last month's average hour. This keeps 2021's and 2026's markets, and BTC and ZEC, on one scale.
- **Three profiles per coin and per half,** each the mean normalised swing in a slot:
  - the **week**: 168 slots, day of week by hour, UTC;
  - the **days**: 7 slots, UTC;
  - the **weekday hours**: 24 slots, Monday to Friday only, by the hour of the day, computed twice: on the **UTC** clock,
    and on the **New York** clock (America/New_York, daylight saving applied, via `zoneinfo`).
- **Pooled profiles** average the 15 comparing coins' profiles with equal weight.
- The body is the primary measure; the range is reported beside it everywhere, and read the same way.

## Readouts, as stated (no verdict)

1. **The hours repeat** when, on the body and the UTC clock, the pooled weekday-hours profile's Spearman correlation
   between the two halves is **at least 0.7**, and at least **13 of the 15** coins' own profiles correlate at **0.5 or
   more**. Otherwise **the hours do not repeat**. Both counts are reported for both clocks and both measures.
2. **The clock:** whichever of UTC and New York gives the higher pooled out-of-sample correlation is reported as **the
   clock the hours follow**; a difference under 0.05 is reported as **no clear clock**. Beside it, each clock's
   out-of-sample peak-to-trough ratio (busiest weekday hour over quietest).
3. **The size:** the pooled out-of-sample busiest and quietest weekday hours on each clock with their normalised swing,
   their ratio, and the weekend's mean swing over the weekdays' (from the days profile), in each half.
4. **The weekend repeats** when the pooled days profile has Saturday and Sunday as its two quietest days in both halves.

Readout 1 is judged on the weekday hours on purpose: the weekend is quiet in every coin, and a 168-slot correlation
would come out high from that alone and say nothing about hours.

## Power

In-sample, each weekday hour holds about 1,300 bars per coin (five years of weekdays); out-of-sample about 450. A
normalised swing's standard deviation is near 1, so a slot's mean is known to about ±0.03 in-sample and ±0.05
out-of-sample: profile differences of 0.1 are resolved in either half, coin by coin.

## Information only

Each coin's profiles in both halves and both clocks; the pooled 168-slot week; the correlation year by year (each year
against the in-sample profile); the range measure beside every readout; the raw size in bps of BTC's, ETH's and SOL's
median hour in each weekday slot, for the Market tab; and **the signed mean return by slot, labelled not a signal**:
direction by hour is a different question, and any rule built on it is a new pre-registration.

## What this cannot say

Which way the price moves in an hour; what trading costs in that hour (#68 is the cost); whether any rule that uses the
profile pays. Binance's bars are not Hyperliquid's: the shape should transfer, the levels may not.

## Robustness, information only

The six readouts of research/ROBUSTNESS_STANDARD.md are not applicable: there is no return series, no configuration
search and no signal to decay; the split by date is this test's own out-of-sample check.
