# Pre-registration — the streaming engine's events against the next-day batch's (#71)

Committed **before** the streaming engine exists as code and before any comparison has been made. Written
2026-11-02. This document is the contract; the result document will report the measurement, and nothing below is
changed afterwards. A later idea takes a new number. **A measurement, information only:** it has a registered
tolerance and a reading, no t, no PASS or FAIL, spends no trial of the FDR family, and changes no forward verdict,
rule or criterion.

## Question

research/LIVE_LATENCY.md classes four forward rules as live-from-tape on the raw tape: #24, #29, #31 and #34. Their
budgets are 45 seconds to 12 minutes, and today the pipeline sees their events 12 to 36 hours late, at the 07:30 run.
A streaming engine reading the tape as it is written could emit them in seconds. **Does it emit the same events the
next day's batch emits for that day?** Where it does not, which side saw an event the other missed, and why, is the
finding.

## Scope, fixed now

- **Rules:** #24 (new 4-hour lows), #31 (bids under breakdowns), #29 (BTC and ETH after 16:00 ET), #34 (SOL and XRP
  into 16:00 ET). The collector-fed rules (#58–#60, #64, #65) are not in scope.
- **Coins:** the 13 Binance USDⓈ-M symbols the raw tape carries: BTC, ETH, SOL, BNB, XRP, ADA, DOGE, AVAX, LINK, TRX,
  LTC, XLM, HBAR. #24 and #31 on those 13 of their 42 (the other 29 are not recorded); #29 on BTC and ETH; #34 on
  SOL and XRP. **Both sides are compared on the same coins.**

## The engine (`espero/livesig.py`)

1. **Bars.** It reads Binance's `trade` frames from `<ESPERO_RAW_DIR>/binance/` (never `aggTrade` as well, which
   would count trades twice) and builds 5-minute bars by the trade's own time `T`: open the first price, close the
   last, high and low the extremes, **volume the sum of `q` in base units**, as the kline volume `lows.bars` reads.
2. **When a bar closes.** When any Binance frame's receive time passes the bar's end plus 2 seconds. A symbol with
   no trade in a closed bar gets a bar at its last close with volume 0, as Binance's klines do. A trade that arrives
   after its bar closed is counted as late and not applied.
3. **The rules, by the batch's own functions with the daily steps' own arguments,** on the coin's panel after each
   bar closes:
   - #24: `lows.events(bars, "down", first=lowsfwd.FORWARD_FROM, last=lowsfwd.FORWARD_TO)`;
   - #31: `bids.events(bars, None, bidsfwd.FORWARD_FROM, bidsfwd.FORWARD_TO, k=2.0, hold=48, taker_bars=48)`;
   - #29: `levetf.rows(bars, coin, day, day)`'s `r_post15` once the 15:55 ET bar has closed: side against it (the
     registered reversal);
   - #34: the same rows' `r` once the 15:40 ET bar has closed: side with it (the registered push).
4. **An event** is (rule, coin, side, ts): `ts` the time the functions report (for #24 and #31 the open of the bar
   after the trigger; for #29 and #34 16:00 and 15:45 ET), and `emitted_ms` the receive time of the frame that closed
   the bar. **Every return column the functions compute is dropped before anything is written or printed.**

## The comparison, per UTC day

- **Live events:** the engine replayed over the tape as it was written (`espero livesig --replay DAY`), which is what
  a running engine emits. When the loop runs (`espero livesig --loop`, installed by the holder), its own events must
  equal the replay's for the same day; any difference is reported as an engine fault.
- **Batch events:** the same functions on Binance's archive bars for the same coins (`data/lows/forward`), as the
  daily steps read them.
- **Beside them, the closed-tape batch:** the same functions on the tape's bars rebuilt after the day closed, late
  frames included. Agreement with live but not with the archive points at the inputs; with the archive but not live,
  at the streaming.
- **Matched** on (rule, coin, side, ts). A day's agreement is matched over the union of both sides' events.
- **A comparable day:** a day both sides hold in full, with no gap on the Binance tape longer than 120 seconds
  (`rawrec.gaps`) during the day or the 5 hours before it (the 50-bar warm-up), and the archive file present for every
  in-scope coin. Days before 2026-11-04 are not comparable: the tape begins on 2026-11-02, and the rules need a
  previous NYSE session and an hour of history the tape does not yet hold.

## The reading, information only

- **A day agrees** when at least **95 %** of the union matches.
- Reported after **30 comparable days**, then each day to 2027-03-31: the share of comparable days that agree, and
  **"the engine reproduces the batch"** when that share is at least **90 %**. It decides nothing: a sizing document
  for #24, #29, #31 or #34 quotes it (research/TEMPLATE_SIZING.md, section 2).
- **Information beside it:** agreement per rule; every live-only and batch-only event with its class (input or
  streaming, from the closed-tape batch); late frames per day; and, from the running loop only, the emitted latency
  (`emitted_ms` minus the bar's end) per rule, median and 95th percentile, against the rule's budget.

## Power

Over 30 comparable days, #24 and #31 fire several times a day across 13 coins and #29 and #34 twice a day each: a few
hundred events, enough to read an agreement share to a percent or two. A tolerance, not a test.

## What it cannot say

Agreement says the engine sees what the batch sees; it says nothing of whether either pays. The archive is
Binance's own record and the tape this Mac's; a frame the Mac never received is a gap, not a disagreement.

## Robustness, information only

The six readouts of research/ROBUSTNESS_STANDARD.md are not applicable, each for its reason: no return series (every
return column is dropped), no configurations, nothing fitted, no signal series of its own, no weights, no edge. The
block is printed with those reasons.

## Timestamp

This file's SHA-256 is stamped with OpenTimestamps (`research/PREREGISTRATION_LIVESIG.md.ots`, `scripts/timestamp.sh`)
at the commit that adds it, before the engine exists.
