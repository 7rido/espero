# Forward test — does HLP's absorbed inventory bounce? (#58)

Committed **before any day of the forward window exists**: the window opens 2026-11-05, and this was
written on 2026-11-01. A paper test: nothing trades. No recorded position has been read to write it
(see Transparency). The fifty-eighth test in this repo.

## Why

The account holder asked for a paper book that uses the data the repo is gathering. No rule does yet, and
a rule can't be wired in without a test, so this is that test. It takes idea 4 in
[IDEAS_NOVEL.md](IDEAS_NOVEL.md), HLP's inventory.

**The mechanism.** HLP is Hyperliquid's own market-making and liquidation vault, and its positions are
public. When it takes the other side of a sharp fall, it holds inventory it didn't choose, and the idea
says that forced flow reverts. The sign comes from that note, written before collection began: "HLP's
forced buys at the bottom revert."

**The prediction.** After HLP's net position in a coin jumps up while that coin's price falls sharply, the
price rises over the next hours, by more than the cost of trading it.

## Data — fixed

- **Coins.** #45's 14: BTC, ETH, SOL, XRP, DOGE, LINK, ADA, AVAX, BNB, TRX, LTC, XLM, HBAR, and SHIB as
  Hyperliquid's `kSHIB`.
- **Window.** Signals from 2026-11-05 00:00 UTC through 2027-03-31 23:59 UTC, 147 days. Slots from
  2026-10-29 until the window opens serve only as the first trailing history.
- **HLP's position.** `data/hlcollect/hlp/`, one file per 15-minute slot. A coin's **net size** in a slot is
  `szi` summed over every address in that file. A coin with no row has net size 0.
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
5. **Guard against a failed read.** The collector skips an account that fails, without marking it in the
   file, which could look like a position vanishing and coming back. So if an address with rows in one slot
   has no rows in the adjacent slot, then every pair touching that change is invalid, on all coins. It gives
   no signal and doesn't enter the trailing history. A sub-account that truly went flat costs a few pairs,
   which is the safe direction.
6. **Entry.** Long, at the open of the first 1-minute candle starting at least 60 s after `t`. If that
   candle isn't within 5 minutes of `t`, the trade is dropped and counted.
7. **Exit.** At the open of the first 1-minute candle starting at least 4 hours after entry. If that candle
   isn't within 5 minutes of the 4-hour mark, the trade is dropped and counted. A trade whose exit falls
   after the window is dropped.
8. **One at a time.** A coin holds one trade. A signal during a hold is ignored, with no adding to it.

**Net, in bps per trade** = gross − 18 − funding. A long pays positive rates settled in (entry, exit]. The
18 bps is the repo's forward hurdle, charged on every coin. #51 found about 9–12 bps for a $1,000 round trip,
but on calm days only, and these entries come during sharp falls.

## Evaluation — once, after 2027-03-31

The headline is the **trade-weighted mean net**, with its t from `espero.audit.trade_weighted_nw`, lags = 1,
using the entry's UTC day. Holds of 4 hours can cross midnight, which the correction allows for.

**PASS requires all of these:**

1. **It pays.** Trade-weighted net > 0 with t ≥ 3.
2. **Not one stretch.** Net > 0 in each half: entries before 2027-01-17 00:00 UTC, and from then on.
3. **Not one coin.** Among coins with at least 10 trades, more than half have net > 0.
4. **On the largest coins too.** Net > 0 across BTC, ETH, SOL, XRP, DOGE and LINK together.

**INCONCLUSIVE:** fewer than 100 trades. **Anything else: FAIL.**

**Information only**, never a claim (`FORWARD_FAMILY.md`, rule 7):

- holds of 1 hour and 1 day;
- the mirror: `jump` below the 1st percentile with `ret` at or above the 90th, shorted;
- gross and funding separately, and the hit rate;
- by coin;
- counts of signals, dropped trades and invalid pairs.

## Power — stated now

There's no prior effect size, because nothing has read this data, so these are planning numbers only.

- **Trades.** The window has about 197,600 coin-pairs before gaps. The price condition alone passes about
  10% and the jump condition about 1%. If the two were independent, that's about 200 signals. Absorption
  would make them occur together, so more is plausible. One-at-a-time removes some.
- **Noise.** About 150 bps per trade over 4 hours is assumed, not measured. Trades that cluster in one sell-off
  add to it.
- **What that detects.**

  | trades | net needed for t = 3, ignoring clustering |
  |---|---|
  | 200 | about +32 bps |
  | 500 | about +20 bps |
  | 1,000 | about +14 bps |

- **For scale.** #26's forced-liquidation bounce netted about +22 bps at 4 hours, in sample. At that size, 200
  trades give an expected t of about 2, a pass chance near 20%, and 500 trades give about 3.3, near 60%.

**A FAIL here is weak evidence against the idea, unless the estimate itself is near or below zero.** The
author's expectation is that this more likely fails than passes: HLP's position is mostly ordinary market
making, and a t of 3 is a high bar.

## Outcomes, fixed now

- **PASS**: treated as a Tier A pass under `FORWARD_FAMILY.md`, rule 2: a real-money sizing and execution
  document, written before any order, on a venue from [VENUE_NONUS.md](VENUE_NONUS.md). The account holder
  checks eligibility and places any order.
- **FAIL**: this rule is closed. A later idea on HLP's data takes a new number and a new document. The paper
  book below is stopped after the verdict.
- **INCONCLUSIVE**: no claim either way, and no extension of this test. Any continuation is a new document.

No stopping early on the running numbers, and no re-tuning of the percentiles, the hold or the coins.

## The paper book

This is what puts the recorded data to use, and it's built after this document is committed.

- It reads each new HLP slot as it lands and applies the rule above, from the same code as the ledger.
- It simulates $1,000 per trade and starts at the window's open. It holds no key, signs nothing and doesn't
  touch testnet.
- It runs under launchd, in its own journal, apart from every other book.
- **The verdict comes from the ledger rebuilt from the recordings, not from the book.** A difference between
  the two is reported. The book's running numbers are for watching and are not a result.

## Known confounds

- **HLP isn't only absorbing.** It's also a market maker, so most of its changes are ordinary inventory. The
  falling-price condition is a stand-in for forced flow. The liquidator sub-account isn't separated.
- **15-minute snapshots are coarse.** A jump may have happened anywhere in the slot, and two moves can net out.
- **Costs in a sell-off.** 18 bps may be too low at these moments, and #51's measurements exclude them.
- **Related to the forced-liquidation family.** Signals may coincide with #27, #32 and #45's events. They're
  different events, but a pass alongside those isn't fully independent. The overlap is reported.
- **Coverage.** Slots are lost when the Mac sleeps. HLP's own files were complete on 2026-10-30 and 10-31, but
  sleep during sell-offs would remove the events this test needs.
- **The thresholds have no data behind them.** The percentiles, the 7-day history and the 4-hour hold are
  the author's choices. The 4 hours also follows #45, where that hold is under forward test.

## Transparency — what was seen before this

- **Seen:** each file's column names, file counts and slots per day, and the collector's code. The status
  commands print counts, never a value.
- **Not seen:** any `hlp`, `positions` or `candles` value, in this work. No script in `research/` reads these
  folders, and no earlier document reports a value from them.
- **A limit on that.** This can only speak to what the repo records. Files can't prove nobody opened them.
- **Already known:** #26's and #44's forced-liquidation results, #51's costs and #55–#57's microstructure
  measurements. None uses HLP's positions.
- **No day of the forward window exists yet.**
