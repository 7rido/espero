"""#80's run: the funding spread between trade.xyz's markets, the criteria, the information-only readouts.

    .venv/bin/python research/fundspread.py | tee research/fundspread_run.txt

Reads hourly funding rows and daily candles for the 28 registered markets from research/data/fundspread/ (fetched
from Hyperliquid's public info endpoint when missing: paced, one request every 8 seconds, never in minutes 19 to 27
of the hour, because this Mac's recorders share the venue's request limit; about 90 minutes from scratch).
Applies espero/fundspread.py as registered in research/PREREGISTRATION_FUNDSPREAD.md, and writes the inputs to
research/fundspread_inputs.csv.gz and the weeks to research/fundspread_weeks.csv.
"""
from __future__ import annotations

import csv
import datetime as dt
import gzip
import io
import json
import math
import statistics
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from espero import fundspread as F  # noqa: E402
from espero import hyperliquid as hl  # noqa: E402
from espero import trials  # noqa: E402
from espero.cascade import nw_t  # noqa: E402
from espero.volf import nw_lags  # noqa: E402

UNIVERSE = ["AAPL", "AMD", "AMZN", "BRENTOIL", "CBRS", "CL", "CRCL", "CRWV", "DRAM", "EWY", "GOLD", "GOOGL", "INTC",
            "META", "MRVL", "MSFT", "MSTR", "MU", "NBIS", "NVDA", "SILVER", "SKHX", "SMSN", "SNDK", "SP500", "SPCX",
            "TSLA", "XYZ100"]
CACHE = ROOT / "research" / "data" / "fundspread"
INPUTS = ROOT / "research" / "fundspread_inputs.csv.gz"
WEEKS = ROOT / "research" / "fundspread_weeks.csv"
JUDGED = ("fail", "pass", "provisional", "exploratory")
START_MS = int(dt.datetime(2025, 10, 1, tzinfo=dt.timezone.utc).timestamp() * 1000)
PAUSE_S = 8.0


def _post(body: dict):
    while 19 <= time.gmtime().tm_min <= 27:
        time.sleep(20)
    out = hl.post(body, url=hl.MAINNET_URL + "/info")
    time.sleep(PAUSE_S)
    return out


def fetch_missing() -> None:
    CACHE.mkdir(parents=True, exist_ok=True)
    now = int(time.time() * 1000)
    for name in UNIVERSE:
        coin = f"xyz:{name}"
        fp, pp = CACHE / f"fund_{name}.json", CACHE / f"px_{name}.json"
        if not fp.exists():
            rows, cursor = [], START_MS
            while True:
                page = _post({"type": "fundingHistory", "coin": coin, "startTime": cursor, "endTime": now})
                if not page:
                    break
                rows += page
                cursor = int(page[-1]["time"]) + 1
                if len(page) < 500:
                    break
            fp.write_text(json.dumps(rows))
        if not pp.exists():
            pp.write_text(json.dumps(_post({"type": "candleSnapshot", "req": {"coin": coin, "interval": "1d",
                                                                              "startTime": START_MS, "endTime": now}})))


def load():
    funding, prices = {}, {}
    for name in UNIVERSE:
        rows = json.loads((CACHE / f"fund_{name}.json").read_text())
        rows.sort(key=lambda r: int(r["time"]))
        funding[name] = ([int(r["time"]) // 1000 for r in rows], [float(r["fundingRate"]) for r in rows])
        prices[name] = {int(c["t"]) // 1000: float(c["o"]) for c in json.loads((CACHE / f"px_{name}.json").read_text())}
    return funding, prices


def mondays(prices) -> list:
    starts = sorted({t for p in prices.values() for t in p})
    return [t for t in starts if dt.datetime.fromtimestamp(t, dt.timezone.utc).weekday() == 0]


def keep_inputs(funding, prices) -> None:
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["market", "kind", "t", "value"])
    for name in UNIVERSE:
        for t, r in zip(*funding[name]):
            w.writerow([name, "funding", t, r])
        for t, o in sorted(prices[name].items()):
            w.writerow([name, "open", t, o])
    INPUTS.write_bytes(gzip.compress(buf.getvalue().encode(), mtime=0))


def ledger_q(p: float):
    d = pd.read_csv(ROOT / "research" / "trials.csv", dtype={"test": str})
    judged = d[d["status"].isin(JUDGED) & (d["test"] != "80")]
    ps = pd.to_numeric(judged["p_from_t"], errors="coerce").fillna(1.0).to_numpy()
    allp = np.append(ps, p)
    return float(trials.bh(allp)[-1]), int(len(allp))


def pct(x) -> str:
    return "-" if x is None or (isinstance(x, float) and math.isnan(x)) else f"{x * 100:+.3f}%"


def day(t: int) -> str:
    return dt.datetime.fromtimestamp(t, dt.timezone.utc).date().isoformat()


def main() -> int:
    print(f"#80, run {time.strftime('%Y-%m-%d %H:%M', time.gmtime())} UTC, as registered in research/PREREGISTRATION_FUNDSPREAD.md")
    fetch_missing()
    funding, prices = load()
    keep_inputs(funding, prices)
    mons = mondays(prices)
    weeks = F.run(funding, prices, mons)
    n = len(weeks)
    print(f"{len(UNIVERSE)} markets; {sum(len(v[0]) for v in funding.values()):,} funding rows; weeks with a position: "
          f"{n} from {day(weeks[0].t)} to {day(weeks[-1].t)} (the last ends {day(weeks[-1].t + F.WEEK_S)}); eligible "
          f"markets per week {min(w.n for w in weeks)} to {max(w.n for w in weeks)}")
    net = [w.net for w in weeks]
    mean = sum(net) / n
    pf = F.profit_factor(net)
    t = nw_t(np.array(net), nw_lags(n))
    p = F.two_sided_p(t) if math.isfinite(t) else float("nan")
    q, fam = ledger_q(p)
    means = F.random_means(funding, prices, weeks)
    gross = sum(w.gross for w in weeks) / n
    share = F.share_at_or_above(gross, means)
    h1, h2 = F.halves(net)
    loo = {m: (lambda ws: sum(x.net for x in ws) / len(ws) if ws else float("nan"))(F.run(funding, prices, mons, skip=m))
           for m in UNIVERSE}
    loo_min = min(v for v in loo.values() if not math.isnan(v))
    worst = min(loo, key=lambda m: loo[m] if not math.isnan(loo[m]) else 9)

    print(f"\n== The registered criteria, on {n} weeks")
    print(f"1. profit factor over the weekly net returns: {pf if pf is None else round(pf, 3)} (need >= {F.MIN_PF})")
    print(f"2. mean weekly net {pct(mean)}, Newey-West t {t:.2f} ({nw_lags(n)} lags), p {p:.4g}, BH q {q:.4g} over "
          f"{fam} tests (need mean > 0, t >= {F.MIN_T}, q < {F.MAX_Q})")
    print(f"3. {F.RANDOM_DRAWS} random assignments (seed {F.RANDOM_SEED}): median gross {pct(float(np.nanmedian(means)))}; the "
          f"rule's gross {pct(gross)}; {share:.1%} of draws at or above it (need under {F.MAX_RANDOM_SHARE:.0%})")
    print(f"4. halves: {pct(h1)} then {pct(h2)}")
    print(f"5. the lowest mean with one market removed: {pct(loo_min)} (without {worst})")
    v, missed = F.verdict(n, pf, mean, t, q, share, h1, h2, loo_min)
    print(f"\nVERDICT: {v}" + "".join(f"\n  missed {m}" for m in missed))

    print("\n== Information only")
    print(f"components of the mean week: price {pct(sum(w.price for w in weeks) / n)}, funding "
          f"{pct(sum(w.fund for w in weeks) / n)}, gross {pct(gross)}, costs {pct(gross - mean)}; mean turnover "
          f"{statistics.fmean(w.turnover for w in weeks):.3f} of capital a week")
    alt = F.run(funding, prices, mons, cost_bps=5.9)
    print(f"growth-mode fee (0.9 bps) + 5 bps slippage: mean weekly net {pct(sum(w.net for w in alt) / len(alt))}, "
          f"NW t {nw_t(np.array([w.net for w in alt]), nw_lags(len(alt))):.2f}")
    spreads = []
    for w in weeks:
        sig = F.eligible(funding, prices, w.t)
        spreads.append(statistics.fmean(sig[m] for m in w.short) - statistics.fmean(sig[m] for m in w.long))
    print(f"the signal's spread, short leg minus long leg, mean {statistics.fmean(spreads) * 24 * 365:+.1%} a year "
          f"(hourly rate x 8,760)")
    print(f"weeks with the funding component positive: {sum(1 for w in weeks if w.fund > 0)} of {n}; weeks with net "
          f"above zero: {sum(1 for x in net if x > 0)} of {n}")
    legs = {}
    for w in weeks:
        for m in w.long:
            legs.setdefault(m, [0, 0])[0] += 1
        for m in w.short:
            legs.setdefault(m, [0, 0])[1] += 1
    print("\nper market: weeks long, weeks short, mean net with the market removed")
    for m in UNIVERSE:
        a, b = legs.get(m, [0, 0])
        print(f"  {m:9s} {a:3d} {b:3d}  {pct(loo[m])}")
    with WEEKS.open("w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["monday", "markets", "long", "short", "price", "funding", "gross", "turnover", "net"])
        for x in weeks:
            w.writerow([day(x.t), x.n, " ".join(x.long), " ".join(x.short), round(x.price, 6), round(x.fund, 6),
                        round(x.gross, 6), round(x.turnover, 4), round(x.net, 6)])
    print(f"\nwrote {INPUTS.relative_to(ROOT)} and {WEEKS.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
