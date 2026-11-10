# Pre-registration — the BTC volatility premium, sold every week with wings (#81)

Committed **before** any option price is turned into a profit or a loss. This document is the contract; the result
document will say whether it was met, and nothing below is changed afterwards. A later idea takes a new number.

## Why this test

The account holder said on 2026-11-10 that a steady 5% to 10% a year with small drawdowns counts as working. A screen
the same day (research/IDEAS_NOVEL.md, idea 23) read Deribit's 30-day implied volatility index against the volatility
that followed: implied was higher by 10.7 points on average over 68 windows since March 2021 (t 5.00), in every
calendar year, but by only 4.1 points since 2025 (t 1.44). That screen used an index, not a price anyone could trade
at. This test asks the same question of real option trades, after costs.

## Hypothesis

People who hold BTC, or borrow against it, buy options to cap what a bad week can cost them, and pay more than the
week then delivers. Whoever sells that protection collects the difference. Selling an at-the-money call and put for
the coming week, buying a far call and a far put so that a crash or a squeeze cannot cost more than a known amount,
and holding BTC against the position's lean each day, earns that difference after costs.

## What was seen before this

- The index screen above (BTC and ETH), by year and since 2025.
- For three Fridays (2021-06-11, 2023-06-09, 2025-06-13): how many option trades Deribit's history holds between
  09:00 and 13:00 UTC, how many of them on the next Friday's expiry (297, 508, 600) and on how many strikes (21, 16,
  31), the index and the lowest and highest strike. The same count for three Fridays of 2020 (01-03, 03-06, 09-11):
  262, 168 and 120 trades on 13, 17 and 19 strikes, every one carrying `iv`, `index_price` and `mark_price`. No
  trade's price or implied volatility was read.
- The field names of one 2022 option's trades.
- From this repo's own recording (`data/deribit`), Friday 2026-11-06, 09:00 to 13:00 UTC, the options expiring
  2026-11-13: half the bid-ask gap by distance from the money (5.0 bps of the index near the money, median and 90th
  percentile, 3.0% of the option's price; 1.0 bps median and 1.5 at the 90th percentile about two weekly standard
  deviations out, 9.6% of the price), the marks, and from them a rough credit for one structure that day. Those
  figures set the costs below.
- Deribit's API on 2026-11-10: `taker_commission` 0.0003 on a BTC option and 0.00035 on the BTC perpetual.
- Deribit's dated-future basis and delivery-price count on 2026-11-10.

No option trade before 2026-11-06 has been priced, and no profit or loss of any option position has been computed.

## Data

- **Trades:** `https://history.deribit.com/api/v2/public/get_last_trades_by_currency_and_time`, currency BTC, kind
  option: every trade with `timestamp`, `instrument_name`, `iv` (percent) and `index_price`. Public, no key.
- **Settlement:** `https://www.deribit.com/api/v2/public/get_delivery_prices`, index `btc_usd`: the 08:00 UTC
  delivery price of every day.
- **Weeks:** every Friday from 2020-01-03 to the last Friday whose options had settled when the run starts. March
  2020 is inside on purpose.
- **Kept:** the trades used and the delivery prices, committed with the result as `research/volprem_inputs.csv.gz`.
- Only BTC. ETH failed the index screen (t 2.70, negative in 2025) and is not tested.

## Rule (`espero/volprem.py`)

The rule has no signal: it sells every week. The window's trades choose the strikes and price them; nothing in the
window decides whether to trade.

For each Friday, with the **window** 09:00:00 ≤ t < 13:00:00 UTC, the **entry** at 13:00 UTC, the **expiry** the next
Friday at 08:00 UTC, and τ = 163 hours as a fraction of a 365-day year:

1. **Inputs.** The window's trades in options of that expiry. *F* is the `index_price` of the last of them. A strike
   has **traded** if it has at least one such trade, call or put; its implied volatility is the median `iv` of its
   trades in the window, calls and puts together, as a fraction.
2. **The body.** *K0* is the traded strike nearest *F* (the lower on a tie). σ0 is its implied volatility and
   σw = σ0·√τ.
3. **The wings.** The call wing *Kc* is the traded strike nearest *F*·exp(2σw) among those from *F*·exp(1.5σw) to
   *F*·exp(3σw); the put wing *Kp* the traded strike nearest *F*·exp(−2σw) among those from *F*·exp(−3σw) to
   *F*·exp(−1.5σw).
4. **A week is skipped,** and counted by reason, if the window holds fewer than five traded strikes, if either wing
   has no traded strike in its range, or if no delivery price exists for a day the week needs.
5. **The position,** per 1 BTC of notional: short one call and one put at *K0*, long one call at *Kc* and one put
   at *Kp*.
6. **Prices** at entry: Black-76 with forward *F*, time τ, no interest, each leg at its own strike's implied
   volatility, in dollars. The credit is the two short prices less the two long ones.
7. **Costs of the options.** Half the bid-ask gap, on each short leg the larger of 5 bps of *F* and 4% of the leg's
   price, on each long leg the larger of 1.5 bps of *F* and 10% of the leg's price (a gap is a share of the price as
   much as of the index, and prices were several times higher in 2021). Deribit's trading fee on each leg: the
   lesser of 3 bps of *F* and 12.5% of the leg's price. At settlement, on each leg that finishes in the money: the
   lesser of 1.5 bps of the delivery price and 12.5% of what the leg pays. `espero/venues.py` has no Deribit entry
   and `espero.costs` no option. The 3 bps is Deribit's API today; the 12.5% caps and the settlement fee are its
   schedule as recalled, because the fee page could not be read on 2026-11-10. Before the run they are checked
   against Deribit's published schedule, and where the two differ the higher is charged and the result says so.
8. **Settlement.** With *S* the delivery price on the expiry day, the position pays out
   max(0, *S* − *K0*) + max(0, *K0* − *S*) − max(0, *S* − *Kc*) − max(0, *Kp* − *S*).
9. **The hedge.** At the entry (price *F*) and at each day's 08:00 UTC delivery price from Saturday to Thursday, the
   position's delta is the sum over the legs of the Black-76 delta at that price, the time left to expiry, and the
   leg's implied volatility **as at entry**. The hedge holds minus that delta in BTC until the next of those times,
   and is closed at the settlement price. Its profit is the holding times the change in price over each step. Its
   cost is 6 bps of every dollar traded (5 bps, the perpetual's taker fee before it was cut to today's 3.5, and 1 bp
   for its spread), the closing trade included.
10. **The week's profit,** in dollars per 1 BTC of notional: credit − option costs − settlement payout − settlement
    fees + hedge profit − hedge costs. **The unhedged week** is the same without the hedge's profit and cost.
11. **The week's risk,** *M*: the larger of *Kc* − *K0* and *K0* − *Kp*, less the credit net of the option costs at
    entry. It is the most the unhedged position can lose, known when it is opened. A week with *M* ≤ 0 is skipped
    and counted.
12. **The week's return** is its profit divided by *M*, hedged and unhedged alike. Dividing by *M* rather than by the
    index gives every week the same weight in risk, which is how a steady book would size it; in share of the index
    the weeks of 2020–22, when premiums were two to three times today's, would decide the verdict by themselves.

## Criteria, all required

Every return below is rule 12's, a share of *M*, after all costs.

1. **The holder's screen:** a profit factor of 1.5 or more over the hedged weekly returns.
2. **Statistical bar (research/FDR_STANDARD.md):** the mean hedged weekly return above zero with a Newey-West
   t ≥ 3 (`espero.cascade.nw_t`, lags by `espero.volf.nw_lags`), p two-sided from the normal distribution, and
   Benjamini-Hochberg q < 0.05 over every judged test in `research/trials.csv` with #81 included.
3. **Still there now:** the mean hedged weekly return above zero over the weeks entered from 2025-01-03.
4. **Not one stretch:** the mean hedged weekly return above zero in all but at most two of the calendar years
   that hold 20 or more priced weeks.
5. **Survives its costs doubled:** the mean hedged weekly return above zero with every half bid-ask gap and the
   hedge's cost doubled, each week's *M* kept as in the main run.
6. **The form with a capped loss pays too:** the mean unhedged weekly return above zero. The hedge sharpens the
   measurement; the unhedged position is the one whose worst case is fixed when it is opened, and the one a paper
   book would hold.

## Power

About 350 Fridays; perhaps 300 priced. Everything here is an estimate; nothing has been computed. The body sells for
about 0.8·σw of the index (call it *P*, near 450 bps at this month's volatility), and *M* is about 1.5 *P*. Hedging
seven times leaves an error near 0.9 *P* / √7, about a third of *P*, before the week's own surprise in volatility:
so a hedged week moves with a standard deviation of perhaps 0.2 to 0.35 *M*, the standard error over 300 weeks is
0.012 to 0.02, and t ≥ 3 needs a mean of 0.035 to 0.06 *M* a week. If realized volatility ran 17% under implied, as
the index screen found over the whole history, the gross edge is near 0.17 *P* and the costs near 0.08 *P*, leaving
about 0.09 *P*, or 0.06 *M*: within reach, not comfortably. At the 2025–26 gap (9%) almost nothing is left after
costs, which 97 weeks could not tell from zero in any case; that is why criterion 3 asks only for the sign. Under 200
priced weeks the verdict is INCONCLUSIVE.

## Outcomes

**PASS:** every criterion holds. What follows is a forward paper book of the unhedged position, marked from this
repo's Deribit recording, under its own registration; never money directly, and research/FORWARD_FAMILY.md still
governs. **FAIL:** any criterion misses; the rule is closed under this number. **INCONCLUSIVE:** fewer than 200 priced
weeks; no claim.

## Information only

Each calendar year's mean and count; the mean since 2025 with its t; the unhedged profit factor, worst week and worst
13 weeks; the hedged worst week and worst 13 weeks; the week of 2020-03-06 and the one after; the share of the credit
kept; the cost by component; skipped weeks by reason; the body's implied volatility against the volatility the week
then realized at the daily prices; the hedge's dollars traded a week; every reading in share of the index as well as
of *M*; and the model's credit against the credit from the same strikes' last `mark_price` × `index_price` in the
window, which would show a pricing error in the code, or the forward-against-index bias named in the last section.

## Robustness, information only

Deflated Sharpe at the ledger's count of judged rows, and turnover (the hedge's). Not applicable: PBO (one
configuration), purged k-fold (nothing fitted), capacity (no recorded depth before 2026-11-02).

## What cannot be tested here

- These options are quoted, paid and settled in BTC. The test converts every premium to dollars at entry and every
  payout at settlement, as if the BTC received were sold at once. The margin Deribit would ask is not modelled.
- A fill at the model price less half a gap, for four legs at one instant, from trades spread over four hours. The
  gaps were measured on one Friday in 2026 and are applied to 2020; criterion 5 doubles them, and they may have been
  wider still.
- Deribit quotes `iv` against the expiry's forward, and the rule prices with the index as the forward. Over a week
  the two differ by the weekly basis, a few bps; the mark-price readout above measures what that does to the credit.
- The hedge trades at the daily delivery price, which is an index, not the perpetual's price; the perpetual's
  funding is not charged or credited.
- The hedged position's loss is not capped: a market that swings between the daily hedges costs the hedge each
  time. *M* is the unhedged position's cap only.
