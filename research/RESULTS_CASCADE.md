# Results — open interest as a next-day cascade forecast, beyond volatility (#72)

**Verdict: FAIL** on criterion 1 and criterion 2. On 991 holdout origins from 2023-01-01 to 2026-03-30, a logistic
model reading open interest, funding and the long-short ratio beside volatility forecast tomorrow's cascade no better
than volatility alone: mean daily log-loss gap **+0.00070**, Newey-West t **0.49**, p 0.62, BH q 1 over 36 judged
tests; the first half of the origins was negative (−0.00119) and the second positive (+0.00258); 28 of 42 coins had a
positive mean gap. Both models forecast the cascade far better than its base rate, which decides nothing here.

Spec: [PREREGISTRATION_CASCADE.md](PREREGISTRATION_CASCADE.md) (`3f0965e`, stamped on OpenTimestamps), after
[EXPLORE_CASCADE.md](EXPLORE_CASCADE.md) (`10c8879`) and the design run [cascade_design_run.txt](cascade_design_run.txt).
One holdout run; output in [cascade_run.txt](cascade_run.txt), the daily series in [cascade_series.csv](cascade_series.csv),
every scored cell in [cascade_cells.csv.gz](cascade_cells.csv.gz). The result is what the design window predicted: the
pre-registration said the author expected a FAIL with the gap near zero, and the gap was +0.0007.

## Data

42 coins. **The pre-registration said ARB, SEI, TIA and WLD have no bars and drop out; that was the design window.**
All four list after 2022-12 and have bars, open interest and funding in the holdout, so the registered rule included
them: 852 to 1,074 targets each. Information only, computed afterwards from the scored cells: on the 38 coins
the pre-registration named, the gap is +0.00058 over 991 origins, Newey-West t 0.41, halves -0.00137 / +0.00253, 24 of 38 coins. The verdict is the same. 80,286 rows with a target over both windows, 3,593 cascade days (4.48%; the design
window's 4.65% kept k at 1.25). Squeeze days 3.90%.

**194 of the 1,185 holdout origins have no `FULL` forecast on any coin**, about five a month: the open-interest
archive on disk (#25's fetch) lacks the last and first days of most months and a few others, which empties `oi1` and
`oi7` for every coin on those origins. `VOL` needs no open interest and forecast 1,185 origins. The registered rule
scores a cell only where both models forecast, so the verdict stands on 991 origins and 36,007 cells with 1,572
cascades, well above the 200 that INCONCLUSIVE needed. The gap series on the 991 is what the criteria read.

## Criteria

| # | criterion | required | actual | met |
|---|---|---|---|---|
| 1 | statistical bar | mean gap > 0, t ≥ 3, q < 0.05 | +0.00070, t 0.49, q 1 | **no** |
| 2 | not one stretch | both halves > 0 | −0.00119 / +0.00258 | **no** |
| 3 | not one coin | more than half of 42 coins > 0 | 28 of 42 | yes |

## What the tables say, information only

1. **Volatility forecasts the cascade; positioning adds nothing measurable.** `VOL` against the base rate: +0.00828,
   t 4.36, 42 of 42 coins. `FULL` against the base rate: +0.00964, t 4.39, 42 of 42. The two are the same forecast
   with different names: `FULL`'s standardized coefficients at the last fit put +0.47 and −0.62 on the one-day and
   30-day variance terms and +0.03 to +0.12 on open interest, funding and the ratio.
2. **The fuller model was calibrated and lifted, and so was the plain one.** `FULL`'s deciles ran from 0.6% observed
   at the bottom to 11.1% at the top against a 4.4% base rate, a 2.54× lift, with the forecast and the observed rate
   within a point in every decile. `VOL`'s top decile held 12.5% and its bottom 0.6%. A risk policy that wants a
   cascade probability already has one in the volatility terms.
3. **The gap's sign turned with time.** 2023 −0.0051, 2024 +0.0030, 2025 +0.0034, 2026 +0.0039 (75 origins). The
   design window, 2022, was −0.0101. With up to 80,000 training rows the eleven-feature fit stopped hurting; it did
   not start helping at a size the t can see. BTC and ETH +0.0004, the rest +0.0007.
4. **The squeeze day looks the same:** +0.00038, t 0.51, 24 of 42 coins.
5. **The projection from the daily sd** (0.042) says a t of 3 at 1,185 origins needs a mean gap of about +0.0037,
   five times what was found.

## What this changes

Nothing running. The readout is closed: open interest, funding and the long-short ratio, read once a day at the
close, do not forecast tomorrow's cascade beyond what the coin's own realized volatility forecasts, on Binance's
USDⓈ-M perpetuals from 2023 to March 2026. A risk document that wants a next-day cascade probability may cite the
volatility model's information readout, under its own pre-registration; it may not cite this test as evidence for
positioning. A variant at another horizon, with intraday positioning, or on Hyperliquid's own open interest (#65's
feed, where every account's leverage is published) takes a new number.

## What this can't show

- **Daily is slow.** Open interest was read once a day; a cascade builds and clears in hours. #65 reads it at five
  minutes on another venue and is judged after 2027-03-31.
- **Binance's metrics are a sample.** The long-short ratio counts accounts, not dollars; the taker and top-trader
  ratios the archive mostly lacks were dropped before the design run, as EXPLORE_CASCADE.md records.
- **The archive's gaps took 16% of the origins** from the registered comparison, as above. A refetch of the
  missing days would let a later test score them; it would not change the sign of a gap this close to zero.
