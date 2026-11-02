"""Your actual Coinbase fee rates, read-only.

`GET https://api.exchange.coinbase.com/fees` returns the account's maker and
taker rates and its 30-day USD volume (docs.cdp.coinbase.com, Exchange API,
Fees). It needs an *Exchange* API key with the "view" permission: key, secret
(base64) and passphrase, signed with HMAC-SHA256. It is the only Coinbase key the
repo reads; nothing here can place an order.

Nothing here can trade: the only request is that one GET. The credentials are
read from the environment (.env) and never printed or logged.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Callable, Optional

FEES_URL = "https://api.exchange.coinbase.com"
FEES_PATH = "/fees"
ENV_KEYS = ("COINBASE_EXCHANGE_KEY", "COINBASE_EXCHANGE_SECRET", "COINBASE_EXCHANGE_PASSPHRASE")


class FeesError(RuntimeError):
    pass


@dataclass
class Fees:
    maker: float          # fraction, e.g. 0.006
    taker: float
    usd_volume: float     # trailing 30 days

    @property
    def maker_bps(self) -> float:
        return 1e4 * self.maker

    @property
    def taker_bps(self) -> float:
        return 1e4 * self.taker


def sign(secret_b64: str, timestamp: str, method: str, path: str, body: str = "") -> str:
    """Exchange API signature: base64(HMAC-SHA256(base64decode(secret), ts + METHOD + path + body))."""
    try:
        key = base64.b64decode(secret_b64)
    except (ValueError, TypeError) as exc:
        raise FeesError("COINBASE_EXCHANGE_SECRET is not base64") from exc
    msg = (timestamp + method.upper() + path + body).encode()
    return base64.b64encode(hmac.new(key, msg, hashlib.sha256).digest()).decode()


def parse(payload) -> Fees:
    try:
        return Fees(maker=float(payload["maker_fee_rate"]), taker=float(payload["taker_fee_rate"]),
                    usd_volume=float(payload.get("usd_volume") or 0.0))
    except (KeyError, TypeError, ValueError) as exc:
        shape = sorted(payload) if isinstance(payload, dict) else type(payload).__name__
        raise FeesError(f"unexpected /fees response shape: {shape}") from exc


def fetch(env: Optional[dict] = None, opener: Optional[Callable] = None,
          now: Optional[float] = None) -> Fees:
    """Your rates. Raises FeesError (never with a credential in the message)."""
    env = os.environ if env is None else env
    key, secret, passphrase = (str(env.get(k) or "").strip() for k in ENV_KEYS)
    if not (key and secret and passphrase):
        missing = [k for k in ENV_KEYS if not str(env.get(k) or "").strip()]
        raise FeesError(f"set {', '.join(missing)} in .env (an Exchange API key with the view permission)")
    ts = str(int(now if now is not None else time.time()))
    req = urllib.request.Request(FEES_URL + FEES_PATH, headers={
        "CB-ACCESS-KEY": key, "CB-ACCESS-SIGN": sign(secret, ts, "GET", FEES_PATH),
        "CB-ACCESS-TIMESTAMP": ts, "CB-ACCESS-PASSPHRASE": passphrase,
        "Content-Type": "application/json", "User-Agent": "espero/0.2",
    })
    try:
        with (opener or urllib.request.urlopen)(req, timeout=15) as r:
            payload = json.loads(r.read())
    except urllib.error.HTTPError as exc:
        hint = {401: "key, secret or passphrase rejected", 403: "the key lacks the view permission"}.get(exc.code, "")
        raise FeesError(f"Coinbase /fees: HTTP {exc.code}" + (f" ({hint})" if hint else "")) from None
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise FeesError(f"Coinbase /fees unreachable: {type(exc).__name__}") from None
    return parse(payload)
