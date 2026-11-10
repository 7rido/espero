# Pre-registration — the funding spread between trade.xyz's markets: short the payers, long the payees (#80)

Committed **before** any funding history beyond one test page is read, and before any return is computed. This
document is the contract; nothing below is changed afterwards. A later idea takes a new number.

## Why this test

#75 to #79 were price patterns on stocks, and none worked. This one is a structural feature of the exchange
itself: trade.xyz's perps pay funding every hour, and the rate differs widely between markets. On 2026-11-10 SKHX
paid 138% a year, NATGAS 422%, and IBM paid its longs 122%. The account holder asked on 2026-11-10 for a different
kind of idea.

## Hypothesis

A perp's funding rate is its premium over the oracle price, smoothed. A market that has paid longs a lot over the
last week is one whose perp traded rich to its reference, and a rich perp tends to come back to it while its
shorts are paid in the meantime. Being short the highest-funding third and long the lowest, in equal weight, earns
the funding difference and the convergence, and is dollar-neutral, so it does not depend on the stocks rising.
The mechanism is the funding formula itself, not a story about investors; the risk is that premiums persist or
that the stocks move against one leg.

## What was seen before this

The markets' 24-hour volumes, open interest and funding rates on 2026-11-10 00:30 UTC (SKHX +138%, NATGAS +422%,
SMSN +63%, UNITREE +110%, IBM −122%, CL −34%, BRENTOIL −53% a year, most at the 5.5% baseline); each market's first
and last daily candle and volume; and the first 500 hourly funding rows of xyz:NVDA (all at 0.0000125, the
baseline). No funding history beyond that page has been read, and no weekly return, price change or portfolio has
been computed on any of these markets.

## Data

- **Markets (28):** those with a 30-day median daily dollar volume of at least $10M and at least 150 days of daily
  candles on 2026-11-10: AAPL, AMD, AMZN, BRENTOIL, CBRS, CL, CRCL, CRWV, DRAM, EWY, GOLD, GOOGL, INTC, META,
  MRVL, MSFT, MSTR, MU, NBIS, NVDA, SILVER, SKHX, SMSN, SNDK, SP500, SPCX, TSLA, XYZ100. Chosen by liquidity and
  age only; no market is added or removed. The coins are named "xyz:<NAME>".
- **Funding:** Hyperliquid's `fundingHistory`, mainnet, hourly rows `(time, fundingRate)` from each market's
  listing to the run. The rate is per hour, as a fraction of notional; positive means longs pay shorts.
- **Prices:** `candleSnapshot` daily candles, mainnet; "the price at t" is the open of the candle starting at t.
- **Kept:** the funding rows and candles used, committed with the result as `research/fundspread_inputs.csv.gz`
  (the venue's history cannot be relied on to stay).
- **Weeks:** Monday 00:00 UTC to the next Monday 00:00 UTC, complete weeks up to the run only.

## Rule (`espero/fundspread.py`)

At each Monday 00:00 UTC *t*:

1. **Eligible markets:** a daily candle at *t* and at *t* + 7 days, and at least 144 of the 168 hourly funding
   rows in [*t* − 7 days, *t*). At least 9 are needed, else no position that week.
2. **Signal:** a market's mean hourly funding rate over [*t* − 7 days, *t*): known before *t*.
3. **Legs:** with *n* eligible markets and *k* = floor(*n*/3), **short the *k* highest** signals and **long the *k*
   lowest**, equal weight within a leg, each leg half the capital (gross 1, dollar-neutral).
4. **Fills** at the open of the candle at *t*; the exit at the open of the candle at *t* + 7 days.
5. **The week's gross return** on capital: ½·(mean price return of the long leg − mean price return of the short
   leg) + ½·(mean funding paid by the short leg's markets − mean funding paid by the long leg's), the funding
   being the sum of the hourly rates settled in [*t*, *t* + 7 days) (a long pays it, a short receives it).
6. **Costs:** 14 bps (trade.xyz's taker fee out of growth mode plus 5 bps) per unit of capital traded, where the
   traded amount is the sum over markets of the change in weight from the previous week's target (the first week
   trades the whole portfolio). A market that stays in its leg costs nothing. The last week's exit is not charged.
7. **Net return** = gross − costs.

## Criteria, all required

1. **The holder's screen:** a profit factor of 1.5 or more over the weekly net returns (the sum of the positive
   weeks over the sum of the negative ones).
2. **Statistical bar (research/FDR_STANDARD.md):** the mean weekly net return above zero with a Newey-West t ≥ 3
   (`espero.cascade.nw_t`, lags by `espero.volf.nw_lags`), p two-sided from the normal distribution, and
   Benjamini-Hochberg q < 0.05 over every judged test in `research/trials.csv` with #80 included.
3. **The funding rank carries information:** of 2,000 draws (seed 0) that each week assign the eligible markets to
   the same-size legs at random, fewer than 5% have a mean weekly **gross** return at or above the rule's. (Gross,
   because a random assignment trades far more than a persistent ranking, and costs would hand the rule an edge it
   did not earn from information.)
4. **Not one stretch:** the mean weekly net return above zero in each half of the weeks, the earlier half taking
   the odd one.
5. **Not one market:** the mean weekly net return stays above zero when each market in turn is removed from the
   universe and the whole rule re-run.

## Power

About 45 to 50 weeks, with the universe growing from about 10 to 28 markets. A dollar-neutral week of this kind
moves with a standard deviation near 2%, so the standard error of the mean is near 0.3%, and t ≥ 3 needs a net
mean near 0.9% a week, about 47% a year. Funding alone, between the top and bottom third, may differ by 50% to
100% a year (about 1% to 2% a week) on a gross of 1, halved by the leg weights: so the funding component is of the
size the bar needs, and the price component can decide it either way. Under 40 weeks the verdict is INCONCLUSIVE.

## Outcomes

**PASS:** every criterion holds; what follows is a paper forward test of the spread on the perps, its own
registration, never money directly. **FAIL:** any criterion misses; the rule is closed under this number.
**INCONCLUSIVE:** fewer than 40 weeks.

## Information only

The funding and price components of the mean week; the long and short legs separately; the mean turnover; the
signal's spread (top third minus bottom third) as an annual rate; the result with the growth-mode fee (0.9 bps)
plus 5 bps; each market's mean contribution; weeks with the funding component alone positive.

## Robustness, information only

Not applicable: PBO (one configuration), purged k-fold (nothing fitted).

## What cannot be tested here

Monday 00:00 UTC is Sunday 19:00 Eastern, when these markets trade on trade.xyz's own pricing and at about 13% of
weekday volume (#73). The 14 bps may understate the cost of trading the whole book at that hour; #74 will say. The
test also covers one year, which began when these markets were listed.
