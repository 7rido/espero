# Results — #78's trend rule on names chosen blind: the Dow Jones 30 of November 2021 (#79)

**FAIL, on all five criteria.** Run once, 2026-11-10, by `research/trendblind.py` at a7f23a4, against
`research/PREREGISTRATION_TRENDBLIND.md` (be2799c, stamped). The full output is `research/trendblind_run.txt`;
every trade is in `research/trendblind_trades.csv`; the bars read are in `research/trendblind_bars.csv.gz`.

## What was tested

#78's rule, unchanged: buy at the next open after a close above the highest close of the 100 bars before, sell
at the next open after a close below the lowest of the 50 before, 14 bps a fill and funding at 10% a year. On 29
of the Dow's 30 components as of November 2021, five years of daily bars from 2021-11-10: 180 trades, entries from
2022-04 to 2026-11, 13 still open at the end.

**A correction to the contract.** It said every one of the 30 still trades. Walgreens (WBA) does not: Yahoo does
not serve it any more, since it was taken private in 2025. It is left out, as registered, and not replaced. The
names that remain are the survivors of the list, a small bias in the rule's favour.

## The criteria

| criterion | needed | result |
|---|---|---|
| 1. profit factor over every trade, net | 1.5 or more | **0.812** |
| 2. mean net trade, t clustered by entry month, BH q | mean > 0, t ≥ 3, q < 0.05 | **−1.12%**, t −0.73 over 51 months, q 0.84 |
| 3. beats random entries held as long | under 5% of 2,000 draws at or above | **97.4%** at or above; the draws' median is +1.06% |
| 4. both halves above zero | yes | **−2.85%, then +0.60%** |
| 5. more than half the markets above zero | yes | **9 of 25** |

## Information only

- **Before costs there is almost nothing.** With no costs and no funding the mean is +2.26% (profit factor 1.51).
  The registered 28 bps of fills and about 3% of funding on a 113-day hold take it to −1.12%; at the growth-mode
  fee it is −0.96%.
- **Win rate 27.8%.** The average win is +17.5% and the average loss −8.3%, the usual shape of a trend rule: many
  small losses, few large wins. Here the wins are not large enough.
- **The rule compounded −12.8% per name** at the median, while buying and holding gained +53.1%. It was invested
  42% of the time.
- Random entries held as long earned +1.06% a trade; the rule's −1.12% is worse than 97% of them.

## What this means

On names chosen without knowing how they did, the breakout has no timing skill. Together with #78: the +33.6% a
trade there came from the list (names chosen in 2026, most of which rose, and a handful of huge winners), not from
the rule. The trend rule is closed on both lists. Nothing here says a different trend rule (other windows, shorts,
a market filter) would not work; each of those would be its own number.
