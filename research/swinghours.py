"""#82: session swings, run once (research/PREREGISTRATION_SWINGHOURS.md).

    python research/swinghours.py

Reads Binance USD-M hourly bars from data/pit/klines_1h (nothing is fetched, nothing under data/ is written), computes
every profile with espero/swinghours.py, prints the four pre-registered readouts and the information beside them, and
writes research/swinghours_run.txt and research/swinghours_profiles.csv.
"""
from __future__ import annotations

import csv
import io
import sys
from contextlib import redirect_stdout
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from espero import swinghours as S  # noqa: E402

DATA = ROOT / "data" / "pit" / "klines_1h"
COINS = ("AAVE", "ADA", "AVAX", "BNB", "BTC", "DOGE", "ENA", "ETH", "LINK", "LTC", "NEAR", "SOL", "UNI", "WLD", "XRP",
         "ZEC", "ZRO")
RAW_COINS = ("BTC", "ETH", "SOL")
OUT_RUN = ROOT / "research" / "swinghours_run.txt"
OUT_PROFILES = ROOT / "research" / "swinghours_profiles.csv"
COLS = ["open_time", "open", "high", "low", "close", "volume"]


def load(coin: str) -> pd.DataFrame:
    files = sorted((DATA / f"{coin}USDT").glob("*.parquet"))
    frames = [pd.read_parquet(f, columns=COLS) for f in files if f.stem <= "2026-09"]
    return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame(columns=COLS)


def fmt(x: float, d: int = 3) -> str:
    return "n/a" if x is None or not np.isfinite(x) else f"{x:.{d}f}"


def run() -> str:
    raw, kept, dropped = {}, {}, {}
    for coin in COINS:
        f = load(coin)
        raw[coin] = f
        s = S.swings(f)
        kept[coin] = s
        dropped[coin] = len(f.drop_duplicates("open_time")) - len(s)
    halves = {c: S.halves(s) for c, s in kept.items()}
    comparing = [c for c in COINS if S.compares(halves[c])]
    rows, out = [], []
    p = out.append
    p("#82 session swings: run once, research/PREREGISTRATION_SWINGHOURS.md")
    p("")
    p("coins and bars (kept; dropped = bad bars and the first 720 hours):")
    for c in COINS:
        h = halves[c]
        p(f"  {c:5s} kept {len(kept[c]):>6,}  dropped {dropped[c]:>5,}  months in {S.months(h['in']):>2}, "
          f"out {S.months(h['out']):>2}  {'compares' if c in comparing else 'information only'}")
    p(f"comparing coins: {len(comparing)}")
    p("")
    results = {}
    for measure in S.MEASURES:
        by_coin = {c: {k: S.profiles(halves[c][k], measure) for k in ("in", "out")} for c in comparing}
        rows += S.summary_rows(by_coin, measure)
        rep = {clock: S.repeat(by_coin, measure, clock) for clock in S.CLOCKS}
        results[measure] = (by_coin, rep)
    body_by_coin, body_rep = results["body"]

    p("READOUT 1, the hours repeat (body, weekday hours, UTC clock):")
    r = body_rep["utc"]
    p(f"  pooled Spearman in vs out {fmt(r.pooled_rho)} (needs >= {S.POOLED_MIN}); coins at >= {S.COIN_MIN}: "
      f"{r.coins_at_min} of {r.coins} (needs {S.COINS_NEEDED})")
    p(f"  => {'THE HOURS REPEAT' if r.repeats else 'THE HOURS DO NOT REPEAT'}")
    for measure in S.MEASURES:
        for clock in S.CLOCKS:
            x = results[measure][1][clock]
            p(f"  {measure:5s} {clock:8s} pooled {fmt(x.pooled_rho)}  coins >= {S.COIN_MIN}: {x.coins_at_min}/{x.coins}"
              f"  {'repeats' if x.repeats else 'does not repeat'}")
    p("  per coin (body): " + ", ".join(f"{c} {fmt(body_rep['utc'].coin_rho[c], 2)}/{fmt(body_rep['new_york'].coin_rho[c], 2)}"
                                        for c in comparing) + "   (UTC/New York)")
    p("")

    p("READOUT 2, the clock (body):")
    p(f"  pooled out-of-sample correlation UTC {fmt(body_rep['utc'].pooled_rho)}, New York "
      f"{fmt(body_rep['new_york'].pooled_rho)} => {S.clock_readout(body_rep['utc'], body_rep['new_york']).upper()}")
    for clock in S.CLOCKS:
        pout = S.pooled([v["out"].hours[clock] for v in body_by_coin.values()])
        p(f"  {clock:8s} out-of-sample peak-to-trough {fmt(S.peak_to_trough(pout), 2)}")
    p(f"  range: UTC {fmt(results['range'][1]['utc'].pooled_rho)}, New York {fmt(results['range'][1]['new_york'].pooled_rho)}"
      f" => {S.clock_readout(results['range'][1]['utc'], results['range'][1]['new_york'])}")
    p("")

    p("READOUT 3, the size (body, pooled, normalised swing: 1.0 = the coin's last month's average hour):")
    for half in ("in", "out"):
        for clock in S.CLOCKS:
            ph = S.pooled([v[half].hours[clock] for v in body_by_coin.values()])
            busy, quiet, ratio = S.busiest_quietest(ph, 3)
            p(f"  {half:3s} {clock:8s} busiest " + ", ".join(f"{S.describe_hour(h, clock)} {ph[h]:.2f}" for h in busy)
              + "; quietest " + ", ".join(f"{S.describe_hour(h, clock)} {ph[h]:.2f}" for h in quiet)
              + f"; ratio {ratio:.2f}")
        days = S.pooled([v[half].days for v in body_by_coin.values()])
        p(f"  {half:3s} days Mon..Sun " + " ".join(f"{d:.2f}" for d in days)
          + f"; weekend over weekdays {S.weekend_ratio(days):.2f}")
    p("")

    p("READOUT 4, the weekend:")
    q = {half: S.weekend_quietest(S.pooled([v[half].days for v in body_by_coin.values()])) for half in ("in", "out")}
    p(f"  Saturday and Sunday the two quietest days: in {q['in']}, out {q['out']} => "
      f"{'THE WEEKEND REPEATS' if all(q.values()) else 'THE WEEKEND DOES NOT REPEAT'}")
    p("")

    p("INFORMATION ONLY")
    week_out = S.pooled([v["out"].week for v in body_by_coin.values()])
    busy, quiet, _ = S.busiest_quietest(week_out, 5)
    p("  the week, out-of-sample, busiest: " + ", ".join(f"{S.week_slot_name(i)} UTC {week_out[i]:.2f}" for i in busy))
    p("  the week, out-of-sample, quietest: " + ", ".join(f"{S.week_slot_name(i)} UTC {week_out[i]:.2f}" for i in quiet))
    ref = S.pooled([v["in"].hours["utc"] for v in body_by_coin.values()])
    years = {}
    for c in comparing:
        for y, rho in S.year_rhos(kept[c], ref).items():
            years.setdefault(y, []).append(rho)
    p("  each year against the in-sample pooled profile (median over coins): "
      + ", ".join(f"{y} {np.nanmedian(v):.2f}" for y, v in sorted(years.items())))
    for c in ("ENA", "ZRO"):
        if c not in comparing and len(kept[c]):
            pc = S.profiles(halves[c]["out"]).hours["utc"]
            p(f"  {c} (not comparing) out-of-sample against the pooled out-of-sample profile: "
              f"{fmt(S.spearman(pc, S.pooled([v['out'].hours['utc'] for v in body_by_coin.values()])), 2)}")
    for c in RAW_COINS:
        bps = S.raw_bps_median(raw[c][S.to_utc(raw[c]["open_time"].to_numpy()) >= S.SPLIT])
        p(f"  {c} median hour, out-of-sample, raw bps by weekday hour UTC 00..23: " + " ".join(f"{b:.0f}" for b in bps))
    signed = S.pooled([S.signed_by_slot(halves[c]["out"]) for c in comparing]) * 1e4
    order = np.argsort(signed)
    p("  NOT A SIGNAL, signed mean return by week slot out-of-sample (bps), highest: "
      + ", ".join(f"{S.week_slot_name(i)} {signed[i]:+.1f}" for i in order[::-1][:3])
      + "; lowest: " + ", ".join(f"{S.week_slot_name(i)} {signed[i]:+.1f}" for i in order[:3]))
    with OUT_PROFILES.open("w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=["coin", "measure", "half", "clock", "hour", "swing"])
        w.writeheader()
        w.writerows(rows)
    return "\n".join(out) + "\n"


def main() -> int:
    buf = io.StringIO()
    with redirect_stdout(buf):
        text = run()
    OUT_RUN.write_text(text, encoding="utf-8")
    print(text, end="")
    return 0


if __name__ == "__main__":
    sys.exit(main())
