"""#77's run: the slow night shift on the 37 markets' daily bars, the criteria, the information-only readouts.

    .venv/bin/python research/nightweek.py | tee research/nightweek_run.txt

Reads each market's daily bars through espero.tradfi (Yahoo, five years; kept for a day in data/cache/tradfi/),
writes the bars it used to research/nightweek_bars.csv.gz (with SPY) and the portfolio's weeks to
research/nightweek_weeks.csv. Applies espero/nightweek.py as registered in research/PREREGISTRATION_NIGHTWEEK.md.
"""
from __future__ import annotations

import csv
import datetime as dt
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

from espero import data, robustness, tradfi, trials  # noqa: E402
from espero import nightshift as N  # noqa: E402
from espero import nightweek as W  # noqa: E402
from espero.cascade import nw_t  # noqa: E402
from espero.tradfi import ET as W_ET  # noqa: E402
from espero.volf import nw_lags  # noqa: E402

JUDGED = ("fail", "pass", "provisional", "exploratory")
BARS = ROOT / "research" / "nightweek_bars.csv.gz"
WEEKS = ROOT / "research" / "nightweek_weeks.csv"


def ledger_q(p: float):
    d = pd.read_csv(ROOT / "research" / "trials.csv", dtype={"test": str})
    judged = d[d["status"].isin(JUDGED) & (d["test"] != "77")]
    ps = pd.to_numeric(judged["p_from_t"], errors="coerce").fillna(1.0).to_numpy()
    allp = np.append(ps, p)
    return float(trials.bh(allp)[-1]), int(len(allp))


def bps(x) -> str:
    return "-" if x is None or (isinstance(x, float) and math.isnan(x)) else f"{x * 1e4:+.1f} bps"


def spy_frame():
    d = data.yahoo_daily("SPY", "5y")
    ts = d["ts"].astype(int).tolist()
    return pd.DataFrame({"ts": ts, "open": d["open"], "high": d["high"], "low": d["low"], "close": d["close"],
                         "volume": d["volume"], "day": [dt.datetime.fromtimestamp(x, W_ET).date().isoformat() for x in ts]})


def load():
    out = {}
    for name, _ in tradfi.allowed():
        out[name] = tradfi.daily(name, "5y")
        time.sleep(0.3)
    return out


def keep_bars(markets, spy) -> None:
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["market", "ts", "open", "high", "low", "close", "day"])
    for name, df in list(markets.items()) + [("SPY", spy)]:
        for r in df.itertuples(index=False):
            w.writerow([name, r.ts, r.open, r.high, r.low, r.close, r.day])
    BARS.write_bytes(gzip.compress(buf.getvalue().encode(), mtime=0))


def compute(markets, cost_bps=W.COST_BPS, funding_year=W.FUNDING_YEAR):
    out = {}
    for name, df in markets.items():
        out[name] = W.weeks(df["ts"].tolist(), df["open"].tolist(), df["close"].tolist(), df["day"].tolist(),
                            cost_bps, funding_year)
    return out


def main() -> int:
    print(f"#77, run {time.strftime('%Y-%m-%d %H:%M', time.gmtime())} UTC, as registered in research/PREREGISTRATION_NIGHTWEEK.md")
    markets = load()
    spy = spy_frame()
    keep_bars(markets, spy)
    print(f"{len(markets)} markets and SPY; {sum(len(df) for df in markets.values()):,} daily bars")
    wk = compute(markets)
    net = {m: {k: v[1] for k, v in ws.items()} for m, ws in wk.items()}
    gross = {m: {k: v[0] for k, v in ws.items()} for m, ws in wk.items()}
    p_net, p_gross = N.portfolio(net), N.portfolio(gross)
    mkt = pd.Series(W.market_weeks(spy["open"].tolist(), spy["close"].tolist(), spy["day"].tolist())).reindex(p_net.index)
    n = len(p_net)
    every = [v for m in net.values() for v in m.values()]
    pf = W.profit_factor(every)
    mean = float(p_net.mean())
    t = nw_t(p_net.to_numpy(), nw_lags(n))
    p = N.two_sided_p(t) if math.isfinite(t) else float("nan")
    q, fam = ledger_q(p)
    h1, h2 = N.halves(list(p_net))
    up, counted = W.breadth(net)
    market = float(mkt.mean())

    print(f"\n== The registered criteria, on {n} weeks from {p_net.index[0]} to {p_net.index[-1]} ({len(every):,} market-weeks)")
    print(f"1. profit factor over every market-week, net: {pf:.3f} (need >= {W.MIN_PF})")
    print(f"2. the portfolio's mean net week {bps(mean)}, Newey-West t {t:.2f} ({nw_lags(n)} lags), p {p:.4g}, "
          f"BH q {q:.4g} over {fam} tests (need mean > 0, t >= {W.MIN_T}, q < {W.MAX_Q})")
    print(f"3. the net week {bps(mean)} against SPY's gross {bps(market)} over the same hours")
    print(f"4. halves: {bps(h1)} then {bps(h2)}")
    print(f"5. markets with 100+ weeks and a mean net week above zero: {up} of {counted}")
    v, missed = W.verdict(n, pf, mean, t, q, market, h1, h2, up, counted)
    print(f"\nVERDICT: {v}" + "".join(f"\n  missed {m}" for m in missed))

    print("\n== Information only")
    print(f"gross mean week {bps(float(p_gross.mean()))}")
    alt = compute(markets, 5.9, 0.10)
    s = N.portfolio({m: {k: x[1] for k, x in ws.items()} for m, ws in alt.items()})
    print(f"growth-mode fee (0.9 bps) + 5 bps slippage: mean net week {bps(float(s.mean()))}, NW t {nw_t(s.to_numpy(), nw_lags(len(s))):.2f}")
    hold = {}
    for name, df in markets.items():
        c, d = df["close"].tolist(), df["day"].tolist()
        last = {}
        for k, day in enumerate(d):
            last[W.week_of(day)] = k
        ks = sorted(last.items())
        hold[name] = {w: c[k] / c[j] - 1 for (w0, j), (w, k) in zip(ks, ks[1:]) if c[j] > 0}
    bh = N.portfolio(hold).reindex(p_net.index)
    print(f"buy and hold, the same markets, close of the week before to the week's last close: mean {bps(float(bh.mean()))}")
    years = sorted({k[:4] for k in p_net.index})
    print("net week by year: " + ", ".join(f"{y} {bps(float(p_net[[k for k in p_net.index if k.startswith(y)]].mean()))}" for y in years))
    dsr_table = pd.read_csv(ROOT / "research" / "trials_dsr.csv")
    var_week = float(np.var(dsr_table["sharpe"].dropna() / math.sqrt(52), ddof=1))
    ds = robustness.deflated_sharpe(p_net.to_numpy(), fam, var_week)
    print(f"deflated Sharpe on the weekly net series (N = {fam}): weekly Sharpe {ds.get('sharpe'):.4f}, DSR {ds.get('dsr'):.3f}")
    print("\nper market: weeks, mean gross week, mean net week")
    for name in markets:
        g, nt = list(gross[name].values()), list(net[name].values())
        print(f"  {name:8s} {len(nt):4d}  {bps(sum(g) / len(g) if g else None):>12s}  {bps(sum(nt) / len(nt) if nt else None):>12s}")
    with WEEKS.open("w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["week", "markets", "gross", "net", "spy"])
        counts = pd.DataFrame(net).count(axis=1)
        for k in p_net.index:
            w.writerow([k, int(counts[k]), round(float(p_gross[k]), 8), round(float(p_net[k]), 8),
                        "" if pd.isna(mkt[k]) else round(float(mkt[k]), 8)])
    print(f"\nwrote {BARS.relative_to(ROOT)} and {WEEKS.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
