# Results — five patterns for the operator on Hyperliquid (#52–#56)

**Binance moves first, by about a second, on 142 of 144 coin-days. After a sharp Binance move, Hyperliquid's price catches
up over the next few seconds and stays there. Three other patterns are real on these days but small: a high premium is
followed by a weaker mark price, a bid-heavy book by a slightly stronger price, and a large burst by a little more movement
in the same direction. One-sided trading over 60 seconds shows nothing clear.** The book usually refills within about a
second. Apart from the catch-up, every effect is smaller than a $1,000 round trip of about 9–12 bps.

These are measurements on 24 calm first-of-month days. They aren't rules or signals, no frozen test changes, and nothing
goes into `espero rate` or the UI. Registered together in `f856715`; raw outputs are `patterns_52_output.txt` to
`patterns_56_output.txt`. The plain summary is [OPERATOR_READOUT.md](OPERATOR_READOUT.md).

| # | measure | label |
|---|---|---|
| 52 | who moves first | **CLEAR LEADER: Binance** |
| 53 | premium, then mark's move | **CLEAR PATTERN** at 1, 5, 15 and 60 min, against the premium |
| 54 | one-sided trading, then mid's move | **NO CLEAR PATTERN** at any horizon |
| 55 | book imbalance, then mid's move | **CLEAR PATTERN** at 10 s, 1 and 5 min; none at 15 min |
| 56 | refill after a burst | descriptive, no label |

## #52 — who moves first

*Binance moved first on 142 of 144 coin-days by about 1,060 ms as a recorder sees it. After a 10 bps move on Binance,
Hyperliquid moved 12.6 bps further in the next 5 seconds.*

| clock | mean daily median lag (95% CI) | halves | Binance first / Hyperliquid first / same bin | label |
|---|---|---|---|---|
| Tardis's receipt (primary) | **1,060 ms (985 to 1,133)** | 1,167, 954 | 142 / 0 / 2 | CLEAR LEADER |
| Exchanges' own (robustness) | 792 ms (721 to 860) | 942, 642 | 143 / 1 / 0 | CLEAR LEADER |

The two clocks agree. The lag is nearly the same on all six coins, 1,000–1,100 ms, so thin trading on smaller coins is not
what's driving it. The cause isn't established, and its uniformity could partly reflect how the feeds reach a recorder. The
lag narrowed between the halves on both clocks. The peak correlations are low, 0.03–0.14, at 100 ms steps: this is a
statement about timing on average, not a move-by-move forecast.

**After a large one-second move, the other venue's mean move in that direction:**

| the move came from | events | next 1 s | next 5 s | next 30 s |
|---|---|---|---|---|
| Binance | 4,766 | **+7.11** | **+12.62** | **+13.11** |
| Hyperliquid | 15,870 | +0.10 | +0.14 | −0.01 |

Hyperliquid's own last-trade moves of this size are over three times as common, and Binance doesn't follow them.

**As a stand-in for Hyperliquid:**

| coin | median price gap, bps | 99th percentile, bps | 5-minute return correlation |
|---|---|---|---|
| BTC | 2.76 | 6.41 | 0.990 |
| ETH | 2.76 | 7.41 | 0.991 |
| SOL | 3.02 | 8.51 | 0.989 |
| XRP | 2.84 | 10.62 | 0.978 |
| DOGE | 3.12 | 12.25 | 0.975 |
| LINK | 3.39 | 16.64 | 0.952 |

So Binance's 5-minute moves are a close stand-in for Hyperliquid's on these coins and days. The level differs by about 3 bps.

### Information only, looked at after the read

The registered figures use last trades, which can be stale, so the author checked the catch-up on Hyperliquid's mid
(`research/patterns_info.py`):

| 4,765 Binance moves of at least 10 bps in one second | bps |
|---|---|
| Binance's own move, mean | 13.65 |
| Hyperliquid's mid during that same second | +1.08 |
| from the end of that second, next 1 s | +6.47 |
| next 5 s | +12.92 (median 11.80) |
| next 30 s | +12.88 |

Averaging by day, the next 5 s is +13.64 (95% CI 12.90 to 14.39). **The catch-up is real on the mid and doesn't reverse by
30 s.** It holds on all six coins (+12.0 to +14.4 at 5 s), and all 24 days are positive, between +10.18 and +17.21. The top 3
days hold 35% of the events.

**This looks large against a round trip of about 9.9–10.9 bps, so it needs a plain warning. It isn't shown to be tradable.**

- About half the catch-up is gone 1 second later: from +1 s to +30 s only about 6.4 bps remain, below the fee.
- The measure starts at the end of the one-second bin, and it counts no order latency. It assumes a fill at the mid.
- Hyperliquid's book file is a half-second feed as a recorder received it. The real book may have moved before the file shows
  it, so the fastest participants have probably taken what's visible here.
- These are events selected on a large move on first-of-month days.

#57 then tested this with fills at the book and a stated reaction time: **NOT CAPTURED**, −8.02 bps per event at 1,000 ms
([RESULTS_CATCHUP.md](RESULTS_CATCHUP.md)). Nothing here supports trading it.

## #53 — mark price against index

*When the premium is high for the last two hours, mark moved less over the next N minutes than when it's low. The gap is
−0.6 bps at 1 minute, growing to −5.9 bps at 60 minutes.*

| horizon | high minus low, bps (98.75% CI) | halves | coins with that sign | up after high / low | label |
|---|---|---|---|---|---|
| 1 min | −0.57 (−0.78 to −0.34) | −0.47, −0.68 | 13 of 14 | 42.5% / 46.1% | CLEAR |
| 5 min | −0.99 (−1.50 to −0.46) | −0.55, −1.43 | 13 of 14 | 43.8% / 47.3% | CLEAR |
| 15 min | −2.27 (−3.77 to −0.71) | −0.97, −3.58 | 13 of 14 | 43.8% / 47.3% | CLEAR |
| 60 min | −5.89 (−10.90 to −1.10) | −3.37, −8.40 | 11 of 14 | 43.8% / 48.2% | CLEAR |

- **More than the definitional reversion.** The premium's own change is only −0.97 to −1.84 bps, so at longer horizons most of
  the gap is the whole price, mark and index together.
- **Weak as a direction.** Up shares differ by 3–4 points, and the 60-minute day values run from −24.1 to +10.4. LINK has the
  opposite sign at every horizon. Larger effects are mostly on smaller coins.
- **Possibly not independent of #52.** The index draws on outside venues, so a premium may partly be Hyperliquid not yet having
  caught up. This test doesn't separate the two.
- **22 days, not 24.** No coin has a value on 2024-11-01 or 2025-02-01, and 2025-01-01 has 8. The ticker file's exchange
  `timestamp` looks defective early on: on 2025-02-01 it spans 0.0 hours on BTC despite 41,603 rows. The cause on 2024-11-01
  wasn't checked. They fell out under the registered minimum, and weren't repaired from the other clock.

## #54 — aggressive buying and selling

*Nothing clear: one-sided buying and one-sided selling over 60 seconds were followed by about the same move.*

| horizon | high minus low, bps (98.75% CI) | coins with that sign | label |
|---|---|---|---|
| 10 s | +0.02 (−0.05 to +0.09) | 9 of 14 | NONE |
| 1 min | +0.11 (−0.05 to +0.26) | 9 of 14 | NONE |
| 5 min | +0.01 (−0.31 to +0.30) | 6 of 14 | NONE |
| 15 min | +0.03 (−0.65 to +0.71) | 8 of 14 | NONE |

The author expected short continuation and it didn't appear. This doesn't show there's no effect, and #56's bursts are a
different, rarer event.

## #55 — book imbalance

*When the visible book leans to bids, the next 10 seconds moved 0.4 bps more than when it leans to asks, rising to 1.1 bps at 5
minutes.*

| horizon | high minus low, bps (98.75% CI) | halves | coins with that sign | up after high / low | label |
|---|---|---|---|---|---|
| 10 s | +0.40 (+0.31 to +0.49) | +0.43, +0.37 | 14 of 14 | 45.9% / 39.7% | CLEAR |
| 1 min | +0.70 (+0.52 to +0.92) | +0.60, +0.79 | 14 of 14 | 50.4% / 45.7% | CLEAR |
| 5 min | +1.13 (+0.66 to +1.62) | +1.01, +1.25 | 13 of 14 | 50.7% / 47.6% | CLEAR |
| 15 min | +1.39 (−0.11 to +3.05) | +0.75, +2.03 | 12 of 14 | 50.3% / 48.7% | NONE |

The most consistent pattern here, but about a tenth of a round trip. It measures top-5 levels on Hyperliquid only, and #49, a
different test on Binance's book, stays sealed and unread.

## #56 — how fast the book refills

*After a large burst, the hit side's top-5 depth was back in about half a second at the median, and price moved about 1.3 bps
with the burst over the next minute.*

27,089 bursts on 24 days.

| | all coins | range across coins |
|---|---|---|
| Median refill | **0.52 s** | 0.47–0.61 s |
| Back within 1 s | | 59–72% |
| Back within 5 s | | 74–90% |
| Back within 30 s | | 89–98% |
| Not back within 300 s | 0.9% | |
| Lowest depth as a share of baseline, median | 97% | 89–108% |

| after the burst | mid's move with the burst, bps (95% CI over days) |
|---|---|
| 1 s | +0.71 (0.65 to 0.78) |
| 5 s | +1.11 (0.95 to 1.29) |
| 30 s | +1.25 (1.00 to 1.51) |
| 60 s | +1.26 (1.02 to 1.54) |

**Half a second is the file's resolution, not a measured refill speed.** Snapshots are 0.54 s apart, and timing starts after
the burst's second ends, so a refill inside that second is invisible. The fair reading is "usually within about a second".
Bursts are top 1% for that coin-day, so many aren't large against the book, and a large order relative to depth could behave
differently. The tail matters: on TRX, 11% weren't back within 30 s. The move doesn't reverse in the minute measured.

## How this ran

- All five rules were committed before any new file was downloaded, and the fetch log was read before anything ran. The code
  was unchanged from the registration at the read, confirmed by `git diff`.
- **Not independent.** All five use the same days, and #52, #53 and #55 may share causes. They were the author's own five
  choices, on data other tests had already read, so they count as trials: five rows in `research/trials.csv`.
- **Calm days.** First-of-month days have no known cascade, so none of this says what happens in a crash.
- **Costs, latency and funding aren't in any of the figures.** A CLEAR label is about these days, not a forecast, and
  this isn't investment advice.
