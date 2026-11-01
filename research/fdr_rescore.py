"""Benjamini-Hochberg q-values for the judged tests in research/trials.csv, for research/FDR_STANDARD.md. Reads the
ledger only and writes nothing. Information only: no committed verdict changes.

    .venv/bin/python research/fdr_rescore.py
"""
from __future__ import annotations

import math
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from espero import trials  # noqa: E402

JUDGED = ("fail", "pass", "provisional", "exploratory")
LOWER_IS_THE_EFFECT = {"18", "26", "36"}    # the registered effect is negative; every other test's is positive
TRADE_WEIGHTED = {"18": -2.68, "19": 3.15, "20": 3.50, "25": 1.93, "26": -3.54, "28": -1.44, "30": -1.65,
                  "35": 0.79, "37": 1.34}   # #44's t for the criterion's own statistic, RESULTS_DAYMEAN_AUDIT.md


def two_sided(t: float) -> float:
    return math.erfc(abs(t) / math.sqrt(2))


def q_values(p: pd.Series, m: int | None = None) -> pd.Series:
    """q-values for `p`; `m` above len(p) counts the missing tests as p = 1, so they cannot be discoveries."""
    m = m or len(p)
    return pd.Series(trials.bh(np.r_[p.to_numpy(), np.ones(m - len(p))])[:len(p)], index=p.index)


def main() -> None:
    d = pd.read_csv(ROOT / "research" / "trials.csv", dtype={"test": str})
    judged = d[d["status"].isin(JUDGED)]
    s = judged[judged["t"].notna()].set_index("test")
    m = len(judged)
    p = s["p_from_t"]
    harmonic = sum(1 / i for i in range(1, len(p) + 1))
    w = pd.Series({k: two_sided(TRADE_WEIGHTED.get(k, s.at[k, "t"])) for k in s.index})

    print(f"judged {m}, with a p-value {len(p)}, without: {list(judged[judged['t'].isna()]['test'])}\n")
    print("| # | status | t | right sign | t >= 3 | p | q, with a p-value | q, all judged | BY | q, trade-weighted |")
    print("|---|---|---|---|---|---|---|---|---|---|")
    q, q_all, q_w = q_values(p), q_values(p, m), q_values(w)
    for k in p.sort_values().index:
        t = s.at[k, "t"]
        sign = (t < 0) == (k in LOWER_IS_THE_EFFECT)
        print(f"| {k} | {s.at[k, 'status']} | {t:g} | {'yes' if sign else 'no'} | {'yes' if abs(t) >= 3 else 'no'} "
              f"| {p[k]:.5f} | {q[k]:.4f} | {q_all[k]:.4f} | {min(1.0, q[k] * harmonic):.4f} "
              f"| {q_w[k]:.4f} |")

    print()
    everyone = judged.set_index("test")["p_from_t"]
    for name, family in ((f"the {len(p)} with a p-value", p), (f"all {m} judged", everyone)):
        for level in (0.05, 0.10):
            rejected, cutoff, k = trials.benjamini_hochberg(family, q=level)
            print(f"{name}, q < {level:.2f}: {k} discoveries, p <= {cutoff:.5f}: {list(family.index[rejected])}")

    ps = everyone.fillna(1.0).to_numpy()
    bar = next(t for t in np.arange(1.0, 6.0, 0.001) if trials.benjamini_hochberg(np.r_[ps, two_sided(t)])[0][-1])
    print(f"\nthe next test clears q < 0.05 on all {m} judged at |t| >= {bar:.2f}, p <= {two_sided(bar):.5f}; "
          f"with t >= 3 as well, |t| >= {max(bar, 3.0):.2f}")


if __name__ == "__main__":
    main()
