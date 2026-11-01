# Regime research — a follow-on to `espero rate` (plan)

**Status, 2026-10-31: step 1 is done ([REGIME_INVENTORY.md](REGIME_INVENTORY.md)); steps 2 to 6 have not started, and no return has been computed.** Agreed in a side session and forwarded from it. It registers no
test, takes no number and spends no trial. Each test it leads to gets its own `PREREGISTRATION_*.md`, numbered from #51.

**Goal:** find regimes where the rating's signals worked better, then confirm them on new data or close them. "Proven" means
only surviving the checks below, and no edge is promised. Most candidates will probably fail, and a published "no edge found"
is a valid result.

## Steps, in order

1. **Inventory.** Sort the finished tests' results by regime. No new tests. Forward tests stay frozen and unread.
2. **Fix the regimes before looking at returns.** At most four, each known at the time, with no hidden Markov models at first:
   - **Trend:** above or below the 200-day average.
   - **Volatility:** low, mid or high, with cut-offs from past data only.
   - **Crypto funding:** crowded long, neutral or crowded short.
   - **Market stress:** a large fall from the high.
3. **Name who pays.** Each candidate says who pays and why. No mechanism, no test. About three candidates at most.
4. **Power first.** Drop a candidate untested if the history can't detect an effect that matters after costs. The 7-day
   horizon gives about 52 independent samples a year per market.
5. **Test survivors once.** Registration committed before computing, purged walk-forward, one sealed holdout read, costs and
   funding included. It must pass in both halves and not depend on one coin. Every test goes in `trials.csv`, with deflated
   Sharpe and SPA reported.
6. **A pass earns only a paper forward test,** on days after its registration, with a set end date.

## Link to the rating

- **Labels:** each regime result shows as `UNPROVEN`, `HISTORICAL PASS` or `FORWARD CONFIRMED`. Not built yet: `espero rate`
  only has the model-level `UNPROVEN` line today.
- **Scorecard:** every rating is logged, so the scorecard can check whether high ratings went up more often than low ones.

## Limits

- Daily prices and funding can be tested now. Order-book history starts 2026-10-31, and liquidation history is patchy.
- **52 samples a year is per market.** Coins move together, so adding coins adds much less than it appears to.

## Points added when this plan was recorded

- **No daily history is fully unseen.** `espero rate`'s skill test has already read crypto and stock history through
  2026-10-29, pooled and not cut by regime, and most of this repo's tests have read crypto bars. A "sealed" window here hides
  the regime results, not the data. Each registration must say what was seen, and step 6 is the only truly clean evidence.
- **Three of the four regimes overlap the rating's features.** Trend, volatility and drawdown are already in the model that
  failed its skill test, so these tests ask a narrower question about the same inputs. Only funding is new. That raises the
  bar for naming a mechanism in step 3.
- **The rating may rarely reach 8 or 3.** The first 8 logged ratings are all 6s and 7s. If that holds, an "8s against 3s"
  comparison will have almost no data, so the scorecard may need to compare above-usual with below-usual ratings. That would
  be fixed in a registration before any scorecard result is read.
- **The frozen window stays closed.** Registrations can't use outcomes from 2026-10-30 until 2027-03-31.
