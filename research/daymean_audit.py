"""Hypothesis #44 — audit of the day-mean convention. Run once:

    python research/daymean_audit.py

Frozen in research/PREREGISTRATION_DAYMEAN_AUDIT.md. Each headline is rebuilt from its own committed event
file with its own module's code; the published day-mean must reproduce before the trade-weighted value counts.
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from espero import audit as au  # noqa: E402
from espero import levetf as lv  # noqa: E402
from espero import liq as lq  # noqa: E402

R = ROOT / "research"
HURDLE = 0.0018


def ANY(t: float) -> bool:
    return True

OUT = R / "daymean_audit.csv"


def read(name: str) -> pd.DataFrame:
    return pd.read_csv(R / name)


def leg_events(ev: pd.DataFrame, col: str = "s", y: str = "y60") -> pd.DataFrame:
    """liq.leg's events: usable, tagged within day, forced down-breaks, long = -y... as leg signs them."""
    ev = lq.usable(ev, col, y)
    ev = ev.assign(tag=lq.tag(ev, col))
    sel = ev[(ev["direction"] == -1) & (ev["tag"] == "forced")]
    return pd.DataFrame({"x": sel[y] * -1, "day": sel["day"]})


def diff_events(ev: pd.DataFrame, col: str = "s", y: str = "y60") -> pd.DataFrame:
    """day_diff's events: usable, tagged within day, forced or organic, on days with both."""
    ev = lq.usable(ev, col, y)
    ev = ev.assign(tag=lq.tag(ev, col))
    ev = ev[ev["tag"].isin(["forced", "organic"])]
    both = ev.groupby("day")["tag"].transform("nunique") == 2
    ev = ev[both]
    return pd.DataFrame({"y": ev[y], "forced": (ev["tag"] == "forced").astype(int), "day": ev["day"]})


def headlines():
    liq18, liq26 = read("liq_events.csv"), read("liq2_events.csv.gz")
    oi = read("oi_events.csv.gz")
    lows = read("lows_events.csv.gz")
    spike = read("liqspike_events.csv")
    x19 = read("settle_events.csv")                  # already excess()'s output: g per high event
    lvd = read("levetf_days.csv.gz")
    lvd = lv.sample(lvd[lvd["coin"].isin(lv.PRIMARY)], "with", "trading").rename(columns={"date": "day"})
    bids = read("bids_events.csv.gz")
    bids = bids[bids["complete"].astype(bool) & bids["filled"].astype(bool)]
    fc = read("fillcost_events.csv.gz")
    sw = read("sweeps_events.csv.gz")
    sw = sw[(sw["side"] == "low") & (sw["kind"] == "reclaimed")]
    ph = read("polyhour_markets.csv.gz").dropna(subset=["profit"])
    oi_use = lq.usable(oi, "oi_drop", "r60")
    oi_f = oi_use[lq.tag(oi_use, "oi_drop") == "forced"]
    longs = spike[spike["side"] == "long"]
    sp = fc[fc["bucket"] == "shorts pay"].dropna(subset=["m30"])
    dn = lows[lows["direction"] == "down"]
    gt0, lt0 = (lambda m: m > 0), (lambda m: m < 0)
    pays = (lambda m: m > HURDLE, lambda t: t > 2)
    # (id, study, headline, kind, frame, published (mean, t), bar (mean_rule, t_rule))
    return [
        ("1", "#18", "leg (a) forced down-breaks, 1 h", "mean", leg_events(liq18), (26.4e-4, 3.85), pays),
        ("2", "#18", "D forced − organic, 1 h", "diff", diff_events(liq18), (-11.4e-4, -2.11), (lt0, lambda t: t <= -3)),
        ("3", "#19", "g, settlement excess", "mean", pd.DataFrame({"x": x19["g"], "day": x19["day"]}), (15.5e-4, 3.52),
         (gt0, lambda t: t >= 3)),
        ("4a", "#20", "new-low bounce, 1 h (the bounce)", "mean", pd.DataFrame({"x": dn["r60"], "day": dn["day"]}),
         (14.8e-4, 9.78), (gt0, lambda t: t >= 3)),
        ("4b", "#20", "new-low bounce, 1 h (it pays)", "mean", pd.DataFrame({"x": dn["r60"], "day": dn["day"]}),
         (14.8e-4, 9.78), pays),
        ("5", "#21", "long leg, raw 24 h", "mean", pd.DataFrame({"x": np.expm1(longs["r24_open"]), "day": longs["day"]}),
         (51.1e-4, 2.45), pays),
        ("6", "#25", "forced leg, 1 h", "mean", pd.DataFrame({"x": oi_f["r60"], "day": oi_f["day"]}), (12.3e-4, 6.00), pays),
        ("7", "#25", "D (oi_drop), 1 h", "diff", diff_events(oi, "oi_drop", "r60"), (3.2e-4, 2.36), (gt0, lambda t: t >= 3)),
        ("8", "#26", "leg (a) forced down-breaks, 1 h", "mean", leg_events(liq26), (23.5e-4, 7.13), pays),
        ("9", "#26", "D forced − organic, 1 h", "diff", diff_events(liq26), (-23.6e-4, -4.06), (lt0, lambda t: t <= -3)),
        ("10", "#28", "the push, with-era trading days", "mean", pd.DataFrame({"x": lvd["y"], "day": lvd["day"]}),
         (-1.5e-4, -1.44), (gt0, lambda t: t >= 3)),
        ("11", "#29 basis", "post-close reversal, 15 min", "mean", pd.DataFrame({"x": lvd["post15"], "day": lvd["day"]}),
         (-6.0e-4, -5.6), (lt0, ANY)),
        ("12", "#30", "filled bids' net", "mean", pd.DataFrame({"x": bids["net"], "day": bids["day"]}), (1.7e-4, 0.97),
         (lambda m: m >= 5e-4, lambda t: t >= 3)),
        ("13", "#33", "shorts pay hard, m30", "mean", pd.DataFrame({"x": sp["m30"], "day": sp["day"]}), (-34.0e-4, -2.62),
         (lt0, ANY)),
        ("14", "#35", "reclaimed sweeps, 1 h", "mean", pd.DataFrame({"x": sw["r60"], "day": sw["day"]}), (15.3e-4, 6.99),
         (gt0, lambda t: t >= 3)),
        ("15", "#37", "the model's bets (dollars a share)", "mean", pd.DataFrame({"x": ph["profit"], "day": ph["day"]}),
         (0.009, 1.0), (gt0, lambda t: t >= 2)),
    ]


def main() -> None:
    rows = []
    for hid, study, name, kind, f, pub, (mr, tr) in headlines():
        f = f.dropna()
        if kind == "mean":
            dm = au.day_mean(f["x"], f["day"])
            tw = au.trade_weighted(f["x"], f["day"])
            n = len(f)
        else:
            per = f.groupby(["day", "forced"])["y"].mean().unstack()
            dd = per[1] - per[0]
            dm = au.day_mean(dd, pd.Series(dd.index, index=dd.index))
            tw = au.diff_trade_weighted(f["y"], f["forced"], f["day"])
            n = len(f)
        unit = 1.0 if study == "#37" else 1e4
        tol_m = 0.006 if study == "#37" else 0.1e-4 * 1.5
        repro = abs(dm["mean"] - pub[0]) <= tol_m and abs(dm["t"] - pub[1]) <= 0.02 + 0.01 * abs(pub[1])
        ch = au.changed(dm, tw, mr, tr) if repro else None
        rows.append({"id": hid, "study": study, "headline": name, "events": n, "days": dm["days"],
                     "published": pub[0] * unit, "published_t": pub[1],
                     "day_mean": dm["mean"] * unit, "day_t": dm["t"], "reproduced": repro,
                     "trade_weighted": tw["mean"] * unit, "trade_t": tw["t"],
                     "ratio": tw["mean"] / dm["mean"] if dm["mean"] else np.nan,
                     "quiet_share": au.quiet_share(f["day"]),
                     "met_day": au.meets(dm, mr, tr), "met_trade": au.meets(tw, mr, tr), "changed": ch})
    out = pd.DataFrame(rows)
    out.to_csv(OUT, index=False, float_format="%.6g")
    pd.set_option("display.width", 250)
    print("#44 — the day-mean audit. bps unless noted (#37 in dollars a share).\n")
    print(out[["id", "study", "headline", "events", "days", "published", "day_mean", "day_t", "reproduced",
               "trade_weighted", "trade_t", "ratio", "quiet_share", "met_day", "met_trade", "changed"]]
          .to_string(index=False, float_format=lambda v: f"{v:.2f}"))
    bad = out[~out["reproduced"]]
    print(f"\nnot reproduced (not audited): {', '.join(bad['id'] + ' ' + bad['study']) if len(bad) else 'none'}")
    chg = out[out["changed"] == True]  # noqa: E712
    print(f"CHANGED: {', '.join(chg['id'] + ' ' + chg['study'] + ' (' + chg['headline'] + ')') if len(chg) else 'none'}")


if __name__ == "__main__":
    main()
