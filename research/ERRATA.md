# Errata

Corrections to published research results, newest first. A result is never re-run to
change its verdict; the code that produced it stays as it ran, marked with a comment that
points here. Numbers below were reproduced from cached data during the 2026-10-27 audit
(docs/AUDIT_2026-10-27.md, section D) unless stated.

## 2026-11-02: #62's replay walks the recorded frame itself, and rests orders on hftbacktest's no-partial-fill exchange

**No tolerance, latency, queue model or criterion changes; written before any fill existed on the tape (0 at
registration).** `PREREGISTRATION_REPLAYSIM.md` says a market order "fills against the levels on the tape at
arrival, walking the book; hftbacktest's partial-fill exchange model". `espero/replaysim.py` walks the last
whole `l2Book` frame before arrival directly (Hyperliquid's frames are whole books, so the walk is the same
sweep with no engine between), and runs the mirror's resting orders through hftbacktest's
`NoPartialFillExchange`, because 2.4.4's `PartialFillExchange` stops with error 14 at the first print on a
tape of whole-book frames, the library's own Hyperliquid converter's output included (checked 2026-11-02, the
two event arrays being identical). A resting order therefore fills whole once the queue ahead clears, or not
at all; the registered question, filled or not, is unchanged. Recorded here, dated, before the first comparison.

## 2026-10-31: #27's forward ledger crashed on its first day with data

**No rule, cost, criterion or verdict changes.** The daily job's `liqbreak` step failed at 07:31 EDT on 2026-10-31,
the first run with a recorded day. A coin with no breaks that day returned an empty table with object-typed columns.
Joining it left every column object-typed, and `liq.usable` crashed on `np.isfinite`. `espero/liqbreak.py` now leaves
empty tables out of the join; an empty table adds no rows, so the ledger's contents are what the rule always meant.

- **No data was lost.** `record()` runs before the ledger, so 2026-10-30's file was saved, and the ledger is rebuilt
  from every saved day on each run. The 2026-10-31 run left no #27 ledger; the next run writes it whole.
- **What was seen while fixing it:** column types, and which coins had a break on 2026-10-30 (12 of 14). The ledger,
  and the `fundsplit` and `liqhold` steps that read it, were run in a scratch folder to check they finish. Their
  counts, returns and notes were not printed or read.

## 2026-10-30: #2's design headline does not reproduce; defects in Binance's archive (found by the substrate, #48)

**No verdict changes.**

- **#2's design period** re-runs at +97.10% a year and Sharpe 1.19 against the published +115.27% and 1.28, on
  Coinbase candles fetched 2026-10-30. Its original inputs were never kept, so the cause is not established;
  dropping the earliest history moves the figure between +27% and +101%, so the panel's start date matters a lot.
  Its holdout reproduces exactly (−29.75%, Sharpe −0.06). BTC's holdout row comes out +23.81% against +23.30%.
- **`aggTrades` for 2022-09-12** holds every print twice in the archive, on ETH, SOL and XRP at least. No published
  result used that day. Anything summing those files must de-duplicate on the id.
- **Monthly hourly bars lack days**: 2022-02-26 → 28 and 2022-04-01 → 02 on SOL, LTC, NEAR, ZEC and XRP.

## 2026-10-29: 打板 (`espero degen`) takes its coin list and bars from Hyperliquid

`degen scan`, `backtest` and `paper` now rank Hyperliquid perps by 24h dollar volume and read their
bars from Hyperliquid by default, charging Hyperliquid's fees; `hyperliquid` is a default backtest
row and a choice in the UI. `--source coinbase` restores the old path exactly.

- **No published number moves.** #10 and #13 were run on Coinbase spot (`--source coinbase`), and
  their verdicts are read on the Binance.US row with Kraken as the check. A Hyperliquid run prints
  its verdict lines marked information only.
- **Shorter history.** Hyperliquid serves the last 5,000 bars: 17 days of 5-minute bars, not the
  30 the backtest asks for; the command says so and uses 17. Its bars are cached apart
  (`*_hl.csv`).
- **Separate books.** The paper loop's default journal is `degen-hl.db` on Hyperliquid and stays
  `degen.db` (#10's) on Coinbase, so perp and spot bars never share a book.
- **Per-1,000 perps** (kPEPE, kBONK) are listed as `PEPE-USD` and priced per coin.

## 2026-10-29: the XS account moves to Hyperliquid prices; the scan and fast screen too

**No verdict changes.** At the user's request, crypto prices for the live tools come from
Hyperliquid's mainnet perps instead of Yahoo (spot) and Coinbase:

- **XS account** (`xs.SOURCE`): 35 of its 42 coins (MKR, YFI, XTZ, EOS, KSM, VET and THETA are not
  listed), daily closes of completed bars only. The record's first two days stand on Yahoo. The first
  Hyperliquid mark is about +2.5% above the last Yahoo mark (\$102.03 vs \$99.58 on a copy at
  06:40 UTC), mostly timing rather than source: Yahoo's marks used the day still forming,
  Hyperliquid's use the last completed bar. Perp prices track spot but are not spot.
- **Scan and fast screen**: Hyperliquid candles, live book and prints, fills at its maker fee
  (1.5 bps), paper only: Hyperliquid's mainnet excludes US persons. `--source coinbase` keeps the
  old feed; #9b's results were measured on Coinbase.
- **The board's coins** come from Hyperliquid; its ETFs stay on Yahoo. #15's frozen result reads
  its own snapshot and does not change.
- **#8 stays on Yahoo**; a Hyperliquid shadow runs beside it, information only (FORWARD_MF.md,
  amendment 2026-10-29).

## 2026-10-29: the #4 TSMOM paper account ignored dividends and could break on a split

**#4's verdict is untouched; the live account's accounting is fixed from 2026-10-29.**

- `tsmom.py` held share counts marked at Yahoo's raw closes, so SPY, TLT, GLD and USO earned price
  only. Over ten years that is TLT ×0.62 instead of ×0.83 with its coupons, SPY ×3.62 instead of
  ×4.24. And a split Yahoo restates into the history would have multiplied a share count bought
  before it (USO, held now, did a 1:8 reverse split in 2020).
- Now each run first rolls every position's value at the last run forward by its adjusted close
  (now ÷ then, both from the same fetch, so a restatement cancels), then turns it back into shares
  at today's price: dividends are reinvested on the ex-date and splits cancel. The signal still
  reads raw closes, as #4 was registered. The first run after the fix marked exactly as before
  ($200.81): no dividend or split fell between 2026-10-27 and the fix, so nothing before it is
  restated.

## 2026-10-29: #8's forward test books Monday fills at a price its schedule cannot trade

Disclosed before the first fill, rule unchanged: research/FORWARD_MF.md, amendment 2026-10-29. The
00:00 UTC open is information-equivalent to the decision (nothing after Sunday's close is read), but
the job runs at 07:30 New York; the verdict will report the open-to-run gap for every Monday.

## 2026-10-29: Yahoo ticker collisions in `xs.UNIVERSE` (found by #15)

**No verdict changes; two live accounts read wrong series for some coins.**

- **`ARB-USD` on Yahoo is not Arbitrum.** It is a dead token: last close $0.0006 on zero volume.
  `TIA-USD`, `WLD-USD` and `OP-USD` are other tokens until Yahoo switches them to the real coin,
  with one-day jumps of +68,063,639% (2024-03-26), +31,092% (2023-08-02) and +200,020%
  (2022-10-06). Found in #15's snapshot (research/RESULTS_TREND.md, transparency).
- **#8 (multifactor, `mf.py`)** filters coins on $1M of 30-day dollar volume, which keeps the dead
  `ARB-USD` and the impostor periods out. Its lookbacks are 30 days, and its holdout
  (2024-07-01 → 2026-10-27) starts after all three switches, so no holdout window straddles one;
  the OP and WLD switches fall in its design period. Verdict unaffected; the forward test from
  2026-11-02 trades only coins that pass the filter.
- **The XS account (`xs.py`, #7's rule) held the dead token from its first day.** It has no
  liquidity filter, and on 2026-10-27 ARbit's flat 0.0% week ranked #2 of 42 because most coins
  fell, so 10% of the book ($9.99 at init) sat in a series with no trades, marked at $0.000629.
  Fixed 2026-10-29, without rewriting its history:
  - `xs.YAHOO` maps ARB to `ARB11841-USD` ("Arbitrum USD" in Yahoo's metadata; `ARB-USD` is
    "ARbit USD"). TIA, WLD and OP need no mapping: Yahoo now serves Celestia, Worldcoin and
    Optimism under them, and their wrong histories end before the account's two-year window.
  - A series that traded under $10,000 in its last 7 bars is not ranked (Yahoo quotes crypto
    volume in dollars; the smallest real coin in the list, KSM, trades about $14M a week). This
    catches the next silent swap; it excluded none of the 42 coins on 2026-10-29.
  - Once per account, before any mark at the new prices, units bought on a re-mapped series are
    closed to cash at that series' last print, at no cost (there was no market to trade them in),
    and saved as a `correction` row. Without it the ARbit units would have been marked at
    Arbitrum's $0.1655, a 263× jump. The cash waits for the next Monday rebalance.
  - The record's first two days stand as they ran: ARB contributed nothing to them (its price
    never moved), which is what holding a token nobody trades looks like.
- **Not changed:** #8 keeps `ARB-USD` (its forward test must run the universe its backtest ran, and
  the $1M filter already excludes it), as does #15's frozen universe; `espero board --alts` lists
  it as failing the liquidity rule.
- **`SHIB-USD`** is printed as exactly 0 on 258 days (2020-08-01 → 2021-04-15): any lookback that
  reaches back to them compares against zero.

## 2026-10-28 (later): degen replay clock

**#10's verdict (FAIL) stands; two of its explanations do not.**

- **Timestamps 1000× too small in the degen backtest** (espero/cli.py `_cmd_degen_backtest`).
  pandas 3 parses the cached candle strings to `datetime64[us]`, and `astype("int64") // 10**9`
  assumed nanoseconds, so a 5-minute bar advanced `ts` by 0.3. Bars sharing one integer `ts`
  overwrote each other in the replay (about two in three were dropped from trading, though the
  features still saw them), the 36-bar time stop could not fire, the daily loss cap read every
  bar as 1970-01-21, and the stale-order check never fired. Live loops were not affected: they
  take `ts` from the API as integers. Fixed in `0f9bebf` (`data.unix_seconds`), with a guard that
  refuses a frame whose bar spacing is not the granularity.
- **#10 reproduced on its own 60 cached files with the corrected clock** (Binance.US fees):
  812 trades (as run 180), profit factor 0.98 (0.78), net −$12.60 (−$40.94), max drawdown 30.0%
  (12.8%), Kraken −$280.14 (−$173.21). Still FAIL on four criteria. But RESULTS_DEGEN's "loses
  money before fees" is wrong: with about $35 of fees on 812 trades, the gross is near
  **+$22, roughly break-even**. Its "half the stops are gaps, the breakout bar is the climax" is
  also an artifact: corrected, 51 of 586 stops are gaps.
- Also corrected, not used by any result: `data.fred_series` and `carry_paper._close_at`'s
  fallback built `ts` the same way.

## 2026-10-28

**No published PASS/FAIL verdict changes.** Two items change how strong a reported number is.

### Reported statistics that overstate

- **Factor t-stats ignore overlapping returns** (RESULTS_MF, RESULTS_LEADLAG, RESULTS_LEADLAG2).
  `factor_eval.summarize` reports t = ICIR·√n on daily ICs of overlapping h-period forward
  returns; neighbouring ICs share h−1 periods of the label, so under a null the reported t has
  a standard deviation near 2 instead of 1 at h = 5. MF composite: plain t 8.11; Newey-West
  4.5–5.0; every 5th day only, 3.15. MF's criterion (OOS t > 3) still passes, narrowly on the
  non-overlapping check. The "expected best null t" printed beside the table assumed
  independent dates and is too low. LEADLAG's t of 13–17 are inflated the same way; it failed on
  spread, so its verdict stands. From this date `evaluate` also reports `t_oos_nw`
  (Newey-West, 2·(h−1) lags); the pass column stays the pre-registered plain t.
- **Carry Sharpe depends on sampling frequency** (RESULTS_CARRY, RESULTS_CARRY2). The
  criterion is the Sharpe of hourly marks, which carry two-venue basis noise that reverts
  within hours (lag-1 autocorrelation about −0.5). On daily closes: #12 7.2 against 1.77
  reported; #11 3.5 against 0.88; ablation A 5.3 against 1.35; ablation B 7.1 against 1.71.
  No verdict flips: #11 and both ablations fail other criteria. The #12 forward test keeps the
  pre-registered hourly criterion; `espero carry status` now shows both.

### Biases that favour a pass

- **Carry universe chosen today** (research/carry.py). Today's top 20 perps by open interest
  were applied to history. Disclosed in the results, but #12 is the pass it could inflate:
  coins that are large now are the ones whose funding stayed positive. The forward test is the
  only control.
- **PEAD** (research/pead.py): same-day close exits fund same-day open entries, entry sizing
  marks open positions at that day's close, and the universe is today's mega-caps. All favour a
  pass, so its FAIL is robust.

### Small deviations from the pre-registered text

- **Momentum lookback one bar short** (research/tsmom.py, xs20.py, momentum.py):
  `iloc[-LOOKBACK]` measures LOOKBACK−1 bars (251 days, not 252; 29, not 30). TSMOM passed
  narrowly (Sharpe 1.08 against the benchmark's 1.02), so a boundary month could move a pick.
  Not checked: its input CSVs are not on disk. The live `espero/tsmom.py` measures 364 calendar
  days and is not affected.
- **Carry time stop** (espero/carry.py, also the forward books): exits after 30 days even when
  the coin still qualifies, then may re-enter it the same hour (4 of 11 time exits in #12). The
  pre-registration says "after 30 days without re-qualifying". Conservative: the round trips
  cost money. The forward books keep the rule as run.
- **One missing hour blanks the carry signal for a week** (espero/carry.py): the 168-hour
  rolling mean needs every hour, so a single gap gives 168 hours of NaN and a no_data exit (ZRO:
  322 NaN hours from 2 gaps; XPL: 168 from 1; one no_data exit in #12). The forward books
  average the last 168 published rates and do not do this.
- **Lead-lag training minimum** (research/leadlag.py): `MIN_TRAIN = 720` was never passed to
  `fe.evaluate`, so the run used 180 hours against the pre-registered 30 days. This moves the
  split edges and the in-sample column; the FAIL was decided on spread and stands.
- **TSMOM benchmark cap** (research/tsmom.py): the equal-weight benchmark keeps its 1/6 cap
  when fewer than 6 assets are eligible (2010–14: 4 eligible, a third in cash). Design period
  only; all 6 are eligible in the holdout.
- **Multifactor marks** (research/multifactor.py): a held coin with a missing close drops out
  of equity that day. Latent: the gaps fall before those coins are eligible, and a re-run with
  forward-filled prices is identical.

### Fixed in code

- **LP simulation trading P&L** (research/lp_sim.py, LP_NOTES.md): rewards were subtracted
  from a cash balance they were never added to; each trading-P&L row was $12.48 too low. Fixed;
  the notes table is corrected and marked. Totals and the conclusion are unchanged.
- **Backtest annualisation** (espero/backtest.py, report.py): Sharpe and CAGR assumed daily
  bars. They now read the bar spacing (identical for daily bars; no result used other bars).

### Forward-test log

- **#12 carry books**, from 2026-10-28 about 02:25 UTC: the loops now backfill missed settled
  hours (up to 72 h), always fetch held coins, drop rows with missing prices and survive failed
  steps. No rule parameter changed; what the books record changed from this time.
- **#13 forward book** (`degen-1h.db`), started 2026-10-28, first bar 05:00 UTC, rule `13` on
  Binance.US fees, polling every 5 minutes. Registered 60 days (to 2026-12-27; to 30 trades or
  2027-02-25 at the latest if fewer). Started after the backtest had already failed, to record
  whether the live period agrees.
- **#10 and #13 forward books stopped early**, 2026-10-28 about 06:20 UTC, at the user's request:
  both backtests had already failed, so the forward tests could not change either verdict. #10
  (`degen.db`, registered to 2026-11-10): 13 closed trades, 1 win, −$18.93, equity $481.07, flat
  when stopped. #13 (`degen-1h.db`): one bar, no trades. Neither is a forward result; both
  journals are kept. The user's Coinbase-fee book in Terminal 8 (`degen-coinbase.db`) is not
  part of any test and was left running.
