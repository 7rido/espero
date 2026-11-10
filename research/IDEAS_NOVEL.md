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
- **Screen, written 2026-11-10 before it is run.** The note above missed that Deribit publishes its 30-day implied
  volatility index (DVOL) with history, free and without a key. For BTC and for ETH: the index's daily close against
  the volatility then realized over the next 30 days (daily closes of Deribit's perpetual, annualized on 365 days),
  on 30-day windows that do not overlap, from the index's first day. **Alive** if implied minus realized averages
  above zero with t ≥ 3 and is positive in at least two windows of three. It cannot show what selling the options
  and hedging them would have cost, or the loss in the worst window, which is the whole risk of this trade.

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

## Quick screens on trade.xyz, written down before they are run (added 2026-11-10)

The account holder asked on 2026-11-10 for candidates that show a profit, found faster than one full test at a time.
A screen is not a test: it reads history that #80 already used, so whatever it shows is **post-hoc**, spends no
trial, and proves nothing. Its job is to decide which idea earns a number and a forward paper book, the only unseen
data these markets have. So the list is fixed here first, every screen is reported whether it lives or dies (the
count screened beside the count alive), and costs are #80's: 14 bps per unit of capital traded, the growth-mode fee
as information.

**Seen before this was written:** #80's result, and each market's mean funding by month for SKHX, SMSN, MU, SNDK, CL,
BRENTOIL, SP500, XYZ100, GOLD, SILVER, NVDA, MSTR and CRCL (funding fell after July 2026: most markets pay 5% to 14% a
year since August; SKHX 13% to 18%, SMSN −12% to +8%, CL −51% to −11%, BRENTOIL −56% to −27%). No pair's price return
has been computed.

### 30. Funding between two markets that move together

- **Mechanism.** #80 earned its funding in 46 of 47 weeks and lost on price, because its two legs were different
  stocks. If both legs are nearly the same thing, the price legs cancel and the funding difference is what is left.
- **Pairs, fixed now (6):** SKHX/SMSN, CL/BRENTOIL, GOLD/SILVER, SP500/XYZ100, MU/SNDK, MU/SKHX.
- **Screen.** #80's rule on one pair: each Monday 00:00 UTC, short the leg whose funding was higher over the last
  week and long the other, half the capital each, hold a week; price from the daily candles, funding as settled, 14
  bps on every unit of weight changed. Read on the weeks from 2026-08-03 (the funding regime that exists now), the
  whole history as information.
- **Alive** if the mean net week is above zero in both readings and the later one is worth at least 5% a year.
- **Known ceiling.** The funding gap itself, halved by the leg weights: from the monthly table, a few percent a year
  at most since August for every pair but SKHX/SMSN and the oil pair. Oil needs a second look even if it lives: both
  contracts pay their longs, which may be the futures curve showing up as funding, returned through price.

### 31. The same thing listed twice

- **Mechanism.** If one underlying has a perp on trade.xyz and another on a second builder exchange, or on
  Hyperliquid's own book (a gold token against xyz:GOLD), the price legs cancel almost exactly and any funding
  difference is the whole trade.
- **Screen.** List every builder exchange's markets, keep an underlying listed twice where the thinner leg trades at
  least $1M on a median day, then #30's rule and reading.
- **Alive** as #30.

### 32. The weekend move in the stock perps comes back when outside prices return

- **Mechanism.** From Friday 20:00 to Sunday 20:00 Eastern these perps trade on trade.xyz's own pricing, at about 13%
  of weekday volume (#73). A thin crowd moves the price with nothing to anchor it; when outside quotes return on
  Sunday evening the price is pulled back to them. Forced convergence, on a clock.
- **Screen.** The stock, ETF and index markets among #80's 28. W = the perp's move from Friday 20:00 to Sunday 19:00
  Eastern (hourly candle opens). Where |W| is at least 1%, take the other side at Sunday 19:00 and leave at Sunday
  21:00 Eastern. 28 bps a round trip.
- **Alive** if there are at least 30 trades and the mean net trade is above zero in each half of them.
- **What it cannot show.** What a real order costs on a Sunday evening; #74's tape will.

### 33. The liquidation bounce with a label known at the break

- **Mechanism.** #26, the repo's one full pass: a 5-minute down-break made mostly of liquidations bounces. Held 4
  hours it netted +21.9 bps a trade after costs and funding on the priced coins (t 4.38, RESULTS_DAYMEAN_AUDIT.md,
  information). It cannot be traded: a break is "forced" by the rank of its forced share among **that whole day's**
  breaks, and by a count of the day's breaks, neither known when the break happens (LIVE_LATENCY.md, fact 1).
- **Screen.** The same events file (`research/liq2_events.csv.gz`, 2023-06-26 to 2024-10-14, 26 coins). A down-break
  is forced if its forced share `s` is above the 2/3 quantile of `s` over every break, any coin and direction, in the
  30 days before its UTC day (at least 100 breaks, else no label); no filter on the day's own count. So the threshold
  is one number fixed at 00:00 UTC. Bought at the break bar's close, held 4 hours (`y240`), 18 bps a round trip
  (`liqhold.ASSUMED_RT`), every event counted, trade-weighted with day-clustered Newey-West errors (`espero.audit`).
  Beside it: the 1-hour hold, the within-day label on the same days, and the net with measured costs and settled
  funding on the coins #43 priced.
- **Alive** if the 4-hour net mean is above zero with t ≥ 3 and positive in 2023 and in 2024.
- **Seen before:** all of #26, #44 and the audit's table on this file, under the within-day label. A label change
  on read history is post-hoc; a survivor is a new number whose only fair test is forward, on #27's kind of
  recording, and it needs a liquidation feed that arrives within minutes (Binance's is silent from this Mac).

### 34. #12's carry on the stock perps: short the perp only while it pays, hold the share against it

- **Mechanism.** #80 showed the funding on these perps is real and reliably paid; it lost because nothing held the
  price still. The share itself does. #12 (provisional) is this trade on crypto: enter when funding is rich, leave
  when it is not.
- **Screen.** Each of #80's markets with a listed equivalent that #73 let stand in. #12's thresholds unchanged: in
  from the hour the trailing 168-hour funding is above 15% a year, out when it is under 5%. Income is the funding
  settled while in; the price legs are taken to cancel, with 34 bps charged per round trip (14 bps the perp as in
  #80, 10 bps assumed for the share, 10 bps for the gap between the two prices at entry and exit, #73's size).
  Return is on capital of 1.5 times the position (the share paid in full, half again as the perp's margin). Read
  since 2026-08-03, the whole history as information.
- **Alive** if the book of all such markets, an equal slot each, nets above zero in both readings.
- **What it cannot show.** The share leg's real cost, financing and tax at the holder's broker, and what happens to
  the perp's margin on a weekend when the share cannot be sold. A US-share broker open to the holder is theirs to
  find; nothing here places an order.

### 35. Carry on the majors, both legs on Hyperliquid, over the long history

- **Mechanism.** #12's: a long perp pays rent to a short one. #12 was read on 4,996 hours of 2026 with Coinbase as
  the spot leg, which the holder cannot use at a sane cost (VENUE_NONUS.md). Hyperliquid has its own spot market for
  the majors, so both legs can sit on one venue; and `research/data/carry/` holds the hourly funding back to May 2023,
  which no test has read as a whole.
- **Seen before this was written:** each coin's mean funding over that file (BTC 14.1% a year, ETH 14.2%, SOL 12.2%).
- **Screen.** BTC, ETH and SOL, each alone: (a) always short the perp against spot; (b) #12's thresholds, in above 15%
  a year on the trailing 168 hours, out under 5%. Income is the funding settled while in, the price legs taken to
  cancel, 25 bps assumed per round trip (to be measured on Hyperliquid's spot book), capital 1.5 times the position.
  By calendar year, with the worst 30 days.
- **Alive** if (a) nets above zero in every calendar year for BTC and for ETH.
- **What it cannot show.** The spot leg's real cost and depth; the gap between Hyperliquid's spot token and the perp;
  that Hyperliquid's spot BTC only began in 2025, so earlier years assume a spot leg that was not there.

### Not screened again, and why

- **Funding as momentum** (#80 reversed): already read post-hoc, +0.46% a week at t 1.07, all of it in the first
  half. Nothing a screen can add; only a forward book could.
- **The night effect at growth-mode fees:** #76 and #77 already carry the line (−4.7 bps a night; +13.9 bps a week at
  t 0.49). The real cost is #74's to measure, about 2026-11-25.

### What the screens showed (run 2026-11-10; every figure post-hoc, none is a verdict)

The first three screens (30 to 32) were written before any was run. Screens 33, 34, 35 and the one under idea 23
were added during the same session, each written before its own run. Seven screens; the count is at the end.

| screen | what it read | alive by its own bar? |
|---|---|---|
| 30. funding between near twins | 6 pairs. Since August: SP500/XYZ100 +7.6% a year, all of it price noise (t 0.67; the funding gap itself is 1% to 2% a year); the other five between 0 and −60% a year. The pairs' own weekly price noise (2% to 4%) buries a funding gap of 0.1% a week. | 1 of 6 by the letter, none in substance |
| 31. the same thing listed twice | 6 underlyings with a second listing above $1M a day, all 2 to 14 weeks old. After costs: NBIS +5.9% a year on a $3M-a-day leg with the gap shrinking; UNITREE's two prices drifted 7.5% apart (no shared outside price, so not a hedge); NVDA, DRAM, SNDK negative. | no: too young, too thin |
| 33. the liquidation bounce with a label known at the break | Held 4 hours: +14.5 bps net (t 1.42, 6,711 trades), 2023 +21.7, 2024 +10.4. The within-day label on the same days: +24.8 (t 3.74). On #18's separate 82 days, same rule: +20.9 (t 1.21). | no (t under 3); positive in both samples |
| 34. stock-perp carry against the share | 20 markets. +2.4% a year on capital over the whole history, +0.3% a year since August. | yes by the letter; pays nothing now |
| 35. carry on the majors, one venue | Always short the perp against spot: BTC 9.3% a year on capital, ETH 9.4%, every calendar year positive (2023 10.0 / 14.9, 2024 16.1 / 14.7, 2025 7.1 / 5.7, 2026 3.6 / 4.0); worst 30 days −0.6%. SOL 8.1%, 0.4% in 2026. | yes, and shrinking |
| 31b. gold listed twice (PAXG on Hyperliquid's own book against xyz:GOLD) | 323 days; the funding gap flipped sign 33 times, so short-the-richer paid +1.7% a year before costs and −9.1% after. | no |
| 32. the weekend move comes back | 24 markets, 30 weekends, 282 fades of a 1%+ weekend move: +7.3 bps net (t 0.51), first half −4.2, second +18.7; the reopen undoes only 14% of the weekend move. A partial run on 3 markets was seen by accident before the full one. | no (a half is negative) |
| 23. the volatility premium | BTC: implied above realized by 10.7 points on average over 68 windows since 2021 (t 5.00), positive in 52, every year positive but falling (26, 15, 7, 10, 5, 3); worst window −30. ETH: +7.5 (t 2.70), 46 of 68, 2025 negative. **Since 2025 alone:** BTC +4.1 points (t 1.44, 15 of 22 windows), ETH −0.2 (t −0.05). | BTC yes on the whole history, not on 2025–26 alone; ETH no |

**A lead that did not hold.** Inside screen 33, the trades were split by how many other forced down-breaks, any
coin, came in the hour before (buckets fixed before reading). With six or more, a cascade, the 1-hour hold made +69
bps net (t 3.04, 699 trades on 116 days, all six quarters, 24 of 25 coins; +57 at 30 bps of cost), and half of it
arrived in the first 15 minutes. The same split on #18's separate days gave +7.9 bps (t 0.60) with no pattern across
the buckets. That second file is a weaker check than it sounds (42 coins against 26 under the same count of six, one
day a month, a threshold up to three months old), so the lead is **not confirmed** rather than refuted. It is not a
candidate, and it is written here so that nobody finds it again and believes it.

**Findings that outlast the screens.**

1. **Funding on the stock perps fell about fivefold after July 2026.** Most markets pay 5% to 14% a year since August.
   Every funding idea on trade.xyz is small until that changes; a line on the Market tab that says when a hedgeable
   market's weekly funding is back above 15% a year would cost little.
2. **A long perp on Hyperliquid pays rent, and nothing about #8 charges it.** #8 was tested as spot (10 bps a side,
   Binance.US). Its Hyperliquid versions are perps: the `mf-hl` paper book, the testnet canary and the mainnet design.
   The word funding is in none of PREREGISTRATION_MF.md, `research/multifactor.py`, FORWARD_MF.md,
   `espero/mf_canary.py`, MAINNET_LIFT.md or DESIGN_MAINNET_PATH.md (RISK_POLICY.md caps funding as a squeeze alarm, at
   73% a year). Since May 2023 longs paid 14.1% a year on BTC, 14.2% on ETH and 12.2% on SOL; in 2026 about 5% to 6%.
   The book is long-only and vol-targeted, with gross exposure "well under 50%" in its results and 0.26 on average in
   the forward book so far. So the drag is about 2 points a year at this year's funding and about 5 at the long-run
   rate, against a holdout return of 16.9%: real, not fatal, and so far uncounted. The plumbing canary is unaffected
   (it tests orders, not returns); a sizing document for #8 on perps should charge it, or hold the longs in spot.
3. **The rents have all shrunk in 2025 and 2026:** the BTC volatility premium from 26 points to 3, carry on the majors
   from 16% to 4%, Deribit's dated-future basis 5.5% a year today (read 2026-11-10). What still pays, pays modestly.
4. **The within-day label flatters the liquidation bounce.** A label that could be known live keeps about 60% of the
   mean and a third of the t. #45's forward test uses the within-day label, so a pass there would still not be a rule
   that can be traded as written.

**Candidates worth a number and a forward paper book, in my order.**

1. **The BTC volatility premium, sold with a capped loss.** The strongest evidence found today over the whole five
   and a half years (t 5.00), on data no test here had read; on 2025–26 alone it is 4 points at t 1.44, which proves
   nothing by itself. Needs: a back-test on real option prices (Deribit serves the trades of expired options
   free), a structure whose worst case is fixed when it is opened, a paper book marked from `espero deribit`'s
   recording, a page in the risk policy for options, and the holder's venue check. Good odds that the premium is
   there; it is small now, and one bad month can take a year of it.
   **Registered the same day as #81** ([PREREGISTRATION_VOLPREM.md](PREREGISTRATION_VOLPREM.md), 8d60f75): every Friday
   since 2020, on the real trades of expired options, in units of the capped loss. The holder said on 2026-11-10 that
   a steady 5% to 10% a year with small drawdowns counts as working, which is why this and the next one lead.
2. **Carry with both legs on Hyperliquid, by #12's rule.** #12's own forward verdict falls on 2026-11-27. Needs first
   a measurement: what Hyperliquid's spot book charges for the long leg, and how far the spot token strays from the
   perp. Good odds that it is positive; 4% to 10% a year on capital at this year's funding, which has to be weighed against
   what idle dollars earn elsewhere, the holder's figure.
3. **The liquidation bounce with a live label, held 4 hours.** A forward twin of #45 fed by the liquidations the raw
   tape already records as they happen (Bybit, OKX). Fair odds: positive twice, strong neither time. For whoever writes it: the live label adds 953 trades the
   within-day label left out, at −50 bps each, most on crash days (2024-04-13: 30 trades at −787). The within-day rank
   was also a cap on trades a day; the twin needs a cap of its own, chosen before it runs. None was screened here.
4. **#8 with its longs in spot and the funding charged.** Not a new edge: it protects the one rule already on the
   way to a canary.

Seven screens, all run: four alive by the letter (30, 34, 35, 23), two of those worth anything (35 and 23).

## The lesson from today's run

#28 also found that crypto's own daily close (23:45 → 00:00 UTC) used to have a push in the day's
direction: +5.5 bps (t 5.3) in 2020–23, gone since 2024. Effects that are real decay once they are
known or crowded. That is why each idea above is tested on data that does not exist yet, or on data
nobody here has read, and why passed effects keep a forward ledger.
