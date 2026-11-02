# Robustness readouts beside every result from #61 on

**Written 2026-11-02. From #61 on, every results document carries the block below, computed by
`espero.robustness`. The block is reported, not decisive:** the statistical bar stays Benjamini-Hochberg
q < 0.05 and |t| ≥ 3, both (research/FDR_STANDARD.md), and every other registered bar stays. A readout
here can make a result decisive only when a later pre-registration says so, with a number, before that
test's result exists. Tests #1 to #60 are not rescored. This document spends no trial and judges nothing.

## The six readouts

| readout | what it is | input | when it reads "not applicable" |
|---|---|---|---|
| **Deflated Sharpe** | Bailey & López de Prado (2014): the probability the per-observation Sharpe beats what the best of N null trials reaches on average, with the track record's length, skew and kurtosis. `espero.trials.psr` and `expected_max_sharpe`, already in the repo. | the test's return series; N = the judged rows of `trials.csv` at judgment; the variance of their per-observation Sharpes, from `trials_dsr.csv` | no return series (a measurement) |
| **PBO by CSCV** | Bailey, Borwein, López de Prado & Zhu (2017): the returns of every configuration tried, T × N, cut into 16 blocks; every half-and-half pairing is a train/test split; the share of pairings where the train winner ranks below the median on test. Pairings are capped at 2,000, drawn with seed 0. | the configurations a pre-registration lists (the registered rule and its information-only variants, each with its returns on the same calendar) | one configuration: a frozen rule with no variants has nothing to overfit among, and the block says so |
| **Purged k-fold with embargo** | López de Prado: test folds are contiguous; a training observation whose label span overlaps the test span is purged; the 1 % of bars after the test span is embargoed. A fold scheme, not a number: a test whose script cross-validates uses `robustness.purged_kfold` and says so. | each observation's start and end bar | a test with no cross-validation (most: the rule is frozen, not fitted) |
| **Signal half-life** | AR(1) on the signal series, half-life −ln 2 / ln φ in the series' bars. | the signal as the rule computes it, one value per bar | no signal series; φ outside (0, 1) reads NaN |
| **Turnover** | one-way: half the sum of \|Δw\| across assets per period (a full switch is 1.0), and a year's worth | the weights per period | a one-position rule reports its trades per year instead, under this heading |
| **Capacity from recorded depth** | the largest notional the recorded side of the book fills at an average slippage within the measured edge, from `data/hlbook` (top 20 a side, every 5 minutes) or the raw `l2Book` tape; never more than the recorded depth, because beyond it the book is unknown, not deep | the edge in bps (the result's net), the book slots at the rule's trade times | no measured edge (a FAIL has no edge to carry), or no recorded book for the venue |

## Rules

1. **Reported in full.** Every line, "not applicable" with its reason included; `robustness.render` prints
   the table a results document pastes. A line left out reads as hidden.
2. **Computed once, with the result,** on the same series the verdict used, after the verdict is written.
   A readout computed before the verdict is a look, and is disclosed as one.
3. **Never a bar.** A deflated Sharpe of 0.3 beside a PASS does not change the PASS; it is printed beside it
   and `FORWARD_FAMILY.md`'s sizing document must quote it. A pre-registration may raise one of these to a
   bar for its own test, with the number, before its result exists.
4. **The trial count is the ledger's.** N for the deflated Sharpe is the number of judged rows in
   `trials.csv` at judgment, not the number of configurations the author remembers trying.
5. **Capacity is a floor on what the book was, not a forecast.** It uses the recorded depth at the rule's
   own trade times; a book recorded at another time of day is not used in its place.
6. **The scaffold carries the section.** `scripts/new-test.py` writes "Robustness, information only" into
   every new pre-registration, listing which of the six will apply, so the choice is made before the result.

## The first use

#61 and #62 are measurements without a return series: their blocks read "not applicable" on all six lines,
and `RESULTS_RAWBARS.md` and `RESULTS_REPLAYSIM.md` will print them that way. The first strategy test from
#63 on reports them in full.

## Limits

- The deflated Sharpe assumes the trials' Sharpes are roughly normal; a ledger of 60 tests with a few
  outliers overstates the expected maximum, which errs toward deflating. Said beside the number.
- PBO over the variants an author chose to list measures overfitting among those, not among the ideas
  never written down. The ledger (`trials.csv`) is the only record of those.
- Purged k-fold assumes label spans are known; a forward test's labels end at its hold, which is known.
- The half-life of a signal is not the half-life of its edge; #43 (horizons) measured the latter directly.
- Capacity from 20 levels every 5 minutes is a coarse floor; the raw tape (`espero rawrec`) holds the whole
  top of book at every change, and from #61 on capacity is read from it where the venue is on the tape.
