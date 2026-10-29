# Pre-registration — the fill-confirmation plumbing, on Hyperliquid's testnet (#40)

Committed **before any order is sent**. A plumbing check, not a strategy, and not a cost
measurement: testnet orders carry no real money. The forty-first test in this repo.

## Why

#39 measured costs on mainnet prints. The check that depends on neither the code nor its author is
**real fills reconciled against the exchange's own records**. [VENUE_CONFIRMATION.md](VENUE_CONFIRMATION.md)
describes that check. It has never been run, and every piece of it can fail silently:

- a fill we record that the exchange doesn't, or the reverse;
- a fee that isn't the schedule's;
- a "post-only" order that takes liquidity;
- a maker/taker flag that disagrees with the order type.

Hyperliquid's testnet runs the same matching engine, API and fee schedule with play money, so the
plumbing can be proven there before it is pointed at a venue that matters.

**What this test cannot say, fixed now.** Testnet books are thin and few traders use them (SOL's
impact prices were 105.40 / 111.88 around a 110.27 mark when this was written). Its spreads,
queues and markouts say **nothing** about mainnet costs. Any testnet markout is printed only to be
labelled as such. It does not confirm or refute #39.

## Setup — fixed

- **Account**: `HL_WALLET_ADDRESS`, signed through `espero/hl_exchange.py`'s guards (testnet URL
  constant, two opt-ins). It holds 967.74 testnet USDC on the spot side and 0 on perps.
  **200 USDC** is moved spot → perp with `usd_class_transfer` before the first order.
- **Coins**: BTC, ETH, SOL. XRP has no testnet market.
- **Size**: the smallest size with notional ≥ $12 at the testnet mark (Hyperliquid's minimum order is
  $10).
- **Fees**: the account's `userFees` at run time. When this was written: taker 0.045%, maker 0.015%.
- **The account's 517 earlier fills** are not ours. They are excluded by time: only fills at or
  after the session's start count.

## The session — run once, about 30 minutes

Every request is logged with local send and receive timestamps (ms), the full response, and the
order ID.

1. **Post-only must refuse to cross.** Per coin, 5 ALO buys priced at the best ask and 5 ALO sells
   at the best bid: 30 orders.
2. **Maker fills.** Per coin, 10 ALO buys at the best bid. Each waits up to 60 s, then is cancelled
   if unfilled. Any filled size is flattened with an IOC sell at 0.5% through the best bid: a taker
   fill.
3. **Taker fills.** Per coin, 3 IOC buys at 0.5% through the best ask, each flattened by an IOC sell
   the same way.
4. **Our record of each order.**
   - IOC: the acknowledgement's `totalSz` and `avgPx`.
   - Resting orders: `query_order_by_oid` after the wait or cancel. Filled = original size −
     remaining size.
   - The session ends flat: no open orders, no position, checked.
5. **The exchange's record.** `user_fills_by_time` from the session's start, pulled 60 s after the
   last order.

## Criteria — PASS requires all four

1. **Post-only refuses.** All 30 crossing ALO orders are rejected, and none appears in the fills.
2. **Every fill reconciles.** Group the exchange's fills by order ID, and compare with our record
   per order ID:
   - filled size equal to the size step;
   - IOC average price equal within one price tick;
   - no order ID in one record and missing from the other.

   Zero breaks.
3. **Fees are the schedule's.** For every exchange fill, fee = price × size × rate, with the maker
   rate when `crossed` is false and the taker rate when true. It must hold within max(0.000001 USDC,
   0.1% of the fee).
4. **The flags agree with the order type.** Every fill from an ALO order has `crossed = false`, and
   every fill from an IOC order has `crossed = true`.

**Information only, decides nothing:**
- send → acknowledgement latency, as the median and 90th percentile per order type;
- the maker fill rate within 60 s;
- testnet 60 s markouts of the maker fills, against the testnet mid, labelled **not representative
  of mainnet**.

## Outcomes, fixed now

- **PASS**: the reconciliation code (`espero/reconcile.py`) is proven against a live exchange record.
  It is the piece a real-venue confirmation would reuse. Whether and where that happens is the
  account holder's decision. This repo places no mainnet order.
- **FAIL**: each break is listed. The plumbing is fixed and the session re-run as a dated amendment
  before anything builds on it.

## Transparency — seen before writing

- The testnet guards passed.
- The account's perp value (0), spot USDC (967.74), fill count (517, not read further), role
  (user) and fee rates.
- Testnet meta and contexts for BTC, ETH and SOL: marks and impact prices.
- No key value was printed or read into this conversation.
