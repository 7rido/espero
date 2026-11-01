# Results — what a market order costs on Hyperliquid as it gets larger (#51)

**On the days measured, an 18 bps round trip covers a market order at $1,000 on all 14 coins. At $10,000 it's covered on
9 and can't be said on 5. At $100,000 it's covered only on BTC, ETH and XRP, and can't be said on the other 11.** Most
of those "can't say" verdicts come from the book file showing too little depth, not from a measured high cost. This
changes no frozen test, and it's a measurement: no signal, no return and no edge claim.

Registered in `a69acce`. Raw output: [bookwalk_output.txt](bookwalk_output.txt) (11 coins) and
[bookwalk_output_supplement.txt](bookwalk_output_supplement.txt) (3 coins).

## Two errors in how this ran

**1. Three coins were not in the registered run.** `research/bookwalk.py fetch` crashed on XLM's first day, because
Tardis answers 400 for a date before a symbol's listing, and the code only expected 404. The author started the report
in the same step as reading that log, so it ran on 11 coins and listed XLM, HBAR and kSHIB as missing. They weren't
missing, just not fetched. The guard stops a second run, so the output stands. The fetch was fixed to treat a 400 as
missing, and the three coins were measured by the same functions in a separate `supplement` command, after the 11
coins' results were seen. All 42 rows below use one rule, but the last 9 are labelled.

**2. The download began moments before the pre-registration was committed.** A failed commit let the download go ahead.
No file was opened first, and the registration says so.

## The registered result

Mean cost in bps from mid, per leg, with the 95% CI over days. Round trip = 2 × (4.5 + cost). "Unfillable" is the share
of snapshots whose visible book couldn't hold the order; those have no cost, so a high share biases the cost low.

| coin | $1,000 cost | verdict | $10,000 cost (CI) | unfillable | verdict | $100,000 cost (CI) | unfillable | verdict |
|---|---|---|---|---|---|---|---|---|
| BTC | 0.10 | COVERED | 0.13 (0.11–0.15) | 0.3% | COVERED | 0.22 (0.19–0.26) | 1.5% | COVERED |
| ETH | 0.26 | COVERED | 0.31 (0.28–0.34) | 0.0% | COVERED | 0.49 (0.44–0.54) | 0.1% | COVERED |
| SOL | 0.35 | COVERED | 0.45 (0.39–0.51) | 0.3% | COVERED | 0.88 (0.77–0.98) | 5.0% | UNKNOWN |
| XRP | 0.43 | COVERED | 0.66 (0.57–0.77) | 0.0% | COVERED | 1.76 (1.52–2.05) | 0.3% | COVERED |
| DOGE | 0.55 | COVERED | 0.99 (0.89–1.09) | 2.1% | COVERED | 2.29 (2.01–2.60) | 9.4% | UNKNOWN |
| LINK | 0.84 | COVERED | 1.55 (1.41–1.70) | 5.5% | UNKNOWN | 4.26 (3.82–4.69) | 20.0% | UNKNOWN |
| ADA | 1.07 | COVERED | 1.86 (1.69–2.04) | 1.5% | COVERED | 4.90 (4.26–5.60) | 33.6% | UNKNOWN |
| AVAX | 0.72 | COVERED | 1.35 (1.20–1.50) | 6.4% | UNKNOWN | 4.05 (3.49–4.58) | 29.1% | UNKNOWN |
| BNB | 0.45 | COVERED | 0.92 (0.75–1.12) | 3.7% | COVERED | 2.54 (2.22–2.90) | 20.0% | UNKNOWN |
| TRX | 0.92 | COVERED | 1.95 (1.76–2.14) | 5.1% | UNKNOWN | 6.33 (5.31–7.42) | 31.6% | UNKNOWN |
| LTC | 1.08 | COVERED | 1.87 (1.67–2.08) | 3.3% | COVERED | 4.85 (4.32–5.52) | 35.3% | UNKNOWN |
| XLM (supplement) | 1.60 | COVERED | 3.41 (2.98–3.85) | 5.1% | UNKNOWN | 10.89 (9.89–11.96) | 38.6% | UNKNOWN |
| HBAR (supplement) | 1.65 | COVERED | 3.87 (3.39–4.36) | 8.5% | UNKNOWN | 12.47 (11.24–13.92) | 59.7% | UNKNOWN |
| kSHIB (supplement) | 1.56 | COVERED | 3.04 (2.53–3.57) | 0.3% | COVERED | 7.25 (6.35–8.15) | 10.7% | UNKNOWN |

| size | COVERED | NOT COVERED | UNKNOWN |
|---|---|---|---|
| $1,000 | 14 | 0 | 0 |
| $10,000 | 9 | 0 | 5 |
| $100,000 | 3 | 0 | 11 |

XLM has 21 days, because Tardis has no 2024-11-01 file for it. Dropping the 9 coin-days the author had already seen
changes no verdict among the first 11 coins. No snapshot was dropped as crossed or one-sided.

## The validation missed on 3 of 6 coins

| coin | $1,000 walk | #39/#41 half-spread | gap | inside 0.5 bp |
|---|---|---|---|---|
| BTC | 0.102 | 0.456 | −0.354 | yes |
| ETH | 0.259 | 0.629 | −0.370 | yes |
| SOL | 0.347 | 0.806 | −0.459 | yes |
| XRP | 0.426 | 0.957 | −0.531 | **no** |
| DOGE | 0.546 | 1.108 | −0.562 | **no** |
| LINK | 0.842 | 1.360 | −0.518 | **no** |

**The book walk reads lower than what real trades paid, on all six.** The direction is what you'd expect if trades
cluster when the spread is wider, but this test doesn't establish that as the cause. So **every cost here is probably low
by something like 0.35–0.55 bps a leg**, on those coins at least. Treat this table as a floor, and don't replace
`espero.costs` with it. That matters most where the margin is thin: at $10,000, HBAR's upper end of 4.36 plus 0.56 is
already past the 4.5 bps that an 18 bps round trip leaves for cost.

## Two days in the main group have only 5 levels

The registration put 2026-07-01 and 2026-08-01 in the 20-level group, but **`book_snapshot_25` has only 5 levels a side
on both, on every coin.** The check before registering had read a different file, `incremental_book_L2`, which still
has 20 on those days and narrows only by 2026-09-01. The registered rule keeps both days in, and the table above does.

**Information only, not the verdict:** the same rule on the 20 days with 20 levels.

| size | COVERED | NOT COVERED | UNKNOWN |
|---|---|---|---|
| $1,000 | 14 | 0 | 0 |
| $10,000 | **14** | 0 | 0 |
| $100,000 | **5** (adds SOL, DOGE) | **1** (kSHIB) | 8 |

So the 5 UNKNOWNs at $10,000 come from those two days. The mean costs barely move, because the visible depth changes
which snapshots can be priced, not the cost of those that can.

## The thin group: 2026-09-01 and 2026-10-01

Five levels a side. Share of snapshots the book couldn't fill, both days pooled:

| size | under 5% | 5–50% | above 50% |
|---|---|---|---|
| $1,000 | all 14 coins | | |
| $10,000 | BTC, ETH, SOL, XRP, LINK, kSHIB | DOGE, ADA, AVAX | BNB, TRX, LTC, XLM, HBAR |
| $100,000 | ETH | BTC, SOL, XRP | the other 10 |

This is a limit of the file, not evidence that Hyperliquid's book got thinner. Costs on these days are in the raw output.
The cause of the narrowing is unknown, and this test can't tell whether it's Tardis's recording or something upstream.

## What this does and doesn't mean

- **For #45's eight assumed-cost coins:** at $1,000 the 18 bps assumption is comfortably above the measured 9.9–12.3 bps
  round trip on ADA, AVAX, BNB, TRX, LTC, XLM, HBAR and kSHIB, including the validation's gap. At $10,000 XLM and HBAR have
  little or no margin. **#45 and every other frozen test keep their committed costs.**
- **COVERED means on these days.** They're the first of each month, with no known cascade among them. The moments a
  liquidation rule trades are the moments this sample is weakest on. This doesn't show those fills would be covered.
- **It charges the displayed book**, with no one reacting and no latency, and it can't see beyond 20 levels. Anything
  inside the 0.54 s between snapshots isn't seen. Resting orders are outside this test.
- **Not a strategy backtest.** 24 scattered days couldn't power an event rule, and none was tried.
- **Tardis's paid data isn't needed for this question now.** The free days answered it at $1,000. A paid month would add
  days, but the book file's narrowing would still limit what recent data can say at larger sizes.
