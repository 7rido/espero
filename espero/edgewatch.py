"""#70: edgewatch, the live stop rule: is this sleeve still the registered edge? (research/PREREGISTRATION_EDGEWATCH.md)

Pure: a sleeve's registered series and its live observations in, a CUSUM, an alarm threshold and an action out.
The CUSUM accumulates evidence that the mean has fallen from the registered edge mu0 to nothing:
S = max(0, S + (mu0 - x) / sigma0 - k), k = mu0 / (2 sigma0), an alarm at S >= h, then S restarts from 0. h is
the smallest threshold that bootstraps of the sleeve's own registered series, independent and in blocks, cross within
a year of observations no more than 5 % of the time. It computes nothing on a sleeve before that sleeve's verdict;
it is information only on the ladder's paper and testnet rungs and binding from the canary. It never raises a
size, and it is distinct from #63's drawdown states: the gate takes the smaller scale.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Sequence, Tuple

import numpy as np

FALSE_ALARM = 0.05          # chance of an alarm within a year of observations, under the registered distribution
BLOCK = 5.0                 # the stationary bootstrap's mean block length, in observations
BLOCKS = (1.0, BLOCK)       # h is the larger of an independent and a block bootstrap's: 5 % under either
PATHS = 20_000
SEED = 0
MIN_OBS = 30                # a registered series shorter than this cannot set a threshold
BINDING_RUNGS = ("canary", "scaled", "target")


@dataclass(frozen=True)
class Params:
    """A sleeve's edgewatch, fixed once from its verdict series at its sizing document's commit."""
    mu0: float
    sigma0: float
    k: float
    h: float
    per_year: float             # the sleeve's observations a year, from its forward window
    false_alarm: float
    delay_median: float         # observations to an alarm if the edge is gone (the series centred on 0)


def reference_k(mu0: float, sigma0: float) -> float:
    """Half the shift being looked for, in sigmas: from mu0 down to 0."""
    if not (mu0 > 0 and sigma0 > 0):
        raise ValueError("a sleeve without a positive registered edge has nothing to watch")
    return mu0 / (2 * sigma0)


def cusum(x: Sequence[float], mu0: float, sigma0: float, h: float = np.inf) -> Tuple[np.ndarray, List[int]]:
    """The statistic after each observation, and the observations at which it alarmed (it restarts at 0 after)."""
    k = reference_k(mu0, sigma0)
    s, path, alarms = 0.0, [], []
    for i, v in enumerate(np.asarray(x, dtype=float)):
        if not np.isfinite(v):
            path.append(s)                       # a missing observation adds no evidence either way
            continue
        s = max(0.0, s + (mu0 - v) / sigma0 - k)
        if s >= h:
            alarms.append(i)
            path.append(s)
            s = 0.0
            continue
        path.append(s)
    return np.asarray(path), alarms


def bootstrap_paths(x: Sequence[float], n: int, paths: int = PATHS, block: float = BLOCK, seed: int = SEED):
    """Stationary block bootstrap (Politis and Romano): `paths` series of length n, one row at a time."""
    v = np.asarray([a for a in x if np.isfinite(a)], dtype=float)
    rng = np.random.default_rng(seed)
    idx = rng.integers(v.size, size=paths)
    for _ in range(n):
        yield v[idx]
        new = rng.random(paths) < 1.0 / block
        idx = np.where(new, rng.integers(v.size, size=paths), (idx + 1) % v.size)


def _max_cusum(rows, mu0: float, sigma0: float, paths: int) -> np.ndarray:
    k = reference_k(mu0, sigma0)
    s = np.zeros(paths)
    top = np.zeros(paths)
    for row in rows:
        s = np.maximum(0.0, s + (mu0 - row) / sigma0 - k)
        top = np.maximum(top, s)
    return top


def calibrate_h(series: Sequence[float], per_year: float, false_alarm: float = FALSE_ALARM, paths: int = PATHS,
                blocks: Sequence[float] = BLOCKS, seed: int = SEED) -> float:
    """The smallest h that the registered series' bootstrap crosses within a year in no more than `false_alarm` of
    paths, taken as the largest over an independent bootstrap and a block bootstrap: a short series can understate
    its own variance by chance either way, and the larger threshold holds the rate under both."""
    v = np.asarray([a for a in series if np.isfinite(a)], dtype=float)
    if v.size < MIN_OBS:
        raise ValueError(f"{v.size} registered observations: at least {MIN_OBS} are needed")
    mu0, sigma0 = float(v.mean()), float(v.std(ddof=1))
    n = max(1, int(round(per_year)))
    hs = []
    for block in blocks:
        top = _max_cusum(bootstrap_paths(v, n, paths, block, seed), mu0, sigma0, paths)
        hs.append(float(np.quantile(top, 1.0 - false_alarm, method="higher")))
    return float(np.nextafter(max(hs), np.inf))   # strictly above the paths at the quantile: at most the rate


def delay(series: Sequence[float], h: float, shift_to: float = 0.0, horizon: int = 3650, paths: int = 2_000,
          block: float = BLOCK, seed: int = SEED) -> float:
    """Median observations to an alarm when the edge has moved to `shift_to` (the series re-centred), capped at
    `horizon`: what the rule can see, for the sizing document to quote."""
    v = np.asarray([a for a in series if np.isfinite(a)], dtype=float)
    mu0, sigma0 = float(v.mean()), float(v.std(ddof=1))
    k = reference_k(mu0, sigma0)
    shifted = v - mu0 + shift_to
    s = np.zeros(paths)
    first = np.full(paths, float(horizon))
    for t, row in enumerate(bootstrap_paths(shifted, horizon, paths, block, seed)):
        s = np.maximum(0.0, s + (mu0 - row) / sigma0 - k)
        hit = (s >= h) & (first == horizon)
        first[hit] = t + 1
        if (first < horizon).all():
            break
    return float(np.median(first))


def params(series: Sequence[float], per_year: float, false_alarm: float = FALSE_ALARM, paths: int = PATHS,
           seed: int = SEED) -> Params:
    """Everything a sleeve's sizing document records, from its verdict series, once."""
    v = np.asarray([a for a in series if np.isfinite(a)], dtype=float)
    h = calibrate_h(v, per_year, false_alarm, paths, BLOCKS, seed)
    mu0, sigma0 = float(v.mean()), float(v.std(ddof=1))
    return Params(mu0, sigma0, reference_k(mu0, sigma0), h, float(per_year), false_alarm,
                  delay(v, h, seed=seed))


# what an alarm does, per latency class (research/LIVE_LATENCY.md)
ACTIONS: Dict[str, Tuple[str, str]] = {
    "live-from-tape": ("halve at once and call the operator", "flat, absorbing until a new number"),
    "operator-paced": ("call the operator; half size until they answer; they may choose flat; silence halves",
                       "flat, absorbing until a new number"),
}


def action(klass: str, alarms: int) -> str:
    """What the sleeve does after its n-th alarm."""
    if alarms <= 0:
        return "nothing"
    if klass not in ACTIONS:
        raise ValueError(f"a {klass} rule is not traded live, so edgewatch never acts on it")
    return ACTIONS[klass][0 if alarms == 1 else 1]


def scale(alarms: int) -> float:
    """The sleeve's edgewatch factor in risk.check: 1, a half after the first alarm, 0 after the second."""
    return 1.0 if alarms <= 0 else 0.5 if alarms == 1 else 0.0


def binding(rung: str) -> bool:
    """Information only on the paper twin and testnet rungs; it acts from the mainnet canary on."""
    return rung in BINDING_RUNGS


def rule():
    """The registered rule is `cusum` with `params`; this name is what the scaffold's test looks for."""
    return cusum
