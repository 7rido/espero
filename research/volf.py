"""#66 (research/PREREGISTRATION_VOLF.md): a HAR forecast of next week's variance against the trailing variance the
books size with.

    .venv/bin/python research/volf.py --design    # files through 2022-12 only; writes research/volf_design_run.txt
    .venv/bin/python research/volf.py --holdout   # once, after the pre-registration; writes research/volf_run.txt

Read-only: data/lows/ (Binance USD-M 5-minute klines, fetched by research/lows.py), data/settle/funding/ and
data/oi/. A month or a day that is not on disk is missing; nothing is downloaded and nothing under data/ is written.
The design run refuses to open a kline file after 2022-12, skips every open-interest day after 2022-12-31 unopened
and drops every funding settlement after 2022-12-31 on load. The holdout run refuses unless
PREREGISTRATION_VOLF.md is committed and unchanged, and unless no holdout output exists yet.
"""
from __future__ import annotations

import argparse
import gzip
import io
import json
import math
import subprocess
import sys
import zipfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Dict, List, Tuple

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from espero import liq as lq  # noqa: E402
from espero import lows as lw  # noqa: E402
from espero import trials  # noqa: E402
from espero import volf as vf  # noqa: E402
from espero.xs import UNIVERSE  # noqa: E402

LOWS = ROOT / "data" / "lows"
FUNDING = ROOT / "data" / "settle" / "funding"
OI = ROOT / "data" / "oi"
PREREG = ROOT / "research" / "PREREGISTRATION_VOLF.md"
DESIGN_OUT = ROOT / "research" / "volf_design_run.txt"
HOLDOUT_OUT = ROOT / "research" / "volf_run.txt"
SERIES_OUT = ROOT / "research" / "volf_series.csv"
KLINE_COLS = ["open_time", "open", "high", "low", "close", "volume", "close_time", "quote_volume",
              "count", "taker_buy_volume", "taker_buy_quote_volume", "ignore"]
JUDGED = ("fail", "pass", "provisional", "exploratory")     # research/fdr_rescore.py's family
FUND_FLOOR = 1e-6
WORKERS = 6


# ----------------------------------------------------------------------------------------------- inputs
def month_klines(sym: str, month: str, design: bool) -> pd.DataFrame | None:
    if not vf.readable(month, design):
        raise SystemExit(f"refused: this run opens no kline file after its last month ({sym} {month})")
    path = LOWS / sym / f"{month}.zip"
    if not path.exists():
        return None
    with zipfile.ZipFile(path) as z:
        text = z.read(z.namelist()[0]).decode()
    header = text.split(",", 1)[0].strip() == "open_time"
    df = pd.read_csv(io.StringIO(text), header=0 if header else None)
    df.columns = KLINE_COLS
    return df


def bars(sym: str, last_month: str, design: bool) -> pd.DataFrame:
    frames = []
    for m in vf.months_through(last_month):
        k = month_klines(sym, m, design)
        if k is not None:
            frames.append(k)
    return lw.bars(pd.concat(frames, ignore_index=True)) if frames else pd.DataFrame()


def funding_daily(sym: str, last_day: pd.Timestamp) -> pd.Series:
    """Each UTC day's summed |funding rate| over the settlements stamped inside it; later settlements dropped."""
    path = FUNDING / f"{sym}.json"
    if not path.exists():
        return pd.Series(dtype=float)
    t, r = [], []
    for row in json.loads(path.read_text()):
        try:
            t.append(int(row["fundingTime"]))
            r.append(abs(float(row["fundingRate"])))
        except (KeyError, TypeError, ValueError):
            continue
    day = pd.to_datetime(np.asarray(t, dtype="int64") // 1000 // vf.DAY_S * vf.DAY_S, unit="s")
    s = pd.Series(r, index=day, dtype=float)
    s = s[s.index <= last_day]
    return s.groupby(level=0).sum()


def oi_daily(sym: str, last_day: pd.Timestamp) -> pd.Series:
    """Open interest in coins at each UTC day's last row; a day after `last_day` is never opened."""
    folder = OI / sym
    out: Dict[pd.Timestamp, float] = {}
    if not folder.exists():
        return pd.Series(dtype=float)
    for p in sorted(folder.glob("*.csv.gz")):
        day = pd.Timestamp(p.name[:10])
        if day > last_day:
            continue
        try:
            with gzip.open(p, "rt") as f:
                lines = [ln for ln in f.read().splitlines() if ln.strip()]
        except (OSError, EOFError):
            continue
        if len(lines) < 2 or not lines[-1].startswith(p.name[:10]):
            continue
        try:
            out[day] = float(lines[-1].split(",")[2])
        except (IndexError, ValueError):
            continue
    return pd.Series(out, dtype=float).sort_index()


# ------------------------------------------------------------------------------------------------- plan
def plan_for(design: bool) -> dict:
    if design:
        last_day, last_month = vf.DESIGN_LAST_DAY, vf.DESIGN_LAST_MONTH
        week = vf.sundays(vf.DESIGN_FIRST_ORIGIN, last_day)
        month = vf.month_ends(pd.Timestamp("2020-12-31"), last_day)
        day = list(pd.date_range("2020-12-31", last_day - pd.Timedelta(days=1), freq="D"))
    else:
        last_day, last_month = vf.HOLDOUT_LAST_DAY, vf.HOLDOUT_LAST_MONTH
        week = vf.sundays(vf.HOLDOUT_FIRST_ORIGIN, last_day)
        month = vf.month_ends(pd.Timestamp("2022-12-31"), last_day)
        day = list(pd.date_range("2022-12-31", last_day - pd.Timedelta(days=1), freq="D"))
    return {"last_day": last_day, "last_month": last_month, "week": week, "month": month, "day": day}


def coin(c: str, design: bool, plan: dict) -> Tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, dict]:
    sym = lq.symbol("binance-futures", c)
    meta = {"coin": c, "symbol": sym}
    b = bars(sym, plan["last_month"], design)
    if b.empty:
        meta["status"] = "no bars"
        return pd.DataFrame(), pd.DataFrame(), pd.DataFrame(), meta
    d = vf.daily(b)
    d = d[d.index <= plan["last_day"]]
    rv, ret = d["rv"], d["ret"]
    feats = vf.har_features(rv)
    b30, b90 = vf.trailing_var(ret, vf.TRAIL_WEEK), vf.trailing_var(ret, vf.TRAIL_MONTH)
    y7, y30, y1 = (vf.forward_mean_sq(ret, h) for h in (vf.WEEK, vf.MONTH_TRAIN_H, 1))
    wk, mo, dy = plan["week"], plan["month"], plan["day"]

    fund = funding_daily(sym, plan["last_day"]).reindex(d.index)
    oi = oi_daily(sym, plan["last_day"]).reindex(d.index)
    extra = feats.assign(f7=np.log(fund.rolling(7, min_periods=7).mean() + FUND_FLOOR),
                         oi7=np.log(oi / oi.shift(7)).abs())

    def at(s: pd.Series, origins: List[pd.Timestamp]) -> np.ndarray:
        return s.reindex(origins).to_numpy(dtype=float)

    week = pd.DataFrame({
        "origin": wk, "coin": c, "y": at(y7, wk), "bench": at(b30, wk),
        "har": at(vf.forecasts(feats, y7, wk, vf.WEEK), wk),
        "cal": at(vf.forecasts(np.log(b30).to_frame("b30"), y7, wk, vf.WEEK), wk),
        "harx": at(vf.forecasts(extra, y7, wk, vf.WEEK), wk)})
    month = pd.DataFrame({
        "origin": mo, "coin": c, "y": [vf.month_target(ret, o) for o in mo], "bench": at(b90, mo),
        "har": at(vf.forecasts(feats, y30, mo, vf.MONTH_TRAIN_H), mo)})
    day = pd.DataFrame({
        "origin": dy, "coin": c, "y": at(y1, dy), "bench": at(b30, dy), "har": at(vf.forecasts(feats, y1, dy, 1), dy)})
    done = d.index[d["complete"]]
    meta.update(status="ok", first=str(done.min().date()) if len(done) else "-", complete_days=int(len(done)),
                calendar_days=int(len(d)), funding_days=int(fund.notna().sum()), oi_days=int(oi.notna().sum()))
    return week, month, day, meta


# --------------------------------------------------------------------------------------------- judgment
def committed_unchanged(path: Path) -> bool:
    rel = str(path.relative_to(ROOT))
    tracked = subprocess.run(["git", "ls-files", "--error-unmatch", rel], cwd=ROOT, capture_output=True)
    changed = subprocess.run(["git", "diff", "--quiet", "HEAD", "--", rel], cwd=ROOT)
    return tracked.returncode == 0 and changed.returncode == 0


def ledger_q(p66: float) -> Tuple[float, int]:
    """#66's Benjamini-Hochberg q over every judged test in the ledger plus #66, a missing p counted as 1."""
    d = pd.read_csv(ROOT / "research" / "trials.csv", dtype={"test": str})
    judged = d[d["status"].isin(JUDGED) & (d["test"] != "66")]
    ps = pd.to_numeric(judged["p_from_t"], errors="coerce").fillna(1.0).to_numpy()
    return float(trials.bh(np.r_[ps, p66])[-1]), len(ps) + 1


# --------------------------------------------------------------------------------------------- printing
def gap_line(name: str, cells: pd.DataFrame, a: str, b: str) -> str:
    d = vf.per_origin(cells, a, b)
    n_cells = len(vf.scored(cells, a, b))
    if not len(d):
        return f"  {name:<46} no cells"
    return (f"  {name:<46} origins {len(d):>5}  cells {n_cells:>6}  mean {d.mean():+.4f}  "
            f"t {vf.t_of(d):+6.2f}  (lags {vf.nw_lags(len(d))})")


def report(week: pd.DataFrame, month: pd.DataFrame, day: pd.DataFrame, metas: List[dict], design: bool) -> List[str]:
    out: List[str] = []
    say = out.append
    first = vf.evaluate(week, month)
    q, m = (None, 0) if design else ledger_q(first["p"])
    ev = vf.evaluate(week, month, q)
    say("#66 volatility forecast: " + ("DESIGN window, files through 2022-12" if design else "HOLDOUT, read once"))
    say("")
    ok = [x for x in metas if x["status"] == "ok"]
    say(f"coins with bars: {len(ok)} of {len(metas)}; without: {[x['coin'] for x in metas if x['status'] != 'ok']}")
    for x in ok:
        say(f"  {x['coin']:<5} {x['symbol']:<13} first complete day {x['first']}  complete {x['complete_days']:>5} "
            f"of {x['calendar_days']:>5} days  funding days {x['funding_days']:>5}  OI days {x['oi_days']:>5}")
    say("")
    say("Primary: weekly origins at Sunday's close, the next 7 days' mean squared daily return,")
    say("QLIKE(#8's 30-day trailing variance) - QLIKE(HAR), averaged over coins at each origin; positive = HAR better")
    say(f"  origins {ev['origins']}  cells {ev['cells']}  mean gap {ev['mean']:+.4f}  t {ev['t']:+.2f} "
        f"(Newey-West, {ev['lags']} lags)  p {ev['p']:.3g}")
    if not design:
        say(f"  q (Benjamini-Hochberg over {m} judged tests including #66) {q:.4g}")
    say(f"  halves: earlier {ev['first_half']:+.4f}  later {ev['second_half']:+.4f}")
    say(f"  breadth: {ev['breadth']:.3f} of {ev['breadth_coins']} coins with >= {vf.MIN_COIN_ORIGINS} weekly cells "
        f"have a positive mean gap")
    say("Monthly: month-end origins, the next calendar month, #63's 90-day trailing variance against the HAR")
    say(f"  origins {ev['month_origins']}  mean gap {ev['month_mean']:+.4f}  t {ev['month_t']:+.2f}")
    say(f"Outcome: {ev['outcome']}" + (f"  checks {ev.get('checks')}" if "checks" in ev else ""))
    say("")
    say("Information only, deciding nothing:")
    say(gap_line("(a) daily: next day, #8's 30-day vs HAR", day, "bench", "har"))
    say(f"  (b) weekly MSE on the variance, trailing over HAR: {vf.mse_ratio(week, 'bench', 'har'):.4f}")
    say(gap_line("(c) calibrated trailing vs HAR", week, "cal", "har"))
    say(gap_line("    #8's 30-day vs calibrated trailing", week, "bench", "cal"))
    hx = vf.scored(week, "har", "harx")
    say(gap_line("(d) HAR vs HAR + funding + open interest", week, "har", "harx")
        + f"  coins {hx['coin'].nunique() if len(hx) else 0}")
    for name, col in (("#8's 30-day", "bench"), ("HAR", "har")):
        s = vf.sizing(vf.scored(week, "bench", "har"), col)
        say(f"  (e) sizing with {name:<12} cells {s['cells']:>6}  mean |log realized/target vol| "
            f"{s['mean_abs_log_ratio']:.4f}  over 2x target {s['share_over_2x']:.4f}  "
            f"week-to-week |change| in log scale {s['scale_change']:.4f}")
    c = week.reset_index(drop=True)
    years = vf.by_group(c, "bench", "har", c["origin"].dt.year)
    tiers = vf.by_group(c, "bench", "har", c["coin"].map(lambda x: "BTC+ETH" if x in vf.LIQUID else "other"))
    say("  (f) by year of origin: " + "; ".join(f"{k} {r['mean']:+.4f} ({int(r['size'])})" for k, r in years.iterrows()))
    say("      by tier: " + "; ".join(f"{k} {r['mean']:+.4f} ({int(r['size'])})" for k, r in tiers.iterrows()))
    sc = vf.scored(week, "bench", "har")
    say(f"  (g) mean QLIKE: #8's 30-day {vf.qlike(sc['y'], sc['bench']).mean():.4f}  "
        f"HAR {vf.qlike(sc['y'], sc['har']).mean():.4f}")
    per_coin = sc.groupby("coin")["d"].agg(["mean", "size"]).sort_values("mean")
    say("  (h) coins whose mean gap is negative: "
        + (", ".join(f"{k} {r['mean']:+.4f} ({int(r['size'])})" for k, r in per_coin[per_coin["mean"] <= 0].iterrows())
           or "none"))
    if design:
        d = vf.per_origin(week, "bench", "har")
        n_hold = len(vf.sundays(vf.HOLDOUT_FIRST_ORIGIN, vf.HOLDOUT_LAST_DAY))
        t = vf.t_of(d)
        say("")
        say(f"Power: the design's weekly gap has mean {d.mean():+.4f}, sd {d.std(ddof=1):.4f} over {len(d)} origins, "
            f"t {t:+.2f}. At the holdout's {n_hold} origins, the same effect and dependence give t about "
            f"{t * math.sqrt(n_hold / len(d)):+.2f}.")
    return out


def main(argv: List[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--design", action="store_true", help="files through 2022-12 only; reruns allowed")
    g.add_argument("--holdout", action="store_true", help="once, after the pre-registration is committed")
    a = ap.parse_args(argv)
    design = bool(a.design)
    if not design:
        if not committed_unchanged(PREREG):
            print("refused: research/PREREGISTRATION_VOLF.md must be committed and unchanged before the holdout")
            return 2
        if HOLDOUT_OUT.exists():
            print(f"refused: {HOLDOUT_OUT.relative_to(ROOT)} exists; the holdout is read once")
            return 2
    plan = plan_for(design)
    with ThreadPoolExecutor(WORKERS) as ex:
        results = list(ex.map(lambda c: coin(c, design, plan), UNIVERSE))
    week = pd.concat([r[0] for r in results if len(r[0])], ignore_index=True)
    month = pd.concat([r[1] for r in results if len(r[1])], ignore_index=True)
    day = pd.concat([r[2] for r in results if len(r[2])], ignore_index=True)
    text = "\n".join(report(week, month, day, [r[3] for r in results], design)) + "\n"
    (DESIGN_OUT if design else HOLDOUT_OUT).write_text(text)
    if not design:
        d = vf.per_origin(week, "bench", "har")
        n = vf.scored(week, "bench", "har").groupby("origin").size()
        pd.DataFrame({"gap": d, "coins": n}).rename_axis("origin").to_csv(SERIES_OUT, float_format="%.6g")
    print(text, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
