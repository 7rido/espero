# Results — a cost curve by order size on Hyperliquid, from #51's book files (#68)

**On the 20 recorded days with 20 levels, a two-parameter square-root curve fitted on the first ten days priced the
next ten within 0.5 bps a leg on ten of #51's 14 coins, and on three of those (BTC, ETH, SOL) a size-free cost was
already within tolerance. On the other four (BNB, XLM, HBAR, kSHIB) the curve drifted, in every case because the
book got dearer between the two periods, not because the form failed: a plain lookup drifted by the same amount.**
The recorded book answers up to $500,000 on BTC and ETH, $200,000 on SOL and XRP, $100,000 on DOGE and kSHIB,
$50,000 on seven coins and $20,000 on HBAR. This is a measurement: no signal, no return, no edge claim, and no
frozen test changes. `espero.costs` was neither read nor changed.

Registered in `9f4f2d7`. One run. Raw output: [costcurve_run.txt](costcurve_run.txt); every coin-day at every size in
[costcurve_days.csv](costcurve_days.csv); the hour buckets in [costcurve_buckets.csv](costcurve_buckets.csv); the
fitted table in [espero/costcurve_table.py](../espero/costcurve_table.py).

## The registered result

Cost in bps of mid, per leg. c0 and k are the design-day fit of `cost = c0 + k × sqrt(size / $10,000)`; the three
errors are root mean square over the measured sizes on the holdout days. The verdict is checked in the registered
order: FLAT IS ENOUGH before CURVE HOLDS.

| coin | reach | c0 | k | curve error | flat error | lookup error | verdict |
|---|---|---|---|---|---|---|---|
| BTC | $500,000 | 0.068 | 0.054 | 0.022 | 0.140 | 0.025 | FLAT IS ENOUGH |
| ETH | $500,000 | 0.207 | 0.103 | 0.042 | 0.233 | 0.044 | FLAT IS ENOUGH |
| SOL | $200,000 | 0.304 | 0.220 | 0.075 | 0.340 | 0.075 | FLAT IS ENOUGH |
| XRP | $200,000 | 0.250 | 0.512 | 0.179 | 0.775 | 0.173 | CURVE HOLDS |
| DOGE | $100,000 | 0.315 | 0.669 | 0.062 | 0.878 | 0.080 | CURVE HOLDS |
| LINK | $50,000 | 0.414 | 1.208 | 0.033 | 1.030 | 0.084 | CURVE HOLDS |
| ADA | $50,000 | 0.467 | 1.340 | 0.220 | 1.258 | 0.225 | CURVE HOLDS |
| AVAX | $50,000 | 0.174 | 1.174 | 0.268 | 1.184 | 0.276 | CURVE HOLDS |
| BNB | $50,000 | 0.076 | 0.619 | **0.562** | 1.065 | 0.563 | **CURVE DRIFTS** |
| TRX | $50,000 | 0.459 | 1.436 | 0.383 | 1.624 | 0.391 | CURVE HOLDS |
| LTC | $50,000 | 0.765 | 1.253 | 0.136 | 1.070 | 0.138 | CURVE HOLDS |
| XLM | $50,000 | 0.347 | 2.653 | **1.320** | 3.536 | 1.316 | **CURVE DRIFTS** |
| HBAR | $20,000 | 0.530 | 2.801 | **1.144** | 2.629 | 1.144 | **CURVE DRIFTS** |
| kSHIB | $100,000 | 0.257 | 1.981 | **1.262** | 3.549 | 1.279 | **CURVE DRIFTS** |

| verdict | coins |
|---|---|
| FLAT IS ENOUGH | 3 |
| CURVE HOLDS | 7 |
| CURVE DRIFTS | 4 |
| UNKNOWN | 0 |

Every coin had ten design and ten holdout days with a cost at its reach, except XLM with nine design days (no
2024-11-01 file, as #51 recorded). 38,401,565 snapshots, none dropped, no coin-day under 20 levels. Leaving out the one
coin-day seen before the registration (SOL 2025-06-01) changes no verdict.

## What the tables say

1. **The form is free.** On all 14 coins the curve's holdout error is within 0.06 bps of the plain lookup's (LINK the
   widest, 0.033 against 0.084), and on eleven of them within 0.01. The square-root fit neither adds nor loses
   accuracy against the design-day means themselves. What it adds is interpolation: a cost at $7,000 or $35,000,
   which no lookup has.
2. **Every drift is the book getting dearer.** On the four CURVE DRIFTS coins the holdout mean is above the design mean
   at every measured size: BNB's $10,000 cost went from 0.64 to 1.22 bps, XLM's from 2.74 to 4.08, HBAR's from 3.19
   to 4.75 and kSHIB's from 2.04 to 3.63. ADA and AVAX also rose at every measured size and LINK and TRX at the
   middle sizes, all within tolerance. BTC moved by at most 0.02 bps at any measured size, and ETH, SOL, XRP and LTC
   got cheaper. The registration said a drift and a bad fit would look the same; here the
   lookup error settles it, and it was the market, between the two periods, on the smaller coins.
3. **Reach is the file's limit.** Beyond each coin's reach the unfillable share climbs fast: at $500,000 the visible
   20 levels could not hold the order on more than half the snapshots for every coin but BTC, ETH, SOL and XRP. Costs
   printed past the reach in the raw output are on the days the book happened to be deep, and mean nothing.
4. **The hour of the day moves the cost by 5 to 28%, information only.** At $10,000 the dearest four-hour bucket over
   the cheapest is 1.28 on BTC, 1.17 on ETH and XRP, 1.15 on SOL, and 1.05 to 1.14 on the rest. 04:00 to 11:59 UTC is
   the cheapest stretch on most coins and 12:00 to 19:59 the dearest, but the day-bootstrap intervals overlap on every
   coin, so this is a tendency, not a finding.
5. **With #51's floor added, 18 bps still covers the reach on eleven coins.** The round trip is 2 × (4.5 + cost).
   At each coin's reach the floor-adjusted curve gives 0.81 (BTC, $500,000) to 4.2 bps (TRX, LTC at $50,000), a round
   trip of 10.6 to 17.5 bps. It does not cover HBAR at $20,000 (5.05 bps, 19.1 round trip), XLM at $50,000 (6.84,
   22.7) or kSHIB at $100,000 (7.09, 23.2). This uses design-day curves; on the drifting coins the holdout was dearer
   still. Information only: no frozen test's cost or hurdle moves.

## The generated table

`espero.costcurve.cost(coin, usd)` reads `espero/costcurve_table.py` and returns the design-day curve's cost. It
raises for BNB, XLM, HBAR and kSHIB, whose verdict is CURVE DRIFTS, for a size past the reach, and for any coin not
measured. With `adjust=True` it adds #51's validation gap, the coin's own on six coins and 0.562 bps on the other
eight. The table serves a sizing document under `research/FORWARD_FAMILY.md` and nothing else today.

## What this does and doesn't mean

- **For a sizing document:** on the ten usable coins a cost by size now exists up to the reach, with a floor
  adjustment. Beyond the reach the recorded book is unknown, not deep. On the four drifting coins the most recent ten
  days are the better guide, and the design-day curve under-prices them.
- **Not the moments that matter most.** First-of-month days only, no known cascade among them, a displayed book that
  does not react, no latency, nothing beyond 20 levels or between snapshots. A liquidation rule trades in the moments
  this sample is weakest on.
- **Not a trend forecast.** Two periods of ten days say the smaller coins' books thinned between 2025 and 2026; they
  do not say they will keep thinning. The book file's narrowing from 2026-07 means the newer days cannot extend this.
- **The validation gap is carried, not re-measured.** The 0.35 to 0.56 bps a leg by which the walk read below real
  trades (#51) is applied as an adjustment here and may itself have moved.
