# Operator readout — what the free Hyperliquid data shows (#51–#56)

Plain summary of [RESULTS_BOOKWALK.md](RESULTS_BOOKWALK.md) and [RESULTS_PATTERNS.md](RESULTS_PATTERNS.md). **Context for
reading the market, not rules or signals.** It comes from 24 calm first-of-month days from 2024-11 to 2026-10, on Hyperliquid,
with no known crash day among them. Nothing here is a forecast or investment advice. The tools don't use any of it.

| what you can see | what usually followed | how much to trust it |
|---|---|---|
| **A sharp move on Binance** (10 bps or more in a second) | Hyperliquid caught up by about 13 bps within 5 s and stayed there for at least 30 s | **Strong as a description.** Binance moved first on 142 of 144 coin-days, by about a second. About half the catch-up is gone 1 s later, so it's far faster than a person can act on |
| **A sharp move on Hyperliquid alone** | Binance didn't follow (about 0 bps) | Strong as a description. The cause isn't established: it may be Hyperliquid catching up or a stale print |
| **Book leaning to bids or asks** on the top 5 levels | Price leaned the same way by 0.4–1.1 bps over 10 s to 5 min | Consistent on nearly all coins, but tiny: about a tenth of a round trip |
| **A large one-second burst of market orders** | Price moved about 1.3 bps with the burst over the next minute, with no reversal in that minute | Solid, but small |
| **Book after a burst** | Top-5 depth usually back within about a second, and within 30 s in about 96% of cases | The file can't see anything faster. Less reliable on TRX, and for orders large against the book |
| **Mark high against index,** compared with the last 2 hours | Mark did 0.6–5.9 bps worse than when the premium was low, over 1 to 60 min | Weak as a direction: up shares differ by only 3–4 points. LINK goes the other way, and the 60-minute figure swings a lot from day to day |
| **One-sided trading over 60 s** | Nothing clear in either direction | Don't read anything into it from this data |

## What this means when you're watching

- **Treat Binance as the early view of a sharp move.** By the time a move shows on Hyperliquid, Binance has typically already
  made it.
- **A sudden Hyperliquid-only move deserves a check against Binance** before you read it as new information.
- **Binance is a close stand-in for 5-minute moves on the six coins checked:** correlation 0.95–0.99. The price level differs by
  about 3 bps at the median, more on LINK and DOGE at the extremes.
- **Book lean and bursts are context, not reasons on their own.** They're well under the cost of a round trip.

## Costs, from #51

- **About 9–12 bps** for a $1,000 market order round trip, including the fee. 18 bps covered it on all 14 coins measured.
- **At $10,000:** covered on all 14 on the 20 days with a full book file. XLM and HBAR have little margin.
- **At $100,000:** clearly covered only on the largest coins, and often unknown. Thin coins are much more expensive.
- Treat these as a minimum: the costs read about 0.35–0.56 bps a leg below what real trades paid.

## What this can't tell you

- **Crash behaviour.** Every number here is from calm days. Costs, catch-up and refill may all look different in a cascade.
- **Whether anything is tradable.** No figure includes your reaction time or a real fill. The Binance catch-up in particular
  isn't shown to be something you can capture.
- **The future.** These are averages over past days, and the next instance can do anything.

Whether any strategy pays still comes from the forward tests, judged after 2027-03-31.
