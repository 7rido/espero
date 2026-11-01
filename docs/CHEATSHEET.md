# Cheatsheet

Everything runs from the project folder:

```bash
cd "/Users/fredp/Espero Trading QuantBot/espero"
```

## The one command you actually need

```bash
.venv/bin/espero          # the home screen: status on top, arrow-key menu below
```

Every menu item is one of the commands in the drawers below; the two most useful without the menu:

```bash
cat health.json          # did this morning's run work? last_success, per-step ok/error/equity
open dashboard.html      # what the accounts hold, their equity curves, and what the trades cost
```

The bot itself needs nothing from you. launchd runs it every day at 07:30.

## Pause / resume / is it alive

```bash
touch KILL                                                       # pause everything (marks too)
rm KILL                                                          # resume
launchctl print gui/$(id -u)/com.espero.daily | grep 'last exit'  # 0 = last run was fine
tail -30 ~/Library/Logs/espero/daily.log                         # what happened, in order
```

## Drawer 1: the paper accounts (hand-driving)

Always use a throwaway `--state` file for experiments. The real ones are `tsmom.db` and `xs.db`
in this folder, and every row written to them is part of the track record.

```bash
.venv/bin/python -m espero tsmom --state /tmp/t.db --cash 1000 --force   # monthly cross-asset trend, rebalance now
.venv/bin/python -m espero xs    --state /tmp/x.db --cash 1000 --force   # weekly top-10 crypto, rebalance now
.venv/bin/python -m espero tsmom --deposit 500                           # add paper capital to the REAL account
.venv/bin/python -m espero tsmom --report                                # history of the real account
.venv/bin/python -m espero dashboard --open                              # rebuild the dashboard now
.venv/bin/python -m espero daily --dry-run                               # preflight: no network, no changes
```

## Drawer 2: research

```bash
.venv/bin/python -m espero matrix                     # the audit table (timing x fees x sizing) on BTC
.venv/bin/python -m espero backtest --fee-bps 60      # one configuration of the bar strategy
.venv/bin/python -m espero factors                    # rank-IC table of the factor zoo, 42 coins
python research/multifactor.py                        # hypothesis #8, exactly as pre-registered
./scripts/check.sh                                    # tests + audit table + CLI smoke test
```

A new idea gets a `research/PREREGISTRATION_<name>.md` committed **before** its script runs, then a
`RESULTS_<name>.md`. No exceptions; that discipline is the product.

## Drawer 3: the fast screen (resting orders, semi-automatic, paper)

```bash
.venv/bin/python -m espero fast --product ETH-USD                 # live Coinbase book, paper fills
.venv/bin/python -m espero fast --product ETH-USD --venue binanceus --record   # charge Binance.US maker, record the book
.venv/bin/python -m espero fast --replay data/book/ETH-USD_2026-10-27T1200.jsonl --speed 20
```

The machine proposes a post-only order with the evidence beside it (signal inputs, measured edge vs
cost, regime, whether the signal is working lately). Nothing is placed until **Enter**. `n` declines,
`r` reprices to the touch, `c` cancels, `j` writes a journal note, `k` kills, `q` quits. Fills and
notes go to `fast.db` with the "why" as it stood at decision time.

## Drawer 4: the single-coin bar strategy (original bot, loses after fees)

```bash
.venv/bin/python -m espero paper --state paper-books/p.db --loop --interval 60              # BTC-USD, $500, hourly
.venv/bin/python -m espero paper --product ETH-USD --state paper-books/p-eth.db --loop      # another coin, own state
.venv/bin/python -m espero paper --venue perp --granularity 300 --state paper-books/p-perp.db --loop  # perp fees + 8h funding
.venv/bin/python -m espero paper-compare paper-books/paper-5m-fees.db --granularity 300     # same bars, every venue's bill
```

Kept because its journal loop is the template for the live path. Not scheduled, not a basket.

## Drawer 6: degen altcoins, 打板 (hypotheses #10 and #13, both failed; command line only)

No longer in `espero ui`: the breakout chase lost before fees on every venue and in every window
(`research/RESULTS_DEGEN.md`, `RESULTS_DEGEN2.md`), so its menu slot went to the carry screen. The
commands stay for reruns.

```bash
.venv/bin/python -m espero degen scan                                   # who is breaking out now: Hyperliquid perps, its fees
.venv/bin/python -m espero degen backtest                               # last 17 days of Hyperliquid 5m bars, every venue's fees
.venv/bin/python -m espero degen paper --loop                           # the live 5m paper loop on Hyperliquid -> degen-hl.db
.venv/bin/python -m espero degen backtest --source coinbase --days 30   # Coinbase spot, as the pre-registered #10/#13 runs
.venv/bin/python -m espero degen paper --source coinbase --venue binanceus --state degen.db --loop   # #10's forward book
.venv/bin/espero fees            # your real Coinbase maker/taker rates (Exchange API key with "view", in .env)
.venv/bin/python -m espero degen paper --venue coinbase --fee-bps 40 --state degen-coinbase.db --loop   # at your own rate
```

Top 60 Hyperliquid perps by 24h volume (Coinbase spot with `--source coinbase`; BTC and ETH left out), new 4h high on a 2-sigma volume spike, stop 2 ATR, trail
2.5 ATR, target 3 ATR, time stop 3h, three slots. Rules and pass criteria are frozen in
`research/PREREGISTRATION_DEGEN.md`; the loop refuses to start twice on one journal. The 30-day
backtest **failed** before fees (`research/RESULTS_DEGEN.md`): use the scan as a view, not the loop as a plan.

## Drawer 7: funding carry on Hyperliquid (hypothesis #11, paper)

```bash
.venv/bin/python -m espero carry screen                                 # #12 on one screen: loops, books, funding vs the bar (also in espero ui)
.venv/bin/python -m espero carry scan                                   # what perp shorts are being paid right now, top 20 by OI
.venv/bin/python research/carry.py fetch                                # funding since 2023, perp and spot candles -> research/data/carry
.venv/bin/python research/carry.py run                                  # #11: one replay, the five criteria, the verdict
.venv/bin/python research/carry.py run2                                 # #12: swap gap + maker execution, with ablations
./scripts/install-carry-launchd.sh                                      # #12's two forward books under launchd: restart if they die
./scripts/install-carry-launchd.sh --status                             # running? (--uninstall stops and removes both)
.venv/bin/python -m espero carry paper --costs maker --state carry-maker.db --loop   # one book by hand (stop launchd's first)
.venv/bin/python -m espero carry status --state carry-maker.db          # equity, funding, fees, open and closed hedges
.venv/bin/python -m espero hl account 0xYourAddress                    # testnet account view, read-only (or HL_WALLET_ADDRESS in .env)
.venv/bin/python -m espero hl order ETH sell 0.01 2400                  # one resting TESTNET order (ALO: maker only)
.venv/bin/python -m espero hl orders                                    # open testnet orders and fills; --cancel ETH 123
.venv/bin/python -m espero carry paper --costs maker --state carry-maker.db --loop --execute-testnet   # mirror the perp leg on testnet
```

Short the perp, hold the same spot, collect the funding longs pay. Enter above 15% annualised on
the trailing week, exit below 5% or after 30 days, five coins at most, 1x, half the capital on each
leg. Rules and criteria are frozen in `research/PREREGISTRATION_CARRY.md`; the result is in
`research/RESULTS_CARRY.md` (**#11 FAIL**: hedge clean, fees took half the funding). #12 adds a 5-point
swap gap, a 7-day minimum hold and maker fees and **passes, provisionally**, pending a 30-day forward
test (`research/RESULTS_CARRY2.md`). That forward test started 2026-10-28 01:00 UTC on `carry-taker.db`
and `carry-maker.db` (same funding, #11 and #12 costs) and ends 2026-11-27; the gap between the two
books is what execution is worth.
Hyperliquid excludes US persons: paper only, and a pass would mean finding a venue the account can use.
Development runs against the testnet (`HL_NETWORK=testnet` in `.env`, UI and faucet at
app.hyperliquid-testnet.xyz); market data always comes from mainnet. The **only** signing code is
`espero/hl_exchange.py`, testnet-only by construction: it needs `HL_NETWORK=testnet`,
`ESPERO_ALLOW_HL_TESTNET=1` and `HL_PRIVATE_KEY` (a dedicated testnet API wallet), builds on the
testnet URL constant and refuses any mainnet URL. `--execute-testnet` shadows the maker book's perp
leg with real resting (ALO) orders so the fill rate #12 assumed can be measured. Mainnet signing is
not implemented.

## Reading the market (#51-#57, research/OPERATOR_READOUT.md)

```bash
.venv/bin/python -m espero readout                                     # what usually follows, and what orders cost; not signals
```

Also on the dashboard, and in the home screen's menu.

## The 1-10 rating (#50, research/RATING.md)

```bash
.venv/bin/python -m espero rate BTC SPY                                 # 1 = strongly down, 10 = strongly up, 7 days ahead
.venv/bin/python -m espero rate ETH --horizon 1                         # also --horizon 30
.venv/bin/python -m espero rate AAPL --stock                            # a name the repo doesn't know needs --stock or --crypto
.venv/bin/python -m espero rate --scorecard                             # how past ratings turned out
```

**Read the warning line.** On 2026-10-31 no horizon beat the symbol's usual rate on past data, and three of six did worse,
so every rating says UNPROVEN: it describes the chart and is not a forecast. Compare it with the usual rate it prints: stocks
rise more often than they fall, so a 7 can be below usual. Funding, liquidations and the book are current readings and never
move the number. Not advice, and it places nothing.

## Drawer 8: the signal board, multi-asset trend (hypothesis #15, scanner)

```bash
.venv/bin/python -m espero board                                        # 1/3/12-month trend: stocks, bonds, commodities, BTC/ETH/SOL, alts
.venv/bin/python -m espero board --alts                                 # every altcoin on its own row
.venv/bin/python -m espero board --carry                                # plus Hyperliquid funding right now (#12's market)
.venv/bin/python research/trend.py                                      # #15's one run, offline from data/trend/
```

For each asset: ▲/▽ against its close 1, 3 and 12 months ago, how that compares with Monday's
reading, and the nearest price that would flip a lookback at the next one. Read-only: prices go to a
temporary cache and `mf.db`/`carry-*.db` are read from copies. **#15 FAILED** its pre-registered test
(`research/RESULTS_TREND.md`): trend timing cut drawdowns but added no return beyond sizing positions
by volatility, so the board shows no sizes and sends no alerts. "stale" means Yahoo has not posted
yesterday's bar yet (it sometimes drops the bar that just closed for a few hours after 00:00 UTC).

## Drawer 9: Hyperliquid as the crypto price source (since 2026-10-29)

```bash
.venv/bin/python -m espero scan                                         # signals from Hyperliquid candles (--source coinbase for the old feed)
.venv/bin/python -m espero fast --product LTC-USD                       # Hyperliquid book and prints, fills at its 1.5 bps maker fee (paper)
.venv/bin/python -m espero hl account                                   # testnet account; a unified account's margin is its spot USDC
```

Crypto prices for the live tools come from Hyperliquid's mainnet perps: the scan, the fast screen,
the board's coins, the XS account and #8's shadow book (`mf-hl.db`). Paper only: Hyperliquid's
mainnet excludes US persons. It lists 35 of the 42 coins (not MKR, YFI, XTZ, EOS, KSM, VET, THETA);
SHIB trades as kSHIB, per 1,000 coins, and is converted back. #8 itself stays on Yahoo, frozen.
For research, `panel.build_hyperliquid(coins, days, granularity)` gives daily bars from August 2020
or hourly bars for the last ~208 days. Details: research/ERRATA.md, 2026-10-29.

## Drawer 5: live money. Off.

`espero live` is experimental and needs `.env` keys, `ESPERO_ALLOW_LIVE=1` and `--confirm-live`
before it sends anything. Leave this drawer shut; see the README section before opening it.

## Where things are

| what | where |
|---|---|
| account state, dashboard, health | this folder |
| logs | `~/Library/Logs/espero/daily.log` |
| the launchd job | `~/Library/LaunchAgents/com.espero.daily.plist` |
| remove the job | `./scripts/install-launchd.sh --uninstall` |
| #12's carry loops | launchd agents `com.espero.carry-taker` and `com.espero.carry-maker` (maker mirrors to testnet) |
| their logs | `~/Library/Logs/espero/carry-taker.log`, `carry-maker.log` |
| stop them | `./scripts/install-carry-launchd.sh --uninstall` |
| full operating procedure | `docs/RUNBOOK.md` |
