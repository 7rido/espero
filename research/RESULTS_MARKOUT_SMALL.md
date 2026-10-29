# Result — do resting orders earn on thinner coins? (#41)

**Answer: NO on Hyperliquid. "Not established" on Binance, by the frozen rule.** On Binance the
data point the same way, but more steeply.

**The finding is the ladder.** Thinner coins pay the front of the queue more and charge the back of
it more. A resting order at this account's speed loses more the thinner the coin:
- BTC: −0.8 bps before fees;
- TIA: −2.5 bps;
- XTZ: −4.0 bps.

The rank correlation with volume across all twelve coins is +0.97.

Spec: [PREREGISTRATION_MARKOUT_SMALL.md](PREREGISTRATION_MARKOUT_SMALL.md) (`524277f`). Code
`a9a446e`. Run as printed `acafe81`: [markout_small_run.txt](markout_small_run.txt).

## Data

- **Coin-days.** 1,960 jobs, 0 errors. Seven V1 days dropped, all before WLD's and TIA's listings,
  as pre-registered.
- **Sets.**
  - B: 210 days × 8 coins.
  - V2: 7 × 8.
  - H: 24 × 6. XTZ and YFI are not on Hyperliquid.
- **Proxy validation.**
  - **60 s and 300 s**: validated on every coin.
  - **10 s**: validated on six coins; XTZ and YFI failed.
  - **1 s**: validated on none. On thin coins the trade proxy understates how fast the price runs
    against a fill in the first second. Real quotes show −1.01 to −4.96 bps where the proxy shows
    −0.64 to −2.78.

  These cells are excluded, as the rule says.
- **Second source: failed, in 4 of 96 cells.** All four are **optimistic** markouts at 60–300 s on
  WLD, XTZ and YFI, where Tardis and the archive differ by 0.29–0.41 bps against a 0.25 bp tolerance:

  | coin | horizon | Tardis | archive |
  |---|---|---|---|
  | WLD | 300 s | 0.54 | 0.83 |
  | XTZ | 60 s | 1.49 | 1.90 |
  | XTZ | 300 s | 1.44 | 1.84 |
  | YFI | 300 s | 0.25 | 0.61 |

  Every conservative and taker cell replicated. The frozen rule makes one failure enough: **the
  Binance answer is "not established", and no Binance cell of these coins enters
  `espero/costs_table.py`**.

## The answer

0 of 464 cells pass.
- **Hyperliquid** (real quotes, no proxy) is negative at every horizon. Net of the maker fee, the
  best cell is ARB, 300 s, settlement window: −2.1 bps, t −1.3.
- **Binance**: every conservative cell at 60 s or more is negative before fees (136 cells; the best
  is −0.26 bps). The one cell positive before fees is YFI, 1 s, wide spread: +0.70 bps. That horizon
  is unvalidated, and the cell is −1.3 bps after the fee.

## Cost per leg — taker round trip, fees included

| coin | $ a day | Binance half-spread | Binance round trip | Hyperliquid half-spread | Hyperliquid round trip |
|---|---|---|---|---|---|
| DOGE | 600M | +0.77 | 11.53 | +1.11 | **11.22** |
| LINK | 126M | +0.91 | 11.81 | +1.36 | **11.72** |
| WLD | 82M | +1.84 | 13.67 | +2.20 | **13.41** |
| ARB | 41M | +2.41 | 14.82 | +1.95 | **12.90** |
| OP | 33M | +3.55 | 17.10 | +2.42 | **13.83** |
| TIA | 18M | +2.07 | 14.14 | +1.83 | **12.65** |
| XTZ | 6M | +3.82 | 17.64 | — | — |
| YFI | 2M | +3.22 | 16.44 | — | — |

- Hyperliquid's column is in `espero.costs`. Binance's is printed here only, because replication
  failed.
- The repo's assumed 18 bps is still above every measured round trip. On the thinnest coins it is
  close to right.

## The ladder — Binance, "all" cells, 60 s, all twelve coins

| coin | $M a day | half-spread | front of queue (optimistic) | back of queue (conservative) |
|---|---|---|---|---|
| BTC | 13,959 | 0.33 | −0.54 | −0.81 |
| ETH | 11,175 | 0.37 | −0.49 | −0.80 |
| SOL | 2,172 | 0.66 | +0.39 | −1.18 |
| XRP | 796 | 0.54 | +0.10 | −1.10 |
| DOGE | 600 | 0.77 | +0.23 | −1.24 |
| LINK | 126 | 0.91 | −0.17 | −1.52 |
| WLD | 82 | 1.84 | +0.64 | −1.85 |
| ARB | 41 | 2.41 | +0.92 | −2.17 |
| OP | 33 | 3.55 | +2.20 | −2.93 |
| TIA | 18 | 2.07 | +0.07 | −2.52 |
| XTZ | 6 | 3.82 | +1.50 | −4.01 |
| YFI | 2 | 3.22 | +0.74 | −3.50 |

Rank correlation with volume: half-spread −0.94, optimistic −0.70, **conservative +0.97**.

**How to read it.** A thinner coin has a wider spread, and the first order in line earns more of it:
up to +2.2 bps on OP. But a resting order that has to wait its turn fills mostly when someone
informed is about to take the whole level. The wider the spread, the bigger the move that follows.
**Going to smaller coins makes the back of the queue worse, not better.**

## Transparency

- **The Binance answer is withheld by the frozen rule**, though its conservative cells all point the
  same way. The four failing cells are in a measure the answer does not use. That is stated here, not
  used to override the rule.
- **The 1 s proxy failure** means #39's majors at 1 s rested on a proxy that is weaker on thin
  coins. It passed there; here it did not.
- **#41 changes nothing in #39.**

## What this changes

- **"Earn the spread by resting at the touch" is closed across the whole liquidity range** this repo
  trades, $14B to $2M a day, at this account's speed.
- **`espero.costs` prices six more coins on Hyperliquid** (DOGE, LINK, WLD, ARB, OP, TIA). It still
  raises for Binance on these coins.
- **For rules that rest orders on small coins** (#31's 40 coins, #34), the measured back-of-queue
  loss is 1.5–4 bps per fill. That is larger than on the majors, and should be priced in.
