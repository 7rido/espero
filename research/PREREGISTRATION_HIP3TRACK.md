# Pre-registration — does a trade.xyz perp follow its listed ticker, hour by hour? (#73)

Committed **before** any comparison is computed. A measurement, information only: no PASS or FAIL, no t, no
trial spent. It fixes, before any strategy is defined, which of a listed ticker's bars may stand in for the
perp in a backtest. Nothing below is changed afterwards; a later idea takes a new number.

## Why

Hyperliquid's stock, index and commodity perps (trade.xyz, `xyz`) began on 2025-10-13. A test over three to five
years can only run on the listed ticker. That is fair only where the perp's price moves as the ticker's does,
and the two differ in kind: the stock trades 6.5 regular hours (16 with pre-market and after-hours), the perp
trades all day on outside quotes five days a week and on trade.xyz's own pricing at weekends; the perp pays
funding and no dividend; a split settles and reopens the market.

## What I had seen when this was written

On 2026-11-10 UTC, read-only: the list of markets, their 24-hour volume, open interest, funding and one order
book each; daily candles for 58 markets (first day, 30-day median volume); hourly candles for NVDA, XYZ100,
GOLD, INTC and CRCL, used only to split their **volume** by session; and Yahoo's daily bars for the mapped
tickers, used only for each one's five-year total return. No perp price was set against a ticker price beyond
one line printing both last prices side by side at one moment. No return of one was compared with the other's.

## Data

- **Markets:** every market in `research/hip3_map.csv` (as committed at 9c38f68) of kind US stock, ETF,
  leveraged ETF, index or commodity, whose last 24 hours reach $5M at the run's first request, and whose first
  15-minute candle is at or before the window's start. Korean, Japanese and Hong Kong lines are left out: their
  price on trade.xyz is converted at a currency rate, which is its own question.
- **Perp:** Hyperliquid's `candleSnapshot`, 15-minute candles, mainnet. "The perp's price at T" is the open of
  the candle that starts at T.
- **Ticker:** Yahoo's chart endpoint, 1-hour bars with pre-market and after-hours for stocks and ETFs, 1-hour
  bars for the futures; and its daily bars, unadjusted, for the official open and close.
- **Window:** 2026-09-21 00:00 UTC to 2026-11-07 00:00 UTC. The venue serves 5,000 candles an interval, about 52
  days of 15-minute candles, so the run must happen by 2026-11-11; if the first days are no longer served, the
  window starts at the first whole day that is, and the results say so.
- **Left out before looking:** a market's split days and the day either side; any bar pair with a missing price
  on either side; US market half-days are kept.

## The measurement

**Hourly.** For each market, take consecutive Yahoo bars on the same Eastern date whose starts are at most 65
minutes apart, both on a 15-minute boundary. The ticker's return is the next bar's open over this bar's open; the
perp's is its price at the next bar's start over its price at this bar's start. Each pair belongs to the
session of its first bar, by the Eastern clock: **pre-market** 04:00 to 09:30, **regular** 09:30 to 16:00,
**after-hours** 16:00 to 20:00; for an index or commodity, every pair is **futures hours**. Per market and
session: the number of pairs, the correlation of the two returns, and the median and 95th percentile of the
absolute difference, in bps.

**At the bell.** For stocks and ETFs, per market and day: the perp's price at 09:30 Eastern against the official
open, and at 16:00 against the official close, as an absolute gap in bps; and the overnight return (close to next
open) of each, as an absolute difference in bps. Per market: the medians.

## Tolerance, fixed now

A market **follows** in a session when it has at least 100 pairs there, a correlation of at least 0.90, a median
absolute difference of at most 10 bps and a 95th percentile of at most 50 bps. Ten bps is under a tenth of the
stop a one-hour rule on these names would carry, so a rule's outcome on the ticker's bar and on the perp's would
rarely differ; fifty catches a stand-in that is usually right and sometimes badly wrong.

A **session stands in** when at least 80% of the markets with 100 pairs there follow. At the bell, the open
and the close each **stand in** when the median gap across markets is at most 10 bps.

## What the outcome decides

- A backtest for these perps may use the ticker's hourly bars only in sessions that stand in, and may fill at
  the official open or close only if that bell stands in. Elsewhere it must use the perp's own bars, which are
  a year old at most.
- The overnight session (20:00 to 04:00 Eastern) and the weekend have no ticker bars. No ticker backtest covers
  them, whatever this measurement finds; a rule that holds through them carries that as an untested stretch.
- Markets that do not follow are listed and left out of ticker backtests.

## Power

Forty-seven days hold about 33 trading days: per market about 210 regular pairs, 160 pre-market and 100
after-hours; fewer where Yahoo has no early prints. A market under 100 pairs in a session is reported as "too
few", never as following.

## Information only

Beside the table: each market's mean signed difference (a drift between the two), the same statistics split
into the window's two halves, and the share of volume by session.

## Robustness, information only

Not applicable: no return, no rule, no configuration.
