# Exploration — #72's design window: does open interest forecast tomorrow's cascade beyond volatility?

**Not a test.** This fixes, before anything is computed, the split between #72's design window and its holdout,
the event, the two models compared, the specification tried on the design window, and the one thing the design run
may change. #72's pre-registration, `PREREGISTRATION_CASCADE.md`, follows the design run and is committed before the
holdout is read. The question came from the account holder's decision of 2026-11-02 to register a cascade-risk
readout on Binance USDⓈ-M price and open interest, after the parent session reported that the repo's continuous
liquidation history (COIN-M, 2023-06 to 2024-10) and its open-interest history (USDⓈ-M, 2021-01 to 2026-03) are
different contracts and do not join.

Script: [cascade.py](cascade.py), rule [espero/cascade.py](../espero/cascade.py). This document was written to disk
and committed before the script's first run.

## The question

At the close of each UTC day, does a model that reads open interest, funding and the published long-short ratios
forecast whether the next day holds a cascade, a one-hour fall as large as the coin's typical whole day, better
than a model that reads volatility alone? A pass is worth what an earlier size-down is worth: a risk readout, not an
entry. It is in #25's and #65's territory (open interest beside the price) and overlaps neither: #25 conditions a
breakdown's bounce on the hour's open-interest drop, #65 reads a 5-minute fall's open interest on Hyperliquid, and
neither forecasts the next day.

## The data

Read-only; nothing is fetched and nothing under `data/` is written.

- **Bars:** Binance USDⓈ-M 5-minute klines, the monthly files in `data/lows/` (#20, #66): the 42 coins of
  `espero.xs.UNIVERSE`, 2020-01 through 2026-03, the archive on disk.
- **Open interest and positioning:** `data/oi/<symbol>/<day>.csv.gz`, Binance's 5-minute `metrics` archive (#25),
  2021-01 to 2026-03-30: `sum_open_interest` (coins) and `count_long_short_ratio`. Each day's **last row** is used,
  so the origin reads what was published by the close. Duplicated rows in a file are dropped. A day the archive
  lacks (a `.none` marker from #25's fetch) is a gap: for most coins the archive on disk begins between 2021-01 and
  2021-12, not at the metrics' first day.
- **Funding:** `data/settle/funding/<symbol>.json` (#19), every settlement with its signed rate.
- **Excluded before looking:** incomplete days (#66's rule 1), any origin missing a feature, and every origin before
  the first fit with 5,000 pooled training rows. Nothing else. The 42 coins are today's survivors; a coin delisted before 2026 is not
  in the list.

## The split, fixed now

- **Design:** origins through 2022-12-30, targets through 2022-12-31. `cascade.py --design` refuses to open a kline
  file after 2022-12 (`espero.volf.readable`), skips every open-interest day after 2022-12-31 without opening it, and
  drops every funding settlement after 2022-12-31 on load. The first fit needs 5,000 pooled rows with every feature
  and a target, which the open-interest archive on disk allows from some month end in 2022, so design forecasts
  cover the rest of 2022.
- **Holdout:** origins 2023-01-01 to 2026-03-30, targets through 2026-03-31, the last day of the archive on disk.
  Read once by `cascade.py --holdout`, which refuses unless the pre-registration is committed unchanged and no
  holdout output exists.
- A holdout origin's model is fitted on every earlier row, design rows included, but only on rows whose target day is
  on or before the fit date.

## The specification tried on the design window

1. **Days.** As #66: a UTC day is complete with at least 276 of its 288 bars, its 23:55 bar, the previous day's
   23:55 bar and a realized variance above zero. Realized variance is the sum of squared log returns between
   consecutive bars opening in the day (`espero.volf.daily`).
2. **The one-hour fall.** Within a day, over every run of 13 bars whose first and last open exactly 3,600 s apart,
   the log change of the close from the first to the last. The day's `fall` is the most negative of these and its
   `rise` the most positive. A day whose bars allow no such window has neither.
3. **The daily sigma.** At origin t, `sigma_d = sqrt(mean realized variance over the last 30 complete days through
   t)`: the coin's typical whole-day move, from its 5-minute bars.
4. **The event.** Day t+1 is a **cascade day** when `fall(t+1) ≤ −k × sigma_d(t)`, an hour that fell as much as
   k typical days. k = 1.25. The **squeeze day**, `rise(t+1) ≥ k × sigma_d(t)`, is an information readout only. The
   event is in the coin's own units, so a high-vol coin is not a cascade every day and a low-vol one never. An hourly
   sigma (the day's variance spread evenly over 24 hours) was considered and dropped before this commit: a 4-sigma
   hour on that scale happened on 12 to 15% of days, because intraday volatility clusters, which is no cascade.
5. **Features at origin t**, eleven, every one known at the 23:55 close. A non-positive open interest, ratio or
   volume gives no value, never a log of zero:
   - volatility, the baseline's: `d1`, `d7`, `d30`, the log mean realized variance over the last 1, 7 and 30 days
     (#66's HAR terms);
   - open interest: `oi1 = ln(OI_t / OI_{t−1})`, `oi7 = ln(OI_t / OI_{t−7})`, `oivol = ln(OI_t / mean base volume
     over the last 30 days)`, open interest relative to turnover;
   - funding: `f1` the last settlement's signed rate on day t, `f7` the sum of signed rates over days t−6..t,
     `fa7 = ln(sum of |rate| over days t−6..t + 1e−6)`;
   - positioning: `ls`, the log of the day's last `count_long_short_ratio`. The taker and top-trader ratios were
     considered and dropped before this commit: on ETH's design window the archive's last row lacks them on 32% and
     80% of days, and a row needs every feature;
   - the move in: `m7`, the log close change over days t−7..t.
6. **Two models, both logistic regressions pooled across coins.** `VOL` on the constant and `d1, d7, d30`. `FULL`
   on `VOL`'s terms and the eight others. Features are standardized on the training rows; the fit is iteratively
   reweighted least squares with a ridge of 0.01 per observation on every standardized coefficient, none on the
   constant, and at most 50 iterations. A third model, `BASE`, is the training rows' event rate, for the lift readout.
7. **Refitting.** Both models are refitted at every month end on every row whose target day is on or before that
   month end, and forecast every origin of the following month. A fit needs 5,000 pooled rows (about four months of
   42 coins); before the first such month end nothing is forecast.
8. **Scoring.** A cell is one coin at one origin, scored when both models forecast and the target exists. Its loss is
   the log loss, with the probability clipped to [10⁻⁴, 1 − 10⁻⁴]. Its gap is `loss(VOL) − loss(FULL)`: positive
   when the fuller model was better. The series is the mean gap over the coins scored at each origin; its t is
   Newey-West with Bartlett weights and `espero.volf.nw_lags` lags.

## What the design run may change

- **k only**, and only if the design window's cascade rate across all rows with a target falls outside 2% to 8%:
  then 1.0 if below, 1.5 if above, disclosed in the pre-registration. Nothing else: not the features, not
  the ridge, not the window, not the models. A second idea takes a new number.

## What has been seen before this

- #25's result: a breakdown's bounce is a little larger when open interest fell in its hour (t 2.36, fading; FAIL).
  #65's exploration on Hyperliquid at 5 minutes: a fall with open interest falling tends to come back, one with open
  interest rising to go on. #66's readout (d): funding and open interest added nothing to the HAR variance forecast
  (−0.017 QLIKE). #18, #21 and #26 on liquidations. None computed a next-day cascade probability on these klines, and
  no forecast error of that kind exists on any day.
- These klines were read by #20, #24's backtest, #25 and #66. The open-interest files were read by #25 for the hour
  around a breakdown and by #66 for a 7-day change.
- The holdout overlaps #49's sealed window (entries 2025-01 → 2026-09) by date. #49 seals the relation between
  Binance's book depth and the next day's return. Nothing here opens a book file, so #49 stays sealed.
- **Seen on 2026-11-03, before this commit, on the design window only:** the event rate on BTC, ETH, DOGE and ADA
  under the hourly sigma at k = 4, 5, 6 and 8 (15/9/6/2.5%, 15/9/6/3%, 14/9/6/2%, 12/7/5/3%) and under the daily
  sigma at k = 0.5, 0.75, 1, 1.25 and 1.5 (39/18/9/6/3%, 40/17/9/6/4%, 37/17/9/5/3%, 38/16/8/5/3%); ETH's design rows
  with their features, which showed the taker and top-trader ratios mostly missing and open interest on disk from
  2021-12; and one ETH row's feature values. No model was fitted and no forecast was scored.
- The author expects: volatility alone forecasts cascades well (clustering), the fuller model adds a little through
  `oi7` and `oivol` (crowded books cascade), and the t on the gap is uncertain because cascades are rare.
