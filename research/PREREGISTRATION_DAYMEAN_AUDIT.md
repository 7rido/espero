# Pre-registration — audit of the day-mean convention (#44)

Committed **before any trade-weighted number of the studies below is computed**. An audit of
published results: nothing trades, and no frozen verdict is rewritten. The forty-fifth test in
this repo.

## Why

Since #18, the event studies here report "each UTC day's mean is one observation" as the point
estimate itself, not only as a way to cluster the standard error. #43 showed what that can do. #20's
bounce at 12 h netted +21.8 bps as a day-mean but **−9.6 bps trade-weighted**, because 50 trades on
quiet days carried the whole day's weight.

That weighting is also not causal: a trade's weight depends on how many other events happen later
the same day. A book cannot hold it.

**The question:** for every published headline built on day-means, does the conclusion survive the
estimator a book actually earns?

## The two estimators

For a headline over events i, with value x_i and day d(i):

- **Day-mean, as published.** The mean over days of each day's mean, with t from those day means
  (`liq.clustered`). The audit must **reproduce each published number** before going further. A
  headline that does not reproduce is reported as such and is not audited.
- **Trade-weighted**, with the standard error clustered by day.
  - mean m = Σx_i / n.
  - se = √(G/(G−1)) · √(Σ_d (Σ_{i∈d} (x_i − m))²) / n, with G days.
  - t = m / se.
- **For a difference D**, forced against organic, the trade-weighted version runs on the same events
  as the published `day_diff`: usable events, ranked within each day, on days that have both
  groups. It is the OLS slope of y on a forced dummy, with day-clustered standard errors.

**Concentration, information only.** The share of the day-mean's total weight carried by events on
days with ≤ 3 events, and the ratio trade-weighted ÷ day-mean.

## The headlines audited — each with its own published code path

| # | study | headline | events | its own bar |
|---|---|---|---|---|
| 1 | #18 | leg (a): long forced down-breaks, 1 h | `liq_events.csv`, `liq.leg(ev, −1, "forced")` | > 18 bps, t > 2 |
| 2 | #18 | D: forced − organic, 1 h | `liq.day_diff(ev)` | D < 0, t ≤ −3 |
| 3 | #19 | g: settlement excess | `settle.excess(settle_events)["g"]` | > 0, t ≥ 3 |
| 4 | #20 | new-low bounce, 1 h | `lows_events.csv.gz`, down, r60 | > 0, t ≥ 3; and > 18 bps, t > 2 |
| 5 | #21 | long leg, raw 24 h from the next hour's open | `liqspike_events.csv`, longs, expm1(r24_open) | > 18 bps, t > 2 |
| 6 | #25 | forced leg, 1 h | `oi_events.csv.gz`, usable, tag(oi_drop) = forced, r60 | > 18 bps, t > 2 |
| 7 | #25 | D (oi_drop), 1 h | `liq.day_diff(ev, "oi_drop", "r60")` | D > 0, t ≥ 3 |
| 8 | #26 | leg (a), 1 h | `liq2_events.csv.gz`, `liq.leg(ev, −1, "forced")` | > 18 bps, t > 2 |
| 9 | #26 | D, 1 h | `liq.day_diff(ev)` | D < 0, t ≤ −3 |
| 10 | #28 | the push, *with* era, trading days | `levetf_days.csv.gz`, `levetf.sample(df, "with", "trading")`, y | > 0, t ≥ 3 |
| 11 | #29's basis | post-close reversal, 15 min | the same sample, post15 | < 0 (it is the reversal) |
| 12 | #30 | filled bids' net | `bids_events.csv.gz`, complete and filled, net | ≥ 5 bps, t ≥ 3 |
| 13 | #33 | shorts pay hard, m30 | `fillcost_events.csv.gz`, bucket "shorts pay" | < 0 |
| 14 | #35 | reclaimed sweeps, 1 h | `sweeps_events.csv.gz`, side low, kind reclaimed, r60 | > 0, t ≥ 3 |
| 15 | #37 | the model's bets | `polyhour_markets.csv.gz`, profit | > 0, t ≥ 2 |

Not audited, and why:
- #21's reversal R needs the price baseline (`ls.baseline`), which is not in its event file.
- #34 is pending.
- Forward tests have no data yet. Their frozen criteria are listed under Outcomes.

## What counts as a changed conclusion — fixed now

A headline **changes** when, between the two estimators:
1. its **sign** flips; or
2. it meets its **own bar** under one estimator and not under the other. The bar is the
   table's last column: the same mean threshold and t threshold.

Everything else is "unchanged". Each changed headline is listed with the verdict it fed, and **the
published verdict is not rewritten**. A dated note is added to each changed study's RESULTS file,
pointing here.

## Outcomes, fixed now

- **The audit table** in RESULTS_DAYMEAN_AUDIT.md: both estimators, the concentration, and changed or
  unchanged.
- **A repo rule from here on.** New pre-registrations report the trade-weighted mean with
  day-clustered errors as the headline, with the day-mean as information. The helper ships as
  `espero/audit.py`.
- **Forward tests (#24, #27, #29, #31, #32, #38).** Their frozen day-mean criteria stay as frozen.
  At each verdict, the trade-weighted value is printed beside them, as information. Where this audit
  finds that a forward test's in-sample basis changes, that is said now, before its window closes.

## Transparency — what I saw before writing this

- #43's decomposition of #20's 12 h result.
- The repo's code paths for each headline: function names and filters, read to fill in the table.
- The published day-mean values in each RESULTS file.
- No trade-weighted value of any headline above, except #20's at 12 h in #43, has been computed.
