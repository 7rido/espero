# Pre-registration — #78's trend rule on names chosen blind: the Dow Jones 30 of November 2021 (#79)

Committed **before** any signal is computed on these names. This document is the contract; nothing below is
changed afterwards. A later idea takes a new number.

## Why this test

#78 (research/RESULTS_TRENDSTOCK.md) cleared the profit-factor screen but not the statistical bar, and random
entries held as long earned almost the same: the 37 names were chosen in November 2026 because they trade most on
trade.xyz now, and most of them rose. The fair check, #78 proposed, is the same rule on names chosen without
knowing how they did. The account holder asked for it on 2026-11-10.

## The names, and why they are blind

The 30 components of the Dow Jones Industrial Average as I recall them on 8 November 2021, listed here before any
of their prices is read: AAPL, AMGN, AXP, BA, CAT, CRM, CSCO, CVX, DIS, DOW, GS, HD, HON, IBM, INTC, JNJ, JPM, KO,
MCD, MMM, MRK, MSFT, NKE, PG, TRV, UNH, V, VZ, WBA, WMT. A committee chose them, not their returns, and the list
dates from before the first bar of the test window, so it carries no knowledge of what came after. The list is
from memory and may be a name or two off; the run prints any symbol Yahoo does not know, and none is added or
swapped. Survivors only in the sense that every one of the 30 still trades.

## What was seen before this

#78's results, including its per-market lines for AAPL, MSFT, IBM and INTC, which are also in this list. One daily
series, JPM's, was fetched on 2026-11-10 to check the data endpoint; no rule was applied to it. No signal, entry,
exit or trade of this rule has been computed on any of the 30.

## Data

- **Bars:** each name's daily bars through `espero.data.yahoo_daily(symbol, "5y")` on the day of the run (opens
  and closes, split-adjusted, not adjusted for dividends), which start on 2021-11-10. A bar before the list's date
  is not used for any signal beyond the 100-bar window needed to fill.
- **Kept:** the bars read, committed with the result as `research/trendblind_bars.csv.gz`.

## Rule

#78's, unchanged, by the same functions (`espero.trendstock.trades`, `net`, `random_means` and the rest, at their
registered numbers): buy at the next open after a close above the highest close of the 100 bars before; sell at the
next open after a close below the lowest of the 50 before; one position, long only; 14 bps a fill; funding at 10% a
year for the calendar days held; a position open at the end closed at the last close. The costs are those of a
perp on trade.xyz, kept for comparability with #78 although most of these names are not listed there.

## Criteria, all required, as #78's

1. A profit factor of 1.5 or more over every trade, net.
2. The mean net trade above zero with t ≥ 3 clustered by entry month (Student's t with months minus one degrees of
   freedom, the normal above 100), and Benjamini-Hochberg q < 0.05 over every judged test in
   `research/trials.csv` with #79 included.
3. Fewer than 5% of 2,000 random-entry draws (seed 0), each replacing every real trade by one from a random bar on
   the same market held as long, at or above the rule's mean net trade.
4. The mean net trade above zero in each half of the trades in entry-date order.
5. More than half the markets with 5 trades or more above zero.

## Power

About 30 names with 100 bars lost to the window give entries over 4.4 years: perhaps 100 to 150 trades. Under 100
trades the verdict is INCONCLUSIVE. These are large, slow stocks, so a typical trade moves less than #78's: its
standard deviation may be near 10%, and t ≥ 3 would then need a mean near 3% a trade at 100 trades.

## Outcomes

**PASS:** every criterion holds on names chosen blind: the breakout has timing skill beyond holding. What follows is
a paper forward test of the rule on trade.xyz's liquid names, its own registration, never money directly.
**FAIL:** any criterion misses; the rule is closed on this list and no other list is tried under this number.
**INCONCLUSIVE:** fewer than 100 trades.

## Information only

The win rate and average win and loss; the median trade; the mean with the best trade removed; no costs and
growth-mode costs; per name trades and mean; buy and hold of the same names from the first possible entry against
the rule's compounded trades.

## Robustness, information only

Not applicable, as #78.
