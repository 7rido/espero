"""What the tabbed home screen shows (`espero/tui.py`), gathered without drawing anything, in plain words.

Every reader takes its source as an argument, so the screen's tests run on made-up data. Nothing here writes to an
account, a ledger or a journal; the only writes are caches under `data/cache/ui/`.

* Today: what waits for the holder's answer, and one line on whether everything is running
* Market: prices and today's moves sized against each coin's normal day, the biggest movers, who pays funding,
  the last hour's liquidations, and next week's volatility from #66's forecast (information, not a signal)
* Books: the canary's progress and the paper accounts
"""
from __future__ import annotations

import io
import json
import math
import sqlite3
import time
import urllib.request
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Dict, Iterable, List, Optional, Sequence, Tuple

ROOT = Path(__file__).resolve().parents[1]
CACHE = ROOT / "data" / "cache" / "ui"
SLEEVE_NAMES = {"mf-canary": "Rule 8 canary (weekly)"}
FOCUS = ("BTC", "ETH", "SOL", "ETC", "NEAR", "BCH")      # the lift's coins lead the market tab
MIN_VOLUME_USD = 5e6                                      # a mover must trade this much a day to be listed
RESTING_H = 0.0000125                                     # funding at rest: 0.01 % per 8 hours, 11 % a year
LIQ_EVERY_S = 900                                         # aggr's free server: at most one request a quarter hour
VOL_COINS = ("BTC", "ETH", "SOL")
VOL_DAYS = 45                                             # #66 needs 30 complete days; the archive lags a day or two


def local_time(ts: float, fmt: str = "%a %-I:%M %p") -> str:
    return time.strftime(fmt, time.localtime(ts)).replace("AM", "am").replace("PM", "pm")


# ------------------------------------------------------------------------------------------------------- Today
@dataclass(frozen=True)
class Waiting:
    id: str
    what: str            # "Buy BTC $12"
    who: str             # "Rule 8 canary (weekly)"
    by: str              # "Mon 6:55 pm"
    by_ts: int


def waiting(state: Path, now: Optional[int] = None) -> List[Waiting]:
    """Every proposal still open for the holder's answer, oldest first. Read only."""
    from . import approvals as ap

    now = int(time.time()) if now is None else now
    db = Path(state) / ap.LEDGER
    if not db.exists():
        return []
    ledger = ap.Ledger.read_only(db)
    try:
        out = []
        for p in ledger.pending(now):
            verb = "Buy" if p.side == "buy" else "Sell"
            out.append(Waiting(p.id, f"{verb} {p.coin} ${p.notional:,.0f}", SLEEVE_NAMES.get(p.sleeve, p.sleeve),
                               local_time(p.expires), int(p.expires)))
        return out
    finally:
        ledger.db.close()


@dataclass(frozen=True)
class System:
    ok: bool
    line: str
    problems: Tuple[str, ...]


WATCH_STALE_S = 30 * 60


def system(state: Path, now: Optional[float] = None) -> System:
    """One line: all running, or what is not. From the watchdog's last pass and the daily job's last run."""
    now = time.time() if now is None else now
    state = Path(state)
    problems: List[str] = []
    if (state / "KILL").exists():
        problems.append("paused: the KILL file is set")
    try:
        w = json.loads((state / "watchdog.json").read_text())
        if now - float(w.get("at", 0)) > WATCH_STALE_S:
            problems.append("the watchdog has not checked in for over 30 minutes")
        for c in w.get("checks", []):
            if not c.get("ok"):
                problems.append(f"{c.get('name')}: {c.get('note', 'not ok')}")
    except (OSError, ValueError):
        problems.append("no watchdog report yet")
    try:
        h = json.loads((state / "health.json").read_text())
        if not h.get("ok"):
            bad = [k for k, v in (h.get("steps") or {}).items() if not v.get("ok")]
            problems.append("the daily job failed" + (f": {', '.join(bad)}" if bad else ""))
    except (OSError, ValueError):
        problems.append("the daily job has not run here yet")
    if not problems:
        return System(True, "all systems running", ())
    n = len(problems)
    return System(False, f"{n} thing{'s' if n > 1 else ''} need{'' if n > 1 else 's'} a look", tuple(problems))


# ------------------------------------------------------------------------------------------------------ Market
@dataclass
class Coin:
    coin: str
    price: float
    change: float                     # since the venue's previous day, a fraction
    funding_h: float                  # the hourly funding rate; positive: longs pay shorts
    oi_usd: float
    volume_usd: float
    sigma: Optional[float] = None     # the coin's normal daily move (30-day), a fraction
    sigmas: Optional[float] = None    # today's change in units of that


def parse_contexts(payload) -> List[Coin]:
    """Hyperliquid's `metaAndAssetCtxs`: every perp's mark, previous day's price, funding, open interest, volume."""
    meta, ctxs = payload
    out = []
    for u, c in zip(meta["universe"], ctxs):
        if u.get("isDelisted"):
            continue
        try:
            mark, prev = float(c["markPx"]), float(c["prevDayPx"])
            out.append(Coin(u["name"], mark, mark / prev - 1 if prev > 0 else 0.0, float(c["funding"]),
                            float(c["openInterest"]) * mark, float(c["dayNtlVlm"])))
        except (KeyError, TypeError, ValueError):
            continue
    return out


def fetch_contexts(post: Optional[Callable] = None) -> List[Coin]:
    from . import hyperliquid as hl

    post = post or (lambda body: hl.post(body, url=hl.MAINNET_URL + "/info"))
    return parse_contexts(post({"type": "metaAndAssetCtxs"}))


def daily_sigma(closes: Sequence[float]) -> Optional[float]:
    """The standard deviation of daily log returns: a coin's normal day. None with fewer than 10 returns."""
    r = [math.log(b / a) for a, b in zip(closes, closes[1:]) if a > 0 and b > 0]
    if len(r) < 10:
        return None
    m = sum(r) / len(r)
    return math.sqrt(sum((x - m) ** 2 for x in r) / (len(r) - 1))


def sigmas_for(coins: Iterable[Coin], closes: Callable[[str], Sequence[float]]) -> None:
    """Fill each coin's normal day and today's move in units of it."""
    for c in coins:
        try:
            s = daily_sigma(closes(c.coin))
        except Exception:  # noqa: BLE001 - one coin's history failing must not blank the tab
            s = None
        c.sigma = s
        c.sigmas = c.change / s if s else None


def hl_closes(coin: str, days: int = 31) -> List[float]:
    from . import hyperliquid as hl

    df = hl.daily(coin, span=f"{days}d")
    return [float(x) for x in df["close"].tolist()]


def focus(rows: Sequence[Coin], coins: Sequence[str] = FOCUS) -> List[Coin]:
    by = {c.coin: c for c in rows}
    return [by[c] for c in coins if c in by]


def movers(rows: Sequence[Coin], n: int = 8, min_volume: float = MIN_VOLUME_USD) -> List[Coin]:
    """The biggest moves today among coins that trade at least `min_volume` a day, by size of the move."""
    liquid = [c for c in rows if c.volume_usd >= min_volume]
    return sorted(liquid, key=lambda c: -abs(c.change))[:n]


def funding(rows: Sequence[Coin], top: int = 20) -> Dict[str, object]:
    """Who pays whom across the `top` coins by volume, volume-weighted, as a yearly rate; and the extremes."""
    big = sorted(rows, key=lambda c: -c.volume_usd)[:top]
    vol = sum(c.volume_usd for c in big)
    avg_h = sum(c.funding_h * c.volume_usd for c in big) / vol if vol else 0.0
    year = avg_h * 24 * 365
    who = "longs pay shorts" if avg_h > 0 else "shorts pay longs" if avg_h < 0 else "nobody pays"
    liquid = [c for c in rows if c.volume_usd >= MIN_VOLUME_USD]
    crowded_long = [c for c in liquid if c.funding_h > RESTING_H * 1.5]
    crowded_short = [c for c in liquid if c.funding_h < 0]
    return {"who": who, "yearly": year,
            "crowded_long": sorted(crowded_long, key=lambda c: -c.funding_h)[:3],
            "crowded_short": sorted(crowded_short, key=lambda c: c.funding_h)[:3]}


def liquidations(frame) -> Dict[str, Dict[str, float]]:
    """aggr's 5-minute bars -> per coin, the dollars of longs (`lsell`) and shorts (`lbuy`) liquidated, summed."""
    out: Dict[str, Dict[str, float]] = {}
    for _, r in frame.iterrows():
        coin = str(r["market"]).split(":")[1].upper().replace("-USDT-SWAP", "").replace("USDT", "")
        d = out.setdefault(coin, {"longs": 0.0, "shorts": 0.0})
        d["longs"] += float(r.get("lsell") or 0.0) if r.get("lsell") == r.get("lsell") else 0.0
        d["shorts"] += float(r.get("lbuy") or 0.0) if r.get("lbuy") == r.get("lbuy") else 0.0
    return out


def aggr_bars(start_ms: int, end_ms: int, markets: Sequence[str], opener=None):
    """One request to aggr for 5-minute bars of up to ten markets."""
    import urllib.parse

    from . import aggr

    opener = opener or urllib.request.urlopen
    url = aggr.API.format(start=start_ms, end=end_ms, bar_ms=300_000,
                          markets=urllib.parse.quote("+".join(markets), safe=""))
    req = urllib.request.Request(url, headers={"User-Agent": "espero (home screen, a request a quarter hour)"})
    with opener(req, timeout=30) as r:
        payload = json.load(r)
    if payload.get("error"):
        raise RuntimeError(f"aggr: {payload['error']}")
    return aggr.parse(payload)


def last_hour_liquidations(now: Optional[float] = None, fetch=None, cache: Path = CACHE) -> Optional[dict]:
    """The last hour's liquidations on BTC and ETH (Binance, Bybit, OKX) from aggr, asked at most every 15 minutes;
    the cached answer otherwise, with its time. None when aggr cannot be reached and nothing is cached."""
    from . import aggr

    now = time.time() if now is None else now
    p = Path(cache) / "liquidations.json"
    try:
        old = json.loads(p.read_text())
        if now - float(old["at"]) < LIQ_EVERY_S:
            return old
    except (OSError, ValueError, KeyError):
        old = None
    end_ms = int(now // 300 * 300) * 1000
    try:
        frame = (fetch or aggr_bars)(end_ms - 3_600_000, end_ms, aggr.COINS["BTC"]["all"] + aggr.COINS["ETH"]["all"])
        got = {"at": now, "coins": liquidations(frame)}
    except Exception:  # noqa: BLE001 - a free server's hiccup shows the last answer, marked by its age
        return old
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(got))
    return got


# ---------------------------------------------------------------------------------------- volatility outlook
ARCHIVE = "https://data.binance.vision/data/futures/um/daily/klines/{sym}/5m/{sym}-5m-{day}.zip"
KLINE_COLS = ["open_time", "open", "high", "low", "close", "volume", "close_time", "quote_volume", "count",
              "taker_buy_volume", "taker_buy_quote_volume", "ignore"]


def _klines(raw: bytes):
    import pandas as pd

    with zipfile.ZipFile(io.BytesIO(raw)) as z:
        text = z.read(z.namelist()[0]).decode()
    df = pd.read_csv(io.StringIO(text), header=0 if text.split(",", 1)[0].strip() == "open_time" else None)
    df.columns = KLINE_COLS
    return df


def recent_bars(sym: str, today: float, days: int = VOL_DAYS, cache: Path = CACHE,
                get: Optional[Callable[[str], bytes]] = None):
    """The last `days` complete UTC days of 5-minute bars from Binance's public archive (the source #66 used),
    each day's file cached once; a day the archive has not published yet is left out."""
    import pandas as pd

    from . import lows

    get = get or (lambda url: urllib.request.urlopen(url, timeout=30).read())
    frames = []
    for k in range(days, 0, -1):
        day = time.strftime("%Y-%m-%d", time.gmtime(today - k * 86_400))
        f = Path(cache) / "klines5m" / sym / f"{day}.zip"
        if not f.exists():
            try:
                raw = get(ARCHIVE.format(sym=sym, day=day))
            except Exception:  # noqa: BLE001 - not yet published, or unreachable: a gap, not a guess
                continue
            f.parent.mkdir(parents=True, exist_ok=True)
            f.write_bytes(raw)
        frames.append(_klines(f.read_bytes()))
    if not frames:
        return pd.DataFrame()
    return lows.bars(pd.concat(frames, ignore_index=True))


def har_coefficients(sym: str, cache: Path = CACHE, archive: Path = ROOT / "data" / "lows"):
    """#66's HAR fitted once on the archive on disk (data/lows, through its last month) for one coin: (beta, smear).
    Cached; None when the archive is not on this machine."""
    import numpy as np
    import pandas as pd

    from . import lows
    from . import volf as vf

    p = Path(cache) / f"har-{sym}.json"
    try:
        d = json.loads(p.read_text())
        return np.array(d["beta"]), float(d["smear"])
    except (OSError, ValueError, KeyError):
        pass
    files = sorted((Path(archive) / sym).glob("*.zip"))
    if not files:
        return None
    bars = lows.bars(pd.concat([_klines(f.read_bytes()) for f in files], ignore_index=True))
    d = vf.daily(bars)
    feats, y = vf.har_features(d["rv"]), vf.forward_mean_sq(d["ret"], vf.WEEK)
    x = feats.to_numpy(dtype=float)
    yy = y.reindex(feats.index).to_numpy(dtype=float)
    ok = np.isfinite(x).all(axis=1) & np.isfinite(yy) & (yy > 0)
    if ok.sum() < vf.MIN_TRAIN:
        return None
    beta, smear = vf.fit(x[ok], yy[ok])
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps({"beta": beta.tolist(), "smear": smear, "through": files[-1].stem}))
    return beta, smear


@dataclass(frozen=True)
class Outlook:
    coin: str
    next_week: float          # the forecast's typical move over the next 7 days, a fraction
    last_month: float         # the last 30 days' realized, scaled to 7 days, a fraction
    word: str                 # "calmer", "about the same", "stormier"


def outlook_from(daily, beta, smear, coin: str) -> Optional[Outlook]:
    """The forecast from the last complete day's inputs, against the trailing 30-day variance it beat in #66."""
    import numpy as np

    from . import volf as vf

    feats = vf.har_features(daily["rv"]).dropna()
    trail = vf.trailing_var(daily["ret"], vf.TRAIL_WEEK).dropna()
    if feats.empty or trail.empty:
        return None
    f = vf.predict(beta, smear, feats.iloc[-1].to_numpy(dtype=float))
    nxt, past = math.sqrt(7 * f), math.sqrt(7 * float(trail.iloc[-1]))
    ratio = nxt / past if past > 0 else 1.0
    word = "calmer" if ratio < 0.85 else "stormier" if ratio > 1.15 else "about the same"
    return Outlook(coin, nxt, past, word) if np.isfinite(nxt) and np.isfinite(past) else None


def volatility_outlook(coins: Sequence[str] = VOL_COINS, now: Optional[float] = None, cache: Path = CACHE,
                       get=None) -> List[Outlook]:
    """Next week's volatility for each coin, from #66's forecast. Cached for the day."""
    from . import volf as vf

    now = time.time() if now is None else now
    day = time.strftime("%Y-%m-%d", time.gmtime(now))
    p = Path(cache) / f"outlook-{day}.json"
    try:
        return [Outlook(**o) for o in json.loads(p.read_text())]
    except (OSError, ValueError, TypeError):
        pass
    out = []
    for coin in coins:
        sym = f"{coin}USDT"
        coef = har_coefficients(sym, cache)
        if coef is None:
            continue
        bars = recent_bars(sym, now, cache=cache, get=get)
        if bars.empty:
            continue
        o = outlook_from(vf.daily(bars), *coef, coin)
        if o:
            out.append(o)
    if out:
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps([o.__dict__ for o in out]))
    return out


# ------------------------------------------------------------------------------------------------------- Books
def canary(state: Path) -> Dict[str, object]:
    """The canary's progress from its own journal: weeks, what it holds, round trips filled, against its bar."""
    from . import mf_canary as mc
    from . import rungs

    p = Path(state) / mc.DB
    out: Dict[str, object] = {"weeks": 0, "held": [], "round_trips": 0, "needed": rungs.testnet_round_trips(mc.SLEEVE),
                              "last_week": None}
    if not p.exists():
        return out
    con = sqlite3.connect(f"file:{p}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    try:
        weeks = con.execute("SELECT sunday, status FROM weeks ORDER BY sunday DESC").fetchall()
        legs = [dict(r) for r in con.execute("SELECT * FROM legs ORDER BY id")]
    except sqlite3.OperationalError:
        return out
    finally:
        con.close()
    held: Dict[str, float] = {}
    for g in legs:
        if g["filled"]:
            held[g["coin"]] = held.get(g["coin"], 0.0) + (g["filled"] if g["kind"] == "entry" else -g["filled"])
    filled = {g["id"]: True for g in legs if g["status"] == "filled"}
    out.update(weeks=len(weeks), held=sorted(c for c, s in held.items() if s > 1e-12),
               round_trips=mc.round_trips(legs, filled),
               last_week=(weeks[0]["sunday"], weeks[0]["status"]) if weeks else None)
    return out


PAPER = (("tsmom.db", "account", "Trend, monthly"), ("xs.db", "xs_account", "Momentum, weekly"),
         ("mf.db", "mf_account", "Rule 8, weekly"), ("mf-hl.db", "mf_account", "Rule 8 on Hyperliquid prices"))


def paper(state: Path) -> List[Tuple[str, float, float]]:
    """(name, equity now, deposits) for each paper account that exists."""
    out = []
    for db, table, name in PAPER:
        p = Path(state) / db
        if not p.exists():
            continue
        con = sqlite3.connect(f"file:{p}?mode=ro", uri=True)
        try:
            row = con.execute(f"SELECT equity FROM {table} ORDER BY ts DESC, id DESC LIMIT 1").fetchone()
            dep = con.execute(f"SELECT COALESCE(SUM(deposit), 0) FROM {table}").fetchone()
        except sqlite3.OperationalError:
            continue
        finally:
            con.close()
        if row:
            out.append((name, float(row[0]), float(dep[0] or 0.0)))
    return out


def judgment_days(now: Optional[float] = None) -> int:
    """Days until the forward tests are judged, after 2027-03-31."""
    now = time.time() if now is None else now
    return max(0, int((time.mktime((2027, 4, 1, 0, 0, 0, 0, 0, -1)) - now) // 86_400))
