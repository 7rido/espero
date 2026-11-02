# Exploration — open interest beside the price at 5 minutes, 2026-10-29 to 2026-11-01 (Hyperliquid's contexts)

**Not a test.** Exploration made to suggest a rule, on data split in advance. Nothing here is a
finding until a pre-registered forward test on the sealed days confirms it. This is idea 18 in
[IDEAS_NOVEL.md](IDEAS_NOVEL.md): a fall made of positions closing (open interest falling with the price)
is a cascade, which #25 and #26 found overshoots and comes back on hourly and daily data; a fall made
of new sellers (open interest rising) is a repricing, which does not.

Script: [oi5m_explore.py](oi5m_explore.py). Output: [oi5m_explore_run.txt](oi5m_explore_run.txt).

## The data and the split

`espero hlcollect` reads every listed perp's mark, oracle, funding, premium and open interest every 5
minutes into `data/hlcollect/ctx/<day>/<HHMM>.csv.gz` (179 coins at the time of writing). Mark and
open interest come from the same read, so they are synchronous. Open interest is in units of the coin.

The days were split **before anything was looked at**, and this section was written to disk before the
script ran:

- **explored**: the ctx slots from 2026-10-29 15:05 UTC (the first on disk) through 2026-11-01 23:55 UTC,
  3.4 days, about 1,000 slots. Their hashes are in `data/hlcollect/MANIFEST.sha256`.
- **sealed**: every slot from 2026-11-02 00:00 UTC on, which the collector keeps recording. The script
  refuses to open them. A pre-registered forward test judges on those days only.

## The cuts, fixed before the run

One grid: the 5-minute slot from the file name. A missing slot is a gap: no event there, no forward
return across it, nothing interpolated.

- **The 5-minute move.** `r = mark_t / mark_{t-1} − 1` for consecutive slots 300 s apart.
- **The open-interest change over the same 5 minutes.** `d = OI_t / OI_{t-1} − 1`, in coins.
- **Events.** Per coin, a **fall** is a slot with `r` at or below the coin's 2nd percentile of `r` over the
  explored days; a **rise** is at or above the 98th.
- **The split.** By the sign of `d`: **closing** (`d < 0`) against **opening** (`d > 0`); then the finer
  split, `d ≤ −1%` against `d ≥ +1%`.
- **Forward returns.** `mark_{t+h} / mark_t − 1` for `h` = 15 minutes, 1 hour, 4 hours, from the slot's
  mark, in bps, gross: no cost is deducted, and the forward hurdle of 18 bps is the reader's yardstick.
- **Groups.** The whole panel; BTC and ETH alone; the three liquidity tiers of #64 from `day_volume`
  at the slot: at least $50M, $5M to $50M, under $5M.
- **The t.** Clustered by slot (`espero.audit.trade_weighted_nw`, lags = 1, with the slot as the
  cluster), because the whole panel moves at once. There are about 80 independent hours in the explored
  days, which is the number that limits every 1-hour figure below.
- **A second look, listed now.** The open-interest change over the hour before the event (`OI_t /
  OI_{t-12} − 1`), split at its coin median: whether a crowded hour before the fall changes the answer.

Nothing is added to this list after the run.

## What was looked at

(filled in after the run)

## What it suggests

(filled in after the run)

## Why this is not a result

(filled in after the run)

## The test this suggests, to be pre-registered before any sealed day is read

(filled in after the run)
