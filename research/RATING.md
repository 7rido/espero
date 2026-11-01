# `espero rate` — the fixed rule behind the 1-10 rating (#50)

**Written 2026-10-31, before the model was fitted or any result seen. It is a measurement and a description, not a
strategy, and it claims no edge.** This repo's tests have found little predictive power, so most ratings may rest on
nothing. The rating moves with the lean anyway, at the operator's request, and says `UNPROVEN` when the lean has no
track record. It is a statistical read on a symbol, not advice. It does not know anyone's position, and it places nothing.

## The rule

- **Scale:** 1 = strongly down, 10 = strongly up.
- **Horizons:** 1, 7 or 30 calendar days. Default 7.
- **Label:** the first close on or after `h` calendar days later is above the signal day's close. A tie is not up.
- **Model:** one ridge logistic per asset class and horizon. Intercept unpenalised, penalty `0.01 × rows`, features
  standardised on the training rows and clipped at ±5. No tuning.
- **Pool:** crypto is `trend.MAJORS` and `trend.ALT_COINS`; stocks and ETFs are `trend.CLASSES`' other members. Either
  pool adds any requested symbol of its class.
- **Features, from closes up to the signal day:** 7, 28, 91 and 364-day log returns and the log distance from the 20, 50
  and 200-day SMAs, each scaled by 60-day volatility over its own span; RSI 14; log 60-day volatility; drawdown from the
  364-day high.
- **Rating from P(up):** under 30% = 1, 30-35% = 2, 35-40% = 3, 40-45% = 4, 45-50% = 5, 50-55% = 6, 55-60% = 7,
  60-65% = 8, 65-70% = 9, 70% and over = 10.

## The warning

Out-of-sample skill is Brier skill against each training window's own base rate, over 6 expanding purged walk-forward folds
(`factor_eval.purged_walk_forward`, `horizon = h`, embargo 5, at least 365 training dates). Its 95% CI is a moving-block
bootstrap of dates, block length `h`, 2,000 draws, seed 50.

`UNPROVEN` shows unless the CI's lower end is above zero. Above zero means "beat the usual rate in past tests". It is not
evidence of profit, and three horizons on two classes mean six looks, so one clearing by chance is possible.

**The pool has survivors only.** Crypto is fitted on coins Hyperliquid still lists, 35 of 42 on 2026-10-31, and
Hyperliquid's daily bars start in August 2020. That flatters crypto's history, and the report says so.

## Not in the number

Funding, liquidations and the order book appear as current readings only. No usable history exists here to test them, so
any weight would be invented. They can enter only through a new registered test.

## The window it may not read

Until 2027-03-31, fitting, skill and the same-state counts use only outcomes dated before 2026-10-30, so nothing overlaps
the frozen forward tests. The prediction itself uses the latest closed bar. It reads no forward folder, ledger, book
database or `health.json`, nor `data/aggr/holdout/`.

## How it is checked

Each run records one row per symbol, signal day and horizon in `data/rate/ratings.csv`. `espero rate --scorecard` compares
due ratings with what happened. Ratings taken close together on related symbols are not independent, so its counts overstate
the evidence. Features, bands and this rule do not change after seeing skill: a change is a new document and a new number.

## First results, 2026-10-31: no cell beat the usual rate

| class | horizon | Brier skill | 95% CI | reading |
|---|---|---|---|---|
| crypto | 1 day | -0.29% | -0.77% to +0.18% | no better |
| crypto | 7 days | -2.06% | -4.07% to -0.21% | **worse** |
| crypto | 30 days | -3.08% | -8.92% to +1.73% | no better |
| stocks and ETFs | 1 day | +0.08% | -0.13% to +0.28% | no better |
| stocks and ETFs | 7 days | -0.61% | -1.03% to -0.22% | **worse** |
| stocks and ETFs | 30 days | -1.90% | -3.08% to -0.70% | **worse** |

**So every rating today is `UNPROVEN`, and three of six cells did worse than simply quoting the usual rate.** A rating
tells the operator what these features looked like, not what comes next. The rule stays as written: the operator asked for
the rating to move anyway. Trying other features until a cell clears would be a new test on a spent sample.

## Corrections made after the first real runs

Both were bugs, seen only after results had been printed. Features, bands and penalty did not change.

- **The label** used the last close on or before `h` days later, so at 1 day a stock's Friday was compared with itself and
  could never be up. SPY's usual rate read 43%. It now uses the first close on or after.
- **Rate limits** made Hyperliquid drop a varying number of coins from the pool, so one coin's rating changed between runs.
  It now fetches two at a time and retries failures once, and the report says how many symbols were fitted.

The report also now says when a rating sits below the symbol's usual rate. SPY reads 7/10 at 56% against a usual 61%:
a 7 there means below usual, because the pooled model gives every symbol the same intercept.
