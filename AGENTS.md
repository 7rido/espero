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
- **Place a real order.** `espero live` stays off. `espero/hl_exchange.py` signs on Hyperliquid's
  testnet only, and its guards must not be weakened. Every real order is the account holder's own
  act.
- **Re-tune a frozen test.** A `research/FORWARD_*.md` or `PREREGISTRATION_*.md` that is committed is
  fixed: its rule, data, criteria and outcomes. A later idea gets a new number and a new document.
- **Stop a forward test early** or read its running numbers as a result. Verdicts are judged once,
  on the date the plan names.
- **Delete or overwrite** the ledgers, `*.db` books, `data/hlcollect/` or `data/aggr/forward*`.
  Forward data can't be downloaded again.
- **Push, merge or open a pull request** unless the user asks in those words.

## The research discipline

1. **Pre-register first.** Write `research/PREREGISTRATION_<NAME>.md` with the hypothesis, data,
   rule, pass criteria, power and outcomes, and commit it **before** computing the result.
2. **Run it once.** Write `research/RESULTS_<NAME>.md` with the verdict as committed, including a
   FAIL. Anything looked at afterwards is labelled "information only".
3. **Costs are explicit.** Use `espero.costs` (measured by #39 and #41) or a venue in
   `espero/venues.py`. Never a hidden or zero fee.
4. **Fills come after the signal.** At the next bar's open, never the signal bar's close.
5. **Mutation-check new tests.** Break the code a test guards and confirm the test fails.
6. **Tests number upward.** Check `README.md` and `research/` for the last `#NN` before taking one.

Ideas that haven't been tested yet go in `research/IDEAS_NOVEL.md`.

## Where things are

- `espero/`: the package. One module per test or account (`liqhold.py` is #45).
- `research/`: every pre-registration, result and forward plan. `FORWARD_FAMILY.md` says what a
  pass leads to.
- `tests/`: `python -m unittest discover -s tests -t .` (or `pytest`).
- `docs/RUNBOOK.md`: the scheduled jobs and how to recover them.
- `health.json`: the last `espero daily` run, one entry per step.
