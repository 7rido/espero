# Runbook — running espero unattended on a Mac

The product is two paper accounts that mark themselves every day and rebalance on their own
calendars. This document is how to keep that running, what to look at when it does not, and how to
stop it.

## Install

```bash
uv venv .venv && uv pip install -e ".[chart,tui,dev]" --python .venv/bin/python
./scripts/check.sh                   # tests + audit table + CLI smoke test
./scripts/install-launchd.sh         # daily at 07:30 local time
```

The installer renders `deploy/launchd/com.espero.daily.plist.template` into
`~/Library/LaunchAgents/com.espero.daily.plist`, runs a preflight with the exact interpreter launchd
will use, and loads the agent. Options are environment variables:

| variable | default | meaning |
|---|---|---|
| `HOUR`, `MINUTE` | `7`, `30` | local time of the daily run |
| `STATE_DIR` | `state/` under the repo | where `tsmom.db`, `xs.db`, `dashboard.html`, `health.json` live (`ESPERO_STATE_DIR` is read too, from the environment or the plist, not from `.env`; see "Where the state lives") |
| `ESPERO_LOG_DIR` | `~/Library/Logs/espero` | rotating `daily.log` plus launchd's stdout/stderr |
| `PYTHON` | `.venv/bin/python` | interpreter |
| `ESPERO_WEBHOOK_URL` | unset | Slack/Discord-style webhook for failures and rebalances |

07:30 local is after the 00:00 UTC crypto close everywhere from Hawaii to Moscow, and after the
previous day's ETF close. launchd runs a missed job when the Mac wakes; it does not run jobs missed
while the machine was powered off, and a day without a mark is just a gap in the equity curve, not
an error.

## What one run does

```
espero daily --state-dir <STATE_DIR>
  tsmom      mark, or rebalance on the first weekday of the month (once)
  xs         mark, or rebalance on Monday; refuses to rebalance if < 30/42 coins are fresh
  dashboard  rewrites dashboard.html
  health     rewrites health.json atomically
```

Each step is isolated. A failure in one is logged, notified, recorded, and the remaining steps still
run. The exit code is 1 if any step failed, 0 otherwise, 3 if another run holds the lock.

## Check it is alive

```bash
launchctl print gui/$(id -u)/com.espero.daily | grep -E 'state|last exit'
cat state/health.json                # last_run, last_success, per-step ok/error/equity
tail -50 ~/Library/Logs/espero/daily.log
open state/dashboard.html
```

`health.json` is the thing to look at first. `last_success` older than two days means the run is
failing or not firing; the `steps` block says which. `python scripts/status.py --print` turns it,
with the ledger and the recordings on disk, into one page (`docs/STATUS.md` is its last snapshot).

## Run one now

```bash
launchctl kickstart gui/$(id -u)/com.espero.daily      # through launchd, as scheduled runs do
.venv/bin/python -m espero daily                       # by hand, same thing, output to the terminal
.venv/bin/python -m espero daily --dry-run             # preflight: no network, no account changes
```

## Pause and resume

```bash
touch KILL          # in STATE_DIR: the next runs do nothing and exit 0 with "paused"
rm KILL             # resume
```

The KILL file pauses marks too. A long pause leaves a gap, nothing else; the accounts resume from
their stored units and cash.

## Things that go wrong

**Yahoo fails.** The fetch retries four times with backoff, then falls back to the CSV cache in
`data/cache/` if it is younger than three days. The XS account refuses to rebalance when fewer than
30 of 42 coins have a close less than two days old (`note` reads `mark (degraded N/42)`); held coins
are marked at their last known price. The TSMOM account has six assets and no such guard: a failed
fetch fails the step, and the previous mark stands.

**Two runs at once.** `daily.lock` holds the owner's pid. A live pid aborts the second run (exit 3);
a dead pid's lock is removed and the run proceeds. The SQLite files are in WAL mode with a 5-second
busy timeout, so even a collision would wait rather than corrupt.

**It rebalanced twice.** It should not: TSMOM checks the account for a rebalance row in the current
month; XS rebalances on Mondays and `INSERT OR REPLACE` on `(ts, note)` means a second Monday run
replaces the first row. If you see two `rebalance` rows in one month, that is a bug; open an issue
with the two rows.

**The laptop was asleep.** Nothing happened. The next wake runs the job once.

**The numbers look wrong.** Every decision row stores the signals the bot saw (`signals` column) and
the weights it chose, separately. `espero tsmom --report` prints the history. The dashboard shows the
stored decision, not a recomputation.

## Remove

```bash
./scripts/install-launchd.sh --uninstall
```

The databases and logs are left in place.

## Where the state lives

Every account, journal, ledger, `health.json`, `dashboard.html`, `KILL` and the home screen's
`paper-books/` live in **one state folder**, `state/` under the repo. Every command resolves it the
same way (`espero.cli.state_dir`): an explicit `--state-dir` or `--state` path; else
`ESPERO_STATE_DIR`; else the current folder if it holds an account; else the project's `state/`.
A bare `--state tsmom.db` means the file in that folder, wherever the command was started from.

Until 2026-11-01 the state lived in the repo root, and the loops installed before then still write
there. **Moving it is a one-time, by-hand step, because a journal moved under a running loop splits
its book.** The installers refuse to start a loop whose book is still in the root, so the order is:

```bash
cd "/Users/fredp/Espero Trading QuantBot/espero" && ./scripts/move-state.sh      # lists what would move; moves nothing
```

1. Stop every writer: `./scripts/install-launchd.sh --uninstall`, `install-carry-launchd.sh --uninstall`,
   `install-hlp-launchd.sh --uninstall`, `install-hlp2-launchd.sh --uninstall`,
   `install-paper-launchd.sh --uninstall`, and any `espero ui` paper loop. The collectors (`hlcollect`,
   `hlbook`) write only `data/` and keep running.
2. `./scripts/move-state.sh --apply`. It refuses if a writer is still loaded, a file is still open,
   or the destination already has a file of the same name.
3. Reinstall the writers with the same five scripts, without `--uninstall`. They find the books in
   `state/`. The paper loop catches up its bars; the hlp books re-read every slot `hlcollect`
   recorded while they were down (`Book.step` walks every slot file it hasn't seen), and before
   2026-11-05 they read nothing at all, so a move done before then costs them nothing.
4. `cat state/health.json` after the next daily run, and `espero ui` shows the same accounts.

A Docker install never had this: its state is the `ESPERO_STATE_DIR` volume (default `docker-state/`).

## The always-on paper trader

`espero paper --loop` runs its rule on Hyperliquid's BTC perp, hourly bars with $500 of paper cash, into
`paper-btc-usd-hl.db`. Fills are simulated; it holds no key and never signs. It reads live candles and funding
from Hyperliquid, not the files the recorders write. It isn't a pre-registered test, and its results count
toward no verdict.

```bash
cd "/Users/fredp/Espero Trading QuantBot/espero" && ./scripts/install-paper-launchd.sh
```

- Check it: `./scripts/install-paper-launchd.sh --status`, or Paper trading on the home screen.
- Stop and remove it: `./scripts/install-paper-launchd.sh --uninstall`. The journal stays.
- It catches up missed bars after a sleep or restart, with their stops, fills and funding.

## #58's paper book

`espero hlp --loop` applies [#58's rule](../research/FORWARD_HLP.md) to each new HLP slot in `data/hlcollect/`,
into `hlp-book.db`. Fills are simulated; it holds no key and never signs. It reads no recorded value before the window
opens on 2026-11-05. The verdict comes from the recordings after 2027-03-31, not from this book.

```bash
cd "/Users/fredp/Espero Trading QuantBot/espero" && ./scripts/install-hlp-launchd.sh
```

- Check it: `./scripts/install-hlp-launchd.sh --status`, and `espero hlp --status --state hlp-book.db`.
- Stop and remove it: `./scripts/install-hlp-launchd.sh --uninstall`. The journal stays.
- It needs the collector running. Slots missed while the Mac slept are lost, and a gap stays a gap.

[#59](../research/FORWARD_HLP2.md) is the same rule with a guard that voids only recorded failed reads. Its book runs
beside #58's, in `hlp2-book.db`:

```bash
cd "/Users/fredp/Espero Trading QuantBot/espero" && ./scripts/install-hlp2-launchd.sh
```

Check it with `./scripts/install-hlp2-launchd.sh --status` and `espero hlp --test 59 --status`.

## #60, the liquidation ladder

[#60](../research/FORWARD_LADDER.md) has no paper book and no loop. It reads the same `data/hlcollect/`
recordings as #58, so the collector is all it needs running. `espero ladder` counts what is on disk by
file name; `espero ladder --verdict` computes the registered verdict once, after 2027-03-31, and
refuses before then (the plan's `python -m espero.ladder` is the same ledger).

## The order-book recorder

`espero hlbook --loop` records Hyperliquid's top 20 levels a side on 10 coins every 5 minutes, into
`data/hlbook/` (not committed), a few MB a day. Public data only; it never signs or trades. The coins are the
top 10 by 24-hour dollar volume at its first run, frozen in `data/hlbook/coins.json`.

```bash
cd "/Users/fredp/Espero Trading QuantBot/espero" && ./scripts/install-hlbook-launchd.sh
```

- Check it with `espero hlbook --status`: slot counts against what a full day holds, never a value.
- Stop and remove it: `./scripts/install-hlbook-launchd.sh --uninstall`. The data stays.
- Slots missed while the Mac slept are lost. A gap stays a gap.
- Don't study these files casually: every look uses up a future holdout. Pre-register first.

## The raw stream recorder

`espero rawrec --loop` keeps every websocket frame from Bybit, OKX and Hyperliquid (mainnet and testnet) on
the forward coins and the paper books' holdings, into the folder named by `ESPERO_RAW_DIR` (docs/DATA.md,
section 5). Public data only; it never signs or trades. It needs `pip install -e ".[raw]"` (zstandard,
websockets). It refuses to start without `ESPERO_RAW_DIR`, and refuses a folder under the repo's `data/`,
where `hlcollect` and `hlbook` already write.

```bash
cd "/Users/fredp/Espero Trading QuantBot/espero" && ESPERO_RAW_DIR="/Users/fredp/Espero Trading QuantBot/espero-raw" ./scripts/install-rawrec-launchd.sh
```

- Check it: `./scripts/install-rawrec-launchd.sh --status`, and `espero rawrec --status` for what is on disk
  (files, bytes, last receive time; never a value). Its log is `~/Library/Logs/espero/rawrec.log`.
- Stop and remove it: `./scripts/install-rawrec-launchd.sh --uninstall`. The recordings stay.
- Watch it live: `espero rawrec --watch BTC,ETH` shows spread, depth within 10 bps, taker flow over a minute,
  liquidations over five, lag and age per venue, refreshed every two seconds from the files being written.
  Information, not a signal: it shows no return. `--read` adds, at the account holder's request, a column of
  words for what the book and flow show with a net lean; it is untested, outside the registry, and written
  nowhere. A rule anyone wants to act on is a numbered pre-registration first.
- Gaps: `espero rawrec --gaps YYYY-MM-DD` shows where the recorder itself was silent (asleep or down). A venue that dropped the connection while the recorder ran shows as `connected: false` heartbeats on the tape, not as a gap. Frames missed either way are gone.
- Disk: about 4 GB a day with every book channel (Binance is over half), 0.3 GB without. Under 30 GB free the
  book channels stop and the trades continue. Point `ESPERO_RAW_DIR` at a disk with room (the Mac's own holds
  about a month); the folder is not in the weekly release.
- Binance streams through its combined websocket endpoint; its REST answers 451 here, so the top-20 partial
  book is the snapshot and `espero.binance_archive` backfills the public archive for gaps. Don't study the
  tape casually: every look uses up a future holdout. Pre-register first.

## The Hyperliquid collector

`espero hlcollect --loop` records what Hyperliquid shows only in the present, for ideas 3, 4, 10 and
14 in `research/IDEAS_NOVEL.md`:
- every 5 minutes, each perp's funding, premium, open interest and prices;
- every 15 minutes, the positions of HLP's sub-accounts;
- every hour, the positions and liquidation prices of the top 2,000 accounts by account value;
- every day, yesterday's 1-minute candles.

It reads public data only and never signs or trades. Its own launchd agent keeps it running:

```bash
cd "/Users/fredp/Espero Trading QuantBot/espero" && ./scripts/install-hlcollect-launchd.sh
```

- Check it: `./scripts/install-hlcollect-launchd.sh --status`, and `espero hlcollect --status` for
  what is on disk. Its log is `~/Library/Logs/espero/hlcollect.log`.
- Stop and remove it: `./scripts/install-hlcollect-launchd.sh --uninstall`. The data stays.
- Data goes to `data/hlcollect/` (not committed), roughly 12–17 MB a day.
- A restart fetches only the slots not on disk. Slots missed while the Mac slept are lost:
  Hyperliquid keeps no history of positions, and only about three days of 1-minute candles.

## Running it in Docker — any machine

`Dockerfile` and `docker-compose.yml` package the same two jobs launchd runs here: the Hyperliquid
collector and the daily job. They run on Linux, Windows or a Mac with Docker (or OrbStack), and on a
server unchanged. No key goes into the image (`.dockerignore` excludes `.env`, every `*.db` and
`data/`).

```bash
docker compose up -d --build     # start both; restarted if they stop or the machine reboots
docker compose ps                # running?
docker compose logs -f daily     # the daily job's output
```

| | |
|---|---|
| `hlcollect` | `espero hlcollect --loop` into `data/hlcollect/` |
| `daily` | `espero daily` once per UTC day at or after `ESPERO_DAILY_UTC` (default 07:30). It checks every 10 minutes, so a day missed while the machine slept runs when it wakes, as launchd's catch-up does |
| `ESPERO_DATA_DIR` | host folder mounted as `data/` (default `./data`) |
| `ESPERO_STATE_DIR` | host folder for the books, `health.json`, the dashboard and logs (default `./docker-state`) |

**What Docker does not change:**

- **A sleeping or powered-off machine records nothing.** On a Mac, Docker runs inside a virtual
  machine on the same laptop. Only an always-on machine closes those gaps.
- **Never run two collectors into one folder.** On a machine that already records with launchd,
  either stop launchd's agents first or set `ESPERO_DATA_DIR` to another folder, so the container
  becomes a separate replica.
- **It doesn't publish.** The Monday release needs the maintainer's GitHub token, which isn't in the
  container. That stays with the maintainer's launchd job.
- **A teammate's recording is a replica.** It starts on the day it's started. Fetch the
  maintainer's history first: `./scripts/fetch-data.sh live`.

## Live trading

There is none. The Coinbase order path (`espero live`) was removed on 2026-11-01: it had never been
reconciled against a venue and served strategies that failed. The only code that signs anything is
`espero/hl_exchange.py`, on Hyperliquid's testnet, for #12's maker mirror. A real order is the account
holder's own act, outside this repo.
