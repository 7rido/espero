# Pre-registration — the portfolio layer: how passes combine, fixed before any two exist (#63)

Committed **before** any forward test is judged and before any two passes exist to combine. Written
2026-11-02, while every forward ledger's running numbers are unread (as `FORWARD_FAMILY.md` records). This
document is the contract; nothing below is changed afterwards, and a later idea takes a new number. **It is
a rule, not a hypothesis test:** it has no t and spends no trial. It computes nothing until the family's
judgment after 2027-03-31, because the inputs it needs are the forward ledgers' returns, which are running
numbers until then (AGENTS.md: never read as a result).

## Why now

`FORWARD_FAMILY.md` fixes what one pass leads to: a sizing document, one at a time, clusters counted once.
It does not say how two sizing documents share one account. Decided after the results arrive, that choice
would be made by the results: the sleeve that did best would get the weight. So the combination rule is
written now, with its lookbacks and thresholds, and the sizing documents apply it as an appendix.

## Scope

Applies when **two or more** tests from the family (#8, #12, #22, #23, #24, #27, #29, #31, #32, #34, #38,
#45, #58, #59, #60, and any later forward test that cites this document) hold a PASS that
`FORWARD_FAMILY.md` allows to proceed to a sizing document (Tier A, or Tier B after its confirmation window),
and the account holder decides to run more than one. One pass alone follows its own plan; this document
adds nothing to it.

## The rule

1. **Sleeves.** Each pass is a sleeve: its frozen rule, its venue, its own ledger of daily returns from the
   forward window (`state/<name>_trades.csv`, or for #58–#60 the recordings), in bps of the sleeve's
   notional, **net of the costs its plan registered**. A cluster (`FORWARD_FAMILY.md` rule 6) is **one
   sleeve**: #27, #32 and #45 together; #22, #24 and #31 together; #58 and #59 together. Inside a cluster
   the member with the larger main-criterion t supplies the rule; the others are not added.
2. **Correlation, reported first.** The Pearson correlation of the sleeves' daily returns over the whole
   forward window, on the days both traded (a day one sleeve did not trade is 0 for it, and counted), with
   the number of such days. A pair above **0.5** is reported as one source of return and the pair is
   **capped at the weight of one sleeve** between them (the larger-t member gets it). Information only beside
   it: the correlation on the second half of the window alone, and the correlation of the sleeves' weekly
   returns.
3. **Vol targeting.** Each sleeve is scaled to a **10 % annualised volatility**, from the trailing
   **90 days** of its own net daily returns (`espero.portfolio.vol_scaled`'s form: target / realised),
   recomputed on the first day of each month, never above **1.0 × its sleeve notional** (this repo does not
   borrow); a sleeve with fewer than 60 trading days of returns is scaled by the whole-window volatility.
   The book's gross exposure is **capped at 100 %** of the account: weights are scaled down pro rata when
   the vol-scaled sleeves would exceed it (`espero.portfolio.target_portfolio_vol` with the realised
   covariance of the sleeves' daily returns, 90-day window).
4. **Drawdown control, per sleeve and for the book.** From the sleeve's or book's own peak of net equity
   since it went live: at **−10 %**, size halves; at **−20 %**, the sleeve (or the book) goes flat and
   stays flat until a new pre-registration, numbered, says why it may resume. The halving is undone when
   equity recovers to within 5 % of the peak. The thresholds are on net equity after costs, marked daily
   at the close the plan uses.
5. **Rebalancing.** Monthly, on the first weekday, as the TSMOM account does (`espero.tsmom`); a sleeve's own
   trades happen on its own calendar inside its allocation. Turnover from this layer alone is reported
   (`espero.robustness.turnover`).
6. **What it cannot do.** It cannot add a sleeve that did not pass, raise any sleeve above its vol target,
   lever the book, or keep a sleeve that hit −20 % alive. It cannot be re-tuned: a different target, window
   or threshold is a new number.

## Data

- The sleeves' daily net returns from the forward ledgers, read **once, at the family's judgment**, by
  `espero.sleeves` (pure: arrays in, weights out), after each verdict is written.
- Nothing is read before. The synthetic tests in `tests/test_sleeves.py` are the only runs before judgment.

## Criteria

There is no PASS or FAIL: the rule either applies (two or more passes the family lets proceed) or does not.
What is recorded at judgment, in `RESULTS_SLEEVES.md`: the sleeves, their pairwise correlations and counts,
the vol-target weights on the window's last month, the gross exposure, the drawdown state of each sleeve on
the window, and the book's net return, volatility and maximum drawdown over the window at those weights,
**information only**: it is the window the sleeves were judged on, so it is in-sample for the weights.

## Outcomes

- **Applies:** the sizing documents written under `FORWARD_FAMILY.md` rule 8 carry these weights, and a
  real order, if the account holder ever places one, is sized by them. The repo prepares the numbers; the
  order is the account holder's act, outside the repo.
- **Does not apply** (fewer than two passes): recorded as such; the single pass follows its own plan.
- A later forward test joins by citing this document in its own pre-registration; it cannot change it.

## Robustness, information only

At judgment, `espero.robustness` on the combined book's daily returns: deflated Sharpe with N = the
ledger's judged rows; PBO not applicable (one registered combination, no variants); turnover of this layer;
capacity of each sleeve from the raw tape's depth at its trade times, at the sleeve's net edge. Purged
k-fold and half-life do not apply: there is no fit and no signal at this layer.

## Timestamp

This file's SHA-256 is stamped with OpenTimestamps (`research/PREREGISTRATION_SLEEVES.md.ots`,
`scripts/timestamp.sh`) at the commit that adds it, before any forward verdict exists.
