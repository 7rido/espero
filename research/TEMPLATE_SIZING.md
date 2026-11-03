# Template: the sizing-and-execution document a PASS needs before any order

**Written 2026-11-02, before any forward verdict.** research/FORWARD_FAMILY.md says a Tier A pass leads to "a
sizing and execution document before any order", and Tier B and #12 to one that also registers a confirmation
window. Nothing said what that document holds. This is its template. A sizing document is **a numbered
pre-registration**: it takes the next free number in `research/trials.csv`, is committed (and stamped with
`scripts/timestamp.sh`) before the sleeve's testnet rung begins, and is fixed from then on. FORWARD_FAMILY rule 8
orders them: one at a time, the largest main-criterion t first.

Copy this file to `research/PREREGISTRATION_SIZING_<NAME>.md`, fill in every section, and delete nothing: a section
that does not apply says why.

---

# Sizing and execution — <rule name> (#<new number>, for #<the passed test>)

Committed **before** the testnet rung. A later change is a new number.

## 1. The pass

- The test, its verdict as written in its `RESULTS_*.md`, its main-criterion t and its q over the ledger at
  judgment (research/FDR_STANDARD.md).
- Its tier (FORWARD_FAMILY.md rules 2 to 5) and, for Tier B or #12, **the confirmation window**: the same frozen
  rule, at least as many days, starting the day after the first window's judgment, passing by the same criteria.
  No order before it passes.
- Its cluster (rule 6): the members, which one supplies the rule (the larger t), and why the others add nothing.
- The robustness block of research/ROBUSTNESS_STANDARD.md, quoted in full, and research/ROBUSTNESS_LIVE.md's
  readouts: BTC beta, lower-tail dependence, the regime split, the deflated Sharpe at the intended size beside the
  capacity readout. Reported, not decisive, unless this document raises one to a bar with a number.

## 2. Latency and who acts

- The row of research/LIVE_LATENCY.md: the event, the budget and where it comes from, the feed, today's delivery,
  the class. A class other than the table's is not allowed.
- **live-from-tape (auto-only):** the live evaluator that produces the event (#71's streaming engine, the HLP books,
  or one written for this rule, with its own tests), and the holder's written decision to let the machine place
  orders unattended (docs/HOLDER_INPUTS.md). Without it the sleeve stops at rung 1.
- **operator-paced:** the operator's hours, the proposal's wait (`approvals.wait_s`), the default on silence (no
  entry), and the TOTP set-up (docs/OPERATOR.md).
- **next-day-batch or not tradable live:** no sizing document; the rule cannot be traded as registered.

## 3. The venue

- The venue, its eligibility **checked by the holder** against its current terms (research/VENUE_NONUS.md, step
  zero), and the holder's own tax and licensing check.
- Its costs: measured by #39 or #41 for that venue (`espero.costs`), or a #47-style cost-confirmation run first.
  "It pays" margins under 2 bps at the venue's base fee are said so (VENUE_NONUS.md: Binance's base taker fee is
  above the 18 bps hurdle).
- #62's measured fill error, carried as a number (PREREGISTRATION_REPLAYSIM.md requires it).
- The order type the rule needs (taker, or maker with its queue model), and whether the venue's API offers it.

## 4. Size

- The capital allocated (docs/HOLDER_INPUTS.md); until answered, none, and this document cannot be completed.
- #63's weight for the sleeve if two or more passes run (PREREGISTRATION_SLEEVES.md), else 1.0.
- The capacity readout at the sleeve's net edge, from the recorded depth at its trade times.
- **The target:** the smallest of #63's weight x capital, the capacity readout, and every cap of
  research/RISK_POLICY.md, stated in dollars and as a fraction.
- Any cap stricter than RISK_POLICY.md's for this sleeve, with the reason (looser is not allowed).

## 5. Execution

- The decision price (what the rule's fill is measured against), the order's timing inside the budget, the order type,
  the time in force, what happens to a partial fill, and the exit, as the frozen rule registers it.
- **The cost budget** each block of fills is judged against: the registered round trip plus #62's error, in bps.
- The stop, where the rule has one, and whether it rests on the venue (so it survives the machine) or is the
  executor's.
- Two-legged rules: both legs' venues, the order in which they are placed and closed (perp first to close), and
  the hedge tolerance (RISK_POLICY.md).

## 6. The ladder for this sleeve

research/DEPLOYMENT_LADDER.md's rungs with this sleeve's numbers: rung 1's round trips and drills, rung 2's budget,
rung 3's block size and step rule, rung 4's target. A sleeve may make a rung stricter, never looser.

## 7. The live stop rule

#70's parameters for this sleeve, computed from the sleeve's verdict series once, at this document's commit: the
observation unit, μ0, σ0, k and h, the false-alarm rate per year, the expected detection delay under no edge, and
what an alarm does for the sleeve's class.

## 8. Attribution and reconciliation

What `espero.attribution` reports for the sleeve each day (fees, funding, slippage against the decision price, the
gap to the twin), the three records each fill is reconciled against, the venue record the daily equity is checked
with, and the tolerance for a break.

## 9. What stops the sleeve

Every way it stops, in one list: the risk gate's stops, #63's drawdown states, edgewatch, two canary breaches,
a reconciliation break, the kill switch, the holder's own drawdown stop, the end of the confirmation window failing.

## 10. The holder's sign-off

The holder's own words, in this document, at its commit: that they have read it, that the capital, venue and
drawdown are theirs, and, for the mainnet rungs, where the written lift of the no-mainnet rule is.

## Timestamp

This file's SHA-256 stamped with OpenTimestamps at its commit.
