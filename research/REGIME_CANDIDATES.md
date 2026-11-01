# Who pays, regime by regime — step 3 of [PLAN_REGIMES.md](PLAN_REGIMES.md)

**Written 2026-10-31. It is reasoning only: it reads no market data, computes nothing, registers no test and spends no trial.**
The evidence is what the repo's documents already state and the abstracts of three papers. The definitions in
[REGIME_DEFINITIONS.md](REGIME_DEFINITIONS.md) don't change here.

**Answer: two candidates go forward and two regimes stop, and both candidates may still close at a gate in step 4.**

| order | candidate | predicted | who pays |
|---|---|---|---|
| 1 | **Volatility, stocks and ETFs** | skill is higher in **high** than in low and mid pooled | Investors who must sell over days when liquidity suppliers have pulled back |
| 2 | **Funding, crypto** | skill is higher in **crowded long** than in neutral | The crowded, levered longs, when their positions unwind |

**Stopped:** trend, stress, and volatility for crypto. A candidate is one regime, one asset class and one predicted direction, and this
order is fixed. Neither prediction may be flipped after seeing a result. Crowded short is information only: the outside evidence is on
the long side, and the repo's short-side figure was selected in hindsight.

## What a mechanism has to explain here

Step 2 fixed the measure as the rating's Brier skill inside a state, against that state's own up rate. That sets three conditions:

- **It must explain skill, not return.** If a state simply goes up more often, its own up rate absorbs that. So "crowded longs get
  liquidated" doesn't count by itself. The mechanism has to say why price features tell up from down better in that state.
- **It must last 7 days.** Most of the repo's evidence of someone paying is at minutes to hours.
- **It must match the way the rating leans.** Who's on the other side depends on whether the rating follows last week's move or fades it.
  That hasn't been looked at, and the report doesn't print the model's weights.

## The gate

**Both candidates need the rating to lean against last week's move.** Step 4 checks this before any skill is computed:

> In each of the 6 folds of the 7-day model, for the candidate's class, take the correlation between the test rows' predicted P(up) and
> the `r7` feature. **Fewer than 5 of 6 folds negative: the candidate closes untested.** Fitting uses training outcomes as always.
> Only these 6 correlations are printed, across all states, with no test-row outcome, skill or regime label.

If the rating follows the move instead, both close and the plan ends with no regime test, which is a valid result. Choosing
trend now as a spare for that case would be picking a story because it fits.

## Volatility

**Stocks and ETFs: keep.**

- **Who pays:** investors who need to sell quickly, paying liquidity suppliers who have become scarce. Rule-bound sellers plausibly add to this over
  days, such as funds that cut exposure when volatility rises. This repo's own sizing rule is built that way ([RESULTS_TREND.md:30-31](RESULTS_TREND.md)).
- **Why skill, not just return:** more of last week's move is then a price concession rather than news, so fading it should tell up from down better.
- **Outside evidence:** [Nagel 2012](https://nber.org/papers/w17653) finds reversal returns track the VIX, and holds that even for industry portfolios, which earn little otherwise.
- **The distance from that paper:** its state is the VIX, not a 60-close tercile of SPY. It studies a reversal strategy's returns, not the skill of a pooled
  directional read. Eight of the 13 ETFs in this pool are bonds or commodities. I read the abstract and introduction level only, and the definitions stay as committed.
- **Repo evidence:** none on stocks at this horizon. #28's post-close reversal is real at minutes on leveraged ETFs ([RESULTS_LEVETF.md:50](RESULTS_LEVETF.md)), which isn't this.
- **Frozen overlap:** none named in the inventory.

**Crypto: stop.**

- **Who pays:** liquidated traders, and the repo has shown that well, but mostly at shorter horizons. In the uncorrected row, which entered 5 minutes late, #43's forced breaks fall
  from t 5.6 at 1 day to 2.0 at 1 week, where +197 bps sits beside +155 for the plain trend control ([RESULTS_HORIZONS.md:39-40](RESULTS_HORIZONS.md)). The corrected
  figure stops at 1 day, +60.4 bps at t 3.63 ([RESULTS_DAYMEAN_AUDIT.md:104-107](RESULTS_DAYMEAN_AUDIT.md)), so no corrected week figure exists.
- **Evidence against:** crowded sell-offs didn't bounce, with −13.8 bps at 3 or more other triggers, and #21's busy days didn't revert either.
- **Frozen overlap:** #22, #24, #27 and #45, which is why a pass wouldn't be new evidence.

## Funding

**Crypto: keep, as the weakest case.**

- **Who pays:** the crowded side, who pay cash to stay levered and are forced out when the price turns. [Schmeling, Schrimpf and Todorov](https://www.bis.org/publ/work1087.pdf) tie high carry to
  smaller, trend-chasing investors, limited arbitrage capital and later crashes.
- **Why skill, not just return:** a crowded position usually follows a move: "High funding follows rallies" ([FORWARD_FUNDSPLIT.md:67](FORWARD_FUNDSPLIT.md)). Fading that move should work better
  when an unwind is waiting than when no one is crowded.
- **The rival story, which I think is as likely:** the unwind finishes within hours, so by 7 days the state adds only noise and skill doesn't change. That would count as a failure.
- **The main weakness:** the paper's crash result is the state predicting direction, which the measure absorbs, so it supports this only indirectly. Its evidence is
  on the long side. On the short side, #43 shows the price rising after shorts pay hard, −606 bps for the short at 1 week ([RESULTS_HORIZONS.md:37](RESULTS_HORIZONS.md)), selected in hindsight and in a rising market.
- **Other distances:** the paper studies the futures basis, and this state is BTC's funding on one venue, applied to every coin.
- **Frozen overlap:** #32 and #38 use funding too, so a pass wouldn't be independent of them. This is the only regime not already among the rating's inputs, which is why it stays.

## Trend

**Crypto and stocks: stop.**

- **Who pays:** no one identifiable. [Cooper, Gutierrez and Hameed 2004](https://doi.org/10.1111/j.1540-6261.2004.00665.x) find momentum profits after up markets and read them as overreaction. That is a behaviour, with no
  party forced to trade at a given time, and the plan set a higher bar for regimes overlapping the rating's inputs.
- **The distance:** their state is a 3-year market return and their strategy is winners minus losers over months. That's far from a 200-close average and a 7-day read.
- **Repo evidence against:** #15's timing added no return (t −0.18), and #43's trend control showed nothing per coin (t 1.3 at 1 week).
- **The measure:** whatever a rising market adds goes into the state's own up rate.

## Stress

**Crypto and stocks: stop.** This is on mechanism, not on how few episodes there are.

- **Who pays:** forced sellers, the same parties as above. In crypto they're the same as the stopped volatility case, with the same evidence against and the same four frozen overlaps.
- **In stocks:** they're the same parties as candidate 1, so a stress test would re-test one mechanism on a subset of its dates. It would look like a second piece of evidence, and it wouldn't be.

## What I knew when choosing

- **Everything in the inventory,** including every #43, #21 and #33 result cited here.
- **`espero rate` reports:** I've seen "past days like this" chance-up figures for BTC, SPY, ETH and one stock, for the symbol's own SMA, trend and RSI. These aren't market states or skill, but they sit close to the trend regime. Those reports also showed a few P(up) values beside their feature readings, which is weak but direct information on what the gate tests. I didn't work out the sign from them.
- **The rating's pooled skill,** below zero in all six cells apart from stocks at 1 day, within noise. Three of six were worse than the usual rate.
- **A wrong forecast of my own:** before this read I expected volatility to drop. It survived for stocks because Nagel names a payer, and I looked that paper up after making the forecast. I ran one targeted search each for volatility, funding and trend, and none for stress.

## Not verified

- The three papers were read at abstract or summary level, so I cite no regression numbers. Nagel's exact horizon isn't confirmed here.
- "No one identifiable" for trend means I didn't find one in these sources. A better-read reviewer may name one.
- The gate's threshold of 5 of 6 is a judgement, set now.
