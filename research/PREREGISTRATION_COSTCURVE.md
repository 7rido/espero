# Pre-registration — a cost curve by order size on Hyperliquid, from #51's book files (#68)

Committed **before any book file is read at a size #51 did not measure**, with one disclosed exception below. A
measurement, not a strategy: nothing trades, no signal is used, no return is computed, and it claims no edge. This
document is the contract; the result document will say what was measured, and nothing below is changed afterwards.
A later idea takes a new number.

## Why

Every frozen test charges one cost per leg, from `espero.costs` (#39, #41) or an assumed 18 bps round trip, with no
size in it. #51 measured a market order's cost at three sizes, $1,000, $10,000 and $100,000, and found it covered at
$1,000 everywhere and unknowable at $100,000 on most coins. A sizing document under `research/FORWARD_FAMILY.md` needs
more than three points: it needs the cost as a function of size, and whether that function holds from one period to
the next. The ten sizes below give the curve; the split by date says whether a curve fitted on the first ten days
still prices the next ten.

**The questions, fixed now:**

1. On each of #51's 14 coins, what does a market order cost at ten sizes from $500 to $500,000, and up to what size can
   the recorded book answer at all?
2. Does a two-parameter square-root curve, `cost = c0 + k × sqrt(size / $10,000)`, fitted on the first ten days,
   predict the second ten days' mean cost at each size within 0.5 bps, the tolerance #51 used for its validation? And
   is a size-free cost, which is what every frozen test assumes, already within that tolerance?
3. Information only: how much does the cost at $10,000 move with the hour of the day?

**This changes no frozen test.** `espero.costs` is not read by this test and not changed by it. The fitted curve goes
into a generated table, `espero/costcurve_table.py`, that only a later sizing document may consume.

## What the author already knew

- **#51's results in full**: `RESULTS_BOOKWALK.md` and `bookwalk_days.csv`, every coin-day at $1,000, $10,000 and
  $100,000, including which days have 20 levels and which 5. So three of the ten sizes are not sealed on any day, and
  the author knows the curve's rough shape between them on every coin.
- **#51's validation gap**: the book walk read 0.35 to 0.56 bps a leg below the effective half-spread real trades paid
  (#39, #41) on the six coins both cover. Those six gaps, and the largest of them for the other eight coins, are carried
  here as a labelled floor adjustment, not measured again.
- **One file at the new sizes, on 2026-11-03, before this document.** A timing check walked SOL's 2025-06-01 asks
  (the buy side only) at $500 to $200,000: 0.38 bps at $500 rising to 1.28 bps at $200,000, every snapshot fillable,
  with a median quoted spread of 0.646 bps, 90th percentile 0.66. That coin-day stays in the sample and is handled like
  every other. Its hour-of-day profile and its sell side were not computed. No other file was opened at a new size.
- **The spread barely varies within a day on SOL** (one tick most of the time), so the hour profile is by hour, not by
  spread; a spread conditioning was considered and dropped before this commit for that reason.
- **Which way the author expects it to go.** The square-root form is the standard impact law and should hold within
  tolerance on the large coins; the flat cost should be enough on BTC and ETH, where the whole curve sits under 1 bps,
  and fail on the small coins; the small coins' reach should stop at $50,000 or $100,000.

## Data — fixed

- **Files.** `data/bookwalk/<coin>-<day>.csv.gz`, Tardis.dev's `book_snapshot_25` for Hyperliquid, exactly the files
  #51 fetched. Nothing is fetched; nothing under `data/` is written.
- **Coins.** #51's 14: BTC, ETH, SOL, XRP, DOGE, LINK, ADA, AVAX, BNB, TRX, LTC, XLM, HBAR and kSHIB.
- **Days.** The 20 first-of-month days with 20 levels a side, 2024-11-01 to 2026-06-01. XLM has 19, having no
  2024-11-01 file. The four days from 2026-07-01 on carry 5 levels a side (`RESULTS_BOOKWALK.md`) and cannot hold the
  larger sizes; they are not read.
- **The split, by date.** Design: the first ten days, 2024-11-01 to 2025-08-01 (XLM nine). Holdout: the next ten,
  2025-09-01 to 2026-06-01. The day is the independent unit, as in #51. A curve is fitted on design days only and scored
  on holdout days only; every other readout uses all 20.
- **A missing file** is recorded as missing, not filled from elsewhere.

## The measurement — fixed

Code: [espero/costcurve.py](../espero/costcurve.py), pure, and [costcurve.py](costcurve.py), which reads and prints.
Both at this document's commit. The walk itself is #51's `espero.bookwalk.walk`, unchanged.

1. **Snapshots** are valid as in #51: both sides present and not crossed. Mid is (best ask + best bid) / 2.
2. **Sizes:** $500, $1,000, $2,000, $5,000, $10,000, $20,000, $50,000, $100,000, $200,000 and $500,000, each a
   market order of that many dollars walked through the visible levels, best first, as #51 did.
3. **A coin-day's cost at a size:** #51's rule. For each side, the mean cost over fillable snapshots, then the mean of
   the two sides; no cost if either side has no fillable snapshot. Its unfillable share is the mean over all snapshots
   of both sides.
4. **Measured sizes.** A coin-size is measured when, over all its days, the mean unfillable share is at most 5% and at
   least 10 days have a cost: #51's UNKNOWN rule, inverted. Unfillability only grows with size, so the measured sizes
   run from $500 up to the first size that fails; that size and every larger one are **beyond reach**. The largest
   measured size is the coin's **reach**.
5. **The curve.** For each coin, with x = sqrt(size / $10,000): ordinary least squares of the design-day mean cost on
   a constant and x, over the measured sizes. This gives c0 (bps, the cost of a vanishing order) and k (bps per unit
   of x).
6. **Scoring.** For each measured size, the holdout-day mean cost against three predictions from the design days:
   - **curve:** c0 + k × x;
   - **flat:** the design mean at $1,000 at every size, which is what a size-free cost assumes;
   - **table:** the design mean at that same size, a lookup with no functional form.
   Each prediction's error is the root mean square over the measured sizes, in bps.
7. **The verdict, one per coin, checked in this order:**

| verdict | rule |
|---|---|
| **UNKNOWN** | fewer than 3 measured sizes, or fewer than 5 design days or 5 holdout days with a cost at the reach |
| **FLAT IS ENOUGH** | the flat prediction's error ≤ 0.5 bps |
| **CURVE HOLDS** | the curve's error ≤ 0.5 bps |
| **CURVE DRIFTS** | anything else |

The test's result is the 14 verdicts with their curves and reaches. No overall pass or fail: this is a measurement.
FLAT IS ENOUGH is checked first because when it holds the curve adds nothing a sizing document needs, whatever its
own error. The table prediction's error is reported beside the curve's and decides nothing; it says whether the
functional form helps or hurts against a plain lookup.

8. **The generated table.** `espero/costcurve_table.py` holds, per coin, c0, k, the reach and the verdict.
   `espero.costcurve.cost(coin, usd)` returns the curve's cost at `usd` and **raises** for a coin whose verdict is
   UNKNOWN or CURVE DRIFTS, for a size beyond the reach, or for a coin not in the table. Nothing is imputed.
   `cost(coin, usd, adjusted=True)` adds the floor adjustment: #51's validation gap for BTC 0.354, ETH 0.370,
   SOL 0.459, XRP 0.531, DOGE 0.562 and LINK 0.518 bps, and the largest of those, 0.562, for the other eight coins.
   The adjustment is a carried-over number, labelled as such, not a measurement of this test.

## Reported alongside, information only

1. Each coin-size's mean cost over all 20 days with a 95% percentile bootstrap CI resampling days (10,000 draws,
   seed 68), its unfillable share, and the design and holdout means separately.
2. The curve's c0 and k per coin, and the three errors.
3. **The hour of the day.** Per coin, the cost at $10,000 in each of six four-hour UTC buckets (00–03, 04–07, …,
   20–23), the mean over all 20 days of each day's bucket mean (both sides averaged as in rule 3; a day-bucket with no
   fillable snapshot on either side has no value), with the same bootstrap CI, and the ratio of the dearest bucket's
   mean to the cheapest. No verdict attaches to it.
4. The floor-adjusted cost at $10,000 and at the reach, per coin.
5. Coin-days with fewer than 20 levels on either side, dropped snapshots and missing files.
6. The main verdicts recomputed without SOL 2025-06-01, the one coin-day seen at a new size.

## What this can't show

- Everything #51 couldn't: first-of-month days only, with no known cascade among them; a displayed book that does not
  react and no latency; nothing beyond 20 levels or inside the 0.54 s between snapshots; resting orders; Binance's
  price against Hyperliquid's.
- **The square-root form is an assumption.** The curve is judged on whether it predicts, not on whether it is the true
  shape; the table prediction is there to show what the form costs or gains against no form at all.
- **A drift and a bad fit look the same.** The split is by date, so a curve that fails on the holdout may be the
  market changing between 2025 and 2026 rather than the form failing. That is deliberate: a sizing document needs a
  curve that survives time, and this test cannot say which of the two it was.
- **Reach is a limit of the file, not of the venue.** Beyond 20 levels the book is unknown, not empty.

## Run once

`python research/costcurve.py report`, which refuses unless this document is committed and unchanged and no output
exists. The output is saved as `research/costcurve_run.txt`, the coin-day rows as `research/costcurve_days.csv`, the
hour buckets as `research/costcurve_buckets.csv`, the table as `espero/costcurve_table.py`, and the write-up as
`research/RESULTS_COSTCURVE.md`, whatever it shows. Anything looked at afterwards is labelled information only. A row
is added to `research/trials.csv` as a measurement, with no p-value: it is outside the FDR family, as #51 is.
