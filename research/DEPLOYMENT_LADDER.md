# The deployment ladder: from a PASS to target size, one rung at a time

**Written 2026-11-02, before any forward verdict and before any sleeve exists.** A forward PASS says an effect was
there on paper, judged once. It does not say the effect survives real fills, real latency and a real account.
This ladder is the path a passed rule climbs to real size. **Every rung's criteria and its step back are written
here, before any sleeve steps on it**, and the scaling rule is code (`espero/rungs.py`, `tests/test_rungs.py`)
before any canary fill exists. It decides no verdict and changes no frozen test. Each sleeve's sizing document
(research/TEMPLATE_SIZING.md) fills in its own numbers for each rung and may make a rung stricter, never looser.

## The rungs

| rung | what trades | what is measured | size | who moves it |
|---|---|---|---|---|
| 0. paper twin | nothing: the frozen rule at its registered fills | the rule itself, the control | none | always on from the verdict |
| 1. testnet mechanics | the sleeve's executor on Hyperliquid's testnet, through `risk.check` | the order path: placement, fills, reconciliation, faults | test money | the holder, after its pass |
| 2. mainnet canary | the sleeve's executor on the holder's venue | **fills only**: shortfall, fees, fill rate. P&L is irrelevant | the venue's minimum order | `rungs.step`, by blocks of 30 fills |
| 3. scaled | the same | the same, and the gap to the twin | 10 % of target, doubling | `rungs.step` |
| 4. target | the same | the same, and edgewatch (#70) binding | the target below | `rungs.step` |

### Rung 0: the paper twin, always on

- **Begins** the day after the sleeve's verdict, never before: before it, the forward ledger's running numbers
  decide nothing and are not read (AGENTS.md). From that day the forward step keeps running unchanged, and its
  ledger, from that day on, is the twin.
- **It is the control:** every live trade is compared with the twin's trade on the same event
  (`espero.attribution`, the gap to the twin), and every operator override with the twin's outcome (#69).
- **It never stops** while any live rung runs. If the twin stops, the live sleeve stops at the next decision point.

### Rung 1: testnet mechanics

The model is `espero/hlp_testnet.py`, which already places #59's trades on Hyperliquid's testnet from its paper
journal, with client order ids, a lookup before any resend, and a `.stop` kill switch.

- **Entry:** the sleeve's sizing document is committed, and the sleeve's executor exists, signs only through
  `espero/hl_exchange.py`, and sends every order through `risk.check`.
- **Pass, all of:**
  1. at least **50 round trips** (`rungs.TESTNET_ROUND_TRIPS`) on the testnet, each reconciled by
     `espero.reconcile` with **zero unreconciled breaks**;
  2. every fault in `espero/replay_stack.py` drilled with its required behaviour (dropped frames, a silent venue,
     partial fills, a restart mid-trade, a position the journal does not know, clock skew, a stale input), on
     recorded tape and, where the testnet allows, live;
  3. the kill switch drilled: the `.stop` file stops entries and closes every open position;
  4. placement latency, signal to acknowledgement, inside the rule's budget (research/LIVE_LATENCY.md) at the
     95th percentile. #40 and #42 measured about 0.9 seconds to acknowledgement;
  5. a restart during an open trade sends no duplicate order and keeps the exit time.
- **Step back:** none: a failure is fixed and the count of round trips starts again.
- **What it cannot say:** anything about edge or cost. Testnet prices and depth are not mainnet's.

### Rung 2: the mainnet canary

- **Entry, all of:** rung 1 passed; the holder's inputs answered (docs/HOLDER_INPUTS.md): capital, venue
  eligibility, the drawdown stop; the holder's written lift of the no-mainnet rule committed and a mainnet module
  built from research/DESIGN_MAINNET_PATH.md with its own tests; an auto-only rule (research/LIVE_LATENCY.md)
  also needs the holder's written decision to let the machine trade unattended.
- **Size:** the venue's minimum order, whatever the target (`rungs.size_fraction` is 0; the executor sends the
  minimum).
- **Measured:** each fill's shortfall against the decision price, net of the fee schedule; the fees against the
  venue's own statement; the maker fill rate where the rule rests orders. **P&L is not a criterion.**
- **Pass, one block (`rungs.CANARY_FILLS` = 30 fills):** the median shortfall inside the sizing document's budget
  (the registered cost plus #62's measured fill error); zero reconciliation breaks; no edgewatch alarm; fees matching
  the statement within max(0.25 bps, 20 %), as VENUE_CONFIRMATION.md would confirm #39's table. Then the sleeve
  moves to rung 3.
- **Step back:** a block that breaches stays on the canary; **two breaches in a row send the sleeve back to
  rung 1**: the fill path itself is in doubt. Any break also stops entries at once through the risk gate until it is
  reconciled.

### Rung 3: scaled, by a rule written now

`espero.rungs.step`, applied after each block of 30 fills:

- the first scaled block runs at **10 % of target** (`START_FRACTION`);
- a block that passes (inside budget, zero breaks, no edgewatch alarm) **doubles** the size: 10 %, 20 %, 40 %,
  80 %, then target;
- a breach **halves** it (never below 5 %);
- **two breaches in a row** send the sleeve back to the canary.

### Rung 4: target

- **The target** is the smallest of: #63's weight for the sleeve (1.0 if it is the only one) x the allocated capital;
  the capacity readout at the sleeve's net edge (research/ROBUSTNESS_STANDARD.md, from the recorded depth at its
  trade times; never more than the recorded depth); and every cap of research/RISK_POLICY.md.
- **It stays** while each block passes. A breach steps it down to 50 %, on rung 3, and the rule above applies.
- **Edgewatch (#70) is binding** here and on rungs 2 and 3: its alarm halves or flattens as #70 says, through the
  sleeve's scale.

## What every rung shares

- **The risk gate:** every order on rungs 1 to 4 passes `risk.check`, and the rung's fraction is one factor of the
  sleeve's scale there, beside #63's weight and the drawdown and edgewatch states.
- **Reconciliation:** three records per fill (research/VENUE_NONUS.md): the executor's log, the venue's fill
  history, the venue's statement. A fill missing from one is a break, listed and never dropped.
- **The operator** (docs/OPERATOR.md): operator-paced sleeves wait for approvals on every rung from 1; auto-only
  sleeves run unattended only from the holder's written decision.
- **No rung is skipped,** and no criterion here is loosened by a sizing document.

## What is not decided here

- Whether any rule passes: that is each forward plan's, once, after 2027-03-31.
- The capital, the drawdown stop and the venue: the holder's (docs/HOLDER_INPUTS.md). Until they are answered the
  canary cannot start, because the risk gate refuses every entry with no capital.
- The mainnet order path itself, which does not exist (research/DESIGN_MAINNET_PATH.md).
