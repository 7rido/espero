# Getting the data

The repo commits code and small frozen datasets. Most market data, about 2.3 GB on the maintainer's
machine, is **not** in git: every byte comes from a public endpoint, needs no key or account, and
is fetched by the script that uses it. The exception is data recorded live (section 4). It can't
be downloaded again later, so the only copy is the one that was recorded at the time.

All commands run from the repo root, inside the virtualenv (see the README's Quickstart).

**The short version:**

```bash
./scripts/fetch-data.sh live              # the live recordings (sections 3–4), ~20 MB
./scripts/fetch-data.sh archives --no-oi  # the public history (section 2), ~1.6 GB
./scripts/fetch-data.sh status            # what is on disk
```

Using an AI agent? [AGENTS.md](../AGENTS.md) tells it which of these a task needs, and why.

## 1. Already in the repo — nothing to do

| folder | what | used by |
|---|---|---|
| `data/BTCUSD_86400s*.csv`, `data/ETHUSD_86400s.csv` | Coinbase daily candles | `espero matrix`, `espero backtest`, the CI audit table |
| `data/panel/`, `data/panel_hourly/` | the frozen crypto factor panel | #8 (`research/multifactor.py`), `espero factors` |
| `data/panel_peers/`, `data/panel_peers_hl/` | the frozen peers year | `research/peers.py` |
| `data/trend/` | the frozen cross-asset snapshot | `research/trend.py` (runs offline) |
| `data/aggr/explore/`, `data/aggr/holdout/` | aggr's hourly liquidation bars, as #21/#22 froze them | `research/aggr_explore.py`, `research/liqspike.py` |
| `data/degen/` (part) | the bars #10's published numbers came from | `espero degen` |

`./scripts/check.sh` needs only these. A fresh clone passes CI with no download.

## 2. Downloaded on first run — public archives

Each script fetches what it's missing, caches it under `data/`, and reuses the cache after that.
Re-running is safe, and an interrupted download resumes. **Run `research/lows.py` first:** several
others read its 5-minute cache instead of downloading it again.

| order | folder | size | command | source | used by |
|---|---|---|---|---|---|
| 1 | `data/lows/` | ~900 MB | `python research/lows.py` | Binance USDⓈ-M monthly 5-minute klines (`data.binance.vision`) | #20, and the cache #23–#38 read |
| 2 | `data/liq/` | ~110 MB | `python research/liq.py` | Binance USDⓈ-M daily 1-minute klines; Tardis.dev's free liquidation days | #18 |
| 3 | `data/liq2/` | ~30 MB | `python research/liq2.py` | Binance COIN-M liquidations | #26 |
| 4 | `data/oi/` | ~680 MB | `python research/oi.py` | Binance daily metrics (open interest) | #25 |
| 5 | `data/settle/` | ~240 MB | `python research/settle.py` | Binance funding history and hourly perp + spot klines | #19 |
| 6 | `data/levetf/` | ~10 MB | `python research/levetf.py` | Binance 5-minute klines (the months #20 lacks) | #28 |
| 7 | `data/bids/` | ~80 MB | `python research/bids.py` | Binance 5-minute klines (monthly + daily) | #30 |
| 8 | `data/markout/` | ~30 MB | `python research/markout.py fetch` | Binance daily trade prints, reduced per coin-day; the raw file is deleted | #39 (then `... report`) |
| 9 | `data/markout_small/` | ~55 MB | `python research/markout_small.py fetch` | as above, eight smaller coins | #41 (then `... report`) |
| — | `data/bookwalk/` | ~3.3 GB | `python research/bookwalk.py fetch` | Tardis.dev's free Hyperliquid book days | #51 (then `... report`) |
| — | `data/patterns/` | ~3.5 GB | `python research/patterns.py fetch` | Tardis.dev's free Hyperliquid and Binance days | #52–#56 (then `... run 52`, and so on) |
| — | `data/polymarket/` | ~17 MB | `python research/polyhour.py` | Polymarket's public market API | #37 |
| — | `data/cache/` | ~35 MB | fetched by `espero tsmom`, `espero board`, `research/tsmom.py` | Yahoo Finance and FRED | #4, #15 |
| — | `data/funding/` | <1 MB | fetched by the daily job (`fundsplit`) | Binance funding history (`fapi/v1/fundingRate`) | #32 |
| — | `research/data/` | ~70 MB | `python research/pead.py`, `python research/carry.py fetch`, `python research/odds_signal.py` | SEC EDGAR, Hyperliquid, Kraken, odds histories | #5, #6, #11, #12 |

These scripts need only the network: no key, no account. Binance's public archive is reachable from
places where Binance's exchange is not.

Scripts that **download nothing** and read the caches above: `research/levpush.py`, `fillcost.py`,
`sweeps.py`, `horizons.py` (it fetches missing bars), `daymean_audit.py`.

## 2b. The point-in-time store (#48)

`data/pit/`, about 11 GB, needs `pip install -e ".[pit]"` (duckdb, pyarrow) and `research/substrate_fetch.py`. It
holds Binance's prints only for the days #2 and #11 traded, not the whole archive (about 440 GB for those coins);
[research/RESULTS_SUBSTRATE.md](../research/RESULTS_SUBSTRATE.md) says what is and isn't covered. Its hashes are in
`research/pit_manifest.csv.gz`.

## 3. Forward data — recorded by the daily job

The forward tests (#22–#45, judged after 2027-03-31) add one complete UTC day at a time:

| folder | what | written by |
|---|---|---|
| `data/aggr/forward/` | aggr's hourly liquidation bars (Binance, Bybit, OKX) | `espero daily` → `liqfwd` |
| `data/aggr/forward5m/` | aggr's 5-minute liquidation bars | `espero daily` → `liqbreak` |
| `data/lows/forward/` | Binance 5-minute klines, 42 coins | `espero daily` → `lowsfwd` |

To record them yourself, run the job once a day, or install it on macOS:

```bash
espero daily                        # one run: every account, every forward ledger, the dashboard
./scripts/install-launchd.sh        # macOS: every day at 07:30 local time (docs/RUNBOOK.md)
docker compose up -d --build        # any OS: the daily job and the collector (docs/RUNBOOK.md)
```

**aggr keeps its 5-minute bars only for a few days.** A day not saved in that time is gone, and the
plans record it as missing, never filled from another source. Binance's klines in `lows/forward/`
stay in Binance's archive and can be fetched again.

## 4. Live recordings — cannot be downloaded later

| folder | what | how to record |
|---|---|---|
| `data/hlcollect/` | Hyperliquid snapshots: top accounts' positions, HLP and which of its accounts failed to read (#59), asset contexts, 1-minute candles | `espero hlcollect --loop`, `./scripts/install-hlcollect-launchd.sh` (macOS), or `docker compose up -d` (any OS) |
| `data/hlbook/` | Hyperliquid's order book, top 20 levels a side, 10 frozen coins, every 5 minutes | `espero hlbook --loop`, `./scripts/install-hlbook-launchd.sh` (macOS) |

These folders are in `.gitignore` on purpose, under "class 4": git must never see them, so that
`git clean` and `git add -A` can't touch them. The release is their backup.
| `data/book/` | order-book recordings from the fast screen and the testnet rehearsal (#42) | `espero fast`, `research/rehearsal.py` |

Hyperliquid's API serves the current state, not history. A snapshot not taken is never available.
`espero hlcollect --status` shows what is on disk.

## 5. The raw stream — recorded outside `data/`, manifested, not in the weekly release

`espero rawrec --loop` keeps every websocket frame from Binance USDⓈ-M (below), Bybit (USDT perps:
`publicTrade`, `orderbook.50`, `allLiquidation`), OKX (USDT swaps: `trades`, `books`, `liquidation-orders`,
plus a REST book snapshot every 5 minutes) and Hyperliquid mainnet and testnet (`trades`, `l2Book`), on the 14 coins aggr's forward
bars cover, the ten `hlbook` records, and every coin a paper book holds. It writes **only** the folder named by
`ESPERO_RAW_DIR`, never `data/`, as `<venue>/<YYYY-MM-DD>/<HH>.ndjson.zst`: one line per frame with the
receive time and the frame verbatim (`espero/rawrec.py` says the format). The recorder writes
`MANIFEST.sha256` into each day folder once the day is over, the same format as section 4's.

| | |
|---|---|
| install | `ESPERO_RAW_DIR=<folder outside data/> ./scripts/install-rawrec-launchd.sh` (docs/RUNBOOK.md) |
| what is on disk | `espero rawrec --status` (files, bytes, last receive time; never a value) |
| where it was silent | `espero rawrec --gaps 2026-11-03`, from the tape itself |
| check a day later | `python -m espero.manifest check $ESPERO_RAW_DIR/okx/2026-11-03` |
| size | about 2 GB a day with the book channels on, measured over five minutes on 2026-11-02 before Binance streamed (zstd level 9; Bybit's 20 ms deltas and OKX's 400-level books are most of it; Binance's diffs and partial books add to it, measured in `espero rawrec --status`), about 0.2 GB without. Under `FREE_FLOOR_GB` (30 GB) free, the book channels stop and the trades and liquidations continue; the tape says when |

**What it is not.** It is not in `publish-data.sh`'s weekly release: a day is larger than a GitHub release
asset allows, so the only copy is the disk named by `ESPERO_RAW_DIR` and its manifests. It is not a second
recorder into `data/`: the installer and the module both refuse a folder under it. And it is not complete:
the recorder of record is a laptop that sleeps, so every gap is on the tape (`--gaps`) and none is filled
from another source.

**Binance.** The recorder keeps Binance USDⓈ-M's `aggTrade`, `depth@100ms` (diffs), `depth20@100ms` (the top
20 levels whole, every 100 ms, the snapshot the diffs are anchored to), `forceOrder`, `markPrice@1s` and
`bookTicker` through the combined websocket endpoint, which answers from this machine; Binance's REST
(`fapi.binance.com`, HTTP 451) and its single-stream websocket path do not (checked 2026-11-02), so there is no
1000-level REST snapshot here. Beside the live tape, `espero.binance_archive` backfills what
`data.binance.vision` publishes, a day or two late, into `<ESPERO_RAW_DIR>/binance_archive/`: `aggTrades`,
`bookTicker`, `bookDepth`, `metrics`, `premiumIndexKlines`, each verified against its published SHA-256, so a
gap in the live tape (the Mac slept) has prints and quotes to fall back on. **The archive has no liquidation
dataset** (daily and monthly listings checked 2026-11-01, and by the module at each run), and Binance's
`forceOrder` stream, the only source, pushes at most one order per symbol per second: "For each symbol, only
the latest one liquidation order within 1000ms will be pushed as the snapshot." So a liquidation missed live
cannot be backfilled, and even a complete recording sees the throttled stream aggr saw.

## Getting the maintainer's copy

Sections 3 and 4 started on different days on different machines. **For the forward tests'
verdicts, the maintainer's recording is the one of record.** A teammate's own recording is an
independent replica: useful for cross-checking gaps, but it starts on the day it was installed.

The maintainer publishes a snapshot as a GitHub release (`data-YYYY-MM-DD`, made with
`./scripts/publish-data.sh`). The daily job does it every Monday when `ESPERO_PUBLISH_AS` is set
in the maintainer's `.env`, so the latest release is at most a week behind. Anyone fetches it with:

```bash
./scripts/fetch-data.sh live
```

It checks the SHA-256, then extracts into `data/` **without overwriting any file you already have**.
Everything in it is public market data: Hyperliquid's published positions of its largest accounts,
order books, klines and liquidation bars. There is no account information and no key.

Each recorded folder carries a `MANIFEST.sha256`, one line per file, written by the publish script
and checked after the extraction. A file you already had that differs from the release's is
reported, not replaced; a file the release has that you don't is an error. To check a fetched copy
again later:

```bash
.venv/bin/python -m espero.manifest check data/hlcollect data/hlbook data/aggr/forward data/aggr/forward5m
```

On a machine that records, the recorders add files after the manifest was written, so the check
lists them as `extra`. That is expected there; the manifest describes the last release, not the
folder today.

## Troubleshooting

- **A download stops partway:** run the same command again. Cached files are kept, and missing
  ones are fetched.
- **`HTTP 404` on a recent day:** Binance publishes each daily file a day or so late. The forward
  rule (#24's) waits a week before calling a day missing.
- **`HTTP 451` or `403`:** the endpoint refuses your region or network. `data.binance.vision` is a
  static archive and is usually reachable when the exchange is not; try another network.
- **Disk space:** sections 1–2 together are about 2.3 GB. `data/lows/` and `data/oi/` are most of
  it. Skip `research/oi.py` unless you need #25.
