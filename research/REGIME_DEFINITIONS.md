# The four regimes, fixed before any return is read — step 2 of [PLAN_REGIMES.md](PLAN_REGIMES.md)

**Written 2026-10-31. It computes nothing, registers no test and spends no trial.** No regime label, state count or return
has been computed. The only data read was the first and last timestamp of the funding file named below, with no rates. These
definitions don't change once committed: a different cut-off is a new document with its reasons.

**Each regime gives one state per date for a whole asset class, read from one market series.** Crypto reads BTC-USD and stocks
and ETFs read SPY.

## The states

| regime | applies to | states | rule at day `t` |
|---|---|---|---|
| **Trend** | crypto, stocks | up, down | **up** if the close is above the mean of the last 200 closes, including `t`; otherwise **down** |
| **Volatility** | crypto, stocks | low, mid, high | `v` = 60-close standard deviation of log returns, annualised. **low** if `v` is at or under the 1/3 quantile of all earlier `v`, **high** if above the 2/3 quantile, otherwise **mid** |
| **Funding** | crypto only | crowded short, neutral, crowded long | `f` = mean of the last 21 Binance BTCUSDT settlements, per 8 hours. **crowded short** if `f` < 0, **crowded long** if `f` > 0.0001, otherwise **neutral** |
| **Stress** | crypto, stocks | stress, normal | drawdown = close ÷ highest close of the last 364 calendar days − 1. **stress** at −50% or lower for BTC-USD, at −20% or lower for SPY; otherwise **normal** |

That's 10 states for crypto and 7 for stocks. There are no combined states such as "down and high volatility": those would
multiply the comparisons on the same few market episodes.

## Exact details

- **Prices:** the series the rating uses, from `rate.load_frames`: Hyperliquid daily closes for BTC-USD, and Yahoo closes adjusted for
  dividends for SPY.
- **Known at the time:** a state at `t` uses nothing after `t`'s close, on the same dates as `rate.rows`.
- **Annualising `v`:** √365 for BTC-USD and √252 for SPY, as in `rate.features`.
- **Volatility cut-offs:** expanding quantiles of `v` through `t − 1`, with pandas' default interpolation, and no label until
  365 earlier values exist for BTC-USD or 252 for SPY. Never quantiles of the full sample, which would know the future.
- **Stress:** the same calculation as the rating's `drawdown` feature, with weekends carried for SPY.
- **Funding settlements:** those at 00:00, 08:00 or 16:00 UTC on `t` or earlier, so the latest counted is 16:00 on `t`. With fewer than
  18 of the 21 present there is no label: a gap stays a gap.
- **Funding source:** #19's existing file `data/settle/funding/BTCUSDT.json`, read-only, which runs 2019-12-31 00:00 to
  2026-10-29 08:00 UTC. **Nothing needs downloading.** `data/funding/` belongs to a running forward test and is not used.
- **The frozen window:** until 2027-03-31, a label dated 2026-10-30 or later doesn't exist for these tests, and every series is cut before computing.

## Why these choices

- **A market series, not the symbol's own.** The symbol's own trend, volatility and drawdown are already `sma200`, `vol` and
  `drawdown` in the rating, so cutting by them hands the model its own inputs back. The market's state is a different question.
- **BTC-USD, not a median of coins.** #2 once suggested a universe median ([RESULTS.md:61](RESULTS.md)). This pool holds survivors only,
  so a median would inherit that bias.
- **BTC's funding, not each coin's.** It matches the other three regimes and overlaps less with #32, which cuts each coin's own
  funding. Each coin's own funding would be a separate candidate with its own number.
- **Funding lines from the exchange's mechanics.** Below zero, shorts pay on balance. Above 0.0001, Binance's default rate and
  #32's line, longs pay a premium. Rejected: 0.0005, because #19 and #33 use it on one settlement, not a weekly mean; a z-score, because #1's fired ~3 or ~17 times a
  year depending on venue ([FINDINGS.md:66](FINDINGS.md)); and percentiles, which could call positive funding "crowded short".
- **Expanding volatility quantiles.** The plan requires cut-offs from past data, and an expanding window adds no further number to tune.
- **Stress at −20% and −50%.** −20% is the usual bear-market convention for a stock index. −50% is a judgement from memory, not
  computed here: BTC's volatility is about three times SPY's, which scales −20% to about −60%, and I took −50% because I expect
  −60% to leave very few episodes. So this line was chosen knowing BTC's past falls.

## What a test will measure

Steps 3 to 5 decide which regimes get tested. Each test measures the same thing, so it can't be picked after seeing results:

- **The existing rating's out-of-sample Brier skill inside each state, at 7 days.** No new signal, features or bands.
- **Against the up rate that state had in the training window,** not the overall rate. Otherwise a rising market looks like skill:
  #21's long leg was "mostly the market" ([RESULTS_LIQSPIKE.md:41](RESULTS_LIQSPIKE.md)). Skill against the overall rate is information only.
- **Pooled across the class's symbols,** on the rating's six purged folds and its date-block bootstrap ([RATING.md](RATING.md)), keeping only dates in the state.
- **7 days only.** The 1 and 30-day horizons are not computed, not even as information, because that would triple the looks.
- **A thin fold gives no result.** If a fold's training window has fewer than 52 dates in a state, that fold reports nothing for that
  state and isn't pooled. It never falls back to the overall rate, which would flatter the rating. 52 is an arbitrary floor, set now.
- **A date with no label is left out** of that regime's states, never given a default state.

Each registration still has to add who pays, its pass criteria and, per the plan, a tradable rule with costs and funding.

## What I knew when choosing

Both earlier documents promised this list. I chose these after reading the 416 inventory rows and my first rating results:

| choice | what I had already seen |
|---|---|
| Trend, 200 closes | The plan named it beforehand. #15's timing added no return (t −0.18), and the rating's pooled skill is below zero. |
| Volatility terciles | The plan named them. #15 and #8 credit volatility sizing with the risk reduction. |
| Funding lines | #32's 0.0001 line, and how #1, #19, #33 and #11 turned out. This same file fed #19 and #33's funding cuts. |
| Stress lines | #43's crowded-sell-off bucket was −13.8 bps, using a different definition. My general knowledge of how far BTC and SPY have fallen. |

**So nothing here is blind to the history, only to these cuts.** The rating has read these prices pooled, and #19 and #33 have read this funding.

## Limits for step 4

- **SPY stands in for bonds and commodities too.** The stock pool includes TLT, IEF, GLD, SLV, USO, UNG, DBA and CPER, and SPY's state may mean
  little for them. Results for these split out are information only.
- **BTC's funding may miss crowding in other coins.**
- **Volatility has probably trended.** If BTC's volatility fell over the years, expanding cut-offs put later years mostly in "low". The state would
  then partly stand in for the period, which step 5's two-halves test exists to catch.
- **Crowded long may be rare.** #32's document warned its group could be small in calm months ([FORWARD_FUNDSPLIT.md:89](FORWARD_FUNDSPLIT.md)).
- **Stress is few episodes.** Long falls count as one long state, so its independent samples may be far fewer than its dates.
- **The regimes overlap each other.** Stress will mostly sit inside trend-down, and high volatility may too, so they aren't four separate pieces of evidence.
- **History is short.** BTC-USD's closes start in August 2020, so with burn-in its labels start in 2021. The rating's walk-forward also holds out only later dates.

Step 4 counts dates and independent samples in each state and drops what the history can't detect. Its counts can't change a cut-off.
