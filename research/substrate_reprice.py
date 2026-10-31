"""Reprices the trades #2 and #11 would have made, on Binance USD-M's own prints and quotes.

    python research/substrate_reprice.py legs      # rebuild both books' legs; reproduction checks
    python research/substrate_reprice.py design    # #2's 2021-23 legs, the impact fit, the markouts
    python research/substrate_reprice.py rehearse DIR  # the holdout's path on design legs; writes to DIR
    python research/substrate_reprice.py holdout   # #48: refuses until sealed, then runs exactly once
    python research/substrate_reprice.py carry     # #11's 2024 legs (after #48's read)

Binance USD-M is a proxy venue for both books: #2 ran on Coinbase spot, #11 on Hyperliquid perps and
Coinbase spot. Every number here is what these trades would have cost on Binance, never what they
cost on the venue they were tested on.
"""
from __future__ import annotations

import json
import subprocess
import sys
import warnings
from pathlib import Path
from typing import Dict, List, Optional

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "research"))
from espero import detector, execsim, pit  # noqa: E402

warnings.filterwarnings("ignore", category=FutureWarning)
warnings.filterwarnings("ignore", message=".*dayofweek.*")

OUT = ROOT / "research"
FEE_PERP = 5.0          # espero.markout.FEES_BPS["binance"]["taker"]
FEE_SPOT = 10.0         # Binance spot's base taker rate
PUBLISHED_HOLDOUT = -29.75
PRIMARY_SIZE = 100_000.0
STRESS_SIZE = 1_000_000.0
SEALED = ("research/PREREGISTRATION_EXEC_ANSWER.md", "research/substrate_q48.sql", "research/substrate_reprice.py",
          "research/substrate_fetch.py", "research/substrate_impact_fit.csv", "research/substrate_regime_edges.json",
          "research/substrate_half_spread.json", "research/substrate_xs_legs.csv", "espero/execsim.py",
          "espero/detector.py", "espero/pit.py")
SEED = 48
REG = "research/PREREGISTRATION_EXEC_ANSWER.md"
DESIGN_WINDOW = ("2021-01-04", "2024-01-01")     # Mondays, first to the one after the last week
HOLDOUT_WINDOW = ("2024-01-01", "2026-10-26")
QUEUE_TTL_MS = 300_000


# ---------------------------------------------------------------- the books' legs

def xs_legs() -> pd.DataFrame:
    """#2's switches exactly as momentum.simulate makes them, design and holdout runs apart: the
    published holdout starts flat, so its first week is an entry, not a carry from 2023."""
    import momentum as m

    panel = m.load()
    idx, opens, closes = m.build(panel)
    rows = []
    for window, (start, end) in {"design": m.DESIGN, "holdout": m.HOLDOUT}.items():
        eq, trades = m.simulate(idx, opens, closes, start, end)
        got = m.metrics(eq)
        print(f"{window}: {len(trades)} switches, CAGR {got['cagr']:+.2f}%")
        if window == "holdout" and round(got["cagr"], 2) != PUBLISHED_HOLDOUT:
            raise SystemExit(f"holdout does not reproduce #2's {PUBLISHED_HOLDOUT}%: {got['cagr']:.2f}%")
        held = None
        for day, target, _ in trades:
            if held is not None:
                rows.append((window, day, held, "sell"))
            if target is not None:
                rows.append((window, day, target, "buy"))
            held = target
    return pd.DataFrame(rows, columns=["window", "day", "coin", "side"])


def headline_2021_23() -> Dict[str, float]:
    """The figure #2's report does not break out: its design run, sliced to 2021-23, 10 bps round trip."""
    import momentum as m

    idx, opens, closes = m.build(m.load())
    eq, _ = m.simulate(idx, opens, closes, *m.DESIGN)
    a = eq[(eq.index >= pd.Timestamp("2021-01-01", tz="UTC")) & (eq.index <= pd.Timestamp("2023-12-31", tz="UTC"))]
    years = len(a) / 365.25
    return {"cagr": (a.iloc[-1] / a.iloc[0]) ** (1 / years) - 1, "log_ann": float(np.log(a.iloc[-1] / a.iloc[0]) / years),
            "years": years}


def carry_trades() -> pd.DataFrame:
    import carry as run

    from espero import carry

    m = carry.evaluate(run.load(extended=True), initial=1.0)
    print(f"#11 extended: {m['trades']} trades, final {m['final']:.4f}")
    if m["trades"] != 369 or round(m["final"], 4) != 1.3385:
        raise SystemExit("#11's extended view does not reproduce")
    eq = m["result"].equity.dropna()
    t = pd.DataFrame(m["result"].trades)
    y = eq[eq.index.year == 2024]
    print(f"2024: {y.iloc[-1] / y.iloc[0] - 1:+.4%}")
    return t


# ---------------------------------------------------------------- reading the store

def prints(dataset: str, symbol: str, day: str) -> Optional[Dict[str, np.ndarray]]:
    p = pit.store_path(pit.STORE, dataset, symbol, day)
    if not p.exists():
        return None
    # 2022-09-12's archive files hold every print twice; the id is what makes a print one print
    df = pd.read_parquet(p, columns=["agg_trade_id", "valid_time", "price", "quantity", "is_buyer_maker"])
    df = df.drop_duplicates("agg_trade_id").sort_values("valid_time", kind="stable")
    return {"t": df["valid_time"].to_numpy(), "p": df["price"].to_numpy(float), "q": df["quantity"].to_numpy(float),
            "bm": df["is_buyer_maker"].to_numpy(bool)}


def quotes(symbol: str, day: str) -> Optional[pd.DataFrame]:
    p = pit.store_path(pit.STORE, "bookTicker", symbol, day)
    return pd.read_parquet(p).sort_values("valid_time", kind="stable") if p.exists() else None


def depth_at_1pct(symbol: str, day: str, t0: int, side: int) -> float:
    """The newest +/-1% depth known at t0, in dollars, on the side a taker would take. A file opens at
    00:00, so a decision then reads its first snapshot, if within a minute."""
    p = pit.store_path(pit.STORE, "bookDepth", symbol, day)
    if not p.exists():
        return float("nan")
    d = pd.read_parquet(p, columns=["known_time", "percentage", "notional"])
    d = d[(d["percentage"] == (1 if side > 0 else -1)) & (d["known_time"] <= t0 + 60_000)].sort_values("known_time")
    if d.empty:
        return float("nan")
    before = d[d["known_time"] <= t0]
    return float(before["notional"].iloc[-1] if len(before) else d["notional"].iloc[0])


def daily_bars(coin: str) -> pd.DataFrame:
    frames = [pd.read_parquet(f) for f in sorted((pit.STORE / "klines_1d" / f"{coin}USDT").glob("*.parquet"))]
    return pd.concat(frames).drop_duplicates("valid_time").sort_values("valid_time")


def trailing(coin: str, t0: int, cache: Dict[str, pd.DataFrame], days: int = 30) -> Dict[str, float]:
    """Dollar volume and volatility over the last `days` bars known strictly before t0."""
    bars = cache.setdefault(coin, daily_bars(coin))
    k = bars[bars["known_time"] <= t0].tail(days)
    if len(k) < days:
        return {"adv": float("nan"), "vol": float("nan")}
    return {"adv": float(k["quote_volume"].mean()), "vol": float(np.log(k["close"]).diff().std())}


def day_open(coin: str, t: int, cache: Dict[str, pd.Series]) -> float:
    """The 00:00 open on Binance's daily bar. The monthly hourly files lack days (2022-02-26 to 28 on
    some coins), the daily bars do not; they agree where both exist. A hole raises: it never reads flat."""
    if coin not in cache:
        frames = [pd.read_parquet(f, columns=["valid_time", "open"])
                  for f in sorted((pit.STORE / "klines_1d" / f"{coin}USDT").glob("*.parquet"))]
        cache[coin] = pd.concat(frames).drop_duplicates("valid_time").set_index("valid_time")["open"].sort_index()
    px = float(cache[coin].get(t, np.nan))
    if not np.isfinite(px):
        raise ValueError(f"no open for {coin} at {pd.Timestamp(t, unit='ms')}")
    return px


# ---------------------------------------------------------------- pricing

def price_leg(day: str, coin: str, side: int, t0: int, sizes, cache: Dict) -> List[dict]:
    """One leg at every size. A missing file gives rows with NaN cost: a gap stays a gap."""
    sym = f"{coin}USDT"
    tape = prints("aggTrades", sym, day)
    info = trailing(coin, t0, cache)
    rows = []
    book = quotes(sym, day)
    for size in sizes:
        row = {"day": day, "coin": coin, "side": side, "t0": t0, "size": size, **info, "tape_bps": np.nan,
               "filled": np.nan, "secs_to_finish": np.nan, "depth_bps": np.nan, "queue_bps": np.nan,
               "queue_filled": np.nan, "queue_secs": np.nan, "quote_spread_bps": np.nan}
        if tape is not None:
            f = execsim.tape_fill(tape["t"], tape["p"], tape["q"], tape["bm"], t0, side, size)
            row.update(tape_bps=f.cost_bps, filled=f.filled, secs_to_finish=(f.end_ms - t0) / 1000)
            for h, v in execsim.markouts(tape["t"], tape["p"], tape["bm"], f.end_ms, side, f.price).items():
                row[f"markout_{h}s"] = v
        row["depth_bps"] = execsim.depth_cost(depth_at_1pct(sym, day, t0, side), size)
        if book is not None and tape is not None and t0 >= int(book["valid_time"].iloc[0]):
            px0 = float(book["best_bid_price"].iloc[0])
            q = execsim.queue_fill(book["valid_time"].to_numpy(), book["best_bid_price"].to_numpy(float),
                                   book["best_bid_qty"].to_numpy(float), book["best_ask_price"].to_numpy(float),
                                   book["best_ask_qty"].to_numpy(float), tape["t"], tape["p"], tape["q"], tape["bm"],
                                   t0, side, size / px0, QUEUE_TTL_MS)
            if q is not None:
                row.update(queue_bps=q.cost_bps, queue_filled=float(q.filled), queue_secs=q.ms_to_fill / 1000)
            first = book.iloc[np.searchsorted(book["valid_time"].to_numpy(), t0, side="right") - 1]
            row["quote_spread_bps"] = (first["best_ask_price"] - first["best_bid_price"]) / first["best_bid_price"] * 1e4
        rows.append(row)
    return rows


def price_legs(legs: pd.DataFrame, sizes=execsim.SIZES) -> pd.DataFrame:
    cache: Dict = {}
    rows: List[dict] = []
    for r in legs.itertuples():
        rows += price_leg(r.day, r.coin, 1 if r.side == "buy" else -1, pit.day_ms(r.day), sizes, cache)
    return pd.DataFrame(rows)


def book_weeks(legs: pd.DataFrame, first: str, last: str, start_held: Optional[str] = None) -> pd.DataFrame:
    """One row per Monday: what the book holds from that open to the next."""
    held = start_held
    rows = []
    for d in pd.date_range(first, last, freq="W-MON"):
        day = d.strftime("%Y-%m-%d")
        for r in legs[legs["day"] == day].itertuples():
            held = r.coin if r.side == "buy" else None
        rows.append({"day": day, "held": held})
    return pd.DataFrame(rows)


def weekly_gross(weeks: pd.DataFrame) -> pd.DataFrame:
    """Open-to-open log return of the held coin and of BTC, on Binance's daily bars."""
    cache: Dict = {}
    rows = []
    days = weeks["day"].tolist()
    for a, b, coin in zip(days[:-1], days[1:], weeks["held"].tolist()[:-1]):
        ta, tb = pit.day_ms(a), pit.day_ms(b)
        bench = np.log(day_open("BTC", tb, cache) / day_open("BTC", ta, cache))
        gross = 0.0 if coin is None or (isinstance(coin, float) and np.isnan(coin)) else \
            float(np.log(day_open(coin, tb, cache) / day_open(coin, ta, cache)))
        rows.append({"day": a, "next_day": b, "held": coin, "gross": gross, "bench": float(bench)})
    return pd.DataFrame(rows)


def funding_paid(weeks: pd.DataFrame) -> pd.Series:
    """The funding a long perp pays over each held week, summed from the archive's published rates."""
    frames = {}
    out = []
    for r in weeks.itertuples():
        if r.held is None or (isinstance(r.held, float) and np.isnan(r.held)):
            out.append(0.0)
            continue
        if r.held not in frames:
            files = sorted((pit.STORE / "fundingRate" / f"{r.held}USDT").glob("*.parquet"))
            frames[r.held] = pd.concat([pd.read_parquet(f, columns=["valid_time", "last_funding_rate"]) for f in files])
        f = frames[r.held]
        a, b = pit.day_ms(r.day), pit.day_ms(r.next_day)
        out.append(float(f[(f["valid_time"] >= a) & (f["valid_time"] < b)]["last_funding_rate"].sum()))
    return pd.Series(out, index=weeks.index)


def add_cost(priced: pd.DataFrame, fit: pd.DataFrame, edges: Dict[str, list], spreads: Dict[str, float]) -> pd.DataFrame:
    """Each leg's cost: fee + the coin's frozen half-spread + the frozen impact slope at this size, this
    coin, this volatility regime. One leg's first print is mostly noise around a proxy mid (its mean can go
    negative), so the half-spread is the design sample's median, both sides, never a rebate. NaN stays NaN."""
    p = priced.copy()
    p["half_spread_bps"] = p["coin"].map(spreads)
    p["regime"] = [execsim.regime_of(v, tuple(edges[c])) for c, v in zip(p["coin"], p["vol"])]
    p["impact_bps"] = [execsim.predict_impact(fit, c, r, z, a)
                       for c, r, z, a in zip(p["coin"], p["regime"], p["size"], p["adv"])]
    p["cost_bps"] = FEE_PERP + p["half_spread_bps"] + p["impact_bps"]
    return p


def legs_cost(priced: pd.DataFrame, size: float) -> np.ndarray:
    """The cost per leg as a fraction. A leg that could not be priced stays NaN."""
    return priced[priced["size"] == size]["cost_bps"].to_numpy(float) / 1e4


def waterfall(g: pd.DataFrame, priced: pd.DataFrame, sizes=execsim.SIZES) -> pd.DataFrame:
    """Annualised log growth at each step. `g` is the output of weekly_gross plus funding."""
    years = len(g) / detector.WEEKS_PER_YEAR
    rows = []
    gross = g["gross"].sum() / years
    funding = g["funding"].sum() / years
    for size in sizes:
        c = legs_cost(priced, size)
        drag = float(-np.nansum(np.log1p(-c)) / years)
        replay = priced[priced["size"] == size]["tape_bps"].to_numpy(float)
        replay_drag = float(-np.nansum(np.log1p(-(replay + FEE_PERP) / 1e4)) / years)
        fee = float(-np.log1p(-FEE_PERP / 1e4) * len(c) / years)
        rows.append({"size": size, "gross": gross, "bench": g["bench"].sum() / years, "fee_drag": fee,
                     "slip_drag": drag - fee, "replay_drag": replay_drag, "net": gross - drag, "funding_drag": funding,
                     "net_with_funding": gross - drag - funding, "legs": len(c), "unpriced": int(np.isnan(c).sum()),
                     "unfinished": int((priced[priced["size"] == size]["filled"] < 1).sum()),
                     "cagr_gross": float(np.exp(gross) - 1), "cagr_net": float(np.exp(gross - drag) - 1),
                     "cagr_net_funding": float(np.exp(gross - drag - funding) - 1)})
    return pd.DataFrame(rows)


def by_size(priced: pd.DataFrame) -> pd.DataFrame:
    """Markout curves and cost by size: the mean across legs."""
    cols = ["cost_bps", "half_spread_bps", "impact_bps", "tape_bps", "depth_bps", "queue_bps", "queue_filled", "queue_secs", "quote_spread_bps", "filled",
            "secs_to_finish"] + [c for c in priced.columns if c.startswith("markout_")]
    return priced.groupby("size")[cols].mean(numeric_only=True).reset_index()


# ---------------------------------------------------------------- commands

def cmd_legs() -> None:
    legs = xs_legs()
    legs.to_csv(OUT / "substrate_xs_legs.csv", index=False)
    print(f"2021-23 from #2's design run: {headline_2021_23()}")
    t = carry_trades()
    t.to_csv(OUT / "substrate_carry_trades.csv", index=False)


def fit_impact_sample():
    """Every 4th design Monday, all nine coins: #48's frozen impact fit. Written once, read by the holdout."""
    days = [d.strftime("%Y-%m-%d") for d in pd.date_range("2021-01-01", "2023-12-31", freq="W-MON")][::4]
    coins = ["BTC", "ETH", "SOL", "LINK", "ADA", "XRP", "DOGE", "LTC", "AVAX"]
    cache: Dict = {}
    vols = []
    for c in coins:
        for d in days:
            vols.append({"coin": c, "day": d, **trailing(c, pit.day_ms(d), cache)})
    v = pd.DataFrame(vols)
    edges = {c: list(execsim.regime_edges(g["vol"])) for c, g in v.groupby("coin")}
    frames = []
    for r in v.itertuples():
        tape = prints("aggTrades", f"{r.coin}USDT", r.day)
        if tape is None or not np.isfinite(r.adv):
            continue
        f = execsim.flow_buckets(tape["t"], tape["p"], tape["q"], tape["bm"], r.adv)
        frames.append(f.assign(symbol=r.coin, regime=execsim.regime_of(r.vol, tuple(edges[r.coin])), day=r.day))
    obs = pd.concat(frames, ignore_index=True)
    fit = execsim.fit_impact(obs)
    fit.to_csv(OUT / "substrate_impact_fit.csv", index=False)
    (OUT / "substrate_regime_edges.json").write_text(json.dumps(edges, indent=1))
    costs = []
    for r in v.itertuples():
        tape = prints("aggTrades", f"{r.coin}USDT", r.day)
        if tape is None:
            continue
        for side in (1, -1):
            f = execsim.tape_fill(tape["t"], tape["p"], tape["q"], tape["bm"], pit.day_ms(r.day), side,
                                  min(execsim.SIZES))
            costs.append({"coin": r.coin, "bps": f.cost_bps})
    spreads = {c: max(float(g["bps"].median()), 0.0) for c, g in pd.DataFrame(costs).groupby("coin")}
    (OUT / "substrate_half_spread.json").write_text(json.dumps(spreads, indent=1))
    print(fit.to_string(float_format=lambda x: f"{x:.2f}"))
    print(f"buckets {len(obs)}, median r2 {fit['r2'].median():.3f}; half-spreads {spreads}\n")
    return fit, edges, spreads


def cmd_design() -> None:
    legs = pd.read_csv(OUT / "substrate_xs_legs.csv")
    legs = legs[(legs["window"] == "design") & (legs["day"] >= DESIGN_WINDOW[0]) & (legs["day"] < DESIGN_WINDOW[1])]
    all_design = pd.read_csv(OUT / "substrate_xs_legs.csv")
    all_design = all_design[(all_design["window"] == "design") & (all_design["day"] < DESIGN_WINDOW[0])]
    start = None
    for r in all_design.itertuples():
        start = r.coin if r.side == "buy" else None
    print(f"held into 2021: {start}")
    fit, edges, spreads = fit_impact_sample()
    priced = add_cost(price_legs(legs), fit, edges, spreads)
    priced.to_csv(OUT / "substrate_design_legs.csv.gz", index=False)
    weeks = book_weeks(legs, *DESIGN_WINDOW, start_held=start)
    g = weekly_gross(weeks)
    g["funding"] = funding_paid(g)
    g.to_csv(OUT / "substrate_design_weeks.csv", index=False)
    w = waterfall(g, priced)
    w.to_csv(OUT / "substrate_design_waterfall.csv", index=False)
    head = headline_2021_23()
    print(f"headline 2021-23 on Coinbase, 10 bps round trip: CAGR {head['cagr']:+.2%}")
    print(w.to_string(float_format=lambda x: f"{x:.4f}"))
    print(by_size(priced).T.to_string(float_format=lambda x: f"{x:.2f}"))
    by_size(priced).to_csv(OUT / "substrate_design_markouts.csv", index=False)

    unpriced = priced[(priced["size"] == PRIMARY_SIZE) & priced["cost_bps"].isna()]
    print(f"\nlegs with no cost: {unpriced[['day', 'coin', 'side']].to_dict('records')}")


def sealed() -> None:
    """The holdout may be read only with #48's registration committed and no earlier read on disk."""
    git = subprocess.run(["git", "log", "--oneline", "--", REG], capture_output=True, text=True, cwd=ROOT)
    if not git.stdout.strip():
        raise SystemExit(f"{REG} is not committed: the holdout stays closed")
    dirty = subprocess.run(["git", "status", "--porcelain", "--", *SEALED], capture_output=True, text=True, cwd=ROOT)
    if dirty.stdout.strip():
        raise SystemExit(f"uncommitted changes to sealed files:\n{dirty.stdout}")
    if (OUT / "substrate_q48.json").exists():
        raise SystemExit("the holdout was already read: one read only")


def read_window(legs: pd.DataFrame, first: str, last: str, out: Path, tag: str, start_held: Optional[str] = None) -> dict:
    """The one path from legs to the number, used by the rehearsal and the read alike. Everything is
    written under a temporary name and renamed at the end, so a crash leaves nothing that looks like a read."""
    fit = pd.read_csv(OUT / "substrate_impact_fit.csv")
    edges = json.loads((OUT / "substrate_regime_edges.json").read_text())
    spreads = json.loads((OUT / "substrate_half_spread.json").read_text())
    priced = add_cost(price_legs(legs), fit, edges, spreads)
    weeks = book_weeks(legs, first, last, start_held=start_held)
    g = weekly_gross(weeks)
    g["funding"] = funding_paid(g)
    w = waterfall(g, priced)
    tmp = out / f".tmp_{tag}"
    tmp.mkdir(parents=True, exist_ok=True)
    legs_path, weeks_path = tmp / "legs.csv.gz", tmp / "weeks.csv"
    priced.to_csv(legs_path, index=False)
    g.to_csv(weeks_path, index=False)
    w.to_csv(tmp / "waterfall.csv", index=False)
    by_size(priced).to_csv(tmp / "markouts.csv", index=False)
    years = len(g) / detector.WEEKS_PER_YEAR
    gross, bench = g["gross"].sum() / years, g["bench"].sum() / years
    report: dict = {"primary_size": PRIMARY_SIZE, "stress_size": STRESS_SIZE, "sizes": {}}
    for size in execsim.SIZES:
        c = legs_cost(priced, size)
        unpriced = int(np.isnan(c).sum())
        c = np.where(np.isnan(c), np.nanmean(c), c)
        a = detector.attribution(np.random.default_rng(SEED), gross, bench, c, years)
        report["sizes"][str(int(size))] = {"theta": a.theta, "lo": a.lo, "hi": a.hi, "gross": a.gross, "bench": a.bench,
                                           "drag": a.drag, "shortfall": a.shortfall, "verdict": a.verdict,
                                           "unpriced": unpriced, "legs": len(c)}
    import duckdb

    sql = (ROOT / "research" / "substrate_q48.sql").read_text()
    sql = sql.replace("{legs}", str(legs_path)).replace("{weeks}", str(weeks_path)).replace("{size}", str(int(PRIMARY_SIZE)))
    q = duckdb.connect().execute(sql).df()
    q.to_csv(tmp / "q48_output.csv", index=False)
    report["sql"] = {k: float(v) for k, v in q.iloc[0].items()}
    want = report["sizes"][str(int(PRIMARY_SIZE))]["theta"]
    if not np.isclose(report["sql"]["theta"], want, atol=1e-9):
        raise SystemExit(f"the raw query and the runner disagree: {report['sql']['theta']} against {want}")
    (tmp / "q48.json").write_text(json.dumps(report, indent=1))
    for name in ("legs.csv.gz", "weeks.csv", "waterfall.csv", "markouts.csv", "q48_output.csv"):
        (tmp / name).rename(out / f"substrate_{tag}_{name}")
    (tmp / "q48.json").rename(out / f"substrate_{tag}_q48.json")
    tmp.rmdir()
    print(json.dumps(report, indent=1))
    print(w.to_string(float_format=lambda x: f"{x:.4f}"))
    return report


def cmd_rehearse() -> None:
    """The holdout's exact path on the design window's legs, written elsewhere. Reads no holdout data."""
    out = Path(sys.argv[2])
    out.mkdir(parents=True, exist_ok=True)
    legs = pd.read_csv(OUT / "substrate_xs_legs.csv")
    legs = legs[(legs["window"] == "design") & (legs["day"] >= DESIGN_WINDOW[0]) & (legs["day"] < DESIGN_WINDOW[1])]
    read_window(legs, *DESIGN_WINDOW, out, "rehearsal", start_held="LTC")


def cmd_holdout() -> None:
    sealed()
    legs = pd.read_csv(OUT / "substrate_xs_legs.csv")
    read_window(legs[legs["window"] == "holdout"], *HOLDOUT_WINDOW, OUT, "holdout")
    (OUT / "substrate_holdout_q48.json").rename(OUT / "substrate_q48.json")


def carry_legs(t: pd.DataFrame) -> pd.DataFrame:
    """A row per side per coin in 2024. Notional as a share of equity is backed out of the fees
    #11 charged: fee = notional * (spot fee + slip + perp fee + slip) on each of entry and exit."""
    per_side = 0.0002 + 0.0005 + 0.00045 + 0.0005
    rows = []
    for r in t.itertuples():
        share = r.fees / (2 * per_side)
        for leg, stamp in (("entry", r.entry), ("exit", r.exit)):
            if str(stamp)[:4] == "2024":
                rows.append({"coin": r.coin, "leg": leg, "t": str(stamp), "share": share, "day": str(stamp)[:10]})
    return pd.DataFrame(rows)


def cmd_carry() -> None:
    if not (OUT / "substrate_q48.json").exists():
        raise SystemExit("run after #48's read: 2024 prints overlap the XS holdout")
    t = pd.read_csv(OUT / "substrate_carry_trades.csv")
    legs = carry_legs(t)
    rows = []
    for r in legs.itertuples():
        t0 = int(pd.Timestamp(r.t).timestamp() * 1000)
        perp = prints("aggTrades", f"{r.coin}USDT", r.day)
        spot = prints("spotAggTrades", f"{r.coin}USDT", r.day)
        side_perp = -1 if r.leg == "entry" else 1      # entry shorts the perp and buys spot
        for size in execsim.SIZES:
            row = {"coin": r.coin, "leg": r.leg, "t": r.t, "share": r.share, "size": size, "perp_bps": np.nan,
                   "spot_bps": np.nan, "perp_mid": np.nan, "spot_mid": np.nan, "perp_filled": np.nan,
                   "spot_filled": np.nan}
            if perp is not None:
                f = execsim.tape_fill(perp["t"], perp["p"], perp["q"], perp["bm"], t0, side_perp, size)
                row.update(perp_bps=f.cost_bps, perp_mid=f.mid0, perp_filled=f.filled)
            if spot is not None:
                f = execsim.tape_fill(spot["t"], spot["p"], spot["q"], spot["bm"], t0, -side_perp, size)
                row.update(spot_bps=f.cost_bps, spot_mid=f.mid0, spot_filled=f.filled)
            rows.append(row)
    out = pd.DataFrame(rows)
    out.to_csv(OUT / "substrate_carry_legs.csv.gz", index=False)
    print(out.groupby("size")[["perp_bps", "spot_bps", "perp_filled", "spot_filled"]].mean().to_string())


if __name__ == "__main__":
    {"legs": cmd_legs, "design": cmd_design, "rehearse": cmd_rehearse, "holdout": cmd_holdout,
     "carry": cmd_carry}[sys.argv[1]]()
