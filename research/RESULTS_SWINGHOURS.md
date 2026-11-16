# Results — session swings: how big each coin's moves are, hour by hour of the week (#82)

**The hours repeat, they follow the UTC clock, and the weekend repeats as the quietest stretch.** On Binance's hourly
bars for 15 coins, the weekday profile of swing size by hour measured on 2020 to 2024 correlated at **0.865** with the
same profile on 2025 to September 2026 (registered bar 0.7), and **all 15 coins** correlated at 0.5 or more (bar 13).
The UTC clock's profile repeated better than New York's (0.865 against 0.749). The busiest weekday hour out-of-sample
was **14:00 UTC, 1.61 times** a coin's average hour, and the quietest **23:00 UTC at 0.80**: a ratio of **2.0**.
Saturday and Sunday were the two quietest days in both halves, at **0.78** of the weekdays out-of-sample. This is a
measurement: no signal, no direction, no edge claim, and it changes no frozen test.

Registered in `8b42820` (stamped), code and runner in `f28b587`. One run, 2026-11-16 16:25 UTC. Raw output:
[swinghours_run.txt](swinghours_run.txt); every coin's weekday-hours profile in both halves, both clocks and both
measures in [swinghours_profiles.csv](swinghours_profiles.csv).

## The registered readouts

| readout | as registered | result |
|---|---|---|
| 1. the hours repeat | pooled Spearman ≥ 0.7 and ≥ 13 of 15 coins at ≥ 0.5, body, weekday hours, UTC | **0.865, 15 of 15: THE HOURS REPEAT** |
| 2. the clock | the higher pooled out-of-sample correlation, by ≥ 0.05 | **UTC** (0.865 against 0.749) |
| 3. the size | busiest and quietest weekday hour, their ratio, the weekend | 14:00 UTC 1.61, 23:00 UTC 0.80, **ratio 2.00**; weekend 0.78 of the weekdays |
| 4. the weekend repeats | Saturday and Sunday the two quietest days in both halves | **yes, in both: THE WEEKEND REPEATS** |

Every variant came out the same way: the range measure repeats too (0.899 UTC, 0.842 New York, 15 of 15 each), and
New York's body profile also clears the bar (0.749, 14 of 15), only less well than UTC's. The coins: BTC 0.89, ETH 0.90
and SOL 0.89 repeat best; WLD and ZEC least, at 0.65 each. ENA and ZRO, too young to compare, follow the pooled
out-of-sample profile at 0.96 and 0.95.

## What the hours look like

Normalised swing, 1.0 = the coin's own last month's average hour, pooled over the 15 coins, weekdays.

| | in-sample 2020–2024 | out-of-sample 2025–2026 |
|---|---|---|
| busiest | 14:00 UTC 1.40, 15:00 1.34, 13:00 1.29 | 14:00 UTC 1.61, 15:00 1.55, 13:00 1.31 |
| quietest | 04:00 UTC 0.88, 05:00 0.91, 23:00 0.96 | 23:00 UTC 0.80, 11:00 0.88, 10:00 0.88 |
| busiest over quietest | 1.59 | 2.00 |
| days, Mon to Sun | 1.11 1.08 1.10 1.07 1.05 **0.85 0.90** | 1.15 1.04 1.04 1.05 1.09 **0.78 0.89** |

**The US equity open dominates, and it has grown.** The three busiest weekday hours are 13:00 to 16:00 UTC in both
halves, the hours around the 9:30 a.m. New York open, and the peak rose from 1.40 to 1.61 times the average hour. The
quiet hours moved: Asia's early morning (04:00 to 05:00 UTC) was quietest in 2020 to 2024, the hour before midnight
UTC and the late European morning in 2025 to 2026. Monday is the busiest day in both halves.

**Why UTC beats New York although the peak is the US open.** The registered reading is the correlation of the whole
24-hour shape, and most of the shape outside the open is set on the UTC clock (Asia's day, funding at 00:00, 08:00 and
16:00 UTC, the European morning); daylight saving shifts those against New York's hours twice a year. The open itself
is about as sharp on either clock (peak-to-trough 2.00 UTC, 1.99 New York). Information, read after the run: a rule
anchored to the open should be anchored to New York's clock, one anchored to anything else to UTC's.

## Information only

- **The week's busiest hours, out-of-sample:** Tuesday 14:00 UTC (1.75), Thursday 15:00 (1.74), Friday 14:00 (1.68),
  Monday 15:00 (1.63) and 14:00 (1.62). **Quietest:** Saturday 10:00 and 11:00 UTC (0.63), Sunday 05:00 (0.64), Sunday
  06:00 and Saturday 19:00 (0.67). The busiest weekday hour moves 2.8 times the quietest weekend hour.
- **Year by year,** each year's profile against the in-sample pooled one (median over coins): 2020 0.47, 2021 0.67,
  2022 0.84, 2023 0.87, 2024 0.90, 2025 0.76, 2026 0.79. The shape set in from 2022, when the US hours came to
  dominate; 2020 and 2021 sit inside the in-sample half and pull its average shape a little away from the later years.
- **In raw bps, the median weekday hour out-of-sample** (UTC 00 to 23):
  - BTC: 27 25 24 21 19 21 20 19 21 21 19 18 22 35 **48** 36 29 33 27 22 22 21 20 16
  - ETH: 37 36 37 30 27 30 27 27 28 30 26 26 31 50 **63** 52 37 45 41 33 35 29 30 27
  - SOL: 43 47 45 37 35 39 33 35 37 34 31 31 41 52 **72** 62 48 54 47 42 42 34 35 32

  BTC's median 14:00 UTC hour moves 48 bps against 16 bps at 23:00. A second bump at 17:00 UTC, on all three, is
  information only.
- **The first 721 bars of each coin were dropped,** not 720 as the pre-registration says: the normaliser needs 720
  previous bars, so the first bar it can normalise is the 721st. No other bar was dropped on any coin.
- **Not a signal: the signed mean return by week slot** out-of-sample ranged from +21.9 bps (Tuesday 15:00 UTC) to
  −23.2 bps (Monday 01:00 UTC). These are the extremes of 168 slots, picked after the fact, and nothing here tests
  whether they differ from chance; any rule on direction by hour is a new pre-registration, judged under the FDR bar.

## What it means for espero

- **Orders and stops.** A resting order or a stop placed for the US open faces about twice the swing of one placed in
  the late UTC evening, and about 2.8 times that of a weekend morning. Sizing a stop in bps should know the hour.
- **The canary.** Rule 8 decides at Sunday's close, in the quietest stretch of the week; from 2026-11-22 its testnet
  buys go out by 08:19 UTC Monday, before the busy hours. Nothing in this changes it.
- **The Market tab** can show, beside each coin, whether the current hour is usually busy or quiet, from
  `swinghours_profiles.csv`. That is a display, not a signal.

## What this cannot say

Which way the price moves in a busy hour; what a trade costs in it (#68 is the cost); whether any rule built on the
profile pays. Binance's bars, not Hyperliquid's: the shape should transfer, the levels may not.
