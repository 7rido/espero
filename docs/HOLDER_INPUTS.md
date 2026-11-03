# What only the account holder can answer

**Written 2026-11-02.** Capital, the drawdown at which to stop, which venues are open to the holder, the time
the holder will give, and whether this repo may ever sign on mainnet are the holder's decisions, never the
repo's and never an agent's. This page asks for them. **Until a question is answered, the system uses its
default, and every default is the safe one: no capital, so the risk gate refuses every entry.** Nothing in this
repo fills in an answer for the holder.

`espero/holder.py` reads the answers from the table below, so an answer here is the answer the code uses:
`holder.allocated_usd()` is the risk gate's capital, `holder.operator_response_s()` the latency audit's
operator, `holder.eligible(venue)` the venue check. `python -m espero.holder` prints what it reads.
`tests/test_holder.py` fails on an answer it cannot read.

## How to answer

Edit the **answer** column below, in a commit of your own, with a short reason in the commit message. Leave a
cell empty for "not answered". Amounts are USD; a drawdown is a negative percentage such as `-15%`; a list is
comma-separated; yes or no is `yes` or `no`. A change later is a new commit, and the old answer stays in the
history. The code reads this page only as `HEAD` holds it (`holder.committed`): an edit not yet committed, or a
copy outside a git checkout, allocates nothing and makes no venue eligible.

<!-- answers:start -->
| id | the question | answer | default until answered |
|---|---|---|---|
| `capital_usd` | How much capital do you allocate to this system, in USD? | | 0: the risk gate refuses every entry |
| `stop_drawdown` | At what drawdown from the peak would you stop everything? | | none, and with no capital it never matters |
| `venues_eligible` | Which venues have you checked as open to you, against their current terms? | | none: no venue may be used |
| `tax_and_licensing_checked` | Have you checked your own country's tax and licensing rules for perpetual futures? | | no: no venue may be used |
| `operator_hours_per_week` | How many hours a week will you give the operator's role? | | 0: operator-paced rules are not traded |
| `operator_response_hours` | When you are on duty, how fast do you answer a proposal, in hours? | | 4 hours, the protocol's |
| `min_capital_usd` | Below what capital is running this not worth it to you? | | not given: no sizing document can say it is worth running |
| `venue_loss_usd` | How much could you lose to one venue failing outright? | | not given: research/RISK_POLICY.md's 50 % per venue stands alone |
| `data_budget_usd_month` | How much a month will you pay for data or an always-on machine? | | 0: nothing is bought |
| `totp_set_up` | Have you set up the operator's one-time-code secret (docs/OPERATOR.md)? | | no: no approval can be given |
| `autonomy` | May the machine place orders unattended for rules too fast for a person (auto-only)? | | no: auto-only rules are not traded |
| `mainnet_lift` | The path of your committed document lifting the no-mainnet rule, if you choose to | | none: there is no mainnet order path |
<!-- answers:end -->

## Each question, why it matters, and what happens until it is answered

### Capital allocated (`capital_usd`)

- **Why:** every cap in research/RISK_POLICY.md is a fraction of it, and the ladder's target is a fraction of it
  (research/DEPLOYMENT_LADDER.md). Without it there is nothing to size.
- **Until answered:** 0. `risk.check` refuses every entry with "no capital allocated". The canary cannot start.
- **Note:** this is the capital you allocate to the system, not your net worth. The gate also stops at the account's
  equity when losses take it lower, so it never sizes against money that is gone.

### The drawdown at which you would stop (`stop_drawdown`)

- **Why:** it is an outer stop above all others: at that loss from the peak, everything is flattened and no entry
  is taken until you change the number (research/RISK_POLICY.md, the holder's stop). It should be a number you
  would really act on, because the system will act on it for you.
- **Until answered:** none. With no capital it never matters, and an allocation without it is incomplete:
  no sizing document can be signed off without it.
- **Beside it, fixed already:** #63 halves a sleeve at -10 % and flattens it at -20 % from its own peak; the risk
  gate stops new entries at -2 % in a day and flattens at -5 % in a week.

### The venues open to you (`venues_eligible`, `tax_and_licensing_checked`)

- **Why:** research/VENUE_NONUS.md, step zero: every venue restricts some countries, the lists change, and the check
  is yours. Your own country's tax and licensing rules for perpetual futures are yours too.
- **Until answered:** no venue. `holder.eligible(venue)` is false for every venue until both are answered, and a
  sizing document cannot name a venue.
- **How:** check each venue's current terms page; list the ones that allow your country of residence (for example
  `binance, hyperliquid`). Do not write your country here: this repo does not record it.

### The operator's hours (`operator_hours_per_week`, `operator_response_hours`)

- **Why:** an operator-paced rule (#4, #8, #12, #63) trades only when a proposal is answered in time
  (docs/OPERATOR.md). Fewer hours means more proposals lapse into silence, and the live sleeve becomes a subsample of
  the registered one; #69 measures what that costs.
- **Until answered:** no hours, so operator-paced rules are not traded. The response time stays the protocol's
  4 hours; an answer above 4 hours raises it, which can move a rule out of operator pacing (research/LIVE_LATENCY.md
  recomputes every class from it). An answer below 4 hours does not lower it.

### The minimum capital worth running (`min_capital_usd`)

- **Why:** running this has fixed costs: data, an always-on machine, and your hours. Below some capital the expected
  net edge does not pay for them. A sizing document compares its target's expected net return, deflated, with these
  costs and says whether it clears this number.
- **Until answered:** not given, and no sizing document can say the sleeve is worth running.
- **How to think about it, once a verdict exists:** the yearly net edge at target, from the verdict and the
  robustness block, times the capital, against the yearly cost of data, the machine and your time. Nothing here can
  be computed before a verdict.

### What one venue may cost you (`venue_loss_usd`)

- **Why:** research/RISK_POLICY.md caps any one venue at 50 % of the base. If you can only bear less than that on
  one venue, say so: a sizing document then uses the smaller of the two.
- **Until answered:** the 50 % cap alone.

### A data budget (`data_budget_usd_month`)

- **Why:** the recorder of record is a laptop that sleeps (docs/RUNBOOK.md, "The recorder of record sleeps"), and
  some feeds cannot be had from this machine at all: Binance's liquidation and funding streams are silent here, which
  is why #22, #23 and #38 are next-day-batch. An always-on machine or a vendor costs money; you have said you will pay
  for data and decide a figure first.
- **Until answered:** 0. Nothing is bought, and no agent buys anything.

### The operator's one-time-code secret (`totp_set_up`)

- **Why:** a reply to a proposal counts only with a code from it (docs/OPERATOR.md).
- **Until answered:** no approval can be given, so operator-paced rules are not traded.
- **How:** generate 20 random bytes, base32-encode them, add them to your authenticator app and to `.env` as
  `ESPERO_OPERATOR_TOTP`. The repo never prints it and no agent sees it.

### Unattended orders for auto-only rules (`autonomy`)

- **Why:** nine rules are live-from-tape and auto-only (research/LIVE_LATENCY.md): their budget is shorter than any
  person's answer, so they run without a person or not at all. Letting a machine place orders unattended is a separate
  decision from allocating capital.
- **Until answered:** no. Auto-only rules stop at the ladder's testnet rung.

### The lift of the no-mainnet rule (`mainnet_lift`)

- **Why:** this repo has no mainnet order path, and none is added unless you lift the rule in writing, in your own
  words, in a committed document (AGENTS.md; research/DESIGN_MAINNET_PATH.md says how the module would check it).
- **Until answered:** none. Nothing signs on mainnet, nothing is prepared for it quietly, and no guard is weakened.
- **How:** write the document yourself, commit it (signed, as the design describes), and put its path here. A path
  that does not exist is refused by the test.

## What this page does not do

It decides nothing about any verdict, and it gives no advice on what the answers should be. An agent working in this
repo reads these answers and never writes them.
