"""#75's run: the registered rule on the 37 markets' hourly bars, the criteria, the information-only readouts.

    .venv/bin/python research/dealrange.py | tee research/dealrange_run.txt

Reads each market's regular-session hourly bars through espero.tradfi (Yahoo, the last 730 days; kept for a day in
data/cache/tradfi/), writes the bars it used to research/dealrange_bars.csv.gz and every trade to
research/dealrange_trades.csv. Applies espero/dealrange.py as registered in research/PREREGISTRATION_DEALRANGE.md.
"""
from __future__ import annotations

import csv
import gzip
import io
import math
import statistics
import sys
import time
from collections import Counter
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from espero import brackets as B  # noqa: E402
from espero import dealrange as D  # noqa: E402
from espero import robustness, tradfi, trials  # noqa: E402

JUDGED = ("fail", "pass", "provisional", "exploratory")
BARS = ROOT / "research" / "dealrange_bars.csv.gz"
TRADES = ROOT / "research" / "dealrange_trades.csv"


def ledger_q(p: float):
    d = pd.read_csv(ROOT / "research" / "trials.csv", dtype={"test": str})
    judged = d[d["status"].isin(JUDGED) & (d["test"] != "75")]
    ps = pd.to_numeric(judged["p_from_t"], errors="coerce").fillna(1.0).to_numpy()
    allp = np.append(ps, p)
    return float(trials.bh(allp)[-1]), int(len(allp))


def load():
    markets = {}
    for name, ticker in tradfi.allowed():
        df = tradfi.hourly(name)
        markets[name] = df
        time.sleep(0.3)
    return markets


def keep_bars(markets) -> None:
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["market", "ts", "open", "high", "low", "close", "day"])
    for name, df in markets.items():
        for r in df.itertuples(index=False):
            w.writerow([name, r.ts, r.open, r.high, r.low, r.close, r.day])
    BARS.write_bytes(gzip.compress(buf.getvalue().encode(), mtime=0))


def run(markets, b: B.Bracket):
    out, armed = [], 0
    for name, df in markets.items():
        o, h, low, c = (df[k].to_numpy(dtype=float) for k in ("open", "high", "low", "close"))
        day = df["day"].tolist()
        orders, trades = D.orders_and_trades(o, h, low, c, day, b)
        armed += len(orders)
        for t in trades:
            out.append(dict(market=name, trade=t, ts=int(df["ts"].iloc[t.entry_i]), day=day[t.entry_i],
                            exit_day=day[t.exit_i]))
    out.sort(key=lambda x: (x["ts"], x["market"]))
    return out, armed


def fmt(x, nd=3):
    return "-" if x is None or (isinstance(x, float) and math.isnan(x)) else f"{x:.{nd}f}"


def main() -> int:
    print(f"#75, run {time.strftime('%Y-%m-%d %H:%M', time.gmtime())} UTC, as registered in research/PREREGISTRATION_DEALRANGE.md")
    markets = load()
    keep_bars(markets)
    print(f"{len(markets)} markets; bars from {min(df['day'].iloc[0] for df in markets.values())} to "
          f"{max(df['day'].iloc[-1] for df in markets.values())}; {sum(len(df) for df in markets.values()):,} bars")
    for name, df in markets.items():
        print(f"  {name:8s} {len(df):5d} bars  {df['day'].iloc[0]} -> {df['day'].iloc[-1]}")

    got, armed = run(markets, D.BRACKET)
    rs = [x["trade"].r for x in got]
    n = len(rs)
    s = B.summary(rs)
    t, days = D.clustered_t(rs, [x["day"] for x in got])
    p = D.two_sided_p(t, days) if t is not None else float("nan")
    q, fam = ledger_q(p) if t is not None else (None, 0)
    h1, h2 = D.halves(rs)
    by_market = {}
    for x in got:
        by_market.setdefault(x["market"], []).append(x["trade"].r)
    up, counted = D.breadth(by_market)

    cases = []
    for name, df in markets.items():
        mine = [x["trade"] for x in got if x["market"] == name]
        if mine:
            cases.append((df["open"].to_numpy(dtype=float), df["high"].to_numpy(dtype=float),
                          df["low"].to_numpy(dtype=float), df["close"].to_numpy(dtype=float), df["day"].tolist(), mine))
    t0 = time.time()
    means = B.random_means(cases, D.BRACKET, draws=D.RANDOM_DRAWS, seed=D.RANDOM_SEED) if cases else np.array([])
    gap, share = B.beats_random(s.mean_r, means) if len(means) and s.mean_r is not None else (float("nan"), 1.0)

    print(f"\n== The registered criteria, on {n} trades from {armed} orders armed")
    print(f"1. profit factor {fmt(s.profit_factor)} (need >= {D.MIN_PF})")
    print(f"2. mean R {fmt(s.mean_r, 4)}, t {fmt(t, 2)} clustered over {days} entry days, p {fmt(p, 4)}, "
          f"BH q {fmt(q, 4)} over {fam} tests (need mean > 0, t >= {D.MIN_T}, q < {D.MAX_Q})")
    print(f"3. random entries: {D.RANDOM_DRAWS} draws (seed {D.RANDOM_SEED}, {time.time() - t0:.0f} s), median mean R "
          f"{fmt(float(np.nanmedian(means)) if len(means) else None, 4)}; the rule {fmt(gap, 4)} above it; "
          f"{share:.1%} of draws at or above the rule (need under {D.MAX_RANDOM_SHARE:.0%})")
    print(f"4. halves: {fmt(h1, 4)} then {fmt(h2, 4)}")
    print(f"5. markets with 5+ trades and a mean R above zero: {up} of {counted}")
    v, missed = D.verdict(n, s.profit_factor, s.mean_r, t, q, share, h1, h2, up, counted)
    print(f"\nVERDICT: {v}" + ("".join(f"\n  missed {m}" for m in missed)))

    print("\n== Information only")
    print(f"win rate {fmt(s.win_rate)}; total {fmt(s.total_r, 1)}R; outcomes: "
          + ", ".join(f"{k} {v}" for k, v in Counter(x['trade'].outcome for x in got).most_common()))
    for label, cost in (("no costs", 0.0), ("growth-mode fee (0.9 bps) + 5 bps slippage", 5.9)):
        b = B.Bracket(targets=D.BRACKET.targets, breakeven_after=1, cost_bps=cost)
        alt = B.summary([x["trade"].r for x in run(markets, b)[0]])
        print(f"{label}: {alt.n} trades, mean R {fmt(alt.mean_r, 4)}, profit factor {fmt(alt.profit_factor)}")
    same = [x["trade"].r for x in got if x["day"] == x["exit_day"]]
    over = [x["trade"].r for x in got if x["day"] != x["exit_day"]]
    print(f"closed the day they opened: {len(same)}, mean R {fmt(statistics.fmean(same) if same else None, 4)}; "
          f"held overnight or longer: {len(over)}, mean R {fmt(statistics.fmean(over) if over else None, 4)}")
    print(f"mean bars held (fill bar to exit bar): {fmt(statistics.fmean(x['trade'].exit_i - x['trade'].entry_i + 1 for x in got) if got else None, 1)}")
    daily = pd.Series({d: 0.0 for d in sorted({d for df in markets.values() for d in df['day']})})
    for x in got:
        daily[x["day"]] += x["trade"].r
    dsr_table = pd.read_csv(ROOT / "research" / "trials_dsr.csv")
    var_daily = float(np.var(dsr_table["sharpe"].dropna() / math.sqrt(365), ddof=1))
    ds = robustness.deflated_sharpe(daily.to_numpy(), fam, var_daily)
    print(f"deflated Sharpe on the daily R series (N = {fam}; the trials' Sharpes, annualised, scaled to a day for "
          f"their variance): daily Sharpe {fmt(ds.get('sharpe'), 4)}, DSR {fmt(ds.get('dsr'))}")
    print("\nper market: trades, mean R")
    for name in markets:
        r = by_market.get(name, [])
        print(f"  {name:8s} {len(r):4d}  {fmt(statistics.fmean(r) if r else None, 3)}")

    with TRADES.open("w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["market", "entry_ts", "entry_day", "exit_day", "signal_i", "entry_i", "exit_i", "entry", "risk", "r",
                    "outcome"])
        for x in got:
            tr = x["trade"]
            w.writerow([x["market"], x["ts"], x["day"], x["exit_day"], tr.signal_i, tr.entry_i, tr.exit_i,
                        round(tr.entry, 6), round(tr.risk, 6), round(tr.r, 6), tr.outcome])
    print(f"\nwrote {BARS.relative_to(ROOT)} and {TRADES.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
