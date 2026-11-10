# Results — the night shift: hold the stock perps from the close to the next open (#76)

**FAIL, on four of five criteria.** Run once, 2026-11-10, by `research/nightshift.py` at b29ed96, against
`research/PREREGISTRATION_NIGHTSHIFT.md` (167ecf4, stamped). The full output is `research/nightshift_run.txt`;
the portfolio's nights are in `research/nightshift_nights.csv`; the bars read are in
`research/nightshift_bars.csv.gz`.

## What was tested

The 37 stocks and ETFs of #73's list, each listed ticker's official close to its next official open, every
night, equal weight: 1,252 nights from 2021-11-11 to 2026-11-06, 38,473 market-nights. 14 bps a fill, two fills a
night, and funding at 10% a year for the hours held.

## The criteria

| criterion | needed | result |
|---|---|---|
| 1. profit factor over every market-night, net | 1.5 or more | **0.778** |
| 2. mean net night, Newey-West t, BH q | mean > 0, t ≥ 3, q < 0.05 | **−20.93 bps**, t −5.07 (the wrong way) |
| 3. the night beats the day, net | the night above the day | −20.93 bps against −22.93: **holds** |
| 4. both halves above zero | yes | **−30.96 bps, then −10.90 bps** |
| 5. more than half the markets above zero | yes | **4 of 33** with 250+ nights |

## Information only

- **The overnight effect is there before costs.** Gross, the average night earned +10.32 bps against +5.81 bps
  for the average day. Of the equal-weight portfolio's log return over five years, the nights gave +1.130 and
  the days +0.423. Without costs or funding the mean night has a Newey-West t of 2.50.
- **The costs are three times the effect.** Two fills at 14 bps plus about 2.5 bps of funding is about 31 bps a
  night, against a gross night of 10 bps. At trade.xyz's growth-mode fee (0.9 bps) plus 5 bps of slippage the
  mean net night is −4.73 bps (t −1.15). Breaking even needs fills of about 4 bps each, fee and slippage together, with funding held at 10%.
- **By year, gross:** 2021 +6.9 bps (seven weeks), 2022 −14.5, 2023 +8.3, 2024 +23.4, 2025 +22.2, 2026 +13.0.
  Weekend nights and weeknights earned the same, about +10 bps.
- **Markets net above zero:** NBIS (+23.0 bps), SNDK (+14.2), CRWV (+12.3), DRAM (+6.8, 151 nights) and IREN
  (+3.4). Most are recent listings that rose fast, which the registration counts as they are and no rule chose.
- Deflated Sharpe on the nightly net series: 0.000.

## What this means

Holding these stocks only overnight earns more than holding them by day, as the literature says, but not
enough to pay for a round trip every night. The rule is closed under this number. A version that holds through
several nights and trades less often would cost less, but that is a different rule with its own number, and
nothing here says it would pay.
