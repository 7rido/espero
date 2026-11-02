# Pre-registration — new Binance USD-M perps after they list, short against BTC (#67)

Committed **before** the holdout is read. This document is the contract; the result document will say whether
it was met, and nothing below is changed afterwards. A later idea takes a new number.

The event list, the split and every design run are in [EXPLORE_LISTDRIFT.md](EXPLORE_LISTDRIFT.md): the split and
events (`a30eda6`), the dating fix and second run (`a014781`), the cover rule (`9ce43fd`), its run (`917e403`), and
the rehearsal of the final code ([listdrift_design_run.txt](listdrift_design_run.txt)). All read files through
2024-12 only.

## Hypothesis

After Binance lists a new USDT-margined perpetual on a crypto token, its price falls against BTC over the next week
by more than funding and costs. Two one-sided flows predict it. A newly launched token meets supply from airdrop
recipients, unlocks and early holders. And a perpetual opens short selling on a coin that until then could only
be bought.

## Data

Read-only; the only writes are the funding cache and its manifest.

- **Events:** [listdrift_events.csv](listdrift_events.csv), committed before any price was read: every USDT
  perpetual first traded on Binance USD-M from 2023-01, kept when Binance's own `underlyingType` is `COIN`, 513
  events. The holdout's positions are those whose entry and exit both fall inside 2025-01-01 → 2026-09-30.
- **Prices:** the point-in-time store's daily klines (`data/pit/klines_1d`, Binance's public archive, delisted
  symbols included).
- **Funding:** Binance's archive per symbol and month through `espero.pit.fetch_file`, each file checked against
  Binance's SHA-256, cached in `data/cache/listdrift/`, hashes in [listdrift_manifest.csv](listdrift_manifest.csv).
  BTC's from the store.
- **Excluded before looking:** non-coin contracts by Binance's type, re-listings, listing months that disagree with
  the first bar, positions that straddle 2025-01-01. A position whose funding month is missing from the archive is
  dropped and counted.

## Rule

1. **Listing day:** the UTC day of the symbol's first daily bar. Binance's onboardDate only decided which events
   exist.
2. **Position:** short the listing and long BTCUSDT, one unit of notional each, opened at the open of the day after
   the listing day and closed at the open 7 days later. A listing whose bars stop inside the hold closes at its last
   close, and the hedge with it. There is no stop and no cover.
3. **Daily P&L:** each leg's price move over its entry price; funding as settled, counting a settlement after the
   entry and at or before the exit, scaled by the day's close over the entry price, a short receiving a positive
   rate; costs per side on the first and the last day: the listing 15 bps (Binance's taker fee of 5 plus an assumed
   half-spread of 10, which no measurement covers) and BTC 5.33 bps (`espero.costs`, measured).
4. **The series:** each day's mean P&L over the positions open that day. Its t is Newey-West with Bartlett weights
   and floor(4(n/100)^(2/9)) lags, its p two-sided from the normal, n being over 100 (`FDR_STANDARD.md`).

Code: [espero/listdrift.py](../espero/listdrift.py) (`CHOSEN_HOLD = 7`, `COVER = False`) and
[listdrift.py](listdrift.py) at this document's commit; `tests/test_listdrift.py`, 37 of 38 mutations caught, the one
missed equivalent.

## Criteria, all required

1. **Statistical bar:** the daily series' mean is above zero with t ≥ 3, and #67's Benjamini-Hochberg q is below
   0.05 over every judged test in `research/trials.csv` with #67 included, a missing p counted as 1
   (`research/fdr_rescore.py`'s family). Today a new test needs |t| ≥ 2.49 for that q, so t ≥ 3 binds.
2. **Not one stretch:** the mean is above zero in each half of the days in date order, the earlier half taking the
   odd one.
3. **Not a few collapses:** the median position's net is above zero.
4. **Not alts against BTC:** the same short against a point-in-time basket instead of BTC, price only, has a
   positive daily mean. The basket is the 30 coins with the most quote volume over the 30 days before the entry,
   each first traded at least 365 days before it and with a bar on every one of those days; BTC, ETH, pegged coins,
   indexes and non-coins are left out.

**INCONCLUSIVE:** fewer than 100 positions or 100 days.

## Power

On the design window, 222 positions over 565 days: daily mean +54 bps, t 1.65; the median position +10.0%, the
mean +2.6%. If the holdout's effect and dependence match, its t at about 638 days is 1.8. 2025 listed about twice
the design's coins a year, and the pumps that carry the variance belong to single coins, so more positions a day
could lift it toward 2.5. **Under 3 either way: a PASS is unlikely.** A FAIL is weak evidence against the drift and
strong evidence that the trade, as specified, is not tradable. The readouts below answer the plainer question,
whether the typical new listing still falls against BTC.

## Outcomes

- **PASS:** all four criteria hold. What follows is `research/FORWARD_FAMILY.md`: a pass is no reason for capital by
  itself; any real trade needs a forward confirmation window and the account holder's own venue check.
- **FAIL:** any criterion misses. The short-the-listing trade closes at this specification; a variant takes a new
  number and cannot use this holdout.
- **INCONCLUSIVE:** as above.

## Information only

Printed beside the verdict by `listdrift.py --holdout`, never a claim:

- the trade gross of funding and costs; the short alone; against the basket, with its t;
- the trade with the cover rule, and how many positions the rule would have closed early;
- funding per position, mean and median; the listing cost per side at which the trade breaks even;
- the 14- and 30-day holds; entry two days after the listing;
- by quarter of entry; by the listing day's own move, above and below its median;
- positions whose listing stopped trading inside the hold; the worst rise against the short at a daily close;
- how often Binance's onboardDate fell on the first trade.

## Robustness, information only

Deflated Sharpe, PBO, purged k-fold and capacity are not computed. The design window saw six configurations, three
holds with and without the cover rule, and one was registered by a rule written before the first run. The ledger's
Benjamini-Hochberg family is the multiple-testing control.

## Transparency — what was seen before this

- The four design-window outputs named above, on files through 2024-12 only; the dating bug and its fix; the cover
  rule, tried and set aside on the account holder's decision.
- Daily bars of these symbols were read for #48, and Binance USD-M returns by many tests. No return after a listing
  in 2025–2026 has been computed.
- The holdout overlaps #49's sealed window (2025-01 → 2026-09) by date. #49 seals book depth against the next day's
  return. Nothing here opens a book file or relates anything to depth, so #49 stays sealed.
- The account holder's report of 2026-11-02 grades the evidence for a post-listing fade C. The same report ran two
  tests on espero's data in another sandbox, CTREND-lite and risk-managed momentum; their files are not in this
  repo and they are not in the ledger. t ≥ 3 binds #67's bar either way.
- The author knows the 2023–26 market in general, and the common claim that new tokens fall after launch.
