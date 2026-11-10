"""#73's run: fetch the registered window, apply espero/hip3track.py, print the tables (PREREGISTRATION_HIP3TRACK.md).

    .venv/bin/python research/hip3track.py | tee research/hip3track_run.txt

Fetches, into research/data/hip3track/ (kept, so a rerun reads the same bytes): one request of 15-minute candles a
market from Hyperliquid, paced because this Mac's recorders share the venue's request limit; Yahoo's hourly bars
(with pre-market and after-hours for stocks) and daily bars with splits. Writes research/hip3track_cells.csv.
"""
from __future__ import annotations

import csv
import datetime as dt
import json
import statistics
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from espero import hip3  # noqa: E402
from espero import hip3track as T  # noqa: E402
from espero import hyperliquid as hl  # noqa: E402

CACHE = ROOT / "research" / "data" / "hip3track"
OUT = ROOT / "research" / "hip3track_cells.csv"
PAUSE_S = 15.0


def utc(day: str) -> int:
    return int(dt.datetime.strptime(day, "%Y-%m-%d").replace(tzinfo=dt.timezone.utc).timestamp())


START, END = (utc(d) for d in T.WINDOW)


def cached(name: str, fetch):
    path = CACHE / name
    if path.exists():
        return json.loads(path.read_text())
    got = fetch()
    CACHE.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(got))
    return got


def perp_candles(coin: str):
    def fetch():
        while 19 <= time.gmtime().tm_min <= 27:          # the collector's hourly sweep
            time.sleep(20)
        got = hl.post({"type": "candleSnapshot", "req": {"coin": coin, "interval": "15m", "startTime": START * 1000,
                                                         "endTime": END * 1000 - 1}}, url=hl.MAINNET_URL + "/info")
        time.sleep(PAUSE_S)
        return got
    return cached(f"perp_{coin.replace(':', '_')}.json", fetch)


def yahoo(sym: str, interval: str, prepost: bool):
    def fetch():
        q = {"period1": START - 5 * 86_400, "period2": END + 86_400, "interval": interval, "events": "split"}
        if prepost:
            q["includePrePost"] = "true"
        url = f"https://query1.finance.yahoo.com/v8/finance/chart/{urllib.parse.quote(sym)}?{urllib.parse.urlencode(q)}"
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=30) as r:
            got = json.loads(r.read())
        time.sleep(0.8)
        return got
    return cached(f"yahoo_{sym.replace('=', '_')}_{interval}{'_pp' if prepost else ''}.json", fetch)


def bars_of(payload):
    r = payload["chart"]["result"][0]
    q = r["indicators"]["quote"][0]
    return [(t, o, c) for t, o, c in zip(r.get("timestamp") or [], q["open"], q["close"]) if o and c], r


def fmt(x, nd=1):
    return "   -" if x is None else f"{x:.{nd}f}"


def main() -> int:
    now = hip3.markets()
    eq = hip3.ticker_map()
    chosen = sorted([m for m in now if m.name in eq and eq[m.name].kind in T.KINDS and m.volume_usd >= T.MIN_DAY_USD],
                    key=lambda m: -m.volume_usd)
    print(f"#73, run {dt.datetime.now(dt.timezone.utc):%Y-%m-%d %H:%M} UTC; window {T.WINDOW[0]} to {T.WINDOW[1]} (UTC, end excluded)")
    print(f"{len(now)} live markets; {len(chosen)} are mapped, of a measured kind, and at ${T.MIN_DAY_USD / 1e6:.0f}M in the last 24 hours")
    cells, bells, late, vol = [], [], [], {}
    for m in chosen:
        e = eq[m.name]
        futures = e.kind in T.FUTURES_KINDS
        candles = perp_candles(m.coin)
        if not candles or int(candles[0]["t"]) // 1000 > START + T.QUARTER_S:
            first = dt.datetime.fromtimestamp(int(candles[0]["t"]) // 1000, dt.timezone.utc) if candles else None
            late.append((m.name, first))
            continue
        perp = {int(c["t"]) // 1000: float(c["o"]) for c in candles}
        for c in candles:
            t = int(c["t"]) // 1000
            et = dt.datetime.fromtimestamp(t, T.ET)
            h = et.hour + et.minute / 60
            s = ("weekend" if et.weekday() == 5 or (et.weekday() == 4 and h >= 20) or (et.weekday() == 6 and h < 20)
                 else T.session(t) or "overnight")
            vol[s] = vol.get(s, 0.0) + float(c["v"]) * float(c["c"])
        hourly, _ = bars_of(yahoo(e.ticker, "1h", prepost=not futures))
        hourly = [(t, o) for t, o, _ in hourly if START <= t < END]
        skip = set()
        if not futures:
            daily, res = bars_of(yahoo(e.ticker, "1d", prepost=False))
            for s in (res.get("events", {}).get("splits") or {}).values():
                d = dt.datetime.fromtimestamp(int(s["date"]), T.ET).date()
                skip |= {(d + dt.timedelta(days=k)).isoformat() for k in (-1, 0, 1)}
            daily = [(t, o, c) for t, o, c in daily if START <= t < END]
            b = T.bell(daily, perp, skip)
            bells.append((m.name, b))
        prs = T.pairs(hourly, perp, futures=futures, skip_days=skip)
        mid = (START + END) // 2
        halves = [T.by_session(T.pairs([x for x in hourly if (x[0] < mid) == first], perp, futures=futures, skip_days=skip))
                  for first in (True, False)]
        for s, st in sorted(T.by_session(prs).items()):
            cells.append((m.name, e.ticker, e.kind, s, st, halves[0].get(s), halves[1].get(s)))

    print(f"\nleft out, first candle after the window's start: {', '.join(f'{n} ({f:%Y-%m-%d})' if f else n for n, f in late) or 'none'}")
    print(f"\n{'market':9s} {'ticker':9s} {'session':13s} {'pairs':>5s} {'corr':>6s} {'median':>7s} {'95th':>7s} {'drift':>6s}  follows   (gaps in bps)")
    for name, tick, kind, s, st, _, _ in cells:
        word = "too few" if not st.enough else "yes" if st.follows else "NO"
        print(f"{name:9s} {tick:9s} {s:13s} {st.n:5d} {fmt(st.corr, 3):>6s} {fmt(st.median_bps):>7s} {fmt(st.p95_bps):>7s} {fmt(st.mean_bps, 2):>6s}  {word}")
    print("\nsessions (a session stands in when 80% of the markets with 100 pairs follow):")
    for s in T.SESSIONS:
        sts = [c[4] for c in cells if c[3] == s]
        if not sts:
            continue
        ok, good, n = T.stands_in(sts)
        h = [T.stands_in([c[k] for c in cells if c[3] == s and c[k] is not None]) for k in (5, 6)]
        enough = [x for x in sts if x.enough]
        print(f"  {s:13s} {'STANDS IN' if ok else 'does not stand in' if ok is not None else 'no market with enough pairs':18s} "
              f"{good} of {n} follow; median of medians {fmt(statistics.median(x.median_bps for x in enough) if enough else None)} bps; "
              f"too few pairs: {len(sts) - n}; halves (information only): {h[0][1]}/{h[0][2]} then {h[1][1]}/{h[1][2]}")
    print(f"\nat the bell, {len(bells)} stocks and ETFs (medians of each market's daily gaps, bps):")
    print(f"{'market':9s} {'days':>4s} {'open':>6s} {'close':>6s} {'overnight':>9s}")
    for name, b in bells:
        print(f"{name:9s} {b['days']:4d} {fmt(b['open_bps']):>6s} {fmt(b['close_bps']):>6s} {fmt(b['overnight_bps']):>9s}")
    for key, label in (("open_bps", "the open"), ("close_bps", "the close")):
        got = [b[key] for _, b in bells if b[key] is not None]
        ok = T.bell_stands_in(got)
        print(f"  {label}: {'STANDS IN' if ok else 'does not stand in'}; median across markets {fmt(statistics.median(got) if got else None)} bps")
    got = [b["overnight_bps"] for _, b in bells if b["overnight_bps"] is not None]
    print(f"  the overnight return's median difference, across markets (information only): {fmt(statistics.median(got) if got else None)} bps")
    tot = sum(vol.values())
    print("\nshare of the perps' dollar volume by session (information only): "
          + ", ".join(f"{k} {v / tot:.0%}" for k, v in sorted(vol.items(), key=lambda kv: -kv[1])))
    with OUT.open("w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["market", "ticker", "kind", "session", "pairs", "corr", "median_bps", "p95_bps", "drift_bps", "follows"])
        for name, tick, kind, s, st, _, _ in cells:
            w.writerow([name, tick, kind, s, st.n, fmt(st.corr, 4).strip(), fmt(st.median_bps, 2).strip(), fmt(st.p95_bps, 2).strip(),
                        fmt(st.mean_bps, 3).strip(), "too few" if not st.enough else "yes" if st.follows else "no"])
        for name, b in bells:
            for key in ("open_bps", "close_bps", "overnight_bps"):
                w.writerow([name, eq[name].ticker, eq[name].kind, "bell:" + key[:-4], b["days"], "", fmt(b[key], 2).strip(), "", "", ""])
    print(f"\nwrote {OUT.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
