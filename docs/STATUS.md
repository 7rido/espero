# Status — generated 2026-11-10 09:48 UTC by `scripts/status.py`

Nothing here is typed by hand. The ledger is `research/trials.csv`; the run is `state/health.json`.

## The ledger

77 tests: 31 fail, 23 forward_pending, 14 measurement, 7 pass, 1 exploratory, 1 provisional.

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

`last_run` 2026-11-09T12:37:27+00:00 — ok; `last_success` 2026-11-09T12:37:27+00:00

| step | ok | note |
|---|---|---|
| tsmom | yes | mark |
| xs | yes | rebalance |
| mf | yes | rebalance |
| mf-hl | yes | mark |
| liqfwd | yes | mark: longs 47 trades on 10 days (+3.4 bps a day); shorts 54 trades on 10 days (+27.4 bps a day) (paper, gross; decides nothing) |
| lowsfwd | yes | mark: 713 paper trades on 10 days (+19.3 bps a day, gross; decides nothing); 7 coin-days not published yet |
| liqbreak | yes | mark: 443 breaks on 10 days; forced down-breaks bought: 120, -3.8 bps an hour (decides nothing) |
| fundsplit | yes | mark: 15 forced down-breaks, 0 after crowded funding |
| postclose | yes | mark: 6 trading days (BTC+ETH after the close +8.8 bps in 15 min; decides nothing) |
| levpush | yes | mark: 6 trading days (SOL+XRP into the close +8.3 bps; decides nothing) |
| bidsfwd | yes | mark: 295 fills of 713 breakdowns on 10 days (+10.2 bps a fill net; decides nothing) |
| settlefwd | yes | mark: 3 shorts-paying settlements of 240 (-32.2 bps in 30 min; decides nothing) |
| liqhold | yes | mark: forced down-breaks held, net trade-weighted: 4h +18.4 bps over 108; 12h +38.2 bps over 104; 1d +18.2 bps over 103 (decides nothing) |
| publish | yes | published: https://github.com/7rido/espero/releases/tag/data-2026-11-09 |
| dashboard | yes | wrote /Users/fredp/Espero Trading QuantBot/espero/state/dashboard.html |

## Recorded on disk (cannot be fetched again)

| folder | files |
|---|---|
| `data/hlcollect` | 5708 |
| `data/deribit` | 6882 |
| `data/hlbook` | 2944 |
| `data/aggr/forward` | 10 |
| `data/aggr/forward5m` | 10 |
| `data/lows/forward` | 455 |

Verdicts, costs and what a pass leads to: `research/INDEX.md`, `research/FORWARD_FAMILY.md`.
