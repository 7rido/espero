# Result — at which holding period do the repo's real signals pay? (#43)

**By the pre-registered rule: one signal CONFIRMED.** #20's new-low bounce, held 12 hours, netted
+21.8 bps on 2025–26 data the choice never saw.

**Economically: not tradable.** A book taking every signal earns **−9.6 bps a trade** in the holdout,
and 9 of the 10 coins are negative on their own. The pre-registered statistic gives each day one
equal vote. That handed the result to **50 of 6,310 trades** on quiet days, and a trader cannot know
at entry which days those are. The forward paper test the rule calls for should not be built on this
statistic.

Spec: [PREREGISTRATION_HORIZONS.md](PREREGISTRATION_HORIZONS.md) (`0896859`). Code `e0f44a2`. Run as
printed `1c94f29`: [horizons_run.txt](horizons_run.txt), cells [horizons_cells.csv](horizons_cells.csv).
The S1 12 h trade list is [horizons_s1_12h_trades.csv.gz](horizons_s1_12h_trades.csv.gz), and
`tests/test_horizons_reference.py` pins both readings.

## Data

- **Coins.** Ten, 2020-01 → 2026-10-27 (later listings from their first bar).
- **S1 regeneration.** Identical to the published `lows_events.csv.gz` on 2020-01 → 2026-03 for all
  ten coins.
- **Power** (minimum detectable net effect, pooled), printed before any signal outcome:

  | horizon | 1 h | 12 h | 1 day | 1 week | 2 weeks |
  |---|---|---|---|---|---|
  | MDE | 0.5 bps | 6.5 bps | 14 bps | 108 bps | 231 bps |

  At a week or more, only very large effects were visible at all.

## The map — selection window, net per trade after Hyperliquid cost and Binance funding

Day-mean bps, Newey-West t in brackets.

| signal | 1 h | 4 h | 12 h | 1 day | 3 days | 1 week | 2 weeks |
|---|---|---|---|---|---|---|---|
| S1 new-low bounce, long | +2.1 (1.2) | +17.6 (5.2) | **+43.5 (6.6)** | +50.8 (4.4) | +101 (2.9) | +296 (2.8) | +956 (2.3) |
| S2 shorts pay hard, short | −12.5 | −44.3 | −130 (−3.0) | −178 | −336 | −606 | −1,074 |
| S3 carry, receive funding | −6.3 | −2.3 | +7.1 (0.8) | +2.8 | −49 | −128 | −40 |
| S4 trend control, long | −9.1 | −14.0 | −3.1 | +10.9 (0.7) | +34 (0.7) | +155 (1.3) | +287 (1.0) |
| S5 #26 forced breaks (information) | +3.4 | +20.3 (4.5) | +50.0 (5.5) | +90.6 (5.6) | +122 (2.8) | +197 (2.0) | +366 (1.8) |

- **Carried:** S1 at 12 h, the largest t.
- **Not carried:** S2, S3 and S4 had no horizon with net > 0 and t ≥ 2.
- **S2 reverses.** #38's 30-minute fall becomes a large loss at every horizon from 4 h: the price
  rises afterwards.
- **S4 shows nothing as a per-coin trade.** Trend's value in this repo is as a portfolio and sizing
  construction (#4, #8, #15), not a per-trade signal.

## Confirmation — S1 at 12 h, entries 2025-01-01 → 2026-10-27

| rule | result |
|---|---|
| net > 0, Holm (k = 1: p ≤ 0.05) | +21.8 bps, t 2.12, p 0.017: **met** |
| both halves > 0 | +25.1 / +18.4: **met** |
| no collapse (≥ ⅓ of selection's +43.5) | **met** |
| unseen | 12 h was never computed before: **met** |

**CONFIRMED, as pre-registered.** The bar is low, though: t 2.12 is under the repo's Harvey-Liu-Zhu
3.0 and the study's deflated 4.09. Even read at face value, the next step was a forward paper test,
not a trade.

## What the confirmation actually rests on — information, after the verdict

| | selection | holdout |
|---|---|---|
| day-mean net (the pre-registered statistic) | +43.5 | **+21.8** |
| **trade-weighted net** (what a book taking every signal earns) | +13.1 | **−9.6** |
| median trade | | −9.4 |
| day-mean without the best 1% / 5% of days | | +12.1 / **−10.8** |
| hit rate | 54.1% | 50.2% |

Split by how many coins triggered on the trade's day:

| same-day triggers | selection: trades, trade-weighted net | holdout: trades, trade-weighted net |
|---|---|---|
| 1 | 24, +225 | 7, +202 |
| 2–3 | 338, +206 | 43, +306 |
| 4 or more | 12,154, +7 | **6,260, −12** |

- **Why the two readings differ.** A quiet day with one isolated new low counts as much as a
  market-wide sell-off day where ten coins trigger. The isolated lows bounced hard; the sell-off
  lows kept falling. The day-mean gives the few isolated trades nearly all the weight.
- **Why the weighting isn't tradable.** At entry nobody knows how many coins will trigger later
  that day. The causal version counts other coins' triggers in the 12 hours **before** entry. On
  the holdout it gives +8.3 (none before), +4.4 (1–2) and **−13.8 (3 or more, 78% of trades)**
  trade-weighted. No causal bucket is clearly positive.
- **By coin, holdout.** 9 of 10 negative: from −25.7 bps (DOGE) to −2.3 (SOL), with TIA alone
  positive at +6.0, t 0.3.
- **Other cuts.**
  - Spot-equivalent (no funding): +22.0 day-mean, same story.
  - At the Binance liquidation-hour cost on the majors: +12.4 (t 1.47), against +13.3 at the "all"
    cost.

## A warning for the whole repo

**"Each UTC day's mean is one observation" is this repo's convention.** It is used in #18–#38 as
the point estimate, not only to correct the standard error. Where many events share a day, it
weights rare quiet-day events far above crowded-day ones, and it uses same-day future information
to do it.

#20's own +14.8 bps at 1 h (42 coins) is a day-mean. Its trade-weighted value has not been
computed. Every result that reports a day-mean of events, including the forward tests' frozen
criteria (#24, #27, #29, #31, #32, #38), may carry the same distortion.

**The right estimator for "what a book earns"** is the trade-weighted mean (or a causal sizing rule
fixed in advance), with day-clustered standard errors. **This is the most important thing #43
found.**

## Transparency

- **Cells whose holdout had been seen.** S1's 1 h and 4 h holdout numbers were seen in
  RECHECK_COSTS, and they are marked "seen". The 12 h cell is new, but its events overlap theirs:
  hours 4–12 of the same trades.
- **This is unseen history, not forward data.** #24 forward-tests the same signal at 4 h.
- **Venues.** Coins were chosen by 2026 liquidity, costs are Hyperliquid's (a venue the account
  holder cannot use), and the funding applied is Binance's.
- **Missing bars.** `one_per_coin` runs after trades with a missing exit bar are dropped, so a gap
  frees a coin a little early.
- **Everything below the confirmation table was computed after the verdict.**

## What this changes

- **No forward test is started on this result.** The pre-registered outcome assumed the statistic
  measured what a book earns, and it does not. A forward test would need a causal sizing rule fixed
  in advance.
- **The audit of the day-mean convention is the next job.** Recompute every event study's headline
  trade-weighted, with day-clustered errors, and list which conclusions change. It affects how much
  the running forward tests can show.
- **The days-to-weeks question, as asked, is answered: nothing confirmed tradably.** At a week or
  more the study could not detect anything under about 100 bps.

> **Correction 2026-10-29.** S5 (#26, information only) entered 5 minutes late: `s5_events` added a bar
> to a `ts` that is already the break bar's close. S1–S4 and the verdict are unaffected. #26's
> corrected longer-hold numbers are in RESULTS_DAYMEAN_AUDIT.md.
