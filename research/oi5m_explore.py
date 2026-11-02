"""Exploration, not a test: open interest beside the price at 5 minutes on Hyperliquid's contexts
(research/EXPLORE_OI5M.md). Reads the explored slots only; refuses anything from 2026-11-02 on.

    .venv/bin/python research/oi5m_explore.py > research/oi5m_explore_run.txt
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from espero.audit import trade_weighted_nw  # noqa: E402
from espero.liqvault import tier_of  # noqa: E402

DATA = Path(__file__).resolve().parents[1] / "data" / "hlcollect" / "ctx"
SEALED_FROM = pd.Timestamp("2026-11-02", tz="UTC")
SLOT = 300
HORIZONS = {"15m": 3, "1h": 12, "4h": 48}
TAIL = 2.0
FINE = 0.01
MIN_EVENTS = 20


def load() -> pd.DataFrame:
    frames = []
    for path in sorted(DATA.glob("*/*.csv.gz")):
        day, hhmm = path.parent.name, path.stem.split(".")[0]
        slot = pd.Timestamp(f"{day} {hhmm[:2]}:{hhmm[2:]}", tz="UTC")
        if slot >= SEALED_FROM:
            continue                                        # sealed: never opened here
        df = pd.read_csv(path, usecols=["coin", "mark", "open_interest", "day_volume"])
        df["slot"] = int(slot.timestamp())
        frames.append(df)
    return pd.concat(frames, ignore_index=True)


def panel(raw: pd.DataFrame) -> pd.DataFrame:
    """Per coin on the 5-minute grid: r, d, the hour-before OI change, forward returns; gaps stay gaps."""
    out = []
    for coin, g in raw.groupby("coin"):
        g = g.drop_duplicates("slot").set_index("slot").sort_index()
        grid = pd.RangeIndex(g.index.min(), g.index.max() + SLOT, SLOT)
        g = g.reindex(grid)                                 # a missing slot is NaN, and stays so
        mark, oi = g["mark"], g["open_interest"]
        f = pd.DataFrame({"coin": coin, "slot": grid, "mark": mark.values, "day_volume": g["day_volume"].values,
                          "r": (mark / mark.shift(1) - 1).values, "d": (oi / oi.shift(1) - 1).values,
                          "d1h": (oi / oi.shift(12) - 1).values})
        for name, k in HORIZONS.items():
            f[f"fwd_{name}"] = 1e4 * (mark.shift(-k) / mark - 1).values
        out.append(f)
    p = pd.concat(out, ignore_index=True)
    p = p[np.isfinite(p["r"]) & np.isfinite(p["d"]) & (p["mark"] > 0)]
    p["tier"] = [tier_of(v) for v in p["day_volume"]]
    return p


def events(p: pd.DataFrame) -> pd.DataFrame:
    lo = p.groupby("coin")["r"].transform(lambda x: np.percentile(x, TAIL))
    hi = p.groupby("coin")["r"].transform(lambda x: np.percentile(x, 100 - TAIL))
    p = p.copy()
    p["kind"] = np.where(p["r"] <= lo, "fall", np.where(p["r"] >= hi, "rise", ""))
    return p[p["kind"] != ""]


def line(label: str, x: pd.DataFrame, col: str) -> str:
    v = x[col].dropna()
    if len(v) < MIN_EVENTS:
        return f"  {label:<28} n={len(v):5d}   (fewer than {MIN_EVENTS})"
    s = trade_weighted_nw(v, x.loc[v.index, "slot"], lags=1)
    return (f"  {label:<28} n={len(v):5d}  slots={s['days']:4d}  mean={s['mean']:+8.1f} bps  t={s['t']:+5.2f}  "
            f"hit={(v > 0).mean():.2f}")


def report(ev: pd.DataFrame, title: str) -> None:
    print(f"\n== {title}")
    for kind in ("fall", "rise"):
        e = ev[ev["kind"] == kind]
        print(f"-- {kind}s: {len(e)} events, median 5-minute move {e['r'].median() * 1e4:+.0f} bps")
        for h in HORIZONS:
            print(f" forward {h}:")
            print(line("all", e, f"fwd_{h}"))
            print(line("closing (d < 0)", e[e["d"] < 0], f"fwd_{h}"))
            print(line("opening (d > 0)", e[e["d"] > 0], f"fwd_{h}"))
            print(line("closing hard (d <= -1%)", e[e["d"] <= -FINE], f"fwd_{h}"))
            print(line("opening hard (d >= +1%)", e[e["d"] >= FINE], f"fwd_{h}"))


def main() -> int:
    raw = load()
    slots = sorted(raw["slot"].unique())
    print(f"explored: {len(slots)} slots, {pd.Timestamp(slots[0], unit='s', tz='UTC')} to "
          f"{pd.Timestamp(slots[-1], unit='s', tz='UTC')}, {raw['coin'].nunique()} coins; sealed from {SEALED_FROM}")
    p = panel(raw)
    ev = events(p)
    print(f"panel rows {len(p)}; events {len(ev)} ({(ev['kind'] == 'fall').sum()} falls, {(ev['kind'] == 'rise').sum()} rises); "
          f"independent hours about {len(slots) / 12:.0f}")
    report(ev, "whole panel")
    report(ev[ev["coin"].isin(["BTC", "ETH"])], "BTC and ETH")
    for tier in ("≥$50M", "$5M–$50M", "<$5M"):
        report(ev[ev["tier"] == tier], f"tier {tier}")
    print("\n== the second look: the hour before the event (OI change over the previous 12 slots, split at the coin median)")
    e = ev[np.isfinite(ev["d1h"])].copy()
    med = e.groupby("coin")["d1h"].transform("median")
    for kind in ("fall", "rise"):
        for h in ("1h", "4h"):
            k = e[e["kind"] == kind]
            print(f"-- {kind}s, forward {h}:")
            print(line("crowded hour before", k[k["d1h"] > med[k.index]], f"fwd_{h}"))
            print(line("thinning hour before", k[k["d1h"] <= med[k.index]], f"fwd_{h}"))
            print(line("closing, crowded before", k[(k["d"] < 0) & (k["d1h"] > med[k.index])], f"fwd_{h}"))
            print(line("closing, thinning before", k[(k["d"] < 0) & (k["d1h"] <= med[k.index])], f"fwd_{h}"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
