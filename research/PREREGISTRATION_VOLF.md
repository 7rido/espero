# Pre-registration — a HAR volatility forecast against the books' trailing variance (#66)

Committed **before** the holdout is read. This document is the contract; the result document will say whether
it was met, and nothing below is changed afterwards. A later idea takes a new number.

The split, the specification and what the design run may change were committed first, in
[EXPLORE_VOLF.md](EXPLORE_VOLF.md) (`b29f6e4`). The design run, files through 2022-12 only, is in
[volf_design_run.txt](volf_design_run.txt) (`9d3d0ad`). It changed nothing below.

## Hypothesis

Volatility clusters at the horizons different traders work on, the day, the week and the month (Corsi 2009),
and five-minute returns measure a day's variance far more precisely than one daily close does. So a HAR forecast
built from 5-minute realized variance predicts the variance of the next seven daily returns better than the
trailing 30-day sample variance of daily returns that #8 sizes with. No one is forced to trade here: the claim is
about measurement, and a pass is worth what a better position size is worth.

## Data

Read-only; nothing is fetched and nothing under `data/` is written.

- **Bars:** Binance USDⓈ-M 5-minute klines from data.binance.vision, the monthly files `research/lows.py` cached
  in `data/lows/` for #20. The 42 coins of `espero.xs.UNIVERSE`, 2020-01 through 2026-03, the archive on disk.
- **Funding and open interest, for one information readout only:** `data/settle/funding/` (#19) and `data/oi/`
  (#25, from 2021-05).
- **Excluded before looking:** incomplete days (rule 1), and a coin's origins before it has 365 training days
  (rule 5). Nothing else. The 42 coins are today's survivors; a coin delisted before 2026 is not in the list.

## Rule

1. **Days.** A UTC day is complete when it has at least 276 of its 288 five-minute bars, its 23:55 bar, the
   previous day's 23:55 bar, and a realized variance above zero. Realized variance is the sum of squared log
   returns between consecutive bars opening in the day. The daily return is the log change between the two 23:55
   closes. A window that touches an incomplete day gives no number.
2. **Origins.** Weekly: every Sunday from 2023-01-01 to 2026-03-22, 169 of them, at the close of Sunday's 23:55
   bar, as #8 decides. Monthly: every month end from 2022-12-31 to 2026-02-28, 39 of them.
3. **Target.** Weekly: the mean squared daily return of the 7 days after the origin, all complete. Monthly: the
   same over the calendar month after the origin.
4. **Benchmark.** Weekly: the sample variance, ddof 1, of the last 30 daily returns through the origin, all
   complete: #8's estimator (`espero/mf.py`, `VOL_WINDOW`). Monthly: the same over the last 90: #63's
   (`espero/sleeves.py`, `VOL_WINDOW`).
5. **HAR.** Per coin: OLS of the log target on a constant and the logs of the mean realized variance over the
   last 1, 7 and 30 days through the origin. The forecast is the exponentiated fit times Duan's smearing factor,
   the mean of the exponentiated residuals of the same fit. The fit is redone at every origin on every day t whose
   target ends on or before the origin (t + 7 ≤ origin; the monthly model uses 30-day targets and t + 30 ≤ origin),
   design days included. A coin needs 365 such days before its first forecast.
6. **Cells.** A cell is one coin at one origin. It is scored only when the target, the benchmark and the HAR
   forecast all exist and are above zero, so both forecasts are judged on the same cells. Its gap is
   QLIKE(target, benchmark) − QLIKE(target, HAR), with QLIKE(y, f) = y/f − ln(y/f) − 1. A positive gap means the
   HAR was better.
7. **The series and its t.** The weekly series is the mean gap over the coins scored at each Sunday. Its t is
   Newey-West with Bartlett weights and floor(4(n/100)^(2/9)) lags, and its p is two-sided from the normal, n
   being over 100 (`FDR_STANDARD.md`). The standard names "a daily series". This one is weekly, one point per
   Sunday, because daily origins' 7-day targets overlap and Sunday origins' do not. That is the only deviation.
8. **No trade.** Nothing is bought or sold, so there is no fill and no cost, and `espero.costs` does not apply.
   What a forecast would do to a position is an information readout below.

Code: [espero/volf.py](../espero/volf.py) and [volf.py](volf.py) at this document's commit;
`tests/test_volf.py`, 28 of 28 mutations caught.

## Criteria, all required

1. **Statistical bar:** the mean weekly gap is above zero with t ≥ 3, and #66's Benjamini-Hochberg q is below
   0.05 over every judged test in `research/trials.csv` with #66 included, a missing p counted as 1
   (`research/fdr_rescore.py`'s family). Today a new test needs |t| ≥ 2.52 for that q, so t ≥ 3 binds.
2. **Not one stretch:** the mean gap is above zero in each half of the scored Sundays in date order, the earlier
   half taking the odd one (85 and 84 if all 169 are scored).
3. **Not one coin:** among coins with at least 52 scored Sundays, more than half have a mean gap above zero.

## Power

From the design window, 98 Sundays: mean gap +0.188, sd 0.787, t 2.19, both halves positive, 29 of 29 coins in
the HAR's favour. The gap is heavy-tailed. In crash weeks both forecasts are far too low, and those weeks carry
most of its variance. If the holdout's effect and dependence match the design's, its t at 169 Sundays is about
2.9: **about an even chance of clearing 3 even if the HAR is as good as it was on the design window.** The earlier
design year was weaker (+0.094 in 2021 against +0.295 in 2022). A FAIL here is therefore weak evidence that the
HAR is no better, and the result document will say so if it happens.

## Outcomes

- **PASS:** criteria 1 to 3 hold, and the mean monthly gap against #63's 90-day variance is above zero.
- **PASS at a week; a month not shown:** criteria 1 to 3 hold, and the monthly mean gap is at or below zero. The
  month has 39 origins, so its sign is weak evidence either way; this outcome only withholds the monthly claim.
- **FAIL:** any of criteria 1 to 3 misses.
- **INCONCLUSIVE:** fewer than 100 Sundays scored, which would be a data failure; 169 are planned.

**What a pass leads to.** The HAR becomes the volatility estimator a *new* rule may use, under its own
pre-registration. It changes nothing already registered. #8's forward account keeps its 30-day estimator to
2027-05-03. #63 keeps its 90-day window, being frozen. `FORWARD_FAMILY.md`'s rules hold. A pass reads "the HAR
beats the estimator #8 uses", not "the 5-minute data helps": only information readout (c) speaks to that, and it
decides nothing. **A FAIL** closes the HAR for sizing on these coins at these horizons. A variant takes a new number.

## Information only

Printed beside the verdict by `volf.py --holdout`, never a claim:

- (a) the next day: every day's origin, the next day's squared return, #8's 30-day variance against a HAR fitted
  on 1-day targets;
- (b) the weekly MSE on the variance, the benchmark's over the HAR's;
- (c) a calibrated trailing regression, the log target on the log of the 30-day variance, fitted like the HAR:
  against the HAR, and #8's variance against it;
- (d) the HAR with two more inputs, the log of the last 7 days' mean daily sum of |funding rate| and the absolute
  7-day log change in open interest, against the HAR. Scored where both load, on the coins and days that have them;
  coverage is printed. On the design window it reached one coin;
- (e) sizing: for each forecast, the mean |log| of realized over target volatility of a position scaled by it,
  the share of weeks above twice the target, and the mean week-to-week change in the log of the scale;
- (f) the weekly gap by year of origin, and BTC and ETH against the other coins;
- (g) the mean QLIKE of each forecast;
- (h) the coins whose mean gap is at or below zero.

## Robustness, information only

Deflated Sharpe, PBO by CSCV, purged k-fold, half-life and capacity do not apply: there is no strategy and one
configuration. Refitting at every origin on targets that end by it is the purge. Readout (e)'s week-to-week
change in scale stands in for turnover.

## Transparency — what was seen before this

- The design run's numbers above and in `volf_design_run.txt`, on files through 2022-12 only.
- These klines were read by #20, #24's backtest and #25 for returns around new lows, breakdowns and open interest.
  No forecast error on any holdout day has been computed.
- The holdout overlaps #49's sealed window (entries 2025-01 → 2026-09) by date. #49 seals the relation between
  Binance's book depth and the next day's return. Nothing here opens a book file or relates anything to depth, so
  #49 stays sealed.
- The author knows the HAR literature, which finds HAR beating trailing estimators in most markets, and the
  2023–2026 market in general. The idea is item #20 of the account holder's plan of 2026-11-02.
- The holdout stops at 2026-03-31, where the archive on disk stops. 2026-04 onward was not fetched.
