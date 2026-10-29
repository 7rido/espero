# Result — audit of the day-mean convention (#44)

**All 16 published headlines reproduced exactly** (15 headlines; #20's is checked against both of its
bars). Re-estimated the way a book earns (trade-weighted, with day-clustered errors), **three
conclusions change** and four more shrink by a third or more. **#26, the repo's one predictive pass,
survives.**

Spec: [PREREGISTRATION_DAYMEAN_AUDIT.md](PREREGISTRATION_DAYMEAN_AUDIT.md) (`9cf07bd`). Code `2e17e09`.
Run: [daymean_audit_run.txt](daymean_audit_run.txt), table [daymean_audit.csv](daymean_audit.csv).

## The table

bps; t in brackets. "Quiet share" is the fraction of days with ≤ 3 events: the days the day-mean
over-weights.

| # | study | headline | events / days | day-mean (published) | trade-weighted | ratio | quiet share | changed |
|---|---|---|---|---|---|---|---|---|
| 1 | #18 | leg (a), forced down-breaks, 1 h | 2,012 / 82 | +26.4 (3.85) | +22.9 (2.98) | 0.87 | 5% | no |
| 2 | #18 | D forced − organic | 6,158 / 82 | −11.4 (−2.11) | −14.4 (−2.68) | 1.26 | 0% | no |
| 3 | #19 | g, settlement excess | 9,579 / 1,452 | +15.5 (3.52) | +15.0 (3.15) | 0.97 | 55% | no |
| 4 | #20 | new-low bounce, 1 h | 136,522 / 2,055 | +14.8 (9.78) | **+5.9 (3.50)** | 0.40 | 1% | no |
| 5 | #21 | long leg, raw 24 h | 620 / 101 | +51.1 (2.46) | **+18.5 (0.75)** | 0.36 | 48% | **yes** |
| 6 | #25 | forced leg, 1 h | 35,319 / 1,430 | +12.3 (6.00) | **+6.1 (2.40)** | 0.49 | 1% | no |
| 7 | #25 | D (oi_drop) | 69,666 / 1,430 | +3.2 (2.36) | +3.3 (1.93) | 1.04 | 0% | no |
| 8 | #26 | leg (a), forced down-breaks, 1 h | 5,971 / 415 | +23.5 (7.13) | **+19.2 (3.67)** | 0.81 | 14% | no |
| 9 | #26 | D forced − organic | 11,096 / 147 | −23.6 (−4.06) | −22.2 (−3.54) | 0.94 | 0% | no |
| 10 | #28 | the push | 1,192 / 596 | −1.5 (−1.44) | −1.5 (−1.44) | 1.00 | 100% | no |
| 11 | #29's basis | post-close reversal, 15 min | 1,192 / 596 | −6.0 (−5.62) | −6.0 (−5.62) | 1.00 | 100% | no |
| 12 | #30 | filled bids' net | 8,602 / 189 | +1.7 (0.97) | **−3.6 (−1.65)** | −2.18 | 1% | **yes** |
| 13 | #33 | shorts pay hard, m30 | 197 / 132 | −34.0 (−2.62) | **−20.1 (−0.77)** | 0.59 | 96% | no* |
| 14 | #35 | reclaimed sweeps, 1 h | 27,008 / 2,122 | +15.3 (6.99) | **+2.1 (0.79)** | 0.14 | 22% | **yes** |
| 15 | #37 | the model's bets ($ a share) | 2,271 / 180 | +0.009 (0.99) | +0.012 (1.34) | 1.30 | 0% | no |

\* #33's bar was only "< 0", so by the rule it is unchanged. But its t falls from −2.6 to −0.8.

## What changed, and what it means

- **#35 (stop runs at yesterday's low reverse).**
  - Its criterion 1, "the reversal: +15.3 bps, t 7.0", was met as a day-mean. Trade-weighted it is
    +2.1 bps, t 0.8: not met.
  - #35 already failed on its other criteria, so the verdict (FAIL) stands, and gets stronger. The
    "reversal is real" reading in its RESULTS does not survive.
  - **#35's "the same bounce as #20" link in RECHECK_COSTS.md is withdrawn.**
- **#21 (liquidation spikes reverse).** Its "the long leg pays: +51.1 bps, t 2.45" was met as a
  day-mean. Trade-weighted it is +18.5, t 0.75, so not met. #21 already failed on criteria 1 and 3;
  the verdict (FAIL) stands, and its one passing leg is gone.
- **#30 (resting bids).** +1.7 becomes −3.6 bps a fill. It failed already; the sign is now negative.
  That fits #39's back-of-queue finding. #31, its forward variant, rests on #30's exploration rows,
  which were day-means. Their trade-weighted values are not computed here.

## What shrank without crossing its bar

- **#20 (new-low bounce): +14.8 → +5.9 bps a trade.** Still real (t 3.5), but 60% of the published
  size came from quiet-day weighting. That matches #43's finding at 12 h.
- **#25's forced leg** halves, to +6.1.
- **#33 (shorts pay hard)** keeps its sign, but t −0.77. #38's forward test rests on a basis that is
  not significant trade-weighted. #43 also found the short loses at every horizon from 4 h.

## What holds

- **#26, the one predictive pass: +19.2 bps a trade, t 3.67.** Still above its 18 bps bar with
  t > 2. Its D holds too (−22.2, t −3.54). The forced-liquidation bounce is the most robust result
  in this repo.
- **#18's leg and D, and #19's settlement excess,** within 15%.
- **#28 and #29 have exactly two events a day** (BTC and ETH), so the two estimators are identical.

## The forward tests, before their windows close

| forward test | in-sample basis, trade-weighted | reading |
|---|---|---|
| #24 (#20's 4 h bounce) | #20 shrinks 0.40× at 1 h; #43 found 12 h negative trade-weighted in 2025–26 | weak |
| #27 (#26 forward) | +19.2, t 3.67 | **holds** |
| #29 (post-close reversal) | identical under both | holds |
| #31 (#30's 2-ATR variant) | #30's base flips negative; the variant itself is not re-estimated | unknown, likely weaker |
| #32 (funding split of #27's breaks) | rests on #26 | holds |
| #38 (#33's shorts-pay short) | t −0.77 trade-weighted | weak |

Their frozen criteria stay frozen. At each verdict the trade-weighted value is printed beside them.

## From here on

`espero/audit.py` is the standard. New pre-registrations report the **trade-weighted mean with
day-clustered errors** as the headline, and the day-mean only as information.

## Information, after the audit — #26's bounce held longer, trade-weighted

Computed on request, 2026-10-29. Hindsight: #43 had shown these horizons as day-means.

| hold | gross, all 26 coins | net after Hyperliquid cost and Binance funding, 8 priced coins (t) | net 2023 / 2024 |
|---|---|---|---|
| 1 h | +19.2 | −0.7 (−0.21) | −2.8 / +0.5 |
| 4 h | +42.6 | +15.5 (3.15) | +9.9 / +18.7 |
| 12 h | — | +31.3 (3.07) | +31.2 / +31.3 |
| 1 day | — | +55.9 (3.37) | +63.5 / +51.6 |

- **Data.** Every event counted, as #26 counts them. Only 2023-06 → 2024-10 exists.
- **Errors.** At 12 h and 1 day the holds overlap across days, so day-clustered t-statistics are
  optimistic.
- **What it says.** On the liquid coins, the 1 h leg nets about zero. The edge that clears costs is at
  4 h – 1 day.
- **What it would take.** Testing this needs a new forward test pre-registered on days that do not
  exist yet. #27, which is frozen at #26's own horizon, cannot test it.

> **Correction 2026-10-29.** The table above entered 5 minutes late. #26's ledger `ts` is the break bar's
> close, already the next bar's open, and 5 minutes were added again. With the entry at `ts` (the 1 h gross
> then equals the file's own y60, +16.4 bps on these coins), net trade-weighted is: 1 h **+5.4** (t 1.52),
> 4 h **+21.9** (t 4.38), 12 h **+36.5** (t 3.57), 1 day **+60.4** (t 3.63). Both years remain positive at
> every horizon from 4 h.
