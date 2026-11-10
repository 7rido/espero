"""A bracket order on bars, simulated honestly: entry at the next bar's open, a stop that defines R, targets that
take part of the position off, the stop to the entry after a target, a time stop, and out at the day's end if
asked. Pure: arrays in, trades out, no I/O; the backtests and any later paper loop call the same code.

The rules where a bar cannot tell what happened first, chosen against the trade:

* **Stop first.** When one bar reaches both the stop and a target, the stop is taken.
* **A gap through the stop** fills at the bar's open, which is worse than the stop.
* **A gap through a target** fills at the target, not at the better open.
* **A stop moved to the entry** after a target counts from the next bar, never inside the bar that hit the target.
* **Costs** (`cost_bps`, of each fill's notional: the fee plus the measured slippage, from #74 once it exists, or
  `espero.costs`/`espero.venues` otherwise) are charged on the entry and on every partial exit.

R is the distance from the entry to the first stop, so a trade stopped out at once is −1R before costs.

`random_means` is the benchmark the HIP-3 proposal put first: the same bracket, side and stop distance (as a
fraction of the price) from random entries on the same bars. A rule is worth something only by how far its mean R
sits above what random entries earn on names that mostly rose.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import List, Optional, Sequence, Tuple

import numpy as np


@dataclass(frozen=True)
class Bracket:
    targets: Tuple[Tuple[float, float], ...] = ((1.5, 0.5), (2.8, 0.5))   # (R multiple, share of the position)
    breakeven_after: Optional[int] = 1        # targets hit before the stop moves to the entry; None: never
    max_bars: Optional[int] = None            # bars held, the entry bar included; then out at that bar's close
    flat_at_day_end: bool = False             # out at the close of each day's last bar
    cost_bps: float = 0.0                     # per fill, of its notional

    def __post_init__(self):
        rs = [r for r, _ in self.targets]
        if any(r <= 0 for r in rs) or rs != sorted(rs) or len(set(rs)) != len(rs):
            raise ValueError("targets must be positive R multiples in increasing order")
        share = sum(s for _, s in self.targets)
        if any(s <= 0 for _, s in self.targets) or share > 1 + 1e-9:
            raise ValueError("target shares must be positive and add up to at most 1")
        if self.max_bars is not None and self.max_bars < 1:
            raise ValueError("max_bars must be at least 1")
        if self.cost_bps < 0:
            raise ValueError("a cost cannot be negative")


@dataclass(frozen=True)
class Trade:
    side: int                 # +1 long, -1 short
    signal_i: int             # the bar whose close decided
    entry_i: int
    exit_i: int               # the bar of the last exit
    entry: float
    risk: float               # price distance from the entry to the first stop: 1R
    r: float                  # the result in R, after costs
    outcome: str              # how the last part left: stop, breakeven, target, time, day end, end of data


def simulate(o: Sequence[float], h: Sequence[float], low: Sequence[float], c: Sequence[float], signal_i: int,
             side: int, risk: float, b: Bracket, day: Optional[Sequence] = None) -> Optional[Trade]:
    """One bracket from a signal at bar `signal_i`'s close; None when no next bar exists to enter on."""
    if side not in (1, -1) or not risk > 0:
        raise ValueError("a trade needs a side and a positive stop distance")
    e = signal_i + 1
    n = len(o)
    if e >= n:
        return None
    entry = float(o[e])
    stop = entry - side * risk
    tps = [(entry + side * r * risk, share) for r, share in b.targets]
    left, pnl, hits = 1.0, 0.0, 0
    cost = entry * b.cost_bps / 1e4

    def out(price: float, share: float) -> None:
        nonlocal left, pnl, cost
        pnl += share * side * (price - entry)
        cost += share * price * b.cost_bps / 1e4
        left -= share

    def stopped() -> str:
        return "breakeven" if stop == entry else "stop"

    for i in range(e, n):
        if i > e and side * (o[i] - stop) <= 0:            # gapped through the stop: out at the open
            reason = stopped()
            out(float(o[i]), left)
            return Trade(side, signal_i, e, i, entry, risk, (pnl - cost) / risk, reason)
        worst = low[i] if side > 0 else h[i]
        if side * (worst - stop) <= 0:                     # the bar reached the stop: taken first
            reason = stopped()
            out(stop, left)
            return Trade(side, signal_i, e, i, entry, risk, (pnl - cost) / risk, reason)
        best = h[i] if side > 0 else low[i]
        while hits < len(tps) and side * (best - tps[hits][0]) >= 0:
            out(tps[hits][0], min(tps[hits][1], left))
            hits += 1
        if left <= 1e-12:
            return Trade(side, signal_i, e, i, entry, risk, (pnl - cost) / risk, "target")
        if b.breakeven_after is not None and hits >= b.breakeven_after:
            stop = entry                                     # from the next bar
        if b.max_bars is not None and i - e + 1 >= b.max_bars:
            out(float(c[i]), left)
            return Trade(side, signal_i, e, i, entry, risk, (pnl - cost) / risk, "time")
        if b.flat_at_day_end and day is not None and (i + 1 == n or day[i + 1] != day[i]):
            out(float(c[i]), left)
            return Trade(side, signal_i, e, i, entry, risk, (pnl - cost) / risk, "day end")
    out(float(c[n - 1]), left)
    return Trade(side, signal_i, e, n - 1, entry, risk, (pnl - cost) / risk, "end of data")


def run(o, h, low, c, signals: Sequence[Tuple[int, int, float]], b: Bracket, day=None) -> List[Trade]:
    """Signals (bar, side, stop distance) in bar order, one trade at a time: a signal while a trade is open, or on
    the bar it closed, is skipped."""
    trades: List[Trade] = []
    busy_until = -1
    for i, side, risk in sorted(signals, key=lambda s: s[0]):
        if i <= busy_until:
            continue
        t = simulate(o, h, low, c, i, side, risk, b, day)
        if t is not None:
            trades.append(t)
            busy_until = t.exit_i
    return trades


@dataclass(frozen=True)
class Summary:
    n: int
    win_rate: Optional[float]      # share with r > 0
    mean_r: Optional[float]
    total_r: float
    profit_factor: Optional[float]  # the R won over the R lost; None with no loss
    t: Optional[float]             # mean / standard error; None under 2 trades or with no spread


def summary(rs: Sequence[float]) -> Summary:
    rs = [float(x) for x in rs]
    n = len(rs)
    if not n:
        return Summary(0, None, None, 0.0, None, None)
    won = sum(x for x in rs if x > 0)
    lost = -sum(x for x in rs if x < 0)
    mean = sum(rs) / n
    sd = math.sqrt(sum((x - mean) ** 2 for x in rs) / (n - 1)) if n > 1 else 0.0
    return Summary(n, sum(1 for x in rs if x > 0) / n, mean, sum(rs), won / lost if lost > 0 else None,
                   mean / (sd / math.sqrt(n)) if n > 1 and sd > 0 else None)


def random_means(cases: Sequence[Tuple[Sequence[float], Sequence[float], Sequence[float], Sequence[float],
                                       Optional[Sequence], Sequence[Trade]]],
                 b: Bracket, draws: int = 1000, seed: int = 0) -> np.ndarray:
    """The benchmark: each draw replaces every real trade by one from a random signal bar on the same market, with
    the same side and the same stop distance as a fraction of the entry price; the draw's value is the mean R of
    those trades. `cases` is one (open, high, low, close, day, trades) per market."""
    rng = np.random.default_rng(seed)
    out = np.empty(draws)
    for k in range(draws):
        rs = []
        for o, h, low, c, day, trades in cases:
            for t in trades:
                i = int(rng.integers(0, len(o) - 1))
                got = simulate(o, h, low, c, i, t.side, t.risk / t.entry * float(o[i + 1]), b, day)
                rs.append(got.r)
        out[k] = sum(rs) / len(rs) if rs else float("nan")
    return out


def beats_random(real_mean: float, means: np.ndarray) -> Tuple[float, float]:
    """(the real mean minus the median random mean, the share of random draws at or above the real mean)."""
    m = means[~np.isnan(means)]
    return real_mean - float(np.median(m)), float(np.mean(m >= real_mean))
