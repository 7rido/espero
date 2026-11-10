# Results — a daily breakout trend rule on the stock perps (#78)

**FAIL, on two of five criteria: the statistical bar and the random-entry test.** Run once, 2026-11-10, by
`research/trendstock.py` at 1adf7c9, against `research/PREREGISTRATION_TRENDSTOCK.md` (bda3b23, stamped). The full
output is `research/trendstock_run.txt`; every trade is in `research/trendstock_trades.csv`; the bars read are in
`research/trendstock_bars.csv.gz`.

## What was tested

The 37 stocks and ETFs of #73's list on their listed tickers' daily bars: buy at the next open after a close above
the highest close of the 100 bars before, sell at the next open after a close below the lowest of the 50 before.
164 trades with entries from 2022-04 to 2026-10, four still open at the end. 14 bps a fill and funding at 10% a
year for the calendar days held.

## The criteria

| criterion | needed | result |
|---|---|---|
| 1. profit factor over every trade, net | 1.5 or more | **4.77** (holds) |
| 2. mean net trade, t clustered by entry month, BH q | mean > 0, t ≥ 3, q < 0.05 | **+33.6%**, t **2.12** over 46 months, p 0.040, q **0.113** (misses) |
| 3. beats random entries held as long | under 5% of 2,000 draws at or above | **33.1%** at or above; the draws' median is +29.2% (misses) |
| 4. both halves above zero | yes | **+12.0%, then +55.2%** (holds) |
| 5. more than half the markets above zero | yes | **22 of 26** (holds) |

## Information only

- **Costs are not the problem here.** With no costs and no funding the mean is +37.6% (profit factor 5.93); at the
  growth-mode fee, +33.8%. The registered 10% funding is the larger cost, about 5% of a 135-day hold.
- **A few trades carry it. These readouts were computed after the verdict.** The median trade is **−3.7%**; 72 of
  164 trades won. The average win is +96.9% and the average loss −15.9%. Twelve trades gained over 100%; the best
  are SNDK +2,307% (listed in February 2025), LITE +659%, KORU +330%, MRNA +316% and RKLB +315%. Without SNDK the
  mean is +19.7% over 163 trades (profit factor 3.19); trimming the top and bottom 5% leaves +8.9%.
- **By entry year:** 2022 −5% (10 trades), 2023 +11%, 2024 +12%, 2025 +112% (SNDK), 2026 +9%.
- **Against buying and holding:** per market from the first possible entry, buy and hold has a median +102% and the
  rule's trades compounded +27%. The rule held a market 44% of the time. It gives up most of the return in
  exchange for avoiding drawdowns, which this measurement does not value.
- The random draws also profit (+29%), because random entries held 135 days on names that mostly rose also rise.
  That is the selection effect the registration named: this list was chosen in 2026, and most of it went up.

## What this means

This is the first rule that clears the holder's profit-factor screen, but not the statistical bar, and not the test
that separates timing from drift. The breakout adds about 4 points a trade over random entries held as long (+33.6
against +29.2), and a third of random draws do better. On these names the whole return comes from holding them
through a rise, which a trend rule does 44% of the time. Closed under this number: the 100/50 windows are the only
ones registered, and no variant is tried under it.

A fair next test would be on names chosen without knowing how they did, such as a fixed index list from 2021; that
is a different rule and list, so it takes a new number.
