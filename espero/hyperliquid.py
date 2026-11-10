"""Hyperliquid public `info` endpoint: perp universe, hourly funding, candles.

Everything here is a POST of a small JSON body to one URL and needs no key.
Two networks: mainnet (market data, the default) and the testnet at
api.hyperliquid-testnet.xyz (HL_NETWORK=testnet, or `testnet_post`), whose web
UI and faucet are at app.hyperliquid-testnet.xyz. Reading an account needs only
its public address; nothing here signs anything.
Every function takes an injectable `fetch(body: dict) -> object` so tests
never touch the network; the default posts through `data.http_get`, which
carries the retry and backoff policy.

Funding on Hyperliquid settles **hourly**, not every 8 hours as on most
venues, and the rate it quotes is the hourly rate. A positive rate is paid by
longs to shorts.
"""
from __future__ import annotations

import datetime as dt
import json
import os
import time
from typing import Callable, Dict, List, Optional

import pandas as pd

MAINNET_URL = "https://api.hyperliquid.xyz"
TESTNET_URL = "https://api.hyperliquid-testnet.xyz"
INFO_URL = MAINNET_URL + "/info"      # default; see info_url()
FUNDING_PERIOD_S = 3600
CANDLE_LIMIT = 5000          # the endpoint returns at most this many candles per call
INTERVAL_S = {"1m": 60, "5m": 300, "15m": 900, "1h": 3600, "4h": 14400, "1d": 86400}

Fetch = Callable[[dict], object]


def network(env: Optional[dict] = None) -> str:
    """"mainnet" or "testnet", from HL_NETWORK in the environment (or .env).
    Market data (universe, funding, candles) comes from mainnet unless asked
    otherwise; the testnet is thin and its funding is not the market's."""
    env = os.environ if env is None else env
    value = (env.get("HL_NETWORK") or "mainnet").strip().lower()
    if value not in ("mainnet", "testnet"):
        raise ValueError(f"HL_NETWORK must be mainnet or testnet, not {value!r}")
    return value


def info_url(env: Optional[dict] = None, testnet: Optional[bool] = None) -> str:
    """HL_API_URL wins; else the network's base. `testnet=True/False` overrides both."""
    env = os.environ if env is None else env
    if testnet is None:
        override = (env.get("HL_API_URL") or "").strip().rstrip("/")
        if override:
            return override + "/info"
        testnet = network(env) == "testnet"
    return (TESTNET_URL if testnet else MAINNET_URL) + "/info"


def post(body: dict, url: Optional[str] = None) -> object:
    from .data import UA, http_get
    raw = http_get(url or INFO_URL, headers={**UA, "Content-Type": "application/json"},
                   data=json.dumps(body).encode())
    return json.loads(raw)


def testnet_post(body: dict) -> object:
    return post(body, info_url(testnet=True))


def user_state(address: str, fetch: Optional[Fetch] = None) -> Dict[str, object]:
    """Read-only account snapshot (`clearinghouseState`): equity, margin in use,
    withdrawable, and open perp positions with entry, size, unrealised P&L and
    the funding they have paid or received. Needs only the public address."""
    st = (fetch or testnet_post)({"type": "clearinghouseState", "user": address})
    summary = st.get("marginSummary", {})
    positions = []
    for ap in st.get("assetPositions", []):
        p = ap.get("position", {})
        szi = float(p.get("szi", 0) or 0)
        if szi == 0:
            continue
        positions.append({
            "coin": p["coin"], "size": szi, "side": "long" if szi > 0 else "short",
            "entry": float(p.get("entryPx") or 0), "notional": float(p.get("positionValue") or 0),
            "unrealized": float(p.get("unrealizedPnl") or 0),
            "funding_paid": float((p.get("cumFunding") or {}).get("sinceOpen", 0) or 0),
            "liquidation": float(p["liquidationPx"]) if p.get("liquidationPx") else None,
            "leverage": float((p.get("leverage") or {}).get("value", 0) or 0),
        })
    return {
        "equity": float(summary.get("accountValue", 0) or 0),
        "margin_used": float(summary.get("totalMarginUsed", 0) or 0),
        "notional": float(summary.get("totalNtlPos", 0) or 0),
        "withdrawable": float(st.get("withdrawable", 0) or 0),
        "positions": positions,
    }


def margin_mode(address: str, fetch: Optional[Fetch] = None) -> Dict[str, object]:
    """How the account is margined, and its spot USDC. A *unified* account (the default
    for new accounts) margins perps with spot USDC directly: its `clearinghouseState`
    reads 0.00 while the money sits in spot, ready to use. Read-only, public address."""
    get = fetch or testnet_post
    try:
        mode = get({"type": "userAbstraction", "user": address})
    except Exception:  # noqa: BLE001 - an older API without the query: the classic split
        mode = "default"
    spot = get({"type": "spotClearinghouseState", "user": address}) or {}
    usdc = next((b for b in spot.get("balances", []) if b.get("coin") == "USDC"), {})
    return {"mode": str(mode or "default"), "spot_usdc": float(usdc.get("total", 0) or 0),
            "spot_hold": float(usdc.get("hold", 0) or 0)}


def perp_dexs(fetch: Optional[Fetch] = None) -> List[Dict[str, object]]:
    """The builder-deployed perp exchanges (HIP-3) by name, e.g. "xyz"; the venue's own perps, which the
    endpoint lists first as null, are left out. Their coins are named "<dex>:<COIN>"."""
    return [d for d in (fetch or post)({"type": "perpDexs"}) if d]


def asset_contexts(fetch: Optional[Fetch] = None, dex: str = "") -> List[Dict[str, float]]:
    """One row per listed perp: coin, mark, hourly funding, open interest and
    24h volume in dollars. `metaAndAssetCtxs` returns `[meta, ctxs]` with the
    two lists aligned by position. `dex` names a builder-deployed exchange
    (`perp_dexs`); empty is the venue's own perps, and the request is then as it always was."""
    meta, ctxs = (fetch or post)({"type": "metaAndAssetCtxs", "dex": dex} if dex else {"type": "metaAndAssetCtxs"})
    out = []
    for m, c in zip(meta["universe"], ctxs):
        if m.get("isDelisted"):
            continue
        mark = float(c["markPx"])
        out.append({
            "coin": m["name"],
            "mark": mark,
            "funding": float(c["funding"]),
            "open_interest": float(c["openInterest"]) * mark,
            "day_volume": float(c["dayNtlVlm"]),
            "max_leverage": int(m.get("maxLeverage", 0)),
        })
    return out


def top_by_open_interest(n: int, ctxs: List[Dict[str, float]]) -> List[str]:
    ranked = sorted(ctxs, key=lambda r: r["open_interest"], reverse=True)
    return [r["coin"] for r in ranked[:n]]


def funding_history(coin: str, start_ms: int, end_ms: Optional[int] = None,
                    fetch: Optional[Fetch] = None, pages: int = 200,
                    sleep=time.sleep) -> pd.DataFrame:
    """Hourly funding, walking forward 500 rows per call. Columns `ts`
    (seconds, the settlement hour) and `funding` (hourly rate)."""
    rows, cursor = [], start_ms
    for _ in range(pages):
        body = {"type": "fundingHistory", "coin": coin, "startTime": cursor}
        if end_ms is not None:
            body["endTime"] = end_ms
        page = (fetch or post)(body)
        if not page:
            break
        rows.extend(page)
        cursor = int(page[-1]["time"]) + 1
        if len(page) < 500:
            break
        sleep(0.5)      # the info endpoint rate-limits bursts of history pages
    if not rows:
        return pd.DataFrame(columns=["ts", "funding"])
    df = pd.DataFrame([{"ts": int(r["time"]) // 1000, "funding": float(r["fundingRate"])}
                       for r in rows])
    return df.drop_duplicates("ts").sort_values("ts").reset_index(drop=True)


def candles(coin: str, interval: str, start_ms: int, end_ms: Optional[int] = None,
            fetch: Optional[Fetch] = None, sleep=time.sleep) -> pd.DataFrame:
    """Perp candles in the same frame as `data.fetch`: `time` (ISO, UTC),
    open/high/low/close/volume. Paginates forward under the 5000-candle cap."""
    step_ms = INTERVAL_S[interval] * 1000
    if end_ms is None:
        end_ms = int(dt.datetime.now(dt.timezone.utc).timestamp() * 1000)
    rows: Dict[int, dict] = {}
    cursor = start_ms
    while cursor < end_ms:
        chunk_end = min(cursor + step_ms * CANDLE_LIMIT, end_ms)
        page = (fetch or post)({"type": "candleSnapshot",
                                "req": {"coin": coin, "interval": interval,
                                        "startTime": cursor, "endTime": chunk_end}})
        if not page:
            break
        for r in page:
            rows[int(r["t"])] = r
        last = int(page[-1]["t"])
        if last + step_ms <= cursor:
            break
        cursor = last + step_ms
        if cursor < end_ms:
            sleep(0.15)
    return pd.DataFrame([{
        "time": dt.datetime.fromtimestamp(t // 1000, dt.timezone.utc).isoformat(),
        "open": float(r["o"]), "high": float(r["h"]), "low": float(r["l"]),
        "close": float(r["c"]), "volume": float(r["v"]),
    } for t, r in sorted(rows.items())])


# ------------------------------------------------- prices for the rest of espero
# Market data for the board, the XS account, #8's shadow book, the scan and the fast
# screen. Always mainnet: the testnet's prices are not the market's. These are perp
# prices; they track spot closely but are not spot, and a coin Hyperliquid does not
# list is an error for the caller to record, never a substitute.
COIN = {"SHIB": "kSHIB"}             # quoted per 1,000 coins
UNIT = {"kSHIB": 1000.0}
INTERVALS = {seconds: name for name, seconds in INTERVAL_S.items()}
SPAN_DAYS = {"1y": 365, "2y": 730, "5y": 1826, "10y": 3652}


def funding_rates(product: str, fetch: Optional[Fetch] = None):
    """For the paper trader: (start_s, end_s) -> {settlement hour: hourly rate} for
    `product`'s perp, from fundingHistory. Settlement times are rounded to the hour."""
    coin = hl_coin(product)

    def rates(start_s: int, end_s: int) -> Dict[int, float]:
        df = funding_history(coin, (start_s - 60) * 1000, (end_s + 60) * 1000, fetch=fetch, sleep=lambda s: None)
        return {int(round(ts / 3600)) * 3600: float(r) for ts, r in zip(df["ts"], df["funding"])}
    return rates


def hl_coin(symbol: str) -> str:
    """"BTC-USD" or "BTC" -> Hyperliquid's name for the perp."""
    base = symbol.upper().split("-")[0]
    return COIN.get(base, base)


_LISTED: Dict[str, object] = {"names": None, "at": 0.0}
LISTED_TTL_S = 3600


def listed(fetch: Optional[Fetch] = None) -> set:
    """Names of the perps Hyperliquid lists now (delisted ones dropped). The live
    answer is cached for an hour: a coin it does not list is answered with HTTP 500
    and four retries, so callers check here first."""
    if fetch is None and _LISTED["names"] is not None and time.time() - float(_LISTED["at"]) < LISTED_TTL_S:
        return set(_LISTED["names"])
    meta = (fetch or post)({"type": "meta"})
    names = {u["name"] for u in meta["universe"] if not u.get("isDelisted")}
    if fetch is None:
        _LISTED.update(names=names, at=time.time())
    return names


def _per_thousand(name: str) -> bool:
    """kPEPE, kBONK, kSHIB: perps quoted per 1,000 coins."""
    return len(name) > 1 and name[0] == "k" and name[1:].isupper()


def degen_universe(top: int = 60, exclude=("BTC", "ETH"), fetch: Optional[Fetch] = None) -> List[dict]:
    """The perps people are trading on Hyperliquid now, ranked by 24h dollar volume, top
    `top`, in `data.degen_universe`'s rows: product (`BASE-USD`), last, volume (coins),
    dollar_volume. A perp quoted per 1,000 coins is named for its coin and registered in
    COIN/UNIT, all of them and not only the top, so `closed_bars` prices a held one per
    coin even after it leaves the list. One call for the whole list."""
    rows = []
    for c in asset_contexts(fetch):
        name = c["coin"]
        k = 1000.0 if _per_thousand(name) else 1.0
        base = name[1:] if k != 1.0 else name
        if k != 1.0:
            COIN.setdefault(base, name)
            UNIT.setdefault(name, k)
        if base in exclude or c["mark"] <= 0:
            continue
        last = c["mark"] / k
        rows.append({"product": f"{base}-USD", "last": last, "volume": c["day_volume"] / last,
                     "dollar_volume": c["day_volume"]})
    rows.sort(key=lambda r: -r["dollar_volume"])
    return rows[:top]


def closed_bars(product: str, granularity: int = 3600, limit: int = 300,
                fetch: Optional[Fetch] = None, now: Optional[float] = None) -> pd.DataFrame:
    """The most recent completed bars, oldest first, in `data.recent_closed_bars`' frame:
    dt, ts, open/high/low/close per coin, volume in coins. The bar still forming is
    dropped. Raises data.FetchError for a coin Hyperliquid does not list."""
    from .data import FetchError, unix_seconds
    coin, k = hl_coin(product), UNIT.get(hl_coin(product), 1.0)
    if fetch is None and coin not in listed():     # delisted perps still serve old candles
        raise FetchError(f"{product}: Hyperliquid does not list {coin}")
    now = time.time() if now is None else now
    end = int(now // granularity * granularity)            # start of the bar still forming
    raw = candles(coin, INTERVALS[granularity], (end - granularity * limit) * 1000, end * 1000 - 1,
                  fetch=fetch, sleep=lambda s: None)
    if raw.empty:
        raise FetchError(f"{product}: no Hyperliquid perp {coin}")
    t = pd.to_datetime(raw["time"], utc=True)
    out = pd.DataFrame({"dt": t, "ts": unix_seconds(t).to_numpy(),
                        **{c: raw[c].to_numpy() / k for c in ("open", "high", "low", "close")},
                        "volume": raw["volume"].to_numpy() * k})
    return out[out["ts"] + granularity <= now].tail(limit).reset_index(drop=True)


def daily(symbol: str, span: str = "2y", fetch: Optional[Fetch] = None,
          now: Optional[float] = None) -> pd.DataFrame:
    """Daily bars shaped like `data.yahoo_daily(adjusted=True)`, so the board, the XS
    account and #8's panel can take them unchanged. adj_close is the close: a perp pays
    no dividends. Hyperliquid serves daily history from August 2020."""
    days = SPAN_DAYS.get(span) or int(str(span).rstrip("d"))
    df = closed_bars(symbol, 86400, days, fetch=fetch, now=now)
    return df.assign(adj_close=df["close"])


class HyperliquidBook:
    """The fast screen's live feed from Hyperliquid mainnet: the top 20 levels a side
    and the prints since the last read, prices per coin. Same contract as
    `book.CoinbaseBook.read()`."""

    def __init__(self, product: str, fetch: Optional[Fetch] = None):
        self.product = product
        self.coin = hl_coin(product)
        self.k = UNIT.get(self.coin, 1.0)
        self.fetch = fetch or post
        self.seen: Optional[set] = None

    def read(self):
        from .book import BookSnapshot, Trade
        book = self.fetch({"type": "l2Book", "coin": self.coin})
        raw = self.fetch({"type": "recentTrades", "coin": self.coin})
        k = self.k
        bids = [(float(lv["px"]) / k, float(lv["sz"]) * k) for lv in book["levels"][0]]
        asks = [(float(lv["px"]) / k, float(lv["sz"]) * k) for lv in book["levels"][1]]
        ids = {int(t["tid"]) for t in raw}
        trades = [] if self.seen is None else [      # the first read has no "since"
            Trade(int(t["tid"]), t["time"] / 1000, "buy" if t["side"] == "B" else "sell",
                  float(t["px"]) / k, float(t["sz"]) * k)
            for t in raw if int(t["tid"]) not in self.seen]
        self.seen = ((self.seen or set()) | ids) if len(self.seen or ()) < 5000 else ids
        trades.sort(key=lambda t: (t.ts, t.id))
        return BookSnapshot(time.time(), self.product, bids, asks, trades)

