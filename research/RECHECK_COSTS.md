# Re-check — earlier results at the measured cost (information only, hindsight)

#39 and #41 measured a taker round trip of **9.9–11.3 bps** on the majors and **11.2–13.8 bps** on six
mid-size Hyperliquid coins. Every earlier test was judged against an assumed **18 bps**. This note
asks which earlier results failed **only** on that assumption, and whether the measured cost changes
them.

**It is hindsight.** These results were seen before the cost was measured, so nothing here is a
verdict. A result that clears the measured cost would still need a fresh forward test. No frozen
test changes.

## Which results failed only on cost

Only results that met **every other** criterion qualify. A cheaper trade cannot rescue an effect that
was not there.

| test | other criteria | gross of the tradable leg | measured round trip | rescued? |
|---|---|---|---|---|
| **#20**, new 4-hour lows bounce | all met (t 9.8, both eras) | +14.8 bps at 1 h (42 coins) | 9.9–13.8 | **no**: see below |
| #19, funding settlement move | all met | best leg +7.1 bps (t 1.85) | ~10.7 | **no**: below cost even now |

**Failed on something besides cost, so not rescuable:**
- #9b: Q5−Q1 only +3.7 bps gross, and it did not beat `rev_1`.
- #10 and #13: profit factor below 1 before Kraken fees.
- #18 and #21: the main effect missed.
- #25, #35: the main effect missed (they are discussed below).
- #28: every criterion missed.
- #11: return and Sharpe both short.

## #20, re-priced

#20's trade buys the next bar after a new 4-hour low on a down-break. It is re-priced on the coins
`espero.costs` measures; day means are the observations.

| set | days | gross 1 h | net 1 h | t | net, first half / second half | net 4 h | t |
|---|---|---|---|---|---|---|---|
| Binance, BTC ETH SOL XRP | 2,043 | +11.1 | **+0.2** | 0.1 | +4.0 / −3.5 | **+21.5** | 7.7 |
| Hyperliquid, the same four | 2,043 | +11.1 | +0.7 | 0.5 | +4.5 / −2.9 | +22.1 | 7.9 |
| Hyperliquid, six mid coins | 1,975 | +14.2 | +2.1 | 0.9 | +9.5 / −4.7 | +31.9 | 7.1 |
| Hyperliquid, all ten priced coins | 2,050 | +12.4 | +1.2 | 0.7 | +6.3 / −3.8 | +24.4 | 8.2 |

- **The 1-hour trade, #20's own, is not rescued.** On the coins whose costs can be measured, its
  gross is +11 to +14 bps. The 42-coin +14.8 leaned on coins not priced here. That leaves a net of
  about zero, negative since February 2023.
- **The 4-hour version clears the measured cost over the whole sample, but it is fading:**

  | year | 2020 | 2021 | 2022 | 2023 | 2024 | 2025 | 2026 |
  |---|---|---|---|---|---|---|---|
  | Binance majors, net 4 h | +34.4 | +48.7 | +6.5 | +16.5 | +21.4 | +6.4 | +2.9 |
  | Hyperliquid 10 coins, net 4 h | +41.1 | +48.1 | +13.0 | +19.7 | +20.7 | +10.1 | −0.9 |

  The 4-hour horizon was information-only in #20, so this is doubly hindsight. **#24 already tests
  it forward**, on days that do not exist yet, against the old 18 bps bar. At the measured cost its
  bar would be about 11 bps gross. The 2025–26 trend says even that is not safe.

## The same pattern elsewhere

#35 (stop runs at yesterday's low: +15.3 bps at 1 h, t 7.0) and #25 (forced breakdowns: +12.3 bps,
t 6.0) failed on their mechanism, not on whether buying the bounce earns. They are the same
"buy after a new low" bounce as #20, measured differently, with gross returns in the same range.
That is one effect, about 11–15 bps an hour gross, roughly the measured round trip. Not three
chances.

## What this changes

- **No earlier failure turns into a pass at the measured cost.** The 18 bps assumption was too high,
  but the results it killed were killed by more than the extra 7 bps, or they have decayed since.
- **#24 (the 4-hour bounce, forward) is the one live test this bears on.** At its verdict after
  2027-03-31, its re-priced net should be read next to its frozen 18 bps result, as information.

> **Note 2026-10-29 (#44):** #35's reversal does not survive trade-weighting (+2.1 bps, t 0.8), so the "same bounce" link above is withdrawn; #20's own 1 h bounce is +5.9 bps trade-weighted, not +14.8. See [RESULTS_DAYMEAN_AUDIT.md](RESULTS_DAYMEAN_AUDIT.md).
