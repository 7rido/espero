# Results — the research substrate, and why XS momentum failed (#48)

**Did XS momentum fail because the signal decayed, or because the trades were unexecutable?**

## The one answer

**Not because the trades were unexecutable. Execution accounts for θ = 0.111 of the shortfall against BTC,
95% CI 0.104 to 0.118, at $100,000 a leg. Verdict: signal.** As the registration requires: *Execution does
not explain #2's failure: its shortfall against BTC was there before costs.*

**Whether the expected edge decayed, this substrate cannot say.** What failed was the realised path. The
excess return over BTC fell 0.71 a year from 2021–23 to the holdout, but the 95% CI on that fall runs from
−0.55 to +1.80. It includes zero, so decay and a bad draw can't be told apart on this history.

| over the holdout, annualised log growth | |
|---|---|
| G, the book before costs, on Binance | −0.300 |
| B, BTC on Binance | +0.227 |
| D, execution's drag at $100,000 a leg | 0.065 |
| shortfall, B − G + D | 0.592 |
| **θ = D ÷ shortfall** | **0.111 (0.104–0.118)** |

The registration wrote down its expected result before the read: about 0.11, and about 0.22 at $1,000,000.

| size per leg | θ | 95% CI | cost a leg | status |
|---|---|---|---|---|
| $1,000 | 0.053 | 0.052–0.054 | 6.4 bps | information |
| $10,000 | 0.067 | 0.065–0.070 | 8.2 bps | information |
| **$100,000** | **0.111** | **0.104–0.118** | **14.2 bps** | **the verdict** |
| $1,000,000 | 0.225 | 0.208–0.241 | 33.0 bps | registered stress row: *not at $1,000,000 either* |

Sealed in `e08b629` before any holdout print was read; read once, in `f976852`; raw output in
[substrate_q48_run.txt](substrate_q48_run.txt). The query is [substrate_q48.sql](substrate_q48.sql), and it
agreed with the Python number to ten places, as the runner requires.

**How far to trust this:**

- **The conclusion was largely known.** `RESULTS.md` already said costs weren't the cause. The new part is the
  measured size, on the venue's own prints. Neither the test nor its CI is independent evidence that #2 failed.
- **The CI is narrow by construction.** It holds the realised path fixed and carries only the uncertainty in
  what the legs cost. It says nothing about the market.
- **Binance is a proxy venue.** #2 ran on Coinbase spot. On Coinbase, with no costs, G and B are −0.330 and
  +0.214, close to Binance's, and θ would be about 0.11. Perp funding would have added another 0.057 a
  year (October 2026's isn't published yet); it is left out of θ because #2 held spot.
- **The impact model errs high.** At $1,000,000 it charges 27.5 bps, against 10.0 for a sweep of the ±1% depth
  and 3.5 for the replay. That leans against the conclusion, and the conclusion holds anyway.
- **Fills are simulated.** Nothing here is a real fill.

## Which tests these are

The request's "two tests that just failed" was not defined anywhere, so it was resolved from the record. Neither
test failed in the window the request names, and the numbers below use both the named window and the real one.

| as asked | taken to be | what the record says |
|---|---|---|
| "2021–2023 XS book" | **#2**, the only cross-sectional test with a FAIL verdict (#7 is exploratory by construction) | Failed on **2024-01 → 2026-10**. 2021–23 is inside its design period, where it made money. |
| "2024 carry book" | **#11**, not #12, whose forward test is still running | Failed on **2026-04 → 2026-10**. 2024 is its **best** year (+16.46%), in an information-only view with the basis unmarked. |

So the first question below is what survives of each book's good stretch. #48 asks about the real failure.

## What the books keep after execution

Binance USD-M prices; a proxy for both books. Fee 5 bps on perps, 10 on spot.

**#2, 2021–23.** Its report never broke this window out. From its design run at 10 bps a round trip, the headline
is **+39.09% a year**; on Binance before costs it is +30.38%.

| size per leg | after execution | of Binance's gross | **of the headline** | and after funding | of the headline |
|---|---|---|---|---|---|
| $1,000 | +27.57% | 91% | **71%** | +9.24% | 24% |
| $10,000 | +26.69% | 88% | **68%** | +8.49% | 22% |
| $100,000 | +23.96% | 79% | **61%** | +6.15% | 16% |
| $1,000,000 | +15.68% | 52% | **40%** | −0.94% | −2% |

**The largest single cost is not execution.** A long perp paid 0.155 a year of log drag in funding across 2021–23.
#2 held spot and paid none of it, so its spot result is not achievable on this perp, and the reverse holds too.

**#11, 2024.** Its headline is **+16.46%**, with basis marked at zero. All 143 trades that entered or exited in
2024, 276 legs, both sides.

| size per position | cost a side, perp + spot | after execution | **of the headline** | after measured basis | of the headline |
|---|---|---|---|---|---|
| $1,000 | 17.7 bps | +16.06% | **98%** | +16.18% | 98% |
| $10,000 | 23.3 bps | +14.14% | **86%** | +14.27% | 87% |
| $100,000 | 41.1 bps | +8.09% | **49%** | +8.21% | 50% |
| $1,000,000 | 97.2 bps | −11.04% | **−67%** | −10.92% | −66% |

The +16.46% assumed 16.5 bps a side, about right for a small book. The measured basis adds only 0.12% across the
133 round trips with both ends in 2024. **Hyperliquid's own book for 2024 is not in any archive here**, so
this measures #11's trades on Binance while still crediting Hyperliquid's funding. Its impact slopes were fit
in-sample on 2024's own coin-days and carry no sealed status.

## 1. The point-in-time store

`espero/pit.py`, Parquet read through DuckDB. Every row carries `valid_time` and `known_time`; a kline is known at
its close. 32,636 archive files listed in [pit_manifest.csv.gz](pit_manifest.csv.gz), **all matching Binance's
published SHA-256**, plus 434 vendor files with their own hashes. 18.3 GB fetched, 11 GB kept, raw zips deleted.
The universe is a query (`pit.universe_sql`): at 2022-01-03 it returns LUNA and MATIC, and at 2024-01-01 ORDI
and 1000BONK. Nothing frozen, nothing from the future.

**What the archive does not hold, and what that does:**

| dataset | exists for | effect |
|---|---|---|
| `bookTicker` | **2023-05-16 → 2024-03-30 only** | No quotes for 2021–22, and about 3 of the holdout's 34 months. Queue fills on 34 legs, information only. |
| `bookDepth` | from 2023-01-01; ±1–5% buckets about every 30 s | Not an order book. A sweep estimate only, none before 2023. |
| `liquidationSnapshot` | **COIN-M only; none for USD-M** | No venue total exists to reconcile to. |
| `exchangeInfo` | **not archived**; 23 Wayback captures, with no capture from 2022-11 to 2023-11 or 2023-11 to 2026-02 | Between captures the last known status stands, so a delisting can be seen late. |
| `metrics` | from 2021-12 (BTC from 2020-09) | Reconciled from then. |

**Ingested as a subset, not whole.** `aggTrades` plus `bookTicker` for these coins is about 440 GB, and this machine
had 204 GB free. So prints cover 779 coin-days, the days the books traded and an impact sample, plus 226 of
spot. Bars and funding cover 21 coins' whole history, and daily bars for all 1,056 symbols ever listed.
`bookTicker` keeps two hours per coin-day. #11's 2024 quotes were not fetched: its reprice doesn't use them.

**Defects the automated report found in Binance's own files** ([pit_gaps.csv](pit_gaps.csv),
[pit_empty_days.csv](pit_empty_days.csv)):

- **`aggTrades` for 2022-09-12 holds every print twice**, on all three coins checked: 2,063,814 duplicate
  ids. The store keeps the file as published, and the reader de-duplicates on the id.
- **Monthly hourly bars lack days**: 2022-02-26 → 28 and 2022-04-01 → 02 on SOL, LTC, NEAR, ZEC and XRP.
  Monday opens therefore read the daily bars, which agree where both exist, and a missing open raises.
- Holes in index, mark and premium bars (77, 67 and 81), listed by symbol.
- No hole in any `aggTrades` id sequence, and no row known before it was valid.

## 2. The execution simulator

`espero/execsim.py`. **Queue fills** need quotes, so they ran only where quotes exist. **A replay cannot show an
order's own impact**, because the prints don't react to it, and the first fit on the replay had an R² near 0.
So impact is fit on the market's flow: return on signed √(flow ÷ daily volume), five-minute buckets, per symbol
and volatility regime, 100,737 buckets from 2021–23, median R² 0.42 ([substrate_impact_fit.csv](substrate_impact_fit.csv)).

Queue fills, back of the queue, five minutes then cross, on 34 legs from 2023-05 to 2024-03:

| size | filled in time | median wait | cost against the mid, crossings included |
|---|---|---|---|
| $1,000 and $10,000 | 94% | 5 s | 1.2 bps |
| $100,000 | 85% | 18 s | 4.6 bps |
| $1,000,000 | 53% | 63 s | 6.9 bps |

Thirty-four legs is few. Markout curves by size are in
[substrate_design_markouts.csv](substrate_design_markouts.csv) and
[substrate_holdout_markouts.csv](substrate_holdout_markouts.csv). **They show no clear size pattern**: one-hour
standard errors are near 15 bps across about 100 legs, far above the differences between sizes.

Corrected before the seal, none affecting the read: my first queue model filled any size on one print through the
level, and my first half-spread could go negative. Corrected after it, information only: a guard skipped most queue
legs, so `substrate_holdout_legs.csv.gz` has too few queue rows and [substrate_queue_fills.csv](substrate_queue_fills.csv) is the
one to use. θ reads neither. `substrate_reprice.py` and `substrate_fetch.py` were sealed files and were edited after
the read: the carry and information commands, and the carry fetch's worker count and quote files. The holdout's
path did not change, and the guard now refuses a second read in any case.

## 3. Calibrating the detector

`espero/detector.py`, [substrate_power.csv](substrate_power.csv). Synthetic markets with fat tails, clustered
volatility and a common factor, at the book's real weekly volatility of 13.5%, through #2's rule and the same
bootstrap. 1,000 paths a cell.

| planted alpha, log a year | power, 147 weeks | power, 303 weeks | average estimate against truth, 147 weeks |
|---|---|---|---|
| **0 (no edge)** | **false positives 7.9%** | 8.0% | **+0.005 against 0** |
| 0.25 | 12% | 11% | 0.20 against 0.19 |
| 0.50 | 19% | 25% | 0.42 against 0.39 |
| 1.00 | 41% | 62% | 0.77 against 0.79 |
| 1.50 | 65% | 91% | 1.15 against 1.20 |
| 2.00 | 87% | 98% | 1.63 against 1.62 |
| 3.00 | 98% | 100% | 2.51 against 2.49 |

- **It recovers a planted alpha** within its CI on 91–94% of paths, and reports zero on the null: the average
  estimate is +0.005.
- **It runs hot.** The false-positive rate is about 8% at a nominal 5%, and coverage is 91–94% rather than 95%.
  That was published rather than tuned away.
- **It is weak.** 80% power on 147 weeks needs a planted alpha near +184% a year. Any edge of a realistic size
  would pass unseen, which is why "decay" can't be claimed.
- **The tape simulator recovers planted costs** to within 0.002 bps
  ([substrate_tape_check.csv](substrate_tape_check.csv)).
- **The attribution** returned the right verdict on 100% of paths at planted θ of 0.04, 0.14, 0.83 and 1.00, and
  "cannot separate" on 100% at 0.32 ([substrate_attribution.csv](substrate_attribution.csv)).

## 4. The trial budget

`espero/trials.py`, [trials.csv](trials.csv) and [trials_scored.csv](trials_scored.csv): 56 rows, #1–#45 plus 9b and #48–#57.

**Spend rate: 30 judged edge tests in 3 calendar days, 10 a day.** At 5% each, that expects 1.5 false passes
and a 79% chance of at least one. Bonferroni's bar per test is 0.17%. Four passed, plus #12 provisionally. 10
more forward tests are running and count as trials; their running numbers were not read.

- **Deflated Sharpe.** Against the best of 56 null trials, the bar is an annualised Sharpe of 1.43. **None of the 9
  Sharpes on file clears 95%**: #12 reaches 0.60, #8 0.22 and #4 0.20 ([trials_dsr.csv](trials_dsr.csv)).
  Returns are assumed normal because no skew is on file, and fat tails would lower these.
- **SPA across the 14 series on disk**, 2,492 days. Gross, p < 0.001: effects are real before costs, and #20's
  bounce leads. **Net of 18 bps a trade, p = 0.045**, led by #12. That is one marginal result, and #12's universe
  was chosen from today's coins (ERRATA, 2026-10-28), so it should not be read as an edge.
- **Holm across the 19 usable p-values** leaves 6: #8, #9b, #19, #20, #26 and #35. Most are the "real, not
  tradable" results, or a spread; many of these t-stats use the day-mean convention #44 audited.
- **Priors are after the fact**: 0.20 for a literature effect, 0.10 for a variant, 0.05 for a novel idea, assigned
  by class, because nothing recorded a prior when these tests ran. They expect 1.7 true passes and 1.3 false.

**The limits of this inventory:** 37 of 56 tests have no p-value, recorded as empty rather than invented. SPA covers
14 series, not the whole inventory, and N = 56 is a floor because many tests held many cells.

**Refreshed 2026-10-31** with the rows for #48 to #57, none of which has a p-value. On the first 46 rows the
bar was 1.38 and #12 reached 0.62, with 40 tests registered rather than 41. Nothing else in this section moved:
the spend rate, Holm's 6, both SPA results and 0 of 9 above 95% are unchanged.

## 5. Reconciliation

Tolerances were fixed in [substrate_reconcile.py](substrate_reconcile.py) before the comparison.
[substrate_reconcile.csv](substrate_reconcile.csv): **15 of 23 checks inside tolerance.** Every failure is below.

| series | against | result | |
|---|---|---|---|
| funding, rate by rate | **venue**: Binance's REST history, cached earlier | 95,461 rates on 14 coins, **no difference**, none missing | ok |
| funding | venue's formula, from premium bars | median 0.17 bps; 95th percentile 1.75 bps | ok |
| funding | **vendor**: Tardis, first of each month | 544 rates, median difference 0 | ok |
| index prints | vendor | 4,867 prints, median 0.03 bps | ok |
| mark prints | vendor | 4,821 prints, median 0 | ok |
| open interest | vendor | 576 samples, median 0.17% | ok |
| best bid and ask | vendor | 100,778 one-second samples, 14 coin-days, 99th percentile 0 bps | ok |
| prints, day high and low | **venue's bars** | 773 coin-days, no difference | ok |
| prints, volume, raw files | venue's bars | **6 days outside**: the 3 doubled days, and the 3 below | **FAIL** |
| prints, volume and dollars, de-duplicated | venue's bars | **3 days outside**: DOGE 2024-10-28 +6.0%, SOL 2024-10-28 +2.2%, DOGE 2026-06-01 −0.15% | **FAIL** |
| prints, trade count, de-duplicated | venue's bars | **8 days outside**, largest 5.8% | **FAIL** |
| **liquidations** | **venue** | **No venue total exists for USD-M** | **FAIL, a gap** |
| liquidations | vendor against vendor: Tardis and aggr | 9 coin-days, median 2.0% | ok |

Eight rows in the CSV fail; the three print rows above expand to seven. **Effect on the numbers:** θ's prices
come from the daily bars, and its costs from fees, frozen half-spreads and frozen slopes, so the holdout's
mismatched days do not enter θ. The 2024-10-28 mismatch is in Binance's own files, and which side is right is
unknown. **Liquidation counts are not reconciled to the venue, and can't be from this archive.** The vendor
sample cost nothing: Tardis's free first-of-month files.

## What else this run lives with

- **#2's design headline does not reproduce**: +97.10% a year against the published +115.27%, on candles fetched
  today (its original inputs were never kept). The holdout reproduces exactly at −29.75%, and the 69 switches in
  2021–23 were identical at each of the three history start dates compared. See `ERRATA.md`.
- **The download.** The session stated the size before fetching, as an estimate of 25–30 GB, and went ahead without
  waiting for a reply. 18.3 GB was fetched and 11 GB kept, with 199 GB still free. Nothing was paid for.
- **The numbers rest on a survivor-chosen universe**, for both books, by design: this is about their trades.
- **The account holder is a non-US resident**, and these data are Binance USD-M. That changes no rule here, and
  this document is not a statement about which venue the holder may use.
- **Nothing forward was read**, and no forward ledger, recorder or frozen test was touched.

Reproduce: `pip install -e ".[pit]"`, then `research/substrate_fetch.py`, `substrate_reprice.py`,
`substrate_calibrate.py`, `substrate_trials.py`, `substrate_quality.py` and `substrate_reconcile.py`.
Tests: `tests/test_substrate.py`; 46 mutations of the guarded code on the final version, all caught.
