# Forward test — a sharp 5-minute fall, read by its open interest: cascade or repricing (#65)

Committed **before any day of the forward window exists**: the window opens 2026-11-03, and this was
written on 2026-11-02. A paper test: nothing trades. The sixty-fifth test in this repo. It joins the
forward family by citing [PREREGISTRATION_SLEEVES.md](PREREGISTRATION_SLEEVES.md), which it cannot change.

## Why

This is idea 18 in [IDEAS_NOVEL.md](IDEAS_NOVEL.md), explored on 2026-11-02 in
[EXPLORE_OI5M.md](EXPLORE_OI5M.md) on the days before this window, and every number and threshold below
was chosen after that look. #25 found on hourly bars that a fall made of positions closing behaves
unlike a fall made of new sellers; #26 found that forced selling overshoots and comes back. The
exploration found the same sign at 5 minutes on 3.4 days: after a sharp 5-minute fall, open interest
down 1% or more leaned up over the next hour and open interest up 1% or more leaned down, with t
between 1.2 and 2.5 on 81 independent hours of one falling regime.

**The mechanism.** A fall with open interest falling is positions being closed, liquidated or not,
which is forced flow and overshoots. A fall with open interest rising is new shorts being opened, which
is information, and does not.

**The prediction.** After a 5-minute fall in the coin's own 2% tail, the next hour's return has the sign
of the open-interest change over the same 5 minutes: up when open interest fell 1% or more (the
**reversal** signal), down when it rose 1% or more (the **continuation** signal), by more than the cost
of trading it, on each side on its own.

## Data — fixed

- **Contexts.** `data/hlcollect/ctx/`, one file per 5-minute slot, every listed perp's mark and open
  interest (in coins) and `day_volume`, from one read. A file's `ts` is when the read started.
- **Coins.** Every perp whose `day_volume` at the signal's slot is at least $5,000,000: a tier rule, not a
  list. The exploration's "closing" side showed nothing under that.
- **Window.** Signals from 2026-11-03 00:00 UTC through 2027-03-31 23:59 UTC, 149 days. Slots before it,
  from 2026-10-29, serve only as trailing history.
- **Prices for fills.** `data/hlcollect/candles/`, Hyperliquid's 1-minute candles of every listed perp;
  candles missing from a file may be taken from the public candle API while served, and the count is
  reported.
- **Funding.** Hyperliquid's settled hourly rates, from its public funding history.
- **Gaps.** A gap stays a gap. A missing slot gives no return across it and no signal at it.

## The rule — fixed

For each coin and each 5-minute slot `t` with a file on disk and a file at `t − 300 s`:

1. **The move and the change.** `r = mark_t / mark_{t−1} − 1` and `d = OI_t / OI_{t−1} − 1`, both from the
   slot's file and the previous slot's.
2. **The tail.** `q` is the 2nd percentile of the coin's `r` over the slots in the 7 days before `t`, not
   including `t`; at least 1,008 such values are required (half of 2,016), or the slot gives no signal.
3. **Liquid.** `day_volume` at `t` is at least $5,000,000.
4. **Signal.** `r ≤ q`, and either `d ≤ −1%` (**reversal**, side +1) or `d ≥ +1%` (**continuation**,
   side −1). Known at `A = ts + 120 s`, `ts` the slot file's own value.
5. **Entry.** On the signal's side, at the open of the first 1-minute candle starting at least 60 s after
   `A`. If that candle isn't within 5 minutes of `A`, the trade is dropped and counted.
6. **Exit.** At the open of the first 1-minute candle starting at least 1 hour after entry. If that candle
   isn't within 5 minutes of the hour, the trade is dropped and counted. A trade whose exit falls after the
   window is dropped.
7. **One at a time.** A coin holds one trade. A signal during a hold is ignored, with no adding to it.

**Net, in bps per trade** = `side × gross − 18 − side × funding`, as #64 defines it: a long pays a positive
rate, a short receives it. The 18 bps is the repo's forward hurdle.

## Evaluation — once, after 2027-03-31

The headline is the **trade-weighted mean net** over both sides together, with its t from the
slot-clustered estimator in `espero/oi5m.py` (`cluster_t`: residuals summed within each 5-minute slot,
Bartlett weights over 12 slots, because the whole panel moves at once and the hour overlaps).

**PASS requires all of these:**

1. **It pays.** Trade-weighted net > 0 with t ≥ 3.
2. **Each side on its own.** The reversal trades' net > 0 and the continuation trades' net > 0, each with
   t ≥ 2 by the same estimator.
3. **Not one stretch.** Net > 0 in each half: entries before 2027-01-17 00:00 UTC, and from then on.
4. **Not one coin.** Among coins with at least 10 trades, more than half have net > 0.
5. **On the liquid coins too.** Net > 0 across the trades whose `day_volume` at the slot was at least
   $50,000,000.

**INCONCLUSIVE:** fewer than 100 closed trades on either side. **Anything else: FAIL.** If 1, 3, 4 and 5
hold and only one side of 2 fails, the verdict is "FAIL (one side only)" and names the side.

**Information only**, never a claim (`FORWARD_FAMILY.md`):

- holds of 15 minutes and 4 hours;
- the thin tier (`day_volume` under $5M), in its own ledger;
- the mirror on rises (`r` at or above the 98th percentile, sides reversed), in its own ledger;
- the open-interest change over the hour before the signal, split at the coin's median;
- gross and funding separately, and the hit rate, by side and by tier;
- counts of signals, slots without the previous slot, slots short of history, dropped and ignored trades.

## Power — stated now

- **Trades.** The explored days held 57 hard events in the two liquid tiers in 3.4 days, about 17 a day,
  in a falling week; the window should hold on the order of 2,000 before one-at-a-time, perhaps half that
  in a calm one, split unevenly between the sides (39 reversal against 18 continuation in the top tier).
- **Noise.** About 150 bps per trade over an hour is assumed from the exploration's spread; trades cluster
  in sell-offs and the slot-clustered t accounts for that.
- **What that detects.** At 1,000 trades and 150 bps, t = 3 needs about +15 bps net; at 300, about +26.
  The exploration's sizes were about +50 and −45 bps gross in the liquid tiers, +12 and −50 in the panel.
- **A FAIL here is evidence against the idea at this horizon** if the estimate is near or below zero on
  both sides; a FAIL on one side with the other paying is recorded as such and is the more likely outcome
  the author sees, since the continuation side was the stronger of the two.

## Outcomes, fixed now

- **PASS**: treated as a Tier A pass under `FORWARD_FAMILY.md`, rule 2: a real-money sizing and execution
  document, written before any order, on a venue from [VENUE_NONUS.md](VENUE_NONUS.md). The account holder
  checks eligibility and places any order. The costs on the thin end of the liquid tier are the first
  thing that document must measure.
- **FAIL**: this rule is closed. A later idea on open interest at 5 minutes takes a new number.
- **INCONCLUSIVE**: no claim either way, and no extension of this test. Any continuation is a new document.

No stopping early on the running numbers, and no re-tuning of the tail, the floor, the hold, the tier or
the history. The collector is not changed for this test.

The ledger's code is `espero/oi5m.py`, run once with `espero oi5m --verdict` after the window has closed.
It refuses to read the recordings before then. There's no paper book, and this document starts no new
process.

## Known confounds

- **The thresholds come from the explored days.** The 2% tail, the 1% floor, the 1-hour hold and the $5M
  tier were chosen after seeing 3.4 days of data; that is why the test is forward, and why a pass on the
  same sign is the only kind that counts.
- **One regime explored.** The market fell through the explored days; the sign of the continuation side
  may be that week's drift in disguise. The window's two halves and the unconditional drift reported
  beside the verdict are the checks.
- **What a 5-minute open-interest change is.** Liquidations, closes and opens net together; the mark and
  open interest are read together, but within the 5 minutes the order of events is unknown.
- **Late by up to 5 minutes, then 2 to 3 more.** The signal is read at the slot and entered minutes
  later; the exploration's returns are mark to mark from the slot, so the fill is later than the figures
  that suggested it.
- **Costs at the thin end.** 18 bps is the repo's hurdle; a coin at $5M of daily volume may not trade for
  it. The $50M criterion is there for that.
- **Related to the forced-liquidation family.** Signals will coincide with #26's, #27's, #45's, #58's,
  #59's, #60's and #64's events; the overlap is reported.
- **Coverage.** Slots are lost when the Mac sleeps, and a lost previous slot voids the next.

## Transparency — what was seen before this

- **Seen:** everything in [EXPLORE_OI5M.md](EXPLORE_OI5M.md) and its run output, on the ctx slots from
  2026-10-29 15:05 to 2026-11-01 23:55 UTC: every split, tier and horizon listed there, including the
  figures this rule's thresholds were chosen from. The ctx files of 2026-11-02 exist on disk and were not
  opened by the exploration; the ledger will read them as trailing history only.
- **Not seen:** any slot from 2026-11-02 on; any fill; any funding figure; the hour-before split's effect
  on the trade (the exploration found none).
- **Already known:** #25, #26, #44, #51 to #57, and the designs of #58 to #64.
- **No day of the forward window exists yet.**
