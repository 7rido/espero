# The lean gate and the power bar — step 4 of [PLAN_REGIMES.md](PLAN_REGIMES.md)

**Written 2026-10-31. Both candidates closed at the power bar, so no regime test will run on this history.** That is not
evidence that regimes don't matter: this history can't tell the states apart at the size that would matter. No skill or return
was cut by state, no test is registered and no trial is spent. The verdict is at the end. Everything before it was committed before the count (`085b5ef`).

## The lean gate: both candidates stay open

The rule from [REGIME_CANDIDATES.md](REGIME_CANDIDATES.md), run once with `research/regime_gate.py`. Each figure is the Pearson correlation
between the test rows' P(up) and `r7` in one fold of the 7-day model.

| candidate | symbols | dates | fold 1 | fold 2 | fold 3 | fold 4 | fold 5 | fold 6 | negative | result |
|---|---|---|---|---|---|---|---|---|---|---|
| Volatility, stocks and ETFs | 13 of 13 | 2,257 | −0.440 | −0.063 | −0.329 | −0.421 | −0.250 | −0.376 | 6 of 6 | open |
| Funding, crypto | 35 of 42 | 1,892 | −0.453 | −0.138 | +0.013 | −0.375 | −0.283 | −0.353 | 5 of 6 | open |

- **What this means:** in most folds the rating leans against last week's move. It says nothing about whether that lean is right.
- **Funding sits exactly on the line,** so one more positive fold would have closed it.
- **Data:** the last row in both panels is 2026-10-22, so no outcome reaches 2026-10-30. Prices were fetched fresh and not kept. The 7 missing coins aren't listed on Hyperliquid.
- **Printed:** only these correlations and the counts above, with no test-row outcome, skill or regime label.
- **Order of work:** the rule was committed before the run (`61f06d9`), but the code wasn't. [regimes.py](../espero/regimes.py) and its tests were written first and caught 12 of 12 mutations.

## The power bar, fixed before counting

The question is whether the history could tell the two states apart at the size that matters. For each candidate:

- **State share `w`:** the state's share of out-of-sample test dates, counting only folds that pass the 52-date training floor. The comparator's share `c` is counted the same way: low and mid pooled for volatility, neutral for funding.
- **Smallest difference that matters:** `D = |S| ÷ (1 − w)`, where `S` is the rating's published 7-day skill for that class. If skill adds up across dates, this is the difference that lifts the state just above zero.
- **Smallest difference the history can detect:** `MDE = (2.80 ÷ 1.96) × H × √(1/w + 1/c)`, for 80% power at 95%. `H` is the published half-width of that skill's confidence interval.

| class | `S` | published 95% CI | `H` |
|---|---|---|---|
| stocks and ETFs, 7 days | −0.61% | −1.03% to −0.22% | 0.405% |
| crypto, 7 days | −2.06% | −4.07% to −0.21% | 1.93% |

**A candidate goes on only if `MDE ≤ D`, and the state has at least 52 test dates in each half of the test period.** Otherwise it closes untested, and no trial is spent. Step 5 needs both halves to pass, which is what the 52-date floor protects.

**What I knew when setting this.** I worked the formula through on shares I assumed, before any count:

| class | `MDE` and `D` at `w` = 1/3, `c` = 2/3 | `w` needed if `c = 1 − w` |
|---|---|---|
| stocks and ETFs | 1.23% against 0.91%: closes | about 47% or more |
| crypto | 5.85% against 3.09%: closes | about 64% or more |

So **I expect this bar to close both**, unless the state is much more common than a third. Expanding cut-offs don't guarantee a third, so the counts could change that. I chose this `D` as the most generous version I could defend. Using `|S|` alone would be stricter.

**Assumptions and limits:**

- **It uses no new outcome,** only the published `S` and CI from [RATING.md](RATING.md).
- **Equal noise per date is assumed,** which is wrong for high volatility, where forecast errors differ. That's left as it is.
- **High-volatility dates run in episodes,** so the true noise is probably larger than this. That favours the candidate.
- **Costs are left out here,** which also favours the candidate. They can only raise the bar, and step 5's tradable rule has to carry them.
- **The formula is approximate.** A narrow miss still closes the candidate: moving the bar after seeing the counts is what this document exists to prevent.

## What the count did, as committed

For SPY volatility and BTC funding only:

- labelled dates and unlabelled dates;
- test dates per state and per fold, and each half's test dates;
- training dates per state per fold, for the 52-date floor.

It uses the date index alone, reads no outcome column, and calls nothing that fits a model.

## The verdict, run once with `research/regime_count.py`

| candidate | state's share `w` | comparator's share `c` | can detect (`MDE`) | needs (`D`) | state's test dates, first and second half | result |
|---|---|---|---|---|---|---|
| Volatility, stocks and ETFs: high against low and mid | 31.7% | 52.6% | 1.30% | 0.89% | 510 and 89 | **closed**, can't detect `D` |
| Funding, crypto: crowded long against neutral | 11.3% | 79.1% | 8.76% | 2.32% | 137 and 36 | **closed**, on both conditions |

Test dates per state, with each fold's count. A fold under the 52-date training floor counts as 0:

| state | test dates | by fold | training dates by fold |
|---|---|---|---|
| high | 599 | 159, 109, 242, 18, 71, 0 | 252, 399, 520, 750, 780, 849 |
| mid | 819 | 0, 180, 74, 182, 180, 203 | 31, 183, 351, 437, 615, 789 |
| low | 177 | 0, 0, 0, 0, 64, 113 | 9, 25, 51, 51, 158, 230 |
| crowded long | 173 | 10, 46, 81, 36, 0, 0 | 92, 102, 136, 229, 265, 265 |
| neutral | 1,208 | 220, 203, 153, 208, 242, 182 | 243, 463, 678, 828, 1027, 1273 |
| crowded short (information only) | 96 | 0, 0, 0, 11, 12, 73 | 18, 42, 48, 59, 79, 87 |

The stock and ETF panel has 2,257 dates with 61 unlabelled and 1,892 test dates, none of them unlabelled. The crypto panel has 1,892 dates, all labelled, and 1,527 test dates.

Shares are of all test dates, so where the training floor removed dates, `w + c` is under 1. The halves split at the median test date, not the calendar midpoint.

**Reading it:**

- **The volatility miss isn't down to the training floor.** The floor removed 297 test dates from low and mid. Counting all of them, for information only, gives `c` = 68.3% and `MDE` 1.24%, still above `D`.
- **The states bunch in time.** High volatility has 510 of its 599 test dates in the first half, with none in the last fold. Crowded long has none in the last two folds. This is the mix-up of regime and period that the plan warned about, and these dates alone show it.
- **Funding misses by a wide margin.** It also fails the second-half floor, with 36 dates against 52.
- **Volatility is the nearer miss,** at 1.30% against 0.89%, and the bar's noise and cost assumptions favoured it. It still closes, and the bar doesn't move.

**What was read:** daily prices, fetched fresh and not kept, once for the gate and once for the count; and BTC's funding rates from #19's file, unchanged. Printed: only the counts and shares above and each step's arithmetic. The code was tested first (29 tests, 48 of 48 mutations caught across the gate and the count), but this run's code wasn't committed beforehand; the bar was.

**Not in `trials.csv`, on purpose.** Nothing here tested a signal: the gate correlates P(up) with a feature, and the count reads dates. Neither read a test-row outcome. If an auditor disagrees, these would be two more rows.

**Not verified:** the label code was tested on synthetic series only. Nobody has checked which real dates SPY's "high" or BTC's "crowded long" fell on, so a bug that passes the synthetic tests wouldn't have been caught here.

## What this leaves

- **The plan stops here.** Steps 5 and 6 don't run. Trend, stress and crypto volatility stopped at step 3.
- **The rating stays as it is:** `UNPROVEN`, with its rule unchanged. No regime label is added to it.
- **What could reopen this:** more dates. The window from 2026-10-30 stays closed until 2027-03-31, and a new attempt would be a new document with these results disclosed.
- **Still running on its own:** the rating's scorecard, as its logged ratings come due.
