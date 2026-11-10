# Pre-registration — the night shift: hold the stock perps from the close to the next open (#76)

Committed **before** any overnight or intraday return is computed for these markets. This document is the
contract; nothing below is changed afterwards. A later idea takes a new number.

## Hypothesis

Published studies of US stocks (Cooper, Cliff and Gulen 2008; Kelly and Clark 2011; Lou, Polk and Skouras 2019)
find that most of their long-run return came between the close and the next open, and little or none during
the trading day. A perp that trades through the night lets a small account hold only that stretch: buy at the
close, sell at the next open. The mechanism offered in that literature is a tug of war between overnight
buyers (retail orders and news) and intraday sellers (institutions trading against them); it is a regularity,
not a forced flow, and it has been public for years, so the prior that it survives today's costs is weak.

## What was seen before this

#73's result: the perp at 16:00 Eastern sits a median 5.4 bps from the official close and at 09:30 a median 7.4
bps from the official open, and the overnight return of perp and ticker differs by a median 8.0 bps across 42
stocks and ETFs over 2026-09-21 to 2026-11-07. Each ticker's five-year total return. #75's failure, which was
intraday. No overnight or intraday return of these markets has been computed by me, and none is computed before
this commit.

## Data

- **Markets:** the 37 stocks and ETFs of `espero.tradfi.allowed()` (#73's list at d3a4d61), no more and no fewer.
- **Bars:** each ticker's daily bars from Yahoo through `espero.tradfi.daily(market, "5y")` on the day of the
  run: the official open and close, adjusted for splits, not for dividends (a perp pays none, and its price falls
  with the stock's on the day one is paid). A market listed less than five years ago is used from its listing.
- **Kept:** the bars read are committed with the result as `research/nightshift_bars.csv.gz`.
- **Excluded before looking:** the first day of each ticker's history; nothing else.

## Rule (`espero/nightshift.py`)

- **Each night, each market** with a close on day *d* and an open on its next trading day: buy at the official
  close of *d*, sell at the next official open. Every market the same notional. Long only, every night, no
  filter.
- **The portfolio's night** is the average of the markets' net returns that night. The series is one value per
  night, in date order.
- **Costs:** 14 bps a fill, two fills a night: trade.xyz's taker fee out of growth mode (9 bps; growth mode can
  be withdrawn by the deployer) plus 5 bps for slippage at the bell. Both trades are at the bell, so a market
  order is the honest assumption.
- **Funding:** a long pays 10% a year, pro rata for the hours held: from 16:00 Eastern on *d* to 09:30 on the
  next trading day (17.5 hours on a weeknight, 65.5 over a weekend, longer over a holiday). trade.xyz's
  standing rate for most of these markets read 5.5% a year on 2026-11-10; 10% allows for the many hours when a
  market's crowd pays more.
- **The day, for comparison:** the same markets held from the official open to the official close of the same
  day, with the same costs and funding for 6.5 hours.

## Criteria, all required

1. **The holder's screen:** a profit factor of 1.5 or more over every market-night, net (the sum of the
   positive net returns over the sum of the negative ones). This is the recipe's bar; for nightly returns it is
   demanding, and it is kept because the recipe set it.
2. **Statistical bar (research/FDR_STANDARD.md):** the portfolio's mean net night above zero with a Newey-West t
   ≥ 3 (`espero.cascade.nw_t`, lags by `espero.volf.nw_lags`), p two-sided from the normal distribution, and
   Benjamini-Hochberg q < 0.05 over every judged test in `research/trials.csv` with #76 included, a missing p
   counted as 1.
3. **The night beats the day:** the portfolio's mean net night above its mean net day.
4. **Not one stretch:** the mean net night above zero in each half of the nights, the earlier half taking the odd
   one.
5. **Not one coin:** among markets with 250 nights or more, more than half have a mean net night above zero.

## Power

About 1,250 nights over five years. An equal-weight night of these names moves with a standard deviation of
roughly 1%, so the standard error of the mean is near 2.8 bps and t ≥ 3 needs a net mean of about 8.5 bps a
night: with 28 bps of fills and about 2.5 bps of funding a night, the gross overnight return would need to
average about 39 bps a night. The published overnight premium for US stocks is a few bps a night, so a fail is
the expected outcome; the test is run because the holder chose it, and its readouts say how far the costs are.

## Outcomes

**PASS:** every criterion holds; what follows is a paper forward test on the perps, its own registration.
**FAIL:** any criterion misses; the rule is closed under this number.
**INCONCLUSIVE:** fewer than 500 nights.

## Information only

The gross overnight and intraday means; the net mean with the growth-mode fee (0.9 bps) plus 5 bps, and with no
costs; funding at 5.5% a year; per market the mean gross and net night; weekend nights against weeknights; by
calendar year; the share of buy-and-hold's return that came overnight.

## Robustness, information only

Deflated Sharpe on the nightly net series against the ledger's Sharpes scaled to a day, as #75 did; PBO not
applicable (one configuration); capacity not computed.
