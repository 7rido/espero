# Exploration — #67's design window: new Binance USD-M perps after they list

**Not a test.** This fixes, before any price is read, the event list, the split between #67's design window and
its holdout, the specification tried on the design window, and what the design run may and may not change.
#67's pre-registration, `PREREGISTRATION_LISTDRIFT.md`, follows the design run and is committed before the holdout
is read.

Script: [listdrift.py](listdrift.py), rule [espero/listdrift.py](../espero/listdrift.py), event list
[listdrift_events.csv](listdrift_events.csv). This document and the event list were committed before the script
read any price.

## The question

After Binance lists a new USDT-margined perpetual on a crypto token, does the price drift down over the next week
to month against BTC, after funding and costs? Two mechanisms predict it. A newly launched token meets supply from
airdrop recipients, unlocks and early holders. And a perpetual opens short selling on a coin that until then could
only be bought. The report the account holder brought on 2026-11-02 grades the evidence C: a post-listing fade that
replicated on a pre-specified Bybit holdout in an unrefereed study, and listing-day pops in older samples.

## The events, from metadata only

- **Symbols:** every USDT perpetual in the point-in-time store's daily klines (`data/pit/klines_1d`, 1,056 USD-M
  symbols since 2020, delisted ones included) whose first bar is in 2023-01 or later and whose name has no `_`
  (dated contracts): 734. The month of the first bar comes from file names.
- **Type:** Binance's own `underlyingType`, from the newest Wayback capture of `fapi/v1/exchangeInfo` since 2023
  that lists the symbol (the newest is 2026-10-01). Only `COIN` is kept. Excluded: 174 US equities, 15 Hong Kong,
  8 Korean and 2 Chinese equities, 8 commodities, 4 pre-market contracts, 1 FX pair, 1 index.
- **Listing day:** the UTC day of Binance's `onboardDate`. Excluded: 6 whose onboard month differs from the first
  bar's month (re-listings, or a record that moved), 1 with no onboard date, 1 whose asset, without a 1000-style
  multiplier, traded under another symbol before.
- **Events: 513.** By listing year: 96 in 2023, 129 in 2024, 237 in 2025 and 51 in 2026.
- Some events are old tokens getting their first Binance perpetual rather than new tokens. The second mechanism
  covers them; nothing here separates the two.

## The split, fixed now

- **Design:** positions whose entry and exit both fall inside 2023-01-01 → 2024-12-31. `listdrift.py --design`
  refuses any kline or funding file after 2024-12.
- **Holdout:** positions inside 2025-01-01 → 2026-09-30. September 2026 is the last month whose funding file is
  published and whose BTC funding is in the store. Read once by `listdrift.py --holdout`, which refuses until the
  hold is set and the pre-registration is committed unchanged.
- A position that straddles 2025-01-01 belongs to neither.

## What has been seen before this

- Daily bars of these symbols were read for #48 (the universe for #2's attribution), and Binance USD-M returns
  have been read by many tests. No test here has measured a return after a listing.
- The holdout overlaps #49's sealed window (2025-01 → 2026-09) by date. #49 seals book depth against the next
  day's return for the 20 most-traded coins. Nothing here opens a book file or relates anything to depth.
- The author knows the 2023–26 market in general, and the common claim that new tokens fall after launch.

## The specification tried on the design window

1. **Position.** Short the listing and long BTCUSDT, one unit of notional each, opened at the open of the day after
   the listing day and closed at the open H days later, H being 7, 14 or 30.
2. **Daily P&L.** Each leg's price move over its entry price. Funding from Binance's archive, settled rates: a
   settlement counts when it falls after the entry and at or before the exit, scaled by the day's close over the
   entry price; a short receives a positive rate. Costs on the first and the last day, per side: the listing 15 bps,
   Binance's taker fee of 5 plus an assumed half-spread of 10, which no measurement covers (about 3.5 times the
   widest half-spread #39 measured on any coin, 2.8 bps on OP on Hyperliquid); BTC 5.33 bps, measured
   (`espero.costs`).
3. **A listing that stops trading** inside the hold closes at its last close, and the hedge closes with it.
4. **The series.** Each day's mean P&L over the positions open that day, in calendar time, so overlapping listings
   and their shared market moves are one observation a day. Its t is Newey-West with `FDR_STANDARD.md`'s lag count,
   on a daily series as the standard says.
5. **Conditions tried.** Both halves of the days positive. The median position positive. And the same short
   against a point-in-time basket instead of BTC, price only: the 30 coins with the most quote volume over the 30
   days before the entry, each first traded at least 365 days before it and with a bar on every one of those days,
   BTC, ETH, pegged coins, indexes and non-coins left out.
6. **Information tried:** the trade gross of funding and costs; the short alone; funding per position; the
   listing cost per side at which the trade breaks even; entry two days after the listing.

## What the design run may change, and what it may not

- **May change:** H, chosen as the largest design t among 7, 14 and 30, the other two becoming information; the
  assumed half-spread, upward only; the information readouts; bugs. Whatever changes is named in the
  pre-registration as chosen on the design window.
- **May not change:** the event list and its exclusions; the split; entry at the open of the day after the listing;
  BTC as the hedge; funding and costs counted; the calendar-time series and its t; the bar, t ≥ 3 with
  Benjamini-Hochberg q < 0.05 over every judged test; the conditions.
- If the design window shows no drift at any H, the test may be abandoned before any holdout read. That would be
  reported here, not hidden.

## The design run, twice

Both runs read files through 2024-12 only. The holdout is unread.

**First run, listing day = Binance's onboardDate** (output [listdrift_design_run_onboard.txt](listdrift_design_run_onboard.txt)).
For 32 of 222 design positions the onboardDate fell one to four days before the symbol's first trade. 25 positions
therefore opened at the first print rather than a day after it, and 7 found no bar to open on. This breaks the
promise above, entry at the open of the day after the listing day, so it is a bug, and it is the one change made
to the event list: the events and their exclusions stand, decided by the onboardDate as before, but each is dated by
its first daily bar (`espero.listdrift.dated`). The correction uses no return. Its t moved down, and it is kept.

**Second run, listing day = the first trade** (output [listdrift_design_run.txt](listdrift_design_run.txt)). Net of
funding and costs, short the listing and long BTC:

| hold | positions | t, daily series | mean position | median position | gross t | against the basket, t | funding per position, mean |
|---|---|---|---|---|---|---|---|
| 7 days | 222 | 1.65 (was 1.97) | +2.6% | +10.0% | 2.35 | 2.37 | −1.3% |
| 14 days | 214 | 1.17 (was 1.28) | +3.6% | +13.3% | 1.67 | 1.39 | −1.5% |
| 30 days | 199 | 0.95 (was 1.11) | +6.1% | +20.5% | 1.35 | 1.08 | −1.6% |

- **The hold is 7 days**, the largest t, as the rule above says.
- **The drift is there and the trade is weak.** The median listing falls about 10% against BTC in its first week.
  A few listings rise hard against the short and pay heavy funding while they do: mean funding is −1.3% a position
  against a median of +0.1%, and the mean position is a quarter of the median. The halves fade, +81 then +28 bps
  a day. The break-even listing cost is about 140 bps a side, so costs are not the problem.
- **The abandon clause does not apply:** there is drift at every hold. **Power is low:** at the holdout's 638 days
  the same effect gives t about 1.8, perhaps 2 with 2025's denser listings, against a bar of 3.
- The holdout is the only historical sample for this question. Whether to read it with this specification, or to
  add a cover rule first, is the account holder's decision, asked on 2026-11-02 before any pre-registration.

## The cover rule, fixed before the third design run

**Decided by the account holder on 2026-11-02, after the second run:** add a cover rule before any holdout read.
This is a change the section "What the design run may change" did not list, made on the account holder's word
and written here before the third run reads anything.

- **The rule.** The short is covered, and the BTC hedge closed with it, at the open of the day after the first
  daily close above the high of the listing day's own bar. Without such a close the planned exit stands.
- **Where the level comes from.** It is the usual stop for shorting a new issue, the high of its first day, taken
  as is. It has no parameter, so nothing was scanned to choose it; it is known at the entry; and it aims at what
  the second run showed, a few listings rising hard against the short and paying funding while they do. The
  fill is the next open, the repo's fill rule, since daily bars cannot say where an intraday stop would fill.
- **Everything else stands:** the events, the split, the entry, the hedge, funding and costs, the series, its t,
  the bar, the conditions, and the hold chosen as the largest design t among 7, 14 and 30. The comparison against
  the basket is closed by the same rule. The trade without the rule is printed as information.

## The third design run, with the cover rule

Files through 2024-12 only; the holdout is unread. Output [listdrift_design_run.txt](listdrift_design_run.txt); the
second run's is kept as [listdrift_design_run_nocover.txt](listdrift_design_run_nocover.txt).

| hold | covered early | t, net | mean position | median position | t without the rule |
|---|---|---|---|---|---|
| 7 days | 88 of 222 | 0.12 | +0.3% | +6.1% | 1.65 |
| 14 days | 101 of 214 | 0.39 | +0.9% | +1.0% | 1.17 |
| 30 days | 111 of 199 | 0.49 | +2.9% | −0.7% | 0.95 |

- **The rule closes 40 to 56% of positions early, and the trade loses most of what it had.** A listing that closes
  above its first day's high often falls afterwards, so the cover takes the loss and misses the fade. Funding per
  position halves, to −0.6%, but the price lost by covering outweighs it. The later half of the design is
  negative at every hold.
- **The abandon clause applies to the trade as now specified:** no hold shows drift; the best t is 0.49. Reading the
  holdout with this rule would spend it on a trade the design window says has nothing.
- Choosing another cover level now would fit it to the design window, which this document ruled out. Going back
  to the trade without the rule is the account holder's call, asked on 2026-11-02; its projected holdout t is
  about 1.8, against a bar of 3.
- Until then `listdrift.CHOSEN_HOLD` stays unset, and `--holdout` refuses.

## Set aside, and what #67 registers

On the account holder's decision on 2026-11-02, before any holdout read, the cover rule is set aside: #67
registers the trade without it, at 7 days, the largest design t without the rule (1.65), as the hold rule above
says. The cover rule's code stays, tested, and the covered trade is printed as information. The final code was
rehearsed on the design window and reproduces the second run (output [listdrift_design_run.txt](listdrift_design_run.txt);
the third run's is kept as [listdrift_design_run_cover.txt](listdrift_design_run_cover.txt)).
