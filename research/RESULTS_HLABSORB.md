# Who absorbs forced liquidations on Hyperliquid — not answered

**Verdict, 2026-10-31: the question cannot be answered under this study's constraints. There is no number and no CI.**
The study stopped at step 2's gate, before any market data was read. This is **not** a "stop at retail scale" verdict.
That verdict needs an estimate below the threshold, and there is no estimate. It also says nothing for or against the
mechanism: every claim in [MECHANISM_LIQUIDATION.md](MECHANISM_LIQUIDATION.md) remains untested. No test ran, so
`research/trials.csv` gains no row, and the next free test number is unused.

## Why it stopped

The question needs to know who rested in the book when liquidation orders hit it. That takes order-level history with
owners, or at the least every fill with both addresses and its liquidation flag.

| route | what it would give | why it is out |
|---|---|---|
| Hyperliquid's S3 buckets | fills, L1 transactions, possibly order-level data | requester pays, so it needs an AWS account. **The user declined AWS on 2026-10-31** |
| Own node | order statuses and raw book diffs, from the day it starts | 16 vCPUs, 128 GB RAM, 500 GB SSD, so very likely well over the $400 a year budget (no quote taken). It also has no history before it starts |
| Public API | a named address's fills, current book, funding, vault history | `userFillsByTime` reaches only an address's 10,000 most recent fills. No public endpoint covers all liquidations or all trades. No historical book endpoint |
| Hydromancer Reservoir | fills and liquidations from 2025-07-28 | delivered from AWS S3, requester pays. Its book data is 20-level snapshots |
| `hyperliquid-data` on PyPI | fills, trades, liquidations, L2 history | its S3 data has the same requirement |
| HypeDexer | trade export | its pages disagree on what is free, and its liquidation data is mainly a live feed. Not evaluated further |
| `data/hlbook/` | our own top-20 snapshots | starts 2026-10-31, after the cut-off, has no owners, and takes 5-minute samples |

**The search for other routes was one web search and the API docs, not a survey.** A free source may exist that it missed.

## What was established

From documentation only, not checked against fills:

- **The route of a forced position:** book, then HLP's Liquidator Vault, then auto-deleveraging.
- **The backstop is not open to an outsider** except by depositing in HLP. This is the docs' description; C13 tests it.
- **The bar:** $2,400 a year gross, 48% on $5,000, reading the $2,000 as after $400 of costs. **The user has not yet
  confirmed that reading, nor that "80r" means 80 hours a week.**

## What would reopen it

Any one of these needs a new decision by the user. The memo stands and can be reused.

1. **Use AWS after all, or have someone else fetch and hand over the files.** Listing first, then the size and cost.
2. **Raise the budget** for a node. It would answer only for days after it starts, which conflicts with this study's
   cut-off, and needs months.
3. **A free forward recorder.** The public trades channel shows both addresses at no cost, but carries no liquidation
   flag, so identifying forced fills would be a problem to solve first. It would need a new job, a change to the
   cut-off, and months of recording. Not verified to be workable.

## What can still be checked for free

Place A in the memo, **the HLP deposit**, is the benchmark for everything else. Its public `vaultDetails` history needs no
account or key. It would show HLP's own record against the 48% bar. It would not answer the study's question, because
HLP's return is not a pure liquidation return, and past returns need a stated window ending before 2026-10-30.
**Not run:** the study's rules want a reply before any download.

## Steps not done

Steps 3 to 7 were not started: power, registration, measurement, the real-fill plan and the replication package. There
is no simulator for this study, so nothing needs an "uncalibrated" label.

## Sources

- [Hyperliquid info endpoint](https://hyperliquid.gitbook.io/hyperliquid-docs/for-developers/api/info-endpoint.md)
- [Hyperliquid historical data](https://hyperliquid.gitbook.io/hyperliquid-docs/historical-data), [node requirements](https://github.com/hyperliquid-dex/node)
- [Hydromancer Reservoir](https://docs.hydromancer.xyz/reservoir), [hyperliquid-data](https://pypi.org/project/hyperliquid-data/), [HypeDexer archive guide](https://docs.hypedexer.com/guides/historical-trade-archive), [HypeDexer](https://hypedexer.com/)
