# Pre-registration — the paper fills, replayed on the recorded book (#62)

Committed **before** any fill is replayed. Written 2026-11-02, the day the raw recorder first ran; no paper
or testnet fill has yet happened on a tape it recorded, so no comparison exists to have been seen. This
document is the contract; the result document will say whether it was met, and nothing below is changed
afterwards. A later idea takes a new number. **A measurement, not a hypothesis test:** a registered
tolerance, no t, no trial spent in the FDR family, and no forward verdict changed by it.

## Question

Every paper book in this repo fills itself at a price it read: #12's carry books at the settled hour's
close, #58/#59's HLP books at the first 1-minute open after the signal, the BTC paper trader at the next
hourly open with a flat 5 bps of slippage. None of them has ever been checked against the book that was
there. This replays each fill as an order arriving on the recorded Hyperliquid book, with a registered
latency, and asks how far the simulated fill sits from the paper one. For the testnet mirror's resting
orders it asks whether the recorded testnet book, with a queue-position model, fills them when the
exchange did.

## The simulator — evaluated first, hand-rolled only for the parts that don't fit

Checked 2026-11-02, both installed in a scratch environment on this Python (3.12):

- **hftbacktest 2.4.4** has a Hyperliquid converter (`hftbacktest.data.utils.hyperliquid`) that reads exactly
  the recorder's dump, one raw `trades` or `l2Book` frame per line with a local receive timestamp; a
  deterministic queue-position model for L2 data (`power_prob_queue_model3`, the one its documentation
  recommends without L3 data); constant and feed-measured order latency (`constant_latency`,
  `intp_order_latency`); partial fills; Binance Futures and Bybit converters too. No OKX converter.
- **nautilus_trader 1.231.0** has Hyperliquid, OKX and Bybit adapters, but they are live data clients, not
  loaders for a recorded tape; its backtest fill models are probabilistic (`ProbabilisticFillModel`,
  `CompetitionAwareFillModel`), not queue position from prints; its `LatencyModel` is comparable.

**Decision: hftbacktest, through a thin adapter** (`espero/replaysim.py`): the recorder's hour files are
turned into hftbacktest's event array by its own converter, and the registered orders are run through its
backtest. Only the comparison, the tolerance and the order list are this repo's. hftbacktest is the `sim`
extra in `pyproject.toml`; when it is absent, the tests of the adapter's pure parts still run and the
replay itself is skipped with that said.

## Data

- **The paper fills, since the recorder started (2026-11-02 01:42 UTC):**
  - `state/carry-maker.db`, `state/carry-taker.db`: `positions` rows (entry at `entry_ts` and `perp_entry`;
    exit at `exit_ts` and the close's perp price). **The perp leg only.** The spot leg is priced on Coinbase
    spot, which the recorder does not keep; it is out of scope and said so in the result.
  - `state/hlp-book.db`, `state/hlp2-book.db`: `trades` rows with `entry_ts`, `entry_px`, `exit_ts`, `exit_px`.
    The window opens 2026-11-05, so none exist yet.
  - `state/paper-btc-usd-hl.db`: `orders` rows with `filled_ts`, `filled_px` (slippage inside), `side`, `size`.
  - `state/carry-maker.db`, `testnet_mirror`: the testnet's own fills (`open_oid`, `open_px`, `open_ts`,
    `open_filled`; the close columns likewise), placed ALO (post-only) at the testnet's touch.
- **The tape:** `<ESPERO_RAW_DIR>/hyperliquid/<day>/*.ndjson.zst` (`trades`, `l2Book`, top 20 levels, every
  change) and `<ESPERO_RAW_DIR>/hyperliquid_testnet/...` for the mirror. A fill whose coin was not yet
  subscribed (the watch adds a book's coin within 15 minutes of its first position) or whose minute lies in a
  recorded gap is **not comparable**, counted and reported.
- **Window:** every fill from the recorder's start to 2027-03-31; judged as below. Nothing before the
  recorder's start is replayed: there is no tape.

## Rule — the order each paper fill becomes

| book | paper fill | replayed as |
|---|---|---|
| carry (perp leg), entry | short at the settled hour's close price, hour T | market sell of `qty_perp` arriving at T + L |
| carry (perp leg), exit | buy at that hour's close | market buy of `qty_perp` arriving at T + L |
| HLP #58/#59, entry and exit | the first 1 m open at or after signal + 60 s (exit: entry + 4 h) | market buy (exit: sell) of `BOOK_USD / px` arriving at that candle's open time + L |
| BTC paper trader | next hourly open × (1 ± 5 bps) | market order of `size` arriving at the bar's open time + L |
| testnet mirror | ALO at the testnet touch, at `open_ts` | limit at `open_px`, arriving at `open_ts` + L, back of the queue (`power_prob_queue_model3(3.0)`), left until the mirror's own cancel or close |

- **L, the latency, is 250 ms** from decision to arrival, and the same from fill to report, fixed now; it is a
  round figure above the recorder's observed feed lag (measured and reported as information). A second
  table at L = 1,000 ms is information only. A market order fills against the levels on the tape at arrival,
  walking the book; hftbacktest's partial-fill exchange model.
- **Fees are the books' own** (`espero.costs`, the venue table) and are not part of the price comparison.
- **The comparison:** `diff_bps = side × (sim_px − paper_px) / paper_px × 10⁴`, positive when the paper fill
  was better than the book allowed (the paper book flattered itself). For the mirror: `filled` agreement
  (both filled, or neither, by the mirror's close time), and `Δt_fill` in seconds where both filled.

## Tolerance, fixed now

- **Taker fills (carry, HLP, BTC):** over all comparable fills, **median |diff_bps| ≤ 5** and **90th
  percentile |diff_bps| ≤ 15**. The signed median is reported beside it, and a signed median above +3 bps is
  reported as "the paper books flatter themselves", information only.
- **Maker fills (the mirror):** **agreement on filled / not filled on at least 80 % of comparable orders**;
  the median |Δt_fill| is reported, not decisive.

## Criteria, judged once

Judged at the first daily run after **30 comparable taker fills and 10 comparable maker orders** exist, or on
2027-03-31 with whatever exists, whichever comes first. Before that, running tables are information only.

1. **(b)** the taker tolerance holds, and
2. the maker agreement holds;
3. **PASS** needs both; **PARTIAL** one; **FAIL** neither; **INCONCLUSIVE** fewer than 10 comparable taker
   fills by 2027-03-31.

No outcome changes any paper book, any forward verdict, or #12's maker-book verdict. A FAIL goes beside the
books as "the paper fills are off by this much on the recorded book", and any sizing document written under
`FORWARD_FAMILY.md` must carry that number.

## Power

Thirty fills put the median within about ±3 bps of its true value if fills scatter with a 10 bps spread,
enough to tell 5 from 15. The 90th percentile at 30 fills is a rough number and is said to be. The mirror's
10 orders give the agreement rate to ±25 %; it is a sanity bar, not a measurement.

## Information only

Per book and side: the distribution of `diff_bps` (median, 10th, 90th), the share of fills that walked more
than one level, the feed lag (receive − exchange time) per venue, the L = 1,000 ms table, fills excluded and
why (no coin on tape, gap, no book within 60 s of arrival), and Hyperliquid's own `userFills` for the mirror
where `espero hl orders` already reads them.

## What this cannot say

A paper fill is not a real fill; neither is a replayed one. The replay walks the book as if the order had no
effect on anyone else, which for $125–$1,000 on these coins is close to true and is still an assumption. The
mainnet tape does not hold mainnet fills of this account (there are none), and the account holder's real
fills, when they exist, are reconciled by `espero.reconcile`, outside this test.

## Procedure

`python research/replaysim.py` reads the journals read-only and the tape, writes `research/replaysim_fills.csv`
(one row per fill: book, coin, side, paper price, simulated price, diff, latency row, comparable or why not)
and prints the tables; `research/replaysim_run.txt` is its output at the judgment. `espero/replaysim.py` holds
the order list, the adapter and the comparison.

## Timestamp

This file's SHA-256 is stamped with OpenTimestamps (`research/PREREGISTRATION_REPLAYSIM.md.ots`,
`scripts/timestamp.sh`) at the commit that adds it, before any fill is replayed; `ots verify` checks it
against Bitcoin once the calendar's attestation is confirmed.
