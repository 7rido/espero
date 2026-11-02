# Pre-registration — aggr's forward bars, rebuilt from the raw streams (#61)

Committed **before** any overlapping day exists. Written 2026-11-02, the day the raw recorder
(`espero rawrec`, docs/DATA.md section 5) first ran; the first UTC day it and `data/aggr/forward*` can both
hold in full is 2026-11-03, and aggr's copy of that day lands at the 07:30 run on 2026-11-04. This document
is the contract; the result document will say whether it was met, and nothing below is changed afterwards.
A later idea takes a new number. **This is a measurement, not a hypothesis test:** it has a registered
tolerance and pass criteria, no t, and changes no forward verdict. It spends no trial of the FDR family
(research/FDR_STANDARD.md) because it claims no effect.

## Question

Fourteen forward tests (#22–#45) are judged on aggr's hourly and 5-minute bars, fetched from one person's
free server. How far do those bars sit from bars rebuilt from the venues' own streams, recorded here? If
far, the forward verdicts rest on a copy no one can audit; if close, the raw tape is an independent
witness, and acceptance (c) below can be run at judgment.

## Data

- **Recorded:** `data/aggr/forward/<day>.csv.gz` (hourly) and `data/aggr/forward5m/<day>.csv.gz`, as the
  daily job saves them, for every market among aggr's 14 coins (`espero/aggr.py`, `COINS`):
  `BINANCE_FUTURES:*`, `BYBIT:*` and `OKEX:*`.
- **Raw:** `<ESPERO_RAW_DIR>/binance/<day>/*.ndjson.zst` (`aggTrade`, `forceOrder`),
  `<ESPERO_RAW_DIR>/bybit/<day>/*.ndjson.zst` (`publicTrade`, `allLiquidation`),
  `<ESPERO_RAW_DIR>/okx/<day>/*.ndjson.zst` (`trades`, `liquidation-orders`, with `instruments.json` for
  contract values). Where the live Binance tape has a gap, prices, volumes and counts for that bar come from
  `<ESPERO_RAW_DIR>/binance_archive/aggTrades/<symbol>/<symbol>-aggTrades-<day>.zip` instead, and the bar is
  marked `archive`; its liquidation columns are then **not comparable** (the archive has no liquidation
  dataset) and are reported as "cannot be rebuilt" rather than compared.
- **Window:** every UTC day from 2026-11-03 on that both sides hold in full, judged as below. Days before
  2026-11-03 are not comparable (the recorder did not exist) and are not read.
- **Excluded before looking:** a market-hour (or market-5-minute bar) inside a recorded gap on our side
  (`rawrec.gaps`, silence over 120 s in that venue's tape during the bar) is **not comparable** and
  leaves the denominator; the count of excluded bars is reported per day. A bar aggr did not save (no
  row) is **comparable and a miss**, because the question is aggr's completeness as much as its arithmetic.

## Rule — how a bar is rebuilt

Exactly as aggr-server builds it (`src/storage/influx.js`, read 2026-11-02; `src/exchanges/bybit.js`,
`okex.js`, `binance_futures.js`):

- A trade goes to the bar of `floor(exchange_ts / bar_ms) * bar_ms`, by the **exchange's** timestamp.
- `open` is the first trade's price, `close` the last, `high` and `low` the extremes; liquidations do not
  touch prices.
- `vbuy`, `vsell` are **dollars** (price × size) of trades whose taker side is buy / sell; `cbuy`, `csell`
  count those trades. Bybit's `S`, OKX's `side` name the taker side. Binance's `m` (buyer is maker) means
  sell; an aggTrade counts `l − f + 1` trades, since aggr's live feed is the raw `@trade` stream.
- `lbuy`, `lsell` are dollars of liquidations by **order** side: Bybit's `S` is the liquidated *position*
  side, so `Buy` (a long liquidated) is a sell order → `lsell`, as aggr flips it; OKX's `side` is already
  the order side; Binance's `o.S` too. OKX sizes are contracts × `ctVal`.
- An empty `lbuy`/`lsell` in aggr's file means 0 (aggr writes the pair only when one is non-zero).
- Hourly bars from `forward/`, 5-minute from `forward5m/`; both are rebuilt and compared.

## Tolerance, per market-bar, all four must hold for a bar to match

| field | matches when |
|---|---|
| `open`, `high`, `low`, `close` | each within 5 bps of aggr's (bar-boundary trades can differ by one print) |
| `vbuy + vsell` | within 2 % of aggr's, or within $2,000 (the venues drop and resend; aggr reconnects) |
| `cbuy + csell` | within 2 %, or within 20 trades |
| `lbuy`, `lsell` | each within 5 % or $500; a Binance bar rebuilt from the archive: not compared, "cannot be rebuilt" |

A bar is compared only where both sides have a row or aggr's row is absent (a miss); a bar our tape lacks
entirely (no trade, no heartbeat) is excluded as a gap, above.

## Criteria, judged once

Judged at the first daily run after **30 comparable UTC days** exist (expected early December 2026), on
those days only; before that, the per-day table is **information only**. After the judgment the daily table
continues as information only, for the family's judgment in 2027.

1. **(a) The rebuilt bars match aggr's on at least 95 % of comparable days**, where a day matches when at
   least 95 % of its comparable hourly market-bars match on all fields in the table, over all three venues'
   markets. Reported, not decisive: the same for 5-minute bars, and per venue.
2. **(c), at the family's judgment after 2027-03-31, not before:** each forward rule that reads aggr's bars
   (#22, #23, #27, #32, #45 through `liqfwd`, `liqbreak`, `fundsplit`, `liqhold`) is applied, once, to the
   rebuilt bars in place of aggr's, over the days both hold, and its PASS/FAIL/INCONCLUSIVE is
   compared with the committed verdict. **Agreement on every test** is the pass. This step reads running
   numbers, so it runs only at judgment; until then the mechanism is tested on synthetic bars only
   (`tests/test_rawbars.py`). It changes no verdict either way: a disagreement is reported beside the
   verdict as "the raw witness disagrees", and nothing more.
3. Both (a) and (c) must hold for #61 to PASS. (a) alone, before 2027-03-31, gives **PROVISIONAL**.

## Power

Thirty days × ~23 markets × 24 hours ≈ 16,000 hourly bars. A 5 % mismatch rate is seen at that size
with no doubt; the criterion is a tolerance, not a test. The weakness is the other way: a laptop that sleeps
can exclude most of a day as a gap, so the number of comparable days is reported beside the fraction.

## Outcomes

**PASS:** (a) and (c). aggr's bars are confirmed as an audited copy; the raw tape is the witness for every
later bar test. **PROVISIONAL:** (a) only, until 2027. **FAIL:** (a) misses. The forward verdicts stand as
committed (their plans name aggr's bars), the result says on which markets and fields they diverge, and any
later test on aggr's bars must register its own witness. **INCONCLUSIVE:** fewer than 30 comparable days by
2027-03-31. No outcome changes a forward test's verdict, bars or criteria.

## Information only

Per day and market: the fraction of matching bars, the field that failed most, the excluded (gap) count,
the count of Binance bars taken from the archive, the 5-minute table, and the receive-time lag (receive − exchange
timestamp) distribution per venue. The hourly `forward/` file has no `BYBIT:SOLUSDT` rows although
`COINS` names it; the run reports whether that market ever appears.

## Procedure

`python research/rawbars.py` reads the raw tape and the forward files, writes `research/rawbars_days.csv`
(one row per day, venue and bar size) and prints the table; `research/rawbars_run.txt` is its output at the
judgment. `espero/rawbars.py` holds the pure rebuild and comparison (arrays in, numbers out). The Binance
archive is fetched by `espero.binance_archive` into `ESPERO_RAW_DIR`, never `data/`.

## Timestamp

This file's SHA-256 is stamped with OpenTimestamps (`research/PREREGISTRATION_RAWBARS.md.ots`,
`scripts/timestamp.sh`) at the commit that adds it, before any overlapping day exists; `ots verify` checks it
against Bitcoin once the calendar's attestation is confirmed.
