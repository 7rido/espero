"""#72: does open interest forecast tomorrow's cascade beyond volatility? (research/EXPLORE_CASCADE.md)

    python research/cascade.py --design     # files through 2022-12 only; reruns allowed
    python research/cascade.py --holdout    # once, after PREREGISTRATION_CASCADE.md is committed

The design run refuses to open a kline file after 2022-12, skips every open-interest day after 2022-12-31
unopened and drops every funding settlement after 2022-12-31 on load. The holdout run refuses unless the
pre-registration is committed and unchanged, and unless no holdout output exists yet.
"""
from __future__ import annotations

import argparse
import contextlib
import gzip
import json
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Dict, List, Tuple

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "research")]

import volf as rvolf  # noqa: E402  the kline loader #66 used, with its design refusal

from espero import cascade as cs  # noqa: E402
from espero import liq as lq  # noqa: E402
from espero import trials  # noqa: E402
from espero import volf as vf  # noqa: E402
from espero.xs import UNIVERSE  # noqa: E402

OI = ROOT / "data" / "oi"
FUNDING = ROOT / "data" / "settle" / "funding"
PREREG = ROOT / "research" / "PREREGISTRATION_CASCADE.md"
DESIGN_OUT = ROOT / "research" / "cascade_design_run.txt"
HOLDOUT_OUT = ROOT / "research" / "cascade_run.txt"
SERIES_OUT = ROOT / "research" / "cascade_series.csv"
CELLS_OUT = ROOT / "research" / "cascade_cells.csv.gz"
JUDGED = ("fail", "pass", "provisional", "exploratory")
OI_COLS = {"sum_open_interest": "oi", "count_long_short_ratio": "ls"}
FIRST_FIT = pd.Timestamp("2021-01-31")
WORKERS = 6


# ----------------------------------------------------------------------------------------------- inputs
def oi_frame(sym: str, last_day: pd.Timestamp) -> pd.DataFrame:
    """Each day's last metrics row: oi and ls. A day after `last_day` is never opened."""
    folder = OI / sym
    rows: Dict[pd.Timestamp, dict] = {}
    if not folder.exists():
        return pd.DataFrame(columns=list(OI_COLS.values()))
    for p in sorted(folder.glob("*.csv.gz")):
        day = pd.Timestamp(p.name[:10])
        if day > last_day:
            continue
        try:
            with gzip.open(p, "rt") as f:
                df = pd.read_csv(f)
        except (OSError, EOFError, ValueError):
            continue
        if df.empty or not set(OI_COLS) <= set(df.columns):
            continue
        df = df.drop_duplicates().sort_values("create_time")
        last = df.iloc[-1]
        if not str(last["create_time"]).startswith(p.name[:10]):
            continue
        try:
            rows[day] = {v: float(last[k]) for k, v in OI_COLS.items()}
        except (TypeError, ValueError):
            continue
    out = pd.DataFrame.from_dict(rows, orient="index").sort_index()
    return out if len(out) else pd.DataFrame(columns=list(OI_COLS.values()))


def funding_frame(sym: str, last_day: pd.Timestamp) -> pd.DataFrame:
    """Every settlement's signed rate by its time; settlements after `last_day` dropped on load."""
    path = FUNDING / f"{sym}.json"
    if not path.exists():
        return pd.DataFrame(columns=["rate"])
    t, r = [], []
    for row in json.loads(path.read_text()):
        try:
            t.append(int(row["fundingTime"]))
            r.append(float(row["fundingRate"]))
        except (KeyError, TypeError, ValueError):
            continue
    idx = pd.to_datetime(np.asarray(t, dtype="int64"), unit="ms")
    f = pd.DataFrame({"rate": r}, index=idx).sort_index()
    return f[f.index < last_day + pd.Timedelta(days=1)]


def plan_for(design: bool) -> dict:
    if design:
        last_day, last_month = vf.DESIGN_LAST_DAY, vf.DESIGN_LAST_MONTH
    else:
        last_day, last_month = vf.HOLDOUT_LAST_DAY, vf.HOLDOUT_LAST_MONTH
    last_origin = last_day - pd.Timedelta(days=1)
    return {"last_day": last_day, "last_month": last_month, "last_origin": last_origin,
            "fits": cs.month_ends(FIRST_FIT, last_origin)}


def coin(c: str, design: bool, plan: dict) -> Tuple[pd.DataFrame, dict]:
    sym = lq.symbol("binance-futures", c)
    meta = {"coin": c, "symbol": sym}
    b = rvolf.bars(sym, plan["last_month"], design)
    if b.empty:
        meta["status"] = "no bars"
        return pd.DataFrame(), meta
    d = vf.daily(b)
    d = d[d.index <= plan["last_day"]]
    ts = b.index.to_numpy(dtype="int64")
    last = (ts - ts // vf.DAY_S * vf.DAY_S) == vf.LAST_BAR_S
    close = pd.Series(np.log(b["close"].to_numpy(dtype=float))[last],
                      index=pd.to_datetime(ts[last] // vf.DAY_S * vf.DAY_S, unit="s"))
    d["close"] = close[~close.index.duplicated(keep="last")].reindex(d.index)
    volume = b["volume"].groupby(pd.to_datetime(ts // vf.DAY_S * vf.DAY_S, unit="s")).sum().reindex(d.index)
    moves = cs.hour_moves(b)
    ev = cs.events(d, moves)
    feats = cs.features(d, volume, oi_frame(sym, plan["last_day"]), funding_frame(sym, plan["last_day"]))
    rows = feats.copy()
    rows["y"] = ev["cascade"]
    rows["squeeze"] = ev["squeeze"]
    rows["sigma_d"] = ev["sigma_d"]
    rows["fall"] = moves["fall"].reindex(d.index).shift(-1)
    rows["coin"] = c
    rows["origin"] = rows.index
    rows = rows[rows["origin"] <= plan["last_origin"]].reset_index(drop=True)
    done = d.index[d["complete"]]
    meta.update(status="ok", first=str(done.min().date()) if len(done) else "-", complete_days=int(len(done)),
                oi_days=int(feats["oi1"].notna().sum()), targets=int(rows["y"].notna().sum()),
                events=int(rows["y"].fillna(0).sum()))
    return rows, meta


# --------------------------------------------------------------------------------------------- judgment
def committed_unchanged(path: Path) -> bool:
    rel = str(path.relative_to(ROOT))
    tracked = subprocess.run(["git", "ls-files", "--error-unmatch", rel], cwd=ROOT, capture_output=True)
    changed = subprocess.run(["git", "diff", "--quiet", "HEAD", "--", rel], cwd=ROOT)
    return tracked.returncode == 0 and changed.returncode == 0


def ledger_q(p72: float) -> Tuple[float, int]:
    """#72's Benjamini-Hochberg q over every judged test in the ledger plus #72, a missing p counted as 1."""
    d = pd.read_csv(ROOT / "research" / "trials.csv", dtype={"test": str})
    judged = d[d["status"].isin(JUDGED) & (d["test"] != "72")]
    ps = pd.to_numeric(judged["p_from_t"], errors="coerce").fillna(1.0).to_numpy()
    allp = np.append(ps, p72)
    q = trials.bh(allp)
    return float(q[-1]), int(len(allp))


def two_sided_p(t: float) -> float:
    from math import erf, sqrt
    return float(2 * (1 - 0.5 * (1 + erf(abs(t) / sqrt(2))))) if np.isfinite(t) else float("nan")


def gap_block(cells: pd.DataFrame, a: str, b: str, label: str) -> List[str]:
    s = cs.per_origin(cells, a, b)
    if s.empty:
        return [f"{label}: no scored origins"]
    t = cs.nw_t(s.to_numpy(), vf.nw_lags(len(s)))
    h1, h2 = cs.halves(s)
    up, counted = cs.breadth(cells, a, b)
    n = len(cs.scored(cells, a, b))
    return [f"{label}: mean gap {s.mean():+.5f} over {len(s)} origins ({n} cells), NW t {t:.2f}; "
            f"halves {h1:+.5f} / {h2:+.5f}; coins with mean gap > 0: {up} of {counted}"]


def report(rows: pd.DataFrame, metas: List[dict], design: bool, plan: dict) -> List[str]:
    out = [f"#72 {'DESIGN' if design else 'HOLDOUT'} run: {len(metas)} coins, origins through {plan['last_origin'].date()}"]
    for m in metas:
        out.append("  " + ", ".join(f"{k}={v}" for k, v in m.items()))
    targets = rows.dropna(subset=["y"])
    rate = float(targets["y"].mean()) if len(targets) else float("nan")
    out.append(f"\nevent rate over every row with a target: {rate:.4f} on {len(targets)} rows, {int(targets['y'].sum())} cascades; "
               f"k = {cs.K_SIGMA} -> registered k would be {cs.choose_k(rate)}")
    sq = rows.dropna(subset=["squeeze"])
    out.append(f"squeeze rate: {float(sq['squeeze'].mean()):.4f} on {len(sq)} rows")

    fits, last_origin = plan["fits"], plan["last_origin"]
    rows = rows.copy()
    rows["vol"], _ = cs.forecasts(rows, cs.VOL, fits, last_origin)
    rows["full"], models = cs.forecasts(rows, cs.FULL, fits, last_origin)
    rows["base"] = cs.base_rate(rows, fits, last_origin)
    first = rows.loc[rows["full"].notna(), "origin"].min() if rows["full"].notna().any() else None
    cells = rows[rows["origin"] >= (pd.Timestamp("2023-01-01") if not design else pd.Timestamp("2000-01-01"))]
    scored = cs.scored(cells, "vol", "full")
    n_events = int(scored["y"].sum())
    out.append(f"first forecast origin {first.date() if first is not None else '-'}; scored cells {len(scored)}, "
               f"cascades among them {n_events}, origins {scored['origin'].nunique()}")

    out.append("\n== The registered comparison: FULL against VOL, log loss, positive when FULL is better")
    out += gap_block(cells, "vol", "full", "FULL vs VOL")
    s = cs.per_origin(cells, "vol", "full")
    if not s.empty:
        t = cs.nw_t(s.to_numpy(), vf.nw_lags(len(s)))
        p = two_sided_p(t)
        h1, h2 = cs.halves(s)
        up, counted = cs.breadth(cells, "vol", "full")
        if design:
            out.append(f"   p (two-sided) {p:.4g}; the verdict is not computed on the design window")
        else:
            q, fam = ledger_q(p)
            out.append(f"   p (two-sided) {p:.4g}; BH q {q:.4g} over {fam} tests")
            out.append(f"   VERDICT: {cs.verdict(t, q, h1, h2, up, counted, n_events)}")

    out.append("\n== Information only")
    out += gap_block(cells, "base", "vol", "(a) VOL vs BASE rate")
    out += gap_block(cells, "base", "full", "(b) FULL vs BASE rate")
    sc = cs.scored(cells, "vol", "full")
    if len(sc) >= 100:
        cal = cs.calibration(sc["full"].to_numpy(), sc["y"].to_numpy())
        out.append("(c) calibration of FULL by decile: n, mean forecast, observed rate")
        out += ["   " + " ".join(f"{int(r.decile)}:{int(r.n)}/{r.forecast:.4f}/{r.observed:.4f}" for r in cal.itertuples())]
        top = cal.iloc[-1]
        out.append(f"(d) lift: top-decile observed rate {top.observed:.4f} against the scored base rate {sc['y'].mean():.4f} "
                   f"= {top.observed / sc['y'].mean() if sc['y'].mean() > 0 else float('nan'):.2f}x; "
                   f"bottom decile {cal.iloc[0].observed:.4f}")
        calv = cs.calibration(sc["vol"].to_numpy(), sc["y"].to_numpy())
        out.append(f"    VOL's top decile {calv.iloc[-1].observed:.4f}, bottom {calv.iloc[0].observed:.4f}")
    if models:
        last_fit = max(models)
        beta = models[last_fit]["beta"]
        out.append(f"(e) FULL's standardized coefficients at the last fit ({last_fit.date()}): "
                   + ", ".join(f"{c} {b:+.3f}" for c, b in zip(["const"] + cs.FULL, beta)))
        v_at = cs.forecasts(rows, cs.VOL, [last_fit], last_origin)[1].get(last_fit)
        if v_at is not None:
            out.append("    VOL's: " + ", ".join(f"{c} {b:+.3f}" for c, b in zip(["const"] + cs.VOL, v_at["beta"])))
    if not s.empty:
        by_year = s.groupby(s.index.year).agg(["mean", "size"])
        out.append("(f) FULL vs VOL by year: " + ", ".join(f"{y} {r['mean']:+.5f} ({int(r['size'])})" for y, r in by_year.iterrows()))
        liquid = cells[cells["coin"].isin(vf.LIQUID)]
        rest = cells[~cells["coin"].isin(vf.LIQUID)]
        out.append(f"(g) BTC and ETH {cs.per_origin(liquid, 'vol', 'full').mean():+.5f}; the rest "
                   f"{cs.per_origin(rest, 'vol', 'full').mean():+.5f}")
    sq_rows = rows.copy()
    sq_rows["y"] = rows["squeeze"]
    sq_rows["vol"], _ = cs.forecasts(sq_rows, cs.VOL, fits, last_origin)
    sq_rows["full"], _ = cs.forecasts(sq_rows, cs.FULL, fits, last_origin)
    sq_cells = sq_rows[sq_rows["origin"] >= cells["origin"].min()] if len(cells) else sq_rows
    out += gap_block(sq_cells, "vol", "full", "(h) the squeeze day, FULL vs VOL")
    if not s.empty:
        out.append(f"(i) the gap's daily sd {s.std():.5f}, so the holdout's t at n origins is about "
                   f"mean / sd * sqrt(n) if dependence matches: n=1185 -> {s.mean() / s.std() * np.sqrt(1185):.2f}")
    return out, cells


def main(argv: List[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--design", action="store_true")
    g.add_argument("--holdout", action="store_true")
    a = ap.parse_args(argv)
    design = bool(a.design)
    if not design:
        if not committed_unchanged(PREREG):
            print("refused: research/PREREGISTRATION_CASCADE.md must be committed and unchanged before the holdout")
            return 2
        if HOLDOUT_OUT.exists():
            print(f"refused: {HOLDOUT_OUT.relative_to(ROOT)} exists; the holdout is read once")
            return 2
    plan = plan_for(design)
    with ThreadPoolExecutor(WORKERS) as ex:
        results = list(ex.map(lambda c: coin(c, design, plan), UNIVERSE))
    rows = pd.concat([r[0] for r in results if len(r[0])], ignore_index=True)
    lines, cells = report(rows, [r[1] for r in results], design, plan)
    text = "\n".join(lines) + "\n"
    (DESIGN_OUT if design else HOLDOUT_OUT).write_text(text)
    if not design:
        cs.per_origin(cells, "vol", "full").rename("gap").to_csv(SERIES_OUT, float_format="%.6g")
        keep = ["origin", "coin", "y", "squeeze", "sigma_d", "fall", "vol", "full", "base"]
        with gzip.open(CELLS_OUT, "wt") as f:
            cells[keep].to_csv(f, index=False, float_format="%.6g")
    print(text, end="")
    return 0


if __name__ == "__main__":
    with contextlib.suppress(BrokenPipeError):
        raise SystemExit(main())
