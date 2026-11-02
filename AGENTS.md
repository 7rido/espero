# AGENTS.md — rules for an AI agent working in espero

Read by Codex, Cursor and most agent harnesses; Claude Code reads it through `CLAUDE.md`. A human
contributor follows the same rules.

## Setup

```bash
python -m venv .venv && source .venv/bin/activate
pip install -e ".[chart,tui,dev]"
./scripts/check.sh            # tests + audit table + CLI smoke test; must pass before any commit
```

Everything runs on public endpoints with no key. Call `.venv/bin/espero <command>`, not the
interactive home screen (`espero ui` needs a real terminal and arrow keys). `espero --help` lists
every command, and `espero <command> --help` its flags.

## Never

- **Read, print, ask for or type a key.** `.env` is the account holder's. An agent may check whether
  a variable is set, never its value.
- **Place a real order.** There is no mainnet order path in this repo, and none is to be added.
  `espero/hl_exchange.py` is the only code that signs anything, on Hyperliquid's testnet only, and
  its guards must not be weakened. Every real order is the account holder's own act.
- **Re-tune a frozen test.** A `research/FORWARD_*.md` or `PREREGISTRATION_*.md` that is committed is
  fixed: its rule, data, criteria and outcomes. A later idea gets a new number and a new document.
- **Stop a forward test early** or read its running numbers as a result. Verdicts are judged once,
  on the date the plan names.
- **Delete or overwrite** the ledgers, `*.db` books, `data/hlcollect/` or `data/aggr/forward*`.
  Forward data can't be downloaded again.
- **Push, merge or open a pull request** unless the user asks in those words.
- **Start a second recorder into the same folder.** `docker compose up` and launchd's agents must
  never write the same `data/`; on a machine that already records, set `ESPERO_DATA_DIR` elsewhere.

## The research discipline

1. **Pre-register first.** Write `research/PREREGISTRATION_<NAME>.md` with the hypothesis, data,
   rule, pass criteria, power and outcomes, and commit it **before** computing the result.
2. **Run it once.** Write `research/RESULTS_<NAME>.md` with the verdict as committed, including a
   FAIL. Anything looked at afterwards is labelled "information only".
3. **Costs are explicit.** Use `espero.costs` (measured by #39 and #41) or a venue in
   `espero/venues.py`. Never a hidden or zero fee.
4. **Fills come after the signal.** At the next bar's open, never the signal bar's close.
5. **Mutation-check new tests.** Break the code a test guards and confirm the test fails.
6. **Tests number upward.** Check `research/INDEX.md` for the last `#NN` before taking one. Every file
   a test adds to `research/` is claimed in `research/index.py` (its `TESTS` table), and the index is
   regenerated with `python research/index.py`; CI fails on an unclaimed file or a stale index. The
   folder stays flat: scripts, tests and #48's seal address its files by name.
7. **From #61 on, the statistical bar is FDR and t ≥ 3, both.** Benjamini-Hochberg at q < 0.05 over every judged test, and
   |t| ≥ 3 on the same t, in the registered direction. Missing either is a fail. #1 to #60 keep their committed criteria.
   See `research/FDR_STANDARD.md`.

Ideas that haven't been tested yet go in `research/IDEAS_NOVEL.md`.

## Data — fetch it yourself, and know why

A fresh clone has only what CI needs. **You may fetch the rest without asking:** every source is
a public endpoint with no key. Fetch only what the task needs, and say what you fetched.

| the task touches | fetch | why it's needed |
|---|---|---|
| CI, `espero matrix`, `backtest`, the factor panel | nothing | committed in `data/` |
| a forward test (#22–#45), `health.json`, the dashboard, liquidations, Hyperliquid positions | `./scripts/fetch-data.sh live` | the maintainer's live recordings. They **can't be downloaded from the source later**: aggr deletes its 5-minute bars after a few days, and Hyperliquid's API serves only the current state. The release is the only copy of the days before you cloned. |
| a past test's numbers (#18–#41), or a new idea on Binance bars | `./scripts/fetch-data.sh archives --no-oi` (add `oi` only for #25) | the price, funding and liquidation history the published results were computed on. Binance's public archive keeps it, so it can be fetched at any time. About 1.6 GB without `oi`. |
| one script only | that script, e.g. `python research/settle.py` | each one downloads its own missing files into its own folder (docs/DATA.md, section 2) |

**Rules for data:**

- **Never overwrite, re-download over, or delete the live recordings.** `fetch-data.sh live`
  extracts with "keep existing files" for that reason. They are git-ignored (`.gitignore`, class 4),
  so never `git add -f` them, and never run `git clean -x`.
- **A new data folder goes in `.gitignore` by its class** (cache, tick days, or recording), not by
  test number. A recording also goes in `scripts/publish-data.sh`'s `PATHS` and `fetch-data.sh`'s
  `LIVE`; `tests/test_manifest.py` checks that.
- **Never commit data or publish a release.** `scripts/publish-data.sh` is the maintainer's.
- **A gap stays a gap.** A day missing from a forward folder is recorded as missing and never
  filled from another source; the forward plans depend on this.
- **For a forward verdict, the maintainer's recording is the one of record.** A recording you start
  yourself is a replica for cross-checking, not a substitute.

## Where things are

- `espero/`: the package. One module per test or account (`liqhold.py` is #45).
- `research/`: every pre-registration, result and forward plan. `FORWARD_FAMILY.md` says what a
  pass leads to.
- `tests/`: `python -m unittest discover -s tests -t .` (or `pytest`).
- `docs/RUNBOOK.md`: the scheduled jobs and how to recover them.
- `state/`: every account, journal, ledger and `health.json` (the last `espero daily` run, one entry
  per step). `espero.cli.state_dir` says how it is found; a bare `--state name.db` lives there. Until
  the move in docs/RUNBOOK.md ("Where the state lives") is done, they may still be in the repo root.
