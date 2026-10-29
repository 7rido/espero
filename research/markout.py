"""Hypothesis #39 — what our fills actually cost, measured on prints.

    python research/markout.py fetch     # download, reduce each coin-day, delete the raw file (resumable)
    python research/markout.py report    # every pre-registered table; writes espero/costs_table.py

The sets, definitions, tolerances and criteria are frozen in research/PREREGISTRATION_MARKOUT.md;
the verdict is written by hand into RESULTS_MARKOUT.md.
"""
from __future__ import annotations

import http.client
import json
import sys
import time
import urllib.error
import urllib.request
import zipfile
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path
from typing import Dict, List, Optional

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "research"))
from espero import aggr, fundsplit  # noqa: E402
from espero import bids as bd  # noqa: E402
from espero import liq as lq  # noqa: E402
from espero import lows as lw  # noqa: E402
from espero import markout as mk  # noqa: E402

COINS = ["BTC", "ETH", "SOL", "XRP"]
RAW = ROOT / "data" / "markout" / "raw"
DAYS_DIR = ROOT / "data" / "markout" / "days"
OUT_DAYS = ROOT / "research" / "markout_days.csv.gz"
OUT_SETTLE = ROOT / "research" / "markout_settle.csv.gz"
MANIFEST = ROOT / "research" / "markout_manifest.json"
TABLE_PY = ROOT / "espero" / "costs_table.py"
WORKERS = 6

B_DAYS = [d.strftime("%Y-%m-%d") for d in pd.date_range("2026-04-01", "2026-10-27")]
V1_DAYS = [d.strftime("%Y-%m-%d") for d in pd.date_range("2023-06-01", "2024-03-01", freq="MS")]
V2_DAYS = [d.strftime("%Y-%m-%d") for d in pd.date_range("2026-04-01", "2026-10-01", freq="MS")]
H_DAYS = [d.strftime("%Y-%m-%d") for d in pd.date_range("2024-11-01", "2026-10-01", freq="MS")]
B_HALF, H_HALF = "2026-07-01", "2025-11-01"
LIQ_MONTHS = ["2026-04", "2026-05", "2026-06", "2026-07", "2026-08", "2026-09", "2026-10"]
LIQ_TOP = 0.95

BINANCE = "https://data.binance.vision/data/futures/um/daily/{kind}/{sym}/{sym}-{kind}-{day}.zip"
TARDIS = "https://datasets.tardis.dev/v1/{ex}/{kind}/{y}/{m}/{d}/{sym}.csv.gz"
AGG_COLS = ["agg_trade_id", "price", "quantity", "first_trade_id", "last_trade_id", "transact_time",
            "is_buyer_maker"]
BT_COLS = ["update_id", "best_bid_price", "best_bid_qty", "best_ask_price", "best_ask_qty",
           "transaction_time", "event_time"]


# ---------------------------------------------------------------- downloads

def get(url: str, path: Path, tries: int = 8) -> Optional[Path]:
    """The file at `path`, downloaded once; None for a 404 (remembered as .none)."""
    if path.exists():
        return path
    if path.with_suffix(".none").exists():
        return None
    path.parent.mkdir(parents=True, exist_ok=True)
    for k in range(tries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "espero"})
            with urllib.request.urlopen(req, timeout=300) as r, open(path.with_suffix(".part"), "wb") as f:
                while True:
                    chunk = r.read(1 << 20)
                    if not chunk:
                        break
                    f.write(chunk)
            path.with_suffix(".part").rename(path)
            return path
        except urllib.error.HTTPError as exc:
            if exc.code == 404:
                path.with_suffix(".none").write_text("")
                return None
            if exc.code in (401, 403) or k == tries - 1:
                raise
        except (urllib.error.URLError, TimeoutError, ConnectionError, http.client.HTTPException, OSError):
            if k == tries - 1:
                raise
        time.sleep(min(60.0, 2.0 ** k))
    return None


def binance(kind: str, coin: str, day: str) -> Optional[Path]:
    sym = f"{coin}USDT"
    return get(BINANCE.format(kind=kind, sym=sym, day=day), RAW / "binance" / kind / f"{sym}-{day}.zip")


def tardis(ex: str, kind: str, coin: str, day: str) -> Optional[Path]:
    sym = f"{coin}USDT" if ex == "binance-futures" else coin
    y, m, d = day.split("-")
    return get(TARDIS.format(ex=ex, kind=kind, y=y, m=m, d=d, sym=sym), RAW / ex / kind / f"{sym}-{day}.csv.gz")


# ---------------------------------------------------------------- readers

def _zip_csv(path: Path, cols: List[str], usecols: List[str]) -> pd.DataFrame:
    with zipfile.ZipFile(path) as z:
        name = z.namelist()[0]
        with z.open(name) as f:
            first = f.readline().decode()
        header = not first.split(",")[0].strip().lstrip("-").replace(".", "").isdigit()
        with z.open(name) as f:
            df = pd.read_csv(f, header=0 if header else None, names=None if header else cols)
    df.columns = cols
    return df[usecols]


def _ms(t: pd.Series) -> np.ndarray:
    """Milliseconds, whether the source wrote ms or µs."""
    t = t.to_numpy(np.int64)
    return t // 1000 if len(t) and t.max() > 10 ** 14 else t


def agg_trades(path: Path) -> pd.DataFrame:
    df = _zip_csv(path, AGG_COLS, ["price", "quantity", "transact_time", "is_buyer_maker"])
    maker = df["is_buyer_maker"].astype(str).str.lower().eq("true").to_numpy()
    return pd.DataFrame({"t": _ms(df["transact_time"]), "p": df["price"].to_numpy(float),
                         "q": df["quantity"].to_numpy(float), "s": np.where(maker, -1, 1).astype(np.int8)})


def book_ticker(path: Path) -> mk.Mids:
    df = _zip_csv(path, BT_COLS, ["best_bid_price", "best_ask_price", "transaction_time"])
    return mk.quote_mids(_ms(df["transaction_time"]), df["best_bid_price"], df["best_ask_price"])


def tardis_trades(path: Path) -> pd.DataFrame:
    df = pd.read_csv(path, usecols=["timestamp", "side", "price", "amount"])
    df = df[df["side"].isin(["buy", "sell"])]
    return pd.DataFrame({"t": df["timestamp"].to_numpy(np.int64) // 1000, "p": df["price"].to_numpy(float),
                         "q": df["amount"].to_numpy(float),
                         "s": np.where(df["side"].eq("buy"), 1, -1).astype(np.int8)})


def tardis_quotes(path: Path) -> mk.Mids:
    df = pd.read_csv(path, usecols=["timestamp", "bid_price", "ask_price"]).dropna()
    return mk.quote_mids(df["timestamp"].to_numpy(np.int64) // 1000, df["bid_price"], df["ask_price"])


def liq_hours() -> Dict[str, np.ndarray]:
    """Per coin, the hours (ms) whose aggr liquidation notional is in its top 5% over 2026-04 → 10."""
    files = [p for m in LIQ_MONTHS for p in (ROOT / "data" / "aggr").glob(f"*/{m}.csv.gz")]
    raw = pd.concat([pd.read_csv(p) for p in files], ignore_index=True)
    out = {}
    for c, df in aggr.panel(raw).items():
        if c not in COINS:
            continue
        tot = (df["long"] + df["short"]).dropna()
        cut = tot.quantile(LIQ_TOP)
        hrs = tot.index[tot > cut]
        out[c] = pd.DatetimeIndex(hrs).as_unit("ms").asi8.astype(np.int64)   # the index's unit varies (s here)
        assert len(out[c]) and (out[c] > 1.7e12).all() and (out[c] < 1.8e12).all(), c
    return out


# ---------------------------------------------------------------- jobs

def _rows(df: pd.DataFrame, **tags) -> pd.DataFrame:
    for k, v in tags.items():
        df.insert(0, k, v)
    return df


def _prints(df: pd.DataFrame) -> Optional[mk.Prints]:
    df = mk.collapse(df)
    return mk.Prints.frame(df) if len(df) >= mk.MIN_PRINTS else None


def settle_prices(pr: mk.Prints, day: str) -> pd.DataFrame:
    """#38's P(t) and P(t + 30 min): the first print at or after each 00/08/16 UTC settlement."""
    rows = []
    for hh in (0, 8, 16):
        t0 = int(pd.Timestamp(f"{day} {hh:02d}:00", tz="UTC").value // 10 ** 6)
        i0, i30 = np.searchsorted(pr.t, [t0, t0 + 1_800_000])
        if i30 < len(pr) and pr.t[i0] < t0 + 300_000 and pr.t[i30] < t0 + 2_100_000:
            rows.append({"ts": t0 // 1000, "p0": pr.p[i0], "p30": pr.p[i30]})
    return pd.DataFrame(rows)


def job(kind: str, coin: str, day: str, liq: Optional[np.ndarray]) -> dict:
    out = DAYS_DIR / kind / f"{coin}-{day}.csv"
    if out.exists() or out.with_suffix(".none").exists():
        return {"job": kind, "coin": coin, "day": day, "status": "cached"}
    raws: List[Path] = []
    try:
        frames = []
        if kind == "B":
            f = binance("aggTrades", coin, day)
            raws = [f] if f else []
            pr = _prints(agg_trades(f)) if f else None
            if pr is not None:
                frames.append(_rows(mk.measures(pr, mk.proxy_mids(pr), liq), set="B", source="archive",
                                    mid="proxy", venue="binance", coin=coin, day=day))
                s = settle_prices(pr, day)
                if len(s):
                    s.assign(coin=coin).to_csv(DAYS_DIR / "settle" / f"{coin}-{day}.csv", index=False)
        elif kind == "V1":
            f, q = binance("aggTrades", coin, day), binance("bookTicker", coin, day)
            raws = [x for x in (f, q) if x]
            pr = _prints(agg_trades(f)) if f and q else None
            if pr is not None:
                for name, mids in (("quote", book_ticker(q)), ("proxy", mk.proxy_mids(pr))):
                    frames.append(_rows(mk.measures(pr, mids), set="V1", source="archive", mid=name,
                                        venue="binance", coin=coin, day=day))
        elif kind == "V2":
            f, q = tardis("binance-futures", "trades", coin, day), tardis("binance-futures", "quotes", coin, day)
            raws = [x for x in (f, q) if x]
            pr = _prints(tardis_trades(f)) if f and q else None
            if pr is not None:
                for name, mids in (("quote", tardis_quotes(q)), ("proxy", mk.proxy_mids(pr))):
                    frames.append(_rows(mk.measures(pr, mids), set="V2", source="tardis", mid=name,
                                        venue="binance", coin=coin, day=day))
        elif kind == "H":
            f, q = tardis("hyperliquid", "trades", coin, day), tardis("hyperliquid", "quotes", coin, day)
            raws = [x for x in (f, q) if x]
            pr = _prints(tardis_trades(f)) if f and q else None
            if pr is not None:
                frames.append(_rows(mk.measures(pr, tardis_quotes(q)), set="H", source="tardis", mid="quote",
                                    venue="hyperliquid", coin=coin, day=day))
        out.parent.mkdir(parents=True, exist_ok=True)
        if not frames:
            out.with_suffix(".none").write_text("missing or under the print floor")
            return {"job": kind, "coin": coin, "day": day, "status": "dropped"}
        pd.concat(frames, ignore_index=True).to_csv(out, index=False, float_format="%.6g")
        return {"job": kind, "coin": coin, "day": day, "status": "ok"}
    finally:
        for r in raws:
            if r is not None and r.exists():
                r.unlink()


def fetch() -> None:
    (DAYS_DIR / "settle").mkdir(parents=True, exist_ok=True)
    lh = liq_hours()
    jobs = ([("V1", c, d) for d in V1_DAYS for c in COINS] + [("V2", c, d) for d in V2_DAYS for c in COINS]
            + [("H", c, d) for d in H_DAYS for c in COINS] + [("B", c, d) for d in B_DAYS for c in COINS])
    done = []
    with ProcessPoolExecutor(WORKERS) as ex:
        futs = {ex.submit(job, k, c, d, lh.get(c) if k == "B" else None): (k, c, d) for k, c, d in jobs}
        for n, f in enumerate(as_completed(futs), 1):
            k, c, d = futs[f]
            try:
                r = f.result()
            except Exception as exc:          # a job that fails is listed, never silently skipped
                r = {"job": k, "coin": c, "day": d, "status": f"error: {exc!r}"}
            done.append(r)
            if r["status"] != "cached":
                print(f"[{n}/{len(jobs)}] {k} {c} {d}: {r['status']}", flush=True)
    collect(done)


def collect(statuses: Optional[List[dict]] = None) -> None:
    parts = [pd.read_csv(p) for p in sorted(DAYS_DIR.glob("*/*.csv")) if p.parent.name != "settle"]
    pd.concat(parts, ignore_index=True).to_csv(OUT_DAYS, index=False, float_format="%.6g", compression="gzip")
    st = [pd.read_csv(p) for p in sorted((DAYS_DIR / "settle").glob("*.csv"))]
    if st:
        pd.concat(st, ignore_index=True).to_csv(OUT_SETTLE, index=False, float_format="%.8g", compression="gzip")
    dropped = sorted(p.parent.name + " " + p.stem for p in DAYS_DIR.glob("*/*.none"))
    meta = {"dropped": dropped}
    if statuses is not None:
        meta["errors"] = [s for s in statuses if s["status"].startswith("error")]
    MANIFEST.write_text(json.dumps(meta, indent=1))


# ---------------------------------------------------------------- report

def stats(days: pd.DataFrame, half: Optional[str]) -> pd.DataFrame:
    return mk.day_stats(days, ["venue", "coin", "measure", "horizon", "cond", "level"], halves=half)


def _all(s: pd.DataFrame) -> pd.DataFrame:
    return s[s["cond"] == "all"]


def validation(days: pd.DataFrame):
    """Which (coin, horizon) the proxy is validated for, and the comparison tables."""
    keys = ["venue", "coin", "measure", "horizon", "cond", "level"]
    tables, ok = {}, {}
    for name in ("V1", "V2"):
        d = days[days["set"] == name]
        a = _all(stats(d[d["mid"] == "proxy"], None))
        b = _all(stats(d[d["mid"] == "quote"], None))
        m = mk.agree(a, b, keys)
        tables[name] = m
        ok[name] = {(r.coin, r.measure, r.horizon): r.ok for r in m.itertuples()}
    validated = set()
    for c in COINS:
        taker = all(ok[v].get((c, "taker", 0), False) for v in ok)
        for h in mk.HORIZONS_S:
            cells = [ok[v].get((c, m, h), False) for v in ok for m in ("maker_opt", "maker_cons")]
            if taker and all(cells):
                validated.add((c, h))
    return validated, tables


def replication(days: pd.DataFrame):
    keys = ["venue", "coin", "measure", "horizon", "cond", "level"]
    b = days[(days["set"] == "B") & days["day"].isin(V2_DAYS)]
    t = days[(days["set"] == "V2") & (days["mid"] == "proxy")]
    m = mk.agree(_all(stats(t, None)), _all(stats(b, None)), keys)
    return bool(len(m)) and bool(m["ok"].all()), m


def fmt(x, nd=2):
    return "—" if x is None or not np.isfinite(x) else f"{x:+.{nd}f}"


def show(df: pd.DataFrame, cols: List[str]) -> str:
    return df[cols].to_string(index=False, float_format=lambda v: f"{v:.2f}")


def write_table(main: pd.DataFrame, validated: set, replicated: bool) -> int:
    keep = main["cond"].isin(["all", *mk.CONDITIONS]) & main["measure"].isin(["taker", "maker_cons"])
    rows = main[keep]
    on_b = rows["venue"] == "binance"
    taker_ok = {c for c in COINS if any((c, h) in validated for h in mk.HORIZONS_S)}
    good = ~on_b | (replicated & np.array([
        (c in taker_ok) if m == "taker" else ((c, h) in validated)
        for c, m, h in zip(rows["coin"], rows["measure"], rows["horizon"])], dtype=bool))
    rows = rows[good & rows["mean"].notna()]
    lines = ['"""Generated by research/markout.py from #39\'s run (research/RESULTS_MARKOUT.md).',
             "Do not edit by hand. Keys: (venue, coin, measure, horizon_s, condition, level) -> mean bps;",
             'measure "taker" is the effective half-spread, "maker_cons" the back-of-queue markout."""',
             'SOURCE = "#39, research/PREREGISTRATION_MARKOUT.md"', "TABLE = {"]
    for r in rows.itertuples():
        lines.append(f"    ({r.venue!r}, {r.coin!r}, {r.measure!r}, {int(r.horizon)}, {r.cond!r}, {r.level!r}): "
                     f"{r.mean:.4f},")
    lines.append("}")
    TABLE_PY.write_text("\n".join(lines) + "\n")
    return len(rows)


def lead_stats(df: pd.DataFrame, col: str) -> dict:
    g = df.groupby("day")[col].mean()
    n = len(g)
    sd = g.std(ddof=1) if n > 1 else np.nan
    return {"days": n, "mean": g.mean() * 1e4, "t": g.mean() / (sd / np.sqrt(n)) if n > 1 and sd > 0 else np.nan}


def taker_leg(main: pd.DataFrame, venue: str, coin: str, cond=("all", "all")) -> float:
    r = main[(main.venue == venue) & (main.coin == coin) & (main.measure == "taker") &
             (main.cond == cond[0]) & (main.level == cond[1])]
    return (mk.FEES_BPS[venue]["taker"] + float(r["mean"].iloc[0])) / 1e4 if len(r) else np.nan


def leads(main: pd.DataFrame) -> List[str]:
    out = []

    def line(name, venue, s_gross, s_net):
        survive = s_net["mean"] > 0 and s_net["t"] >= 2
        bar = s_net["mean"] > 0 and s_net["t"] >= mk.BAR
        out.append(f"  {name:<34} {venue:<12} days {s_gross['days']:>4}  gross {fmt(s_gross['mean'], 1):>7} bps "
                   f"(t {fmt(s_gross['t'])})  net {fmt(s_net['mean'], 1):>7} bps (t {fmt(s_net['t'])})  "
                   f"survives: {'YES' if survive else 'no'}  clears {mk.BAR:.2f}: {'yes' if bar else 'no'}")

    venues = ["binance", "hyperliquid"]
    # #29: fade the session's move at 16:00 ET, BTC and ETH, two taker legs
    lv = pd.read_csv(ROOT / "research" / "levetf_days.csv.gz")
    lv = lv[(lv["kind"] == "trading") & (lv["era"] == "with") & lv["coin"].isin(["BTC", "ETH"])].copy()
    lv["day"] = lv["date"]
    for col, label in (("post15", "#29 fade, 16:00 → 16:15 ET"), ("post60", "#29 fade, 16:00 → 17:00 ET")):
        d = lv.dropna(subset=[col]).copy()
        d["gross"] = -d[col]
        for v in venues:
            rt = d["coin"].map(lambda c: 2 * taker_leg(main, v, c))
            d["net"] = d["gross"] - rt
            line(label, v, lead_stats(d, "gross"), lead_stats(d.dropna(subset=["net"]), "net"))

    # #31: maker bid 2 ATR under #20's breakdowns, 4-hour exit, on the four coins (#30's bars)
    import bids as rb  # research/bids.py, #30's loader
    evs = []
    for c in COINS:
        sym = lq.symbol("binance-futures", c)
        frames = []
        for m in rb.MONTHS:
            data = rb.blob([rb.LOWS / sym / f"{m}.zip", rb.LEVETF / sym / f"{m}.zip"], rb.CACHE / sym / f"{m}.zip",
                           rb.URL_MONTH.format(sym=sym, month=m))
            if data:
                frames.append(rb.frame(data))
        for day in rb.DAYS:
            data = rb.blob([rb.LEVETF / sym / "daily" / f"{day}.zip"], rb.CACHE / sym / "daily" / f"{day}.zip",
                           rb.URL_DAY.format(sym=sym, day=day))
            if data:
                frames.append(rb.frame(data))
        b = lw.bars(pd.concat(frames, ignore_index=True))
        skip = lw.excluded_days("2026-03-01", "2026-11-01")
        evs.append(bd.events(b, skip, k=2.0, hold=48, taker_bars=48).assign(coin=c))
    ev = pd.concat(evs, ignore_index=True)
    fills = ev[ev["complete"].astype(bool) & ev["filled"].astype(bool)].copy()
    for v in venues:
        mf = mk.FEES_BPS[v]["maker"] / 1e4
        cost = np.where(fills["exit"] == "target", 2 * mf,
                        mf + fills["coin"].map(lambda c: taker_leg(main, v, c)).to_numpy(float))
        fills["net"] = fills["gross"] - cost
        line("#31 2-ATR bid, 4h exit (4 coins)", v, lead_stats(fills, "gross"), lead_stats(fills, "net"))

    # #38: short when shorts paid >= 0.05% at the settlement, cover 30 minutes later
    fc = pd.read_csv(ROOT / "research" / "fillcost_events.csv.gz")
    fc = fc[(fc["bucket"] == "shorts pay") & fc["coin"].isin(COINS)].dropna(subset=["m30"]).copy()
    fc["gross"] = -fc["m30"]
    st = pd.read_csv(OUT_SETTLE) if OUT_SETTLE.exists() else pd.DataFrame()
    every = pd.DataFrame()
    if len(st):
        rates = []
        for c in COINS:
            sym = lq.symbol("binance-futures", c)
            for m in LIQ_MONTHS:
                path = fundsplit.DATA / sym / f"{m}.zip"
                if not path.exists():
                    blob = fundsplit._get(fundsplit.URL.format(sym=sym, month=m))
                    if blob is None:
                        continue
                    path.parent.mkdir(parents=True, exist_ok=True)
                    path.write_bytes(blob)
                rates.append(fundsplit.parse(path.read_bytes()).assign(coin=c))
        r = pd.concat(rates, ignore_index=True)
        r["ts"] = r["ts"] // 60 * 60
        every = st.merge(r.rename(columns={"rate": "rate8"}), on=["coin", "ts"], how="inner")
        every = every[every["rate8"] <= -0.0005].copy()
        every["gross"] = -(every["p30"] / every["p0"] - 1)
        every["day"] = pd.to_datetime(every["ts"], unit="s").dt.strftime("%Y-%m-%d")
    for label, d in (("#38 short, Mondays 00:00 2020–26", fc), ("#38 short, every settlement, set B", every)):
        if not len(d):
            out.append(f"  {label:<34} no events")
            continue
        for v in venues:
            rt = d["coin"].map(lambda c: taker_leg(main, v, c, ("funding", "settlement"))
                               + taker_leg(main, v, c, ("funding", "other")))
            d = d.assign(net=d["gross"] - rt)
            line(label, v, lead_stats(d, "gross"), lead_stats(d.dropna(subset=["net"]), "net"))
    return out


def report() -> None:
    days = pd.read_csv(OUT_DAYS)
    print(f"#39 — measured costs and markouts. {len(days):,} day rows; bar t >= {mk.BAR:.2f} "
          f"(computed {mk.bar(mk.PRIOR_TESTS + mk.CELLS):.3f}, N = {mk.PRIOR_TESTS + mk.CELLS})")
    if MANIFEST.exists():
        meta = json.loads(MANIFEST.read_text())
        print(f"dropped coin-days: {len(meta.get('dropped', []))}; job errors: {len(meta.get('errors', []))}")
        for e in meta.get("errors", [])[:20]:
            print("  error:", e)
    print("days per set:", days.groupby(["set", "coin"])["day"].nunique().unstack().to_string())

    print("\n== Proxy validation (|proxy − quote| <= max(0.25 bps, 20%), every 'all' cell, V1 and V2)")
    validated, vt = validation(days)
    for name, m in vt.items():
        print(f"-- {name}")
        print(show(m.rename(columns={"mean": "proxy", "mean_ref": "quote"}),
                   ["coin", "measure", "horizon", "proxy", "quote", "ok"]))
    print("validated (coin, horizon):", sorted(validated))

    print("\n== Second source: Tardis trades vs the archive's aggTrades, V2 days, proxy mid")
    replicated, rt = replication(days)
    print(show(rt.rename(columns={"mean": "tardis", "mean_ref": "archive"}),
               ["coin", "measure", "horizon", "tardis", "archive", "ok"]))
    print("replicated:", replicated)
    print("Hyperliquid cross-check: the collector's 1-minute candles start 2026-10-27; "
          "no Tardis free day overlaps them, so the Hyperliquid table stands on one source.")

    b = days[days["set"] == "B"]
    h = days[days["set"] == "H"]
    main = pd.concat([stats(b, B_HALF), stats(h, H_HALF)], ignore_index=True)
    main.to_csv(ROOT / "research" / "markout_stats.csv.gz", index=False, float_format="%.6g", compression="gzip")

    print("\n== Q1 — measured cost per leg (bps), 'all' cells")
    for v in ("binance", "hyperliquid"):
        fee = mk.FEES_BPS[v]
        print(f"-- {v}: taker fee {fee['taker']}, maker fee {fee['maker']}")
        for c in COINS:
            r = main[(main.venue == v) & (main.coin == c) & (main.cond == "all")]
            tk = r[r.measure == "taker"]
            if not len(tk):
                print(f"   {c}: no data")
                continue
            hs = float(tk["mean"].iloc[0])
            tag = "" if v != "binance" or any((c, hh) in validated for hh in mk.HORIZONS_S) else "  [proxy not validated]"
            cons = {int(x.horizon): (x.mean, x.t) for x in r[r.measure == "maker_cons"].itertuples()}
            opt = {int(x.horizon): (x.mean, x.t) for x in r[r.measure == "maker_opt"].itertuples()}
            print(f"   {c}: half-spread {hs:+.2f} (days {int(tk['days'].iloc[0])}), taker round trip "
                  f"{2 * (fee['taker'] + hs):.2f} vs the assumed 18.00{tag}")
            for hh in mk.HORIZONS_S:
                o, k = opt.get(hh, (np.nan, np.nan)), cons.get(hh, (np.nan, np.nan))
                print(f"      {hh:>3}s  maker markout optimistic {fmt(o[0])} (t {fmt(o[1])})   "
                      f"conservative {fmt(k[0])} (t {fmt(k[1])})")

    print("\n== Q1 by condition (taker half-spread; conservative maker markout at 60 s)")
    pre = main[main["cond"].isin(list(mk.CONDITIONS))]
    for v in ("binance", "hyperliquid"):
        for meas, hh in (("taker", 0), ("maker_cons", 60)):
            r = pre[(pre.venue == v) & (pre.measure == meas) & (pre.horizon == hh)]
            if len(r):
                p = r.pivot_table(index=["cond", "level"], columns="coin", values="mean")
                print(f"-- {v} {meas} {hh}s\n{p.round(2).to_string()}")

    print(f"\n== Q3 — conservative maker markout net of the maker fee, t >= {mk.BAR:.2f}, both halves")
    q = mk.q3(main, validated=validated, replicated=replicated)
    top = q.sort_values("t_net", ascending=False).head(15)
    print(show(top, ["venue", "coin", "horizon", "cond", "level", "days", "net", "t_net", "net_h1", "net_h2", "pass"]))
    print(f"cells examined: {len(q)}; passing: {int(q['pass'].sum())}")
    opt = main[(main.measure == "maker_opt") & main["cond"].isin(["all", *mk.CONDITIONS])].copy()
    opt["net"] = opt["mean"] - opt["venue"].map(lambda v: mk.FEES_BPS[v]["maker"])
    opt["t_net"] = opt["t"] * opt["net"] / opt["mean"]
    print(f"optimistic-bound cells with net > 0 and t >= bar (the front of the queue; do not count): "
          f"{int(((opt['net'] > 0) & (opt['t_net'] >= mk.BAR)).sum())}")
    print("Q3 ANSWER:", "YES" if q["pass"].any() else "NO")

    print("\n== Q2 — open leads re-priced with the measured taker legs (information; forward tests unchanged)")
    for ln in leads(main):
        print(ln)
    print("  #34 and #37: out of this model's reach (see the pre-registration's Scope).")

    print("\n== Information: conservative maker markout at 60 s by UTC hour (all coins' mean)")
    hr = main[(main.cond == "hour") & (main.measure == "maker_cons") & (main.horizon == 60)]
    print(hr.pivot_table(index="level", columns="venue", values="mean").round(2).T.to_string())
    print("\n== Information: by print size (taker half-spread; optimistic maker 60 s)")
    sz = main[(main.cond == "size") & (((main.measure == "taker") & (main.horizon == 0))
                                       | ((main.measure == "maker_opt") & (main.horizon == 60)))]
    print(sz.pivot_table(index=["venue", "measure", "level"], columns="coin", values="mean").round(2).to_string())
    print("\n== Information: 2023–24 (V1, real quotes) next to 2026 (B, proxy), 'all' cells")
    v1 = _all(stats(days[(days["set"] == "V1") & (days["mid"] == "quote")], None))
    bb = _all(main[main.venue == "binance"])
    cmp_ = v1.merge(bb, on=["venue", "coin", "measure", "horizon"], suffixes=("_2023", "_2026"))
    print(show(cmp_, ["coin", "measure", "horizon", "mean_2023", "mean_2026"]))

    n = write_table(main, validated, replicated)
    print(f"\nwrote {TABLE_PY.relative_to(ROOT)}: {n} measured cells")


if __name__ == "__main__":
    {"fetch": fetch, "report": report, "collect": collect}[sys.argv[1] if len(sys.argv) > 1 else "report"]()
