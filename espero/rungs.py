"""The deployment ladder's rungs and its scaling rule, fixed before any canary fill (research/DEPLOYMENT_LADDER.md).

Pure: a block of measured fills in, the next rung and size out. A sleeve climbs paper twin -> testnet -> canary
-> scaled -> target; on the mainnet rungs it moves one block of fills at a time. A block that passes (enough fills,
the median shortfall inside the registered budget, no reconciliation break, no edgewatch alarm) steps the size up;
a breach steps it down; two breaches in a row send it back to the canary, and two on the canary back to testnet.
The fraction it returns is one factor of the sleeve's scale in `risk.check`; the canary trades the venue's minimum,
whatever the fraction.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Optional

RUNGS = ("paper", "testnet", "canary", "scaled", "target")
TESTNET_ROUND_TRIPS = 50       # testnet mechanics: round trips through the sleeve's own executor
CANARY_FILLS = 30              # a mainnet block: the canary's, and each scaled step's
START_FRACTION = 0.10          # the scaled rung starts at a tenth of the target
STEP_UP = 2.0
STEP_DOWN = 0.5
BREACHES_TO_CANARY = 2


@dataclass(frozen=True)
class Block:
    """One block of fills on a mainnet rung, as espero.attribution measures them."""
    fills: int
    median_shortfall_bps: float    # against the decision price, net of the fee schedule
    budget_bps: float              # the sizing document's: the registered cost plus #62's fill error
    breaks: int                    # reconciliation breaks found in the block
    edgewatch_alarm: bool = False


@dataclass(frozen=True)
class State:
    rung: str
    fraction: float = 0.0          # of the target size; meaningful on the scaled rung
    breaches_in_row: int = 0


def breach(block: Block) -> Optional[str]:
    """Why the block fails, or None. A block too small to judge is not a breach: it is not judged yet."""
    if block.breaks > 0:
        return f"{block.breaks} reconciliation break(s)"
    if block.edgewatch_alarm:
        return "an edgewatch alarm (#70)"
    if not math.isfinite(block.median_shortfall_bps) or block.median_shortfall_bps > block.budget_bps:
        return f"median shortfall {block.median_shortfall_bps:.1f} bps over the {block.budget_bps:.1f} bps budget"
    return None


def step(state: State, block: Block) -> State:
    """The rung after one block. Paper and testnet are left by the holder's decision, not by this rule."""
    if state.rung not in ("canary", "scaled", "target"):
        raise ValueError(f"{state.rung}: only the mainnet rungs move by blocks of fills")
    why = breach(block)
    if why is None and block.fills < CANARY_FILLS:
        return state                                   # not a full block yet: no move
    if why is None:
        if state.rung == "canary":
            return State("scaled", START_FRACTION, 0)
        if state.rung == "scaled":
            up = min(1.0, state.fraction * STEP_UP)
            return State("target", 1.0, 0) if up >= 1.0 else State("scaled", up, 0)
        return State("target", 1.0, 0)
    n = state.breaches_in_row + 1
    if state.rung == "canary":                         # two in a row: the fill path itself is in doubt
        return State("testnet", 0.0, 0) if n >= BREACHES_TO_CANARY else State("canary", 0.0, n)
    if n >= BREACHES_TO_CANARY:
        return State("canary", 0.0, 0)
    if state.rung == "target":
        return State("scaled", STEP_DOWN, n)
    return State("scaled", max(START_FRACTION * STEP_DOWN, state.fraction * STEP_DOWN), n)


def size_fraction(state: State) -> float:
    """The rung's factor of the sleeve's scale in risk.check. The canary sends the venue's minimum instead."""
    return {"paper": 0.0, "testnet": 0.0, "canary": 0.0, "scaled": state.fraction, "target": 1.0}[state.rung]
