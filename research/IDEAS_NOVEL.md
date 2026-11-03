# Edges almost no one trades — a working list

Written 2026-10-29. Each idea below has a **mechanism**: someone is forced to trade, or information is
public and unused. Each comes with the data that would test it and its status.

"Almost no one" means I know of no public test of it. I cannot prove nobody trades it. Nothing here is
a result until it passes the repo's rules: pre-registered, run once, verdict kept.

## Where this repo says edges live

- **Patterns failed.** Breakouts (#10, #13), lead-lag (#9, #9b, #16, #17), catch-up trades and
  indicator votes all died on costs or on new data.
- **Forced flow survived.**
  - #26: liquidations overshoot and come back, the one full PASS.
  - #12: funding is rent paid by crowded leverage (provisional).
  - #19 and #20: real, but too small to trade.

So the search is for flows that are **forced, scheduled, or visible before they happen**, in places
that are new (2024–26 instruments) or where the data exists but nobody has shaped it into a signal.

## 1. The US session's move reverses after the close (#29, running)

- **Mechanism.** US flows push BTC and ETH during the session: spot-ETF creations, leveraged-ETF
  hedges, US desks. When they stop at 16:00 ET, part of their price impact wears off. #26's
  reversal, on a clock.
- **Evidence.** #28's information rows: −6.0 bps in the 15 minutes after the close (t −5.6) on NYSE
  days since mid-2024. Flat on weekends. Larger on bigger days. Present in 2024, 2025 and 2026.
- **Status.** A forward test, judged after 2027-03-31
  ([FORWARD_POSTCLOSE.md](FORWARD_POSTCLOSE.md)). At taker costs it is an execution edge, not a trade:
  on an up day, a buyer pays about 6–10 bps less by waiting until after 16:00 ET.

## 2. 2x funds push small coins into the close

- **Mechanism.** A leveraged fund must trade A·L(L−1)·r at its 4 p.m. valuation, in the direction of
  the day's move. #28 found no push on BTC or ETH, which are too deep. It found one where the funds
  are large next to the coin: XRP +8.1 bps (t 4.0) and SOL +3.3 bps (t 1.9) on trading days since
  2x funds launched in spring 2025, against nothing on weekends.
- **The precise prediction.** The push grows with *fund assets ÷ the coin's dollar volume in the last
  15 minutes*. That ratio can be computed every afternoon before the trade. Issuers publish daily
  holdings, and Binance publishes volume.
- **Why almost no one trades it.** The alt 2x funds are months old, and crypto traders do not watch US
  fund mechanics.
- **Next.** Pre-register on the coins whose 2x funds launched since (SOL and XRP were seen in #28), or
  forward on all of them. Needs a small table of launch dates and daily assets.

## 3. Hyperliquid's exact liquidation ladder

- **Mechanism.** On Hyperliquid every open position, its size and its liquidation price are public.
  Addresses come from the trade feed; each one's state is a free API call. That gives the *exact*
  ladder of forced orders below and above the price, where every other venue offers estimates
  (Coinglass-style heatmaps).
- **Prediction.** Two parts, both from #26's mechanism:
  1. the price moves faster through a dense band (the cascade);
  2. it reverts once the band is spent.
- **Why almost no one trades it.** People use this data to hunt single whales, not as a systematic
  ladder.
- **Next.** Forward only, because there is no history. A collector that snapshots positions hourly
  (rate limits allow the top few thousand accounts), then a pre-registered test after a few months.
  Reading public data is allowed; trading Hyperliquid is not, for US persons, so it stays paper.
  Registered as #60, [FORWARD_LADDER.md](FORWARD_LADDER.md); window opens 2026-11-05.

## 4. HLP's inventory

- **Mechanism.** Hyperliquid's own market-making and liquidation vault (HLP) is a public account. When
  it absorbs a cascade, it holds inventory it did not choose and works it off. That is forced flow
  with a visible size.
- **Prediction.** A jump in HLP's net position predicts the next hours' drift as it unwinds. Or, if
  HLP absorbed the bottom, it predicts the bounce. Pre-register the sign from the mechanism (HLP's
  forced buys at the bottom revert) before collecting.
- **Next.** Forward only; the same collector as #3. Registered as #58, [FORWARD_HLP.md](FORWARD_HLP.md), and #59, [FORWARD_HLP2.md](FORWARD_HLP2.md), which changes only the guard; windows open 2026-11-05.

## 5. Ethena's hedge as a funding forecast (for #12) (#36 failed)

**Tested** ([RESULTS_ETHENA.md](RESULTS_ETHENA.md)): with funding's own level and reversion controlled, USDe flows forecast nothing (t +0.75); the raw correlation (t −2.2) is funding mean-reverting after high-yield minting. The original note follows.


- **Mechanism.** Ethena's USDe is backed by spot crypto plus **short perpetuals**, billions of dollars
  of them.
  - Minting USDe opens shorts, which absorbs long demand and **pushes funding down**.
  - Redemptions close shorts and **push funding up**.

  USDe's supply is public every day (DefiLlama's stablecoin history), and funding history is free.
- **Prediction.** A week of net redemptions predicts higher funding over the next week, beyond
  funding's own persistence. That is when #12's carry pays.
- **Why almost no one trades it.** It is used as a narrative ("Ethena compresses funding"), not as a
  timing signal.
- **Next.** A historical test is possible now (Feb 2024 → Oct 2026, daily). It must control for
  funding's own mean reversion. Low power; worth one honest run.

## 6. Stablecoin plumbing: the conversion comes before the purchase

- **Mechanism.** New money that arrives as USDC and wants Binance's deep USDT books converts first
  (USDT goes to a premium against USDC), then buys. Money leaving does the reverse after selling.
  The conversion should *lead* buying and *lag* selling.
- **Data.** Binance's USDCUSDT 1-minute archive. It has a gap from September 2022 to March 2023,
  when Binance converted USDC balances.
- **Risk.** It may live at a horizon of minutes, where costs win, and triangular arbitrage removes
  most of it. A cheap first look, and the most uncertain idea here.

## 7. Forced flow on forced flow: #26 after crowded funding

- **Mechanism.** #26 buys forced down-breaks. When funding was high beforehand, longs were crowded
  *and* paying rent, so more of the selling is forced, and the overshoot (and the bounce) should be
  larger.
- **Next.** Record funding beside #27's forward ledger from the start, and pre-register the split
  before reading it. No new data source: Binance's funding API is free.

## 8. The prediction-market crowd on the hour (#37 failed)

**Tested** ([RESULTS_POLYHOUR.md](RESULTS_POLYHOUR.md)): at minute 30 the crowd beats a random walk (Brier 0.1702 against 0.1733) and the model's bets earn nothing after costs. Lead: at minute 15 the same bet earned +4.7 cents (t 4.3). The original note follows.


- **Mechanism.** Polymarket runs hourly "Bitcoin up or down" markets. A fair price at the start of an
  hour is near 50%. Mid-hour it follows from the move so far and the volatility left. Retail crowds
  chase, so a lean after rallies would be mispricing **on Polymarket itself**, not a bitcoin signal.
- **Data.** Polymarket's public price history. The repo already reads its order book.
- **Limit.** Access for US persons is restricted, so this is paper and research only.

**Collecting since 2026-10-29.** `espero hlcollect` (under launchd; see docs/RUNBOOK.md) saves
the inputs that cannot be fetched later, for #3, #4, #10 and #14:
- the top 2,000 accounts' positions and liquidation prices, hourly;
- HLP's positions, every 15 minutes;
- every perp's funding, premium, open interest and prices, every 5 minutes;
- 1-minute candles, daily.

Each test still needs its pre-registration before its data is read.

## Ranking (my view)

| idea | why it may be unused | mechanism | data | cost to test | next step |
|---|---|---|---|---|---|
| 1 after-close reversal | ETF-era, US clock | strong | have | done | #29, running |
| 2 2x push on small coins | funds are months old | strong, quantitative | issuer files + Binance | small | pre-register on the newer funds |
| 3 HL liquidation ladder | exact data used for gossip | strong (#26's) | public API | collector + months | build a collector |
| 7 #26 after crowded funding | combines two edges | strong | free | small | add funding to #27's ledger |
| 5 Ethena → funding | used as a story | medium | free, daily | small | one historical run |
| 4 HLP inventory | public, unwatched | medium | public API | collector | with #3 |
| 6 stablecoin conversion | plumbing | uncertain | Binance archive | small | exploratory look, then sealed test |
| 8 Polymarket hourly | crowd mispricing | medium | public | medium | paper only |

## Execution ideas: making the "real, not tradable" effects tradable

Added the same day, from the scalper's side of the desk. Every "real, not tradable" verdict here
(#19, #20, #29's lead) assumed taker fills: 9 bps a round trip on Hyperliquid. A maker round trip
costs 3. The forced trader has to cross the spread, and the patient side collects it. These ideas
keep the prediction frozen and change **how** we trade it. That is a new question, with its own risk
(adverse selection), not a re-tuning.

### 9. Resting bids catch forced sellers (#30 failed; #31 running forward)

Rest a bid below a breakdown while the forced selling runs, and sell back at the breakdown price:
#20's bounce, bought as a maker, but only on the events that fall further.
- **#30 failed** at one ATR deep: +1.7 bps net per fill ([RESULTS_BIDS.md](RESULTS_BIDS.md)). The
  breakdowns that reached the bid went on to fall, and the ones that never did bounced.
- **Deeper bids paid** as information: +12.5 to +20 bps net per fill at 2–3 ATR, in every month.
- **#31** ([FORWARD_BIDS2.md](FORWARD_BIDS2.md)) tests a 2-ATR bid with a 4-hour exit on data from
  2026-10-30.

### 10. The funding snipe

Hyperliquid's small caps sometimes pay tens of bps per hour. Enter as a maker just before the hour,
collect one payment, and leave after. #19 measured the cost on Binance: the price swings about 15 bps
against the paying side around settlement. The test is where the payment starts to beat the swing
plus fees. It needs 1-minute prices around the hour, which Hyperliquid keeps for only a few days, so
it uses the same collector as #3.

### 11. Stop runs at obvious levels (#35 failed)

**Tested** ([RESULTS_SWEEPS.md](RESULTS_SWEEPS.md)): sweeps of yesterday's low bounce, but failed sweeps bounce more than reclaimed ones; the stop-run reading adds nothing beyond #20's mean reversion at lows. The original note follows.


Stop orders are forced orders too, and they cluster just past yesterday's high and low, the week's
extremes and round numbers. A sweep beyond the level that closes back inside should reverse, by #26's
logic. Retail trading lore calls these liquidity sweeps; I know of no proper test. It is testable on
the cached 5-minute bars: no level-based trigger has been run here.

### 12. Our own fills sit on Binance's settlement (#33: no cost on ordinary fills)

**Tested** ([RESULTS_FILLCOST.md](RESULTS_FILLCOST.md)): the 00:00 fill is unbiased for 93.5% of coin-Mondays (+1.1 bps). The one bias is on coins whose shorts pay hard: the price falls 19–34 bps in the 30 minutes after a settlement. The original note follows.


XS and #8 fill at 00:00 UTC, the minute Binance settles funding, where #19 measured swings of about
15 bps on high-funding coins. Measure what the bot pays at 00:00 against 00:15 or 00:30 on its own
coins. #8 is frozen, so any change needs its own document.

### 13. The after-close reversal with resting orders

#29's 6–10 bps is below taker costs and above maker costs. If #29 confirms it, the trade is a resting
order on the fade side at 16:00 ET. Waits for #29's verdict.

### 14. Hyperliquid's price against Binance's

When Hyperliquid-only liquidations push its price away from Binance's, arbitrage pulls it back. Trade
Hyperliquid alone, with Binance as the signal. It needs second-by-second recording (the collector).

### 15. The liquidator vault's inventory, the forced flow with a name (added 2026-11-02)

- **Mechanism.** When a Hyperliquid account cannot be closed on the book, its position lands in one of
  HLP's four liquidator vaults (about $32M between them), which hold nothing otherwise and work the
  position off over the next hour. Their inventory is therefore forced flow by construction, with a side,
  a size and an entry price, read every 15 minutes by the collector. Strategy A and B, the accounts #58
  and #59 can see, are ordinary market making; Strategy X, 64% of the vault, is hidden from the API
  (ERRATA 2026-11-02).
- **Evidence, one event.** 2026-11-01 04:30–04:45 UTC: XPL fell 18% (0.0862 → 0.0703) on $28M of
  volume against about $50k a quarter-hour before. At 04:45 Liquidator 3 held 135.6M XPL long at
  0.0759, $9.6M, $0.7M under water; it sold a quarter of it every 15 minutes and was flat by 06:00.
  While it was selling, XPL rose from 0.0714 to 0.0738; by 09:00 it was 0.0750, 6.7% above the low,
  and it closed the day at 0.0712. One event, so this is a description, not a result.
- **Why #58 and #59 cannot see it.** XPL is not in their coin list, and #58 voids any slot in which
  the set of accounts with rows changes, which is exactly what a liquidator appearing and going flat
  does. The tests' own text calls the liquidator "not separated"; this idea separates it.
- **The test it would need.** Pre-registered, forward: on any coin, when a liquidator vault shows a
  new position, take the same side as the vault at the next 15-minute read (it is still selling, so
  the entry is into forced flow) or, the sharper variant, when the vault's size drops below a quarter
  of its first read (the forced flow is nearly done). Exit at a fixed hold or when the vault is flat
  plus one read. Costs as in #58. Expect of the order of 100 events a year over all coins; most will
  be in thin coins the raw tape does not record, so the fill is the paper book's, not a replay. The
  collector's 15-minute cadence is the ceiling on timing; a faster read of the four liquidator
  addresses alone costs little and would be the first change.
- **Status.** Pre-registered as #64 ([FORWARD_LIQVAULT.md](FORWARD_LIQVAULT.md)) on 2026-11-02, window
  2026-11-04 to 2027-03-31. Nothing of #58, #59 or #60 changes.

### 16. The options dealers' hedging (added 2026-11-02)

- **Mechanism.** The market makers who sell BTC and ETH options on Deribit hedge their delta, and the
  size of that hedging per 1% move is their gamma. Short gamma, they sell falls and buy rises, so a
  move runs; long gamma, they do the reverse and the price pins. Near the Friday 08:00 UTC expiries the
  pin has a level. They are forced traders with a public book: every strike's open interest and mark
  implied volatility is served every minute, and the Black-76 gamma of each follows from them.
- **Evidence.** None here. On 2026-11-02 the BTC book held about $400M of hedging per 1% move across
  all strikes, unsigned. The sign is the whole question: the US-equity convention (dealers long calls,
  short puts) has nothing behind it on Deribit, where the sellers are funds as often as market makers.
- **The test it would need.** `espero deribit --loop` records the book from 2026-11-02. A
  pre-registration must fix the sign convention before any window, from a mechanism and not from the
  recorded returns; then: (a) with the net dealer gamma below the trailing 20th percentile, a 1-hour
  move continues over the next hour more than usual (and the reverse above the 80th); (b) in the last
  24 hours before an expiry, the price drifts toward the strike with the largest gamma. Both are
  conditional, horizon one hour to one day, judged on #58's cost and bar.
- **Status.** Idea. The recorder runs; no pre-registration written.

### 17. The Coinbase premium at seconds (added 2026-11-02)

- **Mechanism.** US spot buyers, ETF creations among them, buy on Coinbase; offshore leverage trades
  the perps. When Coinbase trades rich to Binance and the perps, US money is coming in, and over a
  session that money is what moves BTC. The gap is a price level, not a queue: it says who is buying,
  not who is first.
- **Evidence.** None here at this scale. Lead-lag at the minute scale died in #9, #16 and #17, and
  queue games are on the list below. The premium is older and slower than either, and the raw tape now
  holds Coinbase spot beside four perp venues with one receive clock, which nobody has used for this.
- **The test it would need.** From the tape: Coinbase's mid against Binance's and Hyperliquid's, each
  second. Pre-registered: a premium above its trailing 90th percentile for 5 minutes predicts BTC up over
  the next hour (and the mirror). It fails if the premium is only the perps' funding in another coat, so
  the funding-adjusted gap is the information row that would show it.
- **Status.** Idea. The data is recorded; no pre-registration written.

### 18. Open interest beside the tape: a cascade or a repricing (added 2026-11-02)

- **Mechanism.** #25 found that a fall made of closing positions behaves unlike one made of new sellers.
  The collector holds every perp's open interest every 5 minutes and the tape holds the fall as it
  happens: open interest falling with the price is a cascade, which overshoots and comes back (#26);
  open interest rising with a falling price is new sellers, which does not.
- **Evidence.** #25 and #26, on daily and hourly data. Nothing at 5 minutes.
- **What it is.** A live read, not a trade: it tells the screen which kind of fall is on it. The trade
  it would inform is #26's rule, already a pass. A pre-registration would test whether the open-interest
  split improves #26's rule out of sample, nothing else.
- **Status.** Explored on 2026-11-02 on the days before it ([EXPLORE_OI5M.md](EXPLORE_OI5M.md)): the
  same sign as #25 at 5 minutes, t at most 2.5 on 81 hours. Pre-registered as #65
  ([FORWARD_OI5M.md](FORWARD_OI5M.md)) the same day, window 2026-11-03 to 2027-03-31.

### 19. Which new listings squeeze: the filter #67 lacked (added 2026-11-02)

- **Mechanism.** #67 found the median new Binance USD-M perp falling 10 to 15% against BTC in its first week, in
  2023–24 and again in 2025–26, while a few positions carried both the price's tail (one listing rose 484% in a
  week) and most of the funding bill. The squeeze needs a crowd of shorts and a thin float; both leave traces at the entry: funding
  already negative, open interest large against volume, a small circulating supply.
- **Evidence.** #67 itself: the fade in the median, the tail in the mean, funding concentrated in a few
  positions. Nothing yet on whether the squeezes can be told apart in advance.
- **The test it would need.** A filter fixed before any look, from the mechanism: skip a listing whose funding
  over its first day is negative, or whose open interest over its first day is above a set multiple of its
  volume. Listings after 2026-09 only, since #67 read 2023–2026: forward, at 5 to 20 coin listings a month, 2026's pace
  or 2025's.
- **Status.** Idea. Not pre-registered.

## Around the trade: what a fitted model is for here (added 2026-11-03)

Twelve uses of machine learning that a desk runs beside its rules, none of them a price forecast, ranked on 2026-11-02
by how much of each the repo already holds. Two were taken the same day: the cost by order size became #68
([RESULTS_COSTCURVE.md](RESULTS_COSTCURVE.md), a measurement: a square-root curve holds on ten coins, drifts dearer on
four), and cascade risk became #72 ([RESULTS_CASCADE.md](RESULTS_CASCADE.md), FAIL: open interest, funding and the
long-short ratio add nothing to a volatility-only cascade forecast). The data check behind #72 found that the
continuous liquidation history on disk is COIN-M (2023-06 to 2024-10) while the open-interest history is USDⓈ-M
(2021-01 to 2026-03), so the two never join; anything below that wants liquidations beside positioning has that limit.
The ten that remain, with what the check found:

### 20. Fill probability and adverse selection for a resting order

- **Mechanism.** The carry-maker book posts limit orders and `espero.execution` fills them pessimistically against a
  recorded book. A model on the tape that gives the probability a rest fills within N seconds, and the markout when it
  does, turns maker-or-taker into a number per order. The most common model at any firm that makes markets.
- **Have.** `espero/execution.py`, #62's replay (`replaysim.py`), `data/hlbook` at 20 levels every 5 minutes (too coarse
  for fill timing), the raw `l2Book` and trades tape on Hyperliquid since 2026-11-02.
- **Needs.** Weeks of tape before a fit means anything; then a pre-registration scored on days the fit never saw.
- **Status.** Idea, data-bound.

### 21. Toxicity: is the flow arriving now informed?

- **Mechanism.** A maker pulls its quotes when the next prints are likely to run through them. `espero/markout.py`
  already keeps the aggressor sign, the flow window and the liquidation flags that such a model reads.
- **Have.** #39 and #41's markouts, prints with aggressor sign on five venues since 2026-11-02.
- **Needs.** The same weeks of tape as 20, and a post-fill markout model keyed on the flow state.
- **Status.** Idea, data-bound.

### 22. Venue lead-lag and routing

- **Mechanism.** Five venues on one clock. Which leads price discovery, by coin and hour, says where to execute and
  where to read a signal, and whether Hyperliquid follows, which matters for every rule priced on Binance and traded
  there (#51's "what this can't show").
- **Have.** The raw tape since 2026-11-02 and `espero.binance_archive`. Nothing in the repo measures it.
- **Needs.** A measurement module and weeks of tape. No model to fit: a lead-lag table is a readout.
- **Status.** Idea, data-bound. Idea 14 is its trading cousin.

### 23. The volatility risk premium

- **Mechanism.** Implied volatility minus the forecast of realized is the premium option sellers collect; #66's HAR is
  the realized side and `espero deribit` records every option's implied volatility every 5 minutes.
- **Have.** Realized back to 2020; implied only since 2026-11-02.
- **Needs.** Months of recording, or Deribit's history bought from a vendor, which needs the account holder's yes on a
  figure first. Then a pre-registration of the premium's sign and size, before any trade on it (idea 16 is the
  dealers' side of the same book).
- **Status.** Idea, data-bound.

### 24. Shrinkage covariance for the sleeves

- **Mechanism.** `espero/sleeves.py` shares a weight between rules whose correlation is above 0.5. A Ledoit-Wolf or
  factor-model covariance is the standard replacement and changes the weights.
- **Have.** Every input: the sleeves' daily returns.
- **Needs.** Only a numbered readout beside #63, because #63 is frozen to 2027-04-01 and cannot be replaced before it.
- **Status.** Idea, a day's work when wanted.

### 25. The effective number of trials

- **Mechanism.** `FDR_STANDARD.md` divides by the count of judged tests, but correlated tests are not independent
  bets. Clustering the tests' return streams gives the number of bets actually tried, which moves every q.
- **Have.** `robustness.deflated_sharpe` takes a trial count as its input; the forward tests' ledgers; `trials.csv`.
- **Needs.** Each judged test's daily return series saved in one place, which the failed backtests do not do
  uniformly, then the clustering. Plumbing before modelling. It makes the 2027-03-31 judgment more honest, so it is
  the one of the ten that pays whether or not any rule passes.
- **Status.** Idea.

### 26. Feature screening with a locked holdout

- **Mechanism.** Screen many candidate features on a training window, pre-register only the survivors, test them on
  data the screen never saw. How a desk generates ideas without spending a test number on each.
- **Have.** More than any other item: `espero/factor_eval.py` (rank IC, purged walk-forward, a correction for the
  number tried), `espero/ops.py` (the Alpha101 operator set), `features.db`.
- **Needs.** One standard document that names the holdout window and the rules under which it may be touched, and
  says what a leak would look like. Without it the machinery is a snooping engine.
- **Status.** Idea; the standard is a page.

### 27. Data quality on the tape

- **Mechanism.** Gaps, stale books, duplicated prints and venue clock drift, detected as they happen rather than found
  in a test's "two errors in how this ran". The tape is the one asset that cannot be refetched.
- **Have.** sha256 manifests in every recording folder; `espero/detector.py` checks synthetic markets, not recordings.
- **Needs.** A small audit step over each day's files with thresholds fixed in advance. No model needed at first.
- **Status.** Idea; a short job, and overdue.

### 28. Decay and change-point on the forward ledgers

- **Mechanism.** A CUSUM or SPRT on each forward test's returns says when a rule has stopped working before the fixed
  judgment date: a stop rule, never a tuning.
- **Status.** Being written as #70 (edge-watch) by the live-readiness work of 2026-11-02, not an idea for this list.

### 29. Alert triage and log anomaly

- **Mechanism.** `espero/notify.py` fires only on a failed step. The operator protocol (`docs/OPERATOR.md`) now says who
  answers; a triage model would show the one thing that changed rather than forty lines.
- **Needs.** Months of operator logs first. Last of the ten.
- **Status.** Idea, later.

### Not worth trying here

- **Order-book imbalance and queue games**: firms with servers next to the exchange win that race.
- **Indicator scalps**: every indicator vote failed here.
- **Copying whales**: survivorship, and the whales are often the ones being hunted (#3).
- **Cutting `espero rate`'s skill by market regime, on today's history**: untested, because both candidates closed at a fixed
  power bar ([REGIME_POWER.md](REGIME_POWER.md)). It needs more dates, in a new document that discloses this one.

## The lesson from today's run

#28 also found that crypto's own daily close (23:45 → 00:00 UTC) used to have a push in the day's
direction: +5.5 bps (t 5.3) in 2020–23, gone since 2024. Effects that are real decay once they are
known or crowded. That is why each idea above is tested on data that does not exist yet, or on data
nobody here has read, and why passed effects keep a forward ledger.
