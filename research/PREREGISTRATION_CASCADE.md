# Pre-registration — open interest as a next-day cascade forecast, beyond volatility (#72)

Committed **before the holdout is read**. This document is the contract; the result document will say whether it
was met, and nothing below is changed afterwards. A later idea takes a new number.

The split, the event, the two models and what the design run may change were committed first, in
[EXPLORE_CASCADE.md](EXPLORE_CASCADE.md) (`10c8879`). The design run, files through 2022-12 only, is in
[cascade_design_run.txt](cascade_design_run.txt). **It changed nothing below**: the design cascade rate was 4.65%,
inside the 2 to 8% band, so k stays 1.25.

## Hypothesis

A liquidation cascade needs leverage to liquidate. When open interest has grown against recent turnover, when funding
has been paying one side, and when more accounts sit long than short, the next sharp move has more forced sellers
behind it, so tomorrow is more likely to hold an hour that falls as much as the coin's typical whole day. Volatility
clusters, so a volatility model already forecasts cascades; the claim is that positioning adds to it. No one is forced
to trade on the forecast itself: a pass is worth what an earlier size-down is worth, a risk input, not an entry.

## Data

Read-only; nothing is fetched and nothing under `data/` is written. Exactly as EXPLORE_CASCADE.md fixed it:

- **Bars:** Binance USDⓈ-M 5-minute klines in `data/lows/`, `espero.xs.UNIVERSE`'s 42 coins, 2020-01 through
  2026-03. ARB, SEI, TIA and WLD have no bars in the archive on disk and drop out, as the design run showed.
- **Open interest and the long-short ratio:** `data/oi/<symbol>/<day>.csv.gz`, each day's last row, days the
  archive lacks left as gaps.
- **Funding:** `data/settle/funding/<symbol>.json`, every settlement's signed rate.
- **Excluded before looking:** incomplete days, any origin missing a feature, and every origin before the first fit
  with 5,000 pooled training rows.

## Rule

Code: [espero/cascade.py](../espero/cascade.py) and [cascade.py](cascade.py) at this document's commit;
`tests/test_cascade.py`, 28 of 30 mutations caught, two equivalent.

1. **Days, the hour's fall, the daily sigma, the event, the features, the two models, the refitting and the
   scoring** are EXPLORE_CASCADE.md's items 1 to 8, unchanged: the event is `fall(t+1) ≤ −1.25 × sigma_d(t)`, the
   models are `VOL` (constant, `d1`, `d7`, `d30`) and `FULL` (`VOL` plus `oi1`, `oi7`, `oivol`, `f1`, `f7`,
   `fa7`, `ls`, `m7`), both ridged logistic regressions pooled across coins, refitted at every month end on rows
   whose target day is on or before it, forecasting the following month.
2. **Origins.** The holdout's origins are 2023-01-01 to 2026-03-30, targets through 2026-03-31. A holdout origin's
   models are fitted on every earlier row, design rows included, whose target is known by the fit date.
3. **Cells and the series.** A cell is one coin at one origin, scored when both models forecast and the target
   exists. Its gap is `logloss(VOL) − logloss(FULL)`, positive when `FULL` was better. The series is the mean gap
   over coins at each origin. Its t is Newey-West with Bartlett weights and `espero.volf.nw_lags` lags, its p
   two-sided from the normal, the origins being far more than 100 (`FDR_STANDARD.md`).
4. **No trade.** Nothing is bought or sold, so there is no fill and no cost, and `espero.costs` does not apply.

## Criteria, all required

1. **Statistical bar:** the mean daily gap is above zero with t ≥ 3, and #72's Benjamini-Hochberg q is below 0.05
   over every judged test in `research/trials.csv` with #72 included, a missing p counted as 1
   (`research/fdr_rescore.py`'s family).
2. **Not one stretch:** the mean gap is above zero in each half of the scored origins in date order, the earlier
   half taking the odd one.
3. **Not one coin:** among coins with at least 365 scored cells, more than half have a mean gap above zero.

## Power

From the design window, 128 origins from 2022-08-03 to 2022-12-30 (the first fit with 5,000 rows fell on
2022-07-31): mean gap **−0.0101**, daily sd 0.0800, Newey-West t **−1.42**, both halves negative. `FULL` was worse
than `VOL`, and its calibration by decile was not monotone, which is what an eleven-feature model fitted on 5,000
rows and about 230 events looks like. If the holdout's effect and dependence match the design's, its t over about
1,185 origins is about −4.3: a **FAIL in the registered direction**. For a PASS the holdout mean gap must reach about
+0.0070 at that sd. The holdout's fits train on up to ten times the design's rows, so the overfitting should shrink,
but nothing in the design says the sign turns. **The author expects a FAIL**, with the gap near zero, and the test is
run because the account holder asked for the readout and a FAIL closes it properly: #66's readout (d) already found
funding and open interest adding nothing to a variance forecast. Information readout (a) on the design window, `VOL`
against the base rate, was +0.0114 with t 3.02 over 698 origins, 36 of 36 coins: volatility alone forecasts the
cascade, which decides nothing here.

## Outcomes

- **PASS:** criteria 1 to 3 hold. The `FULL` probability may then be an input of a risk document under its own
  pre-registration; it changes nothing already registered and no running book.
- **FAIL:** any criterion misses. Open interest, funding and the long-short ratio, read daily, add no next-day
  cascade skill beyond volatility on these coins; the readout is closed. A variant, at another horizon, with other
  features or on another venue, takes a new number.
- **INCONCLUSIVE:** fewer than 200 cascade days among the scored holdout cells, which would be a data failure.

## Information only

Printed beside the verdict by `cascade.py --holdout`, never a claim: (a) `VOL` against the base rate and (b) `FULL`
against it; (c) `FULL`'s calibration by decile; (d) the lift, the top decile's observed rate over the scored base
rate, and `VOL`'s; (e) each model's standardized coefficients at the last fit; (f) the gap by year; (g) BTC and ETH
against the rest; (h) the squeeze day, the same two models on the rise; (i) the projection of the t from the daily sd.

## Robustness, information only

Deflated Sharpe, PBO by CSCV, half-life, turnover and capacity do not apply: there is no strategy and one
configuration, with k's one permitted change disclosed above and not taken. Fitting at every month end on targets
known by then is the purge.

## Transparency — what was seen before this

- The design run's numbers above and in `cascade_design_run.txt`, on files through 2022-12 only, and the four-coin
  event rates and ETH's feature coverage disclosed in EXPLORE_CASCADE.md.
- These klines were read by #20, #24's backtest, #25 and #66; the open-interest files by #25 and #66. No forecast of a
  next-day cascade has been scored on any holdout day.
- The holdout overlaps #49's sealed window (entries 2025-01 → 2026-09) by date. Nothing here opens a book file, so #49
  stays sealed.
- The holdout stops at 2026-03-31, where the archive on disk stops. 2026-04 onward was not fetched.
