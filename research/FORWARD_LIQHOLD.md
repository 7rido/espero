# Forward test — #26's forced-liquidation bounce, held 4 hours to 1 day (#45)

Committed **before any day of the forward window exists**: the window opens 2026-10-30, and this was
written on 2026-10-29. A paper test: nothing trades. The forty-sixth test in this repo.

## Why

#26 passed. Buying forced down-breaks and holding 1 hour earned +23.5 bps a day-mean. #44 confirmed
it trade-weighted: +19.2 bps, t 3.67, the most robust predictive result here.

Afterwards, as information and in hindsight, #44 priced it at longer holds on the eight coins
`espero.costs` measures, net of cost and funding, trade-weighted:

| hold | 1 h | 4 h | 12 h | 1 day |
|---|---|---|---|---|
| net | −0.7 | **+15.5** (t 3.15) | **+31.3** (t 3.07) | **+55.9** (t 3.37) |

Both years were positive at 4 h and longer. The 1 h leg that #27 tests forward nets about zero on
liquid coins. **If the bounce is tradable at this account's cost, it is at 4 h – 1 day.** Those
numbers were found after looking, on 2023-06 → 2024-10 only, so they can be confirmed only on days
that do not exist yet. This test runs on those days.

> **Amendment 2026-10-29, before the window opens.** The "Why" table above came from an entry 5 minutes
> late. Corrected, net trade-weighted is: 1 h +5.4, 4 h **+21.9** (t 4.38), 12 h **+36.5** (t 3.57),
> 1 day **+60.4** (t 3.63). The rule, the horizons and the criteria below are unchanged. The entry is
> the ledger's `ts`, which is already the next bar's open. With the larger in-sample sizes, the power
> estimate rises to roughly 2.9–3.2 expected t at 4 h.

## Data — fixed

- **Events.** #27's ledger, `espero.liqbreak.ledger`, unchanged:
  - aggr's 5-minute liquidations (Binance USDⓈ-M, Bybit, OKX) on aggr's 14 coins;
  - #26's rule, with forced share and within-day group by `liq.tag`;
  - UTC days **2026-10-30 → 2027-03-31**.
- **The trade.** **Forced down-breaks** (direction −1, group "forced"), bought long.
- **Prices.** Binance USDⓈ-M 5-minute bars as #24 records them (`data/lows/forward/`).
  - Entry: the ledger's `ts`. That is the break bar's close, which is the open of the bar after it, as #26's y.
  - Exit: the close of the bar ending at entry + h.
  - A missing bar drops that trade.
- **Funding over the hold.** Binance's settled rates in (entry, exit], from the public monthly
  archive (`fundsplit.rates`). A long pays positive rates. The verdict waits for March 2027's file.
- **Cost.** Per trade, the Hyperliquid taker round trip from `espero.costs` where it is measured:
  BTC, ETH, SOL, XRP, DOGE, LINK. Where it is not (ADA, AVAX, BNB, TRX, LTC, XLM, HBAR, SHIB), it is
  **18 bps**, the old assumption, which is above every measured round trip on comparable coins.
- **Gaps.** As #27: a day missing in either source is dropped. Trades whose exit falls after the last
  bar on disk are dropped.

## Horizons and the estimator — the repo's rule from #44

- **h ∈ {4 h, 12 h, 1 day}.**
- **Every event counted**, as #26 counts them.
- **Headline: the trade-weighted mean net.** Its t uses the day-clustered residual sums with a
  Newey-West correction across days, with lags = max(1, ⌈h in days⌉). That allows for holds that
  overlap from one day into the next (`espero.audit.trade_weighted_nw`).
- **The day-mean is printed as information.**

## Power — stated now

The in-sample run had 2,803 trades over 16 months on 8 coins. This window is 5 months on 14 coins,
so about 1,500 trades. At the in-sample effect sizes the expected t is roughly 2.2–2.5 per horizon.
**The chance of passing, even if the effect is real at its in-sample size, is about 50–60%.** A FAIL
here is weak evidence against the effect. A PASS is strong evidence for it.

## Evaluation — once, after March 2027's funding file is published

**PASS requires, at one or more horizons, all four:**

1. **It pays.** Trade-weighted net > 0, with a one-sided p clearing **Holm** across the three
   horizons at family α = 0.05.
2. **Not one stretch.** Net > 0 in each half: 2026-10-30 → 12-31 and 2027-01-01 → 03-31.
3. **Not one coin.** Among coins with ≥ 10 trades, more than half have net > 0 at that horizon.
4. **On the measured coins too.** Net > 0 on the six coins whose cost is measured (BTC, ETH, SOL,
   XRP, DOGE, LINK).

**Information only:**
- each horizon's day-mean;
- gross and funding separately;
- the hit rate;
- by coin;
- the 1 h leg, beside #27.

## Outcomes, fixed now

- **PASS**: a document for real-money sizing and execution on a venue a US person may use, written
  before any order. It covers:
  - the venue (Kraken's US perps list BTC, ETH, SOL, XRP, DOGE and others), its fees and funding;
  - position size from #39/#41's measured costs;
  - the reconciliation and position checks proven in #40 and #42.

  The account holder places any order.
- **Anything else: FAIL.** The longer hold is not established. No stopping early on the running
  numbers, and no re-tuning of the horizons.

## Known confounds

- **#27's**: aggr's liquidation data is not #26's COIN-M archive.
- **Unmeasured costs.** Eight of the 14 coins carry an assumed 18 bps, not a measured one. Criterion
  4 guards against the result living only there.
- **Overlapping holds.** At 1 day, holds from one day overlap the next. The Newey-West term is there
  for that.
- **Funding.** Binance's rates are applied to a Hyperliquid-priced trade, as in #43.

## Transparency — what was seen before this

- #26's published results and #44's trade-weighted re-estimate at 1 h – 1 day, on 2023-06 → 2024-10,
  quoted above.
- No day of the forward window exists yet.
