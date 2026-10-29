# Pre-registration — do resting orders earn on thinner coins? (#41)

Committed **before any tick of these coins is downloaded**. A measurement, not a strategy: nothing
trades. The forty-second test in this repo.

## Why

#39 ([RESULTS_MARKOUT.md](RESULTS_MARKOUT.md)) found that a resting order at the back of the queue
loses 0.7–2.5 bps before fees, on BTC, ETH, SOL and XRP, in all 288 cells. That closed "earn the
spread by resting at the touch" **on the majors**. Its biggest open gap is thinner coins: spreads
are wider, and fewer fast market makers may compete for the front of the queue. If resting orders
earn anywhere at this account's speed, the obvious place is down the liquidity ladder.

This test runs #39's measurement, **unchanged**, on eight coins chosen by a fixed liquidity rule.

## The coins — by rule, fixed now

- **Ranking**: the 42 coins of `xs.UNIVERSE`, ranked by mean daily quote volume of their Binance
  USDⓈ-M perpetual in **March 2026**, the month before #39's window. It comes from the 5-minute
  kline archive #30 cached (`data/bids/`).
- **Candidates**: ranks 5–42, so the majors are excluded. Of these, coins with no March file (EOS) or
  under $1M a day (MKR) are dropped. That leaves 36 coins, ranks 5–40.
- **Chosen**: every fifth, from the most liquid to the thinnest. That is ranks 5, 10, 15, 20, 25, 30,
  35 and 40.

| rank | coin | $ a day, March 2026 | on Hyperliquid |
|---|---|---|---|
| 5 | DOGE | 600M | yes |
| 10 | LINK | 126M | yes |
| 15 | WLD | 82M | yes |
| 20 | ARB | 41M | yes |
| 25 | OP | 33M | yes |
| 30 | TIA | 18M | yes |
| 35 | XTZ | 6M | **no** |
| 40 | YFI | 2M | **no** |

The ladder spans 300× in volume, so the test can also see whether markouts **improve** as coins get
thinner, not just whether some coin passes.

## Data — #39's sets, these coins

| set | days | notes |
|---|---|---|
| **B**: Binance `aggTrades` | every UTC day 2026-04-01 → 2026-10-27 | all eight |
| **V1**: Binance `bookTicker` + `aggTrades` | the 1st of each month, 2023-06 → 2024-03 | WLD and TIA only from their listing (the first months 404 and are dropped) |
| **V2**: Tardis `binance-futures` quotes + trades | the 1st of each month, 2026-04 → 2026-10 | all eight |
| **H**: Tardis `hyperliquid` quotes + trades | the 1st of each month, 2024-11 → 2026-10 | six coins (XTZ and YFI are not listed) |
| **L**: aggr hourly liquidations | 2026-04 → 10 | only DOGE and LINK are in aggr's coin list; the other six have no liquidation condition |

## Definitions, conditions, validation, replication — #39's, unchanged

- The same code: `espero/markout.py` at `9eb2602`, with no change to any definition.
- The same trade proxy, the same three measures, the same four conditions plus "all", the same
  horizons (1, 10, 60, 300 s), and the same day clustering.
- The same tolerance: |proxy − quote| ≤ max(0.25 bps, 20%).
- **Validation**: a (coin, horizon) is validated when every "all" cell passes on V2 **and** on V1
  where the coin has V1 days. A coin with no V1 days is validated on V2 alone, and that is reported.
- **Replication**: Tardis trades against the archive's `aggTrades` on the V2 days, every "all" cell.

## The pass bar

- Earlier tests: 41.
- This study's cells: (8 Binance + 6 Hyperliquid coins) × 10 condition levels × 4 horizons = 560.
- N = 601. The deflated bar, by #39's formula: **t ≥ 4.75** (4.752).

Cells that cannot exist are examined as missing, not removed from N: liquidation levels for coins
outside aggr, and Hyperliquid for XTZ and YFI.

## Evaluation — once

**The answer: YES or NO, by #39's Q3 rule.** At least one cell must meet all of:
- the conservative maker markout, net of the venue's maker fee, > 0 with day t ≥ 4.75;
- > 0 in each half;
- on Binance, validated and replicated.

**Information only:**
- the cost table for these coins: taker half-spread, taker round trip, and optimistic and
  conservative markouts;
- the **ladder**: the conservative 60 s markout against log volume rank, across all twelve coins
  (#39's four plus these eight), Binance;
- the size and hour splits, as in #39.

## Outcomes, fixed now

- **The measured cells join `espero/costs_table.py`**, under the same validation rule, so
  `espero.costs` prices these coins too. It still raises for any coin not measured.
- **YES**: the next test pre-registers a forward paper quoting rule in the passing cell. Paper only.
- **NO**: "resting at the touch" stays closed, now across the liquidity ladder from $14B to $2M a
  day.

## Transparency — what I saw before writing this

- **The March 2026 volume ranking** of all 42 coins: the table above, plus the majors' volumes.
- **Archive listings and Tardis range requests** (file existence only) for these eight coins.
- **Hyperliquid's mainnet coin list.**
- **#39's results on the majors.**
- No tick, quote or markout of these eight coins has been computed or seen.
