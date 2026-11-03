# Pre-registration — edgewatch: the live stop rule, "is this sleeve still the registered edge?" (#70)

Committed **before** any forward verdict and before any sleeve exists. Written 2026-11-02, while every forward
ledger's running numbers are unread (as FORWARD_FAMILY.md records). This document is the contract; nothing below
is changed afterwards, and a later idea takes a new number. **It is a rule, not a hypothesis test,** like #63: it has
no t, no PASS or FAIL, and spends no trial of the FDR family. **It computes nothing on a sleeve before that sleeve's
verdict.** Until then it runs on synthetic data only (`tests/test_edgewatch.py`).

## Why now

A sleeve that passed will lose money on some days and in some months. #63's drawdown states act on the depth of a
loss (-10 % halves a sleeve, -20 % flattens it). They do not ask whether the edge itself has gone. A sleeve can lose
its edge while its equity drifts sideways, and it can be in an ordinary drawdown with its edge intact. That needs a
sequential test with a fixed false-alarm rate, and its threshold must be chosen before anyone sees live returns, or
the threshold will be set by them.

## Data

- **The registered series:** the sleeve's verdict series, in **the observation unit its verdict used** (a day's mean,
  a trade, a week), net of the costs its plan registered. It is read **once**, at the sleeve's sizing document's commit
  (research/TEMPLATE_SIZING.md, section 7), after the verdict is written: its mean `μ0`, its standard deviation `σ0`,
  and the series itself for the bootstrap.
- **The live series:** the sleeve's own observations from its first rung on, in the same unit, net of what the venue
  charged (`espero.attribution`). A missing observation adds nothing.
- **Observations a year:** the forward window's count of observations, scaled to 365 days.

## The rule

1. **The statistic,** a one-sided CUSUM for a fall of the mean from `μ0` to 0 (`espero.edgewatch.cusum`):
   `S = max(0, S + (μ0 − x) / σ0 − k)`, with `k = μ0 / (2 σ0)`, starting at 0.
2. **The alarm:** `S ≥ h`. After an alarm `S` restarts from 0.
3. **The threshold `h`,** fixed at the sizing document's commit (`edgewatch.calibrate_h`): the smallest value that the
   CUSUM's maximum over **one year of observations** reaches in at most **5 %** of 20,000 bootstrap paths drawn from the
   registered series itself, taken as **the larger of two bootstraps**: an independent one, and a stationary block one
   (Politis and Romano; mean block 5 observations); seed 0. A short series can understate its own variance by chance,
   through its sample autocorrelations, in either bootstrap; the larger threshold holds the rate under both. So under
   the registered distribution, a sleeve sees a false alarm in at most about one year in twenty.
4. **Recorded beside it, information only:** the median number of observations to an alarm if the edge has gone
   (the series re-centred on 0; `edgewatch.delay`).
5. A sleeve whose registered mean is not positive has nothing to watch, and the rule refuses it.

## What an alarm does

| class (research/LIVE_LATENCY.md) | first alarm | second alarm |
|---|---|---|
| **live-from-tape** (auto-only) | the sleeve's size **halves at once**, and the operator is called | **flat**, absorbing until a new number says why it may resume |
| **operator-paced** | the operator is called; the sleeve runs at **half size** until they answer; they may choose flat; **silence halves** | **flat**, absorbing |
| next-day-batch, not tradable live | not traded live, so the rule never acts | — |

- The factor reaches the risk gate through the sleeve's scale (`edgewatch.scale`: 1, then 0.5, then 0), beside #63's
  drawdown state and the ladder's rung. The gate applies the product, so **the smaller scale wins**. The rule never
  raises a size, and nothing restores a halved size except a new numbered document.
- **Information only on the paper twin and testnet rungs; binding from the mainnet canary on**
  (`edgewatch.binding`). On the canary a binding alarm is a breach of the block (research/DEPLOYMENT_LADDER.md).

## Distinct from #63

#63 asks how deep the sleeve's loss is from its own peak. This rule asks whether the sleeve's mean is still the one it
was registered with. Each acts on its own evidence; neither replaces the other, and the risk gate's day and week stops
(research/RISK_POLICY.md) are a third, account-wide layer on calendar windows.

## Power, from synthetic data only, information only

Run on simulated sleeves before any real series exists: 150-observation verdict windows that passed t ≥ 3, then a
year of 365 observations. These are synthetic numbers, not any forward ledger's.

| true mean / sd | tails | h | median delay if the edge is gone | false alarms a year, live draws from the true distribution |
|---|---|---|---|---|
| 0.25 | normal | 21.0 | 110 observations | 5.2 % |
| 0.25 | t, 3 df | 19.5 | 109 | 7.8 % |
| 0.35 | normal | 17.0 | 81 | 1.8 % |
| 0.35 | t, 3 df | 20.5 | 120 | 1.8 % |
| 0.50 | normal | 12.0 | 38 | 8.8 % |
| 0.50 | t, 3 df | 11.1 | 36 | 19.0 % |

What it shows, said now so it is not discovered later:

- **The 5 % holds when the live mean is the registered one.** With heavy tails, a 150-observation window
  under-represents them, and the realised rate can run a few points high.
- **The winner's curse raises the alarm rate.** A window selected for passing t ≥ 3 overstates its mean. In the 0.50
  rows the window read 0.52 to 0.55, and a live mean 5–10 % below the registered one alarmed in about a tenth to a fifth
  of years. That is the rule working as written: a live edge smaller than the registered one is "not the registered
  edge". It is also why the first alarm halves and only the second flattens.
- **A block bootstrap alone was tried first and set aside before this commit:** on one synthetic 150-observation
  series it understated the variance by chance and alarmed in 23 % of fresh independent years; the larger of the two
  thresholds is what this document registers.
- **A vanished edge is seen in tens to a hundred observations,** fewer when the registered edge was large.

## Outcomes

There is no PASS or FAIL. For each sleeve, its sizing document records `μ0`, `σ0`, `k`, `h`, the observations a year,
the false-alarm rate and the median delay, all computed once from its verdict series. From the canary on, every
observation updates `S`, and every alarm is journaled with its action. A rule that is never traded live is never
watched.

## What it cannot do

It cannot raise a size, re-tune `h` after a live observation, un-halve a sleeve, or watch a sleeve before its verdict.
A different threshold, false-alarm rate or statistic is a new number.

## Robustness, information only

The six readouts of research/ROBUSTNESS_STANDARD.md do not apply: there is no return series of its own, no
configurations, nothing fitted, no signal and no weights. The block is printed with those reasons. Its own statistics
are the table above.

## Timestamp

This file's SHA-256 is stamped with OpenTimestamps (`research/PREREGISTRATION_EDGEWATCH.md.ots`,
`scripts/timestamp.sh`) at the commit that adds it, before any sleeve exists.
