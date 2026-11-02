# Result — a HAR volatility forecast against the books' trailing variance (#66)

**Verdict: PASS.** On 169 Sundays from 2023-01-01 to 2026-03-22, a HAR forecast built from 5-minute bars
predicted the next week's variance of daily returns better than the 30-day trailing variance #8 sizes with: t
3.09, Benjamini-Hochberg q 0.0097 over the 34 judged tests, both halves positive, all 42 coins in its favour. The
month against #63's 90-day variance was positive too (t 2.33), so the outcome is the full PASS, not the pass at a
week only.

What the pass says, and what it does not:

- **It beats the estimator #8 uses.** It does not show that the 5-minute data does the work. Information readout
  (c) puts three quarters of the gain in calibration alone: a regression of the target on #8's own 30-day
  variance, fitted the same way, takes +0.112 of the +0.150 gap, and the HAR's intraday inputs add +0.038
  (t 2.11). That readout decides nothing.
- **It changes no running book.** #8's forward account keeps its 30-day estimator to 2027-05-03, and #63 keeps its
  90-day window, being frozen. A new rule may size with the HAR under its own pre-registration.
- **It cleared the bar narrowly, as its power said it would be close.** The design window projected t about 2.9 at
  169 Sundays; the holdout gave 3.09.

Spec: [PREREGISTRATION_VOLF.md](PREREGISTRATION_VOLF.md) (`dd43d19`, stamped on OpenTimestamps), after the split
in [EXPLORE_VOLF.md](EXPLORE_VOLF.md) (`b29f6e4`) and the design run (`9d3d0ad`). Code: `espero/volf.py` and
[volf.py](volf.py), unchanged since `dd43d19`. One run on 2026-11-02, 30 seconds, at `dd43d19`; output
[volf_run.txt](volf_run.txt); the weekly series [volf_series.csv](volf_series.csv), from which the t reproduces
to four decimals.

## Criteria

| criterion | needs | result | met |
|---|---|---|---|
| 1. mean weekly gap, QLIKE(#8's 30-day) − QLIKE(HAR) | above 0 with t ≥ 3 | +0.150, t 3.09 (Newey-West, 4 lags), p 0.0020 | yes |
| 1. Benjamini-Hochberg q, every judged test with #66 | below 0.05 | 0.0097 over 34 | yes |
| 2. each half of the Sundays | above 0 | +0.182 (85 Sundays), +0.118 (84) | yes |
| 3. coins with 52+ scored Sundays favouring the HAR | more than half | 42 of 42 | yes |
| the month, against #63's 90-day variance | above 0 for PASS | +0.109, t 2.33, 39 month ends | PASS |

The q was computed by `volf.py` from `trials.csv` as committed at `dd43d19`, plus #66's p.
`research/fdr_rescore.py`, rerun with #66's row added, gives the same 0.0097 ("q, all judged").

## The numbers

- **Cells:** 6,612. Every Sunday had 36 to 42 coins. The six listed on Binance's futures after mid-2022 (OP, INJ,
  ARB, SEI, TIA and WLD) joined once they had a year of training days.
- **Mean QLIKE:** 0.629 for #8's 30-day variance, 0.481 for the HAR, 24% lower.
- **By year:** 2023 +0.149, 2024 +0.230, 2025 +0.080, 2026's first quarter +0.109. Positive in every year.
- **By tier:** BTC and ETH +0.145, the other 40 coins +0.149.

## Information only

Printed beside the verdict as registered; none of it is a claim.

- **(a) The next day:** +0.125, t 4.36 over 1,186 days.
- **(b) MSE on the variance:** the trailing estimator's is 1.14 times the HAR's.
- **(c) Calibration:** #8's variance against a calibrated version of itself +0.112 (t 2.04); the calibrated
  version against the HAR +0.038 (t 2.11). The two add to the primary gap exactly, cell by cell, since all three
  forecasts cover the same 6,612 cells. Most of what the HAR wins, a regression on the trailing variance alone
  also wins. Why the raw trailing variance loses that much was not measured.
- **(d) Funding and open interest:** adding them to the HAR loses −0.017 (t −1.22) over 4,727 cells on 42 coins.
  They do not help.
- **(e) Sizing:** a position scaled by the HAR runs above twice its volatility target in 2.7% of weeks, against
  4.7% with #8's variance. Its typical miss is slightly larger (mean |log| of realized over target 0.403 against
  0.396), and its scale moves more week to week (0.137 against 0.114 in log), about a fifth more turnover.
- **(h)** No coin favours the trailing variance.

## A side effect on the family

Adding #66's p lifts the Benjamini-Hochberg cutoff over all judged tests from p ≤ 0.00043 (6 discoveries) to
p ≤ 0.0111 (8): #66, and #17, whose q falls under 0.05. #17 failed with the wrong sign and |t| 2.54, under 3, so
its verdict stands (`FDR_STANDARD.md`: missing either bar is a fail). The bar for the next test moves from |t| 2.52
to 2.49; t ≥ 3 still binds.

## What it leads to

- A rule that sizes by volatility may use the HAR, under its own pre-registration, judged on days after it is
  committed.
- Readouts (c) and (e) are information. Sizing with a calibrated trailing variance, or with the HAR under a
  turnover buffer, would each need a new number.
- Nothing already registered changes: #8, #63 and the forward tests keep their estimators.
