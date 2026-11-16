# Pre-registration — funding carry on BTC and ETH with both legs on Hyperliquid, forward on paper (#83)

Committed **before** the book exists and before any price or funding inside its window is read. This document is the
contract; nothing below is changed afterwards. A later idea takes a new number.

## Why this test

Carry is the one candidate left from the screens of 2026-11-10 (research/IDEAS_NOVEL.md, screen 35): always short
the perp against spot earned about 9% a year on capital on BTC and on ETH since May 2023, positive every calendar
year, but about 4% in 2026. #12 (provisional) runs this trade forward with Coinbase as the spot leg, which the holder
cannot use at a sane cost (VENUE_NONUS.md). Hyperliquid lists BTC and ETH spot tokens (UBTC, UETH) beside their
perps, so both legs can sit on one venue. The account holder said on 2026-11-10 that a steady 5% to 10% a year with
small drawdowns counts as working, and on 2026-11-16, of the 4% figure: "use 4% for larger trades like $100+".
Every year of that history was read by the screen, so there is no unseen history left: only a forward test is fair.

## Hypothesis

Traders who want leverage on BTC and ETH hold long perps and pay the shorts a rent to keep them. A book that holds
the coin and is short the same amount of perp collects that rent while the two price legs cancel, and the rent
exceeds what it costs to open and hold the pair on Hyperliquid.

## What was seen before this

The screen above (each coin's hourly funding from `research/data/carry/`, to 2026-10-28, by calendar year), and one
snapshot of Hyperliquid's books on 2026-11-10 17:38 UTC: buying $50k of spot cost 0.8 bps over the middle for BTC and
1.2 for ETH, selling the perp 0.1 and 1.7, and the spot tokens sat about 5 bps above their perps. Nothing from
2026-11-23 on has been read.

## Data

- **Books:** Hyperliquid's `l2Book` for the perps `BTC` and `ETH` and the spot pairs `@142` (UBTC/USDC) and `@151`
  (UETH/USDC). The pair names are checked against `spotMeta` at start; if Hyperliquid renames them the book follows
  the token, and the result says so.
- **Funding:** Hyperliquid's `fundingHistory` for `BTC` and `ETH`, hourly, as settled.
- **Reads:** one pass an hour at minute 33 (out of minutes 19 to 27, research memory on the shared rate limit): the
  four books, then each coin's funding since the last pass. Each pass is written as read to
  `state/spotcarry/YYYY-MM-DD.jsonl` (raw, append-only) before the book uses it.
- **Window:** from Monday 2026-11-23 00:00 UTC to 2027-03-31 23:59 UTC. A pass that fails is a gap: recorded,
  never filled from another source.

## Rule (`espero/spotcarry.py`)

Two coins, each its own position; nothing is chosen, so the book has no signal.

1. **Size:** $100 of each coin per position, bought on spot and sold on the perp in the same pass (the holder's
   figure). Capital per coin is $150: the spot paid in full and half again as the perp's margin.
2. **Entry:** at the first pass in the window, for each coin: buy $100 of spot at the book's asks, walked level by
   level, and sell the same number of coins on the perp at its bids, walked level by level.
3. **Hold:** to the end of the window. The short perp is credited each settled hour with funding × the perp's
   notional at that hour's mark (positive funding is paid to the short), as Hyperliquid settles it.
4. **Rebalance:** if at a pass the perp short's notional and the spot's value differ by more than 5% of the
   position, trade the perp alone back to the spot's quantity at the book, at the fee in rule 5. No other trade.
5. **Fees:** Hyperliquid's published taker fees for an account with no volume: before the first pass the code reads
   them from Hyperliquid's fee schedule and the result states them; until confirmed the book charges 7 bps on spot
   and 4.5 bps on the perp. A higher published figure is charged in place of these; a lower one is reported and not
   used.
6. **Exit:** at the last pass in the window, sell the spot at the bids and buy back the perp at the asks, walked,
   with fees. This exit is charged in the result whether or not anything trades afterwards.
7. **Marks:** at every pass, each coin's equity = cash + spot units × spot mid − perp units × perp mid + funding
   credited − fees paid, against its $150 of capital. The book's equity is the sum over the two coins.

## Criteria, all required

1. **It pays:** the book's net return over the window, exit included, above zero.
2. **At the holder's rate:** that return, annualised on 365 days, at or above 3% a year on capital. (The holder named
   4%; 3% leaves room for the exit cost on a short window and is fixed now, not after.)
3. **Statistical bar (research/FDR_STANDARD.md):** the book's weekly net returns (Monday 00:00 UTC to Monday, the last
   week charged the exit) have a mean above zero with t ≥ 3 by Student's t with Newey-West errors
   (`espero.cascade.nw_t`, lags `espero.volf.nw_lags`, p two-sided from Student's t at n − 1 degrees of freedom, since
   the weeks are under 100), and Benjamini-Hochberg q < 0.05 over every judged test in `research/trials.csv` with #83
   included.
4. **The hedge held:** at no pass did a coin's spot mid stand more than 1% from its perp mid.
5. **Both coins:** each coin's own net return, exit included, above zero.
6. **The record is whole:** at least 95% of the window's hourly passes succeeded.

## Power

About 18 weeks. At the screen's 2026 rate (about 4% a year on capital, about 0.08% a week), with the price legs
cancelling to within a few bps a week, the weekly standard deviation is perhaps 0.02% to 0.05% of capital, so t ≥ 3
needs only a handful of weeks if the rent is paid. The binding criteria are 1, 2 and 5: the entry and exit cost about
23 bps of the position, about 15 bps of capital, which is two weeks of rent at that rate. Fewer than 12 complete weeks
→ INCONCLUSIVE.

## Outcomes

**PASS:** every criterion holds. What follows is the holder's to decide under research/FORWARD_FAMILY.md,
DEPLOYMENT_LADDER.md and their own lift and allow-list: at most a canary of this size, never money directly from this
document. **FAIL:** any criterion misses; closed under this number. **INCONCLUSIVE:** fewer than 12 complete weeks.

## Information only

#12's thresholds (in above 15% a year on the trailing 168 hours, out under 5%) run on the same passes as a second
book, never a criterion; funding earned, fees and the change in the spot-perp gap, by coin; the worst week; the largest
spot-perp gap; what $100 would have cost at $1k and $10k on the recorded books.

## Robustness, information only

Not applicable: deflated Sharpe, PBO and k-fold (one configuration, nothing fitted). Capacity: the walk at $1k and $10k
above.

## What cannot be tested here

- A paper fill at the recorded book is not a real one: queue, latency and partial fills are missing.
- The perp's margin is assumed to be posted from the $50; liquidation is ruled out only while the price stays inside
  what that margin covers (about +50% on a 2x short), not checked against Hyperliquid's own margin rules.
- Hyperliquid's spot tokens are bridged coins; the risk that UBTC or UETH stops tracking BTC or ETH is what criterion
  4 watches, not something 18 weeks can measure.
- Nothing here places an order. A real position is the holder's act alone.
