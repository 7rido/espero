# Results — does a trade.xyz perp follow its listed ticker, hour by hour and at the bell? (#73)

Run once, 2026-11-10 02:33 UTC, by `research/hip3track.py` at e335799, against
`research/PREREGISTRATION_HIP3TRACK.md` (e07756a, stamped). A measurement, information only: no PASS or FAIL,
no t, no trial spent. The full output is `research/hip3track_run.txt`; every cell is in
`research/hip3track_cells.csv`; the prices it read are kept in `research/hip3track_inputs.csv.gz`, because the
venue serves 15-minute candles for about 52 days.

## What was measured

50 markets: every mapped market of a measured kind with $5M or more traded in the 24 hours before the run (42
stocks and ETFs, 8 indexes and commodities). None started after the window's start. The window was the
registered one, 2026-09-21 to 2026-11-07 UTC. No ticker split inside it, so no day was left out.

## The outcome, as registered

| session | markets with 100 pairs | follow | stands in? |
|---|---|---|---|
| regular (09:30 to 16:00 Eastern) | 42 | 37 | **yes** (88%) |
| pre-market (04:00 to 09:30) | 42 | 0 | **no** |
| after-hours (16:00 to 20:00) | 0 (84 to 86 pairs each) | — | **not judged**: too few pairs |
| futures hours (indexes, commodities) | 8 | 4 | **no** (50%) |

| at the bell (stocks and ETFs, 42 markets, 35 days each) | median across markets | stands in? |
|---|---|---|
| the perp at 09:30 against the official open | 7.4 bps | **yes** |
| the perp at 16:00 against the official close | 5.4 bps | **yes** |

**What this decides, as registered:**

- A backtest for these perps **may use a stock's or ETF's regular-session hourly bars**, and may fill at the
  official open and close.
- It **may not use pre-market or after-hours bars**, nor any index's or commodity's hourly futures bars. There,
  only the perp's own bars count, and they go back to the market's listing at most (October 2025 at the
  earliest).
- **Left out of ticker backtests**, because they do not follow even in the regular session: SNXX (median gap
  20.7 bps), AAOI (10.2), ARM (10.2), PURRDAT (10.8) and USAR (15.4).
  The four indexes and commodities that do not follow in futures hours are XYZ100, SP500, BRENTOIL and NATGAS;
  CL, GOLD, SILVER and COPPER do.
- The overnight session and the weekend have no ticker bars and stay untested, as registered: together 23% of
  the perps' dollar volume in the window.

## Information only

None of the following changes the outcome above.

- **The regular session follows closely where it follows.** The median of the 42 markets' median gaps is 4.9
  bps, correlations 0.979 to 0.999. The window's two halves: 37 of 42 follow in the first, 35 of 42 in the second.
- **Pre-market fails everywhere, and the ticker side may be the cause.** Correlations run 0.42 to 0.88, median
  gaps 11 to 81 bps. Every pre-market hourly bar Yahoo served for NVDA, INTC and SOXL reports zero volume, so
  its "open" is a thin print or a quote, not a traded price. This measurement cannot tell which side is wrong;
  it only says the ticker's pre-market bars cannot stand in.
- **The two equity index futures fail on correlation alone.** XYZ100 against NQ=F and SP500 against ES=F have
  median gaps of 0.8 and 0.7 bps and 95th percentiles of 4.6 and 3.4 bps, far inside the tolerance, but
  correlations of 0.76 and 0.80, under 0.90. Their hourly moves through the night are small enough that a few
  basis points of difference weigh against them. In the window's first half 6 of 8 futures markets followed,
  in the second 4.
- **The overnight return**, close to next open, differs by a median of 8.0 bps across the 42 stocks and ETFs.
- **Drift** between perp and ticker is under 3 bps an hour in every regular-session cell; the largest is
  PURRDAT's −8.65 bps in pre-market.
- **Share of the perps' dollar volume by session:** regular 46%, overnight 18%, pre-market 18%,
  after-hours 12%, weekend 5%.
- **After-hours** held 84 to 86 pairs per market against the 100 needed: Yahoo's after-hours hourly bars are
  fewer than the registration's estimate of about 100. Under the rule this is "too few", not a failure.

## What this means for the next stages

A strategy for these perps that trades stocks and ETFs on hourly bars can be backtested on the listed
ticker's regular session, with entries and exits inside 09:30 to 16:00 Eastern or at the official open and
close, for the 37 markets that follow. A rule that holds overnight is tested only from close to open on the
ticker, which is not the perp's night. Index and commodity rules, and anything trading outside the regular
session, need the perp's own year of bars or a forward test.
