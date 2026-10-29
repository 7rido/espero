# Result — dress rehearsal of the real-fill test, on Hyperliquid's testnet (#42)

**Verdict: PASS on all eight criteria.** The procedure a real-venue test would run worked end to
end, on five coins at once:
- resting post-only orders on both sides;
- a book recorder;
- fill reconciliation;
- the position-against-intent check #40 lacked.

Spec: [PREREGISTRATION_REHEARSAL.md](PREREGISTRATION_REHEARSAL.md) (`0e9be02`). Code `80c97da`. Run as
printed `b7479ab`: [rehearsal_run.txt](rehearsal_run.txt), full log
[rehearsal_session.json](rehearsal_session.json).

## Criteria

| # | criterion | result |
|---|---|---|
| 1a | post-only never takes | met: no ALO fill crossed. One BTC order was refused because the bid moved before it arrived: post-only working as it should. |
| 1b | every fill reconciles | met: 74 exchange fills (69 maker), 0 breaks |
| 1c | fees are the schedule's | met |
| 1d | flags agree with the order type | met |
| 2 | position holds what was intended | met: after all 4 flattens and at the end, on every coin |
| 3 | every maker fill is marked | met: 69 fills × 4 horizons from 7,990 book rows, 0 read errors |
| 4 | no orphan orders | met |
| 5 | the rule chose five coins | met: BTC, ETH, NEAR, PUMP, kPEPE |

## Information only — testnet, not representative of mainnet

**Fill rates within 60 s:**

| coin | fills |
|---|---|
| BTC | 19 of 19 |
| ETH | 19 of 20 |
| kPEPE | 10 of 20 |
| NEAR | 8 of 20 |
| PUMP | 3 of 20 |

**Send → acknowledgement:** median 872 ms, p90 928 ms.

**Markouts.** On BTC and ETH, testnet markouts landed in the same range as #39's mainnet
conservative numbers at the short horizons. For example, ETH at +10 s: −2.59 testnet vs −1.83
mainnet. They diverged at 300 s. With 19 fills and play-money counterparties, this neither confirms
nor refutes anything; it only shows that the comparison table prints.

## What this changes

The kit for a real-fill confirmation is ready and proven:
- `espero/reconcile.py`, with the position check;
- the book recorder and markout pass in `research/rehearsal.py`.

Pointing it at a venue a US person can use (Coinbase's nano perps, or Kraken's US perps) needs that
venue's adapters and a pre-registered pass rule. The account holder places the orders.
