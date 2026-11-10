# Results — the funding spread between trade.xyz's markets: short the payers, long the payees (#80)

**FAIL, on all five criteria.** Run once, 2026-11-10, by `research/fundspread.py` at 0cb0468, against
`research/PREREGISTRATION_FUNDSPREAD.md` (216f135, stamped). The full output is `research/fundspread_run.txt`; the
weeks are in `research/fundspread_weeks.csv`; the funding rows and prices it read are in
`research/fundspread_inputs.csv.gz`. The data download began after the pre-registration was stamped and before it
was committed, and nothing was computed from it until the rule and runner were committed.

## What was tested

Each Monday 00:00 UTC, the 28 registered markets ranked by their mean hourly funding over the week before; the
highest third short, the lowest third long, equal weight, dollar-neutral, held a week, with the funding actually
settled and 14 bps on the change in weights. 47 weeks from 2025-12-15 to 2026-11-02, with 11 to 28 markets eligible
a week (the universe grew as markets were listed). 198,857 hourly funding rows.

## The criteria

| criterion | needed | result |
|---|---|---|
| 1. profit factor over the weekly net returns | 1.5 or more | **0.509** |
| 2. mean weekly net, Newey-West t, BH q | mean > 0, t ≥ 3, q < 0.05 | **−0.668%**, t −1.58, q 0.32 |
| 3. beats random assignments (2,000 draws, gross) | under 5% at or above | **97.2%** at or above; the draws' median gross is −0.006% |
| 4. both halves above zero | yes | **−1.16%, then −0.16%** |
| 5. stays positive with any one market removed | yes | **negative every time**: the mean with one market removed ranges from −0.53% to −0.84% (lowest without MSFT) |

## Information only

- **The funding component did what it was designed to do, and the price component undid it.** On the mean week:
  funding **+0.198%**, price **−0.760%**, gross −0.562%, costs −0.107%. Funding was positive in 46 of 47 weeks;
  *post-hoc*, its Newey-West t is 6.8. The price component's t is −1.76: not significant either way.
- **Why it lost: the markets paying the most funding kept rising.** The short leg (highest funding) gained more
  than the long leg over the following week. A high funding rate here goes with a market that has been rising, so
  the spread looks more like momentum than the reversal the hypothesis named. The registration said a persistent
  premium was the risk; it was.
- **The reverse trade was not a discovery.** Computed afterwards and for information only: long the payers and
  short the payees, on the same weeks, earns +0.455% a week net of the same costs, with a Newey-West t of **1.07**,
  winning 26 of 47 weeks, and all of it in the first half (+0.92%, then −0.03%). No rule is registered from that.
- **The signal is large.** The short leg's mean funding exceeded the long leg's by about 29.5% a year, so the
  premiums are real; the stocks' own moves over a week (about 2% a week) are far bigger than the funding earned
  (about 0.2% a week).
- **Turnover** averaged 0.76 of capital a week: the ranking changes often. At the growth-mode fee (0.9 bps) plus 5
  bps the mean net is −0.61% (t −1.43).
- **Markets:** the legs were stable for some (SP500 and XYZ100 almost always long, being the lowest funding; SKHX
  and MU mostly short); no single market explains the result, since removing any one leaves the mean between
  −0.53% and −0.84%.

## What this means

On this exchange, the funding differences are real and reliably earned, but they are an order of magnitude smaller
than a week of stock moves, and a dollar-neutral long/short of perps does not hedge the stocks' own moves away: the
two legs are different stocks. Funding is only collectable cleanly where the price risk is hedged, which on
trade.xyz would mean holding the real share against the perp, as #12 did against spot for crypto. That would need a
brokerage account for US shares, which the holder's registered venues do not include. Closed under this number.
