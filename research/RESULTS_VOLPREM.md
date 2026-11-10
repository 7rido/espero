# Results — the BTC volatility premium, sold every week with wings (#81)

**FAIL, on all six criteria.** Run once, 2026-11-10, by `research/volprem.py` at d97bd9a, against
`research/PREREGISTRATION_VOLPREM.md` (8d60f75, stamped). The full output is `research/volprem_run.txt`; the weeks,
priced and skipped, are in `research/volprem_weeks.csv`; the trades and delivery prices it read are in
`research/volprem_inputs.csv.gz`. One run; no rerun, no defect found against the contract.

## What was tested

Every Friday from 2020-01-03 to 2026-10-30 (357 of them; the last one's options expired 2026-11-06): sell BTC's
at-the-money call and put for the coming week, buy a call and a put about two weekly standard deviations out, price
all four at the 09:00 to 13:00 UTC trades of that Friday on Deribit, hold BTC against the position's delta each
morning, settle at Deribit's delivery price. 855,368 option trades were read. **350 weeks were priced and 7 skipped**
(5 for a missing delivery price, 2 for a wing with no traded strike); every return is a share of *M*, the capped loss.

## The criteria

| criterion | needed | result |
|---|---|---|
| 1. profit factor over the hedged weekly returns | 1.5 or more | **0.84** |
| 2. mean hedged weekly return, Newey-West t, BH q | mean > 0, t ≥ 3, q < 0.05 | **−1.35% of M**, t −1.36 (5 lags), p 0.175, q 0.44 over 43 tests |
| 3. mean hedged return over the 96 weeks since 2025-01-03 | above zero | **−0.76%** |
| 4. years with 20 or more priced weeks and a mean above zero | all but at most two of 7 | **1 of 7** (only 2026, 44 weeks, is above zero) |
| 5. half-gaps and hedge cost doubled | mean above zero | **−5.22%** |
| 6. unhedged mean, the form with a capped loss | above zero | **−3.48%** |

The verdict is FAIL: all six miss, with 350 priced weeks (the INCONCLUSIVE floor is 200).

## Information only

- **The premium the index showed is mostly not there at the traded strike.** The body's implied volatility (the
  strike nearest the money, one week out) averaged 53.8% against 50.7% realized at the daily prices: **3.1 points**,
  implied above realized in 234 of 350 weeks. The index screen's 10.7 points was a 30-day number. The gross of the
  structure agrees: the credit was +50.7% of *M* a week and the payout −50.3%, so the unhedged position kept 0.4%
  before costs, and the hedge added +3.4%.
- **Costs ate it, and then some.** A week cost 2.66% of *M* in half bid-ask gaps (28 bps of the index), 1.07% in
  Deribit's trading fees, 0.18% in settlement fees and 1.22% in the hedge: 5.1% in all, against a gross of 3.8%.
  The credit kept was −2.4% of itself, hedged; 0.0% unhedged.
- **The pricing is not the culprit.** Over the 344 weeks in which all four legs had a mark in the window, the model's
  credit averaged 0.996 of the credit from those legs' last `mark_price` × `index_price` (mean difference −$13, −1.9
  bps of the index), so the code's Black-76 prices and the forward-against-index bias the contract named are small.
- **By year** (hedged mean, unhedged mean, weeks): 2020 −0.54% / −10.29% / 46; 2021 −1.91% / −3.72% / 52;
  2022 −1.99% / +5.93% / 52; 2023 −1.72% / −11.27% / 52; 2024 −1.57% / −7.01% / 52; 2025 −2.10% / +1.06% / 52; 2026
  +0.82% / +0.81% / 44. Hedged: 180 of 350 weeks above zero; unhedged 206 of 350.
- **Tails.** Hedged worst week −103.4% of *M* (2023-01-13), worst 13 weeks −231.1% (from 2022-02-04). Unhedged worst
  week −100.7% (2023-10-13), worst 13 weeks −567.0% (from 2020-10-09). The two weeks of the March 2020 crash:
  2020-03-06 −25.6% hedged / −71.3% unhedged, 2020-03-13 −13.7% / +5.0%. In a share of the index the means were
  −0.077% hedged (t −0.76) and −0.066% unhedged (t −0.29), and the year signs are the same as above.
- **Since 2025** the hedged mean is −0.76% of *M* (t −0.42); 2026 alone is the one calendar year above zero, over
  44 weeks, +0.82% (not significant, and not a result of this test).
- **The hedge** traded $99,317 a week on average (about 1.9 times the index; median $87,356). The deflated Sharpe
  at N = 43 judged rows is 0.000 (weekly Sharpe −0.065 against an expected best of 0.189).
- **The unhedged loss against *M*.** The contract's *M* nets only the entry costs, so the settlement fees can carry a
  loss past it, which the code and its tests allow for: the worst unhedged week lost 1.007 of *M*, and 19 of 350 weeks
  lost more than *M*, by 0.2% to 0.7% of it, every one with a leg in the money and so a settlement fee.

## Contract notes

Where the pre-registration was loose, the narrowest reading was taken and written into `espero/volprem.py`'s
docstring before the run (d97bd9a): the last trade within a millisecond is the highest `trade_id`; "nearest" is in
dollars and a tie goes to the lower strike on the wings as well as the body; range bounds are inclusive; a trade with
a missing or non-positive `iv` prices nothing but can still be the last for *F* (201 such trades in priced weeks);
criterion 5 doubles the half-gaps and the hedge cost but not the trading or settlement fees. None of this was
chosen by looking at a result.

- **Deribit's fee page was read on 2026-11-10, as the contract required.** Options 3 bps of the underlying,
  capped at 12.5% of the premium; delivery 0.015% capped at 12.5% of the value (daily options exempt, Friday expiries
  not); the BTC perpetual's taker 3.5 bps. Every figure in the contract equals or exceeds it, so nothing higher was
  charged. It is today's schedule; the schedule in 2020 to 2024 may have been higher, which would only lower the means.
- **The first five weeks were skipped for rule 4's missing delivery price.** Deribit's published delivery prices have
  no Saturday to Thursday entries before February 2020, so the Fridays 2020-01-03 to 2020-01-31 could not be hedged
  at daily prices, and the first priced week is 2020-02-07. The rule said to skip such weeks and count them; it did.
- **The contract's trade count for 2025-06-13 (600) was low by two.** The fetcher gives 602 on 31 strikes, and the
  other five registered Fridays match exactly. A pager that advances by the last timestamp plus one drops exactly two
  of that day's trades of the expiry, the case the contract itself warns about; the de-duplicated count is the one
  used. It does not touch the rule.
- **One real trade was printed before the code was committed**, a 2020-01-03 trade, to see the field names; no price
  or volatility was used from it, and nothing was computed on real data until the rule and runner were committed.

## What this means

On Deribit's weekly options the premium exists on average, but the body's implied volatility was only 3 points above
what the week then realized, and a four-leg structure bought and sold at half-gaps plus the hedge's trading costs
about 5% of the capped loss a week. The 10.7 points of the index screen did not survive the trade: at the strike
actually sold, a week ahead, after the costs, the hedged rule lost money in six of seven calendar years (the
unhedged in four), and the hedge's gross edge (+3.4% of *M*) was smaller than the costs it brought. A steady 5% to 10%
a year with small drawdowns is not here, and there is no forward paper book. Closed under this number.
