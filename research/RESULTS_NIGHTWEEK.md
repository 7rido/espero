# Results — the slow night shift: Monday's close to Friday's open, once a week (#77)

**FAIL, on all five criteria.** Run once, 2026-11-10, by `research/nightweek.py` at 0bf37ae, against
`research/PREREGISTRATION_NIGHTWEEK.md` (2ddfdda, stamped). The full output is `research/nightweek_run.txt`; the
portfolio's weeks are in `research/nightweek_weeks.csv`; the bars read, SPY's included, are in
`research/nightweek_bars.csv.gz`.

## What was tested

The 37 stocks and ETFs of #73's list, each held from its week's first official close to its last official open:
261 weeks from 2021-11-08 to 2026-11-02, 8,017 market-weeks. One round trip a week at 14 bps a fill, and funding
at 10% a year for the hours held.

## The criteria

| criterion | needed | result |
|---|---|---|
| 1. profit factor over every market-week, net | 1.5 or more | **0.990** |
| 2. mean net week, Newey-West t, BH q | mean > 0, t ≥ 3, q < 0.05 | **−2.3 bps**, t −0.08 |
| 3. above the market over the same hours | above SPY's gross | **−2.3 against +8.7 bps** |
| 4. both halves above zero | yes | **−16.5 bps, then +11.9 bps** |
| 5. more than half the markets above zero | yes | **12 of 30** with 100+ weeks |

## Information only

- **Gross, the hold earned +35.5 bps a week,** less than the roughly 58 bps that #76's nightly and daily means
  implied. One round trip at 28 bps and about 10 bps of funding take it to −2.3.
- **At the growth-mode fee** (0.9 bps) plus 5 bps of slippage, the mean net week is +13.9 bps, t 0.49: positive,
  nowhere near the bar.
- **Holding every day of the week instead,** close to close, earned +71.9 bps a week gross, twice the hold's.
  Leaving out Friday, the weekend and Monday cost more than it saved in trading.
- **By year, net:** 2021 −37.8 bps (eight weeks), 2022 −61.1, 2023 +28.2, 2024 +5.4, 2025 +32.3, 2026 −12.9.
- **The winners net** are mostly this list's fastest risers: SNDK +184 bps, SKHY +117, NBIS +106, BE +87, NVDA
  +50. Several of these have under two years of history.
- Deflated Sharpe on the weekly net series: 0.001.

## What this means

Trading less does cut the cost to one round trip a week, but the days carried in between do not earn enough, and
the week falls short of simply holding SPY. The night's premium found in #76 is real before costs; on these
names, at these costs, neither the nightly nor the weekly version keeps it. Closed under this number.
