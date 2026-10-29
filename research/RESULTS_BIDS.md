# Result — resting bids catch forced sellers (#30)

**Verdict: FAIL** on criteria 1, 3 and 4. A bid resting one ATR under a breakdown filled on 65% of
events and earned **+1.7 bps net per fill** (t 0.97), against a 5 bps floor with t ≥ 3. It lost in
April–June, and only 7 of 40 coins were positive.

What it did show:
- **The bid beat taking** (criterion 2, met): +3.9 bps per event (t 2.5). It lost less than #20's
  trade at the market, but neither one paid.
- **The scalper's enemy, measured.** On the events where the bid filled, #20's 1-hour return was
  **−21.7 bps** (t −8.8). On the events where it never filled, it was **+63.9 bps** (t 27.7). The
  bounce happens on the breakdowns that never come back down to a shallow bid.

Spec: [PREREGISTRATION_BIDS.md](PREREGISTRATION_BIDS.md) (`6afad5c`); code `3e77966`.

The first run crashed after printing the data counts and before any return or criterion was
printed. A coin with no events gave an untyped empty frame, which turned the return columns into
text on concatenation. What it had printed: 13,252 events, 8,602 fills, EOS's bars missing. The fix
is `413ef62`, with a test that fails without it. Then one run, output in [bids_run.txt](bids_run.txt)
and events in [bids_events.csv.gz](bids_events.csv.gz).

## Data

- Binance USDⓈ-M 5-minute bars, April → 27 October 2026, for 41 of the 42 coins. EOS's files are not
  in the archive for these months.
- 13,252 breakdowns (#20's trigger) on 189 days. None was dropped for gaps.

## Criteria

| # | criterion | required | actual | met |
|---|---|---|---|---|
| 1 | it pays | filled trades' net ≥ 5 bps, t ≥ 3 | +1.7 bps, t 0.97, 8,602 fills | **no** |
| 2 | the bid beats taking | per event, bid − taker > 0, t ≥ 2 | +3.9 bps, t 2.52 | yes |
| 3 | not one stretch | net > 0 in each half | −1.2 bps (Apr–Jun), +3.8 bps (Jul–Oct) | **no** |
| 4 | not one coin | > half of coins with ≥ 20 fills net > 0 | 7 of 40 | **no** |

## What the tables say

1. **The trade, piece by piece.** 70% of fills exited at the target (the breakdown's close) and 30%
   timed out. The median bid sat 30 bps under the close. Filled trades made +6.0 bps gross (t 3.6),
   and fees took 4.5 bps on average. The edge before costs is real; it is just small at 1 ATR.

2. **Adverse selection is the whole story at 1 ATR.** A bid one ATR down fills on ordinary
   continuation as well as on capitulation. The 35% of breakdowns that never reached it carried the
   bounce: +63.9 bps from the next open, against −21.7 bps on those that did.

3. **Deeper bids pay.** Information only, in the pre-registered table:

   | variant | fills | fill rate | net per fill | per event |
   |---|---|---|---|---|
   | bid 0.5 ATR | 10,547 | 80% | −4.2 bps (t −3.3) | −4.0 bps |
   | **the rule, 1 ATR** | 8,602 | 65% | +1.7 bps (t 1.0) | −0.3 bps |
   | **bid 2 ATR** | 5,439 | 41% | **+12.5 bps (t 5.2)** | +2.4 bps (t 2.3) |
   | 1 ATR, 4-hour exit | 8,602 | 65% | +6.6 bps (t 3.4) | +2.9 bps |
   | fills on a touch | 8,733 | 66% | +2.3 bps (t 1.4) | +0.1 bps |

   With the target at the entry plus 1 ATR: +0.0 bps at a 0.5-ATR bid, +5.9 bps at 2 ATR. At 1 ATR
   that target is the trigger close itself, the rule's own.

4. **An exploration after the verdict**, on the same bars, looked at the deeper bids:

   | variant | fills | net per fill | Apr–Jun / Jul–Oct | coins positive | without the top 3 coins |
   |---|---|---|---|---|---|
   | 2 ATR, 1-hour exit | 41% | +12.5 bps (t 5.2) | +11.4 / +13.3 | 23 of 40 | +10.9 bps (t 4.4) |
   | **2 ATR, 4-hour exit** | 41% | **+20.0 bps (t 6.4)** | +19.5 / +20.4 | 34 of 40 | +17.5 bps (t 5.7) |
   | 3 ATR, 1-hour exit | 26% | +18.4 bps (t 5.4) | +16.7 / +19.6 | 30 of 40 | +17.3 bps (t 5.1) |

   - The edge grows with depth, as the mechanism says it should. A deep bid only fills when forced
     selling overshoots, and buying the overshoot pays even though those events go on to fall 46 bps
     from the next open.
   - Every month from April to October was positive for the 2-ATR bid.
   - It was found on this data after the verdict, so it is a lead, not a result.

5. **Shallow bids are the worst of both worlds.** At 0.5 ATR, 80% fill, and they lose 4 bps net per
   fill: every ordinary drift down fills them.

## What this changes

Nothing ships. The pre-registered rule failed. The deeper bid is a lead that needs data no one has
seen: #31 ([FORWARD_BIDS2.md](FORWARD_BIDS2.md)) tests a 2-ATR bid with a 4-hour exit forward, from
2026-10-30, on the 5-minute bars #24's job already records.

## Scoreboard

| # | Hypothesis | Outcome |
|---|---|---|
| 20 | New 4-hour lows on volume bounce | real, not tradable: +14.8 bps in 1h, t 9.8 |
| **30** | **A resting bid 1 ATR under #20's breakdowns, sold at the breakdown price** | **fail**: +1.7 bps net per fill, t 1.0; adverse selection. Lead: 2-ATR bids, +12.5 to +20 bps |


> **Note 2026-10-29 (#44):** re-estimated trade-weighted with day-clustered errors, this study's headline changes. See [RESULTS_DAYMEAN_AUDIT.md](RESULTS_DAYMEAN_AUDIT.md). The verdict above stands as published.
