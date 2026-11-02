# espero

A small, honest crypto research harness: causal indicators, next-bar fills, and tests that fail
the moment you cheat.

## Why this exists

I inherited a 12,000-line trading bot. It looked complete — data layer, risk manager, order manager,
ML ensemble, paper trading. It had never placed a trade. The live path had no exchange client wired
into it, both entry points called methods that didn't exist, the only real order code talked to an
API Coinbase shut down in 2023, and the backtester filled at the *open* of the bar whose *close*
produced the signal.

That last bug was worth 38 percentage points of imaginary return. ([Full audit](docs/AUDIT.md).)

This repo is what was left after deleting everything that couldn't be trusted: one honest backtest
loop, four strategies, and a test suite whose job is to make the same mistakes impossible.

## What it does

- **Causal indicators** — 20/50 SMA, RSI(14), Bollinger(20, 2σ), MACD(12, 26, 9), all computed from
  past data only, with a test that proves it by recomputing every value on a truncated series.
- **Two execution models** — `next_bar` (signal at close *i*, fill at open *i+1*) and `same_bar`
  (the original bug), so the size of the look-ahead is measurable instead of assumed.
- **Costs that bite** — per-side fees and slippage from the command line; gaps through the stop fill
  at the open, not at the stop.
- **Numbers pinned in CI** — `tests/test_reference.py` asserts the audit's published figures against
  the committed dataset. Change the engine, and the claims break loudly.
- **Point-in-time features** — funding rates (Hyperliquid, OKX) and prediction-market odds
  (Polymarket CLOB) land in SQLite with two timestamps: when the data is *about* and when it could
  first have been read. `features.attach()` refuses to use a feature that is younger than the bar it
  would explain. The funding-extreme factor is wired into the signal stack and only fires when the
  column exists.
- **Paper trading with a spine** — `espero paper` runs the same signal code against live Coinbase
  candles, fills on the next bar's open (never the bar that produced the signal), writes every
  signal/order/fill/equity mark to SQLite, and resumes the open position after a restart. A risk
  gate sits under the strategy: max 25% of equity per position, 1% risk per trade, daily loss cap.

## Recent changes

- **2026-11-01.** Three forward tests registered before their window opens on 2026-11-05: #58 and #59 (HLP's
  absorbed inventory) and #60 (Hyperliquid's liquidation ladder). Paper books for #58 and #59 and an always-on
  paper trader run under launchd, and home-screen paper books moved from `/tmp`, which macOS clears on restart, to
  `paper-books/`. `espero readout` shows what #51–#57 measured, as context and not as signals.
- **2026-10-31.** `espero rate` (#50), Hyperliquid's market-order costs (#51) and microstructure measurements
  (#52–#57). [FORWARD_FAMILY.md](research/FORWARD_FAMILY.md) (#46) fixes what a forward pass leads to.
- **2026-10-30.** The repo moved to this GitHub account. Added [AGENTS.md](AGENTS.md), fetchable live data
  ([docs/DATA.md](docs/DATA.md)), an optional weekly data release, and Docker. Python 3.10 is now the minimum. A
  generic plan for venues outside the US is in [research/VENUE_NONUS.md](research/VENUE_NONUS.md); the account holder
  checks eligibility and places any order.

## The home screen

`espero` with no arguments opens an interactive screen: the two accounts and the last run's health on
top, an arrow-key menu below (status, dashboard, a no-write preview of what each rule would decide now,
history, run the daily job, deposit, pause, log, the single-coin loop, the forward tests, the research
results with #39/#41's measured costs, the factor table, tests). Needs
the `tui` extra: `pip install -e ".[chart,tui,dev]"`. Everything on the menu is also a plain command.
Paper books started from it are kept in `paper-books/`.

## A 1-10 rating for one symbol

`espero rate BTC SPY` shows how a coin or stock has been moving and rates which way its history leans: 1 strongly down, 10
strongly up, 7 days ahead by default. Each rating shows the chance of a higher close, the symbol's usual rate, and what
happened on past days like today. **On 2026-10-31 no horizon beat the usual rate on past data and three of six did worse, so
every rating says UNPROVEN.** It describes the chart and is not a forecast or advice. Funding, liquidations and the book
appear as current readings and never move the number. `espero rate --scorecard` checks past ratings against what happened.
See [research/RATING.md](research/RATING.md).

## The fast screen

Hypothesis #9b measured hourly reversal in crypto at t = 14 and 4 bps per three hours: a real effect
the size of the bid-ask bounce, which is the market-maker's income, not a forecaster's. So the fast
work in this repo is execution, not prediction. `espero fast` reads Coinbase's public book every
second, simulates resting post-only orders pessimistically (queue position, fills only from prints,
no price improvement), and proposes orders a human confirms with Enter, with the measured edge, the
venue's cost and the signal's recent IC on the same line. Paper only. The book can be recorded and
replayed at any speed, which is how it is tested and practised. Details: `espero/book.py`,
`execution.py`, `fast.py`, and [research/RESULTS_LEADLAG2.md](research/RESULTS_LEADLAG2.md).

## The degen drawer (打板)

One experiment with free rein, hypothesis #10: the Chinese retail playbook of hitting the board.
`espero degen scan` ranks the top 60 Coinbase altcoins by 24-hour volume on a cross-sectional score
of last-hour return, volume surprise and range expansion; a coin that prints a new 4-hour high on a
2-sigma volume spike is a candidate. `espero degen paper` runs that rule on live 5-minute bars with
up to three positions, every stop, trail and target in units of the coin's own ATR (so SOL gets a
wider stop than BTC without anyone choosing it), entries at the next open, the venue's taker fee.
`espero degen backtest` replays the last 30 days through every venue's fees. The rules and the five
pass criteria were committed before any candle was fetched:
[research/PREREGISTRATION_DEGEN.md](research/PREREGISTRATION_DEGEN.md). Paper only, no key.
**Backtest verdict: FAIL**, and not on fees: [research/RESULTS_DEGEN.md](research/RESULTS_DEGEN.md).

## Running unattended

The product is the two paper accounts. `espero daily` marks both, rebalances when each one's calendar
says so, rewrites the dashboard and a `health.json`, and a launchd agent runs it every morning:

```bash
./scripts/install-launchd.sh         # 07:30 local, state in state/, logs in ~/Library/Logs/espero
cat state/health.json                # last_run, last_success, per-step ok / error / equity
touch state/KILL                     # pause everything; rm state/KILL to resume
```

Each step is isolated (a Yahoo failure in one account does not stop the other or the dashboard), a
pid lock prevents overlapping runs, the exit code is non-zero on any failure, and macOS notifications
(plus an optional webhook, `ESPERO_WEBHOOK_URL`) fire on failures and rebalances. The XS account
refuses to rebalance when fewer than 30 of its 42 coins have a fresh close, because a shrunken
universe would silently change the top-10. The whole operating procedure is in
[docs/RUNBOOK.md](docs/RUNBOOK.md).

Other launchd jobs install separately, each with its own script in `scripts/`:

| script | what it runs |
|---|---|
| `install-hlcollect-launchd.sh` | records Hyperliquid's positions, HLP, contexts and 1-minute candles |
| `install-hlbook-launchd.sh` | records the order book |
| `install-carry-launchd.sh` | #12's two carry books |
| `install-hlp-launchd.sh`, `install-hlp2-launchd.sh` | #58's and #59's paper books |
| `install-paper-launchd.sh` | a paper BTC perp on Hyperliquid, which counts toward no verdict |

launchd catches up scheduled jobs after a sleep, but a recorder records nothing while the Mac is asleep, and a gap
stays a gap. `docker compose up` is the alternative on any machine, and on a Mac it has the same gaps. Never point it
and launchd at the same `data/` folder. Setting `ESPERO_PUBLISH_AS` also publishes the live recordings every Monday.

## Live trading — there is none

The repo has no mainnet order path. The Coinbase adapter and `espero live` were removed on
2026-11-01: that path had never been reconciled against a venue, and it served the four original
strategies, which failed their tests. The only code that signs anything is
[espero/hl_exchange.py](espero/hl_exchange.py), on Hyperliquid's **testnet**, for #12's maker
mirror, behind three guards that refuse anything but a testnet URL. A real order is the account
holder's own act, placed outside this repo with their own keys. `.env.example` lists every variable
the repo reads, and none of them can move money.

## What it does not do (yet)

No reconciliation against a venue on boot, no exchange-side stop orders, no funding, no partial
fills. That is deliberate: those belong *below* the strategy layer, and the roadmap adds them with
tests instead of adding them as decoration. See [Roadmap](#roadmap).

## Factor research

`RESULTS_XS20.md` diagnosed why the cross-sectional tests kept failing: one factor, no risk control,
no turnover control, no breadth. The toolkit the cross-sectional shops actually run on is now in the
package, written to this repo's rules (every operator causal and tested, the forward return computed
in one named place, nothing wired into a live account without a pre-registration):

```bash
espero factors                        # rank-IC table of the zoo on the 42-coin panel
espero factors --horizon 10 --names mom_30,rev_3,lowvol_30
python research/multifactor.py        # hypothesis #8, as pre-registered
```

| module | what it is |
|---|---|
| `ops.py` | Alpha101/191 operator dialect: `ts_rank`, `ts_corr`, `decay_linear`, `cs_rank`, `cs_neutralize`, MAD winsorizing |
| `panel.py` | wide OHLCV panel; eligibility dated by history and dollar volume, not by what exists today |
| `factors.py` | twelve signed factors, three literal Alpha101 formulas, a rank-average composite |
| `factor_eval.py` | rank IC, ICIR, t, IC decay, quantile spread, turnover, purged walk-forward, deflated Sharpe, the Harvey-Liu-Zhu t > 3 hurdle |
| `portfolio.py` | vol targeting, weight caps, turnover buffer, ex-ante book vol |
| `tca.py` | per-trade cost, annual turnover and drag, on the dashboard |

What it deliberately does not include: breadth beyond 42 survivors, machine-learned factor weights
(not enough independent observations to fit one honestly), intraday data, shorting.

## Quickstart

```bash
python -m venv .venv && source .venv/bin/activate
pip install -e ".[chart]"          # numpy + pandas (+ Pillow for charts)

espero matrix                      # the audit table on the committed BTC-USD data
espero backtest --fee-bps 60       # one configuration, honest fills
espero chart                       # docs/equity.png
espero paper                       # one step of paper trading on live candles
espero paper --loop --interval 60  # keep it running (ctrl-c to stop)
# without --venue (or --fee-bps) the paper book charges no fees at all; pass --venue binanceus etc.
espero tsmom --cash 100            # cross-asset trend paper account
espero dashboard --open            # one self-contained HTML page with the accounts and the market readout
espero readout                     # what usually follows on Hyperliquid, and what orders cost; not signals

espero fetch ETH-USD --days 1460   # fresh data, no API key needed
espero matrix data/ETHUSD_86400s.csv
```

Run the tests:

```bash
python -m unittest discover -s tests -t . -v
```

Or run the whole CI job locally — the same steps as `.github/workflows/ci.yml`, no hosted runner
needed:

```bash
./scripts/check.sh --install     # first time
./scripts/check.sh               # tests + audit table + CLI smoke test

./scripts/install-hooks.sh       # optional: run the checks on every git push
```

## Running it with an AI agent, LLM or harness

espero is a command-line tool with no keys and no server, so any agent that can run a shell can
drive it. The rules an agent must follow are in [AGENTS.md](AGENTS.md):

- no keys;
- no real orders;
- no re-tuning a committed test;
- no deleting forward data;
- pre-register before computing.

Most harnesses load that file on their own.

| harness | how it picks up the rules | start it |
|---|---|---|
| **Claude Code** (CLI, desktop, IDE) | `CLAUDE.md`, which imports `AGENTS.md` | `cd espero && claude` |
| **Codex CLI**, **Cursor**, **Aider** and other AGENTS.md-aware agents | `AGENTS.md` | open the repo folder in the tool |
| **Any LLM with a shell tool** (Agent SDKs, LangChain, your own loop) | paste `AGENTS.md` into the system prompt | give the tool the repo folder as its working directory |
| **A scheduled agent** (cron, CI) | as above, plus `health.json` as the thing to read | run `espero daily`, then have the agent summarise `health.json` |

**Setup, the same for every harness:**

```bash
git clone https://github.com/7rido/espero && cd espero
python -m venv .venv && source .venv/bin/activate
pip install -e ".[chart,tui,dev]"
./scripts/check.sh                     # must pass before an agent changes anything
```

**Data.** The clone has only the small frozen datasets that CI needs. `./scripts/fetch-data.sh live`
gets the maintainer's live recordings (~20 MB, from the latest release). `./scripts/fetch-data.sh
archives --no-oi` gets the public history (~1.6 GB). AGENTS.md tells an agent which one a task needs
and why. [docs/DATA.md](docs/DATA.md) has the details.

**What to give the agent.** Use `.venv/bin/espero <command>` (`espero --help` lists them), not the
interactive `espero ui`, which needs a real terminal. Allow it to run shell commands and edit files
inside the repo, and nothing else. It needs no network credentials. Every data source here is a
public endpoint.

**Prompts that work well:**

- "Run `./scripts/check.sh` and tell me what fails."
- "Read `health.json` and the `research/FORWARD_*.md` plans. Which forward tests have events so far?
  Don't judge any of them."
- "I have an idea: _…_. Write the pre-registration for it as the next test number, following
  AGENTS.md, and stop before computing anything."
- "Run the pre-registered test #NN exactly as written and write its RESULTS file."
- "Paper-trade BCH on Hyperliquid prices for a day:
  `espero paper --product BCH-USD --source hyperliquid --loop`."

**What an agent can't do here, by design.** It can't place an order on any real venue. It can't
read a key. It can't move a test's goalposts once committed. Those limits are in the code
(`hl_exchange.py` refuses anything but testnet) and in the tests, not only in the prompt.

## One factor, tested honestly

Funding-rate extremes looked like an edge: on Hyperliquid BTC, funding below z = −2 was followed by
+0.585% on the next day (63% hit, n = 60), and the same rule on ETH returned +28% over the 2025–26
holdout while holding lost money.

Then the longer history arrived. On Deribit's seven years of funding (2019–2026), the identical rule
produced **25 trades, +17.2%, t = 0.91** — no evidence of edge — and the selection period before the
holdout showed nothing at all.

The full write-up, including why a fixed z-threshold cannot be shared across venues (Deribit's funding
std is 8× Hyperliquid's), is in [research/FINDINGS.md](research/FINDINGS.md). The short version: it
was a regime, not a law, and it is not traded by anything in this repo.

A second hypothesis — cross-sectional momentum, [pre-registered](research/PREREGISTRATION.md) before
the data was touched — did the same thing from the other direction: +115% CAGR in the design period,
then **−29.75% CAGR on the holdout** against +23.3% for buying BTC. Two hypotheses, two honest
failures, both written down: [research/RESULTS.md](research/RESULTS.md).

The third failed too (Polymarket liquidity provision — rewards don't cover inventory:
[research/LP_NOTES.md](research/LP_NOTES.md)).

The fourth **passed**: cross-asset time-series momentum over SPY/TLT/GLD/USO/BTC/ETH, pre-registered
before its data was fetched. On the 2021–2026 holdout it returned +7.26% CAGR with a **−8.15% max
drawdown against −14.56%** for equal-weight — less money, much less pain, including +1.6% in 2022 when
long bonds fell 30%. The paper is [here](research/RESULTS_TSMOM.md). It is a drawdown-control result,
not an income one, and the Sharpe margin (1.08 vs 1.02) is inside noise.

The fifth, PEAD on 60 large caps with SEC timestamps, **failed**: −1.64% CAGR and Sharpe −0.05 on the
holdout against SPY's +13.4% and 0.84 — it lost in the design period too. 5,351 filings, a clean
point-in-time design, and no edge in the most scrutinised pond on earth:
[research/RESULTS_PEAD.md](research/RESULTS_PEAD.md).

The sixth, crypto-policy odds as a composite signal, **failed** too: Spearman +0.024 across 422
observations, and the top-vs-bottom quintile spread ran the wrong way. The design period turned out to
be empty — Polymarket's history for these markets starts in December 2023 — which is a flaw in how the
periods were set: [research/RESULTS_ODDS.md](research/RESULTS_ODDS.md).

The seventh, top-5-of-21 crypto momentum, was exploratory by construction (its window was already
contaminated) and showed that selection added nothing over equal weight:
[research/RESULTS_XS20.md](research/RESULTS_XS20.md).

The eighth, the first built from the factor stack — a rank-average of 30-day momentum, 3-day reversal
and low volatility, top 10 of 42, vol-targeted to 20% and turnover-buffered — **passed** all four
pre-registered criteria on its (weakened) holdout: +16.9% CAGR, Sharpe 0.92, −24% max drawdown
against BTC's +10.7%, 0.45, −53%. The information-only decomposition says what kind of pass it is:
ten coins chosen *alphabetically* with the same construction already beat BTC on Sharpe and
drawdown, the extra return comes from the low-vol factor, and momentum contributes nothing. The IC
criterion was met by a composite whose mean quantile spread is *negative*, a flaw in the criterion as
written that the results file records: [research/RESULTS_MF.md](research/RESULTS_MF.md).
Its six-month forward paper test runs from 2026-11-02 to 2027-05-03 in `espero mf` (`mf.db`, part of
`espero daily`), with pass criteria fixed before the account existed:
[research/FORWARD_MF.md](research/FORWARD_MF.md).

The ninth, BTC lead-lag into altcoins on hourly bars, failed twice: once by construction (the
unscaled gap has the same ranks as plain reversal, caught before any data was fetched) and once on
the data (the beta-scaled version does not beat reversal, and the 4 bps spread is the bid-ask bounce):
[research/RESULTS_LEADLAG2.md](research/RESULTS_LEADLAG2.md).

The tenth, 打板 altcoin breakout chasing on 5-minute bars, failed on the data: 180 trades in 30 days,
28% hit rate against a 40% break-even, and a loss *before fees*. Half the stops were gaps on the bar
after the fill: the 2-sigma volume bar is the climax, and the rule buys it. The scanner stays; the
rule does not: [research/RESULTS_DEGEN.md](research/RESULTS_DEGEN.md).

The eleventh is the first that does not predict anything: delta-neutral funding carry on Hyperliquid
(short the perp, hold the spot, collect what longs pay). The hedge held (1.5% max drawdown, funding
paid 4% of funding received) and the income was real, but fees took 55% of it, mostly from the
rule's own churn, and the 2023–24 premium regime that would have cleared the bar is gone: +5.2%
annualised against the 8% required, −7% on Kraken fees. FAIL, closest of anything since #8:
[research/RESULTS_CARRY.md](research/RESULTS_CARRY.md). `espero carry scan` stays as the view of
what shorts are being paid today; development against Hyperliquid runs on its testnet
(`HL_NETWORK=testnet`, UI at app.hyperliquid-testnet.xyz), market data from mainnet, and nothing
in the repo signs an order there.

The twelfth is #11 with the two fixes its post-mortem named, pre-registered as post-hoc: swap a
held coin only for one paying 5 points more and only after a week, and rest maker orders on both
legs. Swaps fall from 55 to 6, fees from 3.15% to 0.14% of equity, and the rule clears all five
criteria: +10.9% annualised, Sharpe 1.77, +6.4% on Kraken maker fees. The pass is provisional on
its own terms (post-hoc, and maker fills assumed at the close) and earns a 30-day forward paper
test, not a conclusion: [research/RESULTS_CARRY2.md](research/RESULTS_CARRY2.md). That test is
running (`espero carry paper`, two books on live hourly funding, one at taker and one at maker
costs, 2026-10-28 → 2026-11-27).

The thirteenth reran 打板 on 1-hour bars, pre-registered with two filters (at most one entry per
bar, and the coin's move must beat BTC's) over a 180-day window #10 never saw: 468 trades, profit
factor 0.90, −$81 on Binance.US fees, still negative before fees. The control without the filters
did no better. FAIL: [research/RESULTS_DEGEN2.md](research/RESULTS_DEGEN2.md). The same day a
replay-clock bug was found in #10's backtest; its FAIL stands, but its gross was about break-even,
not negative ([research/ERRATA.md](research/ERRATA.md)).

The fourteenth ran #12's carry rule, unchanged, on a second venue, Kraken Futures, over the
months before #12's window (2025-10 → 2026-04): six trades, flat, FAIL on four criteria. Kraken's
funding rarely reaches the 15% bar, and when it did the basis took the funding back. In #12's own
months it makes +5.1% a year against #12's +10.9% on Hyperliquid. #12's edge is recorded as
Hyperliquid-only, pending its forward test: [research/RESULTS_CARRY3.md](research/RESULTS_CARRY3.md).

The fifteenth took the published trend rule (Hurst-Ooi-Pedersen's equal-weighted 1-, 3- and 12-month
lookbacks), long/flat, every position sized to the same volatility, across index, bond and commodity
ETFs, BTC/ETH/SOL and an altcoin sleeve, 2018–2026, and asked whether the timing adds anything to the
sizing. It does not: +6.6% CAGR, Sharpe 0.87, max drawdown −14%, against +8.9%, 0.90 and −24% for the
same book always invested. It cut the drawdown beyond the vol-matched book, beat 60/40, and survived
doubled costs, but its excess return over the sizing was −0.4 bps a week (t −0.18). FAIL:
[research/RESULTS_TREND.md](research/RESULTS_TREND.md). Its snapshot also exposed Yahoo ticker
collisions in the crypto universe (ARB, TIA, WLD, OP), recorded in [ERRATA](research/ERRATA.md).
`espero board` shows the rule's trend readings as a scanner, without sizes.

The sixteenth and seventeenth asked why the scan measures every coin against BTC only, and whether
a coin's own peers, or ETH for Ethereum tokens, would lead it better. On a year of Coinbase hourly
bars no test here had seen (2024-10 → 2025-10), neither did: a coin's beta to its leave-one-out peer
basket times the basket's last hour has an out-of-sample IC t of −0.9, and the same with ETH −2.5,
the wrong sign. Both FAIL on all four criteria: [research/RESULTS_PEERS.md](research/RESULTS_PEERS.md).
One-hour reversal replicated on the new year (t 10.7, +4 bps per three hours): the bid-ask bounce
again. The scan keeps BTC as its only leader and says why.

The eighteenth asked whether the liquidations aggr shows can tell a forced breakout from an
organic one. On the 82 free first-of-month days of Binance and Bybit liquidations (2020–2026, 9,212
breaks), breaks made mostly of liquidations faded 11 bps more over the next hour than organic ones,
the predicted direction in every variant, but at t −2.1 against the −3 hurdle, and only in the
second half of the period. FAIL: [research/RESULTS_LIQ.md](research/RESULTS_LIQ.md). Information only:
new 4-hour lows bounced about 18 bps in the next hour, while new highs did not continue.

The nineteenth started from a rule rather than a pattern: Binance's perpetuals settle funding every
8 hours, so when one side pays a high rate, holders who will not pay exit before the instant and
arbitrageurs who collect it enter. Over 266,964 settlements (2020–2026, 42 coins), a coin whose
holders paid at least 0.05% swung 15.5 bps against them around the settlement, relative to coins
with ordinary funding and to the same coin four hours later (t 3.5), in both eras and for both
signs. It is the repo's first confirmed effect, and it is small: no long-only spot trade earned it
after costs. "Real, not tradable": [research/RESULTS_SETTLE.md](research/RESULTS_SETTLE.md).

The twenty-first took the pattern an exploration of aggr's hourly liquidation bars had shown
(April–June 2026: prices came back after a coin's biggest liquidation hours) and tested it once on
four months sealed unread before the exploration began. It did not hold: the reversal across both
sides was +4.8 bps (t 0.3), and it went the other way in July–August. Buying after long-liquidation
spikes made +51 bps a day, in months when the market rose by almost half that anyway. FAIL:
[research/RESULTS_LIQSPIKE.md](research/RESULTS_LIQSPIKE.md).

The twentieth mirrored 打板: buy the new 4-hour **low** on a volume spike instead of the high. On
136,523 breakdowns over six years (2020 → March 2026, the days #18 used left out) it earned +14.8 bps
in the next hour, t 9.8, in every year and on 40 of 42 coins, while buying breakouts lost 6.9 bps. The
strongest effect measured here, and still under the 18 bps bar for one hour: "real, not tradable".
At 4 hours it was +37.8 bps (information only), the lead now worth a test of its own:
[research/RESULTS_LOWS.md](research/RESULTS_LOWS.md).

The twenty-sixth reran #18's rule, unchanged, on Binance's COIN-M liquidation archive: every day from
June 2023 to October 2024 that #18 had not used, 429 days and 35,906 breaks. Breaks made of
liquidations faded 23.6 bps more over the next hour than organic ones (t −4.1), in both halves and
coin by coin, and buying the forced down-breaks earned +23.5 bps an hour (t 7.1). **PASS**: the
first signal here to clear every pre-registered criterion. It now needs a forward test on a live
liquidation feed before anything trades: [research/RESULTS_LIQ2.md](research/RESULTS_LIQ2.md).

The twenty-fifth asked the same question with Binance's open interest as a stand-in for liquidations
(every day 2021 → March 2026): breakdowns where open interest dropped most bounced only 3.2 bps more
(t 2.4), and the gap has faded to below zero since 2025. FAIL:
[research/RESULTS_OI.md](research/RESULTS_OI.md). Open interest does not see which closes were forced.

The twenty-eighth looked for a forced flow on a clock. Leveraged and inverse ETFs must buy after up
days and sell after down days to restore their leverage at the 4 p.m. ET valuation, and the US 2x
bitcoin and ether funds hold billions. Over 596 NYSE days since June 2024, BTC and ETH did not drift
with the day's move in the last 15 minutes before 16:00 (−1.5 bps, t −1.4). FAIL:
[research/RESULTS_LEVETF.md](research/RESULTS_LEVETF.md). The other end of the flow did show, as
information: after the close the session's move reverses, −6.0 bps in 15 minutes (t −5.6), on
trading days and not on weekends, larger on bigger days, in every year since 2024. It is under
costs as a trade and is now a forward test (#29).

The thirtieth changed how a known effect is traded rather than what is predicted. #20's bounce dies
on taker costs, so it rested a maker bid one ATR under each breakdown and sold back at the breakdown
price. On 13,252 breakdowns from April to October 2026, months no breakdown test had used, it earned
+1.7 bps net per fill (t 1.0). FAIL: [research/RESULTS_BIDS.md](research/RESULTS_BIDS.md). It
measured why: the breakdowns that came down to the bid went on to fall 22 bps, while those that
never did bounced 64. Deeper bids, which fill only on capitulation, earned +12.5 to +20 bps net per
fill in every month and on most coins, as information. That lead runs forward as #31.

The thirty-fourth checked the running accounts' own fills. XS and #8 book their Monday fills at 00:00
UTC, a Binance funding settlement. Over 13,089 coin-Mondays (2020–2026) the price drifted +1.1 bps
in the half hour after the fill when funding was ordinary, which it was 93.5% of the time: no bias.
FAIL, and the fill time stays: [research/RESULTS_FILLCOST.md](research/RESULTS_FILLCOST.md). The
bias sits only on coins whose shorts pay hard (1.5%), where the price fell 34 bps after 00:00.

The thirty-sixth tested stop runs: sweeps of yesterday's low that close back above it within 15
minutes. Over 40,785 sweeps on 42 coins (2020–2026) they bounced +15 bps in the next hour, but
sweeps that failed to reclaim bounced more (+19.5 bps), so the reclaim says nothing. FAIL:
[research/RESULTS_SWEEPS.md](research/RESULTS_SWEEPS.md). What is left is #20's mean reversion at
lows, from a second trigger: +39 to +44 bps over 4 hours.

The thirty-seventh asked whether Ethena's USDe flows forecast funding: minting opens Ethena's
shorts, redemptions close them. Over 138 weeks (2024–2026) the raw correlation had the predicted sign
(t −2.2), but it vanished once funding's own level and reversion were controlled (t +0.75). USDe
is minted when funding is high, and high funding falls back on its own. FAIL:
[research/RESULTS_ETHENA.md](research/RESULTS_ETHENA.md).

The thirty-eighth set Polymarket's hourly "Bitcoin Up or Down" crowd against a random-walk binary
option at minute 30. Over 4,297 markets (May–October 2026), betting the model's side when they
differed earned +0.9 cents a share (t 1.0), and the crowd was the better forecaster (Brier 0.1702
against 0.1733). FAIL: [research/RESULTS_POLYHOUR.md](research/RESULTS_POLYHOUR.md). As
information, the same bet at minute 15 earned +4.7 cents (t 4.3).

#39 stopped adding ideas and measured what a fill costs, on 1,004 coin-days of prints (Binance's
archive with a trade-derived mid validated against real quotes, and Hyperliquid via Tardis). A small
taker round trip costs 9.9–11.3 bps, not the assumed 18. Resting orders lose 0.7–2.5 bps to adverse
selection at the back of the queue, before fees, in every one of 288 cells: no condition makes
passive fills pay. #29's reversal does not survive the measured cost; #31 does, on its four majors.
[research/RESULTS_MARKOUT.md](research/RESULTS_MARKOUT.md); the table ships as `espero/costs.py`.

#40 ran the fill-reconciliation plumbing on Hyperliquid's testnet: post-only refusals, fills, fees
and maker/taker flags all reconciled with the exchange's own record (PASS, BTC and ETH; SOL refused
by the testnet's oracle band). It also caught a sizing bug that reconciliation cannot see, now
fixed. [research/RESULTS_TESTNET.md](research/RESULTS_TESTNET.md).

#41 ran #39's measurement on eight coins down the liquidity ladder (DOGE to YFI). No cell pays a
resting order; the back-of-queue loss deepens as coins thin (−0.8 bps on BTC to −4.0 on XTZ, rank
correlation +0.97 with volume). Hyperliquid NO; Binance "not established" by its frozen replication
rule. [research/RESULTS_MARKOUT_SMALL.md](research/RESULTS_MARKOUT_SMALL.md).

#42 rehearsed the real-fill test on testnet across five coins: resting orders, a book recorder,
reconciliation and a position-against-intent check all passed (74 fills, zero breaks).
[research/RESULTS_REHEARSAL.md](research/RESULTS_REHEARSAL.md).

#43 mapped the repo's real signals from 1 hour to 2 weeks. #20's new-low bounce at 12 h passed its
pre-registered confirmation on 2025–26 (+21.8 bps a day-mean), but trade-weighted the same trades
lose 9.6 bps: the day-mean convention gave 50 quiet-day trades the result. Not tradable, and a
warning for every day-mean in this repo. [research/RESULTS_HORIZONS.md](research/RESULTS_HORIZONS.md).

#44 audited the day-mean convention behind most event studies here. All 16 published headlines
reproduced; trade-weighted with day-clustered errors, #35's reversal, #21's long leg and #30's fills
change, #20's bounce shrinks to +5.9 bps, and #26 holds (+19.2 bps, t 3.7). New tests report the
trade-weighted mean. [research/RESULTS_DAYMEAN_AUDIT.md](research/RESULTS_DAYMEAN_AUDIT.md).

#45 is pre-registered and running from 2026-10-30: #26's forced-liquidation bounce held 4 h, 12 h and
1 day on #27's live ledger, net of measured costs and funding, trade-weighted (in-sample +22 to +60 bps,
t 3.6–4.4; forward power about 50–90%). [research/FORWARD_LIQHOLD.md](research/FORWARD_LIQHOLD.md).

#48 built the substrate this repo lacked (point-in-time store, execution simulator, detector calibration, trial
budget, reconciliation) and asked one question: did XS momentum (#2) fail because the signal decayed, or because
its trades were unexecutable? Execution accounts for 0.111 of its shortfall against BTC (95% CI 0.104–0.118) at
$100,000 a leg, so not execution; whether the expected edge decayed, this history cannot say.
[research/RESULTS_SUBSTRATE.md](research/RESULTS_SUBSTRATE.md).

#49 is registered and has not run: whether a day of book imbalance predicts the next day, on sealed entries.
[research/PREREGISTRATION_DEPTHDAY.md](research/PREREGISTRATION_DEPTHDAY.md).

#51 measured what a market order costs on Hyperliquid on 24 first-of-month days. An 18 bps round trip covers $1,000 on all
14 coins. It covers $10,000 on 9 and can't be judged on 5, and covers $100,000 only on BTC, ETH and XRP.
[research/RESULTS_BOOKWALK.md](research/RESULTS_BOOKWALK.md).

#52–#56 measured five patterns on the same days. Binance moved before Hyperliquid by about a second on 142 of 144
coin-days. Premium, book imbalance and large bursts show small effects, below a $1,000 round trip of about 9–12 bps, and
one-sided trading shows nothing clear. [research/RESULTS_PATTERNS.md](research/RESULTS_PATTERNS.md).

#57 asked what's left of Hyperliquid's catch-up to Binance after a delay. Nothing: a $1,000 market order 1 second later,
held 30 seconds, lost 8.02 bps per event after costs (95% CI −8.78 to −7.20), and no delay down to 100 ms came out
positive. [research/RESULTS_CATCHUP.md](research/RESULTS_CATCHUP.md). #51–#57 are summarised for reading the market in
[research/OPERATOR_READOUT.md](research/OPERATOR_READOUT.md).

A study of who absorbs forced liquidations on Hyperliquid stopped before reading any market data, because the order-level
history needs AWS. It has no number, spends no trial and says nothing for or against the mechanism:
[research/RESULTS_HLABSORB.md](research/RESULTS_HLABSORB.md).

#58, #59 and #60 are forward paper tests on what `espero hlcollect` records, registered before their window (2026-11-05
to 2027-03-31). #58 goes long for 4 hours after HLP's net position jumps during a sharp fall, and #59 is the same rule with a
guard that voids only recorded failed reads: [FORWARD_HLP.md](research/FORWARD_HLP.md),
[FORWARD_HLP2.md](research/FORWARD_HLP2.md). #60 goes long for 4 hours after the price falls through a dense band of long
liquidation prices: [FORWARD_LADDER.md](research/FORWARD_LADDER.md).

Scoreboard, from [research/trials.csv](research/trials.csv): 59 tests, #1–#45, 9b and #48–#60. #46 is a rule document,
and #47 is held for a first real-order test. Four signals passed (#4, #8, #12 provisional, #26), two plumbing checks passed
(#40, #42), and #43 passed its confirmation but isn't tradable. Twenty-five failed, including #19 and #20, whose effects are
real but not tradable. Twelve are measurements (#39, #41, #44, #48, #50–#57) and #7 is exploratory. Thirteen forward tests
are running or about to start (#22–#24, #27, #29, #31, #32, #34, #38, #45, #58–#60), and #49 hasn't run. Of the passes, #4
and #8 are risk construction, #12 is income (carry at maker fees) with a forward test still attached, and #26 awaits its
forward tests. No predictive edge has been confirmed forward at any horizon, and across #4, #8 and #15 the one effect that
survives is volatility sizing.

## The numbers

BTC-USD, 2022-10-28 → 2026-10-27, 1,461 daily bars, $10,000, one long position.

| Case | Return | CAGR | Sharpe | Max DD | Trades |
|---|---|---|---|---|---|
| as coded (look-ahead), 2% notional, 10 bps | −0.15% | −0.04% | −0.48 | −0.24% | 11 |
| honest, 2% notional, 10 bps | +0.05% | +0.01% | 0.33 | −0.06% | 7 |
| as coded (look-ahead), full size, 10 bps | **+42.95%** | +9.34% | 0.52 | −42.7% | 43 |
| honest, full size, 10 bps | **+5.23%** | +1.28% | 0.17 | −39.4% | 40 |
| honest, full size, **60 bps** | **−29.07%** | −8.23% | −0.28 | −50.7% | 40 |
| buy & hold | **+289.08%** | +40.45% | — | — | — |

![Equity curves](docs/equity.png)

Same signals every row. The only things that change are when the fill happens and what it costs.

## Design rules

1. **A strategy emits `Signal` objects and nothing else.** It cannot size a position, read the
   account, or call a broker. Everything that can lose money sits below it and is testable offline.
2. **A fill happens after the signal.** There is a test for this, and a second test that pins the
   difference between honest and cheating.
3. **Costs are explicit.** Fee per side, in basis points, on the command line. No hidden 10 bps.
4. **Gaps are real.** If the bar opens through your stop, you get the open.
5. **The published numbers are a test fixture.** If they move, one of us is wrong.

## Layout

```
espero/
  espero/
    data.py         # Coinbase/Yahoo/FRED fetches with retries and a cached fallback
    indicators.py   # causal SMAs, RSI, Bollinger, MACD
    signals.py      # four strategies + weighted combiner (pure functions)
    backtest.py     # one position, one bar at a time, two fill models
    journal.py      # SQLite: bars, signals, orders, positions, equity
    risk.py         # pre-trade gate: size, exposure, daily loss cap
    paper.py        # simulated loop: closed bar -> signal -> next-bar fill -> journal
    broker.py       # reads .env (load_env); named from the order adapter it held until 2026-11-01
    tsmom.py        # monthly cross-asset trend paper account
    xs.py           # weekly cross-sectional crypto paper account, degraded-universe guard
    cash.py         # where idle cash lives, and why
    runner.py       # `espero daily`: tsmom -> xs -> dashboard -> health.json, lock, notifications
    notify.py       # macOS notification + optional webhook
    dashboard.py    # static HTML, with TCA per account
    ops.py          # Alpha101/191 operators, causal
    panel.py        # wide panel + dated eligibility
    factors.py      # the factor zoo
    factor_eval.py  # rank IC, purged walk-forward, deflated Sharpe
    portfolio.py    # vol targeting, caps, turnover buffer
    tca.py          # transaction cost analysis
    report.py       # the matrix table and the equity chart
    ui.py           # the home screen
    rate.py         # `espero rate`, the 1-10 rating (#50)
    hlcollect.py    # records Hyperliquid's positions, HLP, contexts and candles
    hlbook.py       # records Hyperliquid's order book
    hlpbook.py      # #58 and #59's rule and paper books
    ladder.py       # #60's ledger, which refuses to read the recordings before the window closes
    trials.py       # the trial budget behind research/trials.csv
    cli.py          # every command; `espero --help` lists them
    ...             # one module per test or account (liqhold.py is #45)
  tests/            # over 1,000 tests
  deploy/launchd/   # the LaunchAgent templates; the scripts/install-*-launchd.sh scripts render them
  Dockerfile, docker-compose.yml  # the collector and the daily job as two services
  research/         # one pre-registration and one results file per hypothesis; INDEX.md lists every file by test
  data/             # committed BTC/ETH daily candles so the numbers reproduce offline
  docs/AUDIT.md     # the audit that started this
  docs/AUDIT_2026-10.md  # the second audit: what broke on a bad day, and the factor stack
  docs/RUNBOOK.md   # install, check, pause, recover
```

## Roadmap

- [x] Causal indicators + honest backtester + reference tests
- [x] Walk-forward split with a purge gap; report out-of-sample only (`factor_eval.purged_walk_forward`)
- [x] Position sizing as risk: vol targeting and caps (`portfolio.py`), not yet wired to a live account
- [x] SQLite journal: bars, signals, orders, fills, positions, equity
- [x] Restart-safe paper trader on live candles, with a pre-trade risk gate
- [x] Broker interface behind one protocol, with `client_order_id` idempotency
- [x] Live path with dry-run, kill switch, notional cap and daily loss limit
- [ ] Reconciliation against a real venue on boot
- [ ] Exchange-side stop orders (so the stop survives a crash)
- [ ] Kill switch: daily loss cap, max open risk, max orders/minute
- [x] TCA report per paper account (`tca.py`, on the dashboard)
- [x] Scheduled run with health file, lock and notifications (launchd on a Mac, Docker anywhere)
- [x] Retrying HTTP with a cached fallback; degraded-universe guard
- [ ] Dated listing/delisting file, so survivorship can be measured instead of disclosed
- [x] Forward paper account for hypothesis #8 (`espero mf`, 2026-11-02 → 2027-05-03)

The gate for live money is not "it backtests well". It is: two weeks of paper at zero duplicate
orders, a restart mid-position that reconciles to the cent, and out-of-sample results that survive
your actual fee tier.

## Docs

- [docs/AUDIT.md](docs/AUDIT.md) — the original audit: what was broken, how it was measured, and the
  30-day plan this project is executing.
- [docs/AUDIT_2026-10.md](docs/AUDIT_2026-10.md) — the second audit: ten findings, five money bugs
  fixed, the deployment gaps closed, and what a factor shop would add.
- [docs/RUNBOOK.md](docs/RUNBOOK.md) — running it unattended: launchd on a Mac, or Docker anywhere.
- [docs/DATA.md](docs/DATA.md) — getting the data: what's committed, what each script downloads,
  and what can only be recorded live.
- [docs/CHEATSHEET.md](docs/CHEATSHEET.md) — the two commands you need, and the drawers you don't.
- [research/FORWARD_FAMILY.md](research/FORWARD_FAMILY.md) — what a forward test's pass leads to.
- [research/VENUE_NONUS.md](research/VENUE_NONUS.md) — venues for an account holder outside the US.

## License

MIT. Research and education only. Not financial advice; this software can lose money, and the
default configuration will.

Closes nothing automatically, promises nothing, and has no opinion about what happens next.
