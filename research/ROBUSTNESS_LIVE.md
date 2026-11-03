# Readouts at size: what a sleeve is exposed to, before it is sized

**Written 2026-11-02, before any forward verdict and before any sleeve exists. Pre-registered, information only.**
research/ROBUSTNESS_STANDARD.md fixed six readouts that every result from #61 on carries. This adds four more for
the moment a pass becomes a sleeve: they are computed in its sizing document (research/TEMPLATE_SIZING.md, section
1) and at the family's judgment for #63's sleeves, on the series those use, never before a verdict. **They are
reported, never decisive:** no readout here changes a verdict, a weight or a size unless a later numbered
pre-registration makes it a bar, with the number, before that sleeve's data exists. They are a second table from
`espero.robustness.block_live` and `render_live`, so the six-line block of #61 to #67 is unchanged. This document
spends no trial and judges nothing.

## The four readouts

| readout | what it is | input | not applicable when |
|---|---|---|---|
| **BTC beta** | OLS beta of each sleeve's daily net return on BTC's daily return, with its t and R² (`robustness.beta`), and of the dip-buying cluster #22, #24, #31 as one equal-weight series, a day a member did not trade counting 0 as #63 counts it (`cluster_beta`) | the sleeves' daily net returns; BTC's daily return on the venue the sleeve trades | no sleeve, or no member of the cluster passed |
| **Lower-tail dependence** | for each pair of sleeves, the chance one is in its worst 5 % of days given the other is (`lower_tail_dependence`, `tail_matrix`), against 5 % if they were independent, beside the Pearson correlation #63's weights use | the same returns | fewer than two sleeves |
| **Regime split** | each sleeve's mean daily return, count and t by calendar year (`by_year`) and by funding regime: "high" where the trailing 30-day mean of the venue's daily funding is above the window's median, else "low" (`funding_regime`) | the returns; the venue's funding history | no returns or no funding history |
| **Deflated Sharpe at the intended size** | the deflated Sharpe (N = the ledger's judged rows, as the standard fixes) of the sleeve's registered net series once each observation pays its trades' **extra** impact at the intended notional: twice the gap between the recorded book's sweep cost at that notional and at $1,000, the small size the registered costs were measured at (`extra_cost_bps`, `deflated_sharpe_at_size`), set beside the capacity readout | the net series, trades per observation, the recorded book at the sleeve's trade times, the intended notional from the sizing document | no net series, no intended size, or no recorded book past $1,000 |

## Why these four

- **BTC beta:** several forward rules buy falls (#22, #24, #31 buy the same kind of dip, FORWARD_FAMILY.md rule 6).
  A sleeve that is mostly BTC at a lag is not a separate source of return, and the cluster's beta says how much of the
  book's risk is one market move.
- **Tail dependence:** #63 combines sleeves on Pearson correlation over the whole window. Two sleeves can be unrelated
  on ordinary days and lose together on the worst ones, and that is the day the risk gate's stops are for.
- **Regime split:** #12's carry paid about three times more in 2024 than in other years. A pass that rests on one year
  or one funding regime is said to rest there.
- **Deflated Sharpe at size:** a sleeve's registered costs were measured at small size; at its intended notional the
  book charges more. The deflated Sharpe on the series that pays it is what the sizing document quotes beside the
  capacity readout.

## Rules

1. Computed once per sleeve, at its sizing document, on its verdict series and the recorded book at its own trade
   times; and once at the family's judgment for #63. Computing one earlier is a look and is disclosed as one.
2. Reported in full, "not applicable" with its reason included (`render_live` prints it).
3. Never a bar unless a later pre-registration says so, with a number, before its data exists.

## Limits

- Beta on daily returns misses intraday exposure: a 4-hour hold's beta is measured on the day it closes.
- Lower-tail dependence on a 150-day window rests on about seven tail days per sleeve; it is a reading, not an
  estimate to size on.
- The funding regime's median is the window's own, so the split describes the past and cannot be traded.
- The extra impact is a floor: the recorded book is the top 20 levels every five minutes (`data/hlbook`) or the raw
  tape's, and it walks as if the order affected no one else.
