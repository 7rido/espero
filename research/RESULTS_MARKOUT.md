# Result — what our fills actually cost, measured on prints (#39)

**Q3: NO.** No condition gives a resting order a positive markout after the maker fee: 0 of 288
cells pass. A back-of-the-queue fill loses 0.7–2.5 bps to adverse selection **before** fees, in
every coin, venue, horizon and condition.

**Q1: the 18 bps hurdle was too high for a small fill.** The measured taker round trip, fees
included, is **9.9–11.3 bps**.

**Q2: of the open leads, only #31 survives the measured cost.** #29 does not. #38 cannot be judged
on these four coins.

Spec: [PREREGISTRATION_MARKOUT.md](PREREGISTRATION_MARKOUT.md) (`98bddef`, pushed before any
download). Code `0c3b64f`. Run as printed `c313be8`. Liquidation fix `8cc416f` (see Transparency).
Output in [markout_run_liqfix.txt](markout_run_liqfix.txt) (complete) and
[markout_run.txt](markout_run.txt) (the first report, cut short). Day rows in
[markout_days.csv.gz](markout_days.csv.gz). The importable table is
[`espero/costs_table.py`](../espero/costs_table.py).

## The two sentences

1. **Paying the spread is cheap; being filled is what costs.**
   - A small taker pays 0.3–1.0 bps of half-spread on top of the fee.
   - A small maker at the back of the queue gets filled exactly when the price is about to go
     through its level, and loses about as much as the taker saved.
2. **The front of the queue earns; we would not be there.** On Binance SOL and XRP, the average
   liquidity provider makes +0.1 to +0.4 bps (the optimistic bound). The back of the queue loses
   −1.0 to −1.2 bps on the same prints. That is #30's −21.7 vs +63.9 bps, at tick resolution.

## Data

- **Coin-days.** 1,004 reduced, 0 dropped, 0 errors.
  - B (Binance archive): 210 days × 4 coins.
  - V1: 10 × 4. V2: 7 × 4.
  - H (Hyperliquid, Tardis): 24 × 4.
- **Proxy validated on every (coin, horizon), on both V1 and V2.** The largest gap was XRP's
  conservative 1 s markout on V2: −0.86 proxy vs −1.08 quote, inside the 0.25 bp tolerance.
- **Second source replicated.** Tardis trades matched the archive's `aggTrades` in all 36 "all"
  cells.
- **Hyperliquid stands on one source.** The collector's 1-minute candles start 2026-10-27, after
  the last free Tardis day.

## Q1 — measured cost per leg

"All" cells, bps. Each round trip = 2 × (fee + half-spread). The conservative maker markout is at
60 s. t is over days.

| venue | coin | half-spread | taker round trip | maker markout, optimistic | maker markout, conservative |
|---|---|---|---|---|---|
| Binance (5.0 / 2.0) | BTC | +0.33 | **10.67** | −0.54 | −0.81 (t −66) |
| | ETH | +0.37 | **10.74** | −0.49 | −0.80 |
| | SOL | +0.66 | **11.31** | +0.39 | −1.18 |
| | XRP | +0.54 | **11.09** | +0.10 | −1.10 |
| Hyperliquid (4.5 / 1.5) | BTC | +0.46 | **9.91** | −0.59 | −1.42 (t −25) |
| | ETH | +0.63 | **10.26** | −0.38 | −1.81 |
| | SOL | +0.81 | **10.61** | −0.39 | −2.08 |
| | XRP | +0.96 | **10.91** | −0.26 | −2.52 |

**By condition** (Binance, conservative maker markout at 60 s / taker half-spread):

| condition | maker markout | taker half-spread |
|---|---|---|
| liquidation hours | **worst**: −1.1 to −1.4 (vs −0.7 to −1.1 in other hours) | **highest**: +0.47 to +0.78 |
| flow "with" (the maker trading the same way as the last 10 s of aggressors) | worse: −1.0 to −1.6 | |
| flow "against" | least bad: −0.7 to −1.0 | |
| settlement window | slightly less bad than other times | |
| spread | barely matters on Binance | about 2× higher on a wide spread on Hyperliquid |

**Over time.** 2023–24 (V1, real quotes) is close to 2026 for BTC and ETH, so costs have not
drifted much.

**What it means.**
- The 2 bps of slippage each side in the 18 bps hurdle is about 4× what a small fill actually pays
  in spread. Every frozen test keeps its 18 bps; new tests should import `espero.costs`.
- **Size matters on Hyperliquid.** Its above-median prints paid +0.54 to +1.28 bps. A larger
  account pays more than this table says.

## Q3 — can resting orders earn here?

**NO, by a wide margin.**

- The best cell, net of the maker fee, is still −2.9 bps: Hyperliquid XRP, 300 s, settlement window.
  Its day t is −2.7, with both halves negative.
- No cell is positive before fees, let alone after.
- The optimistic bound has 0 cells clearing the bar net of fees either.

**`hftbacktest`, information only.** It ran on 4 hours of real Level 2 data, Binance BTCUSDT,
2026-10-01 00:00–04:00 UTC. The full day (796 MB compressed) exhausted 16 GiB while converting, so
the slice was a bounded retry.
- A 0.001 BTC post-only bid re-joined the best bid every 60 s.
- It filled 76–78% of the time.
- 60 s markout: **−0.94 bps** (risk-averse queue) and **−0.85 bps** (power-prob queue). The standard
  error is about 0.23.
- My bounds for that day were −0.55 (optimistic) and −0.81 (conservative). A real queue model lands
  **at or past the conservative bound**, so that bound is not too harsh.

## Q2 — the open leads, re-priced

Information only. The forward tests' criteria, hurdles and windows are unchanged.

| lead | venue | days | gross | net, measured cost | survives (net > 0, t ≥ 2) | clears 4.60 |
|---|---|---|---|---|---|---|
| #29, 16:00 → 16:15 ET | Binance | 596 | +6.0 (t 5.6) | **−4.7** (t −4.4) | no | no |
| | Hyperliquid | 596 | +6.0 | **−4.1** (t −3.8) | no | no |
| #29, 16:00 → 17:00 ET | Binance | 596 | +8.1 (t 3.7) | −2.6 (t −1.2) | no | no |
| | Hyperliquid | 596 | +8.1 | −2.0 (t −0.9) | no | no |
| #31, 2-ATR bid, 4h exit, **4 of 40 coins** | Binance | 158 | +16.0 (t 5.4) | **+11.2** (t 3.7) | **yes** | no |
| | Hyperliquid | 158 | +16.0 | **+12.2** (t 4.0) | **yes** | no |
| #38, Mondays 00:00 2020–26 | either | 9 | +49.2 (t 1.0) | +38 (t 0.8) | no | no |
| #38, every settlement, Apr–Oct 2026 | — | 0 | no events | — | — | — |

- **#29 is dead at any realistic cost.** Its 6–8 bps reversal is real (t 5.6), but smaller than one
  measured round trip of about 10.7 bps. Its forward test runs on, frozen. A PASS there would still
  not pay a taker.
- **#31 survives on its four majors.** Its rule already demands a trade-through, so its gross
  already carries the adverse selection, and the maker legs are priced at the fee.
  - This is my reading of the pre-registration's "maker entry at the conservative markout". The
    other reading also subtracts the entry's 60 s conservative markout. That counts the post-fill
    path twice, and still leaves **+10.3 bps (t 3.4) on both venues**.
  - It does not test #31's 40-coin breadth claim.
- **#38 cannot be judged on these coins.** Only 9 coin-Mondays in 6.8 years had shorts paying hard,
  and a t on 9 observations means nothing. No settlement on these four coins in April–October 2026
  reached −0.05%; the lowest was −0.039%, on SOL. #38's events live in the other 38 coins.
- **#34 and #37 are out of this model's reach.** The reasons, and what would be needed, are in the
  pre-registration's Scope.

## Transparency

- **The liquidation condition never matched in the first run.** `aggr.panel`'s index is at
  second resolution. `liq_hours` divided it by 10⁶ as if it were nanoseconds, so no fill was flagged.
  - It was found after the report printed. The run was committed as printed (`c313be8`), then the
    unit was fixed with a range guard (`8cc416f`), and set B was rerun.
  - The rerun changed **only** the liquidation rows: 8,622 of 334,576 day rows, all `cond == liq`.
    Every other cell is bit-identical.
  - Q3 was NO before and after: 0 of 272 cells, then 0 of 288. The table above uses the fixed run.
  - The test suite missed it because the smoke test fed the job a hand-built millisecond array and
    never exercised `liq_hours`.
- **The first report's log is truncated.** `markout_run.txt` was cut short by a `head -150` in the
  pipe. `markout_run_liqfix.txt` is complete.
- **Cell count.** Q3 examined 288 cells, not 320: Hyperliquid has no liquidation condition (set L
  covers Binance only). The bar stayed at 4.60, as pre-registered.
- **The #31 pricing reading** above, with both numbers shown.
- **The venue note rests partly on secondary sources for fees.** It says so.
- **The pre-registration's own Transparency section** lists what was seen before it was written,
  including 300 bytes of an undecoded gzip.

## What this changes

- **`espero/costs.py` ships with 360 measured cells.**
  - New tests price legs with `costs.leg` / `costs.round_trip`.
  - It raises for any coin it did not measure.
  - Frozen tests keep their 18 bps.
- **NO on Q3, as pre-registered.**
  - Rules that depend on maker fills are priced at the conservative bound from now on.
  - "Rest a bid and wait" ideas are closed for this account's size and venues, unless a new data
    source changes the picture.
- **The one useful lever left in execution is when to cross, not whether to rest.** Avoid
  liquidation hours and wide spreads (on Hyperliquid, about 2× the half-spread). Cross against recent
  flow, not with it.
- **What would confirm this independently**: real fills on a regulated US venue, reconciled against
  the FCM's daily statements. See [VENUE_CONFIRMATION.md](VENUE_CONFIRMATION.md). Nothing was placed.
