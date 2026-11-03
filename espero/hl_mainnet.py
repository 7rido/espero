"""Hyperliquid **mainnet** order path, built from research/DESIGN_MAINNET_PATH.md after the holder's signed lift.

The no-mainnet rule was lifted by the holder in research/MAINNET_LIFT.md (commits cf109df and 88cd069, signed with
the holder's key). This module exists only under that lift, and refuses unless every guard passes, in this order,
every time an exchange is built:

1. `HL_NETWORK` is `mainnet`, so this module and the testnet's can never be built from one environment.
2. `ESPERO_ALLOW_HL_MAINNET=1`, a second opt-in distinct from the testnet's.
3. The holder's lift: `docs/HOLDER_INPUTS.md`'s `mainnet_lift`, as HEAD holds it, names a file; that file is at HEAD
   and unchanged on disk; its last commit passes `git verify-commit` against the allowed-signers file git is
   configured with, which must sit outside the repository; its block names this venue, an expiry not yet past and
   this machine's hash.
4. The allow-list, `config/mainnet_allowlist.json`, at HEAD, unchanged, its last commit verified the same way; every
   order's coin and size are checked against it and against the lift.
5. Every order carries a `risk.Ruling` that allowed it, at most its notional, under the policy committed at HEAD.
6. Live only: the key, `HL_MAINNET_PRIVATE_KEY`, read here and nowhere else, after 1 to 5; never when `CI` is set.
7. Live only: the base URL is a constant and is asserted after the SDK is built.

Dry run is the default: guards 1 to 5 run, the order is checked, and the exact order that would have been sent is
journaled to `state/mainnet-dryrun.db`. No key is read and no signer is built.

The kill switch is the state folder's `KILL` file, read before every order: while it exists only reduce-only orders
pass; when it reads `flatten`, `flatten()` closes every position with reduce-only IOC orders crossing further on each
unfilled try (`hlp_testnet.EXIT_SLIPS`).
"""
from __future__ import annotations

import json
import math
import os
import sqlite3
import subprocess
import time
import urllib.parse
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Callable, Dict, List, Optional, Sequence, Tuple

from . import holder, risk
from .hl_exchange import (
    OrderResult,
    TestnetExchange,
    _cloid,
    account_address,
    parse_order_response,
    round_price,
    round_size,
)
from .hlp_testnet import EXIT_SLIPS

MAINNET_URL = "https://api.hyperliquid.xyz"
MAINNET_HOST = "api.hyperliquid.xyz"
VENUE = "hyperliquid"
ROOT = Path(__file__).resolve().parents[1]
ALLOWLIST = Path("config") / "mainnet_allowlist.json"
DRY_DB = "mainnet-dryrun.db"
LIVE_DB = "mainnet-orders.db"
KILL = "KILL"

SCHEMA = """CREATE TABLE IF NOT EXISTS mainnet_orders (
    id INTEGER PRIMARY KEY AUTOINCREMENT, ts INTEGER NOT NULL, mode TEXT NOT NULL,
    coin TEXT, side TEXT, size REAL, price REAL, tif TEXT, reduce_only INTEGER, cloid TEXT, notional REAL,
    policy_hash TEXT, lift_commit TEXT, allow_commit TEXT,
    status TEXT, oid INTEGER, filled REAL, avg_px REAL, error TEXT
);"""


class MainnetRefused(RuntimeError):
    """Raised, never caught in this module, when a guard does not pass. The message says which."""


# ----------------------------------------------------------------------------------------------- git and the lift
def _git(root: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["git", "-C", str(root), *args], capture_output=True, text=True, timeout=60)


def at_head_unchanged(root: Path, rel: str) -> bool:
    """The file is in HEAD and the copy on disk is byte for byte HEAD's."""
    r = subprocess.run(["git", "-C", str(root), "show", f"HEAD:{rel}"], capture_output=True, timeout=60)
    p = root / rel
    return r.returncode == 0 and p.is_file() and r.stdout == p.read_bytes()


def last_commit(root: Path, rel: str) -> str:
    r = _git(root, "log", "-1", "--format=%H", "--", rel)
    return r.stdout.strip() if r.returncode == 0 else ""


def signers_file(root: Path) -> Optional[Path]:
    """git's configured allowed-signers file, when it exists and lies outside the repository."""
    r = _git(root, "config", "--get", "gpg.ssh.allowedSignersFile")
    raw = r.stdout.strip()
    if r.returncode != 0 or not raw:
        return None
    p = Path(os.path.expanduser(raw)).resolve()
    try:
        p.relative_to(Path(root).resolve())
        return None                     # inside the repo: anything that can commit could rewrite it
    except ValueError:
        pass
    return p if p.is_file() else None


def verified(root: Path, commit: str) -> bool:
    """The commit carries a signature that `git verify-commit` accepts against the allowed-signers file."""
    if not commit or signers_file(root) is None:
        return False
    return _git(root, "verify-commit", commit).returncode == 0


@dataclass(frozen=True)
class Lift:
    path: str
    commit: str
    venue: str
    coins: Tuple[str, ...]
    max_order_usd: float
    max_position_usd: float
    expiry: date
    machine: str


def read_lift(root: Path = ROOT, today: Optional[date] = None, machine: Optional[str] = None) -> Lift:
    """Guard 3: the holder's committed, signed, unexpired lift for this venue and this machine."""
    from .holderform import lift_answers, machine_hash

    page = Path(root) / "docs" / "HOLDER_INPUTS.md"
    if not at_head_unchanged(root, "docs/HOLDER_INPUTS.md"):
        raise MainnetRefused("docs/HOLDER_INPUTS.md is not what HEAD holds: an answer counts only once committed")
    rel = holder.answers(page)["mainnet_lift"]
    if not rel:
        raise MainnetRefused("no lift: docs/HOLDER_INPUTS.md names no mainnet_lift")
    if not at_head_unchanged(root, rel):
        raise MainnetRefused(f"the lift {rel} is not at HEAD, or has uncommitted edits")
    commit = last_commit(root, rel)
    if not verified(root, commit):
        raise MainnetRefused(f"the lift's commit {commit[:12] or '?'} does not verify against the allowed signers")
    f = lift_answers((Path(root) / rel).read_text(encoding="utf-8"))
    try:
        lift = Lift(rel, commit, f["venue"].strip().lower(),
                    tuple(c.strip().upper() for c in f["coins"].split(",") if c.strip()),
                    float(f["max_order_usd"]), float(f["max_position_usd"]),
                    date.fromisoformat(f["expiry"].strip()), f["machine"].strip())
    except (KeyError, ValueError) as exc:
        raise MainnetRefused(f"the lift's block does not read: {exc}") from None
    if lift.venue != VENUE:
        raise MainnetRefused(f"the lift covers {lift.venue}, not {VENUE}")
    if (today or date.today()) > lift.expiry:
        raise MainnetRefused(f"the lift lapsed on {lift.expiry}")
    if not (0 < lift.max_order_usd <= lift.max_position_usd) or not all(map(math.isfinite, (lift.max_order_usd,
                                                                                               lift.max_position_usd))):
        raise MainnetRefused("the lift's sizes do not read: 0 < largest order <= largest position")
    here = machine if machine is not None else machine_hash()
    if lift.machine != here:
        raise MainnetRefused("this is not the machine the lift names")
    return lift


@dataclass(frozen=True)
class Allowed:
    coin: str
    max_order_usd: float
    max_position_usd: float


def read_allowlist(root: Path = ROOT) -> Tuple[Dict[str, Allowed], str]:
    """Guard 4's file: rows of coin and sizes on this venue, at HEAD, signed. Returns the rows and their commit."""
    rel = ALLOWLIST.as_posix()
    if not at_head_unchanged(root, rel):
        raise MainnetRefused(f"{rel} is not at HEAD, or has uncommitted edits")
    commit = last_commit(root, rel)
    if not verified(root, commit):
        raise MainnetRefused(f"{rel}'s commit {commit[:12] or '?'} does not verify against the allowed signers")
    try:
        doc = json.loads((Path(root) / rel).read_text(encoding="utf-8"))
        rows = {}
        for r in doc["rows"]:
            if str(r["venue"]).lower() != VENUE:
                continue
            a = Allowed(str(r["coin"]).upper(), float(r["max_order_usd"]), float(r["max_position_usd"]))
            if not (0 < a.max_order_usd <= a.max_position_usd and math.isfinite(a.max_position_usd)):
                raise ValueError(f"{a.coin}: 0 < order <= position")
            rows[a.coin] = a
    except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
        raise MainnetRefused(f"{rel} does not read: {exc}") from None
    return rows, commit


def guard_env(env: dict) -> None:
    """Guards 1 and 2."""
    if (env.get("HL_NETWORK") or "").strip().lower() != "mainnet":
        raise MainnetRefused("HL_NETWORK must be 'mainnet' to build the mainnet exchange")
    if (env.get("ESPERO_ALLOW_HL_MAINNET") or "").strip() != "1":
        raise MainnetRefused("set ESPERO_ALLOW_HL_MAINNET=1 to allow mainnet orders")


def guard_key(env: dict) -> str:
    """Guard 6: the key, read last, never under CI."""
    if (env.get("CI") or "").strip():
        raise MainnetRefused("CI is set: no mainnet key is read under CI")
    override = (env.get("HL_API_URL") or "").strip()
    if override and urllib.parse.urlparse(override).hostname != MAINNET_HOST:
        raise MainnetRefused(f"HL_API_URL={override!r} is not {MAINNET_HOST}; refusing")
    key = (env.get("HL_MAINNET_PRIVATE_KEY") or "").strip()
    if not key:
        raise MainnetRefused("HL_MAINNET_PRIVATE_KEY is empty: an API wallet that cannot withdraw (docs/API_KEYS.md)")
    return key


def holder_limits(root: Path = ROOT) -> Dict[str, Optional[float]]:
    """The holder's own figures the mainnet path enforces beside the policy: the drawdown stop for risk.Account's
    holder_stop, and the most one venue may hold."""
    a = holder.answers(Path(root) / "docs" / "HOLDER_INPUTS.md")
    return {"holder_stop": a["stop_drawdown"], "venue_loss_usd": a["venue_loss_usd"]}


# ------------------------------------------------------------------------------------------------------ exchange
class MainnetExchange:
    """`hl_exchange.TestnetExchange`'s methods on mainnet, behind every guard above. Dry run unless asked.

    `exchange` / `info` can be injected (tests): then no key is read and nothing is built, but guards 1 to 5 still
    run. `meta` is {coin: szDecimals}. `now` and `today` are injectable clocks, `positions` the account's state."""

    def __init__(self, env: Optional[dict] = None, root: Path = ROOT, state: Optional[Path] = None,
                 dry_run: bool = True, exchange=None, info=None, meta: Optional[Dict[str, int]] = None,
                 address: Optional[str] = None, today: Optional[date] = None, machine: Optional[str] = None,
                 now: Callable[[], float] = time.time, positions: Optional[Callable[[], dict]] = None):
        env = dict(os.environ) if env is None else env
        guard_env(env)
        self.root = Path(root)
        self.lift = read_lift(self.root, today, machine)
        self.allowed, self.allow_commit = read_allowlist(self.root)
        self.dry_run = dry_run
        self.now = now
        self.state = Path(state) if state is not None else self.root / "state"
        self.state.mkdir(parents=True, exist_ok=True)
        self.limits = holder_limits(self.root)
        self.db = sqlite3.connect(self.state / (DRY_DB if dry_run else LIVE_DB))
        self.db.execute(SCHEMA)
        self.db.commit()
        if not dry_run and exchange is None:
            key = guard_key(env)
            from eth_account import Account
            from hyperliquid.exchange import Exchange
            from hyperliquid.info import Info
            wallet = Account.from_key(key)
            account = address or account_address(env) or wallet.address
            exchange = Exchange(wallet, base_url=MAINNET_URL,
                                account_address=account if account.lower() != wallet.address.lower() else None)
            info = info or Info(base_url=MAINNET_URL, skip_ws=True)
            address = account
            if getattr(exchange, "base_url", None) != MAINNET_URL:
                raise MainnetRefused("the exchange is not on the mainnet constant; refusing")
        # the testnet wrapper's methods, unchanged, on whatever client was built or injected: they only call
        # self.ex and self.info, and build nothing when a client is given
        self.venue = TestnetExchange(exchange=exchange, info=info, meta=meta, address=address) \
            if (exchange is not None or info is not None or meta is not None) else None
        self.address = address or ""
        self._positions = positions

    # -------------------------------------------------------------- the kill switch
    def kill_state(self) -> str:
        """'' when there is no KILL file; 'flatten' when it reads flatten; 'kill' otherwise."""
        p = self.state / KILL
        if not p.exists():
            return ""
        try:
            return "flatten" if p.read_text().strip().lower() == "flatten" else "kill"
        except OSError:
            return "kill"

    # -------------------------------------------------------------- checks every order passes
    def held_usd(self, coin: Optional[str] = None) -> float:
        """Gross notional held on the venue now, in one coin or all; 0 in a dry run with no venue client."""
        if self.venue is None and self._positions is None:
            return 0.0
        st = self.positions()
        return sum(abs(float(p.get("notional", 0.0) or 0.0)) for p in st.get("positions", [])
                   if coin is None or p.get("coin") == coin)

    def refuse_order(self, coin: str, side: str, size: float, price: float, reduce_only: bool,
                     ruling: Optional[risk.Ruling]) -> Optional[str]:
        """Why this order may not be sent, or None. Reduce-only orders pass the kill switch and the size caps."""
        if side not in ("buy", "sell"):
            return "side must be buy or sell"
        if not (math.isfinite(size) and math.isfinite(price)) or size <= 0 or price <= 0:
            return "size and price must be positive numbers"
        notional = size * price
        if reduce_only:
            return None
        if self.kill_state():
            return f"the {KILL} file is present: reduce-only orders only"
        if coin.upper() not in self.lift.coins:
            return f"{coin} is not among the lift's coins"
        a = self.allowed.get(coin.upper())
        if a is None:
            return f"{coin} is not on the allow-list"
        largest = min(a.max_order_usd, self.lift.max_order_usd)
        if notional > largest + 1e-9:
            return f"${notional:,.2f} is above the largest order (${largest:,.2f})"
        after = self.held_usd(coin) + notional
        if after > min(a.max_position_usd, self.lift.max_position_usd) + 1e-9:
            return f"${after:,.2f} in {coin} would be above the largest position"
        venue_cap = self.limits.get("venue_loss_usd")
        if venue_cap is not None and self.held_usd() + notional > venue_cap + 1e-9:
            return f"the venue would hold more than the holder's ${venue_cap:,.2f} (venue_loss_usd)"
        if ruling is None:
            return "no ruling from the risk gate"
        if not ruling.allowed:
            return "the risk gate refused: " + "; ".join(ruling.reasons)
        if ruling.policy_hash != risk.policy_hash():
            return "the ruling was made under a different policy than HEAD's"
        if notional > ruling.notional + 1e-9:
            return f"${notional:,.2f} is above the ruling's ${ruling.notional:,.2f}"
        return None

    def _journal(self, mode: str, coin: str, side: str, size: float, price: float, tif: str, reduce_only: bool,
                 cloid: Optional[str], ruling: Optional[risk.Ruling], res: OrderResult) -> None:
        self.db.execute(
            "INSERT INTO mainnet_orders (ts, mode, coin, side, size, price, tif, reduce_only, cloid, notional, "
            "policy_hash, lift_commit, allow_commit, status, oid, filled, avg_px, error) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (int(self.now()), mode, coin, side, size, price, tif, int(reduce_only), cloid, size * price,
             ruling.policy_hash if ruling else None, self.lift.commit, self.allow_commit,
             res.status, res.oid, res.filled, res.avg_px, res.error))
        self.db.commit()

    # -------------------------------------------------------------- orders
    def limit(self, coin: str, side: str, size: float, price: float, tif: str = "Alo", reduce_only: bool = False,
              cloid: Optional[str] = None, ruling: Optional[risk.Ruling] = None,
              sz_decimals: Optional[int] = None) -> OrderResult:
        """An order checked against every guard; journaled whatever happens. A refusal returns status 'refused'."""
        sd = sz_decimals if sz_decimals is not None else (self.venue.meta.get(coin) if self.venue else None)
        sane = side in ("buy", "sell") and all(isinstance(v, (int, float)) and math.isfinite(v) and v > 0
                                               for v in (size, price))
        sz = round_size(size, sd) if sane and sd is not None else size
        px = round_price(price, sd, side) if sane and sd is not None else price
        why = self.refuse_order(coin, side, sz, px, reduce_only, ruling)
        mode = "dry" if self.dry_run else "live"
        if why is not None:
            res = OrderResult(coin, side, sz, px, tif, "refused", None, 0.0, None, why)
        elif self.dry_run:
            res = OrderResult(coin, side, sz, px, tif, "dry", None, 0.0, None, None)
        else:
            if sz <= 0 or px <= 0:
                res = OrderResult(coin, side, sz, px, tif, "refused", None, 0.0, None, "rounds to zero")
            else:
                kw = {"cloid": _cloid(cloid)} if cloid else {}
                resp = self.venue.ex.order(coin, side == "buy", sz, px, {"limit": {"tif": tif}},
                                           reduce_only=reduce_only, **kw)
                res = OrderResult(coin, side, sz, px, tif, **parse_order_response(resp))
        self._journal(mode, coin, side, sz, px, tif, reduce_only, cloid, ruling, res)
        return res

    def _need_venue(self):
        if self.venue is None:
            raise MainnetRefused("a dry run with no venue client cannot read the venue")
        return self.venue

    def order_status(self, cloid: str) -> dict:
        return self._need_venue().order_status(cloid)

    def book(self, coin: str) -> Tuple[float, float]:
        return self._need_venue().book(coin)

    def cancel(self, coin: str, oid: int) -> bool:
        if self.dry_run:
            return True
        return self._need_venue().cancel(coin, oid)

    def open_orders(self) -> List[dict]:
        return self._need_venue().open_orders()

    def fills(self, since_ts: int = 0) -> List[dict]:
        return self._need_venue().fills(since_ts)

    def positions(self) -> dict:
        """The account's mainnet clearinghouse state, read from mainnet's public info endpoint."""
        from . import hyperliquid as hl

        if self._positions is not None:
            return self._positions()
        self._need_venue()
        return hl.user_state(self.address, fetch=lambda body: hl.post(body, url=MAINNET_URL + "/info"))

    # -------------------------------------------------------------- the kill switch's two actions
    def cancel_all(self) -> int:
        """Cancel every resting order; the number cancelled."""
        n = 0
        for o in self.open_orders():
            if self.cancel(o["coin"], int(o["oid"])):
                n += 1
        return n

    def flatten(self, tranche_slips: Sequence[float] = EXIT_SLIPS, tries: int = 8,
                sleep: Callable[[float], None] = time.sleep) -> List[OrderResult]:
        """Close every position with reduce-only IOC orders, each unfilled try crossing further; returns the tries."""
        out: List[OrderResult] = []
        self.cancel_all()
        for k in range(tries):
            held = [p for p in self.positions().get("positions", []) if float(p.get("size", 0) or 0) != 0]
            if not held:
                break
            slip = tranche_slips[min(k, len(tranche_slips) - 1)]
            for p in held:
                size = abs(float(p["size"]))
                side = "sell" if float(p["size"]) > 0 else "buy"
                bid, ask = self.book(p["coin"])
                px = bid * (1 - slip) if side == "sell" else ask * (1 + slip)
                out.append(self.limit(p["coin"], side, size, px, tif="Ioc", reduce_only=True))
            sleep(min(30.0, 2.0 ** k))
        return out
