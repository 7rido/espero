"""The trial budget: every test in research/trials.csv, deflated Sharpe, SPA, and the spend rate.

    python research/substrate_trials.py

Reads committed event files and frozen research inputs only. Forward tests count as trials and
contribute no statistic: their running numbers are not read.
"""
from __future__ import annotations

import json
import sys
import warnings
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "research"))
from espero import trials  # noqa: E402

warnings.filterwarnings("ignore")
OUT = ROOT / "research"
SEED = 4804
# Assigned after the fact, by the class of the idea. Nothing recorded a prior when these tests ran.
PRIORS = {"literature": 0.20, "variant": 0.10, "novel": 0.05, "measurement": np.nan}
ASSUMED_POWER = 0.5
HURDLE_BPS = 18.0       # two Hyperliquid taker round trips, the repo's "it pays" bar (#39)
DAYS = {"2": 1031, "4": 2120, "5": 2120, "7": 1395, "8": 846, "11": 209, "12": 209, "14": 168, "15": 3220}


def scored() -> pd.DataFrame:
    d = pd.read_csv(OUT / "trials.csv", dtype={"test": str})
    d["prior"] = d["prior_class"].map(PRIORS)
    # Two-sided throughout, so one test's one-sided figure (#43's) is not compared with the rest.
    p = d["p_from_t"].fillna(d["p_reported"])
    d["p_used"] = p
    have = p.notna()
    d["p_holm"], d["q_bh"] = np.nan, np.nan
    d.loc[have, "p_holm"] = trials.holm(p[have].to_numpy())
    d.loc[have, "q_bh"] = trials.bh(p[have].to_numpy())
    d["days"] = d["test"].map(DAYS)
    return d


def deflate(d: pd.DataFrame) -> pd.DataFrame:
    """Sharpes on one scale (annualised -> per day), deflated against every test run, not just those
    that reported a Sharpe. Returns assumed normal: the files hold no skew, and fat tails would lower these."""
    s = d[d["sharpe"].notna() & d["days"].notna()].copy()
    per_day = s["sharpe"] / np.sqrt(365.25)
    var = float(per_day.var(ddof=1))
    n = len(d)
    s["sr_daily"] = per_day
    s["psr_vs_zero"] = [trials.psr(x, 0.0, int(t)) for x, t in zip(per_day, s["days"])]
    s["dsr"] = [trials.deflated_sharpe(x, int(t), n, var) for x, t in zip(per_day, s["days"])]
    s.attrs["var_daily"] = var
    s.attrs["sr0_ann"] = trials.expected_max_sharpe(n, var) * np.sqrt(365.25)
    return s


def panel() -> pd.DataFrame:
    """Daily series for each headline whose events or books are on disk, flat on days it did not trade."""
    import daymean_audit as au

    cols = {}
    sign = {"11": -1.0, "13": -1.0}     # registered as a short signal (#29's reversal, #33's shorts pay)
    for hid, study, name, kind, frame, _, _ in au.headlines():
        if kind != "mean" or study == "#37" or hid == "4b":
            continue
        f = frame.dropna()
        day = pd.to_datetime(f["day"]).dt.tz_localize(None).dt.normalize()
        # #30's figure is already net of its own measured cost
        net = sign.get(hid, 1.0) * f["x"] - (0.0 if study == "#30" else HURDLE_BPS / 1e4)
        cols[f"{study} {name} (net of 18 bps)"] = net.groupby(day).mean()
        cols[f"{study} {name} (gross)"] = (sign.get(hid, 1.0) * f["x"]).groupby(day).mean()
    import momentum as m

    idx, op, cl = m.build(m.load())
    eq, _ = m.simulate(idx, op, cl, *m.HOLDOUT)
    r2 = eq.pct_change().dropna()
    r2.index = r2.index.tz_localize(None).normalize()
    cols["#2 holdout, as run"] = r2
    import carry as run

    from espero import carry

    for label, kw in (("#11 as run", {}), ("#12 as run", dict(maker=True, swap_gap=carry.SWAP_GAP,
                                                              min_hold=carry.MIN_HOLD_H))):
        e = carry.evaluate(run.load(), initial=1.0, **kw)["result"].equity.dropna()
        e.index = e.index.tz_localize(None)
        r = e.resample("1D").last().pct_change().dropna()
        cols[label] = r
    cal = pd.date_range("2020-01-01", "2026-10-27", freq="D")
    return pd.DataFrame({k: v.groupby(level=0).sum().reindex(cal) for k, v in cols.items()}).fillna(0.0)


def main() -> None:
    rng = np.random.default_rng(SEED)
    d = scored()
    d.drop(columns=["days"]).to_csv(OUT / "trials_scored.csv", index=False)
    judged = d[d["status"].isin(["pass", "fail", "provisional", "exploratory"])]
    print(d[["test", "status", "prior_class", "prior", "t", "p_used", "p_holm", "q_bh"]].to_string(
        index=False, float_format=lambda x: f"{x:.3g}"))

    s = deflate(d)
    print(f"\nDeflated Sharpe: {len(d)} trials, SR0 {s.attrs['sr0_ann']:.2f} annualised")
    print(s[["test", "status", "sharpe", "sharpe_freq", "days", "psr_vs_zero", "dsr"]].to_string(
        index=False, float_format=lambda x: f"{x:.3f}"))
    s[["test", "status", "sharpe", "sharpe_freq", "days", "psr_vs_zero", "dsr"]].to_csv(
        OUT / "trials_dsr.csv", index=False)

    x = panel()
    gross = [c for c in x.columns if "net of" not in c]
    net = [c for c in x.columns if "gross" not in c]
    out = {}
    for label, c in (("gross", gross), ("net", net)):
        r = trials.spa(rng, x[c].to_numpy(), mean_block=10, draws=5000)
        r["best_name"] = c[r["best"]]
        out[f"spa_{label}"] = r
        print(f"\nSPA, {label}: p {r['p']:.4f}, stat {r['stat']:.2f}, {r['k']} series x {r['n']} days, "
              f"best {r['best_name']}, kept {r['kept']}")
    tstat = x.mean() / x.std() * np.sqrt(len(x))
    tstat.sort_values().to_csv(OUT / "trials_spa_series.csv", header=["t_flat_days"])

    sp = trials.spend(d)
    with_prior = judged[judged["prior"].notna()]
    expected = {"expected_true_passes_at_priors": float((with_prior["prior"] * ASSUMED_POWER).sum()),
                "expected_false_passes_at_priors": float(((1 - with_prior["prior"]) * 0.05).sum()),
                "p_values_available": int(d["p_used"].notna().sum()),
                "survive_holm_05": int((d["p_holm"] < 0.05).sum()), "survive_bh_05": int((d["q_bh"] < 0.05).sum()),
                "sr0_annualised": s.attrs["sr0_ann"], "dsr_above_95": int((s["dsr"] > 0.95).sum())}
    summary = {**sp, **expected, **out}
    (OUT / "trials_summary.json").write_text(json.dumps(summary, indent=1, default=float))
    print(json.dumps({**sp, **expected}, indent=1, default=float))


if __name__ == "__main__":
    main()
