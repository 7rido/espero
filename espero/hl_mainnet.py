"""Hyperliquid **mainnet** order path, built from research/DESIGN_MAINNET_PATH.md after the holder's signed lift.

The no-mainnet rule was lifted by the holder in research/MAINNET_LIFT.md (commits cf109df and 88cd069, signed with
the holder's key). This module exists only under that lift, and refuses unless every guard passes, in this order,
when an exchange is built **and again before every order that is not reduce-only**:

1. `HL_NETWORK` is `mainnet`, so this module and the testnet's can never be built from one environment.
2. `ESPERO_ALLOW_HL_MAINNET=1`, a second opt-in distinct from the testnet's.
3. The holder's lift: `docs/HOLDER_INPUTS.md`, as HEAD holds it and itself signed, names a file; that file is at
   HEAD and unchanged on disk; its last commit carries an SSH signature that `git verify-commit` accepts against the
   allowed-signers file at `SIGNERS`, a fixed path outside the repository; its block names this venue, an expiry not
   yet past (UTC), a rule, who approves, and this machine's hash.
4. The allow-list, `config/mainnet_allowlist.json`, at HEAD, unchanged, its last commit verified the same way; every
   order's coin and size are checked against it and against the lift.
5. Every order carries a `risk.Ruling` made for that order (venue, coin, side, the lift's rule), used once, that
   allowed it, at most its notional, under the policy committed at HEAD.
6. Live only: the key, `HL_MAINNET_PRIVATE_KEY`, read here and nowhere else, after 1 to 5; never when `CI` is set.
7. Live only: the base URL is a constant and is asserted after the SDK is built.

How git is asked (2026-11-09 audit, M3 and M5): with every `GIT_*` variable removed from the environment, replace
refs ignored, the signature programs and the signers file given on the command line, so nothing in `.git/config` or
the environment chooses what is trusted. A file's last commit is read with `--full-history`, so a merge that brings
an older signed version back is itself the last commit, and is unsigned. The newest lift, allow-list and holder page
this machine has accepted are remembered in the state folder (`mainnet-anchor.json`); a checkout of an older one is
refused.

Dry run is the default: guards 1 to 5 run, the order is checked, and the exact order that would have been sent is
journaled to `state/mainnet-dryrun.db`. No key is read and no signer is built.

Dollar caps count what is held, what rests unfilled on the venue, and the order, each at the larger of its limit
price and the venue's bid, so a sell priced far below the market counts at the market.

The kill switch is the state folder's `KILL` file, read before every order: while it exists only reduce-only orders
pass and resting orders are cancelled; when it reads `flatten`, `flatten()` closes every position with reduce-only
IOC orders crossing further on each unfilled try (`hlp_testnet.EXIT_SLIPS`), and raises `NotFlat` if it could not.
"""
from __future__ import annotations

import json
import math
import os
import secrets
import shutil
import sqlite3
import subprocess
import time
import urllib.parse
from dataclasses import dataclass
from datetime import date, datetime, timezone
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
PAGE = "docs/HOLDER_INPUTS.md"
SIGNERS = Path.home() / ".config" / "espero" / "allowed_signers"   # the holder's, outside every checkout
DRY_DB = "mainnet-dryrun.db"
LIVE_DB = "mainnet-orders.db"
ANCHOR = "mainnet-anchor.json"
KILL = "KILL"

SCHEMA = """CREATE TABLE IF NOT EXISTS mainnet_orders (
    id INTEGER PRIMARY KEY AUTOINCREMENT, ts INTEGER NOT NULL, mode TEXT NOT NULL,
    coin TEXT, side TEXT, size REAL, price REAL, tif TEXT, reduce_only INTEGER, cloid TEXT, notional REAL,
    policy_hash TEXT, lift_commit TEXT, allow_commit TEXT,
    status TEXT, oid INTEGER, filled REAL, avg_px REAL, error TEXT
);"""


class MainnetRefused(RuntimeError):
    """Raised, never caught in this module, when a guard does not pass. The message says which."""


class NotFlat(RuntimeError):
    """`flatten()` ran out of tries with positions still open. `.tries` holds every order it sent."""

    def __init__(self, coins: Sequence[str], tries: List[OrderResult]):
        super().__init__(f"not flat after every try: {', '.join(coins)} still held; the operator is needed")
        self.tries = tries


# ----------------------------------------------------------------------------------------------- git and the lift
def _git(root: Path, *args: str, text: bool = True) -> subprocess.CompletedProcess:
    """git asked so that only the repository's objects answer: no `GIT_*` variable (GIT_DIR, GIT_CONFIG_*) reaches
    it, and replace refs are ignored."""
    env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
    env["GIT_NO_REPLACE_OBJECTS"] = "1"
    return subprocess.run(["git", "--no-replace-objects", "-C", str(root), *args], capture_output=True, text=text,
                          timeout=60, env=env)


def at_head_unchanged(root: Path, rel: str) -> bool:
    """The file is in HEAD and the copy on disk is byte for byte HEAD's."""
    r = _git(root, "show", f"HEAD:{rel}", text=False)
    p = Path(root) / rel
    return r.returncode == 0 and p.is_file() and not p.is_symlink() and r.stdout == p.read_bytes()


def last_commit(root: Path, rel: str) -> str:
    """The last commit that touched the file, merges included: a merge that restores an older version is the last."""
    r = _git(root, "log", "-1", "--full-history", "--format=%H", "--", rel)
    return r.stdout.strip() if r.returncode == 0 else ""


def signers_file(root: Path, signers: Optional[Path] = None) -> Optional[Path]:
    """The allowed-signers file, when it is an absolute path to a file outside the repository. The path is this
    module's constant, never git's configuration: `.git/config` is writable by anything that can commit."""
    p = Path(SIGNERS if signers is None else signers)
    if not p.is_absolute():
        return None
    p = p.resolve()
    try:
        p.relative_to(Path(root).resolve())
        return None                     # inside the repo: anything that can commit could rewrite it
    except ValueError:
        pass
    return p if p.is_file() else None


def _ssh_keygen() -> str:
    return "/usr/bin/ssh-keygen" if Path("/usr/bin/ssh-keygen").exists() else (shutil.which("ssh-keygen") or "false")


def verified(root: Path, commit: str, signers: Optional[Path] = None) -> bool:
    """The commit carries an SSH signature that verifies against the allowed-signers file. Every program and file
    git uses for it is named here, on the command line, where it outranks any configuration."""
    sf = signers_file(root, signers)
    if not commit or sf is None:
        return False
    raw = _git(root, "cat-file", "commit", commit)
    header = raw.stdout.split("\n\n", 1)[0] if raw.returncode == 0 else ""
    if "\ngpgsig -----BEGIN SSH SIGNATURE-----" not in "\n" + header:
        return False                    # unsigned, or signed some other way (a PGP keyring is not the signers file)
    r = _git(root, "-c", f"gpg.ssh.allowedSignersFile={sf}", "-c", f"gpg.ssh.program={_ssh_keygen()}",
             "-c", "gpg.program=false", "-c", "gpg.openpgp.program=false", "-c", "gpg.x509.program=false",
             "-c", "gpg.ssh.revocationFile=", "verify-commit", commit)
    return r.returncode == 0 and 'Good "git" signature' in (r.stderr or "")


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
    rule: str = ""
    approval: str = ""


def utc_today() -> date:
    return datetime.now(timezone.utc).date()


def read_lift(root: Path = ROOT, today: Optional[date] = None, machine: Optional[str] = None,
              signers: Optional[Path] = None) -> Lift:
    """Guard 3: the holder's committed, signed, unexpired lift for this venue and this machine."""
    from .holderform import lift_answers, machine_hash

    page = Path(root) / PAGE
    if not at_head_unchanged(root, PAGE):
        raise MainnetRefused(f"{PAGE} is not what HEAD holds: an answer counts only once committed")
    page_commit = last_commit(root, PAGE)
    if not verified(root, page_commit, signers):   # it names the lift and gives the venue limit: the holder's only
        raise MainnetRefused(f"{PAGE}'s commit {page_commit[:12] or '?'} does not verify against the allowed signers")
    rel = holder.answers(page)["mainnet_lift"]
    if not rel:
        raise MainnetRefused(f"no lift: {PAGE} names no mainnet_lift")
    if not at_head_unchanged(root, rel):
        raise MainnetRefused(f"the lift {rel} is not at HEAD, or has uncommitted edits")
    commit = last_commit(root, rel)
    if not verified(root, commit, signers):
        raise MainnetRefused(f"the lift's commit {commit[:12] or '?'} does not verify against the allowed signers")
    f = lift_answers((Path(root) / rel).read_text(encoding="utf-8"))
    try:
        lift = Lift(rel, commit, f["venue"].strip().lower(),
                    tuple(c.strip().upper() for c in f["coins"].split(",") if c.strip()),
                    float(f["max_order_usd"]), float(f["max_position_usd"]),
                    date.fromisoformat(f["expiry"].strip()), f["machine"].strip(),
                    f["rule"].strip().lstrip("#"), f["approval"].strip())
    except (KeyError, ValueError) as exc:
        raise MainnetRefused(f"the lift's block does not read: {exc}") from None
    if lift.venue != VENUE:
        raise MainnetRefused(f"the lift covers {lift.venue}, not {VENUE}")
    if (today or utc_today()) > lift.expiry:
        raise MainnetRefused(f"the lift lapsed on {lift.expiry}")
    if not (0 < lift.max_order_usd <= lift.max_position_usd) or not all(map(math.isfinite, (lift.max_order_usd,
                                                                                               lift.max_position_usd))):
        raise MainnetRefused("the lift's sizes do not read: 0 < largest order <= largest position")
    if not lift.rule or not lift.approval:
        raise MainnetRefused("the lift does not say which rule it covers and who approves each trade")
    here = machine if machine is not None else machine_hash()
    if lift.machine != here:
        raise MainnetRefused("this is not the machine the lift names")
    return lift


@dataclass(frozen=True)
class Allowed:
    coin: str
    max_order_usd: float
    max_position_usd: float


def read_allowlist(root: Path = ROOT, signers: Optional[Path] = None) -> Tuple[Dict[str, Allowed], str]:
    """Guard 4's file: rows of coin and sizes on this venue, at HEAD, signed. Returns the rows and their commit."""
    rel = ALLOWLIST.as_posix()
    if not at_head_unchanged(root, rel):
        raise MainnetRefused(f"{rel} is not at HEAD, or has uncommitted edits")
    commit = last_commit(root, rel)
    if not verified(root, commit, signers):
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


def policy_at_head() -> bool:
    """The risk gate this process runs is the one its checkout has committed: a ruling's policy hash is compared
    with this module's own, which says nothing if espero/risk.py was edited and not committed."""
    return at_head_unchanged(Path(risk.__file__).resolve().parents[1], "espero/risk.py")


def check_anchor(root: Path, state: Path, commits: Dict[str, str]) -> None:
    """Refuse a lift, allow-list or holder page older than one this machine has already accepted (a checkout of an
    earlier signed version would otherwise undo a later, tighter one), then remember the ones accepted now."""
    path = Path(state) / ANCHOR
    seen: Dict[str, str] = {}
    if path.exists():
        try:
            seen = {str(k): str(v) for k, v in json.loads(path.read_text(encoding="utf-8")).items()}
        except (OSError, ValueError, AttributeError):
            raise MainnetRefused(f"{path} does not read; the holder removes it after checking the lift") from None
    for name, now in commits.items():
        old = seen.get(name)
        if old and old != now and _git(root, "merge-base", "--is-ancestor", old, now).returncode != 0:
            raise MainnetRefused(f"the {name} at {now[:12]} is not the one accepted here before ({old[:12]}) or a "
                                 f"later one; if the holder rewrote history on purpose, the holder removes {path}")
    if seen != {**seen, **commits}:
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps({**seen, **commits}, indent=1), encoding="utf-8")
        os.replace(tmp, path)


def _wrap(exchange, info, meta: Optional[Dict[str, int]], address: Optional[str]) -> TestnetExchange:
    """The testnet wrapper's methods on a client that is already built (or absent, in a dry run), without running
    the testnet's own guard: nothing here may read the testnet's key or build its signer."""
    w = TestnetExchange.__new__(TestnetExchange)
    w.ex, w.info, w.address, w._meta = exchange, info, address or "", meta
    return w


# ------------------------------------------------------------------------------------------------------ exchange
class MainnetExchange:
    """`hl_exchange.TestnetExchange`'s methods on mainnet, behind every guard above. Dry run unless asked.

    `exchange` / `info` can be injected (tests): then no key is read and nothing is built, but guards 1 to 5 still
    run. `meta` is {coin: szDecimals}. `now` and `today` are injectable clocks, `positions` the account's state,
    `signers` the allowed-signers file (tests; the default is `SIGNERS`), `policy_committed` the check that the
    running risk gate is HEAD's."""

    def __init__(self, env: Optional[dict] = None, root: Path = ROOT, state: Optional[Path] = None,
                 dry_run: bool = True, exchange=None, info=None, meta: Optional[Dict[str, int]] = None,
                 address: Optional[str] = None, today: Optional[date] = None, machine: Optional[str] = None,
                 now: Callable[[], float] = time.time, positions: Optional[Callable[[], dict]] = None,
                 signers: Optional[Path] = None, policy_committed: Callable[[], bool] = policy_at_head):
        env = dict(os.environ) if env is None else env
        self.env = {k: env.get(k) for k in ("HL_NETWORK", "ESPERO_ALLOW_HL_MAINNET")}
        self.root = Path(root)
        self._today, self._machine, self._signers = today, machine, signers
        self._policy_committed = policy_committed
        if state is not None:
            self.state = Path(state)
        elif self.root == ROOT:
            from .cli import state_dir  # where the home screen writes KILL, not always the repo's state/
            self.state = Path(state_dir())
        else:
            self.state = self.root / "state"
        self.guards(remember=False)
        self.dry_run = dry_run
        self.now = now
        self.state.mkdir(parents=True, exist_ok=True)
        self._remember()
        self.db = sqlite3.connect(self.state / (DRY_DB if dry_run else LIVE_DB))
        self.db.execute(SCHEMA)
        self.db.commit()
        self._spent: List[risk.Ruling] = []
        if not dry_run and exchange is None:
            key = guard_key(env)
            account = address or account_address(env)
            if not account:   # positions are read for this address: a wrong one makes every cap blind
                raise MainnetRefused("HL_WALLET_ADDRESS is not set or is not an address: the account the API "
                                     "wallet trades for must be named")
            from eth_account import Account
            from hyperliquid.exchange import Exchange
            from hyperliquid.info import Info
            wallet = Account.from_key(key)
            exchange = Exchange(wallet, base_url=MAINNET_URL,
                                account_address=account if account.lower() != wallet.address.lower() else None)
            info = info or Info(base_url=MAINNET_URL, skip_ws=True)
            address = account
            if getattr(exchange, "base_url", None) != MAINNET_URL:
                raise MainnetRefused("the exchange is not on the mainnet constant; refusing")
        self.venue = _wrap(exchange, info, meta, address) \
            if (exchange is not None or info is not None or meta is not None) else None
        self.address = address or ""
        self._positions = positions

    def guards(self, remember: bool = True) -> None:
        """Guards 1 to 4 and the holder's venue limit, read afresh: at start, and before every order that is not
        reduce-only, so a lift withdrawn, tightened or lapsed stops a process that is already running."""
        guard_env(self.env)
        self.lift = read_lift(self.root, self._today, self._machine, self._signers)
        self.allowed, self.allow_commit = read_allowlist(self.root, self._signers)
        self.limits = holder_limits(self.root)
        cap = self.limits.get("venue_loss_usd")
        if cap is None or not math.isfinite(cap) or cap <= 0:
            raise MainnetRefused(f"{PAGE}'s venue_loss_usd is unanswered or does not read: no venue limit, no order")
        if remember:
            self._remember()

    def _remember(self) -> None:
        check_anchor(self.root, self.state, {"lift": self.lift.commit, "allow-list": self.allow_commit,
                                             "holder page": last_commit(self.root, PAGE)})

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
    def _reads_venue(self) -> bool:
        return self._positions is not None or (self.venue is not None and self.venue.info is not None)

    def held_usd(self, coin: Optional[str] = None) -> float:
        """Gross notional held on the venue now, in one coin or all; 0 in a dry run with no venue client."""
        if not self._reads_venue():
            return 0.0
        total = 0.0
        for p in self.positions().get("positions", []):
            if coin is not None and p.get("coin") != coin:
                continue
            n = p.get("notional")
            if n is None:   # a row without its value is sized from its entry, never counted as nothing
                n = float(p.get("size", 0) or 0) * float(p.get("entry", 0) or 0)
            total += abs(float(n or 0.0))
        return total

    def resting_usd(self, coin: Optional[str] = None) -> float:
        """What rests unfilled on the venue, at its limit prices: it becomes a position without another check."""
        if self.venue is None or self.venue.info is None:
            return 0.0
        return sum(abs(float(o.get("sz", 0) or 0) * float(o.get("limitPx", 0) or 0)) for o in self.open_orders()
                   if coin is None or o.get("coin") == coin)

    def _exposure(self, coin: str, side: str, size: float, price: float) -> float:
        """The order's dollars for every cap: at its limit price, or at the venue's bid when a sell is priced below
        it (it would fill at the market, not at its limit). ValueError when the book cannot be read."""
        if side == "sell" and self.venue is not None and self.venue.info is not None:
            bid, _ask = self.book(coin)
            return size * max(price, bid)
        return size * price

    def refuse_order(self, coin: str, side: str, size: float, price: float, reduce_only: bool,
                     ruling: Optional[risk.Ruling]) -> Optional[str]:
        """Why this order may not be sent, or None. Reduce-only orders pass the kill switch and the size caps."""
        if side not in ("buy", "sell"):
            return "side must be buy or sell"
        if not (math.isfinite(size) and math.isfinite(price)) or size <= 0 or price <= 0:
            return "size and price must be positive numbers"
        if reduce_only:
            return None
        if self.kill_state():
            return f"the {KILL} file is present: reduce-only orders only"
        try:
            self.guards()
        except MainnetRefused as exc:
            return f"a guard no longer passes: {exc}"
        if coin.upper() not in self.lift.coins:
            return f"{coin} is not among the lift's coins"
        a = self.allowed.get(coin.upper())
        if a is None:
            return f"{coin} is not on the allow-list"
        try:
            notional = self._exposure(coin, side, size, price)
            held_coin, held_all = self.held_usd(coin), self.held_usd()
            rest_coin, rest_all = self.resting_usd(coin), self.resting_usd()
        except Exception as exc:  # noqa: BLE001 - the venue could not be read: no cap can be checked, so no order
            return f"the venue could not be read for the caps ({type(exc).__name__}: {exc})"
        largest = min(a.max_order_usd, self.lift.max_order_usd)
        if notional > largest + 1e-9:
            return f"${notional:,.2f} is above the largest order (${largest:,.2f})"
        after = held_coin + rest_coin + notional
        if after > min(a.max_position_usd, self.lift.max_position_usd) + 1e-9:
            return f"${after:,.2f} in {coin}, held and resting, would be above the largest position"
        venue_cap = self.limits["venue_loss_usd"]
        if held_all + rest_all + notional > venue_cap + 1e-9:
            return f"the venue would hold more than the holder's ${venue_cap:,.2f} (venue_loss_usd)"
        if ruling is None:
            return "no ruling from the risk gate"
        if not ruling.allowed:
            return "the risk gate refused: " + "; ".join(ruling.reasons)
        if ruling.policy_hash != risk.policy_hash() or not self._policy_committed():
            return "the ruling was made under a different policy than HEAD's"
        o = ruling.order
        if o is None:
            return "the ruling names no order: it must come from risk.check for this order"
        if (o.venue, o.coin.upper(), o.side, o.reduce_only) != (VENUE, coin.upper(), 1 if side == "buy" else -1, False):
            return "the ruling was made for another order (venue, coin or side)"
        if str(o.rule).lstrip("#") != self.lift.rule:
            return f"the ruling is for rule {o.rule}; the lift covers rule {self.lift.rule}"
        if any(r is ruling for r in self._spent):
            return "the ruling was already used for an order"
        if notional > ruling.notional + 1e-9:
            return f"${notional:,.2f} is above the ruling's ${ruling.notional:,.2f}"
        return None

    def _journal(self, mode: str, coin: str, side: str, size: float, price: float, tif: str, reduce_only: bool,
                 cloid: Optional[str], ruling: Optional[risk.Ruling], res: OrderResult) -> int:
        cur = self.db.execute(
            "INSERT INTO mainnet_orders (ts, mode, coin, side, size, price, tif, reduce_only, cloid, notional, "
            "policy_hash, lift_commit, allow_commit, status, oid, filled, avg_px, error) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (int(self.now()), mode, coin, side, size, price, tif, int(reduce_only), cloid, size * price,
             ruling.policy_hash if ruling else None, self.lift.commit, self.allow_commit,
             res.status, res.oid, res.filled, res.avg_px, res.error))
        self.db.commit()
        return int(cur.lastrowid)

    def _settle(self, row: int, res: OrderResult) -> None:
        self.db.execute("UPDATE mainnet_orders SET status=?, oid=?, filled=?, avg_px=?, error=? WHERE id=?",
                        (res.status, res.oid, res.filled, res.avg_px, res.error, row))
        self.db.commit()

    # -------------------------------------------------------------- orders
    def limit(self, coin: str, side: str, size: float, price: float, tif: str = "Alo", reduce_only: bool = False,
              cloid: Optional[str] = None, ruling: Optional[risk.Ruling] = None,
              sz_decimals: Optional[int] = None) -> OrderResult:
        """An order checked against every guard; journaled whatever happens. A refusal returns status 'refused'.
        A live order is journaled as 'sending' with its client id before it leaves; if the venue's answer never
        comes, it stays as 'unknown' with that id, to be looked up (`order_status`) before anything is sent again."""
        if self.kill_state() and not self.dry_run and self.venue is not None and self.venue.info is not None:
            try:
                self.cancel_all()       # under KILL nothing rests: a resting entry could still fill
            except Exception:  # noqa: BLE001 - the cancel is best effort; the order below is still checked
                pass
        sd = sz_decimals if sz_decimals is not None else (self.venue.meta.get(coin) if self.venue else None)
        sane = side in ("buy", "sell") and all(isinstance(v, (int, float)) and math.isfinite(v) and v > 0
                                               for v in (size, price))
        sz = round_size(size, sd) if sane and sd is not None else size
        px = round_price(price, sd, side) if sane and sd is not None else price
        why = self.refuse_order(coin, side, sz, px, reduce_only, ruling)
        if why is None and sane and (sz <= 0 or px <= 0):
            why = "rounds to zero"
        mode = "dry" if self.dry_run else "live"
        if why is not None:
            res = OrderResult(coin, side, sz, px, tif, "refused", None, 0.0, None, why)
            self._journal(mode, coin, side, sz, px, tif, reduce_only, cloid, ruling, res)
            return res
        if ruling is not None and not reduce_only:
            self._spent.append(ruling)  # kept, so the same ruling is known by identity for the process's life
        if self.dry_run or self.venue is None or self.venue.ex is None:
            res = OrderResult(coin, side, sz, px, tif, "dry", None, 0.0, None, None)
            self._journal("dry", coin, side, sz, px, tif, reduce_only, cloid, ruling, res)
            return res
        cloid = cloid or "0x" + secrets.token_hex(16)
        row = self._journal(mode, coin, side, sz, px, tif, reduce_only, cloid, ruling,
                            OrderResult(coin, side, sz, px, tif, "sending", None, 0.0, None, None))
        try:
            resp = self.venue.ex.order(coin, side == "buy", sz, px, {"limit": {"tif": tif}},
                                       reduce_only=reduce_only, cloid=_cloid(cloid))
            res = OrderResult(coin, side, sz, px, tif, **parse_order_response(resp))
        except Exception as exc:  # noqa: BLE001 - it may have reached the venue: recorded, never silently retried
            res = OrderResult(coin, side, sz, px, tif, "unknown", None, 0.0, None,
                              f"no answer from the venue ({type(exc).__name__}): look it up by client id {cloid}")
        self._settle(row, res)
        return res

    def _need_venue(self):
        if self.venue is None or self.venue.info is None:
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
        """Close every position with reduce-only IOC orders, each unfilled try crossing further; returns the tries.
        One coin's failure never stops the others, and positions still open after the last try raise `NotFlat`."""
        out: List[OrderResult] = []
        try:
            self.cancel_all()
        except Exception:  # noqa: BLE001 - closing matters more than the cancel that could not be made
            pass

        def open_now() -> List[dict]:
            return [p for p in self.positions().get("positions", []) if float(p.get("size", 0) or 0) != 0]

        for k in range(tries):
            held = open_now()
            if not held:
                return out
            slip = tranche_slips[min(k, len(tranche_slips) - 1)]
            for p in held:
                size = abs(float(p["size"]))
                side = "sell" if float(p["size"]) > 0 else "buy"
                try:
                    bid, ask = self.book(p["coin"])
                    px = bid * (1 - slip) if side == "sell" else ask * (1 + slip)
                    out.append(self.limit(p["coin"], side, size, px, tif="Ioc", reduce_only=True))
                except Exception as exc:  # noqa: BLE001 - this coin failed this try; the others still close
                    out.append(OrderResult(p["coin"], side, size, 0.0, "Ioc", "error", None, 0.0, None,
                                           f"{type(exc).__name__}: {exc}"))
            sleep(min(30.0, 2.0 ** k))
        left = open_now()
        if left:
            raise NotFlat(sorted({p["coin"] for p in left}), out)
        return out
