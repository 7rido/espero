# Status — generated 2026-11-02 09:29 UTC by `scripts/status.py`

Nothing here is typed by hand. The ledger is `research/trials.csv`; the run is `state/health.json`.

## The ledger

63 tests: 25 fail, 18 forward_pending, 12 measurement, 6 pass, 1 exploratory, 1 provisional.

| # | status | what | document |
|---|---|---|---|
| 4 | pass | Cross-asset time-series momentum (SPY/TLT/GLD/USO/BTC/ETH) | `research/RESULTS_TSMOM.md` |
| 8 | pass | Multi-factor XS crypto, vol-targeted, turnover-buffered | `research/RESULTS_MF.md` |
| 12 | provisional | Carry with swap gap + maker execution | `research/RESULTS_CARRY2.md` |
| 26 | pass | #18's rule on every day of Binance COIN-M liquidations | `research/RESULTS_LIQ2.md` |
| 40 | pass | Fill-reconciliation plumbing on Hyperliquid testnet | `research/RESULTS_TESTNET.md` |
| 42 | pass | Dress rehearsal of real-fill test on testnet | `research/RESULTS_REHEARSAL.md` |
| 43 | pass | At which holding period do real signals pay? | `research/RESULTS_HORIZONS.md` |

**Forward, judged once after 2027-03-31:** #22, #23, #24, #27, #29, #31, #32, #34, #38, #45, #49, #58, #59, #60, #61, #62, #63, #64. Their running numbers decide nothing and are not shown here.

## The last daily run

`last_run` 2026-11-02T00:49:26+00:00 — dry run (nothing marked); `last_success` 2026-11-01T21:25:36+00:00

| step | ok | note |
|---|---|---|
| tsmom | yes | skipped (dry run) |
| xs | yes | skipped (dry run) |
| mf | yes | skipped (dry run) |
| mf-hl | yes | skipped (dry run) |
| liqfwd | yes | skipped (dry run) |
| lowsfwd | yes | skipped (dry run) |
| liqbreak | yes | skipped (dry run) |
| fundsplit | yes | skipped (dry run) |
| postclose | yes | skipped (dry run) |
| levpush | yes | skipped (dry run) |
| bidsfwd | yes | skipped (dry run) |
| settlefwd | yes | skipped (dry run) |
| liqhold | yes | skipped (dry run) |
| publish | yes | skipped (dry run) |
| dashboard | yes | wrote /Users/fredp/Espero Trading QuantBot/espero/state/dashboard.html |

## Recorded on disk (cannot be fetched again)

| folder | files |
|---|---|
| `data/hlcollect` | 1652 |
| `data/hlbook` | 636 |
| `data/aggr/forward` | 2 |
| `data/aggr/forward5m` | 2 |
| `data/lows/forward` | 123 |

Verdicts, costs and what a pass leads to: `research/INDEX.md`, `research/FORWARD_FAMILY.md`.
