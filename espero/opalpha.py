"""#69: operator alpha, what the overrides earned against the rule (research/PREREGISTRATION_OPALPHA.md).

Pure: overrides in, numbers out, no I/O. Each override is scored against the paper twin's trade on the same
event, both net of costs: alpha_bps = (live net - twin net) / proposed notional x 10^4, positive when the operator
did better than the rule. Information only: there is no PASS or FAIL and no trial is spent.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Dict, Optional, Sequence

import numpy as np

from .factor_eval import newey_west_t

KINDS = ("reject", "modify", "exit", "delay", "operator", "silence")
MIN_OVERRIDES = 30
WINDOW_DAYS = 365
DAY_S = 86_400


@dataclass(frozen=True)
class Override:
    kind: str                   # one of KINDS
    rule: str
    at: int                     # when the operator acted (or the proposal lapsed)
    notional: float             # the proposal's notional
    live_net: Optional[float]   # dollars, net of fees and funding: what was done (0 when nothing was traded)
    twin_net: Optional[float]   # dollars, net of registered costs: what the rule did on the same event


def alpha_bps(o: Override) -> Optional[float]:
    """The override's score, or None when either side is missing (not comparable, counted)."""
    if o.live_net is None or o.twin_net is None or not o.notional > 0:
        return None
    return (o.live_net - o.twin_net) / o.notional * 1e4


def lags(n: int) -> int:
    """Newey-West lags floor(4 (n/100)^(2/9)), as research/FDR_STANDARD.md fixes them."""
    return int(math.floor(4 * (n / 100) ** (2 / 9))) if n > 0 else 0


def _stats(scores: Sequence[float], dollars: Sequence[float]) -> Dict[str, float]:
    x = np.asarray(scores, dtype=float)
    n = int(x.size)
    return {"n": n,
            "mean_bps": float(x.mean()) if n else float("nan"),
            "median_bps": float(np.median(x)) if n else float("nan"),
            "dollars": float(np.sum(dollars)) if n else 0.0,
            "share_positive": float((x > 0).mean()) if n else float("nan"),
            "t_nw": float(newey_west_t(x, lags(n))) if n >= 3 else float("nan")}


def ready(overrides: Sequence[Override], first_live: Optional[int], now: int) -> bool:
    """The measurement is reported once: at 30 comparable overrides, or 365 days after the first live proposal."""
    if first_live is None:
        return False
    comparable = sum(1 for o in overrides if alpha_bps(o) is not None)
    return comparable >= MIN_OVERRIDES or now - first_live >= WINDOW_DAYS * DAY_S


def summary(overrides: Sequence[Override]) -> Dict[str, object]:
    """Per kind and overall, in time order: count, mean and median bps, dollars, share above zero, the NW t
    (for reading, against no bar), and what was not comparable."""
    unknown = sorted({o.kind for o in overrides} - set(KINDS))
    if unknown:
        raise ValueError(f"unknown override kinds: {unknown}")
    ordered = sorted(overrides, key=lambda o: o.at)
    scored = [(o, alpha_bps(o)) for o in ordered]
    ok = [(o, a) for o, a in scored if a is not None]
    out: Dict[str, object] = {"all": _stats([a for _, a in ok], [o.live_net - o.twin_net for o, _ in ok])}
    for k in KINDS:
        sel = [(o, a) for o, a in ok if o.kind == k]
        out[k] = _stats([a for _, a in sel], [o.live_net - o.twin_net for o, _ in sel])
    out["not_comparable"] = sum(1 for _, a in scored if a is None)
    out["silence_dollars"] = out["silence"]["dollars"]
    return out


def rule():
    """The registered measurement is `summary`; this name is what the scaffold's test looks for."""
    return summary
