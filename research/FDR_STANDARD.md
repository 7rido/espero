# FDR and t ≥ 3 as the statistical bar for new tests

**Written 2026-11-01. From #61 on, a new test must clear both Benjamini-Hochberg at q < 0.05 and the Harvey-Liu-Zhu t ≥ 3.**
Tests #1 to #60 keep their committed criteria, including every forward test. This document spends no trial and judges nothing.

## The rule

A pre-registration from #61 on uses this as its significance criterion, unless it states and justifies a stricter one:

1. **The family:** every row of `trials.csv` with status `fail`, `pass`, `provisional` or `exploratory` when the new test is
   judged, plus the new test. A row with no p-value counts as p = 1, because leaving it out would flatter the result.
2. **The p-value:** two-sided, from the test's registered t. Overlapping or clustered data needs a day-clustered or Newey-West
   t. Under 100 independent observations, use Student's t or a registered bootstrap instead of the normal approximation.
3. **The bar:** q < 0.05 from `trials.benjamini_hochberg`, and |t| ≥ 3 on the same t, both in the registered sign, which the
   caller checks. Missing either is a fail. A strong result the wrong way is not a discovery.
4. **Reported beside it, deciding nothing:** Benjamini-Yekutieli, and q at 0.10.
5. **Every other bar stays.** These two are the statistical bar only. Costs, both halves, not-one-coin and any other registered
   bar still apply.
6. **The verdict freezes when judged.** A later test can't reopen it, although later tests will change the q it would get.

## Limits

- **This isn't strict FDR control.** Benjamini-Hochberg assumes one fixed list, and this one grows over time. Freezing each
  verdict is the practical choice, and a true online method would be stricter.
- **The tests share data,** so they aren't independent. Benjamini-Hochberg holds under positive dependence, which has not been
  verified here. That's why Benjamini-Yekutieli is reported beside it.
- **FDR's line moves with the list.** It has no fixed t equivalent. Each discovery loosens it, and each test that misses tightens
  it. t ≥ 3 stays fixed, so whichever is stricter decides.
- **A wrong-way result still counts as a rejection.** The sign check refuses #17 as a discovery, yet its two-sided p helps other
  tests through: without it, #61's bar would be |t| ≥ 2.57 instead of 2.52.
- **FDR says a result probably isn't noise.** It doesn't say the result pays: #9b, #20 and #35 clear it and fail on other bars.

## The old tests rescored, information only

Run with `research/fdr_rescore.py`, which reads the ledger and writes nothing. **No committed verdict changes.** The t values
are the ledger's. #8, #9b, #16 to #20, #25, #26, #28, #30, #33, #35 and #37 were rerun at least twice on 2026-11-01 with identical output, and the t
values match their committed records, except that #8's Newey-West t reruns at 4.74 against the ledger's 4.5. #21's sealed
data stayed closed, so it was not rerun. The question came after these results were known, so nothing here is blind.

The family is the 19 judged tests with a p-value, as the committed `trials_scored.csv` has it. The checks are the rule's family
of all 33 judged tests, Benjamini-Yekutieli, and #44's trade-weighted t where it exists.

| # | t | q | q, all 33 | BY | q, trade-weighted | FDR bar | Rescored outcome |
|---|---|---|---|---|---|---|---|
| 8 | 4.5 | 0.0000 | 0.0001 | 0.0001 | 0.0001 | met | pass, unchanged |
| 9b | 13.44 | 0.0000 | 0.0000 | 0.0000 | none | met | fail, on spread and reversal |
| 16 | −0.93 | 0.4308 | 0.7483 | 1.0000 | none | no, wrong sign | fail |
| 17 | −2.54 | 0.0301 | 0.0523 | 0.1068 | none | no, wrong sign | fail |
| 18 | −2.11 | 0.0662 | 0.1150 | 0.2350 | 0.0233 | no | fail, and also on both halves |
| 19 | 3.52 | 0.0014 | 0.0024 | 0.0048 | 0.0062 | met | real, not tradable, unchanged |
| 20 | 9.78 | 0.0000 | 0.0000 | 0.0000 | 0.0022 | met | real, not tradable, unchanged |
| 21 | 0.27 | 0.8309 | 1.0000 | 1.0000 | none | no | fail |
| **25** | **2.36** | **0.0434** | **0.0754** | **0.1539** | **0.1132** | **met on the 19 only, not under any check** | **fail under this rule; real, not tradable on the 19 only** |
| 26 | −4.06 | 0.0002 | 0.0003 | 0.0007 | 0.0022 | met | pass, unchanged |
| 28 | −1.44 | 0.2589 | 0.4497 | 0.9186 | 0.2589 | no, wrong sign | fail |
| 30 | 0.97 | 0.4308 | 0.7483 | 1.0000 | 0.1880 | no | fail |
| 33 | 0.92 | 0.4308 | 0.7483 | 1.0000 | none | no | fail |
| 35 | 6.99 | 0.0000 | 0.0000 | 0.0000 | 0.5066 | met, not trade-weighted | fail, on reclaim and cost |
| 37 | 0.99 | 0.4308 | 0.7483 | 1.0000 | 0.2854 | no | fail |

**Reading it:**

- **FDR and t ≥ 3 agree on every test here.** Scored side by side under this rule, on the rerun's Newey-West and Student's t,
  they reach the same answer on all 15 tests with a t ≥ 3 bar, and on the 4 with other bars. Requiring both changes no outcome.
- **No test gains or loses a pass.** #25's label is the only change, and it still doesn't pay: +12.3 bps against the 18 bps bar.
- **Under this rule's own family of 33, #25 doesn't move either,** and nothing changes.
- **Which tests count decides who gets through.** On 19 tests the weakest discovery is at t = 2.36, wrong-sign #17 aside. On 33
  it's at t = 3.52. That's the weakest result already through, not the bar a new test faces.
- **FDR alone would be looser than t ≥ 3 for the next test, which is why both are required.** On this ledger #61 clears q < 0.05
  at |t| ≥ 2.52 (p ≤ 0.0117), because it would rank eighth of 34, so t ≥ 3 decides for now. If FDR's line rises above 3 as tests
  are added, FDR decides. `fdr_rescore.py` prints both.
- **At q < 0.10 no verdict changes beyond #25:** #18 would meet the statistical bar on the 19 but still fails both halves.
- **The normal approximation isn't what decides these.** Student's t moves #25's p from 0.01827 to 0.01841, #18's from
  0.0349 to 0.0379, and #26's from 0.00005 to 0.00008.
- **14 judged tests have no p-value:** #2 to #7, #9 to #14, #40 and #42. Their results stay as they were.
- **#15, #36 and #43 have other statistical bars,** so they aren't rescored. #43's own rule stands, though its q across the
  ledger is 0.0662.

## Scoring the judged tests with no t, information only

**Written 2026-11-02, before computing.** 14 judged tests have no t, so they count as p = 1 and can't be discoveries. This
section fixes how each gets one. Rough estimates from the ledger were seen first, so the choices are fixed but not blind. It
spends no trial, changes no verdict and leaves `trials.csv` as it is.

**Common to all:** a two-sided t on a daily series over the test's registered window, venue and costs, against zero or the
registered benchmark. Newey-West with floor(4(n/100)^(2/9)) lags. Over 100 days the normal p, otherwise Student's t. The
registered direction is a positive mean. The run is the blocked-network copy at `bbd1575`, with nothing from 2026-10-30 on.

| # | Series | Against | Notes |
|---|---|---|---|
| 2 | daily strategy return minus BTC's, holdout 2024-01-01 to 2026-10-27, as `research/momentum.py` computes them | BTC buy and hold | the registered bar is beating BTC |
| 10 | daily net P&L of closed trades at Binance.US fees, by UTC exit day, zero on days with no exit, over the 30-day window | zero | the corrected replay in `ERRATA.md` |
| 11 | daily returns of the hourly equity, the #11 rule, primary hours | zero | hourly returns with 24 Newey-West lags and the plain daily t are reported beside, deciding nothing |
| 13 | as #10, 1-hour rule, 2026-03-30 to 2026-09-26, dollar volume from the last 24 stored bars | zero | approximate: the replay gives 456 trades against the published 468 |
| 14 | as #11, #12's rule on Kraken, maker costs, primary window | zero | |
| 5 | estimate: holdout Sharpe × √years from the ledger | zero | data missing; no Newey-West |
| 6 | estimate: r √(n − 2) / √(1 − r²) from the ledger's Spearman r | zero | data missing; days overlap, so this overstates |

**Not scored, still p = 1:** #3 (one market over 30 days, a simulation), #7 (exploratory, data missing), #9 (never run), #12
(inside its forward window), #40 and #42 (testnet plumbing, no effect to measure), and #4 (passed on its own rule).

**Then:** the 33 judged tests are scored under this document's rule with the rerun t for the other 19, and the result is
written below.

**Result, 2026-11-02.** Each replay matched its published figures: #2's Sharpe −0.06 against BTC's 0.69, #11's 0.88 hourly
and 3.48 daily, #14's 0.02, and #10's 812 trades at −$12.60. #13 is the exception, with 456 trades at −$69.49 against 468 at −$80.93.

| # | t | q, all 33 | FDR | t ≥ 3 | Verdict, unchanged |
|---|---|---|---|---|---|
| **11** | **+3.41** | **0.0030** | **met** | **met** | fail: +5.2% against 8%, and Kraken fees |
| 2 | −0.98 against BTC | 0.6818 | no, wrong sign | no | fail |
| 13 | −0.73 | 0.7675 | no, wrong sign | no | fail |
| 6 | +0.49, estimate | 0.9786 | no | no | fail |
| 10 | −0.12, Student's t | 1.0000 | no, wrong sign | no | fail |
| 5 | −0.12, estimate | 1.0000 | no, wrong sign | no | fail |
| 14 | −0.01 | 1.0000 | no, wrong sign | no | fail |

- **#11's funding carry is the one new signal.** Its daily net return is positive at t 3.41, so it clears both bars. It
  still failed on cost: it earned +5.2% a year against the 8% bar. #12, the same carry with maker execution, is the test that
  asks whether it pays, and it stays sealed until its window closes.
- **#11 clears t ≥ 3 only by the committed method.** Its plain daily t is 2.63 and its hourly Newey-West t is 2.65, both of
  which clear FDR alone but not t ≥ 3. The Newey-West t is higher because the daily returns are negatively autocorrelated
  (lag 1 −0.35, then +0.15, +0.04 and −0.14),
  estimated from 209 days. Under a slightly different method, it would be the first test to pass FDR and fail t ≥ 3.
- **Every other newly scored test misses both bars,** and five of the seven went the wrong way.
- **The other tests' results don't change.** The FDR cutoff stays at p ≤ 0.00905, #25's q falls to 0.0670, and the next
  test's FDR bar falls to |t| ≥ 2.48, so t ≥ 3 still decides.
