# Result — the fill-confirmation plumbing, on Hyperliquid's testnet (#40)

**Verdict: PASS on all four pre-registered criteria, for BTC and ETH.** SOL was never tested: the
testnet rejected every SOL order as too far from its oracle price.

**The session also found a real bug that reconciliation cannot see.** `hl_exchange.round_size` cut
on-grid sizes one step: 0.00014 → 0.00013, 0.29 → 0.28. So every flatten undersold, and the session
ended 0.00011 BTC long. It is fixed (`9eef64a`), and the position is closed.

Spec: [PREREGISTRATION_TESTNET.md](PREREGISTRATION_TESTNET.md) (`e5f19cb`). Code `e34e498`. Run as
printed `d92ff88`: [testnet_run.txt](testnet_run.txt), full log
[testnet_session.json](testnet_session.json).

## Criteria

| # | criterion | result |
|---|---|---|
| 1 | post-only refuses to cross | **met**: 30 of 30 crossing ALO orders rejected, none filled. A 31st, ETH maker 6, was refused because the bid moved between snapshot and send: post-only working as it should. |
| 2 | every fill reconciles | **met**: 46 exchange fills on 44 order IDs against 47 orders in our record, 0 breaks. Two maker fills arrived as two partial fills each (0.00013 + 0.00001); grouping by order ID handled them. |
| 3 | fees are the schedule's | **met**: every fill's fee = price × size × 0.015% (maker) or 0.045% (taker), within tolerance |
| 4 | flags agree with the order type | **met**: every ALO fill had `crossed = false`, every IOC fill `crossed = true` |

## What did not go as pre-registered

- **SOL: 0 orders accepted.** All 13 non-crossing SOL orders were refused with "Price too far from
  oracle". Testnet's SOL book sat away from its oracle (impact prices 105.40 / 111.88 around a
  110.27 mark when the pre-registration was written). The criteria rest on BTC and ETH only.
- **The 200 USDC spot → perp transfer was refused** ("Must deposit before performing actions").
  Orders were accepted anyway, margined from the account's existing balance. The transfer was never
  needed.
- **The session did not end flat**, against the procedure's "the session ends flat, checked":
  - **Cause:** `round_size` floored 0.00014 × 10⁵ = 13.999… to 13. Each of 11 BTC flattens sold
    0.00001 short, leaving 0.00011 BTC.
  - **Why the reconciliation could not see it:** our record and the exchange's agree, correctly, on
    what was sent. **Comparing records cannot catch an order that was wrong when it was made.**
  - **Fixed:** in `espero/hl_exchange.py`, with a test that fails on the old code (`9eef64a`). The
    same function sizes #12's testnet mirror, which has not yet placed an order.
  - **Cleaned up:** the 0.00011 BTC was closed with a reduce-only IOC afterwards. The account is flat
    with no open orders.

## Information only

- **Send → acknowledgement: about 0.9 s.** Median 906 ms for ALO and 903 ms for IOC; p90 below
  975 ms. That is signing plus a round trip from this machine. On mainnet, an order this slow joins
  the back of every queue, which is #39's conservative bound.
- **Maker fill rate within 60 s:** 16 of 19 accepted bids.
- **Testnet 60 s maker markout:** −0.63 bps (n 16). **Not representative of mainnet**, and it
  confirms nothing.

## What this changes

- **`espero/reconcile.py` is proven against a live exchange record**, on maker, taker and partial
  fills. It is the piece a real-venue confirmation would reuse.
- **A confirmation on a real venue needs one more check than #40 had: position after = position
  intended**, per coin, after every flatten. Reconciliation proves the two records agree. Only an
  intent check proves either is what we meant.
- **Whether and where to run a real confirmation is the account holder's call.** See
  [VENUE_CONFIRMATION.md](VENUE_CONFIRMATION.md). Nothing here places a mainnet order.
