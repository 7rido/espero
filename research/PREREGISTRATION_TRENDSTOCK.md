# Pre-registration — a daily breakout trend rule on the stock perps (#78)

Committed **before** any signal is computed. This document is the contract; nothing below is changed afterwards. A
later idea takes a new number.

## Why this test

#76 and #77 (research/RESULTS_NIGHTSHIFT.md, RESULTS_NIGHTWEEK.md) lost to costs: trading every night, or every
week, pays 28 bps of fills for a few bps of edge. A trend rule trades a few times a year, so its costs per trade
are small against the moves it chases. This is the account holder's choice, after #75 to #77, on 2026-11-10.

## Hypothesis

Stocks that make a new high keep trending for weeks (the time-series momentum literature: Moskowitz, Ooi and
Pedersen 2012, on futures; Hurst, Ooi and Pedersen 2017, over a century), because information spreads and
investors under-react. A long-only breakout buys the new high and sells when the trend breaks.

## What was seen before this

Each mapped ticker's five-year total return, which shows how many of these names rose (30 of the 33 with five
years); #75 to #77's results; the counts of daily bars. No breakout, entry, exit or trade of this rule has been
computed on any of these markets.

## Data

- **Markets:** the 37 stocks and ETFs of `espero.tradfi.allowed()` (#73's list), no more and no fewer.
- **Bars:** each ticker's daily bars through `espero.tradfi.daily(market, "5y")` on the day of the run: official
  opens and closes, split-adjusted, not adjusted for dividends. A market listed less than five years ago is used
  from its first bar.
- **Kept:** the bars read, committed with the result as `research/trendstock_bars.csv.gz`.

## Rule (`espero/trendstock.py`)

All on one market's daily bars, using only closes already known.

1. **Entry signal:** a bar's close is above the highest close of the 100 bars before it.
2. **Exit signal:** a bar's close is below the lowest close of the 50 bars before it.
3. **Fills:** a signal at a bar's close fills at the **next bar's open**. One position per market, long only; an
   entry signal while held is ignored, and so is an exit signal while flat.
4. **A position open at the end of the data** is closed at the last bar's close and counts as a trade.
5. **Costs:** 14 bps a fill, two fills a trade (trade.xyz's taker fee out of growth mode plus 5 bps). **Funding:**
   10% a year for the calendar days from the entry open to the exit open.
6. **A trade's return:** exit price over entry price, minus the costs and the funding.

## Criteria, all required

1. **The holder's screen:** a profit factor of 1.5 or more over every trade, net.
2. **Statistical bar (research/FDR_STANDARD.md):** the mean net trade return above zero with a t ≥ 3, the
   standard error clustered by the trade's entry month, its p from Student's t with months minus one degrees of
   freedom (the normal above 100 months), and Benjamini-Hochberg q < 0.05 over every judged test in
   `research/trials.csv` with #78 included, a missing p counted as 1.
3. **Beats random entries held as long:** of 2,000 draws (seed 0), each replacing every real trade by one on the
   same market from a random bar, held the same number of bars, with the same costs and funding, fewer than 5%
   have a mean net return at or above the rule's. This is what removes the lift from holding names that rose.
4. **Not one stretch:** the mean net trade return above zero in each half of the trades, in entry-date order, the
   earlier half taking the odd one.
5. **Not one coin:** among markets with 5 trades or more, more than half have a mean net trade return above zero.

## Power

Unknown before the run: the trade count is a result. A breakout rule on 37 names over about 4.5 years might give
200 to 400 trades; a trade's net return has a standard deviation near 15%, so t ≥ 3 needs a mean near 3% a trade
at 200 trades. Under 100 trades the verdict is INCONCLUSIVE.

## Outcomes

**PASS:** every criterion holds; what follows is a paper forward test on the perps, its own registration.
**FAIL:** any criterion misses; the rule is closed under this number, and no other window (20, 50, 200) is tried
under it.
**INCONCLUSIVE:** fewer than 100 trades.

## Information only

The win rate and the average win and loss; the mean days held; the result with no costs and with the growth-mode
fee (0.9 bps plus 5); each market's trades and mean; the portfolio's compounded return against buying and holding
the same markets equal-weight over the same dates; the share of days a market was held.

## Robustness, information only

Not applicable: PBO (one configuration), purged k-fold (nothing fitted); deflated Sharpe is not computed on a
trade-level series.

## The selection, said plainly

These names were chosen in November 2026 because they trade most on trade.xyz now, and most of them rose over
these years. A long-only rule on them gains from that before it gains from any skill; criterion 3 measures
against it, and nothing can remove it entirely.
