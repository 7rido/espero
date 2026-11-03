"""Hyperliquid **testnet** order path. The only code in espero that signs anything.

Guard rails, in the order they are checked, every time an exchange is built:

1. `HL_NETWORK` must be `testnet`.
2. `ESPERO_ALLOW_HL_TESTNET=1` must be set (a second, explicit opt-in).
3. `HL_API_URL`, if set, must be a testnet URL. The exchange is built on the
   testnet constant regardless; the env can refuse, never redirect.
4. `HL_PRIVATE_KEY` is read here and nowhere else, and only after 1-3 pass.

The signer is the official SDK (`hyperliquid-python-sdk`), installed as the
`hl` extra. Mainnet is not reachable from this module: the base URL is a
constant, and it is asserted after construction.

The mirror at the bottom shadows a carry paper book's perp leg with real
testnet orders (ALO, resting at the hour's price) so the maker-fill assumption
behind #12 can be measured instead of assumed. The spot leg stays paper: there
is no spot market for these coins on the testnet.
"""
from __future__ import annotations

import math
import os
import re
import sqlite3
import time
import urllib.parse
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

TESTNET_URL = "https://api.hyperliquid-testnet.xyz"
TESTNET_HOST = "api.hyperliquid-testnet.xyz"
MAX_SIG_FIGS = 5
MAX_DECIMALS_PERP = 6


class TestnetRefused(RuntimeError):
    """Raised, never caught here, when the environment does not describe a testnet-only setup."""


def guard(env: Optional[dict] = None) -> str:
    """Return the private key only when every testnet guard passes."""
    env = os.environ if env is None else env
    network = (env.get("HL_NETWORK") or "").strip().lower()
    if network != "testnet":
        raise TestnetRefused("HL_NETWORK must be 'testnet' to sign anything (mainnet signing is not implemented)")
    if (env.get("ESPERO_ALLOW_HL_TESTNET") or "").strip() != "1":
        raise TestnetRefused("set ESPERO_ALLOW_HL_TESTNET=1 to allow testnet orders")
    override = (env.get("HL_API_URL") or "").strip()
    if override and urllib.parse.urlparse(override).hostname != TESTNET_HOST:
        raise TestnetRefused(f"HL_API_URL={override!r} is not the testnet ({TESTNET_HOST}); refusing")
    key = (env.get("HL_PRIVATE_KEY") or "").strip()
    if not key:
        raise TestnetRefused("HL_PRIVATE_KEY is empty: create an API wallet in the testnet UI and put its key in .env")
    return key


def account_address(env: dict) -> Optional[str]:
    """HL_WALLET_ADDRESS when it is a well-formed 0x address, else None."""
    a = (env.get("HL_WALLET_ADDRESS") or "").strip()
    return a if re.fullmatch(r"0x[0-9a-fA-F]{40}", a) else None


# -------------------------------------------------------------------- rounding
def round_size(sz: float, sz_decimals: int) -> float:
    # round first: 0.00014 * 1e5 is 13.999999999999998 in floating point and must not floor to 13
    return math.floor(round(abs(sz) * 10 ** sz_decimals, 9)) / 10 ** sz_decimals


def round_price(px: float, sz_decimals: int, side: str) -> float:
    """Hyperliquid accepts at most 5 significant figures and 6 − szDecimals
    decimals on a perp price. A sell is rounded up and a buy down so the
    rounded order never crosses further than the asked price."""
    if px <= 0:
        raise ValueError("price must be positive")
    decimals = min(MAX_DECIMALS_PERP - sz_decimals, max(0, MAX_SIG_FIGS - 1 - int(math.floor(math.log10(px)))))
    step = 10 ** -decimals
    units = px / step
    units = math.ceil(units - 1e-9) if side == "sell" else math.floor(units + 1e-9)
    return round(units * step, decimals)


def parse_order_response(resp: Any) -> dict:
    """Flatten the SDK's order response to {status, oid, filled, avg_px, error}."""
    try:
        st = resp["response"]["data"]["statuses"][0]
    except (KeyError, IndexError, TypeError):
        return {"status": "error", "oid": None, "filled": 0.0, "avg_px": None,
                "error": str(resp)[:200]}
    if "resting" in st:
        return {"status": "resting", "oid": int(st["resting"]["oid"]), "filled": 0.0, "avg_px": None, "error": None}
    if "filled" in st:
        f = st["filled"]
        return {"status": "filled", "oid": int(f["oid"]), "filled": float(f["totalSz"]),
                "avg_px": float(f["avgPx"]), "error": None}
    return {"status": "error", "oid": None, "filled": 0.0, "avg_px": None, "error": str(st.get("error", st))[:200]}


def _cloid(raw: str):
    """The SDK's Cloid when it is installed; the bare string for injected fakes."""
    try:
        from hyperliquid.utils.types import Cloid
    except ImportError:
        return raw
    return Cloid(raw)


# -------------------------------------------------------------------- exchange
@dataclass
class OrderResult:
    coin: str
    side: str
    size: float
    price: float
    tif: str
    status: str
    oid: Optional[int]
    filled: float
    avg_px: Optional[float]
    error: Optional[str]


class TestnetExchange:
    """Thin, testnet-only wrapper over the SDK's Exchange and Info clients.

    `exchange` / `info` can be injected (tests); when they are, no key is read
    and nothing is built. `meta` is {coin: szDecimals}."""

    def __init__(self, env: Optional[dict] = None, exchange=None, info=None,
                 meta: Optional[Dict[str, int]] = None, address: Optional[str] = None):
        if exchange is None:
            key = guard(env)
            from eth_account import Account
            from hyperliquid.exchange import Exchange
            from hyperliquid.info import Info
            wallet = Account.from_key(key)
            env_ = os.environ if env is None else env
            # an API (agent) wallet signs for the main account: orders, fills and
            # positions belong to HL_WALLET_ADDRESS, not to the signing key
            account = address or account_address(env_) or wallet.address
            exchange = Exchange(wallet, base_url=TESTNET_URL,
                                account_address=account if account.lower() != wallet.address.lower() else None)
            info = info or Info(base_url=TESTNET_URL, skip_ws=True)
            address = account
            if getattr(exchange, "base_url", TESTNET_URL) != TESTNET_URL:
                raise TestnetRefused("exchange is not on the testnet URL; refusing")
        self.ex = exchange
        self.info = info
        self.address = address or ""
        self._meta = meta

    @property
    def meta(self) -> Dict[str, int]:
        if self._meta is None:
            m = self.info.meta()
            self._meta = {u["name"]: int(u["szDecimals"]) for u in m["universe"]}
        return self._meta

    def limit(self, coin: str, side: str, size: float, price: float, tif: str = "Alo",
              reduce_only: bool = False, cloid: Optional[str] = None) -> OrderResult:
        """Resting limit order. `tif` Alo = add-liquidity-only (rejected rather
        than crossing: the maker test), Gtc = may take, Ioc = take or cancel.
        `cloid` (0x + 32 hex) tags the order so a timed-out call can be looked up."""
        if side not in ("buy", "sell"):
            raise ValueError("side must be buy or sell")
        if coin not in self.meta:
            raise ValueError(f"{coin}: not a testnet perp")
        sd = self.meta[coin]
        sz, px = round_size(size, sd), round_price(price, sd, side)
        if sz <= 0:
            raise ValueError(f"{coin}: size {size} rounds to zero at {sd} decimals")
        if px <= 0:
            raise ValueError(f"{coin}: price {price} rounds to zero on the venue's grid")
        kw = {"cloid": _cloid(cloid)} if cloid else {}
        resp = self.ex.order(coin, side == "buy", sz, px, {"limit": {"tif": tif}}, reduce_only=reduce_only, **kw)
        p = parse_order_response(resp)
        return OrderResult(coin, side, sz, px, tif, **p)

    def order_status(self, cloid: str) -> dict:
        """The venue's record of an order by client id: {"status": "unknownOid"} if it never arrived."""
        return self.info.query_order_by_cloid(self.address, _cloid(cloid))

    def book(self, coin: str) -> tuple[float, float]:
        """Best bid and ask on the testnet book. The mirror prices from here,
        not from mainnet: an ALO order only measures maker fills if it rests
        at the top of the book it is posted to."""
        snap = self.info.l2_snapshot(coin)
        bids, asks = snap["levels"][0], snap["levels"][1]
        if not bids or not asks:
            raise ValueError(f"{coin}: empty testnet book")
        return float(bids[0]["px"]), float(asks[0]["px"])

    def cancel(self, coin: str, oid: int) -> bool:
        resp = self.ex.cancel(coin, int(oid))
        return isinstance(resp, dict) and resp.get("status") == "ok"

    def open_orders(self) -> List[dict]:
        return list(self.info.open_orders(self.address))

    def fills(self, since_ts: int = 0) -> List[dict]:
        out = []
        for f in self.info.user_fills(self.address):
            if int(f.get("time", 0)) // 1000 >= since_ts:
                out.append(f)
        return out

    def positions(self) -> dict:
        from . import hyperliquid as hl
        return hl.user_state(self.address, fetch=hl.testnet_post)


# ---------------------------------------------------------------------- mirror
MIRROR_SCHEMA = """
CREATE TABLE IF NOT EXISTS testnet_mirror (
    position_id INTEGER PRIMARY KEY, coin TEXT,
    open_oid INTEGER, open_px REAL, open_size REAL, open_status TEXT, open_filled REAL DEFAULT 0, open_ts INTEGER,
    close_oid INTEGER, close_px REAL, close_status TEXT, close_filled REAL DEFAULT 0, close_ts INTEGER,
    note TEXT
);
"""
# added after the first version; created on open when missing
MIRROR_COLUMNS = {"paper_px": "REAL", "close_done": "REAL DEFAULT 0", "close_tries": "INTEGER DEFAULT 0"}
CLOSE_TRIES_MAKER = 3      # after this many unfilled ALO closes, cross the spread to flatten
REPRICE_S = 3000           # a close still resting this long is cancelled and re-placed


class TestnetMirror:
    """Shadow a CarryBook's perp leg on the testnet with ALO orders priced at
    the testnet book (sell at the best ask, buy back at the best bid). One row
    per paper position; statuses are refreshed from the venue on every sync.
    The answer it produces is the fill rate of resting orders, the number #12
    assumed to be 100%. Closes are retried until the short is flat: re-priced
    each sync, and after CLOSE_TRIES_MAKER tries sent as a crossing IOC (noted)."""

    def __init__(self, db: sqlite3.Connection, exchange: TestnetExchange):
        self.db = db
        self.ex = exchange
        self.db.executescript(MIRROR_SCHEMA)
        have = {r[1] for r in self.db.execute("PRAGMA table_info(testnet_mirror)")}
        for col, kind in MIRROR_COLUMNS.items():
            if col not in have:
                self.db.execute(f"ALTER TABLE testnet_mirror ADD COLUMN {col} {kind}")
        self.db.commit()

    def rows(self) -> List[sqlite3.Row]:
        return self.db.execute("SELECT * FROM testnet_mirror ORDER BY position_id").fetchall()

    def _place(self, coin: str, side: str, size: float, price: float, tif: str, reduce_only: bool) -> OrderResult:
        """Place, and if the call itself failed (timeout after the venue took
        it), look for the order among the open ones before calling it lost."""
        try:
            return self.ex.limit(coin, side, size, price, tif=tif, reduce_only=reduce_only)
        except Exception as exc:  # noqa: BLE001 - record, do not crash the paper book
            err = str(exc)[:200]
        tracked = {r["open_oid"] for r in self.rows()} | {r["close_oid"] for r in self.rows()}
        want = "A" if side == "sell" else "B"
        try:
            for o in self.ex.open_orders():
                if (o.get("coin") == coin and o.get("side") == want and int(o["oid"]) not in tracked
                        and abs(float(o.get("sz", 0)) - size) <= 1e-9 * max(1.0, size)):
                    return OrderResult(coin, side, size, float(o.get("limitPx", price)), tif, "resting",
                                       int(o["oid"]), 0.0, None, f"recovered after: {err}")
        except Exception:  # noqa: BLE001
            pass
        return OrderResult(coin, side, size, price, tif, "error", None, 0.0, None, err)

    def sync(self, positions: List[sqlite3.Row], closed: List[sqlite3.Row], prices: Dict[str, float],
             now: Optional[int] = None) -> List[str]:
        """`prices` are the paper book's (mainnet) perp prices, kept only to
        record the gap to the testnet book; orders are priced from the book."""
        now = now or int(time.time())
        out: List[str] = []
        self.refresh(out, now=now)
        known = {r["position_id"]: r for r in self.rows()}

        # 1. new paper positions -> resting short at the testnet best ask
        for p in positions:
            if p["id"] in known:
                continue
            try:
                _, ask = self.ex.book(p["coin"])
            except Exception as exc:  # noqa: BLE001 - try again next sync
                out.append(f"testnet {p['coin']}: no book ({exc}); open retried next hour")
                continue
            r = self._place(p["coin"], "sell", p["qty_perp"], ask, "Alo", False)
            self.db.execute(
                "INSERT INTO testnet_mirror (position_id, coin, open_oid, open_px, open_size, open_status, "
                "open_filled, open_ts, note, paper_px) VALUES (?,?,?,?,?,?,?,?,?,?)",
                (p["id"], p["coin"], r.oid, r.price, r.size, r.status, r.filled, now, r.error,
                 prices.get(p["coin"])))
            out.append(f"testnet {p['coin']}: short {r.size} @ {r.price} ALO -> {r.status}"
                       + (f" ({r.error})" if r.error else ""))

        # 2. paper closes -> stop the open, buy back what filled until flat
        for c in closed:
            m = known.get(c["id"])
            if m is None or m["close_status"] in ("filled", "unfilled_open"):
                continue
            if m["open_oid"] and m["open_status"] in ("resting", "part"):
                # the paper hedge is gone: no more of the open may fill
                try:
                    self.ex.cancel(c["coin"], m["open_oid"])
                except Exception:  # noqa: BLE001
                    pass
                self.db.execute("UPDATE testnet_mirror SET open_status=? WHERE position_id=?",
                                ("part" if (m["open_filled"] or 0) > 0 else "cancelled", c["id"]))
            filled = float(m["open_filled"] or 0)
            if filled <= 0:
                self.db.execute("UPDATE testnet_mirror SET close_status='unfilled_open', close_ts=? "
                                "WHERE position_id=?", (now, c["id"]))
                out.append(f"testnet {c['coin']}: paper closed, open never filled -> cancelled")
                continue
            self._close(m, filled, now, out)

        self.db.commit()
        return out

    def _close(self, m: sqlite3.Row, filled: float, now: int, out: List[str]) -> None:
        coin = m["coin"]
        done = float(m["close_done"] or 0) + (float(m["close_filled"] or 0) if m["close_oid"] else 0.0)
        remaining = filled - done
        if remaining <= filled * 1e-3:
            self.db.execute("UPDATE testnet_mirror SET close_status='filled' WHERE position_id=?",
                            (m["position_id"],))
            return
        if m["close_oid"] and m["close_status"] in ("resting", "part"):
            if now - (m["close_ts"] or 0) < REPRICE_S:
                return                                   # give the resting close time
            try:
                self.ex.cancel(coin, m["close_oid"])
            except Exception:  # noqa: BLE001
                pass
        try:
            bid, ask = self.ex.book(coin)
        except Exception as exc:  # noqa: BLE001
            out.append(f"testnet {coin}: no book ({exc}); close retried next hour")
            return
        tries = int(m["close_tries"] or 0) + 1
        if tries > CLOSE_TRIES_MAKER:
            r = self._place(coin, "buy", remaining, ask, "Ioc", True)     # cross: flatten
            tag = "IOC (maker closes did not fill)"
        else:
            r = self._place(coin, "buy", remaining, bid, "Alo", True)
            tag = "ALO"
        self.db.execute(
            "UPDATE testnet_mirror SET close_oid=?, close_px=?, close_status=?, close_filled=?, close_ts=?, "
            "close_done=?, close_tries=?, note=COALESCE(note,'') || ? WHERE position_id=?",
            (r.oid, r.price, r.status, r.filled, now, done, tries,
             f" close#{tries} {tag}" + (f": {r.error}" if r.error else ""), m["position_id"]))
        if r.status == "filled" and done + r.filled >= filled * 0.999:
            self.db.execute("UPDATE testnet_mirror SET close_status='filled' WHERE position_id=?",
                            (m["position_id"],))
        out.append(f"testnet {coin}: close buy {r.size} @ {r.price} {tag} -> {r.status}")

    def refresh(self, out: Optional[List[str]] = None, now: Optional[int] = None, grace: int = 60) -> None:
        """Pull statuses from the venue. An order placed less than `grace`
        seconds ago that the venue does not list yet is left as it is, so a
        just-placed order is not misread as cancelled."""
        out = out if out is not None else []
        now = now or int(time.time())
        try:
            open_oids = {int(o["oid"]) for o in self.ex.open_orders()}
            fills = self.ex.fills()
        except Exception as exc:  # noqa: BLE001
            out.append(f"testnet: status refresh failed: {exc}")
            return
        filled: Dict[int, float] = {}
        for f in fills:
            filled[int(f["oid"])] = filled.get(int(f["oid"]), 0.0) + float(f["sz"])
        for m in self.rows():
            for leg in ("open", "close"):
                oid, status = m[f"{leg}_oid"], m[f"{leg}_status"]
                if not oid or status in ("filled", "cancelled", "error", "unfilled_open"):
                    continue
                got = filled.get(oid, 0.0)
                size = (m["open_size"] if leg == "open"
                        else (m["open_filled"] or 0) - (m["close_done"] or 0))
                fresh = (m[f"{leg}_ts"] or 0) > now - grace
                new = ("filled" if size and got >= size * 0.999 else
                       "part" if got > 0 else
                       "resting" if oid in open_oids or fresh else "cancelled")
                if new != status or got != m[f"{leg}_filled"]:
                    self.db.execute(f"UPDATE testnet_mirror SET {leg}_status=?, {leg}_filled=? WHERE position_id=?",
                                    (new, got, m["position_id"]))
                    out.append(f"testnet {m['coin']}: {leg} order {oid} {status} -> {new} ({got} filled)")

    def summary(self) -> dict:
        rows = self.rows()
        opens = [r for r in rows if r["open_oid"]]
        return {
            "orders": len(opens),
            "filled": sum(1 for r in opens if r["open_status"] == "filled"),
            "part": sum(1 for r in opens if r["open_status"] == "part"),
            "resting": sum(1 for r in opens if r["open_status"] == "resting"),
            "cancelled": sum(1 for r in opens if r["open_status"] in ("cancelled", "unfilled_open")),
            "errors": sum(1 for r in rows if r["open_status"] == "error"),
        }
