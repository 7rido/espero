"""#67 (research/PREREGISTRATION_LISTDRIFT.md): short a new Binance USD-M perp the day after it lists, long BTC.

    .venv/bin/python research/listdrift.py --events    # metadata only: writes research/listdrift_events.csv
    .venv/bin/python research/listdrift.py --design    # files through 2024-12 only; writes listdrift_design_run.txt
    .venv/bin/python research/listdrift.py --holdout   # once, after the pre-registration; writes listdrift_run.txt

Prices and volumes come from the point-in-time store's daily klines (`data/pit/klines_1d`, delisted symbols
included), read-only. Funding comes from Binance's public archive through `espero.pit.fetch_file`, each file checked
against Binance's SHA-256, cached in `data/cache/listdrift/` with its hash in `research/listdrift_manifest.csv`.
`--events` reads exchangeInfo captures from the Wayback Machine and the store's file names, never a price.
The design run refuses any kline or funding file after 2024-12. The holdout run refuses unless
PREREGISTRATION_LISTDRIFT.md is committed and unchanged, and unless no holdout output exists yet.
"""
from __future__ import annotations

import argparse
import gzip
import json
import math
import subprocess
import sys
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from espero import costs, pit, trials  # noqa: E402
from espero import listdrift as ld  # noqa: E402

KLINES = ROOT / "data" / "pit" / "klines_1d"
BTC_FUNDING = ROOT / "data" / "pit" / "fundingRate" / "BTCUSDT"
CACHE = ROOT / "data" / "cache" / "listdrift"
EVENTS = ROOT / "research" / "listdrift_events.csv"
MANIFEST = ROOT / "research" / "listdrift_manifest.csv"
PREREG = ROOT / "research" / "PREREGISTRATION_LISTDRIFT.md"
DESIGN_OUT = ROOT / "research" / "listdrift_design_run.txt"
HOLDOUT_OUT = ROOT / "research" / "listdrift_run.txt"
SERIES_OUT = ROOT / "research" / "listdrift_series.csv"
JUDGED = ("fail", "pass", "provisional", "exploratory")     # research/fdr_rescore.py's family
WORKERS = 8
UNCLASSIFIED_COINS = {"MBLUSDT": "COIN"}     # in no capture since 2023; MovieBloc's token, by name


# ----------------------------------------------------------------------------------------------- events
def captures() -> Dict[str, dict]:
    """symbol -> its newest exchangeInfo record since 2023, from the Wayback Machine (cached)."""
    out: Dict[str, dict] = {}
    folder = CACHE / "exinfo"
    folder.mkdir(parents=True, exist_ok=True)
    for ts, _ in sorted(pit.wayback_captures(), reverse=True):
        if ts < "20230101":
            continue
        p = folder / f"{ts}.json"
        if not p.exists():
            url = f"https://web.archive.org/web/{ts}id_/https://fapi.binance.com/fapi/v1/exchangeInfo"
            with urllib.request.urlopen(url, timeout=120) as r:
                body = r.read()
            p.write_bytes(gzip.decompress(body) if body[:2] == b"\x1f\x8b" else body)
        for s in json.loads(p.read_bytes()).get("symbols", []):
            out.setdefault(s["symbol"], {"type": s.get("underlyingType"), "contract": s.get("contractType"),
                                         "onboard_ms": s.get("onboardDate"), "capture": ts})
    for s, kind in UNCLASSIFIED_COINS.items():
        out.setdefault(s, {"type": kind, "contract": "PERPETUAL", "onboard_ms": None, "capture": "by name"})
    return out


def first_months() -> Dict[str, str]:
    """symbol -> the month of its first daily bar, from file names only."""
    out = {}
    for d in KLINES.iterdir():
        names = sorted(p.stem[:7] for p in d.glob("*.parquet"))
        if names:
            out[d.name] = names[0]
    return out


def write_events() -> pd.DataFrame:
    """Every symbol in the store: the candidates (USDT perps first traded 2023-01 or later) with their listing day
    and exclusion, and the rest with their type, which the basket needs."""
    meta = captures()
    firsts = first_months()
    ev = ld.classify(meta, firsts).assign(candidate=True)
    rest = [{"symbol": s, "first_month": m, "type": meta.get(s, {}).get("type") or "", "listing_day": None,
             "excluded": "", "candidate": False} for s, m in sorted(firsts.items()) if s not in set(ev["symbol"])]
    out = pd.concat([ev, pd.DataFrame(rest)], ignore_index=True)
    out["type"] = out["type"].fillna("")
    out["capture"] = out["symbol"].map(lambda s: meta.get(s, {}).get("capture", ""))
    out = out.sort_values(["candidate", "first_month", "symbol"], ascending=[False, True, True])
    out.to_csv(EVENTS, index=False)
    return out


def load_events() -> pd.DataFrame:
    e = pd.read_csv(EVENTS, keep_default_na=False, dtype={"excluded": str})
    e["listing_day"] = pd.to_datetime(e["listing_day"].replace("", None))
    e["candidate"] = e["candidate"].astype(str).eq("True")
    return e


# ------------------------------------------------------------------------------------------------ inputs
def readable(period: str, last_month: str) -> bool:
    return period[:7] <= last_month


def bars(symbol: str, last_month: str) -> pd.DataFrame:
    """Daily open, close and quote volume by UTC day, from files whose month is at most `last_month`."""
    files = sorted(p for p in (KLINES / symbol).glob("*.parquet") if readable(p.stem, last_month))
    if not files:
        return pd.DataFrame(columns=["open", "high", "close", "quote_volume"])
    df = pd.concat([pd.read_parquet(p, columns=["open_time", "open", "high", "close", "quote_volume"]) for p in files])
    df["day"] = pd.to_datetime(df["open_time"].astype("int64") // ld.DAY_MS * ld.DAY_MS, unit="ms")
    df = df.drop_duplicates("day", keep="last").set_index("day").sort_index()
    return df[["open", "high", "close", "quote_volume"]].astype(float)


def months_between(a: pd.Timestamp, b: pd.Timestamp) -> List[str]:
    return [p.strftime("%Y-%m") for p in pd.period_range(a, b, freq="M")]


def funding_rates(symbol: str, months: List[str], last_month: str, rows: List[dict]) -> Optional[pd.Series]:
    """Settled rates by settlement time in ms, or None if a month is missing from the archive."""
    parts = []
    for m in months:
        if not readable(m, last_month):
            raise SystemExit(f"refused: this run fetches no funding after {last_month} ({symbol} {m})")
        p = pit.store_path(CACHE, "fundingRate", symbol, m)
        if not p.exists():
            row = pit.fetch_file("fundingRate", symbol, m, store=CACHE)
            if row is None:
                return None
            rows.append(row)
        parts.append(pd.read_parquet(p, columns=["valid_time", "last_funding_rate"]))
    f = pd.concat(parts).drop_duplicates("valid_time").sort_values("valid_time")
    return pd.Series(f["last_funding_rate"].astype(float).to_numpy(), index=f["valid_time"].astype("int64").to_numpy())


def btc_funding(last_month: str) -> pd.Series:
    files = sorted(p for p in BTC_FUNDING.glob("*.parquet") if readable(p.stem, last_month))
    f = pd.concat([pd.read_parquet(p, columns=["valid_time", "last_funding_rate"]) for p in files])
    f = f.drop_duplicates("valid_time").sort_values("valid_time")
    return pd.Series(f["last_funding_rate"].astype(float).to_numpy(), index=f["valid_time"].astype("int64").to_numpy())


def save_manifest(rows: List[dict]) -> None:
    if not rows:
        return
    new = pd.DataFrame(rows)
    if MANIFEST.exists():
        old = pd.read_csv(MANIFEST)
        new = pd.concat([old, new]).drop_duplicates(["symbol", "period"], keep="first")
    new.sort_values(["symbol", "period"]).to_csv(MANIFEST, index=False)


# ------------------------------------------------------------------------------------------------ the run
def positions(ev: pd.DataFrame, hold: int, span: Tuple[pd.Timestamp, pd.Timestamp], lag: int = 1) -> pd.DataFrame:
    """The dated events whose whole position, at this hold and entry lag, lies inside the span."""
    rows = []
    for _, r in ev.iterrows():
        entry, exit_ = ld.window(r["listing_day"], hold, lag)
        if ld.inside(entry, exit_, span):
            rows.append({"symbol": r["symbol"], "listing_day": r["listing_day"], "onboard_day": r["onboard_day"],
                         "entry": entry, "exit": exit_})
    return pd.DataFrame(rows)


def run(design: bool) -> Tuple[List[str], dict]:
    span = ld.DESIGN if design else ld.HOLDOUT
    last_month = ld.DESIGN_LAST_MONTH if design else ld.HOLDOUT_LAST_MONTH
    e = load_events()
    holds = ld.HOLDS if design else (ld.CHOSEN_HOLD,) + tuple(h for h in ld.HOLDS if h != ld.CHOSEN_HOLD)
    with ThreadPoolExecutor(WORKERS) as ex:
        allbars = dict(zip(sorted(p.name for p in KLINES.iterdir()),
                           ex.map(lambda s: bars(s, last_month), sorted(p.name for p in KLINES.iterdir()))))
    allbars = {s: b for s, b in allbars.items() if len(b)}
    events = ld.dated(e[e["candidate"] & e["excluded"].eq("")], {s: b.index[0] for s, b in allbars.items()})
    plans = {h: positions(events, h, span) for h in holds}
    plans["lag2"] = positions(events, holds[0], span, lag=2)
    btc = allbars["BTCUSDT"]
    btc_rates = btc_funding(last_month)
    volume = pd.DataFrame({s: b["quote_volume"] for s, b in allbars.items()})
    first_day = {s: b.index[0] for s, b in allbars.items()}
    types = dict(zip(e["symbol"], e["type"]))
    not_coin = {s for s, t in types.items() if t and t != "COIN"}
    basket_excluded = ld.MAJORS | ld.PEGGED | ld.INDEX | not_coin | {s for s in allbars if not s.endswith("USDT")}
    basket_excluded |= {s for s in allbars if "_" in s}

    rows: List[dict] = []
    need = {}
    for key, p in plans.items():
        for _, r in p.iterrows():
            need.setdefault(r["symbol"], set()).update(months_between(r["entry"], r["exit"]))

    def fetch(sym: str):
        return sym, funding_rates(sym, sorted(need[sym]), last_month, rows)

    with ThreadPoolExecutor(WORKERS) as ex:
        rates = dict(ex.map(fetch, sorted(need)))
    save_manifest(rows)

    lc = ld.cost_per_side()
    hc = costs.leg("binance", "BTC", "taker") / 1e4
    chosen: Dict[Tuple[pd.Timestamp, str], List[str]] = {}

    def members_at(entry: pd.Timestamp, s: str) -> List[str]:
        if (entry, s) not in chosen:
            chosen[(entry, s)] = ld.basket_members(volume, first_day, entry, basket_excluded | {s})
        return chosen[(entry, s)]

    results = {}
    for key, p in plans.items():
        net, gross, unhedged, abn, other, info, covered, would = {}, {}, {}, {}, {}, {}, {}, {}
        for _, r in p.iterrows():
            s, entry, exit_ = r["symbol"], r["entry"], r["exit"]
            b, fr = allbars.get(s), rates.get(s)
            if b is None or fr is None:
                info[s] = "no bars" if b is None else "funding missing"
                continue
            level = ld.cover_level(b, r["listing_day"])
            reg = level if ld.COVER else None                      # the registered trade's cover, if any
            ev = ld.event(b, btc, entry, exit_, fr, btc_rates, lc, hc, cover=reg)
            if ev.empty:
                info[s] = "no entry bar"
                continue
            net[s] = ev
            covered[s] = ld.cover_exit(b, entry, exit_, reg)
            would[s] = ld.cover_exit(b, entry, exit_, level)
            gross[s] = ld.event(b, btc, entry, exit_, fr, btc_rates, 0.0, 0.0, with_funding=False, cover=reg)
            other[s] = ld.event(b, btc, entry, exit_, fr, btc_rates, lc, hc, cover=None if ld.COVER else level)
            stop = covered[s]
            short = ld.leg(b, entry, stop, -1)
            f_short = ld.funding(fr, short, entry, ld.close_of(short, stop), -1).reindex(short.index).fillna(0.0)
            cst = pd.Series(0.0, index=short.index)
            cst.iloc[0] -= lc
            cst.iloc[-1] -= lc
            unhedged[s] = pd.DataFrame({"net": short["pnl"] + f_short + cst})
            abn[s] = ld.abnormal(b, {m: allbars[m] for m in members_at(entry, s)}, entry, exit_, cover=reg)
        results[key] = {"plan": p, "net": net, "gross": gross, "unhedged": unhedged, "abnormal": abn, "dropped": info,
                        "other": other, "covered": covered, "would": would, "bars": allbars}
    return report(results, design, lc, hc, e, allbars), results


# ------------------------------------------------------------------------------------------------ judgment
def committed_unchanged(path: Path) -> bool:
    rel = str(path.relative_to(ROOT))
    tracked = subprocess.run(["git", "ls-files", "--error-unmatch", rel], cwd=ROOT, capture_output=True)
    changed = subprocess.run(["git", "diff", "--quiet", "HEAD", "--", rel], cwd=ROOT)
    return tracked.returncode == 0 and changed.returncode == 0


def ledger_q(p: float) -> Tuple[float, int]:
    """#67's Benjamini-Hochberg q over every judged test in the ledger plus #67, a missing p counted as 1."""
    d = pd.read_csv(ROOT / "research" / "trials.csv", dtype={"test": str})
    judged = d[d["status"].isin(JUDGED) & (d["test"] != "67")]
    ps = pd.to_numeric(judged["p_from_t"], errors="coerce").fillna(1.0).to_numpy()
    return float(trials.bh(np.r_[ps, p])[-1]), len(ps) + 1


# ------------------------------------------------------------------------------------------------ printing
def line(name: str, events: Dict[str, pd.DataFrame], column: str = "net") -> str:
    cal = ld.calendar(events, column)["mean"]
    per = ld.totals(events, column)
    if not len(per):
        return f"  {name:<44} no positions"
    return (f"  {name:<44} positions {len(per):>4}  days {int(cal.notna().sum()):>4}  daily mean {cal.mean() * 1e4:+7.2f} bps"
            f"  t {ld.t_of(cal):+6.2f}  mean position {per.mean() * 100:+7.2f}%  median {per.median() * 100:+7.2f}%")


def report(results: dict, design: bool, lc: float, hc: float, e: pd.DataFrame, allbars: dict) -> List[str]:
    out: List[str] = []
    say = out.append
    say("#67 listing drift: " + ("DESIGN, files through 2024-12" if design else "HOLDOUT, read once"))
    say("")
    cands = e[e["candidate"]]
    say(f"USDT perps first traded 2023-01 or later: {len(cands)}; events: {int(cands['excluded'].eq('').sum())}")
    for why, n in cands.loc[cands["excluded"] != "", "excluded"].value_counts().items():
        say(f"  excluded, {why}: {n}")
    say(f"costs per side: listing {lc * 1e4:.2f} bps (fee {ld.FEE_BPS} + assumed half-spread "
        f"{ld.LISTING_HALF_SPREAD_BPS}), BTC {hc * 1e4:.4f} bps (espero.costs, measured)")
    say("")
    p = results[next(iter(results))]["plan"]
    if len(p):
        gap = (p["listing_day"] - p["onboard_day"]).dt.days
        say(f"listing day = the first daily bar's day; Binance's onboardDate fell on it for {int((gap == 0).sum())} "
            f"of {len(p)} positions, earlier by {dict(sorted(gap[gap != 0].value_counts().items()))} days for the rest")
        say("")
    keys = [k for k in results if k != "lag2"]
    best = None
    for h in keys:
        r = results[h]
        ev = ld.evaluate(r["net"], r["abnormal"])
        say(f"hold {h} days: short the listing, long BTC, net of funding and costs")
        say(line("net", r["net"]))
        say(line("gross: no funding, no costs", r["gross"]))
        say(line("unhedged short, net", r["unhedged"]))
        say(line("abnormal: short the listing, long the basket", r["abnormal"]))
        say(line(("without" if ld.COVER else "with") + " the cover rule, net", r["other"]))
        n_cov = sum(1 for s, x in r["would"].items() if x != r["plan"].set_index("symbol").at[s, "exit"])
        say(f"  the cover rule closes early, on a close above the listing day's high: {n_cov} of {len(r['would'])}")
        fund = ld.totals(r["net"], "funding")
        say(f"  funding per position: mean {fund.mean() * 100:+.2f}%  median {fund.median() * 100:+.2f}%; "
            f"break-even listing cost per side {ld.break_even_bps(r['net'], lc):+.1f} bps")
        dropped = {k: int(v) for k, v in pd.Series(r["dropped"]).value_counts().items()} if r["dropped"] else {}
        say(f"  halves {ev['first_half'] * 1e4:+.2f} / {ev['second_half'] * 1e4:+.2f} bps a day; dropped {dropped}")
        if best is None or (math.isfinite(ev["t"]) and ev["t"] > best[1]):
            best = (h, ev["t"])
        say("")
    if design:
        say(f"design choice: the hold with the largest t is {best[0]} days (t {best[1]:+.2f})")
        return out
    h = ld.CHOSEN_HOLD
    r = results[h]
    first = ld.evaluate(r["net"], r["abnormal"])
    q, m = ledger_q(first["p"])
    ev = ld.evaluate(r["net"], r["abnormal"], q)
    say(f"PRIMARY, hold {h} days: daily mean {ev['mean'] * 1e4:+.2f} bps, t {ev['t']:+.2f} (Newey-West, "
        f"{ev['lags']} lags), p {ev['p']:.3g}, q {q:.4g} over {m} judged tests including #67")
    say(f"  positions {ev['events']}, days {ev['days']}; halves {ev['first_half'] * 1e4:+.2f} / "
        f"{ev['second_half'] * 1e4:+.2f} bps; median position {ev['median_event'] * 100:+.2f}%; "
        f"abnormal daily mean {ev['abnormal_mean'] * 1e4:+.2f} bps (t {ev['abnormal_t']:+.2f})")
    say(f"Outcome: {ev['outcome']}" + (f"  checks {ev.get('checks')}" if "checks" in ev else ""))
    say("")
    say("Information only, deciding nothing:")
    say(line(f"entry two days after the listing, hold {h}", results["lag2"]["net"]))
    per = ld.totals(r["net"])
    plan = r["plan"].set_index("symbol")
    q_of = plan.loc[per.index, "entry"].dt.to_period("Q").astype(str)
    say("  by quarter of entry: " + "; ".join(f"{k} {v.mean() * 100:+.2f}% ({len(v)})" for k, v in per.groupby(q_of)))
    day1 = pd.Series({s: float(allbars[s].at[plan.at[s, "listing_day"], "close"] / allbars[s].at[plan.at[s, "listing_day"],
                     "open"] - 1) for s in per.index if plan.at[s, "listing_day"] in allbars[s].index})
    med = day1.median()
    up, down = per[day1.reindex(per.index) > med], per[day1.reindex(per.index) <= med]
    say(f"  by the listing day's own move (median {med * 100:+.1f}%): above {up.mean() * 100:+.2f}% ({len(up)}), "
        f"at or below {down.mean() * 100:+.2f}% ({len(down)})")
    short_paths = {s: ld.leg(allbars[s], plan.at[s, "entry"], r["covered"][s], -1) for s in per.index}
    stopped = sum(1 for s, v in short_paths.items() if v.index[-1] != r["covered"][s])
    worst = max((float(v["ratio"].max()) - 1 for v in short_paths.values()), default=float("nan"))
    say(f"  positions whose listing stopped trading inside the hold: {stopped}; worst rise against the short at a "
        f"daily close while it was open: {worst * 100:+.0f}%")
    return out


def main(argv: List[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--events", action="store_true", help="metadata only: write the event list")
    g.add_argument("--design", action="store_true", help="files through 2024-12 only; reruns allowed")
    g.add_argument("--holdout", action="store_true", help="once, after the pre-registration is committed")
    a = ap.parse_args(argv)
    if a.events:
        e = write_events()
        c = e[e["candidate"]]
        print(f"wrote {EVENTS.relative_to(ROOT)}: {len(c)} candidates, {int(c['excluded'].eq('').sum())} events")
        print(c.loc[c["excluded"] != "", "excluded"].value_counts().to_string())
        return 0
    if a.holdout:
        if ld.CHOSEN_HOLD is None:
            print("refused: the hold is chosen on the design window and set before the pre-registration")
            return 2
        if not committed_unchanged(PREREG):
            print("refused: research/PREREGISTRATION_LISTDRIFT.md must be committed and unchanged before the holdout")
            return 2
        if HOLDOUT_OUT.exists():
            print(f"refused: {HOLDOUT_OUT.relative_to(ROOT)} exists; the holdout is read once")
            return 2
    lines, results = run(design=bool(a.design))
    text = "\n".join(lines) + "\n"
    (DESIGN_OUT if a.design else HOLDOUT_OUT).write_text(text)
    if a.holdout:
        cal = ld.calendar(results[ld.CHOSEN_HOLD]["net"])
        cal.rename_axis("day").to_csv(SERIES_OUT, float_format="%.8g")
    print(text, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
