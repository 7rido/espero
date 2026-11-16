# Status — generated 2026-11-16 16:34 UTC by `scripts/status.py`

Nothing here is typed by hand. The ledger is `research/trials.csv`; the run is `state/health.json`.

## The ledger

81 tests: 34 fail, 23 forward_pending, 15 measurement, 7 pass, 1 exploratory, 1 provisional.

| # | status | what | document |
|---|---|---|---|
| 4 | pass | Cross-asset time-series momentum (SPY/TLT/GLD/USO/BTC/ETH) | `research/RESULTS_TSMOM.md` |
| 8 | pass | Multi-factor XS crypto, vol-targeted, turnover-buffered | `research/RESULTS_MF.md` |
| 12 | provisional | Carry with swap gap + maker execution | `research/RESULTS_CARRY2.md` |
| 26 | pass | #18's rule on every day of Binance COIN-M liquidations | `research/RESULTS_LIQ2.md` |
| 40 | pass | Fill-reconciliation plumbing on Hyperliquid testnet | `research/RESULTS_TESTNET.md` |
| 42 | pass | Dress rehearsal of real-fill test on testnet | `research/RESULTS_REHEARSAL.md` |
| 43 | pass | At which holding period do real signals pay? | `research/RESULTS_HORIZONS.md` |
| 66 | pass | HAR volatility forecast from 5-minute bars against #8's 30-day trailing variance, next week | `research/RESULTS_VOLF.md` |

**Forward, judged once after 2027-03-31:** #22, #23, #24, #27, #29, #31, #32, #34, #38, #45, #49, #58, #59, #60, #61, #62, #63, #64, #65, #69, #70, #71, #74. Their running numbers decide nothing and are not shown here.

## The last daily run

`last_run` 2026-11-16T12:39:27+00:00 — ok; `last_success` 2026-11-16T12:39:27+00:00

| step | ok | note |
|---|---|---|
| tsmom | yes | mark |
| xs | yes | rebalance |
| mf | yes | rebalance |
| mf-hl | yes | mark |
| liqfwd | yes | mark: longs 129 trades on 17 days (+15.1 bps a day); shorts 87 trades on 17 days (+16.0 bps a day) (paper, gross; decides nothing) |
| lowsfwd | yes | mark: 1400 paper trades on 17 days (+11.4 bps a day, gross; decides nothing); 7 coin-days not published yet |
| liqbreak | yes | mark: 812 breaks on 17 days; forced down-breaks bought: 222, -10.0 bps an hour (decides nothing) |
| fundsplit | yes | mark: 15 forced down-breaks, 0 after crowded funding |
| postclose | yes | mark: 11 trading days (BTC+ETH after the close +8.0 bps in 15 min; decides nothing) |
| levpush | yes | mark: 11 trading days (SOL+XRP into the close +7.7 bps; decides nothing) |
| bidsfwd | yes | mark: 671 fills of 1400 breakdowns on 17 days (+11.9 bps a fill net; decides nothing) |
| settlefwd | yes | mark: 3 shorts-paying settlements of 240 (-32.2 bps in 30 min; decides nothing) |
| liqhold | yes | mark: forced down-breaks held, net trade-weighted: 4h -4.2 bps over 222; 12h +16.1 bps over 218; 1d -31.1 bps over 215 (decides nothing) |
| publish | yes | published: https://github.com/7rido/espero/releases/tag/data-2026-11-16 |
| dashboard | yes | wrote /Users/fredp/Espero Trading QuantBot/espero/state/dashboard.html |

## Recorded on disk (cannot be fetched again)

| folder | files |
|---|---|
| `data/hlcollect` | 8882 |
| `data/deribit` | 12297 |
| `data/hlbook` | 4749 |
| `data/aggr/forward` | 17 |
| `data/aggr/forward5m` | 17 |
| `data/lows/forward` | 749 |

Verdicts, costs and what a pass leads to: `research/INDEX.md`, `research/FORWARD_FAMILY.md`.
