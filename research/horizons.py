"""Hypothesis #43 — at which holding period do the repo's real signals pay?

    python research/horizons.py          # reads the bar and funding caches (fetches missing bars), then the tables

Frozen in research/PREREGISTRATION_HORIZONS.md. The verdict is written by hand into RESULTS_HORIZONS.md.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Dict

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "research"))
import bids as rb  # noqa: E402  research/bids.py: #30's bar loader

from espero import costs, fillcost  # noqa: E402
from espero import horizons as hz  # noqa: E402
from espero import liq as lq  # noqa: E402
from espero import lows as lw  # noqa: E402

COINS = ["BTC", "ETH", "SOL", "XRP", "DOGE", "LINK", "WLD", "ARB", "OP", "TIA"]
MAJORS = ["BTC", "ETH", "SOL", "XRP"]
SIGNALS = ["S1", "S2", "S3", "S4"]
MONTHS = [m.strftime("%Y-%m") for m in pd.period_range("2020-01", "2026-09", freq="M").to_timestamp()]
OUT = ROOT / "research" / "horizons_cells.csv"
SUMMARY = ROOT / "research" / "horizons_summary.json"


def load_bars(c: str) -> pd.DataFrame:
    sym = lq.symbol("binance-futures", c)
    frames = []
    for m in MONTHS:
        data = rb.blob([rb.LOWS / sym / f"{m}.zip", rb.LEVETF / sym / f"{m}.zip"], rb.CACHE / sym / f"{m}.zip",
                       rb.URL_MONTH.format(sym=sym, month=m))
        if data:
            frames.append(rb.frame(data))
    for day in rb.DAYS:
        data = rb.blob([rb.LEVETF / sym / "daily" / f"{day}.zip"], rb.CACHE / sym / "daily" / f"{day}.zip",
                       rb.URL_DAY.format(sym=sym, day=day))
        if data:
            frames.append(rb.frame(data))
    return lw.bars(pd.concat(frames, ignore_index=True))


def load_funding(c: str) -> pd.DataFrame:
    sym = lq.symbol("binance-futures", c)
    rows = json.loads((ROOT / "data" / "settle" / "funding" / f"{sym}.json").read_text())
    raw = pd.DataFrame({"ts": [int(r["fundingTime"]) // 1000 // 60 * 60 for r in rows],
                        "rate": [float(r["fundingRate"]) for r in rows]}).drop_duplicates("ts")
    return raw.merge(fillcost.settlements(rows), on="ts", how="left")


def regenerate_s1(bars: Dict[str, pd.DataFrame]) -> Dict[str, pd.DataFrame]:
    """S1 on the combined bars; asserted equal to the published file on 2020-01 → 2026-03 first."""
    pub = pd.read_csv(ROOT / "research" / "lows_events.csv.gz")
    out = {}
    for c, b in bars.items():
        old = lw.events(b, "down", lw.excluded_days())
        want = pub[(pub["coin"] == c) & (pub["direction"] == "down")]
        if not np.array_equal(old["ts"].to_numpy(), want["ts"].to_numpy()):
            raise SystemExit(f"S1 regeneration differs from lows_events for {c}: {len(old)} vs {len(want)}")
        ev = lw.events(b, "down", lw.excluded_days("2019-12-01", "2026-11-01"), last=hz.DATA_END)
        out[c] = pd.DataFrame({"ts": ev["ts"].to_numpy(dtype="int64"), "side": 1.0})
    print(f"S1 regeneration: identical to research/lows_events.csv.gz on 2020-01 → 2026-03 for all {len(bars)} coins")
    return out


def s5_events() -> Dict[str, pd.DataFrame]:
    ev = lq.usable(pd.read_csv(ROOT / "research" / "liq2_events.csv.gz"))
    ev = ev[(lq.tag(ev) == "forced") & (ev["direction"] == -1)]
    return {c: pd.DataFrame({"ts": g["ts"].to_numpy(dtype="int64") + hz.BAR_S, "side": 1.0})
            for c, g in ev.groupby("coin") if c in COINS}


def run() -> None:
    print(f"#43 — the horizon map. Coins: {', '.join(COINS)}. Bar (selection, information): t >= {hz.BAR}")
    bars = {c: load_bars(c) for c in COINS}
    fund = {c: load_funding(c) for c in COINS}
    for c in COINS:
        b = bars[c]
        print(f"  {c}: bars {pd.to_datetime(b.index[0], unit='s'):%Y-%m-%d} → {pd.to_datetime(b.index[-1], unit='s'):%Y-%m-%d}"
              f", funding rows {len(fund[c])}")

    sel_end = pd.Timestamp(hz.SELECT_END, tz="UTC").value // 10 ** 9 + hz.DAY_S
    print("\n== Power, from unconditional returns in the selection window (before any signal outcome)")
    for name, h in hz.HORIZONS.items():
        sds, ns = [], 0
        for c in COINS:
            sd, n = hz.unconditional_sd(bars[c], h, sel_end)
            if np.isfinite(sd):
                sds.append(sd)
                ns += n
        sd = float(np.mean(sds))
        print(f"  {name:>4}: sd {1e4 * sd:7.1f} bps, non-overlapping windows {ns:>7,}, "
              f"MDE {1e4 * hz.mde(sd, ns):6.2f} bps (all coins pooled), "
              f"{1e4 * hz.mde(sd, ns / len(COINS)):6.2f} bps (one coin's worth)")

    events = {"S1": regenerate_s1(bars),
              "S2": {c: hz.settlement_events(fund[c].dropna(subset=["rate8"]), "S2") for c in COINS},
              "S3": {c: hz.settlement_events(fund[c].dropna(subset=["rate8"]), "S3") for c in COINS},
              "S4": {c: hz.trend_events(bars[c]) for c in COINS},
              "S5": s5_events()}

    rows, store = [], {}
    for sig, per_coin in events.items():
        for name, h in hz.HORIZONS.items():
            parts, parts_all, parts_bn = [], [], []
            for c, ev in per_coin.items():
                if not len(ev):
                    continue
                st, rt = fund[c]["ts"].to_numpy(), fund[c]["rate"].to_numpy()
                rtrip = costs.round_trip("hyperliquid", c) / 1e4
                parts.append(hz.trades(ev, bars[c], h, rtrip, st, rt).assign(coin=c))
                parts_all.append(hz.trades(ev, bars[c], h, rtrip, st, rt, one=False).assign(coin=c))
                if c in MAJORS:
                    parts_bn.append(hz.trades(ev, bars[c], h, costs.round_trip("binance", c) / 1e4, st, rt)
                                    .assign(coin=c))
            tr = pd.concat(parts, ignore_index=True) if parts else pd.DataFrame()
            if not len(tr):
                continue
            ta = pd.concat(parts_all, ignore_index=True)
            tb = pd.concat(parts_bn, ignore_index=True) if parts_bn else tr.iloc[:0]
            store[(sig, name)] = tr
            sel, hold = hz.windows(tr)
            row = {"signal": sig, "h": name}
            for tag, frame in (("sel", sel), ("hold", hold)):
                for k, v in hz.stats(frame, h).items():
                    row[f"{tag}_{k}"] = v
                row[f"{tag}_gross"] = hz.stats(frame, h, "gross")["mean"]
                row[f"{tag}_funding"] = hz.stats(frame, h, "funding")["mean"]
                row[f"{tag}_spot"] = hz.stats(frame, h, "net_spot")["mean"]
            s_all, _ = hz.windows(ta)
            row["sel_all_events"] = hz.stats(s_all, h)["mean"]
            s_bn, _ = hz.windows(tb)
            row["sel_binance_majors"] = hz.stats(s_bn, h)["mean"]
            rows.append(row)
    cells = pd.DataFrame(rows)
    cells.to_csv(OUT, index=False, float_format="%.6g")

    pd.set_option("display.width", 220)
    for sig in [*SIGNALS, "S5"]:
        c = cells[cells.signal == sig]
        label = {"S1": "#20 new-low bounce, long", "S2": "#38 shorts pay hard, short",
                 "S3": "carry, receive funding", "S4": "trend control, long",
                 "S5": "#26 forced down-breaks, long (information; 2023-06 → 2024-10)"}[sig]
        print(f"\n== {sig}: {label} — selection window (holds ending by {hz.SELECT_END}), bps per trade")
        print(c[["h", "sel_trades", "sel_days", "sel_hit", "sel_gross", "sel_funding", "sel_mean", "sel_t",
                 "sel_spot", "sel_all_events", "sel_binance_majors"]]
              .rename(columns={"sel_mean": "net", "sel_t": "t", "sel_spot": "net_spot", "sel_gross": "gross",
                               "sel_funding": "funding", "sel_hit": "hit", "sel_trades": "trades", "sel_days": "days",
                               "sel_all_events": "net_overlapping", "sel_binance_majors": "net_binance_majors"})
              .to_string(index=False, float_format=lambda v: f"{v:.2f}"))
        clears = c[(c.sel_mean > 0) & (c.sel_t >= hz.BAR)]["h"].tolist()
        print(f"  cells clearing the deflated bar {hz.BAR}: {hz.fmt_list(clears)}")

    print("\n== Selection: the horizon each signal carries (largest t among net > 0, t >= 2)")
    chosen = {}
    for sig in SIGNALS:
        c = cells[cells.signal == sig].set_index("h")
        h = hz.choose({k: {"mean": r.sel_mean, "t": r.sel_t} for k, r in c.iterrows()})
        chosen[sig] = h
        print(f"  {sig}: {h if h else 'not carried'}")

    print(f"\n== Confirmation: trades entering {hz.HOLDOUT_START} → {hz.DATA_END}, at the carried horizon")
    carried = {s: h for s, h in chosen.items() if h}
    holds, pvals = {}, {}
    for sig, name in carried.items():
        tr = store[(sig, name)]
        _, hold = hz.windows(tr)
        h = hz.HORIZONS[name]
        st = hz.stats(hold, h)
        holds[sig] = (hold, st)
        pvals[sig] = hz.p_one_sided(st["t"])
    holm = hz.holm(pvals)
    summary = {"chosen": chosen, "confirmed": {}}
    for sig, name in carried.items():
        hold, st = holds[sig]
        h = hz.HORIZONS[name]
        sel = cells[(cells.signal == sig) & (cells.h == name)].iloc[0]
        h1 = hz.stats(hold[hold["day"] < hz.HOLDOUT_SPLIT], h)
        h2 = hz.stats(hold[hold["day"] >= hz.HOLDOUT_SPLIT], h)
        c = hz.confirm(sig, name, {"mean": sel.sel_mean}, st, h1, h2, holm[sig])
        ok = all(c.values())
        summary["confirmed"][sig] = {"h": name, "ok": ok, **c, "hold": st, "h1": h1["mean"], "h2": h2["mean"],
                                     "sel": float(sel.sel_mean), "p": pvals[sig]}
        print(f"  {sig} at {name}: selection net {sel.sel_mean:+.1f} bps (t {sel.sel_t:.2f}); holdout net "
              f"{st['mean']:+.1f} bps (t {st['t']:.2f}, p {pvals[sig]:.4f}, {st['trades']} trades, hit {st['hit']:.1%}); "
              f"halves {h1['mean']:+.1f} / {h2['mean']:+.1f}")
        print(f"      holm {'met' if c['holm'] else 'no'} · halves {'met' if c['halves'] else 'no'} · "
              f"no collapse (>= 1/3 of selection) {'met' if c['no_collapse'] else 'no'} · "
              f"unseen {'yes' if c['unseen'] else 'NO (seen before the pre-registration)'}  →  "
              f"{'CONFIRMED' if ok else 'not confirmed'}")
    print("\nVERDICT:", "confirmed: " + hz.fmt_list([s for s, v in summary["confirmed"].items() if v["ok"]]))

    print("\n== Information: holdout net at every horizon (not a test; the choice was made on selection)")
    print(cells.pivot_table(index="signal", columns="h", values="hold_mean")[list(hz.HORIZONS)]
          .round(1).to_string())
    SUMMARY.write_text(json.dumps(summary, indent=1, default=float))


if __name__ == "__main__":
    run()
