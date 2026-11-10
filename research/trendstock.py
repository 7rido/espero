"""#78's run: the breakout trend rule on the 37 markets' daily bars, the criteria, the information-only readouts.

    .venv/bin/python research/trendstock.py | tee research/trendstock_run.txt

Reads each market's daily bars through espero.tradfi (Yahoo, five years; kept for a day in data/cache/tradfi/),
writes the bars it used to research/trendstock_bars.csv.gz and every trade to research/trendstock_trades.csv.
Applies espero/trendstock.py as registered in research/PREREGISTRATION_TRENDSTOCK.md.
"""
from __future__ import annotations

import csv
import datetime as dt
import gzip
import io
import math
import statistics
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from espero import tradfi, trials  # noqa: E402
from espero import trendstock as T  # noqa: E402

JUDGED = ("fail", "pass", "provisional", "exploratory")
BARS = ROOT / "research" / "trendstock_bars.csv.gz"
TRADES = ROOT / "research" / "trendstock_trades.csv"


def ledger_q(p: float):
    d = pd.read_csv(ROOT / "research" / "trials.csv", dtype={"test": str})
    judged = d[d["status"].isin(JUDGED) & (d["test"] != "78")]
    ps = pd.to_numeric(judged["p_from_t"], errors="coerce").fillna(1.0).to_numpy()
    allp = np.append(ps, p)
    return float(trials.bh(allp)[-1]), int(len(allp))


def pct(x) -> str:
    return "-" if x is None or (isinstance(x, float) and math.isnan(x)) else f"{x * 100:+.2f}%"


def fmt(x, nd=3):
    return "-" if x is None or (isinstance(x, float) and math.isnan(x)) else f"{x:.{nd}f}"


def month_of(ts: int) -> str:
    return dt.datetime.fromtimestamp(ts, dt.timezone.utc).strftime("%Y-%m")


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


def run(markets, cost_bps=T.COST_BPS, funding_year=T.FUNDING_YEAR):
    out = {}
    for name, df in markets.items():
        out[name] = T.trades(df["ts"].tolist(), df["open"].tolist(), df["close"].tolist(), cost_bps, funding_year)
    return out


def main() -> int:
    print(f"#78, run {time.strftime('%Y-%m-%d %H:%M', time.gmtime())} UTC, as registered in research/PREREGISTRATION_TRENDSTOCK.md")
    markets = load()
    keep_bars(markets)
    print(f"{len(markets)} markets; {sum(len(df) for df in markets.values()):,} daily bars")
    by = run(markets)
    rows = []
    for name, trs in by.items():
        ts = markets[name]["ts"].tolist()
        for t in trs:
            rows.append((ts[t.entry_i], name, t))
    rows.sort(key=lambda r: (r[0], r[1]))
    rets = [t.ret for _, _, t in rows]
    n = len(rets)
    print(f"entries from {month_of(rows[0][0])} to {month_of(rows[-1][0])}: {n} trades, "
          f"{sum(1 for _, _, t in rows if t.end)} still open at the end of the data")

    pf = T.profit_factor(rets)
    mean = sum(rets) / n
    t, months = T.clustered_t(rets, [month_of(ts) for ts, _, _ in rows])
    p = T.two_sided_p(t, months) if t is not None else float("nan")
    q, fam = ledger_q(p)
    cases = [(markets[m]["ts"].tolist(), markets[m]["open"].tolist(), markets[m]["close"].tolist(), trs)
             for m, trs in by.items() if trs]
    t0 = time.time()
    means = T.random_means(cases)
    share = T.share_at_or_above(mean, means)
    h1, h2 = T.halves(rets)
    up, counted = T.breadth({m: [t.ret for t in trs] for m, trs in by.items()})

    print(f"\n== The registered criteria, on {n} trades")
    print(f"1. profit factor over every trade, net: {fmt(pf)} (need >= {T.MIN_PF})")
    print(f"2. mean net trade {pct(mean)}, t {fmt(t, 2)} clustered over {months} entry months, p {fmt(p, 4)}, "
          f"BH q {fmt(q, 4)} over {fam} tests (need mean > 0, t >= {T.MIN_T}, q < {T.MAX_Q})")
    print(f"3. random entries held as long: {T.RANDOM_DRAWS} draws ({time.time() - t0:.0f} s), median mean "
          f"{pct(float(np.nanmedian(means)))}; the rule {pct(mean)}; {share:.1%} of draws at or above it "
          f"(need under {T.MAX_RANDOM_SHARE:.0%})")
    print(f"4. halves: {pct(h1)} then {pct(h2)}")
    print(f"5. markets with 5+ trades and a mean net trade above zero: {up} of {counted}")
    v, missed = T.verdict(n, pf, mean, t, q, share, h1, h2, up, counted)
    print(f"\nVERDICT: {v}" + "".join(f"\n  missed {m}" for m in missed))

    print("\n== Information only")
    wins = [r for r in rets if r > 0]
    loss = [r for r in rets if r <= 0]
    print(f"win rate {len(wins) / n:.3f}; average win {pct(sum(wins) / len(wins) if wins else None)}, "
          f"average loss {pct(sum(loss) / len(loss) if loss else None)}; mean days held "
          f"{statistics.fmean(t.days for _, _, t in rows):.0f}")
    for label, cost, fund in (("no costs, no funding", 0.0, 0.0),
                              ("growth-mode fee (0.9 bps) + 5 bps slippage", 5.9, 0.10)):
        alt = [t.ret for trs in run(markets, cost, fund).values() for t in trs]
        print(f"{label}: {len(alt)} trades, mean {pct(sum(alt) / len(alt))}, profit factor {fmt(T.profit_factor(alt))}")
    held = {m: sum(t.exit_i - t.entry_i for t in trs) / max(1, len(markets[m]) - T.ENTRY_WINDOW) for m, trs in by.items()}
    print(f"share of the days a market was held (median across markets): {statistics.median(held.values()):.2f}")
    comp, hold = [], []
    for m, df in markets.items():
        o, c = df["open"].tolist(), df["close"].tolist()
        if len(o) > T.ENTRY_WINDOW + 1:
            hold.append(c[-1] / o[T.ENTRY_WINDOW + 1] - 1)
            g = 1.0
            for t in by[m]:
                g *= 1 + t.ret
            comp.append(g - 1)
    print(f"per market from the first possible entry: buy and hold, median {pct(statistics.median(hold))}; "
          f"the rule's trades compounded, median {pct(statistics.median(comp))}")
    print("\nper market: trades, mean net trade")
    for m, trs in by.items():
        r = [t.ret for t in trs]
        print(f"  {m:8s} {len(r):3d}  {pct(sum(r) / len(r) if r else None)}")

    with TRADES.open("w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["market", "entry_ts", "entry_i", "exit_i", "entry", "exit", "days", "net", "open_at_end"])
        for ts, m, t in rows:
            w.writerow([m, ts, t.entry_i, t.exit_i, round(t.entry, 6), round(t.exit, 6), round(t.days, 2),
                        round(t.ret, 6), int(t.end)])
    print(f"\nwrote {BARS.relative_to(ROOT)} and {TRADES.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
