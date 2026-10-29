# Result — liquidation spikes reverse (#21)

**Verdict: FAIL** on criteria 1 and 3. On the four sealed months the pattern the exploration showed
mostly did not come back: the reversal across both sides was +4.8 bps (t 0.27) against a t ≥ 3 bar,
and the first half went the other way. Buying after long-liquidation spikes did make money (+51 bps
raw over 24 hours, t 2.45), but in months when the whole market rose.

Spec: [PREREGISTRATION_LIQSPIKE.md](PREREGISTRATION_LIQSPIKE.md) (committed `0b50764` with #20's,
before either ran); code `ac35453`, also before. The run verified the four sealed files against
their SHA-256 first. One run; output in [liqspike_run.txt](liqspike_run.txt), events in
[liqspike_events.csv](liqspike_events.csv).

## Data

aggr's hourly bars, 2026-07-01 → 2026-10-28 (sealed on 2026-10-29, unread until this run), 14 coins,
thresholds from each coin's previous 720 hours (June's explored bars as warm-up only). **631
long-liquidation spikes and 609 short ones, on 119 days.** The average coin-hour rose: +19.5 bps over
24 hours.

## Criteria

| # | criterion | required | actual | met |
|---|---|---|---|---|
| 1 | forced flow reverts, both sides | mean R > 0, t ≥ 3 | +4.8 bps, t 0.27, 117 days | **no** |
| 2 | each side's sign | longs > 0, shorts < 0 | longs +28.0 bps (t 1.36), shorts −53.9 bps (t −1.87) | yes |
| 3 | not one stretch | R > 0 in both halves | −20.2 bps (Jul–Aug), +33.0 bps (Sep–Oct) | **no** |
| 4 | the long leg pays | raw 24h > 18 bps, t > 2 | +51.1 bps, t 2.45 | yes |

## What the tables say

1. **The combined test was mostly a same-day comparison, and it found nothing.** 96 of the 119 days
   had spikes on both sides. On those days R compares coins whose longs were liquidated with coins
   whose shorts were liquidated, over the same 24 hours, and the two did about the same. A day's
   market move cancels out of that comparison. Criterion 2, each side against the average hour as
   the exploration measured it, does include the market's move, and points the reversal way on both
   sides, but neither side is significant.
2. **The exploration's effect shrank on new months.** After long-liquidation spikes: +65 bps (t 2.4)
   explored, +28 bps (t 1.4) here. After short ones: −56 bps (t −2.6) explored, −54 bps (t −1.9) here.
   Counted per event instead of per day there is no reversal at all: longs −4.7 bps, shorts +14.9 bps.
   Quiet days with one or two spikes reverted; busy days, when many coins cascaded together, did not.
3. **The long leg's profit is mostly the market.** +51 bps a day after long spikes, in months when
   the average coin-hour gained +19.5 bps a day, with day-weighting favouring the quiet days.
4. **Information only: 4 hours looks stronger than 24.** Longs +26.0 bps (t 3.12), shorts −27.1 bps
   (t −2.88), combined +10.7 bps (t 1.73). The biggest third of long spikes by dollars: +54.5 bps
   (t 2.37), the smallest third +12.3. By coin it is all over the place (ETH +54, XLM −97). None of
   it can be claimed from this run.

## A flaw in the design, stated plainly

Combining both sides into one daily R was meant to add power. Because most days had both kinds of
spike, it turned criterion 1 into a cross-sectional comparison the exploration never measured. The
exploration measured each side over time. The pre-registered verdict stands. A future test of this
idea should judge each side over time (criterion 2's form), at the horizon fixed in advance, and
needs more than four months to have the power that requires.

## What this changes

Nothing ships. The sealed months are used. "Liquidations mark turning points" goes back to being a
lead. The live recorder would only be worth building to gather the longer history a fair test needs.

#20 (new 4-hour lows on volume, price only, 2020 → March 2026) runs next, as pre-registered; it does
not touch these months.

## Scoreboard

| # | Hypothesis | Outcome |
|---|---|---|
| 12 | Carry with swap gap + maker execution (Hyperliquid) | pass, provisional — forward test to 2026-11-27 |
| 18 | Liquidations sort breakouts into forced and organic | fail — right direction, t −2.1, second half only |
| 19 | The funding settlement moves prices | real, not tradable — +15.5 bps, t 3.5 |
| **21** | **Liquidation spikes reverse (sealed July–October)** | **fail** — R +4.8 bps, t 0.3; the long leg's +51 bps was mostly a rising market |


> **Note 2026-10-29 (#44):** re-estimated trade-weighted with day-clustered errors, this study's headline changes. See [RESULTS_DAYMEAN_AUDIT.md](RESULTS_DAYMEAN_AUDIT.md). The verdict above stands as published.
