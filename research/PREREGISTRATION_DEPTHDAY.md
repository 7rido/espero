# Pre-registration — does a day of book imbalance predict the next day? (#49)

Committed **before any imbalance is computed and before its runner is written**. #46 and #47 are taken by
drafts outside this work, and #48 is the last run, so this is #49.

## Hypothesis

Among the most-traded USD-M perps, coins whose book held more bids than asks within 1% of the mid over one UTC
day beat coins with the opposite lean over the next UTC day, after costs and funding.

**The prior against it is stated first.** `research/IDEAS_NOVEL.md` lists "order-book imbalance and queue games"
under "not worth trying here", because firms next to the exchange win that race. This test holds for a day, so it
is not that race, but resting depth can be pulled before it ever trades, so it may say little about real interest.
This repo has found no predictive edge at any horizon, and #48's budget found the 5% level long since spent.

## What has already been seen

- `bookDepth` was read for #48 on the days #2 and #11 traded, and for one spot check of its format, as the ±1%
  dollars at a single moment on each traded side, turned into a sweep cost. **Nobody has computed an imbalance,
  a daily average of depth, or its relation to any return.**
- Daily bars for 1,056 symbols and the 2021–24 universe sample were read for #48.
- The author knows #2's and #11's results and the 2024–26 market in general, as anyone does.
- `data/hlbook/` is not used: it has one slot. Nothing from a forward folder is used.

## Data

Binance USD-M from the public archive, through `espero/pit.py`, each file checked against Binance's SHA-256:
`bookDepth`, `klines` (1-day), `fundingRate`. About 14 GB of `bookDepth` in transit for 20 coins a day, reduced to
one row a coin-day. No key, no order. The holder is a non-US resident; this measures Binance's data and says
nothing about which venue the holder may use.

- **Design:** signal days 2023-02-01 → 2024-12-31. Used to find bugs. Its result is reported, and cannot change
  anything below.
- **Sealed:** entries 2025-01-01 → 2026-09-30, about 638 days, **read once**. It stops at the last month whose funding
  file is published, and well before the forward window that opened 2026-10-30.

## The rule — frozen

1. **Universe** for an entry at 00:00 on day D: `pit.universe_sql(asof = 00:00 D, top_n = 20, lookback_days = 30)`.
   Only what was known by then. Delisted coins stay in history.
2. **Signal** for coin c from day D−1: the mean over that day's snapshots of (N₋₁ − N₊₁) ÷ (N₋₁ + N₊₁), where N₋₁ and
   N₊₁ are the `notional` at percentage −1 and +1. A coin with under 1,440 snapshots that day is out for that entry.
3. **Book:** k = floor(n ÷ 3) of the n eligible coins, equal dollars. Long the k highest signals, short the k lowest,
   ties broken by symbol. Under 12 eligible coins: flat. Rebuilt daily.
4. **Fills** at day D's 00:00 open on the 1-day bar, after the signal. Exit at D+1's open. A held coin with no
   open or no next open counts as a −100% long or +100% short loss and is reported: a hole never reads as flat.
5. **Return** per day: the mean of long returns minus the mean of short returns, per dollar on each side.
6. **Costs:** **10 bps per dollar traded, per side**, on the actual change in weights, with no netting across days beyond
   that change. That is #48's measured 8.2 bps at $10,000 a leg, rounded up for this universe's thinner coins, which
   #48 never priced. 6 and 14 bps are reported as information.
7. **Funding:** each position pays or earns Binance's published rates for settlements in its holding day. A settlement
   exactly at the entry open belongs to the day it opens.

## Pass — all four, on the sealed entries

1. Mean daily net return > 0, with Newey-West **t ≥ 3** (5 lags).
2. Positive in both halves: 2025, and 2026-01 → 2026-09.
3. No single coin provides more than half of the summed gross P&L.
4. Above zero at the 14 bps cost as well.

Anything else is **FAIL**, and is published with the same rigour. A failure gets no variant on this sample: no other
threshold, band, holding period or universe.

## Power

Stated from arithmetic, because any estimate from the data would read it. On 638 days, t = 3 needs an annualised
net Sharpe of about **2.3**, and 80% power needs a true Sharpe near **2.9**. That is a high bar on purpose: at the 5%
level this project already expects false passes. A modest real effect would most likely fail here, and that fail would
not show there is no effect. #48's detector ran hot on another rule (about 8% at a nominal 5%), so the runner must
report this statistic's false-positive rate on synthetic nulls before the read.

## Information only

Deflated Sharpe against the updated inventory; the 2%–5% depth bands; the coins' individual results; a held-for-3-days
view; #48's flow-impact cost per coin. None can change the verdict, and any strong number here would need its own
registration, tested on days after this one's window.

## What each outcome means

- **PASS:** a candidate, not a strategy. It earns a forward paper test with its own plan. No real order follows.
- **FAIL:** the daily ±1% imbalance is closed on this sample. `data/hlbook/` keeps recording, and any Hyperliquid study
  needs its own registration.

## Procedure

Before the sealed read: the runner and its tests are committed, mutation-checked and rehearsed on design days,
refusing to read sealed days unless this file is committed unchanged and no earlier read is on disk. Then one run.
`research/RESULTS_DEPTHDAY.md` records the verdict as committed. **Not started: this file registers the test only.**
