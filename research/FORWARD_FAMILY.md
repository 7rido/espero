# The forward tests as a family — what a pass leads to (#46)

**Committed 2026-10-31.** Written on 2026-10-30, the day the forward window opens, while every
event ledger was empty (see Transparency). It changes **no** test's verdict. Each `FORWARD_*.md`
(and #34's part B) stays the only judge of its own PASS or FAIL, with its bars as committed. This
document fixes only what happens **after** a pass: what it may lead to, what must confirm it first,
and the order if several pass at once.

## Why

About ten tests are judged together after 2027-03-31. Run enough tests and one can pass by luck.
Deciding now, while no result can be seen, what each pass would be worth is what keeps the family
honest. Deciding after the results arrive would let them choose the rule.

## The chance of a lucky pass — nominal

Under no effect at all, the main criterion alone of each test passes with about this chance
(one-sided, normal approximation):

| bar | tests | nominal chance each |
|---|---|---|
| t ≥ 3 (or ≤ −3) | #22, #23, #24, #27, #29, #31 | 0.13% |
| t ≥ 2 (or ≤ −2) | #32, #34 part B, #38 | 2.3% |
| Holm across 3 horizons, family α 0.05 | #45 | ≤ 5% |
| none: Sharpe and drawdown against BTC, return > 0 | #8 (MF) | unknown; depends on BTC's path |
| none written: see rule 5 | #12 (carry), ends 2026-11-27 | unknown; 30 days has almost no power |

Adding these up gives at most about 13% for the nine tests with a t-bar. That's before each test's
other conditions (both halves, "it pays" above 18 bps, not one coin), which all must hold too and
cut it a lot. These numbers are **nominal**: day-means over 153 days are fat-tailed and somewhat
correlated, so the true chances are higher than the table says. The real exposure is:

1. **#8 (MF)**. It has no significance test at all. Its own plan already says a six-month pass "is
   still not a reason for capital".
2. **The three t ≥ 2 tests** (#32, #34, #38).
3. **The "information only" lists.** Across the family there are dozens of these readouts:
   horizons, coins, months, mirrors; #27 alone records six groups at three horizons. Somewhere
   among them a strong-looking number is close to certain. **That's the biggest hole, bigger than
   the ten main verdicts.**

## The rule — fixed when committed, 2026-10-31

1. **Verdicts stand as written.** No correction is applied to any test's own bars. Re-tuning a
   frozen test is not allowed, and that includes raising its bar.
2. **Tier A: a t ≥ 3 PASS** (#22, #23, #24, #27, #29, #31). The plan's own outcome applies: a sizing
   and execution document before any order.
3. **Tier B: a t ≥ 2 or Holm PASS** (#32, #34, #38, #45). The PASS stands. But before any real order,
   the sizing document must pre-register a **confirmation window**: the same frozen rule, at least
   as many days, starting the day after the first window's judgement. It must pass by the same
   criteria. #32 trades nothing alone, so it needs this only if a document weights #27 by it.
4. **#8 (MF)**. Its pass or fail ends or continues #8 as its plan says. It is never by itself a
   reason for capital.
5. **#12 (carry).** Its plan grants a 30-day paper test, 2026-10-28 → 2026-11-27, and writes no pass bar for
   it and no book that decides it. This fixes both, once, without changing its rule or its costs:
   - **The bar** is #12's five criteria, unchanged, with the hourly Sharpe ERRATA says the forward test keeps.
   - **The maker book decides**, because maker costs are what #12 registered. Its fills are assumed at the
     close, so that verdict is an upper bound. The taker book is always reported beside it, and the gap is the
     test's stated question.
   - **A pass is never by itself a reason for capital.** Thirty days can't tell a Sharpe of 1.5 from 0. Before
     any real order, the rule needs a confirmation window as in Tier B, of at least 153 days, like the others.
   - **A fail** closes carry at retail scale, as #12's plan says.
6. **Clusters count once.**
   - **#27, #32 and #45** use the same events: forced down-breaks on Hyperliquid.
   - **#22, #24 and #31** buy the same kind of dip.

   Passes inside one cluster are one finding, not independent confirmation. A pass in one with
   fails in the others is reported as exactly that.
7. **Information-only readouts never become claims.** Any one of them, however strong, can enter
   the repo only as a new pre-registration tested on days after 2027-03-31.
8. **If several pass**, sizing documents are written in order of their main-criterion t, largest
   first. The account holder is a non-US resident ([VENUE_NONUS.md](VENUE_NONUS.md)), so venue
   access does not decide the order. One document at a time; the next starts after the previous
   one is finished or abandoned.
9. **A FAIL is not overturned** by a pass elsewhere in its cluster, by an information-only readout,
   or by a later look at a different window.

## Transparency — what was seen before this

- Each forward plan's evaluation, power and outcome sections, as committed.
- `health.json` from the 2026-10-30 07:30 run: every event test at 0 events or "no breaks yet";
  `mf` and `mf-hl` at 100.0, unchanged from their start. No forward return of any test has been seen.
- **Rule 5 was added on 2026-10-31, three days into #12's window**, so unlike the rest it is not written before
  its test began. Its author read #12's plan, results, ERRATA and the screen's code, not its books or its screen.
  **Whether the books were seen is not known.** The user is not sure whether #12's books or `espero carry screen`
  have been looked at since 2026-10-28, and on 2026-10-29 both books were running in visible terminal tabs. So
  rule 5 is treated as possibly written after some of its running numbers were seen.
- **Between writing and committing**, the 2026-10-31 daily run recorded the window's first day and #27's ledger
  step crashed (ERRATA, 2026-10-31). Fixing it showed which coins had a break on 2026-10-30, 12 of 14. No count,
  return or note from any forward ledger was read, and no rule here changed after that.
