# Pre-registration — dress rehearsal of the real-fill test, on Hyperliquid's testnet (#42)

Committed **before any order is sent**. A rehearsal: testnet orders carry no real money and meet no
real counterparties. The forty-third test in this repo.

## Why

#39 and #41 conclude from historical prints that a resting order at the back of the queue loses
before fees. The test of that conclusion that depends on neither the code nor its author is **real
resting orders, on a venue the account holder may legally use, placed by the account holder**.
[VENUE_CONFIRMATION.md](VENUE_CONFIRMATION.md) describes it.

This rehearsal runs **the exact procedure** of that test on Hyperliquid's testnet, so every part of
it is proven before real orders depend on it:
- placing post-only orders on both sides of several coins at once;
- recording the venue's public book through the session, to mark each fill to market;
- reconciling every fill against the exchange's record;
- **the check #40 lacked**: the position held equals the position intended, after every flatten
  and at the end.

**What it cannot say, fixed now.** Testnet counterparties are a few test bots trading play money.
Its markouts are printed only so that the comparison code runs end to end. They are labelled **not
representative**, and they neither confirm nor refute #39 or #41.

## Coins — by rule

At the session start:
- take mainnet's perps ranked by 24-hour notional volume;
- keep the first **five** whose testnet book has both sides, a mid within **1%** of the testnet
  oracle price, and a spread under 50 bps.

When this was written that was **BTC, ETH, NEAR, PUMP, kPEPE**. HYPE (mid 68% from oracle), ZEC
(empty book) and SOL (5%) were excluded, and XRP is not listed. The rule is re-applied at the start,
and the coins it picks are printed.

## The procedure — this is what the real-venue test will repeat

- **Size**: the smallest size with notional ≥ $12 at the mid. Sizes come from the fixed
  `round_size`.
- **Orders**: per coin, **20 post-only orders**, alternating a buy at the best bid and a sell at the
  best ask. The coins run in parallel, one order resting per coin at a time. Each rests up to 60 s
  and is cancelled if unfilled. Fills are kept as inventory, so the alternation keeps it near flat.
- **Intended position**: a running sum per coin, from the fills our record shows (IOC acknowledgement
  sizes; for resting orders, original − remaining size).
- **Flatten**: when the intended position exceeds two order sizes, and at the end, a reduce-only IOC
  closes it.
- **The book recorder**: the best bid and ask of every chosen coin, polled once a second for the
  whole session and for **6 minutes after the last fill**, with the local receive time.
- **The exchange's record**: `user_fills_by_time` from the session start, 60 s after the last order.

## Criteria — PASS requires all five

1. **#40's four checks**, unchanged (`espero/reconcile.py`):
   - post-only never takes (here: no ALO fill with `crossed = true`);
   - every fill reconciles;
   - fees are the schedule's;
   - flags agree with the order type.
2. **The position holds what was intended**: after every flatten and at the end, the exchange's
   position per coin equals the intended position, within half a size step. The session ends flat on
   every coin.
3. **Every maker fill is marked**: each one has a recorded mid at +1, +10, +60 and +300 s, taken
   within 2 s of its target time.
4. **No orphan orders**: no open orders remain at the end.
5. **The rule chose five coins.**

**Information only, labelled not representative of mainnet:**
- per-coin maker fill rate within 60 s;
- testnet markouts at each horizon, printed beside #39's conservative band for BTC and ETH, so the
  comparison table the real test will print is exercised;
- send → acknowledgement latency.

## Outcomes, fixed now

- **PASS**: the kit (recorder, position check, markout comparison, reconciliation) is ready.
  - The real-venue version is pre-registered next, once the account holder chooses the venue. It
    gets a pass rule fixed before the first order: real fills' conservative-comparable markouts
    against #39's band.
  - The account holder places those orders; this repo does not.
- **FAIL**: each break is listed, fixed, and the rehearsal re-run as a dated amendment.

## Transparency — seen before writing

- Mainnet's top ten perps by 24-hour volume.
- Their testnet books against the oracle, as listed above.
- #40's results.
- No order has been sent for this test.
