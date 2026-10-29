# What it would take to confirm #39's costs with real fills (nothing is placed)

#39 measures costs on Binance and Hyperliquid prints. A US person can use neither for perpetuals.
The only check that depends on neither the code nor its author is **the exchange's own record of
fills on a venue the account may legally use**. This note says what that check needs. It places
nothing, and nothing in this repo will place it. Every order is the account holder's own act.

Facts below were gathered on 2026-10-29 from public pages and news. Fees and contract sizes change,
so **confirm each against the venue's current published schedule before relying on it.**

## Candidate instruments

| venue | instrument | size of one contract | why it fits | to confirm |
|---|---|---|---|---|
| **Coinbase Financial Markets** (CFTC-regulated FCM, Coinbase Derivatives exchange) | perpetual-style nano BTC and ETH futures (5-year expiry, 24/7, launched 2025-07-21) | 0.01 BTC; 0.10 ETH | the smallest regulated BTC/ETH perp exposure available to US persons, 24/7 like the venues #39 measured | the current fee schedule (news reports put it from 0.02% per contract with a $0.15 minimum, which is **not** from Coinbase); whether SOL and XRP nanos are listed |
| **Kraken Derivatives US** (NinjaTrader Clearing, an FCM; listed on Bitnomial) | US perpetual futures in BTC, ETH, SOL and XRP (plus others), USD-quoted | not in the support article; see Bitnomial's contract specifications | covers all four of #39's coins | the contract multiplier; the four fee parts (exchange, NFA, clearing, per-contract commission); funding times (Kraken's support page says payments post once daily at 15:00 CT; a launch report says 8-hourly at 19:00, 03:00 and 11:00 CT). Either way it is **not** 00/08/16 UTC, so #38's mechanism does not carry over as-is |
| CME Group | Micro Bitcoin and Micro Ether futures | 0.1 BTC; 0.1 ETH | deepest regulated book | not 24/7; dated expiries; a futures broker account; a contract far larger than a test needs |

**Recommendation for a confirmation run: the Coinbase nano BTC contract.** It has the smallest
size, 24/7 hours and a public API. Kraken's US perps are the alternative if SOL and XRP matter.

## What the confirmation would measure

The same three numbers #39 measured, on fills the account actually got.

1. **Taker effective half-spread.**
   - Record the venue's best bid and ask at the moment of each market order: the public
     order-book/ticker feed, recorded by the account holder's own process.
   - Compare with the fill price on the venue's fill record.
2. **Maker fill rate and conservative markout.**
   - Post-only limit orders at the best bid or ask, at the minimum size.
   - Record which filled and when.
   - Record the mid at 1 s, 10 s, 60 s and 300 s after each fill.
   - Compare with #39's conservative bound. It should be close to or worse than the optimistic
     bound; if it is better, the bound is too harsh.
3. **All-in fees per fill**, from the statement, not the schedule.

**Sample size.** About 200 fills of each kind is the smallest sample in which a 1 bp difference in
half-spread is visible against typical noise. Pre-register that number before the first order.
Then compare against #39's table within its own tolerance: max(0.25 bps, 20%).

## How fills reconcile against the exchange's statements

- **Three records per fill, which must agree.**
  - The order acknowledgement and fill messages, from the venue's API. Store them raw, as received.
  - The account's fills/history endpoint, pulled after the session.
  - The FCM's **daily statement**, the legal record. Futures commission merchants issue these to
    every account daily. They show trades, fees and cash adjustments, including funding.
- **The reconciliation table:**
  - Key it on the venue's fill ID.
  - Columns: price, size, side, liquidity flag (maker/taker), fee, timestamp.
  - Any fill present in one record and missing from another is a break and is listed, not dropped.
  - Fees are checked fill by fill against the schedule. Funding is checked against the venue's
    published rate × position.
- **Who holds the credentials.** The account holder creates any API key and stores it in `.env`
  themselves. It is read-only for the reconciliation pull; the repo never sees or prints it. Orders
  are placed by the account holder, by hand or with their own tool, never by this repo's live path.
  That path stays off.

## What would change #39's conclusions

- **Measured taker half-spread on the regulated venue above #39's.** Every re-priced lead loses that
  difference twice per round trip.
- **Maker fills marking out better than #39's conservative bound.** Then the bound was too harsh,
  and Q3 should be re-asked with a fill model calibrated on those fills, as a new pre-registered
  test.
- **All-in fees above the schedule.** Minimum charges at nano size can dominate: $0.15 on a 0.01 BTC
  contract near $110k is about 1.4 bps. Then the hurdle for this account is the statement's number,
  not the venue's headline rate.

Sources:
- [Coinbase perpetual-style futures launch (FOW)](https://www.fow.com/insights/coinbase-hails-arrival-of-perpetual-style-futures-in-us)
- [The Block on the two contracts and July 21 start](https://www.theblock.co/amp/post/359852/coinbase-derivatives-two-us-perpetual-style-futures-contracts-to-begin-trading-on-july-21)
- [Coingape fee report (secondary)](https://coingape.com/coinbase-launches-cftc-regulated-perpetual-futures-in-the-u-s/amp/)
- [Kraken: US perpetual futures (support)](https://support.kraken.com/articles/us-perpetual-futures)
- [Kraken launch announcement (Business Wire)](https://www.businesswire.com/news/home/20260529607011/en/)
