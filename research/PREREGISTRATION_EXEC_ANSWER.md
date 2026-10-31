# Pre-registration — did #2 fail because the signal decayed, or because the trades were unexecutable? (#48)

Committed **before the holdout's prints, quotes or Binance prices are read**. One question, one
number, one read. Not a new hypothesis: it adds no rule and cannot rescue #2, whose verdict stands.
#46 and #47 are taken by drafts outside this work, so this is #48.

## Which test, and what is already known

**#2** (`PREREGISTRATION.md`, `momentum.py`, `RESULTS.md`): weekly, 100% in the top 30-day return of
nine large coins, on Coinbase spot. It failed on its **2024-01-01 → 2026-10-27 holdout** (−29.75% a
year against BTC's +23.30%). 2021–2023 is in its design period, where it made money.

**This question is contaminated, and the likely answer is known.** `RESULTS.md` already says "costs are
not the cause", from re-running the holdout at 4, 10 and 30 bps (−28.8%, −29.8%, −32.9% a year). The
design read also found costs small: 6 bps a leg at $1,000, 34 bps at $1,000,000. So a verdict of
"signal" would surprise nobody, and this test's value is its measured size and CI, on the venue's own
prints.

**Not yet read:** Binance's prints, quotes and depth on the holdout's legs, and Binance's returns over its
weeks. **Already touched in the holdout's calendar, none of it a return or a cost:** reconciliation of
funding rates, and of first-of-month index, mark and open interest on BTC, ETH and SOL; the store's bar and
gap counts; a universe ranking for 2024-01-01 by volume.

**The expected result, from published numbers, written before the read.** G about −0.33 and B about +0.21 a
year, with 130 legs over 2.82 years. At the design read's mean cost a leg (14 bps at $100,000, 34 at
$1,000,000), θ is about **0.11 at $100,000** and about **0.22 at $1,000,000**. The first sits well inside
"signal"; the second sits close enough to its 0.25 bar that a straddling CI is an anticipated outcome.

## Data

- **Legs:** `research/substrate_xs_legs.csv`, window `holdout`: 130 legs on the 81 switches
  `momentum.simulate` makes, which reproduces −29.75% exactly. Every leg's time and coin is fixed.
- **Prints:** Binance USD-M `aggTrades` for each leg's coin-day, checked against Binance's SHA-256 and
  de-duplicated on the trade id. **Prices:** the daily bars' 00:00 open, Monday to Monday.
- **Venue proxy.** #2 ran on Coinbase spot. Coinbase's history offers no prints or quotes here, so this
  measures **these trades on Binance USD-M perps**. The account holder is non-US; that changes nothing
  here. Perp funding is reported beside the number, not in it: it is a cost of holding this proxy, not
  of executing on it, and #2 held spot.
- **The universe is #2's nine coins.** It stays survivor-chosen, because the question is about #2's trades.

## The one number

$$\theta=\frac{D}{D + B - G}$$

over the holdout, as annualised log growth: **G** the book's gross return before costs, **B** BTC's, **D**
execution's drag. θ is the share of the realised shortfall against BTC that execution accounts for, and
θ = 1 if the book beat BTC before costs.

- **D** = the sum over legs of −ln(1 − c), per year, at **$100,000 a leg**. c = 5 bps taker fee +
  the coin's half-spread frozen in `substrate_half_spread.json` + impact, with the slope frozen in
  `research/substrate_impact_fit.csv`, the regime cuts frozen in `substrate_regime_edges.json`, and the
  trailing volume known before each leg.
- **Why $100,000 a leg is the verdict's size.** It is 200 times this account's roughly $500 book, so it
  still leans toward "unexecutable" against any size this project would trade. **$1,000,000 is the
  registered stress row**: it carries its own θ, CI and sentence, and cannot change the verdict. The size
  was chosen after seeing the design read's costs and before reading any holdout cost; both are disclosed
  here. $1,000 and $10,000 are information.
- **The impact fit errs toward too much.** The market's flow includes its informed part, and the design
  read has it at 29 bps at $1M, against 15 for a sweep of the ±1% depth and 9 for the replay.
- **The half-spread is half a tick at the touch**, the median first fill at $1,000 on the design sample,
  never below zero. #39's taker figure is higher (BTC 0.33 bps), because it averages every print, including
  those that sweep. Here, sweeping belongs to the impact term.
- **The CI** is 95% percentile, 10,000 draws resampling the legs (seed 48). **G and B are not
  resampled.** The failure already happened, so what it was is a fact; what is uncertain is what the legs
  cost. Whether that path shows the *expected* edge changed is a different question, below.
- A leg with no measurable cost takes the mean of the others, and the count is reported.

**The raw query is committed:** `research/substrate_q48.sql`. The runner must print the same point
estimate from SQL and from Python, or the run is reported as broken.

## Verdict, fixed now

| result | verdict | sentence the results must carry |
|---|---|---|
| CI upper ≤ 0.25 | **signal** | Execution does not explain #2's failure: its shortfall against BTC was there before costs. |
| CI lower ≥ 0.75 | **execution** | #2's failure is mostly what it costs to trade. |
| otherwise | **cannot separate** | The substrate cannot explain the failure. |

**The $1,000,000 row.** CI upper ≤ 0.25: "not at $1,000,000 either". Otherwise: "at $1,000,000, on a fit
that errs high, execution cannot be excluded as a material part". Neither changes the verdict.

The synthetic test (`research/substrate_attribution.csv`) returned the right verdict on 100% of paths for
planted θ of 0.04, 0.14, 0.83 and 1.00, and "cannot separate" on 100% for 0.32. The tight CI is a fact of the
method: it carries the uncertainty of the costs, not of the market path.

## What this cannot say

"Signal" here means **the realised shortfall against BTC existed before costs**. It does **not** establish
that the expected edge decayed. Separating decay from a bad draw needs power this history lacks: on these 147
weeks the detector reaches 80% power only near a planted +184% a year of log return, about +150% of realised
excess (`research/substrate_power.csv`). Its false-positive rate is about 8% at a nominal 5%. So the gross 2021–23 against gross holdout gap will be
reported with its own CI, **information only**, and no decay claim follows from it unless that CI excludes zero.

## Holes this run lives with

- `bookTicker` covers 2023-05-16 → 2024-03-30, about 3 of the holdout's 34 months: queue-position fills
  on those legs only, information only.
- `bookDepth` covers all the holdout but only as cumulative ±1–5% buckets: a coarse sweep, information only.
- Fills of size assume the same flow would have traded. Nothing here is a real fill.

## Procedure

`python research/substrate_fetch.py holdout`, then `python research/substrate_reprice.py holdout`, once.
The runner refuses unless this file is committed, with no uncommitted change to it, the query, the runner,
the fetcher, the frozen fit, cuts and half-spreads, the leg list, `execsim.py`, `detector.py` or `pit.py`, and
no earlier read on disk. The path was rehearsed on the design legs: the query and Python agreed. A bug found afterwards is corrected in a dated
note; the first read stays published. Results: `research/RESULTS_SUBSTRATE.md`.
