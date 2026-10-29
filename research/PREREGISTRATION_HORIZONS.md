# Pre-registration — at which holding period do the repo's real signals pay? (#43)

Committed **before any long-horizon outcome is computed**. A paper study: nothing trades. The
forty-fourth test in this repo.

## Why

Several signals here are real, but small. Each beats chance by a margin no luck explains, yet earns
less per trade than a round trip costs at the horizon it was tested on:

| test | signal | as tested |
|---|---|---|
| #20 | new 4-hour lows bounce | 1 h, t 9.8 |
| #26 | forced down-breaks bounce | 1 h, t 7.1 |
| #33 | price falls after settlements where shorts pay hard | 30 min, t −4.4 |
| #12 | carry pays the side receiving funding | income |

The arithmetic: a tilt of p earns about (2p − 1) × the typical move. A small round trip costs about
11 bps (#39, #41). At 1 hour a 51% tilt makes about 1 bp. At 1 week, where BTC moves about 650 bps,
the same 51% makes about 13. **The question is whether any of these tilts survives to a horizon
where it clears the cost.** No signal here has been measured past 4 hours.

## Signals — definitions frozen, direction fixed

| # | signal | entry | side |
|---|---|---|---|
| S1 | #20's trigger: a new 4-hour low on a down-break, by `espero/lows.py::events(b, "down", skip=excluded_days())`, one per coin per hour | the open of the bar after the trigger | long |
| S2 | #38's: an 8-hour settlement (00/08/16 UTC) whose settled rate, scaled to 8 h, is **≤ −0.0005** | the open of the 5-minute bar at the settlement, P(t) | short |
| S3 | carry, #12's logic: at each 8-hour settlement, rate **> +0.0001** (longs pay more than the default) → short; rate **< −0.0001** → long | P(t) at the settlement | the side receiving funding |
| S4 | control, #15's trend: all three of 28-, 91- and 364-day returns positive at the 00:00 UTC daily close | the open of the first bar after 00:00 | long |
| S5 | #26's forced down-breaks (`research/liq2_events.csv.gz`, direction down, forced), **information only** | its recorded entry | long |

- **Rates** come from `data/settle/funding/`, Binance USDⓈ-M settled funding, 2020 → 2026-10-29.
  They are read by **#33's own function** (`espero/fillcost.py`'s reader of Binance funding rows).
  It returns each settlement's minute and `rate8`, the rate scaled to 8 hours by the time since the
  coin's previous settlement. S2 and S3 use only settlements at 00, 08 and 16 UTC. Funding charged
  over a hold uses the raw settled rates, not `rate8`.
- **S1 regeneration.** S1's events are regenerated on the combined bars (`data/lows/` to 2026-03,
  then #30's chain of caches to 2026-10-27). A test must show that on 2020-01 → 2026-03 they equal
  `research/lows_events.csv.gz` exactly (count and timestamps), before any outcome is computed.

## Coins and costs

- **Coins.** The ten `espero.costs` prices on Hyperliquid: BTC, ETH, SOL, XRP, DOGE, LINK, WLD, ARB,
  OP, TIA. Each coin's events start once it has bars, funding and, for S4, 364 days of history.
- **Primary cost.** The Hyperliquid taker round trip, `costs.round_trip("hyperliquid", coin)`, at
  the "all" cell.
- **Information.** The Binance round trip on the four majors.
- **Funding over the hold.** Every Binance settlement in (entry, exit] is charged: a long pays a
  positive rate, a short receives it. It is Binance's history applied to a Hyperliquid-priced
  trade, because that is the history that exists. This is stated, not hidden.
- **Spot-equivalent** (no funding, long signals only) is printed as information.

## Horizons

1 h, 4 h, 12 h, 1 day, 3 days, 1 week, 2 weeks. The exit is the close of the bar that ends at
entry + h. A trade whose exit bar is missing is dropped.

## The trade — one position per coin at a time

The primary measure runs each signal as a book could. A coin takes a new entry only once its
previous hold has ended; events arriving during a hold are skipped. That is return per unit of
capital-time actually deployable, with non-overlapping trades within a coin.

**Net per trade** = side × (exit / entry − 1) − round trip − side × Σ funding over the hold.

All events, overlapping, are printed as information.

**Statistic.** Each entry day's mean net is one observation. t is Newey-West with lags = max(1,
⌈h in days⌉), as `factor_eval.newey_west_t` computes it.

## Two stages — choose, then confirm on data the choice never saw

1. **Selection: trades whose whole hold ends by 2024-12-31.**
   - For each of S1–S4, the chosen horizon is the one with the **largest net t**, among horizons
     with net > 0 and t ≥ 2. A signal with no such horizon is not carried forward.
   - Whether each selection cell clears the deflated bar for this study is printed as information.
     The bar counts 43 earlier tests plus 5 signals × 7 horizons = 35 cells, so N = 78: t ≥ **4.09**.
2. **Confirmation: trades entering on or after 2025-01-01**, ending by 2026-10-27. Nothing between
   the stages is used. A late-2024 entry whose hold crosses into 2025 belongs to neither.

**A carried signal is CONFIRMED when all four hold:**
1. Its holdout net at the chosen horizon is > 0, with Newey-West t clearing **Holm's** threshold at
   a family α = 0.05 one-sided across the carried signals. With k carried, the smallest p must be
   ≤ 0.05/k, the next ≤ 0.05/(k − 1), and so on.
2. Net > 0 in each holdout half: 2025-01-01 → 2025-11-30 and 2025-12-01 → 2026-10-27.
3. **No collapse.** The holdout net is at least **one third** of its selection net. A horizon chosen
   because it was lucky halves out of sample; that is regression to the mean, not confirmation.
4. **Not already seen.** A cell whose holdout numbers were seen before this pre-registration cannot
   pass. Its confirmation is printed, marked "seen". That covers:
   - **S1 at 1 h and 4 h**: the yearly re-pricing in [RECHECK_COSTS.md](RECHECK_COSTS.md) showed
     2025 and 2026.
   - **S2 at 1 h**: #33 printed Monday settlements through 2026.

**Power, printed before any signal outcome.** For each horizon the run first prints a minimum
detectable net effect from the ten coins' **unconditional** returns in the selection window:
- MDE = 2.49 × sd(trade return at h) / √(expected non-overlapping trades);
- 2.49 is 80% power at one-sided 5%.

A null at a horizon reads as "nothing larger than its MDE", not "nothing".

## Outcomes, fixed now

- **A confirmed signal**: a forward paper test is pre-registered next, on an instrument a US person
  can hold (CME micro futures, or Coinbase or Kraken US perps), priced at that venue's published
  costs and funding. Nothing trades on this result.
- **None confirmed**: the days-to-weeks question is answered negative for these signals, and the
  allocation study (the risk-premia framework) is next.
- **#26 (S5)** enters no confirmation, because its liquidation data ends in 2024-10. #27 already
  tests it forward.

## Transparency — what I saw before writing this

- **#20's 1 h and 4 h yearly nets on these coins**, 2020–2026, in RECHECK_COSTS.md. That is why
  those holdout cells are marked "seen".
- **#33's Monday results**, 2020–2026, at 15, 30 and 60 minutes.
- **#38's re-pricing**: no hard shorts-pay settlement on the four majors in April–October 2026.
- **#26's 1 h, #32's 1 h and #12's results**, as published.
- **Coverage only, not outcomes**: the funding cache's date range (2019-12-31 → 2026-10-29),
  liq2's range (2023-06-26 → 2024-10-14), and the bar caches.
- No outcome at 12 h or longer has been computed for any signal.
