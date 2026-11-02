# Result — new Binance USD-M perps after they list, short against BTC (#67)

**Verdict: FAIL.** On 288 listings from 2025-01 to 2026-09, shorting a new crypto perp at the open of the day after
its first trade and holding it a week against BTC lost money net of funding and costs: a daily mean of −52 bps,
t −0.89, q 0.73 over the 35 judged tests. Three of the four criteria missed: the t, both halves, and the drift
against the basket of established coins.

What it says:

- **The typical new listing still falls.** The median position made +12.7% net in its week (+14.4% gross), more
  than on the design window (+10.0%). That is the one criterion that held.
- **A few squeezes and their funding erase it.** The worst listing rose 484% against the short within its week, at
  a daily close. Funding cost a mean of −2.7% a position against a median of −0.1%: the coins that squeeze are the
  ones whose shorts pay. The mean position lost 0.5%, and the trade loses even before costs once funding is counted.
- **As the pre-registration said,** a FAIL is weak evidence against the drift and strong evidence that the trade,
  as specified, is not tradable. Its power made a pass unlikely; the holdout came in below even that, negative.

Spec: [PREREGISTRATION_LISTDRIFT.md](PREREGISTRATION_LISTDRIFT.md) (`361f57c`, stamped on OpenTimestamps), after
[EXPLORE_LISTDRIFT.md](EXPLORE_LISTDRIFT.md) (`a30eda6` to `917e403`, and the rehearsal). Code unchanged since
`361f57c`. One run on 2026-11-02, under two minutes, at `361f57c`; output [listdrift_run.txt](listdrift_run.txt);
the daily series [listdrift_series.csv](listdrift_series.csv), from which the t reproduces to four decimals.

## Criteria

| criterion | needs | result | met |
|---|---|---|---|
| 1. daily mean of short listing, long BTC, net | above 0 with t ≥ 3 | −52.4 bps, t −0.89 (Newey-West, 5 lags), p 0.37 | no |
| 1. Benjamini-Hochberg q, every judged test with #67 | below 0.05 | 0.73 over 35 | no |
| 2. each half of the days | above 0 | −43.0 and −61.9 bps a day | no |
| 3. the median position | above 0 | +12.7% | yes |
| 4. the short against the basket, price only | daily mean above 0 | −34.5 bps (t −0.59) | no |

The q was computed by `listdrift.py` from `trials.csv` as committed at `361f57c`, plus #67's p;
`research/fdr_rescore.py`, rerun with #67's row added, gives the same.

## The numbers

- **Positions:** 288 over 553 days, none dropped. Binance's onboardDate fell on the first trade for all 288; the
  dating gap the design window found was a 2023–24 matter.
- **Gross of funding and costs:** −12 bps a day (t −0.21), mean position +2.6%, median +14.4%.
- **Funding per position:** mean −2.7%, median −0.1%.
- **Break-even listing cost per side:** negative, −12 bps.
- **By quarter of entry, mean position:** 2025Q1 +14.3% (49), Q2 −0.6% (65), Q3 −16.3% (67), Q4 +5.8% (54),
  2026Q1 +12.1% (29), Q2 −26.6% (16), Q3 +4.5% (8).

## Information only

Printed beside the verdict as registered; none of it is a claim.

- **Longer holds:** 14 days −5.7 bps a day (t −0.14), median +19.4%, mean −3.5%. 30 days −36.9 bps (t −0.77), median
  +25.0%, mean −37.6%, with funding alone costing a mean of −39.8% a position: a few positions held short through a
  squeeze paid most of it.
- **With the cover rule:** +9.7 bps a day (t 0.22), mean +1.2%, median +10.9%, 79 of 288 closed early; at 14 and 30
  days +9.3 (t 0.29) and +13.3 (t 0.59). The cover cuts the tail's damage and leaves nothing detectable.
- **Entry two days after the listing:** +3.5 bps a day (t 0.07).
- **The short alone, net:** −46.8 bps a day (t −0.78).
- **By the listing day's own move:** above its median of −1.7%, +0.95% a position (144); at or below, −2.0% (144).
- **No listing stopped trading** inside its hold.

## What it leads to

- The trade closes at this specification. A variant, with sizing, another tail control or a filter at entry, takes a
  new number and cannot use the 2025–2026 listings: they are read now.
- The fact worth keeping is in both windows: the median new listing falls 10 to 15% against BTC in its first week,
  and a few squeezes, which carry the funding bill too, take the mean away. Telling the squeeze candidates apart at
  entry, from funding or open interest, is a new idea, and it would need listings after 2026-09 to test.
