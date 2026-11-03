# Production-readiness audit: security, correctness, tests, and the plan

**Written 2026-11-03 on branch `liq-breakout` at `221d111`, by an agent, read-only except for the fixes listed in
section 4.** "Production" here means real orders by the account holder under the repo's own discipline (AGENTS.md).
Nothing in this audit lifts the no-mainnet rule, re-tunes a frozen test, or weakens a guard. The audit was cut short
by a usage limit: section 5 says what was not finished.

Severity: **critical** (money or a key at risk now), **high** (an order path or a forward test can go wrong),
**medium** (wrong under a plausible fault), **low**, **info**. "VERIFIED" means reproduced by running code.

## 1. Security

What holds, checked by reading and by running the tests:

- `.env` is `0600`, git-ignored (`tests/test_api_keys.py`), read only by `broker.load_env`, whose warnings name
  line numbers and never a value. No key-like string is in a tracked file.
- `espero/hl_exchange.py` is the only signer. `guard()` checks `HL_NETWORK=testnet`, `ESPERO_ALLOW_HL_TESTNET=1`,
  a testnet `HL_API_URL` if any, and only then reads `HL_PRIVATE_KEY`; the SDK is built on the constant
  `TESTNET_URL` and asserted after construction. Every path that reaches it (`cli._testnet_exchange` for
  `hl-order`, `hl-orders`, `carry paper --execute-testnet`, `hlp-testnet`) builds `TestnetExchange()` with no
  injected exchange, so the guard runs. `approvals.py`, `risk.py`, `holder.py`, `watchdog.py` and `livesig.py`
  import neither the SDK nor `hl_exchange`: they cannot sign.
- `notify.webhook` POSTs `{"text": title + message}` to `ESPERO_WEBHOOK_URL` only, one attempt, and redacts the
  URL in its own log line. Messages carry step names, error strings cut to 200 characters, and watchdog notes; no
  env value reaches them. `notify.macos` quotes through `json.dumps`.
- Recorders (`rawrec`, `hlcollect`, `hlbook`, `deribit`) read public endpoints and sign nothing; `rawrec.raw_dir`
  refuses an unset `ESPERO_RAW_DIR` and any folder under `data/`; hour files are named from the clock, never from
  a venue's symbol. `rawrec` holds an `flock` on `<raw>/rawrec.lock`; `lock.JournalLock` is `flock` too, so a
  crash leaves no stale lock.
- `data.http_get` is `urllib` with TLS verification on; a 4xx other than 429 is not retried.
- The launchd templates run `.venv/bin/python -m espero ...` from the repo as the login user; `PATH` includes
  `/opt/homebrew/bin` (user-writable: same trust domain as the user). `.dockerignore` keeps `.env`, `*.db`,
  `data/` and `state/` out of the image.

Findings:

| sev | where | finding | fix |
|---|---|---|---|
| high, VERIFIED, **fixed** (84bf725) | `espero/holder.py` `allocated_usd`, `eligible` | The page says an answer counts only in the holder's commit, but the code read the working tree: any uncommitted edit of `docs/HOLDER_INPUTS.md` (a stray save, a sibling session, any process with write access) allocated capital and named venues. | `holder.committed` compares the page with `git show HEAD:`; a differing page, a page outside a checkout or no git counts as unanswered; `problems()` says so. |
| medium, VERIFIED, **fixed** (9502a38) | `tests/test_no_mainnet.py` `SIGNING` | The guard that keeps the repo free of a second signer missed `from hyperliquid import exchange` + `exchange.Exchange(acct, ...)`, `importlib.import_module("hyperliquid.exchange")`, `__import__("eth_account")` and any `Exchange(` whose first argument is not literally `wallet`. | The pattern now matches any `Exchange(` call, the short-name import and the run-time imports; the test lists spellings it must catch and innocents it must not. |
| low, VERIFIED, **fixed** (1459048) | `espero/approvals.py` `post` | The inbox file holds the operator's live TOTP code until the runner takes it and was created with the umask (0644): any local account could read a code inside its 60-second window. | Created `0600`. |
| low | `espero/approvals.py` `take` | An unreadable inbox file is renamed `.unreadable` and kept, code included. | Delete it, or strip the code, when it is set aside. Left. |
| low | `pyproject.toml` `hl` extra; the executor's venv | `hyperliquid-python-sdk>=0.24` and its chain (`eth_account 0.13.7`, `requests`, `msgpack`) are unpinned and unhashed; a compromised release would receive the testnet key, and would receive a mainnet key if one ever existed. Installed today: SDK 0.24.0. | Before any mainnet key: pin the `hl` extra, install it with `pip install --require-hashes` from a lock file kept in the repo, and record the versions in the sizing document. Holder's venv; plan step. |
| low | `espero/watchdog.py` `sntp_offset` | SNTP over UDP to `time.apple.com`, unauthenticated: a spoofed answer can force "refuse trading" (a denial) or hide a real skew. | Query two servers and refuse on disagreement; or accept, since the check is a tripwire. Left. |
| low | `espero/runner.py` `publish_data` | Monday's publish runs `gh` from `PATH` with that account's token in the child's env only. A compromised `gh` on `/opt/homebrew/bin` is in the user's own trust domain. | Note only. |
| info | `espero/cli.py` `_cmd_hl_account --mainnet` | Reads mainnet account state by public address; no key, no signature. Correct as documented. | none |

## 2. Code correctness

Checked and sound: `runner.run_daily` checks `KILL` before the lock, isolates every step, writes `health.json` by
rename, and records `last_success` only on a full non-dry run; `runner.Lock` is `O_EXCL` with a stale-pid sweep
(a reused pid fails safe: the run aborts); `journal.transaction` rolls back on any `BaseException` and nests by
depth; WAL lets the daily job and the dashboard read while a loop writes, and `JournalLock` keeps writers to one;
`approvals.Ledger` uses `BEGIN IMMEDIATE`, authenticates last, consumes a code only on success, and its hash chain
and append-only triggers hold (`tests/test_approvals.py`); `reconcile.startup` compares positions within half a
step and orders by client id, and on a shared account compares only its own orders; `risk.check` refuses side 0,
negative and NaN notional, cuts inf to the tightest room, caps reduce-only at the held notional, and orders its
stops holder > week > day; `costs.leg` signs and `markout.FEES_BPS` agree with `venues.py`; `hl_exchange.round_price`
is the identity on every 5-significant-figure grid price for szDecimals 0 to 5, a sell rounds up and a buy down;
`replaysim.book_at` never picks a frame after the time; `latency` budgets are all in seconds and `classify`
reproduces every row's class; `edgewatch`'s CUSUM cannot hide a decayed edge and its bootstrap threshold gives
5.0 % false alarms on 4,000 iid paths. `hlp_testnet.Executor` journals the client id before the send and looks an
unanswered order up by it before anything new is sent.

Findings:

| sev | where | finding | fix |
|---|---|---|---|
| high, VERIFIED, **fixed** (74c761b) | `espero/markout.py:290` `q3` | Under pandas 3 an empty filtered frame maps the venue to a `str` Series and `s["mean"] - fee` raises `TypeError`; `research/markout.py:505` and `markout_small.py:172` call it. Hidden because the test that covers it was never run (section 3). | `.astype(float)`; equal on every non-empty frame (checked on #39's fixture), so no registered number moves. |
| high, VERIFIED | `espero/replay_stack.py:203` `Stack.step` | A last frame older than `replaysim.MAX_BOOK_AGE_MS` (60 s) but inside the silence limit (120 s) and the rule's budget: `book_at` returns None and `book["bids"]` raises `TypeError`; a one-sided frame raises `IndexError`. `espero replay-stack --day` aborts the day. | Refuse "no usable book" when `book is None` or a side is empty. **Not fixed (usage limit).** |
| medium, VERIFIED, **fixed** (ef70e50) | `espero/replay_stack.py` `_send` | The "sent before" branch asked the venue without catching `VenueSilent`: a restart during a silent window raised out of `step()`, against the `restart` and `venue_silent` rows of `FAULTS`. | Journals "no answer", sends nothing, asks again next step; a test holds both faults together. |
| medium, VERIFIED | `espero/replay_stack.py:211` `Stack.exit` | The exit skips `watchdog.clock_ok`: with the clock 5 s off an exit is still sent, against `FAULTS["clock_skew"]`. | Check the clock first in `exit` too. **Not fixed.** |
| medium, VERIFIED | `espero/rungs.py:48,57` `breach`, `step` | `breach` says a block too small to judge is not a breach, but `Block(fills=0, median=nan)` is one (`not isfinite`), and two empty blocks in a row send a canary back to testnet; a NaN `budget_bps` is never a breach. | In `step`, return `state` for a short block unless the breach is a break or an edgewatch alarm; a non-finite budget is a breach. **Not fixed.** |
| low, VERIFIED | `espero/risk.py:261,267` `check` | A NaN sigma gives `max(0.25, nan) == 0.25`, the same as a missing coin ($39,216 cap on $10k venue equity instead of $20,619 at sigma 0.06); a negative `mmr` equal to `-need` divides by zero. | Refuse on a non-finite sigma and a negative mmr. **Not fixed.** |
| low, VERIFIED | `espero/risk.py:246` `check` | `sleeve_scale` above 1 is not clamped: scale 3 gives a per-sleeve cap of $30,000 on $10k (leverage and per-venue still bind, so nothing exceeds capital). | `scale = min(1.0, scale)`, as RISK_POLICY.md's wording intends. **Not fixed.** |
| low, VERIFIED | `espero/risk.py:225` `check` reduce-only | Ignores `order.min_notional`: a $3 flatten is allowed and the venue rejects it, so dust can keep a week or holder stop's "flatten everything" from completing. | Say so in the ruling; the executor rounds dust up to the venue minimum where the venue clips reduce-only. Left. |
| low | `espero/replay_stack.py:85,203` | Decision-side checks select frames by exchange time `t`, not receive time `rt`: a frame with `t <= now < rt` is seen before it arrived (feed lag, up to `LATENCY_INFO_MS`). Fill side is right. | Filter by `rt <= now_ms` on the decision side. Left; replay only. |
| low, VERIFIED | `espero/replay_stack.py:191` | A rule with no latency row gets budget 0 and is refused only by strict `>`; with `emitted_ms` None in `main()` the stale check passes at 0 ms. | Refuse "no latency budget" outright. **Not fixed.** |
| low, VERIFIED | `espero/hl_exchange.py:171` `limit` | The rounded size is checked but not the rounded price: a buy below one price step rounds to 0.0 and is sent (the venue rejects it). | `if px <= 0: raise ValueError` after rounding. Left. |
| low | `espero/sleeves.py:94` via `portfolio.vol_scaled` | A sleeve whose trailing 90 days are literally 0 has vol 0, weight `inf` clipped to the cap: the largest weight for the quietest sleeve. Bites only if non-trading days are fed as 0 rather than NaN. | #63 is frozen; record in ERRATA and feed NaN, not 0. Left. |
| low | `espero/watchdog.py:108` `check_daily` | A run paused by `KILL` writes `ok: false` with no steps, so the alarm reads "the last run had a failed step: " with an empty list. | Say "paused by KILL" instead. Left. |
| info | `espero/risk.py:130` `Account` | `day_start`/`week_start` default 0 switch the day and week stops off: the live account builder must set them (`replay_account` does). | Hold it in the sleeve runner's tests when it exists. |
| info | `espero/risk.py:118` `funding_8h` | Hyperliquid quotes an hourly rate; a caller passing it as `funding_8h` understates funding 8x. No caller yet. | Convert at the venue adapter. |

Not reached (usage limit): the day-handling questions on the forward steps (`liqfwd` to `liqhold`, `carry_paper`,
`hlpbook`: a day read twice or skipped silently, partial-day writes, DST on the 07:30 local run), the recorders'
response handling (`hlcollect`, `hlbook`, `deribit`, `binance_archive`, `aggr`, `tapewatch.follow`'s whole-file
read), and `scripts/`. Three reviews of exactly these were in flight when the limit hit; section 5.

## 3. Tests and gaps

| sev | where | finding | fix |
|---|---|---|---|
| high, VERIFIED, **fixed** (74c761b, bdec2b7) | `tests/test_audit.py`, `test_costs.py`, `test_horizons.py`, `test_horizons_reference.py`, `test_liqhold.py`, `test_markout.py`, `test_markout_reference.py`, `test_reconcile.py` | 68 tests were plain pytest-style functions; CI and `scripts/check.sh` run `unittest discover`, which never collected them. Two were failing (the `q3` finding above). #39's and #43's reference numbers were therefore not held by CI. | Each is now a `TestCase`; `tests/approx.py` replaces `pytest.approx`; 74 tests run under both runners. |
| medium | `tests/test_shape.py` `test_every_module_has_a_test` | A module counts as tested if its name appears anywhere in `tests/`; a mention is not a test. | Require a `test_<module>.py` or an import of the module. Left. |
| low | `tests/test_replay_stack.py` | Each `FAULTS` row had one test, none for two faults together (restart + silence) or for the book-age window between 60 s and 120 s. | The first is added (ef70e50); the second goes with the `book_at` fix. |

The untested-failure-path review of `hl_exchange`, `hlp_testnet`, `watchdog`, `livesig`, `runner`, `journal`,
`notify`, `broker`, `rawrec` and `tapewatch` was in flight at the limit; not reported here.

## 4. What was fixed, each in its own commit, each mutation-checked

| commit | fix | mutation check |
|---|---|---|
| 74c761b | `markout.q3` on an empty frame under pandas 3; `test_markout` collected | revert → 2 failures |
| bdec2b7 | seven more test files collected by unittest | n/a (74 pass both ways) |
| ef70e50 | `replay_stack._send` silent venue after a restart | revert → error |
| 9502a38 | `test_no_mainnet` pattern catches every signer spelling | old pattern misses 3 of 3 |
| 84bf725 | `holder` reads the page only as HEAD holds it | `committed` forced True → 2 failures; gate removed → 2 failures |
| 1459048 | approvals inbox file `0600` | revert → failure |

No frozen test's rule, data, criteria or result changed; no guard was weakened; `docs/STATUS.md` was not
regenerated (the ledger did not change).

## 5. The prod-readiness plan

It follows research/DEPLOYMENT_LADDER.md's rungs, research/RISK_POLICY.md's gate, docs/OPERATOR.md's protocol and
docs/HOLDER_INPUTS.md's questions, and repeats none of them. Nothing below moves a verdict: every rung above the
paper twin waits for a PASS judged after 2027-03-31.

**Blocked on the account holder (only they can do these):**

1. Answer docs/HOLDER_INPUTS.md in a commit of their own: `capital_usd`, `stop_drawdown`, `venues_eligible` and
   `tax_and_licensing_checked` (research/VENUE_NONUS.md, step zero; the holder is non-US and eligibility is theirs),
   the operator's hours and response time, `totp_set_up`, `autonomy`, `data_budget_usd_month`. Until then `risk.check`
   refuses every entry, and since 84bf725 only the committed page counts.
2. Set `ESPERO_OPERATOR_TOTP` and `ESPERO_WEBHOOK_URL` in `.env` (the latter is defined but empty, so watchdog
   escalation reaches only the notification centre).
3. Rerun the eight installers that `bootstrap` straight after `bootout` (`TestReinstall.NOT_YET`) once they are
   fixed, and rerun the livesig install line so the engine writes its heartbeat; run the recovery drill in
   docs/RUNBOOK.md and record it.
4. Keys per docs/API_KEYS.md: a separate sub-account, withdrawals disabled at the venue, an IP allow-list, an API
   wallet on Hyperliquid, rotation every 90 days. Pin and hash-check the `hl` extra in the executor's venv.
5. The written lift of the no-mainnet rule (`mainnet_lift`), signed as research/DESIGN_MAINNET_PATH.md describes,
   only after a verdict and a sizing document exist. Capital and drawdown figures are theirs; no agent advises.

**Blocked on code (in order):**

1. Fix the four open replay-stack and gate findings above (`book_at` None, `exit` clock, no-budget refusal, NaN
   sigma and negative mmr, scale clamp), each with a test; then fix `rungs.step` for short blocks.
2. Finish the three unfinished reviews (forward-step day handling, recorders, test gaps) and act on them.
3. The sleeve runner (docs/OPERATOR.md, "What is not built"): consumes the inbox, builds `risk.Account` with
   `day_start`, `week_start`, `peak`, `sigma_daily` and `breaks` from `reconcile.startup`, runs `attribution`, and
   is drilled through `replay_stack` on recorded days.
4. #8 needs a run shortly after Monday 00:00 UTC (today's is 12.5 h late, budget 8.4 h); #49 has no module or step
   computing it (`forward_pending` in trials.csv); 29 of #24's and #31's 42 coins are not on the raw tape.
5. The mainnet module from research/DESIGN_MAINNET_PATH.md, only after the holder's lift, with `tests/test_no_mainnet`
   rewritten to hold the new guards rather than the absence of the module.

**The first five steps, ordered:** the holder answers HOLDER_INPUTS (1 above); the five open code findings are fixed
and the unfinished reviews completed; the sleeve runner is built and drilled on tape through `replay_stack`; the
`hl` extra is pinned and hash-checked and the installers' bootout race fixed; rung 1 (testnet mechanics: 50 round
trips, every fault drilled, the kill switch drilled) for the first sleeve whose verdict passes.
