# Exploration — #66's design window: a HAR volatility forecast against the books' trailing variance

**Not a test.** This fixes, before anything is computed, the split between #66's design window and its holdout,
the specification tried on the design window, and what the design run may and may not change. #66's
pre-registration, `PREREGISTRATION_VOLF.md`, follows the design run and is committed before the holdout is read.
The idea is item #20 in the account holder's plan of 2026-11-02 ("HAR-RV on realized volatility from 5-min
bars ... beats trailing realized volatility on out-of-sample QLIKE loss"), taken as #66 the same day.

Script: [volf.py](volf.py), rule [espero/volf.py](../espero/volf.py). This section was written to disk and
committed before the script's first run.

## The question

Does a HAR forecast built from 5-minute realized variance predict next week's variance of daily returns better
than the trailing 30-day variance #8 sizes with? And next month's better than #63's trailing 90-day variance?
Both books size by dividing a volatility target by a trailing standard deviation of daily closes, so a better
forecast of the coming week's or month's variance is a better position size.

## The data

Read-only; nothing is fetched and nothing under `data/` is written.

- **Bars:** Binance USDⓈ-M 5-minute klines from data.binance.vision, the monthly files `research/lows.py`
  cached in `data/lows/` for #20: 42 coins (`espero.xs.UNIVERSE`), 2020-01 through 2026-03.
- **Funding:** `data/settle/funding/<symbol>.json`, every settlement since 2020 (`research/settle.py`, #19).
- **Open interest:** `data/oi/<symbol>/<day>.csv.gz`, Binance's 5-minute metrics from 2021-05 (`research/oi.py`, #25).

## The split, fixed now

- **Design:** the bars of 2020-01 through 2022-12. Weekly origins 2021-01-03 → 2022-12-18, month-end origins
  2020-12-31 → 2022-11-30, daily origins 2020-12-31 → 2022-12-30. `volf.py --design` refuses to open a kline
  file after 2022-12, skips every open-interest day after 2022-12-31 without opening it, and drops every funding
  settlement after 2022-12-31 on load, since a coin's funding history is one file.
- **Holdout:** weekly origins 2023-01-01 → 2026-03-22 (169 Sundays), month-end origins 2022-12-31 → 2026-02-28
  (39), targets through 2026-03-31, the last month of the archive on disk. 2026-04 onward is not fetched.
  Read once by `volf.py --holdout`, which refuses unless the pre-registration is committed unchanged and no
  holdout output exists.
- A holdout origin's model is fitted on every earlier day, design days included, but only on targets that end
  on or before the origin.

## What has been seen before this

- These klines were read by #20, #24's backtest and #25 for returns around new lows, breakdowns and open
  interest. No test here has forecast volatility on them, and no forecast error has been computed on any day.
- The holdout overlaps #49's sealed window (entries 2025-01 → 2026-09) by date. #49 seals the relation between
  Binance's book depth and the next day's return. Nothing here opens a book file or relates anything to depth,
  so #49 stays sealed.
- The author knows the HAR literature (Corsi 2009; Patton 2011 on QLIKE's robustness to a noisy target), which
  finds HAR beating trailing estimators in most markets, and the 2023–2026 crypto market in general.
- The 42 coins are today's survivors. A coin delisted before 2026 is not in the list.

## The specification tried on the design window

1. **Days.** A UTC day is complete with at least 276 of its 288 bars, its 23:55 bar, the previous day's 23:55
   bar, and a realized variance above zero. Realized variance is the sum of squared log returns between
   consecutive bars opening in the day; the daily return is the log change between the two 23:55 closes. A
   window that touches an incomplete day gives no number.
2. **Target.** The mean squared daily return over the 7 days after a Sunday origin, #8's holding week. For the
   monthly comparison, over the calendar month after a month-end origin. The target is in daily returns, the
   books' own unit, so the 5-minute data cannot win by measuring a different quantity.
3. **Benchmarks.** The sample variance (ddof 1) of the last 30 daily returns (#8, `espero/mf.py`) and of the last
   90 (#63, `espero/sleeves.py`): the books' estimators.
4. **HAR.** Per coin, OLS of the log target on the logs of the mean realized variance over the last 1, 7 and 30
   days. Duan's smearing factor, the mean of the exponentiated residuals, undoes the log's bias. Refitted at
   every origin on every day whose target ends on or before it, with at least 365 such days. The monthly model
   is fitted on 30-day targets.
5. **Score.** QLIKE. Per cell, QLIKE(benchmark) − QLIKE(HAR), averaged over the coins at each origin. A Newey-West
   t over the origins with `FDR_STANDARD.md`'s lag count, on one point per Sunday: daily origins' 7-day targets
   overlap, Sunday origins' do not.
6. **Information readouts tried:** the next day; MSE; a calibrated trailing regression (the log target on the
   log of the 30-day variance); HAR with the last week's funding and open-interest change added; what each
   forecast does to a volatility-targeted position; by year; BTC and ETH against the rest.

## What the design run may change, and what it may not

- **May change:** the complete-day threshold, the minimum training rows, the log form and the smearing, the
  information readouts, and bugs. Whatever changes is named in the pre-registration as chosen on the design window.
- **May not change:** the holdout's dates; the two benchmarks; the target in daily returns; QLIKE; the Sunday
  clock and the 7-day horizon; the primary statistic and its bar (t ≥ 3 and Benjamini-Hochberg q < 0.05 over
  every judged test, `FDR_STANDARD.md`); the monthly comparison against #63's 90 days.
- The design run estimates power for the pre-registration. It cannot pass or fail #66.

## The design run

Run on 2026-11-02 after `b29f6e4`, in ten seconds; output [volf_design_run.txt](volf_design_run.txt). **Nothing in
the specification changed after it.** No bug was found, and the day rule, the training minimum, the log form and
the smearing stand as written above.

- **Coins:** 38 of 42 have bars before 2023 (ARB, SEI, TIA and WLD list later). Most coins have 99% of their
  calendar days complete; ICP has 490 of 600.
- **Weekly:** 98 Sundays with a forecast (2021-02 → 2022-12), 2,551 cells. Mean QLIKE 0.700 for #8's 30-day
  variance and 0.480 for the HAR. Mean gap +0.188, sd 0.787, t 2.19 (Newey-West, 3 lags). Halves +0.089 and
  +0.286. All 29 coins with a year of cells favour the HAR.
- **Monthly:** 22 month ends, mean gap +0.036, t 0.71.
- **Information:** the next day, t 3.15 over 700 origins. MSE ratio 1.17 in the HAR's favour. A calibrated
  trailing regression closes part of the gap (#8's variance against it +0.122, it against the HAR +0.066, t 2.88),
  so the gain is part calibration and part the 5-minute data. HAR with funding and open interest reached 35 cells
  on one coin, because open interest starts in late 2021 for most coins and the model needs a year of it.
  Sizing with the HAR halves the share of weeks a position runs above twice its volatility target (6.0% → 3.3%).
- **Power.** The gap is heavy-tailed: crash weeks, when both forecasts are far too low, carry most of its
  variance. If the holdout's effect and dependence match the design's, its t at 169 Sundays is about 2.9, about
  an even chance of clearing 3. The earlier design year was weaker (+0.094 in 2021 against +0.295 in 2022). The
  bar stays where `FDR_STANDARD.md` puts it: a new test clears q < 0.05 over the 33 judged tests at |t| ≥ 2.52
  today, so t ≥ 3 binds.
