"""Calibrates the detector on synthetic markets with a known answer. Reads no market returns except
the design window's weekly volatility, which sets how noisy the synthetic market is.

    python research/substrate_calibrate.py

Writes research/substrate_power.csv and substrate_attribution.csv, and prints both.
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from espero import detector, execsim  # noqa: E402

OUT = ROOT / "research"
ALPHAS = (0.0, 0.25, 0.5, 1.0, 1.5, 2.0, 3.0)
WEEKS = (147, 156, 303)     # the holdout, 2021-23, both
PATHS = 1000
SEED = 4803


def synthetic_tape(rng, half_bps, slope_bps_per_print, n=30_000, step_ms=120, qty=2.0, mid=100.0):
    """Alternating aggressors, a known half-spread, and a price that drifts up after t = 0 at a known
    rate, so the true cost of working an order is half-spread + drift over its own average time."""
    t = np.arange(n) * step_ms
    bm = rng.random(n) < 0.5
    path = mid * (1 + slope_bps_per_print / 1e4 * np.arange(n))
    price = path + np.where(bm, -1, 1) * mid * half_bps / 1e4
    return t, price, np.full(n, qty), bm, path


def tape_check(rng) -> pd.DataFrame:
    """Planted spreads and drift against what `tape_fill` reports: its one job, on data with a known cost."""
    rows = []
    for half, slope in ((0.5, 0.0), (3.0, 0.0), (3.0, 0.001), (10.0, 0.005)):
        est, truth = [], []
        for _ in range(200):
            t, p, q, bm, path = synthetic_tape(rng, half, slope)
            f = execsim.tape_fill(t, p, q, bm, 60_000, 1, 2_000.0)
            mid0 = path[np.searchsorted(t, 60_000, side="right") - 1]
            done = int(np.searchsorted(t, f.end_ms, side="left"))
            start = int(np.searchsorted(t, 60_000, side="left"))
            buys = ~bm[start:done + 1]
            truth.append(half + ((path[start:done + 1][buys].mean() - mid0) / mid0 * 1e4))
            est.append(f.cost_bps)
        rows.append({"half_spread_bps": half, "drift_bps_per_print": slope, "true_cost_bps": float(np.mean(truth)),
                     "estimated_cost_bps": float(np.mean(est)), "error_sd_bps": float(np.std(np.array(est) - truth))})
    return pd.DataFrame(rows)


def main() -> None:
    rng = np.random.default_rng(SEED)
    weeks = pd.read_csv(OUT / "substrate_design_weeks.csv")
    vol = float(weeks["gross"].std())
    print(f"weekly vol of the book, 2021-23: {vol:.3f}\n")

    tape = tape_check(rng)
    tape.to_csv(OUT / "substrate_tape_check.csv", index=False)
    print("the tape simulator on planted costs:")
    print(tape.to_string(index=False, float_format=lambda x: f"{x:.3f}"))

    rows = []
    for w in WEEKS:
        for cost in (0.0, 0.001):
            rows += [{**r, "cost_per_leg": cost} for r in
                     detector.power_table(rng, ALPHAS, w, PATHS, cost_per_leg=cost, weekly_vol=vol)]
    power = pd.DataFrame(rows)
    power.to_csv(OUT / "substrate_power.csv", index=False)
    print("\npower, false positives (alpha 0, cost 0) and coverage:")
    print(power.to_string(index=False, float_format=lambda x: f"{x:.3f}"))

    design_legs = pd.read_csv(OUT / "substrate_design_legs.csv.gz")
    leg_sd = float(design_legs[design_legs["size"] == 1_000_000.0]["tape_bps"].std()) / 1e4
    print(f"\nleg cost sd at $1M, 2021-23: {leg_sd * 1e4:.1f} bps")
    cases = [("all signal", 0.60, 0.0005), ("mostly signal", 0.60, 0.0020), ("mixed", 0.20, 0.0020),
             ("mostly execution", 0.05, 0.0050), ("all execution", 0.0, 0.0100)]
    att = pd.DataFrame(detector.attribution_table(rng, cases, paths=PATHS // 2, leg_sd=leg_sd))
    att.to_csv(OUT / "substrate_attribution.csv", index=False)
    print("\nthe attribution on planted splits:")
    print(att.to_string(index=False, float_format=lambda x: f"{x:.3f}"))


if __name__ == "__main__":
    main()
