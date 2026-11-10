# Pre-registration — what a fill costs on trade.xyz's perps, by size and session (#74)

Committed **before** any book is recorded for it. A measurement, information only: no PASS or FAIL, no t, no
trial spent. `espero.costs` refuses any coin #39 did not measure, so no rule on these perps can be costed until
this exists. Nothing below is changed afterwards.

## What I had seen when this was written

On 2026-11-10 UTC, one order book for each of 58 markets, taken between 00:37 and 00:40 UTC (the US overnight
session): the median spread was 1.5 bps and a $10,000 buy cost a median 1.8 bps from the mid. One moment, one
session. Those numbers set nothing below except the sizes worth measuring.

## Data

- **Books:** Hyperliquid's `l2Book` frames for trade.xyz's markets, mainnet, written by the second raw recorder
  (`com.espero.rawrec-hip3`, its own folder named by `ESPERO_RAW_DIR_HIP3`), 20 levels a side.
- **Markets:** the ones that recorder is started with: every market in `research/hip3_map.csv` whose last 24
  hours reach $5M when the account holder installs it. The list is written to the folder's `coins.json` and
  only ever grows.
- **Window:** the first 14 complete UTC days after the recorder starts, which hold two weekends. A day with
  a recorded gap of more than an hour for a market (`rawrec.gaps`) is left out for that market and counted.
- **Fees:** each market's taker and maker fee as `espero.hip3.fees_bps` computes them from the venue's own
  report, read once a day in the window, with the days in growth mode and out of it counted.

## The measurement

At every minute boundary, the last whole book at or before it, if it is at most 10 seconds old. From its mid,
the average price of a market buy and of a market sell of **$1,000, $10,000 and $50,000** walking the
recorded levels, as bps from the mid; a size the 20 levels cannot fill is counted as unfilled, not priced.
Each sample belongs to a session by the Eastern clock: regular (09:30 to 16:00, Monday to Friday),
pre-market and after-hours (04:00 to 09:30, 16:00 to 20:00), overnight (20:00 to 04:00), weekend (Friday 20:00
to Sunday 20:00). An index or commodity uses the same clock, so its numbers can be read beside a stock's.

Per market, session and size: the number of samples, the share unfilled, and the median and 90th percentile of
the cost, buys and sells together; and the quoted half-spread's median.

## Rules fixed now

- A cell with fewer than 500 samples, or more than 5% unfilled, is **not measured**. Nothing is imputed from
  another market or session.
- **The cost a backtest must use** for a taker fill of a given size, market and session: the fee the market
  would pay **out of growth mode**, plus the cell's 90th percentile. Growth mode is the deployer's to switch,
  and a rule that pays only at the discounted fee has not been shown to pay. The discounted fee and the median
  are reported beside it, never used to judge.
- A maker fill is not measured here: this recorder's trades and books could support it, as #39 and #62 did for
  the venue's own perps, and that is its own registration.

## Outcome

`research/RESULTS_HIP3COST.md` with the table, and a generated `espero/hip3cost_table.py` the backtests read.
`espero.costs`' table, measured by #39 and #41, is not touched.

## Power

Fourteen days hold 20,160 minutes: about 3,900 regular, 5,700 pre-market and after-hours, 4,800 overnight
and 5,760 weekend samples a market, before gaps. Every session clears 500 unless the recorder was down for
most of it.

## Information only

The cost by hour of the Eastern day; the same table for the window's two weeks apart; how often the book was
older than 10 seconds; each market's days in and out of growth mode.

## Robustness, information only

Not applicable: no return, no rule, no configuration.
