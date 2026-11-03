"""Live attribution: per sleeve, venue and day, what the fills cost against their decision prices, fees, funding, and
the gap to the paper twin; and the venue's own equity against the journal's, a break pausing new entries.

Pure where it can be: fills and funding in, rows out. The twin's numbers are an input, and they are given only from a
sleeve's verdict on (research/DEPLOYMENT_LADDER.md, rung 0): before it, a forward book's running numbers decide
nothing and are not read. The venue's record is Hyperliquid's public `clearinghouseState`, read by address with no
key, or an exchange's read-only statement through an adapter that maps onto `Fill`. A break between the two writes
`<state>/<sleeve>.pause`, which the risk gate reads as `Account.paused`, and notifies.
"""
from __future__ import annotations

import json
import sqlite3
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Dict, Iterable, List, Optional, Sequence, Tuple

EQUITY_TOL_USD = 1.0           # a break is a gap above the larger of a dollar ...
EQUITY_TOL_FRAC = 0.001        # ... and 0.1 % of the venue's equity
PAUSE = ".pause"


@dataclass(frozen=True)
class Fill:
    sleeve: str
    venue: str
    coin: str
    ts: int                     # unix seconds
    side: int                   # +1 bought, -1 sold
    qty: float
    px: float
    fee: float                  # USD paid (a rebate is negative)
    decision_px: float          # the price the rule decided at: the slippage is measured against it
    trade: str                  # the round trip it belongs to
    liquidity: str = "taker"

    @property
    def notional(self) -> float:
        return abs(self.qty) * self.px


@dataclass(frozen=True)
class FundingPayment:
    sleeve: str
    venue: str
    coin: str
    ts: int
    usd: float                  # received is positive, paid negative
    trade: str = ""


def day_of(ts: float) -> str:
    return time.strftime("%Y-%m-%d", time.gmtime(ts))


def slippage_bps(f: Fill) -> float:
    """Against the decision price, positive when the fill was worse: a buy above it, a sell below it."""
    return f.side * (f.px - f.decision_px) / f.decision_px * 1e4


def slippage_usd(f: Fill) -> float:
    return f.side * (f.px - f.decision_px) * abs(f.qty)


def daily(fills: Iterable[Fill], funding: Iterable[FundingPayment] = ()) -> List[dict]:
    """One row per sleeve, venue and UTC day: fills, notional, fees, funding, slippage in dollars and in bps of
    notional (weighted by notional), and the maker share."""
    rows: Dict[Tuple[str, str, str], dict] = {}

    def row(sleeve, venue, day):
        return rows.setdefault((sleeve, venue, day), {"sleeve": sleeve, "venue": venue, "day": day, "fills": 0,
                                                      "notional": 0.0, "fees": 0.0, "funding": 0.0,
                                                      "slippage_usd": 0.0, "maker_notional": 0.0})
    for f in fills:
        r = row(f.sleeve, f.venue, day_of(f.ts))
        r["fills"] += 1
        r["notional"] += f.notional
        r["fees"] += f.fee
        r["slippage_usd"] += slippage_usd(f)
        r["maker_notional"] += f.notional if f.liquidity == "maker" else 0.0
    for p in funding:
        row(p.sleeve, p.venue, day_of(p.ts))["funding"] += p.usd
    out = []
    for r in rows.values():
        n = r.pop("maker_notional")
        r["slippage_bps"] = r["slippage_usd"] / r["notional"] * 1e4 if r["notional"] else 0.0
        r["maker_share"] = n / r["notional"] if r["notional"] else 0.0
        out.append(r)
    return sorted(out, key=lambda r: (r["day"], r["sleeve"], r["venue"]))


def trades(fills: Iterable[Fill], funding: Iterable[FundingPayment] = (), flat_tol: float = 1e-9) -> Dict[str, dict]:
    """Per round trip: gross from the fills' cash, fees, funding, net, the entry notional, net in bps of it, and
    whether it is closed (its fills net to flat)."""
    by: Dict[str, dict] = {}
    for f in sorted(fills, key=lambda f: f.ts):
        t = by.setdefault(f.trade, {"sleeve": f.sleeve, "venue": f.venue, "coin": f.coin, "opened": f.ts,
                                    "closed": None, "position": 0.0, "cash": 0.0, "fees": 0.0, "funding": 0.0,
                                    "entry_notional": None})
        if t["entry_notional"] is None:
            t["entry_notional"] = f.notional
        t["position"] += f.side * abs(f.qty)
        t["cash"] -= f.side * abs(f.qty) * f.px
        t["fees"] += f.fee
        if abs(t["position"]) <= flat_tol * max(1.0, abs(f.qty)):
            t["closed"] = f.ts
    for p in funding:
        if p.trade in by:
            by[p.trade]["funding"] += p.usd
    for t in by.values():
        cash = t.pop("cash")
        t["gross"] = cash if t["closed"] is not None else float("nan")
        t["net"] = t["gross"] - t["fees"] + t["funding"]
        t["net_bps"] = t["net"] / t["entry_notional"] * 1e4 if t["entry_notional"] else float("nan")
    return by


def twin_gap(live: Dict[str, dict], twin_bps: Dict[str, float]) -> Dict[str, float]:
    """Live net minus the twin's net on the same event, in bps of notional, for closed trades the twin also took."""
    return {k: t["net_bps"] - twin_bps[k] for k, t in live.items() if k in twin_bps and t["closed"] is not None}


def reconcile_equity(journal_equity: float, venue_equity: float, tol_usd: float = EQUITY_TOL_USD,
                     tol_frac: float = EQUITY_TOL_FRAC) -> Optional[str]:
    """A break, in words, when the journal's equity and the venue's own differ by more than the tolerance."""
    gap = journal_equity - venue_equity
    if abs(gap) > max(tol_usd, tol_frac * abs(venue_equity)):
        return f"equity break: the journal says {journal_equity:,.2f}, the venue {venue_equity:,.2f} ({gap:+,.2f})"
    return None


def pause_path(state_dir: Path, sleeve: str) -> Path:
    return Path(state_dir) / f"{sleeve}{PAUSE}"


def pause(state_dir: Path, sleeve: str, reason: str, now: Optional[float] = None,
          tell: Optional[Callable[[str, str], None]] = None) -> Path:
    """Stop the sleeve's new entries until a person removes the file, and say so."""
    path = pause_path(state_dir, sleeve)
    path.write_text(json.dumps({"at": now or time.time(), "reason": reason}), encoding="utf-8")
    if tell is None:
        from .notify import notify as tell
    try:
        tell(f"espero: {sleeve} paused", reason)
    except Exception:  # noqa: BLE001 - the pause stands even when the message fails
        pass
    return path


def paused(state_dir: Path, sleeve: str) -> bool:
    return pause_path(state_dir, sleeve).exists()


def check_equity(state_dir: Path, sleeve: str, journal_equity: float, venue_equity: float,
                 tell: Optional[Callable[[str, str], None]] = None) -> Optional[str]:
    """Reconcile the day's equity; on a break, pause the sleeve and notify. Returns the break or None."""
    why = reconcile_equity(journal_equity, venue_equity)
    if why:
        pause(state_dir, sleeve, why, tell=tell)
    return why


def venue_equity_hl(address: str, fetch=None) -> float:
    """Hyperliquid's own record of the account's equity, public by address, no key."""
    from . import hyperliquid as hl

    return float(hl.user_state(address, fetch=fetch)["equity"])


def from_hlp_testnet(db: Path, sleeve: str = "59") -> List[Fill]:
    """#59's testnet executor's journal as fills, read-only: its mechanics against the testnet mid at each decision.
    It reads nothing of #59's paper book."""
    con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    out: List[Fill] = []
    try:
        for r in con.execute("SELECT * FROM hlp_testnet WHERE entry_px IS NOT NULL ORDER BY signal_ts"):
            trade = f"{r['coin']}-{r['signal_ts']}"
            if r["qty"] and r["entry_mid"]:
                out.append(Fill(sleeve, "hyperliquid_testnet", r["coin"], int(r["entry_ts"]), 1, float(r["qty"]),
                                float(r["entry_px"]), float(r["entry_fee"] or 0.0), float(r["entry_mid"]), trade))
            if r["exited"] and r["exit_px"] and r["exit_mid"]:
                out.append(Fill(sleeve, "hyperliquid_testnet", r["coin"], int(r["exit_ts"]), -1, float(r["exited"]),
                                float(r["exit_px"]), float(r["exit_fee"] or 0.0), float(r["exit_mid"]), trade))
    finally:
        con.close()
    return out


def render(rows: Sequence[dict]) -> str:
    if not rows:
        return "no fills"
    head = "| day | sleeve | venue | fills | notional | fees | funding | slippage $ | slippage bps | maker |"
    lines = [head, "|---|---|---|---|---|---|---|---|---|---|"]
    for r in rows:
        lines.append(f"| {r['day']} | {r['sleeve']} | {r['venue']} | {r['fills']} | {r['notional']:,.2f} | "
                     f"{r['fees']:,.4f} | {r['funding']:+,.4f} | {r['slippage_usd']:+,.4f} | "
                     f"{r['slippage_bps']:+.2f} | {r['maker_share']:.0%} |")
    return "\n".join(lines)


def main(argv=None) -> int:
    """Print #59's testnet mechanics by day, read-only; information only."""
    import sys

    argv = sys.argv[1:] if argv is None else argv
    state = Path(argv[0]) if argv else Path(__file__).resolve().parents[1] / "state"
    db = state / "hlp2-testnet.db"
    print(render(daily(from_hlp_testnet(db))) if db.exists() else f"no {db}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
