# Forward test — HLP's absorbed inventory, with reads recorded (#59)

Committed **before any day of the forward window exists**: the window opens 2026-11-05, and this was
written on 2026-11-01. A paper test: nothing trades. The fifty-ninth test in this repo.

## Why

#58 tests whether a jump in HLP's net position during a sharp fall is followed by a bounce. Its guard
voids any pair of slots where an account's rows appear or disappear, because the collector didn't record
failed reads. That also voids a sub-account truly opening or closing its only positions, which may be the
absorption the test is looking for. #58's note, written while building its book, records this.

#58 stays frozen and runs as committed. **This test changes one thing:** the collector now records
which accounts failed, so the guard voids failed reads only. Everything else is #58's, restated here so
this document stands alone.

**The prediction.** After HLP's net position in a coin jumps up while that coin's price falls sharply, the
price rises over the next hours, by more than the cost of trading it.

## Data — fixed

- **Coins.** #45's 14: BTC, ETH, SOL, XRP, DOGE, LINK, ADA, AVAX, BNB, TRX, LTC, XLM, HBAR, and SHIB as
  Hyperliquid's `kSHIB`.
- **Window.** Signals from 2026-11-05 00:00 UTC through 2027-03-31 23:59 UTC, 147 days. Earlier slots serve
  only as trailing history.
- **HLP's position.** `data/hlcollect/hlp/`, one file per 15-minute slot. A coin's **net size** in a slot is
  `szi` summed over every address in that file. A coin with no row has net size 0.
- **Read records.** `data/hlcollect/hlp_reads/`, one JSON file per slot, new with this test, listing the accounts
  asked and those that failed. It's written before the slot's positions file and holds no market value.
- **Prices.** `data/hlcollect/candles/`, Hyperliquid's own 1-minute candles. Candles missing from a file may
  be taken from Hyperliquid's public candle API while it still serves them, and the count is reported.
  No other venue's prices are used.
- **Funding.** Hyperliquid's settled hourly rates, from its public funding history.
- **Gaps.** A gap stays a gap. A slot missing from disk is never rebuilt, and no pair is formed across it.

## The rule — fixed

For each coin and each pair of adjacent 15-minute slots, with `t` the later slot's `ts`:

1. **Price.** `C(s)` is the close of the last 1-minute candle that ended at or before `s`.
   `ret = C(t) / C(t−1) − 1`.
2. **Jump.** `jump = (net size at t − net size at t−1) × C(t)`, in dollars.
3. **Trailing history.** The coin's valid pairs among the 672 slots before this one, about 7 days, not
   including this pair. At least 336 are required, or the pair gives no signal.
4. **Signal.** All four must hold:
   - `jump > 0`;
   - `jump` is above the 99th percentile of the trailing jumps;
   - `ret < 0`;
   - `ret` is at or below the 10th percentile of the trailing returns.
5. **Guard against a failed read — the one change from #58.** A pair is invalid, on all coins, if either
   slot's record lists a failed account, or if either slot from the first record onward has no record. An
   invalid pair gives no signal and doesn't enter the trailing history. An account's rows appearing or
   disappearing with no failed read is a real change and stays valid. Slots before the first record exist have
   no way to show a failure, so they count as history only, unguarded. They leave the 7-day history
   by about 2026-11-09. They can't produce a signal, since all of them are before the window.
6. **Entry.** Long, at the open of the first 1-minute candle starting at least 60 s after `t`. If that
   candle isn't within 5 minutes of `t`, the trade is dropped and counted.
7. **Exit.** At the open of the first 1-minute candle starting at least 4 hours after entry. If that candle
   isn't within 5 minutes of the 4-hour mark, the trade is dropped and counted. A trade whose exit falls
   after the window is dropped.
8. **One at a time.** A coin holds one trade. A signal during a hold is ignored, with no adding to it.

**Net, in bps per trade** = gross − 18 − funding. A long pays positive rates settled in (entry, exit].

## Evaluation — once, after 2027-03-31

The headline is the **trade-weighted mean net**, with its t from `espero.audit.trade_weighted_nw`, lags = 1,
using the entry's UTC day.

**PASS requires all of these:**

1. **It pays.** Trade-weighted net > 0 with t ≥ 3.
2. **Not one stretch.** Net > 0 in each half: entries before 2027-01-17 00:00 UTC, and from then on.
3. **Not one coin.** Among coins with at least 10 trades, more than half have net > 0.
4. **On the largest coins too.** Net > 0 across BTC, ETH, SOL, XRP, DOGE and LINK together.

**INCONCLUSIVE:** fewer than 100 trades. **Anything else: FAIL.**

**Information only**, never a claim (`FORWARD_FAMILY.md`, rule 7):

- the signals #58 voids here and their net, as the direct comparison of the two guards;
- holds of 1 hour and 1 day;
- gross and funding separately, and the hit rate;
- by coin;
- counts of signals, dropped trades, failed reads and invalid pairs.

## Power — stated now

The same planning numbers as #58, with no prior effect size and about 150 bps of noise per trade assumed.
About 200 trades need about +32 bps net for t = 3, and 500 need about +20 bps. **A FAIL is weak evidence
against the idea, unless the estimate itself is near or below zero.** The author still expects this more
likely to fail than pass. Most of HLP's position changes are probably ordinary market making.

## Outcomes, fixed now

**#58 and #59 count once** (`FORWARD_FAMILY.md`, rule 6). They differ only in the guard, so nearly all of their
trades should match, and passes in both are one finding.

- **PASS**: treated as a Tier A pass under `FORWARD_FAMILY.md`, rule 2: a real-money sizing and execution
  document, written before any order, on a venue from [VENUE_NONUS.md](VENUE_NONUS.md). The account holder
  checks eligibility and places any order. If #58 fails and #59 passes, that's reported as exactly that, and the
  document must say how much of the result comes from the pairs #58 voids.
- **FAIL**: this rule is closed. A later idea on HLP's data takes a new number and a new document.
- **INCONCLUSIVE**: no claim either way, and no extension of this test.

No stopping early on the running numbers, and no re-tuning of the percentiles, the hold or the coins.

## The paper book

Any paper book for this test runs in its own journal, apart from #58's. It simulates fills, holds no key, signs
nothing and doesn't touch testnet. **The verdict comes from the ledger rebuilt from the recordings, not from a book.**

## Known confounds

#58's all apply:

- **HLP isn't only absorbing.** Most of its changes are probably ordinary inventory, and the falling-price
  condition is only a stand-in for forced flow. The liquidator sub-account isn't separated.
- **15-minute snapshots are coarse.**
- **Costs in a sell-off.** 18 bps may be too low at these moments.
- **Related to the forced-liquidation family** (#27, #32, #45): a pass alongside those isn't fully independent.
- **Coverage.** Slots are lost when the Mac sleeps.
- **The thresholds have no data behind them.**

New with this test:

- **A second try at one idea.** It was prompted by a design flaw, not by a result, since no day of the window
  exists. It still adds a row to the trial list.
- **A failed read that returns no error.** The record catches an account whose read fails, not one that
  returns an empty or wrong answer. Those would look like real changes.

## Transparency — what was seen before this

- **Seen:** the file counts in #58's note (258 slots, 255 valid pairs, 2 invalid; 2 accounts with rows in most slots
  and 3 in 5 consecutive slots), and the collector's log lines, which give position, account and failure counts
  per slot (for example, 8 accounts asked and 0 failed).
- **Not seen:** any position, jump, price or return. Which account is the third wasn't checked.
- **Already known:** everything listed in #58's Transparency section.
- **No day of the forward window exists yet.**
