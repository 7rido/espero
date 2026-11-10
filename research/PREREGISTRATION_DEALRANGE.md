# Pre-registration — buy the discount half of an hourly dealing range at its proximal line (#75)

Committed **before** any rule is applied to any price. This document is the contract; the result document will
say whether it was met, and nothing below is changed afterwards. A later idea takes a new number.

## Where the rule comes from

The account holder shared on 2026-11-09 a screenshot of a friend's paper bot trading trade.xyz's stock perps on
1-hour bars, labelled "1H TradFi Dealing Range + Proximal + EQ/ERL (PF 1.71 BLOCK)", and a recipe: backtest a
strategy on three to five years, keep a profit factor of 1.5 or better, paper trade, then real money after 50+
profitable trades. The friend's code is not available. The rule below is my reconstruction of that family from
the screenshot's labels and numbers, written before testing: the exits are read exactly from the two trades
shown (half at 1.5R, the stop to the entry, the rest at 2.8R, R being the entry minus the stop; both long,
both resting limit entries); the swing strength, the zone's bar and the cancel rule are my choices, fixed here.
A pass or a fail speaks for this rule, not for the friend's.

## Hypothesis

After a swing low and the rally from it, price often returns to the zone the rally started from; a resting buy
at the top of that zone, when it sits in the lower half of the range, with a stop under the swing low, earns
more than its losses because the targets are 1.5 and 2.8 times the stop. The mechanism claimed by this school is
resting demand at the origin of a move; no forced flow is named, so the prior is weak, and the repo's two
nearest relatives failed on crypto (#13, 1-hour breakouts; #35, stop runs at yesterday's low).

## Data

- **Markets:** the 37 stocks and ETFs whose regular session followed their trade.xyz perp in #73
  (`espero.tradfi.allowed()`, from `research/hip3track_cells.csv` at d3a4d61). No market is added or removed.
- **Bars:** the listed ticker's 1-hour bars from Yahoo as `espero.tradfi.hourly` serves them on the day of the
  run: the last 730 days, bars starting 09:30 to 15:30 Eastern only (#73: the only session that stands in for
  the perp). The run prints each market's first and last bar. A market listed less than 730 days ago is used
  from its first bar.
- **Recipe's three to five years:** not met. Yahoo serves two years of hourly bars; five need a data key only
  the holder can create. This is said here, not discovered later.
- **Excluded before looking:** nothing beyond what `tradfi` excludes.
- **Kept:** the bars the run reads are committed with the result as `research/dealrange_bars.csv.gz`, because
  Yahoo's window rolls and the cache is not in git.

## Rule (`espero/dealrange.py`)

All on one market's bars, in order, using only bars already closed.

1. **Swings.** Bar *j* is a swing low when its low is strictly below the lows of the 5 bars before and the 5
   bars after it; a swing high likewise with highs, strictly above. A swing is known at the close of bar *j*+5.
2. **The range.** When a swing high at bar *h* is known, and the latest known swing low is at a bar *l* < *h*,
   the range runs from that low's low (the **range low**) to the high's high (the **range high**). Its
   **midpoint** is their average.
3. **The proximal line.** The last bar at or before *l*, searching back at most 10 bars, that closed below its
   open. The proximal line is that bar's high. No such bar: no order.
4. **Arming,** at the close of bar *h*+5, when all hold: the proximal line is below the midpoint; it is above
   the stop; and that bar's close is above the proximal line (else the price is already through the zone).
5. **The stop:** the range low minus 0.1 times the 14-bar ATR (Wilder's, `espero.indicators.atr`) at the arming
   bar. 1R is the proximal line minus the stop.
6. **The fill:** the first bar after the arming bar whose low is strictly below the proximal line fills a buy
   at the proximal line, never at a better price, even when that bar opens lower. When that bar opens at or
   below the stop, the trade exits at that open: the loss is the line minus the open, in R, plus costs.
7. **The exits** (`espero.brackets`, with the order filled inside a bar): half at +1.5R, then the stop at the
   entry from the next bar, the rest at +2.8R. Stop first when a bar reaches both; the fill bar can be stopped
   but cannot reach a target; a gap through the stop fills at the open. No time stop. A position may be held
   overnight and over weekends; its overnight move is the ticker's close to open (#73's information: the
   perp's differs by a median 8 bps).
8. **Cancel** an unfilled order when a bar closes below the range low, or when any later swing (low or high)
   becomes known; the swing whose confirmation armed the order does not cancel it. Within a bar the fill is
   checked first, then the cancels: a bar that fills and closes below the range low is a filled trade (its
   stop sits below that low). A new range then arms by rules 2 to 4.
9. **One position per market;** an order that would fill while one is open is cancelled. Long only.
10. **At the data's end** a position still open is closed at the last bar's close and counts in every
    criterion; an order still unfilled is dropped.

**Costs:** 14 bps of notional on every fill, entry and each exit: trade.xyz's taker fee out of growth mode
(9 bps; growth mode can be withdrawn by the deployer, as #74's registration rules) plus 5 bps for slippage.
#74's measured costs do not exist yet; #73's one overnight snapshot put a $10,000 order at a median 1.8 bps.
Charging the taker fee on resting entries and targets is deliberate.

## Criteria, all required

1. **The friend's screen:** profit factor (R won over R lost, every trade) of 1.5 or more.
2. **Statistical bar (research/FDR_STANDARD.md):** the mean R per trade above zero with t ≥ 3, the standard
   error clustered by the trade's entry day (Eastern), its p two-sided from the normal distribution with more
   than 100 entry days and from Student's t with days minus one degrees of freedom otherwise, and Benjamini-Hochberg q < 0.05 over every judged test in
   `research/trials.csv` (status fail, pass, provisional or exploratory) with #75 included, a missing p counted
   as 1.
3. **Beats random entries:** of 2,000 draws of `brackets.random_means` (seed 0; each trade replaced by a market
   entry at a random bar's next open on the same market, same side, same stop as a fraction of price, the same
   bracket and costs), fewer than 5% have a mean R at or above the rule's.
4. **Not one stretch:** mean R above zero in each half of the trades, in entry-time order, the earlier half
   taking the odd one.
5. **Not one coin:** among markets with 5 trades or more, more than half have a mean R above zero.

## Power

Unknown before the run; the rule's trade count is a result. With this bracket a trade's R has a standard
deviation near 1.3, so t ≥ 3 needs a mean of 3.9 / √n: 0.28R at 200 trades, 0.18R at 500. A true profit factor of
1.5 with this bracket is a mean near 0.25R, so fewer than 200 trades leave a real edge of that size more likely to
miss than to pass. Under 100 trades the verdict is INCONCLUSIVE.

## Outcomes

**PASS:** every criterion holds. What follows is the recipe's next step, a paper forward test on the perps
(stage 9 of the holder's list, its own registration), never money directly; research/FORWARD_FAMILY.md applies.
**FAIL:** any criterion misses; this rule is closed, and no variant is tried under this number.
**INCONCLUSIVE:** fewer than 100 trades; no claim.

## Information only

Beside the verdict, deciding nothing: the win rate and how each trade ended (stop, breakeven, target, end of
data); the result without costs and with the growth-mode fee (0.9 bps plus 5); the random draws' median and
the rule's distance above it; per market the trades and mean R; trades held overnight against trades closed
the same day; the mean bars held.

## Robustness, information only

Deflated Sharpe on the per-trade R with N = the ledger's judged rows; not applicable: PBO (one configuration),
purged k-fold (nothing fitted), capacity (no depth recorded for these bars).

## What was seen before this

The #73 result and its inputs (perp against ticker; no rule); each mapped ticker's five-year total return; for
NVDA and CRCL, the count of hourly bars per day served by `espero.tradfi`. No swing, range, entry or exit has
been computed on any of these markets' bars.
