# Results — buy the discount half of an hourly dealing range at its proximal line (#75)

**FAIL, on all five criteria, the wrong way.** Run once, 2026-11-10, by `research/dealrange.py` at be88f15, against
`research/PREREGISTRATION_DEALRANGE.md` (e34a028, stamped). The full output is `research/dealrange_run.txt`; every
trade is in `research/dealrange_trades.csv`; the bars it read are kept in `research/dealrange_bars.csv.gz`.

This rule is my reconstruction of a friend's system from a screenshot. The verdict speaks for this rule, not for
the friend's, whose code was not available.

## What was tested

37 stocks and ETFs (#73's regular-session list), each listed ticker's regular-session hourly bars from Yahoo, the
last 730 days: entries from 2023-12-20 to 2026-11-09. 4,827 orders were armed and 1,287 filled. Costs were 14 bps a
fill.

A first attempt the same day stopped while loading data, before any rule ran: Yahoo refused NBIS's `range=730d`
request. It was fixed in be88f15 (hourly bars are now asked for by explicit dates) and the run repeated in full.

## The criteria

| criterion | needed | result |
|---|---|---|
| 1. profit factor | 1.5 or more | **0.44** |
| 2. mean R, t clustered by entry day, BH q | mean > 0, t ≥ 3, q < 0.05 | **−0.583R**, t −9.14 over 489 days, p 6.4e-20 (the wrong way) |
| 3. random entries (2,000 draws, seed 0) | under 5% of draws at or above the rule | **100%**: the draws' median is −0.256R; the rule is 0.327R worse |
| 4. both halves above zero | yes | **−0.501R, then −0.666R** |
| 5. more than half the markets above zero | yes | **4 of 37** |

## Information only

- **Outcomes:** 847 stops, 255 at the second target, 185 at breakeven; a win rate of 33.5%; −750.5R in total.
- **Costs are not the reason.** With no costs the mean is −0.373R (profit factor 0.585); with the growth-mode fee
  and 5 bps of slippage, −0.462R. The median stop is 176 bps of price, so a round trip at 14 bps a fill costs
  0.16R.
- **The registered fill rule on gaps.** 115 trades had a fill bar opening at or below the stop. The registration
  filled them at the line and exited them at the open, a loss of 3.18R on average and 366R in total. A real
  resting order would have filled at the lower open. The other 1,172 trades still average −0.328R, with a profit
  factor of 0.605.
- **Same day against overnight:** the 596 trades closed the day they opened averaged −1.353R; the 691 held
  overnight or longer averaged +0.081R.
- **Random entries also lose here** (median −0.256R): the bracket itself, with its costs on these bars, is
  negative before any entry rule. Buying the pullback into the proximal line did worse than buying at random.
- Mean bars held: 8.7. Deflated Sharpe on the daily R series: 0.000.
- **Markets above zero:** AAPL (+0.11R), PLTR (+0.06), SKHY (+0.34, 6 trades) and SNDK (+0.003).

## What this means

As reconstructed, the rule does not work on these markets, and it is closed under this number. Whether the
friend's own version differs enough to matter cannot be known without its code. Any new version takes a new
number and a new pre-registration, and this result counts in its family.
