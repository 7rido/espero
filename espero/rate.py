"""How a coin or stock is moving, and which way its history leans, as a rating from 1 to 10 (#50).

1 is strongly down, 10 strongly up. The number is a ridge logistic's chance of a higher close, on
price features only, with the rule fixed in research/RATING.md. It moves with the lean even when
the lean has no track record, and then says UNPROVEN: this repo has found little predictive power,
so a high rating may rest on nothing. Funding, liquidations and the book are current readings. No
history here can test them, so they never move the number.

It reads public data and places nothing. It reads no forward folder, ledger, book database or
health.json. Each rating is recorded in data/rate/ratings.csv so that it can be scored later.
"""
from __future__ import annotations

import logging
import math
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Dict, Iterable, List, Optional, Sequence, Tuple

import numpy as np
import pandas as pd

from . import aggr, board, data, indicators, trend, venues
from . import costs as cost_table
from . import hyperliquid as hl
from .detector import block_indices
from .factor_eval import purged_walk_forward

log = logging.getLogger("espero.rate")

DATA = Path(__file__).resolve().parents[1] / "data" / "rate"
LEDGER = "ratings.csv"
AGGR_CACHE = "aggr_24h.csv"
AGGR_MAX_AGE_S = 3600
HORIZONS = (1, 7, 30)
DEFAULT_HORIZON = 7
CRYPTO_DAYS = "2300d"          # Hyperliquid serves daily bars from August 2020
STOCK_SPAN = "10y"
PERIODS = {"crypto": 365, "etf": 252}
RETURN_DAYS = (7, 28, 91, 364)
SMA_DAYS = (20, 50, 200)
VOL_ROWS = 60
RIDGE = 0.01                   # penalty per training row
CLIP = 5.0
SPLITS = 6
EMBARGO = 5
MIN_TRAIN = 365
DRAWS = 2000
SEED = 50
FROZEN_FROM = pd.Timestamp("2026-10-30")       # the forward window's first day
FROZEN_UNTIL = pd.Timestamp("2027-03-31")
FEATURES = tuple(f"r{d}" for d in RETURN_DAYS) + tuple(f"sma{d}" for d in SMA_DAYS) + ("rsi", "vol", "drawdown")
LEDGER_COLS = ["asof", "symbol", "kind", "horizon", "rating", "p_up", "usual", "proven", "close", "run_ts"]
FEW_SCORED = 30
WORKERS = 2                    # Hyperliquid answers 6 at once with 429s, and lost coins would change the model

Get = Callable[[str], pd.DataFrame]


class RatingError(ValueError):
    """A symbol that can't be rated, with the reason to show."""


# ---------------------------------------------------------------- symbols and prices
def _known_crypto() -> set:
    return set(trend.MAJORS) | set(trend.ALT_COINS) | {f"{c}-USD" for c in aggr.COINS}


def _known_stocks() -> set:
    return {m for k, ms in trend.CLASSES.items() if k != "crypto" for m in ms}


def resolve(symbol: str, kind: Optional[str] = None) -> Tuple[str, str]:
    """(symbol as the data expects it, 'crypto' or 'etf'). A name this repo doesn't know needs `kind`."""
    s = symbol.strip().upper()
    if not s:
        raise RatingError("an empty symbol")
    base = s[:-4] if s.endswith("-USD") else s
    if kind == "crypto" or (kind is None and s.endswith("-USD")):
        return f"{base}-USD", "crypto"
    if kind == "etf":
        return s, "etf"
    if f"{base}-USD" in _known_crypto():
        return f"{base}-USD", "crypto"
    if s in _known_stocks():
        return s, "etf"
    raise RatingError(f"{symbol}: not a symbol this repo knows; add --crypto or --stock to say which it is")


def pool(kind: str) -> List[str]:
    """The symbols one model is fitted on."""
    if kind == "crypto":
        return list(trend.MAJORS + trend.ALT_COINS)
    return [m for k, ms in trend.CLASSES.items() if k != "crypto" for m in ms]


def load_frames(symbols: Sequence[str], kinds: Dict[str, str], get: Optional[Get] = None,
                now: Optional[pd.Timestamp] = None) -> Tuple[Dict[str, pd.Series], Dict[str, str]]:
    """Closed daily closes, adjusted for dividends. Yahoo's cache goes to a folder that is thrown away."""
    now = pd.Timestamp.now(tz="UTC").tz_localize(None) if now is None else now
    with tempfile.TemporaryDirectory() as tmp:
        def default(sym: str) -> pd.DataFrame:
            if kinds[sym] == "crypto":
                return hl.daily(sym, CRYPTO_DAYS)
            return data.yahoo_daily(sym, STOCK_SPAN, cache_dir=Path(tmp), max_cache_age_days=0, adjusted=True)
        frames, errors = board.fetch_frames(list(symbols), fetch=get or default, workers=WORKERS)
        if errors:                                 # a coin lost to a rate limit must not change the model
            more, errors = board.fetch_frames(list(errors), fetch=get or default, workers=1)
            frames.update(more)
    out: Dict[str, pd.Series] = {}
    for sym, df in frames.items():
        px = trend.complete(df, now)["adj_close"]
        px = px[px > 0]
        if px.empty:
            errors[sym] = "no closed bars"
        else:
            out[sym] = px
    return out, errors


# ------------------------------------------------------------------------- features
def features(px: pd.Series, kind: str) -> pd.DataFrame:
    """One row per close, using that close and earlier ones only."""
    daily = px.asfreq("D").ffill()                 # calendar days; ETFs carry over weekends
    periods = PERIODS[kind]
    logpx = np.log(px)
    sigma = logpx.diff().rolling(VOL_ROWS, min_periods=VOL_ROWS).std() * math.sqrt(periods)
    out = pd.DataFrame(index=px.index)
    for d in RETURN_DAYS:
        out[f"r{d}"] = np.log(daily / daily.shift(d)).reindex(px.index) / (sigma * math.sqrt(d / 365))
    for d in SMA_DAYS:
        sma = px.rolling(d, min_periods=d).mean()
        out[f"sma{d}"] = np.log(px / sma) / (sigma * math.sqrt(d / periods))
    out["rsi"] = indicators.rsi(px).where(logpx.diff().expanding().count() >= 14)
    out["vol"] = np.log(sigma)
    high = daily.rolling(364, min_periods=364).max().reindex(px.index)
    out["drawdown"] = px / high - 1
    return out.replace([np.inf, -np.inf], np.nan)[list(FEATURES)]


def _later(px: pd.Series, h: int) -> pd.Series:
    """The first close on or after `h` calendar days later. A Friday's next day is Monday's close, not its own."""
    return px.asfreq("D").bfill().shift(-h).reindex(px.index)


def outcome(px: pd.Series, h: int) -> pd.Series:
    """1 if that later close is higher, 0 if not, NaN where it isn't known yet."""
    future = _later(px, h)
    return (future > px).astype(float).where(future.notna())


def readable_until(now: pd.Timestamp) -> pd.Timestamp:
    """Outcomes must be dated before this: the forward window stays unread until its verdicts."""
    return min(FROZEN_FROM, now) if now <= FROZEN_UNTIL else now


def rows(px: pd.Series, kind: str, h: int, now: pd.Timestamp) -> pd.DataFrame:
    """Feature rows with a known outcome dated before the frozen window."""
    x = features(px, kind)
    x["y"] = outcome(px, h)
    x = x[x.index + pd.Timedelta(days=h) < readable_until(now)]
    return x.dropna()


# ---------------------------------------------------------------------------- model
@dataclass(frozen=True)
class Fit:
    beta: np.ndarray
    mean: np.ndarray
    std: np.ndarray


def fit(x: np.ndarray, y: np.ndarray, ridge: float = RIDGE, iterations: int = 25) -> Fit:
    """Ridge logistic by Newton's method. The intercept isn't penalised."""
    mean, std = x.mean(axis=0), x.std(axis=0)
    std = np.where(std > 0, std, 1.0)
    z = np.column_stack([np.ones(len(x)), np.clip((x - mean) / std, -CLIP, CLIP)])
    penalty = np.eye(z.shape[1]) * ridge * len(x)
    penalty[0, 0] = 0.0
    beta = np.zeros(z.shape[1])
    for _ in range(iterations):
        p = np.clip(1 / (1 + np.exp(-z @ beta)), 1e-6, 1 - 1e-6)
        hessian = (z * (p * (1 - p))[:, None]).T @ z + penalty
        step = np.linalg.solve(hessian, z.T @ (y - p) - penalty @ beta)
        beta = beta + step
        if np.abs(step).max() < 1e-8:
            break
    return Fit(beta, mean, std)


def predict(model: Fit, x: np.ndarray) -> np.ndarray:
    z = np.column_stack([np.ones(len(x)), np.clip((x - model.mean) / model.std, -CLIP, CLIP)])
    return 1 / (1 + np.exp(-z @ model.beta))


def skill(panel: pd.DataFrame, h: int, draws: int = DRAWS, seed: int = SEED) -> dict:
    """Out-of-sample Brier skill against each fold's training base rate, with a block-bootstrap CI over dates."""
    dates = pd.DatetimeIndex(sorted(panel.index.unique()))
    errs = []
    for train, test in purged_walk_forward(dates, n_splits=SPLITS, horizon=h, embargo=EMBARGO, min_train=MIN_TRAIN):
        a = panel[panel.index.isin(train)]
        b = panel[panel.index.isin(test)]
        if a.empty or b.empty:
            continue
        model = fit(a[list(FEATURES)].to_numpy(), a["y"].to_numpy())
        p = predict(model, b[list(FEATURES)].to_numpy())
        y = b["y"].to_numpy()
        errs.append(pd.DataFrame({"model": (p - y) ** 2, "base": (a["y"].mean() - y) ** 2}, index=b.index))
    if not errs:
        raise RatingError("too little history to test the model")
    by_day = pd.concat(errs).groupby(level=0).sum().sort_index()
    m, b = by_day["model"].to_numpy(), by_day["base"].to_numpy()
    idx = block_indices(np.random.default_rng(seed), len(m), h, draws)
    boots = 1 - m[idx].sum(axis=1) / b[idx].sum(axis=1)
    lo, hi = np.quantile(boots, [0.025, 0.975])
    return {"skill": float(1 - m.sum() / b.sum()), "lo": float(lo), "hi": float(hi), "days": len(m)}


def rating(p_up: float) -> int:
    """Under 30% is 1, one point per 5% after that, 70% and over is 10."""
    return int(min(10, max(1, math.floor(round((p_up - 0.25) / 0.05, 9)) + 1)))


def lean(score: int) -> str:
    return {5: "barely down", 6: "barely up"}.get(score, "leans up" if score > 6 else "leans down")


def proven(s: dict) -> bool:
    return s["lo"] > 0


# ---------------------------------------------------------------- what history shows
def _state(name: str, value: float) -> str:
    if name.startswith("sma"):
        return f"above {name[3:]}-day SMA" if value > 0 else f"below {name[3:]}-day SMA"
    if name.startswith("r"):
        return f"{name[1:]}-day trend up" if value > 0 else f"{name[1:]}-day trend down"
    raise ValueError(name)


def _rsi_band(s: pd.Series) -> pd.Series:
    return pd.cut(s, [-1, 30, 50, 70, 101], labels=["under 30", "30-50", "50-70", "over 70"], right=False).astype(str)


def _drawdown_band(s: pd.Series) -> pd.Series:
    return pd.cut(s, [-1.01, -0.3, -0.1, 0.01], labels=["over 30% below", "10-30% below", "within 10%"],
                  right=False).astype(str)


def same_state(px: pd.Series, kind: str, h: int, now: pd.Timestamp) -> List[dict]:
    """On this symbol's own past days in today's state, how often it closed higher `h` days later."""
    x = features(px, kind)
    today = x.iloc[-1]
    past = rows(px, kind, h, now)
    states = []
    for name in ("sma200", "sma50", "sma20", "r28", "r91", "r364"):
        same = np.sign(past[name]) == np.sign(today[name])
        states.append((_state(name, today[name]), f"{today[name]:+.1f} sd", same))
    states.append((f"RSI 14 {_rsi_band(x['rsi']).iloc[-1]}", f"{today['rsi']:.0f}",
                   _rsi_band(past["rsi"]) == _rsi_band(x["rsi"]).iloc[-1]))
    states.append((f"high: {_drawdown_band(x['drawdown']).iloc[-1]}", f"{today['drawdown']:+.0%}",
                   _drawdown_band(past["drawdown"]) == _drawdown_band(x["drawdown"]).iloc[-1]))
    rng = np.random.default_rng(SEED)
    out = []
    for label, now_text, mask in states:
        y = past["y"][mask].to_numpy()
        if len(y) < 2:
            out.append({"label": label, "now": now_text, "days": len(y), "up": None, "lo": None, "hi": None})
            continue
        boots = y[block_indices(rng, len(y), h, 1000)].mean(axis=1)
        out.append({"label": label, "now": now_text, "days": len(y), "up": float(y.mean()),
                    "lo": float(np.quantile(boots, 0.025)), "hi": float(np.quantile(boots, 0.975))})
    return out


def typical_move(px: pd.Series, h: int, now: pd.Timestamp) -> float:
    move = (_later(px, h) / px - 1).dropna()
    move = move[move.index + pd.Timedelta(days=h) < readable_until(now)]
    return float(move.abs().median()) if len(move) else float("nan")


def round_trip_bps(symbol: str, kind: str) -> Tuple[float, str]:
    """Measured where #39 measured it, the venue's base fees for other coins, #8's assumption for ETFs."""
    if kind == "etf":
        return 2e4 * trend.COSTS["etf"], "#8's assumed ETF cost"
    coin = symbol[:-4]
    try:
        return cost_table.round_trip("hyperliquid", coin), "measured on Hyperliquid"
    except cost_table.NotMeasured:
        return venues.round_trip_bps("hyperliquid"), "Hyperliquid base fees, spread not measured"


# ----------------------------------------------------------------- current readings
def _funding(coin: str, now: float, post: Callable) -> str:
    df = hl.funding_history(coin, int((now - 7 * 86400) * 1000), fetch=post)
    if df.empty:
        return "unavailable"
    return f"{df['funding'].mean() * 24 * 365:+.1%} a year, 7-day average"


def _book(coin: str, post: Callable) -> str:
    book = post({"type": "l2Book", "coin": coin})
    bids, asks = book["levels"]
    bid, ask = float(bids[0]["px"]), float(asks[0]["px"])
    mid = (bid + ask) / 2
    near = lambda side, keep: sum(float(lv["px"]) * float(lv["sz"]) for lv in side if keep(float(lv["px"])))  # noqa: E731
    b = near(bids, lambda p: p >= mid * 0.99)
    a = near(asks, lambda p: p <= mid * 1.01)
    if b + a <= 0:
        return "unavailable"
    return f"{b / (b + a):.0%} bids, ${b + a:,.0f} within 1% (top 20 levels)"


def _liquidations(coin: str, now: float, folder: Path, fetch_aggr: Callable) -> str:
    base = {v: k for k, v in hl.COIN.items()}.get(coin, coin)
    if base not in aggr.COINS:
        return "not covered"
    path = Path(folder) / AGGR_CACHE
    if path.exists() and now - path.stat().st_mtime < AGGR_MAX_AGE_S:      # one person's free server
        raw = pd.read_csv(path)
    else:
        end = pd.Timestamp(now, unit="s", tz="UTC").floor("h")
        raw = fetch_aggr(end - pd.Timedelta(hours=24), end)
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_name(path.name + ".tmp")
        raw.to_csv(tmp, index=False)
        tmp.replace(path)
    p = aggr.panel(raw).get(base)
    if p is None:
        return "unavailable"
    return f"longs ${p['long'].sum():,.0f}, shorts ${p['short'].sum():,.0f} in the last 24 hours"


def context(symbol: str, kind: str, now: Optional[float] = None, folder: Path = DATA,
            post: Optional[Callable] = None, fetch_aggr: Optional[Callable] = None) -> Dict[str, str]:
    """Current readings. A failed one says so; none of them can touch the rating."""
    if kind != "crypto":
        return {"funding": "not available for stocks", "liquidations": "not available for stocks",
                "book": "not available for stocks"}
    now = time.time() if now is None else now
    post = post or hl.post
    coin = hl.hl_coin(symbol)
    readers = {"funding": lambda: _funding(coin, now, post), "liquidations":
               lambda: _liquidations(coin, now, folder, fetch_aggr or aggr.fetch), "book": lambda: _book(coin, post)}
    out = {}
    for name, read in readers.items():
        try:
            out[name] = read()
        except Exception as exc:  # noqa: BLE001 - a missing reading is a line, not a crash
            log.warning("%s %s: %s", symbol, name, exc)
            out[name] = "unavailable"
    return out


# --------------------------------------------------------------------------- rating
@dataclass(frozen=True)
class ClassModel:
    model: Fit
    skill: dict
    symbols: int
    rows: int


def build_model(prices: Dict[str, pd.Series], kind: str, h: int, now: pd.Timestamp) -> ClassModel:
    parts = [rows(px, kind, h, now) for px in prices.values()]
    parts = [p for p in parts if not p.empty]
    if not parts:
        raise RatingError(f"no {kind} history to fit")
    panel = pd.concat(parts).sort_index()
    try:
        s = skill(panel, h)
    except ValueError as exc:
        raise RatingError(f"too little {kind} history to test the model: {exc}") from exc
    return ClassModel(fit(panel[list(FEATURES)].to_numpy(), panel["y"].to_numpy()), s, len(parts), len(panel))


def rate_symbol(symbol: str, kind: str, px: pd.Series, cm: ClassModel, h: int, now: pd.Timestamp) -> dict:
    x = features(px, kind)
    latest = x.iloc[-1]
    if latest.isna().any():
        raise RatingError(f"{symbol}: needs at least 364 days of closes and {SMA_DAYS[-1]} bars; it has {len(px)}")
    p_up = float(predict(cm.model, latest.to_numpy(dtype=float)[None, :])[0])
    past = rows(px, kind, h, now)
    usual = float(past["y"].mean()) if len(past) else float("nan")
    return {"symbol": symbol, "kind": kind, "horizon": h, "asof": px.index[-1], "close": float(px.iloc[-1]),
            "p_up": p_up, "rating": rating(p_up), "usual": usual, "skill": cm.skill, "proven": proven(cm.skill),
            "move": typical_move(px, h, now), "cost": round_trip_bps(symbol, kind),
            "evidence": same_state(px, kind, h, now)}


def rate(requests: Iterable[Tuple[str, str]], h: int = DEFAULT_HORIZON, get: Optional[Get] = None,
         now: Optional[pd.Timestamp] = None) -> Tuple[List[dict], Dict[str, str]]:
    """Ratings for (symbol, kind) pairs, and the reason for any that couldn't be rated."""
    now = pd.Timestamp.now(tz="UTC").tz_localize(None) if now is None else now
    requests = list(requests)
    results, errors = [], {}
    for kind in ("crypto", "etf"):
        wanted = [s for s, k in requests if k == kind]
        if not wanted:
            continue
        universe = list(dict.fromkeys(pool(kind) + wanted))
        prices, failed = load_frames(universe, {s: kind for s in universe}, get=get, now=now)
        try:
            cm = build_model(prices, kind, h, now)
        except RatingError as exc:
            errors.update({s: str(exc) for s in wanted})
            continue
        for s in wanted:
            if s not in prices:
                errors[s] = f"{s}: no price history ({failed.get(s, 'empty')})"
                continue
            try:
                results.append({**rate_symbol(s, kind, prices[s], cm, h, now), "fitted": cm.symbols,
                                "pool": len(universe)})
            except RatingError as exc:
                errors[s] = str(exc)
    return results, errors


# ------------------------------------------------------------------- the score it keeps
def read_ledger(folder: Path = DATA) -> pd.DataFrame:
    path = Path(folder) / LEDGER
    if not path.exists() or path.stat().st_size == 0:
        return pd.DataFrame(columns=LEDGER_COLS)
    return pd.read_csv(path)


def log_rating(r: dict, folder: Path = DATA, now: Optional[float] = None) -> bool:
    """One row per symbol, signal day and horizon: the first reading stands. True if a row was added."""
    old = read_ledger(folder)
    asof = r["asof"].strftime("%Y-%m-%d")
    if len(old) and ((old["asof"] == asof) & (old["symbol"] == r["symbol"]) & (old["horizon"] == r["horizon"])).any():
        return False
    row = {"asof": asof, "symbol": r["symbol"], "kind": r["kind"], "horizon": r["horizon"], "rating": r["rating"],
           "p_up": round(r["p_up"], 6), "usual": round(r["usual"], 6), "proven": bool(r["proven"]),
           "close": r["close"], "run_ts": int(time.time() if now is None else now)}
    path = Path(folder) / LEDGER
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    new = pd.DataFrame([row], columns=LEDGER_COLS)
    (new if old.empty else pd.concat([old, new], ignore_index=True)).to_csv(tmp, index=False)
    tmp.replace(path)
    return True


def scorecard(folder: Path = DATA, get: Optional[Get] = None, now: Optional[pd.Timestamp] = None) -> dict:
    """Due ratings against what happened. A rating is due once its close `h` days later has printed."""
    now = pd.Timestamp.now(tz="UTC").tz_localize(None) if now is None else now
    book = read_ledger(folder)
    if book.empty:
        return {"recorded": 0, "due": 0, "rows": [], "failed": []}
    book = book.assign(when=pd.to_datetime(book["asof"]))
    due = book[book["when"] + pd.to_timedelta(book["horizon"], unit="D") < now.normalize()]
    if due.empty:
        return {"recorded": len(book), "due": 0, "rows": [], "failed": []}
    kinds = dict(zip(due["symbol"], due["kind"]))
    prices, errors = load_frames(sorted(kinds), kinds, get=get, now=now)
    scored = []
    for r in due.itertuples():
        px = prices.get(r.symbol)
        if px is None or r.when not in px.index:
            continue
        up = outcome(px, int(r.horizon)).get(r.when)
        if up is not None and not math.isnan(up):
            scored.append({"rating": int(r.rating), "up": up, "p_up": r.p_up, "usual": r.usual})
    table = pd.DataFrame(scored, columns=["rating", "up", "p_up", "usual"])
    out = {"recorded": len(book), "due": len(due), "scored": len(table), "failed": sorted(errors), "rows": []}
    if table.empty:
        return out
    for score, g in table.groupby("rating"):
        out["rows"].append({"rating": int(score), "n": len(g), "up": float(g["up"].mean()),
                            "expected": float(g["p_up"].mean())})
    base = ((table["usual"] - table["up"]) ** 2).sum()
    out["skill"] = float(1 - ((table["p_up"] - table["up"]) ** 2).sum() / base) if base > 0 else float("nan")
    return out


# ---------------------------------------------------------------------------- report
def format_price(x: float) -> str:
    return f"{x:,.2f}" if x >= 1 else f"{x:.6g}"


def _pool_note(r: dict) -> List[str]:
    if "fitted" not in r:
        return []
    note = f"Model fitted on {r['fitted']} of {r['pool']} symbols"
    flatter = ", only coins still listed on Hyperliquid, which flatters crypto's history."
    return [note + (flatter if r["kind"] == "crypto" else ".")]


def _against_usual(p_up: float, usual: float) -> str:
    """A 7 can still be below a symbol's usual rate: stocks rise more often than they fall."""
    if math.isnan(usual) or round(p_up, 2) == round(usual, 2):
        return ""
    return ", so below usual" if p_up < usual else ", so above usual"


def format_report(r: dict, ctx: Dict[str, str]) -> str:
    s, name = r["skill"], r["symbol"]
    cost, source = r["cost"]
    lines = [f"{name}  last close {format_price(r['close'])} on {r['asof']:%Y-%m-%d}   {r['horizon']} days ahead",
             f"RATING {r['rating']}/10  {lean(r['rating'])}: {r['p_up']:.0%} chance of a higher close"
             f" (usual rate for {name} {r['usual']:.0%}{_against_usual(r['p_up'], r['usual'])})"]
    span = f"skill {s['skill']:+.2%}, 95% CI {s['lo']:+.2%} to {s['hi']:+.2%}, over {s['days']:,} days"
    if r["proven"]:
        lines.append(f"Beat the usual rate in past tests; not evidence of profit ({span}).")
    else:
        result = "did worse than" if s["hi"] < 0 else "did not reliably beat"
        lines += [f"⚠ UNPROVEN: on past data it was not fitted to, this model {result} the usual rate ({span}).",
                  "  Treat this rating as a description of the chart, not a forecast."]
    lines += [f"A typical {r['horizon']}-day move is ±{r['move']:.1%}; "
              f"a round trip costs about {cost / 100:.2f}% ({source}).",
              *_pool_note(r),
              "", f"{'In the rating: this symbol on past days like today':<52}{'now':>9}{'days':>8}"
                  "  chance up (95% CI)"]
    for e in r["evidence"]:
        chance = "too few" if e["up"] is None else f"{e['up']:.0%} ({e['lo']:.0%}-{e['hi']:.0%})"
        lines.append(f"  {e['label']:<50}{e['now']:>9}{e['days']:>8,}  {chance}")
    lines += ["", "Not in the rating: no history here to test them"]
    lines += [f"  {k:<14}{ctx[k]}" for k in ("funding", "liquidations", "book")]
    lines += ["", "A statistical read of public data, not advice. "
                  "It knows nothing of your position and places nothing."]
    return "\n".join(lines)


def format_scorecard(card: dict) -> str:
    if not card["recorded"]:
        return "No ratings recorded yet."
    if not card["due"]:
        return f"{card['recorded']} ratings recorded, none due yet."
    lines = [f"{card['recorded']} ratings recorded, {card['due']} due, {card.get('scored', 0)} scored."]
    if card.get("failed"):
        lines.append(f"No prices for: {', '.join(card['failed'])}")
    if not card["rows"]:
        return "\n".join(lines)
    lines.append(f"{'rating':>6}{'count':>7}{'closed higher':>15}{'it said':>9}")
    lines += [f"{r['rating']:>6}{r['n']:>7}{r['up']:>15.0%}{r['expected']:>9.0%}" for r in card["rows"]]
    lines.append(f"Brier skill against each symbol's usual rate: {card['skill']:+.2%}")
    if card.get("scored", 0) < FEW_SCORED:
        lines.append(f"Under {FEW_SCORED} scored ratings: too few to read anything into.")
    lines.append("Ratings taken close together on related symbols are not independent, "
                 "so these counts overstate the evidence.")
    return "\n".join(lines)
