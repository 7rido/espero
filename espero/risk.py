"""The gate every order passes through before it can cost money.

This lives below the strategy on purpose: a strategy that returns a BUY signal
has not been allowed to decide size, and cannot bypass any of these checks.

Two parts. The first, `RiskLimits` and `check_buy`, is the paper books' own
per-book sizing (paper.py, degen.py), kept exactly as it was: a running paper
loop imports it on every restart and its journal is #62's input. The second,
`Policy` and `check`, is the account's gate (research/RISK_POLICY.md): every
order that could reach a venue passes it, #63's sleeves sit above it, and
nothing bypasses it. Its numbers are fractions of the holder's allocated
capital, 0 until docs/HOLDER_INPUTS.md says otherwise, so until then it
refuses every entry.
"""
from __future__ import annotations

import hashlib
import json
import re
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Dict, List, Mapping, Optional, Tuple


@dataclass(frozen=True)
class RiskLimits:
    max_position_pct: float = 0.25     # never more than 25% of equity in one position
    max_open_positions: int = 1
    daily_loss_cap_pct: float = 0.03   # stop trading for the day at -3%
    min_notional: float = 10.0
    risk_per_trade: float = 0.01       # 1% of equity is at risk if the stop triggers
    stop_pct: float = 0.05


@dataclass
class Decision:
    allowed: bool
    notional: float = 0.0
    reason: str = ""


def size_position(equity: float, confidence: float, limits: RiskLimits) -> float:
    """Risk-based sizing: notional such that (notional * stop_pct) is the risk budget."""
    if equity <= 0:
        return 0.0
    risk_budget = equity * limits.risk_per_trade
    by_risk = risk_budget / max(limits.stop_pct, 1e-9)
    by_cap = equity * limits.max_position_pct
    return max(0.0, min(by_risk, by_cap))


def check_buy(equity: float, cash: float, open_positions: int, day_pnl: float,
              confidence: float, limits: RiskLimits) -> Decision:
    if open_positions >= limits.max_open_positions:
        return Decision(False, reason="max open positions")
    if equity <= 0:
        return Decision(False, reason="no equity")
    if day_pnl <= -limits.daily_loss_cap_pct * equity:
        return Decision(False, reason="daily loss cap hit")
    notional = size_position(equity, confidence, limits)
    if notional < limits.min_notional:
        return Decision(False, reason=f"notional {notional:.2f} below minimum")
    if notional > cash:
        notional = cash * 0.99
        if notional < limits.min_notional:
            return Decision(False, reason="not enough cash")
    return Decision(True, notional=notional, reason="ok")


def check_sell(open_positions: int) -> Decision:
    if open_positions == 0:
        return Decision(False, reason="nothing to sell")
    return Decision(True, reason="ok")


# ====================================================================== the account's gate
POLICY_DOC = Path(__file__).resolve().parents[1] / "research" / "RISK_POLICY.md"
START, END = "<!-- policy:start -->", "<!-- policy:end -->"
STOPS = ("ok", "day", "week", "holder")


@dataclass(frozen=True)
class Policy:
    """research/RISK_POLICY.md's numbers, each with its reasoning there. Fractions of the smaller of the holder's
    allocation and the account's equity. The holder changes one in a commit that edits that table and this class
    together; tests/test_risk.py fails when they differ."""
    leverage: float = 1.0               # gross perp notional / capital, the whole account: no borrowing (#63)
    venue_leverage: float = 1.0         # gross perp notional on a venue / the equity held on that venue
    per_coin: float = 0.20              # gross perp notional in one coin / capital
    per_venue: float = 0.50             # gross notional on one venue, every leg / capital
    per_sleeve: float = 1.0             # a sleeve's gross / capital, before its weight, rung and scales
    liq_floor: float = 0.25             # the venue book survives an adverse move this large ...
    liq_sigmas: float = 8.0             # ... and this many of the coin's daily sigmas, whichever is larger
    funding_day: float = 0.0020         # funding paid in the next 24 h at current rates, every position / capital
    funding_position: float = 0.0010    # the same, one position
    day_stop: float = -0.02             # equity against 00:00 UTC: no entries until the next UTC day
    week_stop: float = -0.05            # equity against Monday 00:00 UTC: flatten, no entries until next Monday + ack
    hedge_tolerance: float = 0.02       # a two-legged trade's |spot - perp| / its leg: above it, a break


POLICY = Policy()


def policy_hash(policy: Policy = POLICY) -> str:
    """The numbers' fingerprint, carried by every ruling, so a journal says which policy allowed an order."""
    return hashlib.sha256(json.dumps(asdict(policy), sort_keys=True).encode()).hexdigest()


@dataclass(frozen=True)
class Position:
    venue: str
    coin: str
    sleeve: str
    side: int                           # +1 long, -1 short
    notional: float                     # |size| x mark, USD
    leg: str = "perp"                   # "perp", or "spot" (fully paid: no liquidation, no funding)
    funding_8h: float = 0.0             # the coin's current rate per 8 hours; positive: longs pay shorts
    liq_px: Optional[float] = None      # the venue's own liquidation price, where it reports one
    mark: Optional[float] = None
    group: str = ""                     # a two-legged trade's id: carry's spot and perp legs share it


@dataclass(frozen=True)
class Account:
    capital: float                      # the holder's allocation (espero.holder), 0 until answered
    equity: float                       # marked now, every venue
    equity_by_venue: Mapping[str, float]
    positions: Tuple[Position, ...] = ()
    day_start: float = 0.0              # equity at 00:00 UTC
    week_start: float = 0.0             # equity at Monday 00:00 UTC
    peak: float = 0.0                   # equity's peak since live, for the holder's own stop
    holder_stop: Optional[float] = None  # the drawdown at which the holder stops, e.g. -0.15 (docs/HOLDER_INPUTS.md)
    sleeve_scale: Mapping[str, float] = field(default_factory=dict)   # #63 weight x rung x drawdown x edgewatch
    sigma_daily: Mapping[str, float] = field(default_factory=dict)    # each coin's trailing 30-day daily sigma
    breaks: Tuple[str, ...] = ()        # open reconciliation or hedge breaks: entries refused while any is open
    paused: bool = False                # a KILL file, an executor's .stop or attribution's .pause
    awaiting_ack: bool = False          # a week stop the operator has not acknowledged yet

    @property
    def base(self) -> float:
        """What the fractions apply to: the allocation, or the equity when losses have taken it lower."""
        return max(0.0, min(self.capital, self.equity))


@dataclass(frozen=True)
class Order:
    sleeve: str
    rule: str
    venue: str
    coin: str
    side: int                           # +1 buy, -1 sell
    notional: float                     # USD asked for
    leg: str = "perp"
    reduce_only: bool = False
    funding_8h: float = 0.0
    mmr: float = 0.005                  # the venue's maintenance margin rate for the coin
    min_notional: float = 10.0          # the venue's smallest order (espero.venues)
    group: str = ""


@dataclass(frozen=True)
class Ruling:
    allowed: bool
    notional: float                     # what may be sent: the order's, cut to the tightest cap, or 0
    reasons: Tuple[str, ...]
    checks: Mapping[str, Tuple[float, float]]   # check -> (room left before the order, the cap), USD
    policy_hash: str


def stop_state(account: Account, policy: Policy = POLICY) -> str:
    """'holder' (the holder's own drawdown: flat, absorbing), 'week', 'day' or 'ok', the most severe first."""
    if (account.holder_stop is not None and account.peak > 0
            and account.equity / account.peak - 1 <= account.holder_stop):
        return "holder"
    if account.week_start > 0 and account.equity / account.week_start - 1 <= policy.week_stop:
        return "week"
    if account.day_start > 0 and account.equity / account.day_start - 1 <= policy.day_stop:
        return "day"
    return "ok"


def on_stop(state: str) -> Tuple[str, ...]:
    """What a stop does to resting orders and open positions, in order."""
    return {
        "ok": (),
        "day": ("cancel resting entry orders", "no new entries until 00:00 UTC",
                "open positions run to their registered exits"),
        "week": ("cancel every resting order", "flatten every position reduce-only, perp legs first",
                 "no new entries until next Monday 00:00 UTC and the operator's authenticated acknowledgement"),
        "holder": ("cancel every resting order", "flatten every position reduce-only, perp legs first",
                   "no new entries until the holder changes the stop in docs/HOLDER_INPUTS.md"),
    }[state]


def _gross(positions, venue=None, coin=None, sleeve=None, perp_only=False) -> float:
    return sum(p.notional for p in positions
               if (venue is None or p.venue == venue) and (coin is None or p.coin == coin)
               and (sleeve is None or p.sleeve == sleeve) and (not perp_only or p.leg == "perp"))


def _funding_paid_day(notional: float, side: int, funding_8h: float) -> float:
    """Dollars a position pays in the next 24 hours at the current rate; a position that is paid counts 0."""
    return notional * max(0.0, side * funding_8h) * 3


def liq_distance(account: Account, venue: str, extra: float = 0.0, mmr: float = 0.005) -> float:
    """The adverse move, as a fraction, that takes the venue's whole perp book to its maintenance margin if every
    position moves against itself at once: (equity - mmr x gross) / gross. Conservative by construction."""
    gross = _gross(account.positions, venue=venue, perp_only=True) + extra
    if gross <= 0:
        return float("inf")
    return (account.equity_by_venue.get(venue, 0.0) - mmr * gross) / gross


def check(order: Order, account: Account, policy: Policy = POLICY) -> Ruling:
    """The account's ruling on one order: refused, allowed as asked, or allowed smaller, with every reason."""
    h = policy_hash(policy)

    def refuse(why: str, checks=None) -> Ruling:
        return Ruling(False, 0.0, (why,), checks or {}, h)

    if order.side not in (1, -1) or not order.notional > 0:
        return refuse("an order needs a side and a size")
    if order.reduce_only:
        held = sum(p.notional for p in account.positions if p.venue == order.venue and p.coin == order.coin
                   and p.leg == order.leg and p.side == -order.side)
        if held <= 0:
            return refuse("reduce-only, but there is nothing on that side to reduce")
        return Ruling(True, min(order.notional, held), ("reduce-only: it passes the caps, and is journaled",), {}, h)

    if account.capital <= 0:
        return refuse("no capital allocated (docs/HOLDER_INPUTS.md): the default is 0")
    state = stop_state(account, policy)
    if state != "ok":
        return refuse(f"{state} stop: " + "; ".join(on_stop(state)))
    if account.awaiting_ack:
        return refuse("a week stop awaits the operator's authenticated acknowledgement")
    if account.paused:
        return refuse("paused: a KILL, .stop or .pause file is in place")
    if account.breaks:
        return refuse(f"an open break: {account.breaks[0]}")

    base, pos = account.base, account.positions
    venue_eq = account.equity_by_venue.get(order.venue, 0.0)
    scale = account.sleeve_scale.get(order.sleeve, 0.0)
    if scale <= 0:
        return refuse(f"sleeve {order.sleeve!r} has no allocation (its #63 weight, rung or states are 0)")
    perp = order.leg == "perp"
    room: Dict[str, Tuple[float, float]] = {
        "per venue": (policy.per_venue * base - _gross(pos, venue=order.venue), policy.per_venue * base),
        "per sleeve": (policy.per_sleeve * scale * base - _gross(pos, sleeve=order.sleeve),
                       policy.per_sleeve * scale * base),
    }
    if perp:
        room["leverage"] = (policy.leverage * base - _gross(pos, perp_only=True), policy.leverage * base)
        room["venue leverage"] = (policy.venue_leverage * venue_eq - _gross(pos, venue=order.venue, perp_only=True),
                                  policy.venue_leverage * venue_eq)
        room["per coin"] = (policy.per_coin * base - _gross(pos, coin=order.coin, perp_only=True),
                            policy.per_coin * base)
        need = max(policy.liq_floor, policy.liq_sigmas * account.sigma_daily.get(order.coin, 0.0))
        for p in pos:
            if p.venue == order.venue and p.leg == "perp" and p.liq_px and p.mark:
                if abs(p.liq_px / p.mark - 1) < need:
                    return refuse(f"{p.coin} on {p.venue} is already within {need:.0%} of its liquidation price",
                                  room)
        cap_liq = venue_eq / (need + order.mmr) - _gross(pos, venue=order.venue, perp_only=True)
        room["liquidation distance"] = (cap_liq, venue_eq / (need + order.mmr))
        paid_now = sum(_funding_paid_day(p.notional, p.side, p.funding_8h) for p in pos if p.leg == "perp")
        per_dollar = _funding_paid_day(1.0, order.side, order.funding_8h)
        if per_dollar > 0:
            same = sum(p.notional for p in pos if p.venue == order.venue and p.coin == order.coin
                       and p.leg == "perp" and p.side == order.side)
            room["funding, all"] = ((policy.funding_day * base - paid_now) / per_dollar, policy.funding_day * base)
            room["funding, this position"] = (policy.funding_position * base / per_dollar - same,
                                              policy.funding_position * base)

    allowed = min(order.notional, *(r for r, _ in room.values()))
    binding = [f"{k}: room ${max(r, 0):,.2f}" for k, (r, _) in room.items() if r < order.notional]
    if allowed < order.min_notional:
        return refuse(f"below the venue's ${order.min_notional:,.2f} minimum after the caps"
                      + (f" ({'; '.join(binding)})" if binding else ""), room)
    reasons = tuple(binding) if binding else ("within every cap",)
    return Ruling(True, float(allowed), reasons, room, h)


def hedge_breaks(positions: Tuple[Position, ...], policy: Policy = POLICY) -> List[str]:
    """Two-legged trades whose legs no longer offset: |spot - perp| above the tolerance of the larger leg."""
    out = []
    for g in sorted({p.group for p in positions if p.group}):
        legs = [p for p in positions if p.group == g]
        spot = sum(p.side * p.notional for p in legs if p.leg == "spot")
        perp = sum(p.side * p.notional for p in legs if p.leg == "perp")
        size = max(abs(spot), abs(perp))
        if size > 0 and abs(spot + perp) > policy.hedge_tolerance * size:
            out.append(f"{g}: spot {spot:+,.2f} against perp {perp:+,.2f} is off by more than "
                       f"{policy.hedge_tolerance:.0%}")
    return out


def flatten_orders(positions: Tuple[Position, ...]) -> List[Order]:
    """What "flat" takes: a reduce-only order against every position, perp legs first. A carry trade is flat only
    when both legs are zero; its perp leg goes first because it is the one that can be liquidated and pays
    funding, and a fully paid spot leg left alone can lose only what it holds."""
    ordered = sorted(positions, key=lambda p: (p.leg != "perp", p.venue, p.coin))
    return [Order(p.sleeve, "flatten", p.venue, p.coin, -p.side, p.notional, leg=p.leg, reduce_only=True,
                  group=p.group) for p in ordered if p.notional > 0]


def policy_table(policy: Policy = POLICY) -> Dict[str, float]:
    return asdict(policy)


def doc_table(doc: Path = POLICY_DOC) -> Dict[str, float]:
    """The numbers as research/RISK_POLICY.md states them, between its policy markers: | `field` | value | ..."""
    text = doc.read_text(encoding="utf-8")
    a, b = text.find(START), text.find(END)
    if a < 0 or b < 0:
        return {}
    out = {}
    for m in re.finditer(r"^\|\s*`([a-z_]+)`\s*\|\s*([-+0-9.]+)\s*\|", text[a:b], re.M):
        out[m.group(1)] = float(m.group(2))
    return out


def main(argv=None, doc: Path = POLICY_DOC) -> int:
    argv = sys.argv[1:] if argv is None else argv
    table = doc_table(doc)
    for k, v in policy_table().items():
        flag = "" if table.get(k) == v else f"   <- RISK_POLICY.md says {table.get(k)}"
        print(f"{k:18s} {v:g}{flag}")
    print(f"policy hash {policy_hash()}")
    return 0 if table == policy_table() else 1


if __name__ == "__main__":
    sys.exit(main())
