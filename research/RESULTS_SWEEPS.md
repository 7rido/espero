# Result — stop runs at yesterday's low reverse (#35)

**Verdict: FAIL** on criteria 2 and 4. Sweeps of yesterday's low that close back above it within 15
minutes do bounce: **+15.3 bps** in the next hour (t 7.0), in both halves and every year. The ones
that **fail** to reclaim bounce more: **+19.5 bps** (t 7.5). The reclaim, the supposed sign that
the stops below the level fired and are spent, adds nothing (−4.2 bps, t −1.2).

What remains is the mean reversion at new lows this repo already knows (#20; #24 runs it
forward), seen from a daily level instead of a 4-hour window. The "stop hunt" reading is not
supported.

Spec: [PREREGISTRATION_SWEEPS.md](PREREGISTRATION_SWEEPS.md) (`4cef5ae`); code `d4a1a7f`. One run,
output in [sweeps_run.txt](sweeps_run.txt), events in [sweeps_events.csv.gz](sweeps_events.csv.gz).

## Data

42 coins' 5-minute bars, 2020-01-02 → 2026-10-27. **40,785 first sweeps** of yesterday's low
(27,008 reclaimed, 13,777 failed) on 2,180 days.

## Criteria

| # | criterion | required | actual | met |
|---|---|---|---|---|
| 1 | the reversal | reclaimed long 1h > 0, t ≥ 3 | +15.3 bps, t 6.99 | yes |
| 2 | the reclaim matters | reclaimed − failed > 0, t ≥ 2 | −4.2 bps, t −1.24 | **no** |
| 3 | not one era | > 0 in both halves | +15.5 / +15.1 bps | yes |
| 4 | it pays | > 18 bps, t > 2 | +15.3 bps | **no** |

## What the tables say

1. **Weakness at yesterday's low is bought, reclaimed or not.**

   | | 1 hour | 4 hours |
   |---|---|---|
   | reclaimed | +15.3 bps (t 7.0) | +39.1 bps (t 9.3) |
   | failed | +19.5 bps (t 7.5) | +44.1 bps (t 9.5) |

   Failures beat reclaims in 2021, 2022, 2024 and 2026.
2. **It is not #20's events in disguise.** 64% of reclaimed sweeps had a #20 trigger in the hour,
   and those without one bounced the same (+12.5 against +12.7 bps). The effect is broader than
   #20's volume-spike trigger: prices come back after breaking a widely watched low.
3. **The mirror holds at yesterday's high** (information): paper shorts after sweeps of it gained
   +8.0 bps when reclaimed (t 3.5) and +11.6 bps when failed (t 5.1). Intraday mean reversion at
   daily extremes, both ways.
4. **Round numbers carry little** (BTC to $1,000, ETH to $100): +6.0 bps reclaimed (t 2.0), +5.6
   failed.
5. **Costs**: one Hyperliquid taker round trip with slippage leaves +2.3 bps at 1 hour. The 4-hour
   numbers (+39 to +44 bps gross) are the ones that would survive costs, and that is #24's horizon,
   already running forward on new data.

## What this changes

Nothing ships. Stop hunts as a distinct mechanism: no. Buying breaks of yesterday's low and holding
4 hours: the same edge as #20 and #24, from a second trigger. It adds weight to #24's forward test
rather than a new trade.

## Scoreboard

| # | Hypothesis | Outcome |
|---|---|---|
| 20 | New 4-hour lows on volume bounce | real, not tradable: +14.8 bps in 1h, t 9.8 |
| **35** | **Sweeps of yesterday's low that reclaim it reverse (stop runs)** | **fail**: they bounce (+15 bps/h), but failed sweeps bounce more; the reclaim adds nothing |


> **Note 2026-10-29 (#44):** re-estimated trade-weighted with day-clustered errors, this study's headline changes. See [RESULTS_DAYMEAN_AUDIT.md](RESULTS_DAYMEAN_AUDIT.md). The verdict above stands as published.
