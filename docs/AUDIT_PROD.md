# Production-readiness audit: security, correctness, tests, and the plan

**Written 2026-11-02 and 2026-11-03 on branch `liq-breakout`, from `221d111`, by an agent.** "Production" here means
real orders placed by the account holder under the repo's own discipline (AGENTS.md). The audit is read-only except
for the fixes in section 4. Each fix is its own commit, has a test, and was mutation-checked. Nothing here lifts the
no-mainnet rule, re-tunes a frozen test, reads a forward test's running numbers as a result, or weakens a guard.
Where a fix changes what a running forward account or recorder records, `research/ERRATA.md` says so in the same
commit.

Severity: **critical** (money or a key at risk now), **high** (an order path, a key path or a forward test can go
wrong), **medium** (wrong under a plausible fault), **low**, **info**. "VERIFIED" means reproduced by running code
against the module or a copy of real data in a scratch folder. Line numbers are at `221d111`.

**Overall.** No critical finding. No path signs on mainnet, and no key can leave the machine through code in this
repo. The two most serious things found were plumbing: 68 tests that CI never ran (one failing), and #4's paper
account drifting its share counts with no trade. Both are fixed. Nothing can trade real money today because
`docs/HOLDER_INPUTS.md` is unanswered, so `risk.check` refuses every entry.

## 1. Security

### What holds

- **Secrets.** `.env` is mode 0600 and git-ignored (`tests/test_api_keys.py`). `broker.load_env` reads it and its
  warnings name line numbers only. No key-like string is in a tracked file. `notify.redact` keeps the webhook URL's
  path out of logs. The operator's TOTP secret is read from the environment and never printed or journaled.
- **The only signer.** `espero/hl_exchange.py` builds the SDK only after `guard()` passes: `HL_NETWORK=testnet`,
  `ESPERO_ALLOW_HL_TESTNET=1`, an `HL_API_URL` that is the testnet host (since 44fbd4e), then `HL_PRIVATE_KEY`. The
  exchange is built on the constant `TESTNET_URL` and asserted after construction. Every path that reaches it
  (`espero hl-order`, `hl-orders`, `carry paper --execute-testnet`, `hlp-testnet` through `cli._testnet_exchange`)
  builds `TestnetExchange()` with no injected exchange, so the guard always runs. `approvals.py`, `risk.py`,
  `holder.py`, `watchdog.py`, `livesig.py`, `replay_stack.py` and the recorders import neither the SDK nor
  `hl_exchange`'s exchange: they cannot sign.
- **The webhook.** `notify.webhook` POSTs `{"text": title + message}` to `ESPERO_WEBHOOK_URL` only, once. Messages
  carry step names, error text cut to 200 characters and watchdog notes; no environment value reaches them.
- **Network.** Every endpoint is public and TLS-verified (`urllib` default context; no `CERT_NONE` anywhere).
  Venue names in paths are a fixed tuple; symbols, coins and addresses from responses go into file contents, never
  into paths. `binance_archive` verifies SHA-256 before keeping a file and never extracts a zip. Endpoints:
  Bybit, OKX, Hyperliquid mainnet and testnet, Binance futures and Coinbase websockets (`rawrec`); OKX, Binance,
  Coinbase REST books; Hyperliquid `/info` and the stats leaderboard (`hlcollect`, `hlbook`, `hyperliquid`);
  Deribit's book summary; `data.binance.vision` and its S3 listing; `api.aggr.trade`; Yahoo and FRED (`data`);
  GitHub releases (`fetch-data.sh`).
- **Locks and paths.** `rawrec` holds an `flock` on `<raw>/rawrec.lock`, and `lock.JournalLock` is `flock` too, so a
  crash leaves no stale lock. `rawrec.raw_dir` refuses an unset `ESPERO_RAW_DIR` and any folder under `data/`, after
  resolving symlinks. `state/` and `data/` are the login user's (mode 755 folders, 644 files); the risk is another
  local account reading them, which matters only for the inbox (fixed below).
- **Images and agents.** `.dockerignore` keeps `.env`, `*.db`, `data/` and `state/` out of the image. The launchd
  templates run `.venv/bin/python -m espero ...` as the login user from the repo.

### Findings

| sev | where | finding and scenario | fix or reason left |
|---|---|---|---|
| high, VERIFIED, **fixed** b8ea432 | `scripts/fetch-data.sh:30` | `tar -xzkf` into the repo root kept existing files but placed any new member anywhere under the checkout, and hid tar's errors. A compromised release, or a mistyped `GH_REPO`, could drop `.venv/.../x.pth`, which the next Python start runs. The `.sha256` comes from the same release, so it proves the download, not the publisher. | Members are listed first and the archive is refused if any lies outside the live folders (`fetch-data.sh check-archive`); tar errors are shown again. The fetch list now equals publish-data.sh's, `data/deribit` included, and a test holds them equal (see section 4). |
| high, VERIFIED, **fixed** 84bf725 | `espero/holder.py` `allocated_usd`, `eligible` | The page says an answer counts only in the holder's commit, but the code read the working tree. An uncommitted edit (a stray save, a sibling agent session) allocated capital and named venues. | Only the page as `HEAD` holds it counts (`holder.committed`); no git or a differing page is unanswered. |
| medium, VERIFIED, **fixed** 9502a38 | `tests/test_no_mainnet.py` | The guard that keeps a second signer out missed `from hyperliquid import exchange`, `importlib.import_module(...)`, `__import__("eth_account")` and an `Exchange(` whose first argument is not literally `wallet`. | Matches every `Exchange(` call and the short-name and run-time imports, with a table of spellings it must and must not catch. |
| medium, VERIFIED, **fixed** 44fbd4e | `espero/hl_exchange.py:47` | `"testnet" not in HL_API_URL` let `https://api.hyperliquid.xyz/?testnet` and `https://testnet.evil.example/` through. The exchange is still built on the constant, so this was a guard that lied, not an order path. | The override must parse to the host `api.hyperliquid-testnet.xyz`. |
| medium, VERIFIED, **fixed** 159a66d | `espero/holder.py:52` | `capital_usd = inf` (or `1e999`) parsed, and `risk.Account.base = min(inf, equity)` then sized every cap against the whole account. | Amounts and drawdowns must be finite. |
| low, VERIFIED, **fixed** 1459048 | `espero/approvals.py` `post` | The inbox file carries a live TOTP code until the runner takes it, and was created 0644: any local account could read a code inside its window. | Created 0600. |
| medium, VERIFIED, **fixed** 55b7a6f | `espero/rawrec.py:661,739` | `max_size=None` on the websockets: one huge frame from a faulty or hostile endpoint means unbounded memory, a kill, and a launchd restart loop that reconnects to the same frame. | Frames bounded at 64 MiB. REST reads in `rawrec`, `hlcollect`, `deribit` and `data.http_get` are still unbounded; left, low. |
| low | `pyproject.toml` `hl` extra | `hyperliquid-python-sdk>=0.24` and its chain (installed: SDK 0.24.0, `eth_account` 0.13.7) are unpinned and unhashed. A compromised release would receive the testnet key, and a mainnet key if one ever existed. | Plan, holder step 4: pin and install with `--require-hashes` before any mainnet key. |
| low | `espero/watchdog.py` `sntp_offset` | Unauthenticated SNTP to one server: a spoofed answer forces "refuse trading" or hides a real skew. | Left: a tripwire. Query two servers before the clock gates real orders. |
| low | `espero/approvals.py` `take` | A malformed inbox file is renamed `.unreadable` and kept with its code. | Left: delete or strip the code when the sleeve runner is built. |
| low | `espero/hlcollect.py`, `hlbook.py`, `deribit.py` | No single-writer lock: a manual `espero hlcollect` beside the launchd loop shares the fixed `.tmp` name and can rename a mixed file into place. | Left; AGENTS.md already forbids a second recorder. Add `JournalLock` on the data folder. |
| info | `runner.publish_data` | Monday's publish runs `gh` from `PATH` with that account's token in the child's environment only. `/opt/homebrew/bin` is user-writable: the same trust domain as the user. | None. |
| info | `hyperliquid.post` | Defaults to mainnet `/info` and ignores `HL_API_URL`; only `info_url`/`testnet_post` honour `HL_NETWORK`. Reading only. | None. |

## 2. Code correctness

### What holds

`runner.run_daily` checks `KILL` before the lock, isolates each step, writes `health.json` by rename, and records
`last_success` only on a full, non-dry run. The 07:30 local launchd run lands at 12:30 UTC (11:30 in US summer
time): DST moves the hour but never makes two runs or none in a UTC day. Every forward step works in UTC;
`levetf.at` uses `zoneinfo` America/New_York, and its NYSE holidays and early closes are right through 2027.
`liqfwd`, `lowsfwd` and `liqbreak` rerun idempotently on per-day files, and `lowsfwd`'s `.none` markers record
Binance's missing days. Ledgers are rebuilt whole each run, so no partial-day row survives. `journal.transaction`
rolls back at depth 0 on any exception; WAL lets the daily job read while a loop writes; `JournalLock` keeps
writers to one; `paper.py` replays missed bars in one transaction. `approvals.Ledger` uses `BEGIN IMMEDIATE`,
consumes a code only on success, and its hash chain and append-only triggers hold. `reconcile.startup` covers every
branch. `risk.check` refuses side 0 and non-positive or NaN size, caps reduce-only at what is held, and orders its
stops holder, week, day. `costs.leg` signs and `markout.FEES_BPS` match `venues.py`. `hl_exchange.round_price` is
the identity on every 5-significant-figure grid price, sells round up and buys down. `replaysim.book_at` never reads
a frame after its time. Every latency budget is in seconds, and `classify` reproduces every row's class.
`edgewatch`'s CUSUM cannot hide a decayed edge, and its bootstrap threshold gives 5.0 % false alarms on iid paths.
`hlp_testnet` journals a client order id before the send and looks an unanswered order up by it before sending
again.

### Findings

| sev | where | finding and scenario | fix or reason left |
|---|---|---|---|
| high, VERIFIED, **fixed** a63e665 | `espero/tsmom.py:131` `roll_forward` (#4) | It rolled each position from the last run's mark price by `adj_now / adj_then` read today. Yahoo serves the current day's bar while it forms, so the two prices of that bar differ and the share count moved by (partial / final) every run with no trade: `state/tsmom.db`'s 2026-10-30 mark moved SPY, GLD and USO units; a synthetic run drifts 4 to 11 % in seven marks. | Rolls from a bar already closed at the last run, stored with the row. ERRATA: past rows are not repaired. |
| high, VERIFIED, **fixed** 74c761b | `espero/markout.py:290` `q3` | Under pandas 3 an empty filtered frame maps the fee to a `str` Series and the subtraction raises; `research/markout.py` and `markout_small.py` call it. Hidden because its test never ran (section 3). | Cast to float; equal on every non-empty frame, so no registered number moves. |
| high, VERIFIED, **fixed** 4ff1c46 | `espero/liqbreak.py:30`, `liqfwd.py:40` (#22, #23, #27) | An aggr answer with no bars was saved as the day and never asked for again; its breaks read zero liquidations, and `liq.tag` ranks one or two of them "forced". No such day is on disk. | An empty day is not saved: the step fails naming the day and retries, so a day aggr no longer serves stays a visible gap. ERRATA. |
| medium, VERIFIED, **fixed** 4ff1c46 | `liqfwd`, `liqbreak`, `lowsfwd`, `fundsplit.rates`, `manifest.write`, `rawrec` `instruments.json`, `binance_archive` sidecars | Each wrote with `write_bytes`/`write_text`. A crash mid-write left a truncated file that the next run skips as done, and that breaks eight daily steps every day until deleted by hand. | `manifest.write_atomic`: written beside, fsynced, read back through a gzip or zip check, renamed. |
| medium, VERIFIED, **fixed** 5b6863e | `espero/fundsplit.py:89` `attach` (#32) | The unbounded backward join gave every break in a month Binance's archive has not published yet last month's final rate, so the crowded split ran on a stale rate all month. | Looks back one funding interval (9 h); past it the rate is missing and the break is dropped, as the plan says, until the month is published. The 64 cached monthly files (6,102 settlements) have no internal gap over 9 h, so a complete archive reads as before. ERRATA. |
| medium, VERIFIED, **fixed** bfa249a | `espero/notify.py:32`, `runner.py:210` | A malformed `ESPERO_WEBHOOK_URL` makes urllib raise `ValueError`, which `webhook` did not catch; the runner sends the trade note outside the step's try, so a bad URL crashed `run_daily` after a rebalance with `health.json` unwritten. | Caught in both places. Runner tests no longer load the real `.env`. |
| high, VERIFIED, **fixed** 781ba0f | `espero/replay_stack.py:203` `step` | A last frame older than 60 s but inside the silence limit and the rule's budget made `book_at` return None and `step` raise; a one-sided frame raised too. `espero replay-stack --day` aborted the day. | Reads the last book inside the rule's budget; refuses "no usable book" on none or an empty side. |
| medium, VERIFIED, **fixed** ef70e50, 7f32b61, 781ba0f | `espero/replay_stack.py` `_send`, `startup`, `exit` | Against `FAULTS`: a silent venue at the lookup before a resend raised out of `step`; a restart while the venue was silent recorded a false break that refused every later entry for good; `exit` skipped the clock check; a rule with no latency row passed at exactly 0 ms. | Each fixed with a test: nothing is resent on a silent venue, the startup waits for unresolved orders, `exit` checks the clock, an unbudgeted rule is refused. |
| medium, VERIFIED, **fixed** 59b3b87 | `espero/rungs.py:48,57` | An empty block (no fills, NaN median) was a breach, so two in a row sent a canary back to testnet with nothing measured; a NaN budget let any shortfall pass. | An empty block is not judged unless it carries a break or an alarm; a NaN budget is a breach. |
| low, VERIFIED, **fixed** d0516d0 | `espero/risk.py:246,261,267` | A NaN sigma silently took the 25 % floor ($39,216 of room instead of $20,619 on $10k at 6 % a day); a negative margin rate could divide by zero; a sleeve scale above 1 widened the per-sleeve cap past the base. | Refused on a non-finite sigma or rate; scale capped at 1. No policy number changed. |
| low, VERIFIED, **fixed** 0a2998a | `espero/hl_exchange.py:171` `limit` | A buy below one price step rounded to 0.0 and was sent. | Refused after rounding. |
| medium, VERIFIED, **fixed** 55b7a6f | `espero/rawrec.py` `line`, `FrameDecoder._emit`, `classify` | A pretty-printed JSON frame (a gateway's error body) put raw newlines on the tape and every reader raised at that line, losing the rest of the hour; a frame with odd field types raised in `classify`, which the feed took for a lost connection and reconnected with backoff. | One line per frame; a bad line is a skipped marker; `classify` returns `_ctrl`. |
| medium, VERIFIED, **fixed** e79504b | `espero/tapewatch.py:388` `follow` | One `read()` of the whole hour fed the decoder at once, holding the decompressed hour in memory (a 137 MB Binance hour is about 2 GB; #71's engine peaked at 878 MB); lines flushed just before the hour turned were skipped. | Reads 1 MiB pieces and drains the old hour first. |
| low, VERIFIED, **fixed** c4a116d, de1fabe | `approvals.take`, `watchdog --ack` | An inbox file the runner cannot read raised `OSError` out of `take`; `--ack` rewrote `watchdog.json` with no checks. | Set aside; checks kept. |
| medium, VERIFIED | `espero/rawrec.py:478` `gaps` | Counts `_meta` heartbeats as activity, and the recorder writes one a minute whether or not the socket is up, so `--gaps` and `watchdog --drill-report` never see a venue that stopped sending. | Left: ignoring `_meta` needs a check that Hyperliquid testnet's quiet books do not then read as gaps. Plan, code step 2. |
| medium | `espero/carry_paper.py:348` `_close_at` (#12) | A live hour is priced on Hyperliquid's forming candle, a caught-up hour (Mac asleep) on the closed one, and nothing records which. Hours older than 72 h are dropped with no `events` row. | Left: #12 is frozen; an ERRATA note for its owner, and an `events` row for skipped hours. |
| medium | `espero/xs.py:274` | A second run on a Monday rebalances again and replaces the week's turnover row with 0; a Monday the Mac was off skips the rebalance with no row. | Left: an exploratory account, not a test. |
| medium | `espero/liqhold.py:105` (#45) | With no settlement in the hold (the current month, not yet archived) the trade's funding is 0, so its net reads high until the month is published. | Left: `horizons.funding_over` is #43's frozen code; ERRATA notes it for #45's owner. The ledger is rebuilt after the window. |
| low, VERIFIED | `espero/tsmom.py:129` | `carry_total` is last run's carry plus this run's, not a running sum; the dashboard's "carry to date" is wrong. Cash is right. | Left: sum the column. |
| low | `espero/rawrec.py` `Feed.run`, `coinbase_subscribe` | The retry delay resets on handshake, so a venue that drops after subscribe is retried every second; one Coinbase subscribe message for every product fails whole after a reconnect if one product is unlisted. | Left: needs each venue's documented behaviour checked. |
| low | `espero/rawrec.py` error paths | On a full disk the error handler's own write raises and the recorder restarts every 60 s. | Left: bounded (nothing to record when full; the 30 GB floor stops books first). |
| low | `espero/deribit.py:75` | One instrument name of a new shape fails the whole currency's slot every time. | Left: per-row try. |
| low | `espero/replay_stack.py:85` | Decision-side checks pick frames by exchange time, not receive time, so a replay can see a frame before it arrived. | Left: replay only; use `rt` on the decision side. |
| low, VERIFIED | `espero/risk.py:225` reduce-only | Ignores the venue minimum: a $3 flatten is allowed and rejected by the venue, so dust can keep a stop's "flatten everything" from completing. | Left: the executor rounds dust to the minimum where the venue clips reduce-only. |
| low | `espero/sleeves.py:94` (#63) | A sleeve whose 90 days are literally 0 gets vol 0 and the largest weight. Bites only if zeros are fed instead of NaN. | Left: #63 is frozen; feed NaN. |
| low | `espero/runner.py:142` | A stale lock whose pid was reused raises before `health.json` is written. | Left: the watchdog's 26-hour check catches it. |
| info | `espero/risk.py:130`, `:118` | `day_start`/`week_start` default 0 switch the day and week stops off; Hyperliquid quotes hourly funding where the gate takes 8-hourly. No caller yet. | Hold both in the sleeve runner's tests. |

## 3. Tests and gaps

| sev | where | finding | fix or reason left |
|---|---|---|---|
| high, VERIFIED, **fixed** 74c761b, bdec2b7 | eight files: `test_audit`, `test_costs`, `test_horizons`, `test_horizons_reference`, `test_liqhold`, `test_markout`, `test_markout_reference`, `test_reconcile` | 68 tests were pytest-style functions. CI and `scripts/check.sh` run `unittest discover`, which never collected them; two were failing. #39's and #43's pinned reference numbers were not held by CI. | Converted to TestCases; `tests/approx.py` replaces `pytest.approx`. |
| high, **fixed** ce32149 | `tests/test_shape.py` | "Every module has a test" passed on a file that collects nothing, which is how the above went unseen. | Fails on a module-level `def test_` or a test file that collects no test. |
| medium, VERIFIED, **fixed** 43da3db | `tests/test_risk.py:124` | With the size guard deleted, zero and negative sizes were still refused by the minimum: two of three cases passed for the wrong reason. Reduce-only was shown only under a week stop. | Each case asserts the guard's own reason; reduce-only is held under no capital, a pause, a break and an awaited ack. |
| medium | `tests/test_shape.py` | A module counts as tested if its name appears anywhere in a test's text, a comment included. | Left: require an import. |
| medium | `tests/test_no_mainnet.py` | Still unmatched: `hyperliquid.utils.signing`, `web3`, `eth_keys`, `coincurve`, and a one-line redirect from another module (`hl_exchange.TESTNET_URL = ...`). It scans `espero/`, `research/`, `scripts/` `.py` only. | Plan, code step 3, before any mainnet key exists. |
| medium | `tests/test_hl_exchange.py` (`TestnetMirror`) | Untested: `refresh` when the venue raises, `sync`/`_close` with no book, a cancel that raises, recovery that raises, an empty book, the post-construction `base_url` assertion. | Plan, code step 3. |
| medium | `tests/test_hlp_testnet.py` | `_resolve` is tested for the entry leg only: an exit that never reached the venue, an entry found with 0 filled, fees when `fills()` raises, the kill switch while a leg is in flight, a remainder that rounds to zero. | Plan, code step 3. |
| low | `tests/test_runner.py` | `write_health`'s atomicity and a failing `publish` are untested. | Plan. |
| low | `tests/test_audit_rest.py:55` | "Warnings never quote a value" is held by two substrings; the unclosed-quote branch is never run. | Plan: match every warning against the allowed forms. |
| low | `tests/test_approvals.py:256` | "An order without a code" passes `key=None`, never a wrong code; a tampered proposal's rollback is unpinned. | Plan. |

## 4. What was fixed

Each row is its own commit with a test, and each was mutation-checked: the fix reverted, its test fails.

| commit | fix | mutation check |
|---|---|---|
| 74c761b | `markout.q3` on an empty frame; `test_markout` collected | 2 failures |
| bdec2b7 | seven more test files collected by unittest | 74 run under both runners |
| ef70e50 | `replay_stack._send`: silent venue after a restart | error |
| 9502a38 | `test_no_mainnet` catches every signer spelling | old pattern misses 3 of 3 |
| 84bf725 | `holder` counts only the committed page | 2 failures, two mutants |
| 1459048 | approvals inbox file 0600 | failure |
| 781ba0f | `replay_stack`: no usable book, exit's clock, unbudgeted rule | 2 failures, 2 errors |
| d0516d0 | `risk.check`: NaN sigma, negative rate, scale above 1 | 2 failures |
| 0a2998a | `hl_exchange.limit`: price that rounds to zero | failure |
| 59b3b87 | `rungs`: empty block, NaN budget | failure, error |
| b8ea432 | `fetch-data.sh` refuses members outside the live folders | failure |
| 44fbd4e | `hl_exchange.guard` checks the host | 5 failures |
| 159a66d | `holder` refuses infinite and NaN amounts | failure |
| bfa249a | a failed notification never fails the daily run | 2 errors |
| a63e665 | `tsmom` rolls from a closed bar (ERRATA) | failure, error |
| 4ff1c46 | atomic recordings; an empty aggr day is never saved (ERRATA) | failures in each of three modules |
| 5b6863e | `fundsplit.attach` bounded to one interval (ERRATA) | failure |
| ce32149 | `test_shape`: every test file collects a test | 2 failures |
| 7f32b61 | `replay_stack.startup` waits for unresolved orders | failure |
| 55b7a6f | `rawrec`: one line per frame, bad line skipped, `_ctrl` on odd frames, bounded frames | 1 failure, 3 errors |
| e79504b | `tapewatch.follow`: pieces, drain the old hour | failure |
| c4a116d | `approvals.take` on an unreadable file | error |
| de1fabe | `watchdog --ack` keeps the checks | failure |
| 43da3db | `test_risk`: the guard's own reason; reduce-only under every pause | guard removed: failure |
| 55f88fe | `fetch-data.sh`'s list equals the published one, `data/deribit` included | old list: 2 failures |

No frozen test's rule, data, criteria or committed result changed. `research/trials.csv` did not change, so
`docs/STATUS.md` was not regenerated. **The running agents still run the old code** until each is restarted: the
recorder (`com.espero.rawrec`), #71's engine (`com.espero.livesig`) and the daily job pick up these fixes only at
their next start. The daily job starts fresh each morning. The holder restarts the two loops by rerunning their
install lines, which wait for the old job to stop:

```bash
cd "/Users/fredp/Espero Trading QuantBot/espero" && ESPERO_RAW_DIR="/Users/fredp/Espero Trading QuantBot/espero-raw" ./scripts/install-rawrec-launchd.sh
```

```bash
cd "/Users/fredp/Espero Trading QuantBot/espero" && ESPERO_RAW_DIR="/Users/fredp/Espero Trading QuantBot/espero-raw" ./scripts/install-livesig-launchd.sh
```

## 5. The plan to production

It climbs `research/DEPLOYMENT_LADDER.md`'s rungs through `research/RISK_POLICY.md`'s gate, under
`docs/OPERATOR.md`'s protocol, on the answers in `docs/HOLDER_INPUTS.md`, and repeats none of them. Nothing below
moves a verdict: every rung above the paper twin waits for a PASS judged once after 2027-03-31.

### Blocked on the account holder: only they can do these

1. **Answer `docs/HOLDER_INPUTS.md`, in a commit of their own.** Capital, the drawdown stop, the eligible venues and
   the tax and licensing check (`research/VENUE_NONUS.md`, step zero: the holder is non-US and eligibility is
   theirs), the operator's hours and response time, the TOTP set-up, autonomy, the data budget. Until then
   `risk.check` refuses every entry, and since 84bf725 only the committed page counts. Capital and drawdown figures
   are the holder's; no agent gives financial advice.
2. **Fill `.env` themselves:** `ESPERO_OPERATOR_TOTP` (docs/OPERATOR.md, set-up) and `ESPERO_WEBHOOK_URL`, which is
   defined but empty, so watchdog escalation reaches only this Mac's notification centre.
3. **Restart the loops on the current code** (the two lines above), and run the recovery drill in
   `docs/RUNBOOK.md` and record it there. Once the eight installers in `TestReinstall.NOT_YET` wait for the old job
   (code step 4), rerun those too.
4. **Keys, per `docs/API_KEYS.md`,** before any mainnet key exists: a separate sub-account, withdrawals disabled at
   the venue, an IP allow-list, an API wallet on Hyperliquid, rotation every 90 days. Install the `hl` extra pinned
   and hash-checked in the executor's virtualenv.
5. **The written lift of the no-mainnet rule** (`mainnet_lift`), signed as `research/DESIGN_MAINNET_PATH.md`
   describes, and only after a verdict and a sizing document (`research/TEMPLATE_SIZING.md`) exist.

### Blocked on code, in order

1. **The sleeve runner** (docs/OPERATOR.md, "What is not built"). It consumes the inbox; builds `risk.Account` with
   `day_start`, `week_start`, `peak`, `sigma_daily` and `breaks` from `reconcile.startup`; converts Hyperliquid's
   hourly funding to the gate's 8-hourly; runs `attribution`; and is drilled day by day through `replay_stack` on
   the recorded tape. Its tests hold the two info items of section 2.
2. **The open medium findings of section 2:** `rawrec.gaps` ignoring heartbeats (with a check on quiet feeds), the
   ERRATA notes for #12's forming candle and the carry book's skipped hours, `xs`'s rerun guard, `tsmom`'s
   `carry_total`, `replay_stack`'s receive-time decisions.
3. **The test backlog of section 3,** first the signer's: `test_no_mainnet`'s remaining spellings and redirects,
   `TestnetMirror`'s refusal branches and `hlp_testnet`'s exit-leg recovery. These must be in place before rung 1
   (testnet mechanics) counts any round trip.
4. **Operations:** the eight installers that `bootstrap` straight after `bootout` wait for the old job, as
   `rawrec`'s and `livesig`'s do; #8 needs a run shortly after Monday 00:00 UTC (today's is 12.5 h late, its budget
   8.4 h); #49 has no module computing it; 29 of #24's and #31's 42 coins are not on the raw tape.
5. **The mainnet module,** only after holder step 5, built from `research/DESIGN_MAINNET_PATH.md` with its own
   tests, and `tests/test_no_mainnet.py` rewritten to hold its guards rather than its absence.

### The first five steps

1. The holder answers `docs/HOLDER_INPUTS.md` in a commit and fills the two `.env` values.
2. The holder reruns the `rawrec` and `livesig` install lines so the recorder and #71's engine run the fixed code.
3. The sleeve runner is built and drilled on the recorded tape through `replay_stack`.
4. The signer's test backlog is closed and the eight installers are fixed.
5. The first sleeve whose verdict passes climbs rung 1, testnet mechanics: 50 reconciled round trips, every fault
   drilled, the kill switch drilled, latency inside its budget.
