"""#76's run: the night shift on the 37 markets' daily bars, the criteria, the information-only readouts.

    .venv/bin/python research/nightshift.py | tee research/nightshift_run.txt

Reads each market's daily bars through espero.tradfi (Yahoo, five years; kept for a day in data/cache/tradfi/),
writes the bars it used to research/nightshift_bars.csv.gz and the portfolio's nights to
research/nightshift_nights.csv. Applies espero/nightshift.py as registered in research/PREREGISTRATION_NIGHTSHIFT.md.
"""
from __future__ import annotations

import csv
import gzip
import io
import math
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from espero import nightshift as N  # noqa: E402
from espero import robustness, tradfi, trials  # noqa: E402
from espero.cascade import nw_t  # noqa: E402
from espero.volf import nw_lags  # noqa: E402

JUDGED = ("fail", "pass", "provisional", "exploratory")
BARS = ROOT / "research" / "nightshift_bars.csv.gz"
NIGHTS = ROOT / "research" / "nightshift_nights.csv"


def ledger_q(p: float):
    d = pd.read_csv(ROOT / "research" / "trials.csv", dtype={"test": str})
    judged = d[d["status"].isin(JUDGED) & (d["test"] != "76")]
    ps = pd.to_numeric(judged["p_from_t"], errors="coerce").fillna(1.0).to_numpy()
    allp = np.append(ps, p)
    return float(trials.bh(allp)[-1]), int(len(allp))


def bps(x) -> str:
    return "-" if x is None or (isinstance(x, float) and math.isnan(x)) else f"{x * 1e4:+.2f} bps"


def load():
    out = {}
    for name, _ in tradfi.allowed():
        out[name] = tradfi.daily(name, "5y")
        time.sleep(0.3)
    return out


def keep_bars(markets) -> None:
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["market", "ts", "open", "high", "low", "close", "day"])
    for name, df in markets.items():
        for r in df.itertuples(index=False):
            w.writerow([name, r.ts, r.open, r.high, r.low, r.close, r.day])
    BARS.write_bytes(gzip.compress(buf.getvalue().encode(), mtime=0))


def compute(markets, cost_bps=N.COST_BPS, funding_year=N.FUNDING_YEAR):
    night, day, hours = {}, {}, {}
    for name, df in markets.items():
        ts, o, c, d = df["ts"].tolist(), df["open"].tolist(), df["close"].tolist(), df["day"].tolist()
        ns = N.nights(ts, o, c, d, cost_bps, funding_year)
        night[name] = ns
        day[name] = N.days(o, c, d, cost_bps, funding_year)
        for k, v in ns.items():
            hours[k] = v[2]
    return night, day, hours


def main() -> int:
    print(f"#76, run {time.strftime('%Y-%m-%d %H:%M', time.gmtime())} UTC, as registered in research/PREREGISTRATION_NIGHTSHIFT.md")
    markets = load()
    keep_bars(markets)
    print(f"{len(markets)} markets; {sum(len(df) for df in markets.values()):,} daily bars")
    for name, df in markets.items():
        print(f"  {name:8s} {len(df):5d} bars  {df['day'].iloc[0]} -> {df['day'].iloc[-1]}")

    night, day, hours = compute(markets)
    net = {m: {k: v[1] for k, v in ns.items()} for m, ns in night.items()}
    gross = {m: {k: v[0] for k, v in ns.items()} for m, ns in night.items()}
    p_net, p_gross = N.portfolio(net), N.portfolio(gross)
    d_net = N.portfolio({m: {k: v[1] for k, v in ds.items()} for m, ds in day.items()})
    d_gross = N.portfolio({m: {k: v[0] for k, v in ds.items()} for m, ds in day.items()})
    n = len(p_net)
    every = [v for m in net.values() for v in m.values()]
    pf = N.profit_factor(every)
    mean = float(p_net.mean())
    t = nw_t(p_net.to_numpy(), nw_lags(n))
    p = N.two_sided_p(t) if math.isfinite(t) else float("nan")
    q, fam = ledger_q(p)
    h1, h2 = N.halves(list(p_net))
    up, counted = N.breadth(net)

    print(f"\n== The registered criteria, on {n} nights from {p_net.index[0]} to {p_net.index[-1]} ({len(every):,} market-nights)")
    print(f"1. profit factor over every market-night, net: {pf:.3f} (need >= {N.MIN_PF})")
    print(f"2. the portfolio's mean net night {bps(mean)}, Newey-West t {t:.2f} ({nw_lags(n)} lags), p {p:.4g}, "
          f"BH q {q:.4g} over {fam} tests (need mean > 0, t >= {N.MIN_T}, q < {N.MAX_Q})")
    print(f"3. the night {bps(mean)} against the day {bps(float(d_net.mean()))}, both net")
    print(f"4. halves: {bps(h1)} then {bps(h2)}")
    print(f"5. markets with 250+ nights and a mean net night above zero: {up} of {counted}")
    v, missed = N.verdict(n, pf, mean, t, q, mean, float(d_net.mean()), h1, h2, up, counted)
    print(f"\nVERDICT: {v}" + "".join(f"\n  missed {m}" for m in missed))

    print("\n== Information only")
    print(f"gross: the night {bps(float(p_gross.mean()))}, the day {bps(float(d_gross.mean()))} (portfolio means)")
    for label, cost, fund in (("growth-mode fee (0.9 bps) + 5 bps slippage, 10% funding", 5.9, 0.10),
                              ("no costs, no funding", 0.0, 0.0), ("14 bps a fill, funding at 5.5%", 14.0, 0.055)):
        nn, _, _ = compute(markets, cost, fund)
        s = N.portfolio({m: {k: x[1] for k, x in ns.items()} for m, ns in nn.items()})
        print(f"{label}: mean night {bps(float(s.mean()))}, NW t {nw_t(s.to_numpy(), nw_lags(len(s))):.2f}")
    wk = pd.Series({k: v for k, v in p_gross.items() if hours.get(k, 0) > 20})
    wd = pd.Series({k: v for k, v in p_gross.items() if hours.get(k, 0) <= 20})
    print(f"gross, over a weekend or holiday: {len(wk)} nights, mean {bps(float(wk.mean()))}; weeknights: {len(wd)}, "
          f"mean {bps(float(wd.mean()))}")
    years = sorted({k[:4] for k in p_gross.index})
    print("gross night by calendar year: " + ", ".join(f"{y} {bps(float(p_gross[[k for k in p_gross.index if k.startswith(y)]].mean()))}" for y in years))
    lo = float(np.log1p(p_gross).sum())
    ld = float(np.log1p(d_gross.reindex(p_gross.index).dropna()).sum())
    print(f"of the equal-weight portfolio's log return, the nights gave {lo:+.3f} and the days {ld:+.3f}")
    dsr_table = pd.read_csv(ROOT / "research" / "trials_dsr.csv")
    var_daily = float(np.var(dsr_table["sharpe"].dropna() / math.sqrt(365), ddof=1))
    ds = robustness.deflated_sharpe(p_net.to_numpy(), fam, var_daily)
    print(f"deflated Sharpe on the nightly net series (N = {fam}): nightly Sharpe {ds.get('sharpe'):.4f}, DSR {ds.get('dsr'):.3f}")
    print("\nper market: nights, mean gross night, mean net night")
    for name in markets:
        g, nt = list(gross[name].values()), list(net[name].values())
        print(f"  {name:8s} {len(nt):5d}  {bps(sum(g) / len(g) if g else None):>12s}  {bps(sum(nt) / len(nt) if nt else None):>12s}")

    with NIGHTS.open("w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["day", "markets", "gross", "net", "hours"])
        counts = pd.DataFrame(net).count(axis=1)
        for k in p_net.index:
            w.writerow([k, int(counts[k]), round(float(p_gross[k]), 8), round(float(p_net[k]), 8), hours.get(k)])
    print(f"\nwrote {BARS.relative_to(ROOT)} and {NIGHTS.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
