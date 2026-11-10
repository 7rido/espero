# Pre-registration — the slow night shift: Monday's close to Friday's open, once a week (#77)

Committed **before** any week of these markets is computed. This document is the contract; nothing below is
changed afterwards. A later idea takes a new number.

## Why this test

#76 (research/RESULTS_NIGHTSHIFT.md) found that these 37 stocks and ETFs earned more overnight than by day: +10.32
bps a night against +5.81 a day, gross. But two fills every night cost three times what a night earned. Asked on
2026-11-10 for a slower version, this one holds through four nights and the three days between them, Monday's
close to Friday's open, for one round trip a week instead of four. It carries three days to save three round
trips.

## What was seen before this

Everything #76 printed, including its gross night and day means, its per-market results and its years. Its numbers
let anyone estimate this rule's gross mean: four nights and three days come to roughly 58 bps a week. So this is
not a blind test of the effect; it tests whether that gross, after one round trip and four days of funding, is
above zero and above the market's return over the same hours, by the bars below.

## Data

- **Markets:** the 37 of `espero.tradfi.allowed()`, as #76.
- **Bars:** each ticker's daily bars through `espero.tradfi.daily(market, "5y")` on the day of the run; the market
  benchmark is SPY's daily bars through `espero.data.yahoo_daily("SPY", "5y")`.
- **Kept:** the bars read, committed with the result as `research/nightweek_bars.csv.gz`.

## Rule (`espero/nightweek.py`)

- **Each calendar week** (Monday to Sunday, Eastern dates) with at least three trading days on a market's bars:
  buy at the official close of the week's first trading day, sell at the official open of its last trading day.
  A normal week holds Monday's close to Friday's open; a week opening on a Tuesday holiday starts at Tuesday's
  close.
- **Every market the same notional;** the portfolio's week is the average of the markets' net returns that week.
- **Costs:** 14 bps a fill, two fills a week, as #76.
- **Funding:** 10% a year for the hours held, from 16:00 Eastern on the entry day to 09:30 on the exit day
  (89.5 hours in a normal week).
- **The market's week:** SPY's gross return over the same entry close and exit open, with no costs or funding.

## Criteria, all required

1. **The holder's screen:** a profit factor of 1.5 or more over every market-week, net.
2. **Statistical bar (research/FDR_STANDARD.md):** the portfolio's mean net week above zero with a Newey-West t
   ≥ 3 (`espero.cascade.nw_t`, lags by `espero.volf.nw_lags`), p two-sided from the normal distribution, and
   Benjamini-Hochberg q < 0.05 over every judged test in `research/trials.csv` with #77 included.
3. **Beats the market:** the portfolio's mean net week above SPY's mean gross week over the same hours.
4. **Not one stretch:** the mean net week above zero in each half of the weeks, the earlier half taking the odd
   one.
5. **Not one coin:** among markets with 100 weeks or more, more than half have a mean net week above zero.

## Power

About 255 weeks. An equal-weight week of these names moves with a standard deviation near 3%, so the standard
error of the mean is about 19 bps, and t ≥ 3 needs a net mean near 57 bps a week: the gross would need about 95
bps against the roughly 58 that #76's means imply. A fail on the t is the expected outcome; the profit factor of
1.5 on weekly returns of stocks is also demanding. The test is run because the holder chose it, and its readouts
show where it stands.

## Outcomes

**PASS:** every criterion holds; what follows is a paper forward test on the perps, its own registration.
**FAIL:** any criterion misses; the rule is closed under this number.
**INCONCLUSIVE:** fewer than 100 weeks.

## Information only

The gross mean week; the net mean with the growth-mode fee (0.9 bps) plus 5 bps; buy-and-hold of the same
markets over the same calendar weeks, close to close; SPY's mean week; per market the mean net week; by calendar
year.

## Robustness, information only

Deflated Sharpe on the weekly net series against the ledger's Sharpes scaled to a week; PBO not applicable (one
configuration).

## The selection, said plainly

These 37 names were chosen in November 2026 because they trade most on trade.xyz now, and 30 of the 33 with five
years of history rose. Any rule that holds them long will look better over these years than it would have
looked choosing names in 2021. Criterion 3 measures against the market, not against this bias, which no test on
this list can remove.
