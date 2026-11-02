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

971 slots, 179 coins, 173,630 coin-slots; 3,587 falls and 3,586 rises at the 2% tails (a median fall of
85 bps in 5 minutes). About 81 independent hours. The whole market fell over the explored days: every
coin-slot's forward return averaged −9 bps at 1 hour and −34 bps at 4 hours, and that drift sits under
every event figure below, which is why each group's unconditional line is printed first.

**Two things were added after the first run, both disclosed here.** The first run's t statistics were
wrong: `espero.audit.trade_weighted_nw` clusters by day and read the slot numbers as one day. The
script now clusters by 5-minute slot with Bartlett weights over the horizon's slots
(`cluster_t`). And the unconditional line per group was added, because without it every 4-hour
figure read as a finding when it was the period's fall. No cut, tail, split or horizon changed.

The split by the open-interest change, falls, forward 1 hour, gross bps, with the slot-clustered t:

| group | fall with OI down ≥ 1% ("closing hard") | fall with OI up ≥ 1% ("opening hard") |
|---|---|---|
| whole panel | +12.5 (n 271, 108 slots, t +0.35, hit 0.61) | −49.7 (n 202, 100 slots, t −2.08, hit 0.41) |
| tier ≥ $50M | +52.4 (n 39, 29 slots, t +1.21, hit 0.62) | fewer than 20 |
| tier $5M–$50M | +46.7 (n 38, 22 slots, t +1.63, hit 0.71) | −41.6 (n 26, t −0.89) |
| tier < $5M | −2.2 (n 194, t −0.05, hit 0.59) | −49.4 (n 158, 86 slots, t −2.02, hit 0.41) |
| unconditional, 1 hour | −8.7 (whole panel) | |

At 15 minutes the same sign: opening-hard falls go on falling (−59 bps, t −2.27 in the panel; −67, t −2.47
in the thin tier); closing-hard falls do not (−15, t −0.7). At 4 hours everything is under the period's
fall and nothing separates. The sign-only split (`d < 0` against `d > 0`, without the 1% floor) shows the
same order but weaker: −18 against −32 bps at 1 hour in the panel, t under 1.2 on both.

BTC and ETH alone have 40 falls and 40 rises, and one or two hard events; nothing can be read there.
Rises are not the mirror: a rise with open interest up hard continues at 15 minutes (+11, t +0.7) and
reverses by 1 hour (−49, t −1.9 in the panel; −144, t −2.2 in the top tier on 22 events), while a rise
with open interest down hard shows nothing.

The second look, the hour before the event, separates nothing: crowded and thinning hours before a fall
give −38 and −13 bps at 1 hour with t under 1.3, and the same at 4 hours and for rises.

## What it suggests

The direction #25 found on hourly bars is in the 5-minute data with the same sign: a fall that is made
of positions closing tends to come back over the next hour, and a fall that is made of new positions
opening tends to go on. Read as a forecast for the next hour after a sharp 5-minute fall: **open
interest down hard, lean up; open interest up hard, lean down.** The split is wider in the two liquid
tiers (about +50 against −45 bps) than in the thin one, where the "closing" side shows nothing.

The size is what matters for a trade: the continuation side is about −50 bps at 1 hour against an
18 bps hurdle, the reversal side about +12 in the panel and +50 in the liquid tiers. The t statistics
are 1 to 2.5 on 20 to 100 independent slots.

## Why this is not a result

- **Three and a half days, one regime.** The market fell throughout; 81 independent hours; every 4-hour
  figure is the period's drift. A different week can reverse any line above.
- **The t statistics are at most 2.5**, on the one split out of the ten listed that shows the largest
  gap; the ten were fixed before the run, but a reader choosing the best of ten expects a t of 2 by
  chance.
- **Seen before writing the suggestion.** Every number above was looked at before the test below was
  written, so the test's thresholds (the 2% tail, the 1% floor, the 1-hour hold) come from this data.
  Only the sealed days can judge them.
- **Thin coins carry the counts.** 2,772 of the 3,587 falls are in coins under $5M of daily volume, where
  the 18 bps hurdle is not a round trip (#64's confound), and the liquid tiers have 26 to 39 hard events.
- **Open interest changes for reasons other than the fall.** A 5-minute change in open interest is
  liquidations, closes and opens together; the mark and the open interest come from one read, but the
  fall and the change are measured over the same 5 minutes, so the ordering within them is unknown.
- **Mark prices, not fills.** Forward returns are mark to mark on the 5-minute grid; a fill 2 to 3
  minutes after the slot and the spread are not in them.

## The test this suggests, to be pre-registered before any sealed day is read

A forward test on the sealed days (from 2026-11-02 00:00 UTC, judged with the family after 2027-03-31),
in #58's terms, in a new document with a new number:

- **Data.** `data/hlcollect/ctx/` for the mark and open interest, candles for fills, funding history.
  Coins: the two liquid tiers (`day_volume` at the slot of at least $5M), fixed as a tier rule, not a
  list.
- **Signal.** A 5-minute fall at or below the coin's trailing 7-day 2nd percentile of 5-minute mark
  returns, with the same 5 minutes' open-interest change at or below −1% (the reversal signal) or at or
  above +1% (the continuation signal). Known at the slot's `ts` + 120 s.
- **Trade.** Long on the reversal signal, short on the continuation signal, at the open of the first
  1-minute candle at least 60 s after the signal, held 1 hour, one at a time per coin, net of 18 bps
  and funding by side, as #64 defines net.
- **Criteria.** #58's: trade-weighted net > 0 with t ≥ 3 (clustered by slot), both halves, more than
  half of coins with at least 10 trades, the liquid tier on its own; and, because the two sides are
  one claim, each side's net > 0 on its own. Fewer than 100 trades a side is inconclusive.
- **Power.** The explored days held 57 hard events in the two liquid tiers in 3.4 days, about 17 a
  day, so the window should hold about 2,000 before one-at-a-time; at 150 bps of noise per trade,
  t = 3 needs about +10 bps net, so the test can see an effect a third the size of the one above.
- **Information only.** The 15-minute and 4-hour holds, the thin tier, the rise mirror, and the hour
  before the event.

Nothing here is traded, and the sealed days are not opened until that document is committed.
