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
