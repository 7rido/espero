"""#81's run: the BTC volatility premium sold every Friday with wings, the criteria, the information-only readouts.

    .venv/bin/python research/volprem.py --counts     # fetch and count only: trades and strikes for six Fridays
    .venv/bin/python research/volprem.py              # the one run; writes research/volprem_run.txt itself

Reads Deribit's public history (no key): option trades from history.deribit.com's
get_last_trades_by_currency_and_time for every Friday 09:00 to 13:00 UTC from 2020-01-03, paged by `has_more` and
de-duplicated on `trade_id`, and the 08:00 UTC delivery prices from get_delivery_prices (index btc_usd). Raw
responses are cached under research/data/volprem/ (git-ignored); an error body is raised, never cached. Applies
espero/volprem.py as registered in research/PREREGISTRATION_VOLPREM.md (8d60f75) and writes research/volprem_run.txt,
research/volprem_weeks.csv and research/volprem_inputs.csv.gz. It refuses to overwrite an existing run file.
`--synthetic DIR` pushes made-up weeks through the same compute, print and write path into DIR (a dry run of the
formatting; it fetches nothing and touches nothing in research/).
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
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from espero import robustness  # noqa: E402
from espero import volprem as V  # noqa: E402
from espero.cascade import nw_t  # noqa: E402
from espero.volf import nw_lags  # noqa: E402

TRADES_URL = "https://history.deribit.com/api/v2/public/get_last_trades_by_currency_and_time"
DELIVERY_URL = "https://www.deribit.com/api/v2/public/get_delivery_prices"
CACHE = ROOT / "research" / "data" / "volprem"
RUN = ROOT / "research" / "volprem_run.txt"
WEEKS = ROOT / "research" / "volprem_weeks.csv"
INPUTS = ROOT / "research" / "volprem_inputs.csv.gz"
FIRST = dt.date(2020, 1, 3)
JUDGED = ("fail", "pass", "provisional", "exploratory")
PAUSE_S = 0.3
UA = {"User-Agent": "Mozilla/5.0 (compatible; research client)"}
PAGE = 1000
COUNT_FRIDAYS = {                                     # the pre-registration's own counts: (trades on next expiry, strikes)
    dt.date(2020, 1, 3): (262, 13), dt.date(2020, 3, 6): (168, 17), dt.date(2020, 9, 11): (120, 19),
    dt.date(2021, 6, 11): (297, 21), dt.date(2023, 6, 9): (508, 16), dt.date(2025, 6, 13): (600, 31),
}
FEES_CHECKED = (
    "Fee schedule checked 2026-11-10 against Deribit's published page (support.deribit.com/hc/en-us/articles/"
    "25944746248989, 'Fees', updated that day): options 3 bps of the underlying maker and taker, capped at 12.5% of "
    "the premium; delivery 0.015% (1.5 bps) of the underlying, capped at 12.5% of the option's value, with daily "
    "options exempt and Friday expiries not; the BTC perpetual taker 3.5 bps (hedge cost charged 6 bps, higher). "
    "Every figure in the contract equals or exceeds the page; nothing higher is charged. It is today's schedule, not "
    "the one in force in 2020 to 2024.")


# ------------------------------------------------------------------------------------------------ fetching
def _get(url: str, params: dict) -> dict:
    full = url + "?" + urllib.parse.urlencode(params)
    last = None
    for attempt in range(6):
        try:
            with urllib.request.urlopen(urllib.request.Request(full, headers=UA), timeout=90) as r:
                body = json.loads(r.read())
            time.sleep(PAUSE_S)
            if "error" in body or not isinstance(body.get("result"), dict):
                raise RuntimeError(f"{url} {params}: {str(body)[:300]}")
            return body["result"]
        except (urllib.error.URLError, TimeoutError, ConnectionError, json.JSONDecodeError) as exc:
            last = exc
            time.sleep(2.0 * (attempt + 1))
    raise RuntimeError(f"{url} {params}: gave up after 6 tries: {last}")


def _ms(d: dt.date, hour: int) -> int:
    return int(dt.datetime(d.year, d.month, d.day, hour, tzinfo=dt.timezone.utc).timestamp()) * 1000


def fetch_trades(friday: dt.date) -> list:
    """Every BTC option trade 09:00 to 13:00 UTC on `friday`, raw, from the cache or the history server."""
    path = CACHE / f"trades_{friday.isoformat()}.json"
    if path.exists():
        return json.loads(path.read_text())
    start, end = _ms(friday, 9), _ms(friday, 13)
    out, seen, cursor = [], set(), start
    while True:
        res = _get(TRADES_URL, {"currency": "BTC", "kind": "option", "start_timestamp": cursor, "end_timestamp": end,
                                "count": PAGE, "sorting": "asc", "include_old": "true"})
        page = res["trades"]
        new = [t for t in page if t["trade_id"] not in seen]
        for t in new:
            seen.add(t["trade_id"])
        out += new
        if not res.get("has_more"):
            break
        if not new:
            raise RuntimeError(f"{friday}: a full page added no new trade_id while has_more was true")
        cursor = max(int(t["timestamp"]) for t in page)
    CACHE.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(out))
    return out


def fetch_deliveries() -> dict:
    path = CACHE / "delivery_btc_usd.json"
    if path.exists():
        raw = json.loads(path.read_text())
    else:
        raw, offset = [], 0
        while True:
            res = _get(DELIVERY_URL, {"index_name": "btc_usd", "offset": offset, "count": 1000})
            rows = res["data"]
            raw += rows
            offset += len(rows)
            if not rows or offset >= res["records_total"]:
                break
        if len(raw) != res["records_total"]:
            raise RuntimeError(f"delivery prices: {len(raw)} rows of {res['records_total']}")
        CACHE.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(raw))
    return {dt.date.fromisoformat(r["date"]): float(r["delivery_price"]) for r in raw}


def to_trades(raw: list) -> list:
    def num(x):
        return float(x) if x is not None else float("nan")
    return [V.Trade(int(t["timestamp"]), str(t["trade_id"]), t["instrument_name"], num(t.get("iv")),
                    num(t.get("index_price")), num(t.get("mark_price"))) for t in raw]


def fridays(now: dt.datetime) -> list:
    """Every Friday from 2020-01-03 whose options (expiring the next Friday 08:00 UTC) had settled by `now`."""
    out, d = [], FIRST
    while dt.datetime(d.year, d.month, d.day, 8, tzinfo=dt.timezone.utc) + dt.timedelta(days=7) <= now:
        out.append(d)
        d += dt.timedelta(days=7)
    return out


# ------------------------------------------------------------------------------------------------ ledger
def ledger_other_p() -> list:
    d = pd.read_csv(ROOT / "research" / "trials.csv", dtype={"test": str})
    judged = d[d["status"].isin(JUDGED) & (d["test"] != "81")]
    return list(pd.to_numeric(judged["p_from_t"], errors="coerce").fillna(1.0).to_numpy())


def var_week() -> float:
    d = pd.read_csv(ROOT / "research" / "trials_dsr.csv")
    return float(np.var(d["sharpe"].dropna() / math.sqrt(52), ddof=1))


# ------------------------------------------------------------------------------------------------ printing
class Out:
    def __init__(self):
        self.lines = []

    def __call__(self, text: str = "") -> None:
        print(text)
        self.lines.append(text)

    def text(self) -> str:
        return "\n".join(self.lines) + "\n"


def pct(x, digits=3) -> str:
    return "-" if x is None or (isinstance(x, float) and math.isnan(x)) else f"{x * 100:+.{digits}f}%"


def usd(x) -> str:
    return "-" if x is None or (isinstance(x, float) and math.isnan(x)) else f"{x:,.1f}"


def worst_run(values, k=13):
    """The lowest sum of `k` consecutive priced weeks, and the Friday it starts on's index."""
    if len(values) < k:
        return float("nan"), -1
    sums = [sum(values[i:i + k]) for i in range(len(values) - k + 1)]
    i = min(range(len(sums)), key=sums.__getitem__)
    return sums[i], i


def nwt(x) -> float:
    return nw_t(np.array(x), nw_lags(len(x))) if len(x) >= 3 else float("nan")


def reading(out, label: str, weeks, unit: str) -> None:
    """One block of readings, in a share of M or of the index."""
    div = (lambda w: w.M) if unit == "M" else (lambda w: w.F)          # noqa: E731
    h = [w.profit_h / div(w) for w in weeks]
    u = [w.profit_u / div(w) for w in weeks]
    wh, ih = worst_run(h)
    wu, iu = worst_run(u)
    out(f"  [{label}, in a share of {'M' if unit == 'M' else 'the index'}]")
    out(f"    hedged: mean {pct(statistics.fmean(h))}, NW t {nwt(h):.2f}, profit factor {V.profit_factor(h)}, worst week "
        f"{pct(min(h))} ({weeks[h.index(min(h))].friday}), worst 13 weeks {pct(wh)} from {weeks[ih].friday if ih >= 0 else '-'}")
    out(f"    unhedged: mean {pct(statistics.fmean(u))}, NW t {nwt(u):.2f}, profit factor {V.profit_factor(u)}, worst week "
        f"{pct(min(u))} ({weeks[u.index(min(u))].friday}), worst 13 weeks {pct(wu)} from {weeks[iu].friday if iu >= 0 else '-'}")
    since = [x for x, w in zip(h, weeks) if w.friday >= V.SINCE]
    out(f"    hedged since {V.SINCE}: mean {pct(statistics.fmean(since)) if since else '-'} over {len(since)} weeks, "
        f"NW t {nwt(since):.2f}")
    years = sorted({w.friday.year for w in weeks})
    out("    by calendar year (hedged mean, unhedged mean, weeks): " + "; ".join(
        f"{y} {pct(statistics.fmean([x for x, w in zip(h, weeks) if w.friday.year == y]))} "
        f"{pct(statistics.fmean([x for x, w in zip(u, weeks) if w.friday.year == y]))} "
        f"{sum(1 for w in weeks if w.friday.year == y)}" for y in years))


def describe(out, w) -> None:
    out(f"    {w.friday}: F {usd(w.F)}, body {w.K0:,.0f} at {w.sig0:.1%}, wings {w.Kp:,.0f} / {w.Kc:,.0f}, settled {usd(w.S)}; "
        f"credit {usd(w.credit)}, costs {usd(w.gap + w.fee)}, payout {usd(w.payout)}, settlement fees {usd(w.settle_fee)}, "
        f"hedge pnl {usd(w.hedge_pnl)} cost {usd(w.hedge_cost)}; M {usd(w.M)}; profit hedged {usd(w.profit_h)} unhedged "
        f"{usd(w.profit_u)}; returns {pct(w.ret_h)} / {pct(w.ret_u)}")


def report(out, all_weeks: list, deliveries: dict, other_p: list) -> tuple:
    weeks = [w for w in all_weeks if isinstance(w, V.Week)]
    skips = [w for w in all_weeks if isinstance(w, V.Skip)]
    n = len(weeks)
    if n < 3:
        out(f"only {n} priced weeks of {len(all_weeks)}; nothing to judge")
        return "INCONCLUSIVE", []
    verdict, checks, st = V.criteria(weeks, other_p)
    out(f"\n== The registered criteria, on {n} priced weeks of {len(all_weeks)} Fridays")
    for c in checks:
        out(f"{c.n}. {'ok  ' if c.ok else 'MISS'} {c.text}")
    out(f"\nVERDICT: {verdict}" + ("" if verdict != "INCONCLUSIVE" else f" (fewer than {V.MIN_WEEKS} priced weeks)"))
    for c in checks:
        if not c.ok:
            out(f"  missed {c.n}: {c.text}")

    out("\n== Information only")
    out(f"priced {n}, skipped {len(skips)}; by reason: " + ", ".join(
        f"{r}: {sum(1 for s in skips if s.reason == r)}" for r in V.REASONS))
    out(f"Fridays with no trade of the next expiry in the window: {sum(1 for s in skips if s.n_trades == 0)}; trades "
        f"dropped for a missing or non-positive iv, in priced weeks: {sum(w.n_unusable for w in weeks)}")
    for label, unit in (("M", "M"), ("index", "index")):
        reading(out, label, weeks, unit)
    out("\n  2020-03-06 and the week after:")
    for d in (dt.date(2020, 3, 6), dt.date(2020, 3, 13)):
        hit = next((w for w in all_weeks if w.friday == d), None)
        if isinstance(hit, V.Week):
            describe(out, hit)
        else:
            out(f"    {d}: " + (f"skipped, {hit.reason}" if hit else "not in the run"))
    credit = sum(w.credit for w in weeks)
    out(f"\n  share of the credit kept: hedged {sum(w.profit_h for w in weeks) / credit:+.1%}, unhedged "
        f"{sum(w.profit_u for w in weeks) / credit:+.1%} (sum of profit over sum of credit, {usd(credit / n)} a week)")
    comp = {"half gaps": [w.gap for w in weeks], "trading fees": [w.fee for w in weeks],
            "settlement fees": [w.settle_fee for w in weeks], "hedge cost": [w.hedge_cost for w in weeks]}
    out("  cost by component, mean a week: " + "; ".join(
        f"{k} ${statistics.fmean(v):,.1f} ({pct(statistics.fmean(x / w.M for x, w in zip(v, weeks)))} of M, "
        f"{statistics.fmean(x / w.F for x, w in zip(v, weeks)) * 1e4:.1f} bps of the index)" for k, v in comp.items()))
    out(f"  gross of the hedge, mean a week: credit {pct(statistics.fmean(w.credit / w.M for w in weeks))} of M, payout "
        f"{pct(statistics.fmean(w.payout / w.M for w in weeks))}, hedge profit "
        f"{pct(statistics.fmean(w.hedge_pnl / w.M for w in weeks))}")
    iv = [w.sig0 for w in weeks]
    rv = [w.realized for w in weeks]
    out(f"  body implied volatility against the volatility realized at the daily prices: mean {statistics.fmean(iv):.1%} vs "
        f"{statistics.fmean(rv):.1%} ({statistics.fmean(a - b for a, b in zip(iv, rv)) * 100:+.1f} points; implied above "
        f"realized in {sum(1 for a, b in zip(iv, rv) if a > b)} of {n} weeks)")
    traded = [w.hedge_traded for w in weeks]
    out(f"  the hedge's dollars traded a week: mean ${statistics.fmean(traded):,.0f}, median ${statistics.median(traded):,.0f}; "
        f"turnover (hedge dollars traded over the index) mean {statistics.fmean(w.hedge_traded / w.F for w in weeks):.2f} "
        f"a week")
    marked = [w for w in weeks if w.mark_credit is not None]
    if marked:
        diff = [w.credit - w.mark_credit for w in marked]
        out(f"  the model's credit against the credit from the same strikes' last mark price x index in the window "
            f"({len(marked)} of {n} weeks had all four legs marked): mean model minus mark ${statistics.fmean(diff):+,.1f} "
            f"({statistics.fmean(d / w.F for d, w in zip(diff, marked)) * 1e4:+.1f} bps of the index), median "
            f"${statistics.median(diff):+,.1f}, mean ratio {statistics.fmean(w.credit / w.mark_credit for w in marked if w.mark_credit):.3f}")
    else:
        out("  the model's credit against the marks: no week had all four legs marked in the window")
    out(f"  worst unhedged loss over M "
        f"{max(-w.profit_u / w.M for w in weeks):.3f} (settlement fees are not in M, so it can pass 1)")

    out("\n== Robustness, information only")
    sr = robustness.deflated_sharpe([w.ret_h for w in weeks], st["fam"], var_week())
    out(f"deflated Sharpe on the hedged weekly returns (N = {st['fam']} judged rows): weekly Sharpe {sr.get('sharpe'):.4f}, "
        f"expected best of N {sr.get('expected_max'):.4f}, DSR {sr.get('dsr'):.3f}")
    out("PBO (one configuration), purged k-fold (nothing fitted) and capacity (no recorded depth before 2026-11-02): "
        "not applicable, as registered.")
    return verdict, checks


def write_files(weeks_path: Path, inputs_path: Path, all_weeks: list, trades_by_friday: dict, deliveries: dict) -> None:
    with weeks_path.open("w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["friday", "status", "reason", "trades", "unusable_iv", "strikes", "F", "settlement", "K0", "Kc", "Kp",
                    "sigma0", "credit", "half_gaps", "trading_fees", "payout", "settlement_fees", "hedge_pnl", "hedge_cost",
                    "hedge_traded", "M", "profit_hedged", "profit_unhedged", "ret_hedged", "ret_unhedged", "ret_hedged_x2",
                    "realized_vol", "mark_credit"])
        for x in all_weeks:
            if isinstance(x, V.Skip):
                w.writerow([x.friday, "skipped", x.reason, x.n_trades] + [""] * 24)
            else:
                w.writerow([x.friday, "priced", "", x.n_trades, x.n_unusable, x.n_strikes, x.F, x.S, x.K0, x.Kc, x.Kp,
                            round(x.sig0, 6), round(x.credit, 4), round(x.gap, 4), round(x.fee, 4), round(x.payout, 4),
                            round(x.settle_fee, 4), round(x.hedge_pnl, 4), round(x.hedge_cost, 4), round(x.hedge_traded, 2),
                            round(x.M, 4), round(x.profit_h, 4), round(x.profit_u, 4), round(x.ret_h, 6), round(x.ret_u, 6),
                            round(x.ret_h2, 6), round(x.realized, 6), "" if x.mark_credit is None else round(x.mark_credit, 4)])
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["kind", "friday", "ts_ms", "trade_id", "instrument", "iv", "index_price", "mark_price", "delivery_price"])
    for f in sorted(trades_by_friday):
        for t in V.window_trades(trades_by_friday[f], f):
            w.writerow(["trade", f, t.ts_ms, t.trade_id, t.name, t.iv, t.index, t.mark, ""])
    for d in sorted(deliveries):
        w.writerow(["delivery", d, "", "", "", "", "", "", deliveries[d]])
    inputs_path.write_bytes(gzip.compress(buf.getvalue().encode(), mtime=0))


# ------------------------------------------------------------------------------------------------ the runs
def run_counts() -> int:
    """Fetch six Fridays and count: no price, no volatility, no profit is printed."""
    ok = True
    for f, (want_trades, want_strikes) in sorted(COUNT_FRIDAYS.items()):
        win = V.window_trades(to_trades(fetch_trades(f)), f)
        any_strikes = {p[1] for p in (V.parse_instrument(t.name) for t in win) if p}
        got = (len(win), len(any_strikes))
        print(f"{f}: raw trades {len(fetch_trades(f))}; next expiry in the window {got[0]} on {got[1]} strikes "
              f"(registered {want_trades} on {want_strikes}); unusable iv {sum(1 for t in win if not V._usable(t))}; "
              f"usable strikes {len(V.strike_table(win))}")
        ok &= got == (want_trades, want_strikes)
    print("MATCH" if ok else "MISMATCH")
    return 0 if ok else 1


def synthetic(folder: Path) -> int:
    """A made-up run through the whole print and write path."""
    rng = np.random.default_rng(1)
    folder.mkdir(parents=True, exist_ok=True)
    strikes = [80_000, 85_000, 88_000, 95_000, 100_000, 105_000, 112_000, 115_000, 120_000, 125_000]
    all_weeks, by_friday, deliveries = [], {}, {}
    d = dt.date(2020, 1, 3)
    for k in range(60):
        f = d + dt.timedelta(days=7 * k)
        spot = 100_000.0
        exp = f + dt.timedelta(days=7)
        tr = [V.Trade(_ms(f, 9) + 1000 * i, f"{k}{i}", f"BTC-{exp.day}{exp.strftime('%b').upper()}{exp.strftime('%y')}-{s}-"
                      f"{'CP'[i % 2]}", 50.0 + rng.normal(0, 2), spot, 0.01) for i, s in enumerate(strikes)]
        for j in range(1, 8):
            deliveries[f + dt.timedelta(days=j)] = spot * math.exp(rng.normal(0, 0.02) * j ** 0.5)
        if k % 11 == 5:
            tr = tr[:3]
        by_friday[f] = tr
        all_weeks.append(V.evaluate_week(f, tr, deliveries))
    out = Out()
    out(f"synthetic dry run of #81's compute and print path, {len(all_weeks)} Fridays")
    report(out, all_weeks, deliveries, [0.5] * 5)
    write_files(folder / "weeks.csv", folder / "inputs.csv.gz", all_weeks, by_friday, deliveries)
    (folder / "run.txt").write_text(out.text())
    print(f"\nwrote {folder}")
    return 0


def main(argv) -> int:
    if "--counts" in argv:
        return run_counts()
    if "--synthetic" in argv:
        return synthetic(Path(argv[argv.index("--synthetic") + 1]))
    if RUN.exists():
        print(f"{RUN.relative_to(ROOT)} exists: #81 is run once; a rerun is for a defect against the contract only, "
              f"and the earlier output is kept (move it aside by hand and say so in the result)")
        return 2
    out = Out()
    now = dt.datetime.now(dt.timezone.utc)
    out(f"#81, run {now.strftime('%Y-%m-%d %H:%M')} UTC, as registered in research/PREREGISTRATION_VOLPREM.md (8d60f75)")
    out(FEES_CHECKED)
    days = fridays(now)
    deliveries = fetch_deliveries()
    by_friday, all_weeks, empty = {}, [], 0
    for f in days:
        raw = fetch_trades(f)
        by_friday[f] = to_trades(raw)
        all_weeks.append(V.evaluate_week(f, by_friday[f], deliveries))
        empty += 0 if raw else 1
    out(f"{len(days)} Fridays from {days[0]} to {days[-1]} (the last expires {days[-1] + dt.timedelta(days=7)}); "
        f"{sum(len(v) for v in by_friday.values()):,} raw trades fetched; Fridays whose fetch returned no trade at all: {empty}; "
        f"{len(deliveries):,} delivery prices from {min(deliveries)} to {max(deliveries)}")
    verdict, _ = report(out, all_weeks, deliveries, ledger_other_p())
    write_files(WEEKS, INPUTS, all_weeks, by_friday, deliveries)
    out(f"\nwrote {RUN.relative_to(ROOT)}, {WEEKS.relative_to(ROOT)} and {INPUTS.relative_to(ROOT)}")
    RUN.write_text(out.text())
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
