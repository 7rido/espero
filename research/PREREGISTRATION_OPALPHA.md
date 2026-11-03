# Pre-registration — operator alpha: what the operator's overrides earned against the rule (#69)

Committed **before** any override exists. Written 2026-11-02, while no sleeve is live, no proposal has been
made and no operator has answered one: there is nothing to have seen. This document is the contract; the
result document will report the measurement, and nothing below is changed afterwards. A later idea takes a new
number. **A measurement, information only:** it has no PASS or FAIL, no t bar, spends no trial of the FDR
family (research/FDR_STANDARD.md), and changes no verdict, rule, size or mode by itself.

## Question

docs/OPERATOR.md lets a person stand between an operator-paced rule and its orders: approve, reject, size
down, exit early, or let the proposal lapse. Each of those is a decision the frozen rule did not make. Did they
add or take away return, against the rule followed exactly? Without a registered answer, a run of lucky
overrides would read as skill, and an operator who loses money by overriding would never be told.

## Data

- **The overrides,** from the approvals ledger (`approval_events` in the sleeve's journal, `espero.approvals`):
  every answer to a machine proposal other than "approve as proposed", every operator-initiated trade
  (mode B), and every silence. Kinds, fixed now:

  | kind | what the operator did | live outcome | the rule's outcome |
  |---|---|---|---|
  | `reject` | declined an entry the rule proposed | nothing traded: 0 | the twin's net on that trade |
  | `modify` | approved at a smaller size (fraction f of the proposal) | f × the trade's net | the twin's net |
  | `exit` | closed a position before the rule's exit | the live net to the early exit | the twin's net to the registered exit |
  | `delay` | approved after the rule's own entry time, inside the budget | the live net from the later fill | the twin's net from the registered fill |
  | `operator` | proposed an entry the machine had not, matching a live event of the rule (mode B) | the live net | the twin's net on the same event, 0 if the twin did not take it |
  | `silence` | let an entry lapse (its default: not taken) | 0 | the twin's net |

  A silent exit is executed by default and is the rule's own exit, so it is not an override.
- **The rule's counterfactual** is the paper twin (research/DEPLOYMENT_LADDER.md, rung 0), which takes every
  event the frozen rule takes at its registered fills and exits, net of the costs its plan registered. For each
  override, the twin's trade on the same event is the comparison.
- **The live outcome** is the venue's own fills, net of fees and funding, from `espero.attribution`.
- **Window:** from the first proposal of the first operator-paced sleeve on a mainnet rung (the canary or later)
  until **30 comparable overrides** or **365 days**, whichever comes first. Testnet and paper proposals are rehearsals and
  are not counted.
- **Excluded before looking:** an override whose twin trade is missing (the twin was down) is not comparable and
  is counted, never filled.

## Rule — how an override is scored

`alpha_bps = (live net − twin net) / proposed notional × 10⁴`, positive when the operator did better than the
rule. Every number is net of costs (`espero.costs` for the twin, the venue's statement for the live side), never
gross, never zero-cost. `espero/opalpha.py` holds it: pure, overrides in, numbers out.

## What is reported, once

At the end of the window, in `RESULTS_OPALPHA.md`: per kind and overall, the count, mean and median `alpha_bps`,
their sum in dollars, and a Newey-West t over the overrides in time order with `floor(4(n/100)^(2/9))` lags;
the share of overrides with `alpha_bps > 0`; and, beside them, what silence alone cost or earned. **No PASS or
FAIL.** The t is printed for reading, against no bar.

## What it can change

Nothing by itself. A later numbered pre-registration may use this number, with a bar written before its own
data, to decide whether a sleeve keeps its operator or runs under its rule alone.

## Power

Thirty overrides at a spread of 50 bps a trade put the mean within about ±18 bps (one standard error 9 bps):
enough to see an operator who costs or adds a round trip per override, not enough to see a few bps.

## Outcomes

**Reported** at 30 comparable overrides or 365 days. **Not applicable** if no operator-paced sleeve reaches a mainnet rung
by the end of 2028. Either is recorded in the ledger as a measurement.

## Information only

Per rule and per operator-paced class; the hour of day of the overrides; the overrides made within 10 minutes of
the proposal against later ones.

## Robustness, information only

The six readouts of research/ROBUSTNESS_STANDARD.md are not applicable, each for its reason: deflated Sharpe
and PBO (no strategy and no configurations: it scores decisions against a fixed rule), purged k-fold (nothing is
fitted), signal half-life (no signal series), turnover (no weights), capacity (no edge of its own). The block is
printed with those reasons.

## Timestamp

This file's SHA-256 is stamped with OpenTimestamps (`research/PREREGISTRATION_OPALPHA.md.ots`,
`scripts/timestamp.sh`) at the commit that adds it, before any override exists.
