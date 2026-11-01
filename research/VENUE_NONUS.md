# A venue for a non-US account holder — the plan (nothing is placed)

**Committed 2026-10-31.** Written on 2026-10-30, after the user stated that the account holder
is a non-US resident. The holder's country is not recorded here. [VENUE_CONFIRMATION.md](VENUE_CONFIRMATION.md)
planned for a US holder; this is its counterpart. Like that note, it places nothing. **The repo's
order path does not change:** `hl_exchange.py` signs on Hyperliquid's testnet only, `live.py` stays
off, and every real order is the account holder's own act.

## Step zero — eligibility, checked by the holder

Before anything else, the holder confirms against **each venue's current terms page** that their
country of residence is permitted. Every venue below restricts some countries, and the lists
differ and change. The holder also confirms their own country's tax and licensing rules for
perpetual futures. Neither check is made here, and nothing below applies to a venue until both are
done for it.

**The operator is the holder.** The holder runs the process, on their own machine, with their own
keys. A US-based person operating the holder's account would still be a US person trading on the
venue, and this plan does not cover that.

## What the forward tests are measured on

Every forward test prices its trades on **Binance USDⓈ-M perpetuals**: Binance's 5-minute archive,
recorded by #24's job. #27, #32 and #45 find their events in liquidations summed over Binance,
Bybit and OKX (aggr's feed). #32 and #38 use Binance's funding, which settles at 00:00, 08:00 and
16:00 UTC. The "it pays" bar of 18 bps is two Hyperliquid taker round trips. #45 nets each trade
with `espero.costs`, measured by #39 and #41 on Binance and Hyperliquid.

So a pass carries over most directly to Binance USDⓈ-M, the tests' own prices and funding clock.
Next comes Hyperliquid, whose costs are measured and whose prices track Binance's on these coins.
Every other venue adds a price basis and an unmeasured cost.

## The venues — compared, without the holder's country

Fees are the base tier, from the venues' pages and secondary reports on 2026-10-30. **Confirm each
against the venue's current schedule.** "Eligible?" is the holder's to fill in.

| venue | type | taker / maker (bps) | funding | the tests' prices? | costs measured (#39/#41)? | the 14 coins? | fills read without a trading key | eligible? |
|---|---|---|---|---|---|---|---|---|
| **Binance USDⓈ-M** | exchange | 5.0 / 2.0 (4.5 taker paying in BNB) | 8-hourly, 00/08/16 UTC | **yes** | **yes** | **yes** (the tests' source) | read-only API key | ? |
| **Hyperliquid** | on-chain order book | 4.5 / 1.5 | hourly | no, tracks Binance | **yes** | **yes** (checked 2026-10-30) | **public, by address** | ? |
| Coinbase Advanced perps (added 2026-10-31) | exchange; non-US, select countries | 3.0 / 0.0 advertised as promotional (another Coinbase page says 0.0 / 0.0) | check | no | no | check | check | ? |
| Bybit | exchange | 5.5 / 2.0 | 8-hourly by default; some contracts shorter | no | no | check | read-only API key | ? |
| OKX | exchange | 5.0 / 2.0 (one report says 6.0 taker) | 8-hourly by default | no | no | check | read-only API key | ? |
| dYdX | on-chain order book | 5.0 / 1.0 | hourly | no | no | check | public, by address | ? |
| Deribit | exchange | 5.0 / 0.0 (BTC, ETH) | accrues continuously, credited daily at 08:00 UTC | no | no | BTC and ETH; few others | read-only API key | ? |

**What the table changes:**

- **Binance's base taker fee is above the tests' hurdle.** Two round trips at 5.0 bps a side cost
  20 bps, against the 18 bps the "it pays" criteria assume. With the BNB discount it's 18. A pass
  that clears 18 bps by less than 2 bps is not a pass at Binance's base fee.
- **#38 is tied to an 8-hour clock.** Its settlements at 00/08/16 UTC exist on Binance (and by
  default Bybit and OKX), not on Hyperliquid's or dYdX's hourly funding, nor on Deribit's
  continuous accrual.
- **Coinbase's perps are the cheapest on paper, and the least certain.** Two round trips at 3.0 bps a side cost 12 bps,
  against the 18 bps bar. But Coinbase calls the rate promotional and reserves the right to change it, and its own pages
  disagree. Its price gap to Binance, real fills, funding schedule and coins are all unknown, and the repo has no route to
  it: `CoinbaseBroker` is the spot route. **Never use 12 bps in a sizing document without a measurement.**
- **Not candidates:** Coinbase spot (60–90 bps base taker in secondary reports, 120 in `espero/venues.py`) and Alpaca
  crypto (25 bps taker, spot only in the documents found). Two round trips cost at least 100 bps. Coinbase's US
  perpetual-style futures are for US persons ([VENUE_CONFIRMATION.md](VENUE_CONFIRMATION.md)).
- **Order of preference, if eligible:**
  1. **Binance USDⓈ-M**: the tests' own prices, funding and measured costs.
  2. **Hyperliquid**: measured costs, all 14 coins, reconciliation with no key, and the plumbing
     proven on its testnet by #40 and #42.
  3. The rest: each needs its own cost measurement (a new #39-style run) before a sizing document
     may use it.

## What may go real before 2027-03-31

**Only a cost-confirmation run**, on the venue the holder picks from the table. No strategy trades.
It is the measurement [VENUE_CONFIRMATION.md](VENUE_CONFIRMATION.md) describes:

- pre-registered as its own test (#47) before the first order;
- at the venue's minimum order size;
- about 200 taker and 200 maker fills, the power stated in VENUE_CONFIRMATION.md;
- passing if it matches #39's table for that venue within max(0.25 bps, 20%). A venue #39 did not
  measure has no table to match, so its run is a measurement, not a confirmation.

Everything after the window is governed by [FORWARD_FAMILY.md](FORWARD_FAMILY.md). A strategy
reaches real money only through a forward PASS, its tier's confirmation, and a sizing document.

## Reconciliation — the repo never holds a key that trades

Three records per fill must agree:

1. **The holder's own order log**, from whatever placed the order.
2. **The venue's fill history**:
   - **On-chain venues** (Hyperliquid, dYdX): public, read by address. No key at all.
     Hyperliquid's `userFills` is what `espero/reconcile.py` already checks, and `espero hl account
     --mainnet` already reads an account this way.
   - **Exchanges**: a **read-only** API key. The holder creates it, with trading and withdrawal
     disabled, and stores it in `.env` themselves. The repo never sees it printed. Each needs an
     adapter that maps its fills onto `reconcile.py`'s fields.
3. **The venue's own statement or trade export**, downloaded by the holder.

A fill present in one record and missing from another is a break and is listed, never dropped.

## Known gaps, stated now

- **#45's outcome names a venue a US person may use** (Kraken's US perps). That plan is committed
  and its window is open, so its text stays. If #45 passes, its sizing document says which venue
  applies to this holder and why.
- **"This bot"**, the BCH paper loop (the RSI/MACD/Bollinger vote), is not a candidate. The repo's
  own audit found that it loses after fees. It runs as a demonstration of the plumbing, and nothing
  in this plan points it at real money.
- **Whether the repo ever signs on mainnet** is a separate decision, made only after a forward pass,
  with its own pre-registration. If made, it would use a key that cannot withdraw, notional caps and
  a kill switch. It is not designed here.

Sources (fees and funding, 2026-10-30):
- [Binance futures fee structure](https://www.binance.com/support/faq/360033544231); [Finder on Binance futures fees](https://finder.com/cryptocurrency/trading/binance-futures-fees)
- [Bybit's fees](https://bybit.nl/nl-NL/help-center/article/Bybit-s-Fees-That-You-Need-to-Know); [Bybit vs Binance (CoinPerps)](https://www.coinperps.com/learn/bybit-vs-binance-perpetual-futures-fees)
- [OKX fee details](https://web3.okx.com/help/fee-details); [crypto futures fees compared](https://web3.okx.com/zh-hans-au/learn/crypto-futures-fees-compared)
- [dYdX trading fees](https://docs.dydx.exchange/introduction-trading_fees); [dYdX funding](https://docs.dydx.xyz/concepts/trading/funding)
- [Deribit funding specifications](https://support.deribit.com/hc/en-us/articles/31424939178397-Funding-Specifications); [Deribit fees](https://support.deribit.com/hc/en-us/articles/25944746248989)
- 2026-10-31: [Coinbase perpetuals](https://www.coinbase.com/fr/perpetuals); [Coinbase perpetuals API guide](https://docs.cdp.coinbase.com/coinbase-app/advanced-trade-apis/guides/perpetual); [Coinbase marketing page](https://www-marketing.coinbase.com/advanced-trade/perpetuals); [Altrady on Coinbase fees](https://www.altrady.com/blog/crypto-trading-platforms/coinbase-advanced-trade); [Alpaca crypto fees](https://docs.alpaca.markets/docs/crypto-fees)
