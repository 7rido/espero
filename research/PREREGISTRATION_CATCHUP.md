# Pre-registration — how much of Hyperliquid's catch-up to Binance is left after a realistic delay? (#57)

Committed **before this measurement has been run on any real file**. It has been run only on made-up files, to test the
code. **This commit does not run it.** The account holder decides when to run it, and it runs once.

## The question

#52 found that after a sharp Binance move, Hyperliquid's price catches up by about 13 bps within 5 seconds and holds for 30.
That figure assumed no reaction time and a fill at the mid. **If you buy after a realistic delay, at the book, with fees, and
hold 30 seconds, what's left?**

## This sample isn't clean, and can't produce an edge

These are the same 24 days #52 read, on the same files. The author has seen the following, from `research/RESULTS_PATTERNS.md`:

- 4,765 Binance moves of 10+ bps in a one-second bin, with Hyperliquid's mid up +6.47 bps in the next second, +12.92 in 5 s and
  +12.88 in 30 s, so about 6.4 bps remain between +1 s and +30 s.
- All 24 days and all 6 coins are positive at 5 s, and #51's $1,000 round trip is about 9–11 bps on these coins.

So **the author expects a loss at the main delay, of about 3–5 bps per event**, and this test is mostly checking that arithmetic
with a real fill. **Even the best outcome here is only a reason to test on unread days.** It can't justify a claim of an edge.

## Data — fixed

- **Files already on disk, no download.** Binance USDⓈ-M `trades` (`data/patterns/`) and Hyperliquid `book_snapshot_25`
  (`data/bookwalk/`), from Tardis's free first-of-month days, 2024-11-01 to 2026-10-01.
- **Coins:** #52's six: BTC, ETH, SOL, XRP, DOGE, LINK.
- **The clock.** `local_timestamp` on both, Tardis's one receipt clock. It includes each venue's path to the recorder, and an
  account in another place would differ.
- **Book.** Top 5 levels only, since #51 found 5 levels from 2026-07-01.

## The rule — fixed

1. **Event.** At each Binance trade, compare its price with the last trade at or before 1,000 ms earlier. An event is the first
   trade where the absolute change is at least 10 bps, and at least 30 s after the coin's previous kept event. Unlike #52's fixed
   one-second bins, this can be computed live. **Direction** is the sign of the change.
2. **Entry.** At event time + the delay, a market order for $1,000 walks Hyperliquid's first snapshot received **at or after**
   that time: buy for an up move, sell for a down move.
3. **Exit.** The first snapshot at or after entry time + 30 s, the opposite market order for the same size.
4. **Net, bps per event** = direction × (exit mid / entry mid − 1) × 10,000 − entry walk cost − exit walk cost − 2 × 4.5 bps fee.
   Walk costs are #51's (`espero.bookwalk`). Funding over 30 s is ignored, and that is stated, not hidden.
5. **Dropped and counted:** no snapshot within 5 s of the time it's needed, a move past the end of the day, or a book that can't
   fill the order on either leg. An unfillable leg's true cost is higher than anything measured, so its share is reported.

**Delays:** 100, 250, 500, **1,000**, 2,000 and 5,000 ms.

**The main delay is 1,000 ms.** `research/RESULTS_REHEARSAL.md` and `RESULTS_TESTNET.md` measured send-to-acknowledgement on this
machine at a median of 872–906 ms, on testnet, not mainnet. That's signing plus a round trip, and an order reaches the book a
little before its acknowledgement, but the time to see Binance's trade and decide also has to fit in. It's an approximation and
is stated as one. Delays under about 500 ms need infrastructure this project doesn't have.

## The verdict, one, at 1,000 ms, $1,000 and 30 s

A day's value is the mean net over its events across the six coins, and a day without events is left out. CI: 95% percentile
bootstrap over days, 10,000 draws, seed 57.

| verdict | rule, checked in this order |
|---|---|
| **NOT CAPTURED** | The CI's upper end is at or below zero |
| **WORTH TESTING ON UNREAD DAYS** | The CI's lower end is above zero, the first and last 12 days are both positive, at least 4 of 6 coins' means are positive, and at most 5% of events are dropped as unfillable |
| **CAN'T SAY** | Anything else |

**Power.** About 200 events a day over 24 days. #52's day-level spread suggests the CI will be about ±1 bp wide, so a 3–5 bps loss
or a similar gain would be seen clearly. That rests on the prior read, and isn't a formal calculation.

**What each leads to:**

- **NOT CAPTURED:** the catch-up stays a description for reading the market, and nothing more is done with it on this account.
- **CAN'T SAY:** the same, and the reason is recorded.
- **WORTH TESTING ON UNREAD DAYS:** a new, numbered pre-registration on days nobody has read, which means paid Tardis days or a new
  recorder for both venues. Your decision. No order, no ledger and no change to any forward test comes from this result.

## Reported alongside, none of it a verdict

- Net, CI and event count at every delay, and the longest delay with a positive mean.
- At the main delay: gross, walk costs and fee separately, per coin, by half, and the share dropped by each reason.
- Sizes: $10,000 at the same delay, with its unfillable share.
- Holds of 5 and 60 s at the same delay.
- The share of events where the mid had already reached the event's full size by the entry.

## What it can't show

- **Other people.** It charges the displayed book as if nobody else is reacting. Many events are the same moment for every fast
  participant, so a real order may well fare worse than this.
- **Between snapshots.** The book file updates about every 0.54 s, and "first snapshot at or after" can add up to that much delay.
  It's conservative by design, and the shortest delays are blurred by it.
- **Crashes, and days outside the sample.** First-of-month days include no known cascade.
- **Your account's latency to Binance's feed.** Only the recorder's view is measured.

## Run once, when asked

`python research/catchup.py run` writes `research/catchup_output.txt` and refuses a second run. The result goes in
`research/RESULTS_CATCHUP.md` whatever it shows, and `research/trials.csv` is updated. Anything looked at afterwards is labelled
information only. This isn't investment advice, and nothing here places an order.
