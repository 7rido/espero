"""#81: the BTC volatility premium, sold every week with wings (research/PREREGISTRATION_VOLPREM.md, 8d60f75).

The frozen rule and its criteria, pure: Deribit option trades and delivery prices in, weekly returns and a verdict
out, no I/O. research/volprem.py fetches and prints. The numbers below are the pre-registration's.

Readings fixed before any result. The contract is silent or loose at these points, and the narrowest reading is
taken. None of them was chosen by looking at a profit or a loss.

* **The window's trades.** Those of the expiry (the next Friday's), with 09:00:00 <= t < 13:00:00 UTC, filtered here
  and not by trusting the endpoint's end bound. A trade with a missing, non-positive or non-finite `iv` cannot be
  priced: it is left out of every strike and implied volatility, and counted (`Week.n_unusable`). It still counts as
  one of "the last of them" for *F*, which is the `index_price` of the last trade of the expiry in the window whatever
  its `iv`; a missing or non-positive `index_price` is skipped over in looking for it.
* **"Last".** Trades are ordered by (timestamp in ms, then `trade_id` read as an integer when it is all digits, else
  as text): several trades can share a millisecond, and the highest `trade_id` is the last.
* **"Nearest" and ties.** Nearest in dollars of strike, never in log distance. A tie goes to the lower strike, for
  *K0* (the contract says so) and, by the same reading, for the two wings too.
* **Range bounds** (*F*·exp(1.5σw) to *F*·exp(3σw) and its mirror) are inclusive.
* **A strike's implied volatility** is the median of its trades' `iv` over 100, calls and puts together; the strike
  has traded if it has at least one usable trade.
* **Skip order.** Fewer than five traded strikes (a window with no trades is that), then a wing with no strike in
  range, then a missing delivery price (Saturday to Thursday and the expiry's own), then M <= 0. No other reason
  exists in this module.
* **Hedge times and holdings.** The entry (price *F*, 163 hours left), then the 08:00 UTC delivery prices of
  Saturday to Thursday (144, 120, 96, 72, 48 and 24 hours left), then the settlement price. Seven holdings, each
  minus the position's delta at its time and price; the last one is closed at the settlement price. Dollars traded:
  the opening holding at *F*, each change in holding at that day's price, the closing holding at the settlement.
* **M** is rule 11 to the letter: the larger width less the credit net of the entry costs (half-gaps and trading
  fees). It does **not** include the settlement fees, so the unhedged loss can exceed it by exactly those fees; the
  loss before them never does.
* **Criterion 5** doubles the half-gaps and the hedge's cost only, not the trading or settlement fees, on the main
  run's weeks, with the main run's *M*.
* **Criterion 4** counts a year as a loss when its mean hedged return is at or below zero.
* **Realized volatility** (information only): sqrt of the squared log returns of the seven steps over tau.
"""
from __future__ import annotations

import datetime as dt
import math
import statistics
from dataclasses import dataclass
from typing import Dict, List, Mapping, NamedTuple, Optional, Sequence, Tuple, Union

import numpy as np

from .cascade import nw_t
from .trials import bh
from .volf import nw_lags

TAU_HOURS = 163
TAU = TAU_HOURS / (365 * 24)
HOURS_LEFT = (163, 144, 120, 96, 72, 48, 24)        # at the entry and at Saturday to Thursday 08:00 UTC
WINDOW_START_S = 9 * 3600
WINDOW_END_S = 13 * 3600
BODY_ZONE = 2.0
WING_LOW, WING_HIGH = 1.5, 3.0
MIN_STRIKES = 5
SHORT_GAP_BPS, SHORT_GAP_PCT = 5.0, 0.04
LONG_GAP_BPS, LONG_GAP_PCT = 1.5, 0.10
FEE_BPS, FEE_CAP = 3.0, 0.125
SETTLE_BPS, SETTLE_CAP = 1.5, 0.125
HEDGE_BPS = 6.0
MIN_PF = 1.5
MIN_T = 3.0
MAX_Q = 0.05
MIN_WEEKS = 200
MIN_YEAR_WEEKS = 20
MAX_LOSING_YEARS = 2
SINCE = dt.date(2025, 1, 3)

FEW_STRIKES = "fewer than five traded strikes"
NO_WING = "a wing has no traded strike in its range"
NO_DELIVERY = "no delivery price for a day the week needs"
NO_RISK = "M <= 0"
REASONS = (FEW_STRIKES, NO_WING, NO_DELIVERY, NO_RISK)

_MONTHS = {m: i + 1 for i, m in enumerate(("JAN", "FEB", "MAR", "APR", "MAY", "JUN", "JUL", "AUG", "SEP", "OCT",
                                           "NOV", "DEC"))}


class Trade(NamedTuple):
    ts_ms: int
    trade_id: str
    name: str
    iv: float               # percent, as Deribit gives it
    index: float
    mark: float             # in BTC


@dataclass(frozen=True)
class Skip:
    friday: dt.date
    reason: str
    n_trades: int


@dataclass(frozen=True)
class Week:
    friday: dt.date
    F: float
    S: float
    K0: float
    Kc: float
    Kp: float
    sig0: float
    n_trades: int            # the expiry's trades in the window, usable or not
    n_unusable: int
    n_strikes: int
    credit: float
    gap: float               # half bid-ask gaps, the four legs
    fee: float               # Deribit's trading fee, the four legs
    payout: float            # what the position pays at settlement (can be negative)
    settle_fee: float
    hedge_pnl: float
    hedge_cost: float
    hedge_traded: float      # dollars
    M: float
    profit_h: float
    profit_u: float
    ret_h: float
    ret_u: float
    ret_h2: float            # hedged, the half-gaps and the hedge's cost doubled, the same M
    realized: float          # annualised, from the seven steps
    mark_credit: Optional[float]


# ---------------------------------------------------------------------------------------------- Black-76
def ncdf(x: float) -> float:
    return 0.5 * math.erfc(-x / math.sqrt(2))


def _d1(F: float, K: float, sig: float, tau: float) -> float:
    return (math.log(F / K) + 0.5 * sig * sig * tau) / (sig * math.sqrt(tau))


def black76(F: float, K: float, sig: float, tau: float, kind: str) -> float:
    """Price in dollars of a call ('C') or put ('P') on a forward `F`, no interest: F N(d1) - K N(d2)."""
    d1 = _d1(F, K, sig, tau)
    d2 = d1 - sig * math.sqrt(tau)
    if kind == "C":
        return F * ncdf(d1) - K * ncdf(d2)
    return K * ncdf(-d2) - F * ncdf(-d1)


def delta(F: float, K: float, sig: float, tau: float, kind: str) -> float:
    d1 = _d1(F, K, sig, tau)
    return ncdf(d1) if kind == "C" else ncdf(d1) - 1.0


# ---------------------------------------------------------------------------------------------- the inputs
def parse_instrument(name: str) -> Optional[Tuple[dt.date, float, str]]:
    """`BTC-10JAN20-7250-C` -> (expiry date, strike, 'C'), None for a name that is not a BTC option's."""
    parts = name.split("-")
    if len(parts) != 4 or parts[0] != "BTC" or parts[3] not in ("C", "P"):
        return None
    code = parts[1]
    try:
        day, mon, year = int(code[:-5]), _MONTHS[code[-5:-2]], 2000 + int(code[-2:])
        return dt.date(year, mon, day), float(parts[2].replace("d", ".")), parts[3]
    except (ValueError, KeyError):
        return None


def _day_s(d: dt.date) -> int:
    return int(dt.datetime(d.year, d.month, d.day, tzinfo=dt.timezone.utc).timestamp())


def _order(t: Trade):
    return (t.ts_ms, (0, int(t.trade_id), "") if t.trade_id.isdigit() else (1, 0, t.trade_id))


def _usable(t: Trade) -> bool:
    return math.isfinite(t.iv) and t.iv > 0


def window_trades(trades: Sequence[Trade], friday: dt.date) -> List[Trade]:
    """The expiry's trades with 09:00:00 <= t < 13:00:00 UTC on `friday`, in order, one per trade_id."""
    lo = (_day_s(friday) + WINDOW_START_S) * 1000
    hi = (_day_s(friday) + WINDOW_END_S) * 1000
    expiry = friday + dt.timedelta(days=7)
    seen, out = set(), []
    for t in trades:
        p = parse_instrument(t.name)
        if p is None or p[0] != expiry or not lo <= t.ts_ms < hi or t.trade_id in seen:
            continue
        seen.add(t.trade_id)
        out.append(t)
    return sorted(out, key=_order)


def strike_table(trades: Sequence[Trade]) -> Dict[float, float]:
    """{strike: implied volatility as a fraction}: the median `iv` of the strike's usable trades, calls and puts
    together."""
    by: Dict[float, List[float]] = {}
    for t in trades:
        p = parse_instrument(t.name)
        if p is not None and _usable(t):
            by.setdefault(p[1], []).append(t.iv / 100.0)
    return {k: statistics.median(v) for k, v in by.items()}


def nearest(strikes: Sequence[float], target: float) -> float:
    """The strike nearest `target` in dollars, the lower on a tie."""
    return min(strikes, key=lambda k: (abs(k - target), k))


def pick_strikes(table: Mapping[float, float], F: float):
    """(K0, Kc, Kp) by rules 2 and 3, or None when a wing has no traded strike in its range."""
    ks = sorted(table)
    K0 = nearest(ks, F)
    sw = table[K0] * math.sqrt(TAU)
    up = [k for k in ks if F * math.exp(WING_LOW * sw) <= k <= F * math.exp(WING_HIGH * sw)]
    dn = [k for k in ks if F * math.exp(-WING_HIGH * sw) <= k <= F * math.exp(-WING_LOW * sw)]
    if not up or not dn:
        return None
    return K0, nearest(up, F * math.exp(BODY_ZONE * sw)), nearest(dn, F * math.exp(-BODY_ZONE * sw))


# ---------------------------------------------------------------------------------------------- the legs
def legs(K0: float, Kc: float, Kp: float, table: Mapping[float, float]):
    """(kind, strike, sign, implied volatility): short call and put at K0, long call at Kc and put at Kp."""
    return [("C", K0, -1, table[K0]), ("P", K0, -1, table[K0]), ("C", Kc, 1, table[Kc]), ("P", Kp, 1, table[Kp])]


def half_gap(F: float, price: float, sign: int) -> float:
    """Rule 7: on a short leg the larger of 5 bps of F and 4% of its price, on a long leg 1.5 bps and 10%."""
    if sign < 0:
        return max(SHORT_GAP_BPS * 1e-4 * F, SHORT_GAP_PCT * price)
    return max(LONG_GAP_BPS * 1e-4 * F, LONG_GAP_PCT * price)


def trade_fee(F: float, price: float) -> float:
    """The lesser of 3 bps of F and 12.5% of the leg's price."""
    return min(FEE_BPS * 1e-4 * F, FEE_CAP * price)


def settle_fee(S: float, payoff: float) -> float:
    """On a leg that finishes in the money, the lesser of 1.5 bps of the delivery price and 12.5% of what it pays."""
    return min(SETTLE_BPS * 1e-4 * S, SETTLE_CAP * payoff) if payoff > 0 else 0.0


def payoff(kind: str, K: float, S: float) -> float:
    return max(0.0, S - K) if kind == "C" else max(0.0, K - S)


def settlement_payout(K0: float, Kc: float, Kp: float, S: float) -> float:
    """Rule 8: what the position pays out (a loss when positive)."""
    return max(0.0, S - K0) + max(0.0, K0 - S) - max(0.0, S - Kc) - max(0.0, Kp - S)


def risk(K0: float, Kc: float, Kp: float, credit: float, entry_costs: float) -> float:
    """Rule 11: the larger width less the credit net of the entry costs (the settlement fees are not in it)."""
    return max(Kc - K0, K0 - Kp) - (credit - entry_costs)


def position_delta(lg, price: float, hours_left: float) -> float:
    return sum(sign * delta(price, K, sig, hours_left / (365 * 24), kind) for kind, K, sign, sig in lg)


def hedge(lg, path: Sequence[float]) -> Tuple[float, float, float, List[float]]:
    """Rule 9 over `path` = (F, Saturday .. Thursday, settlement): (profit, dollars traded, cost, holdings). Holding i
    is minus the delta at path[i] with HOURS_LEFT[i] to run, held to path[i + 1]."""
    hold = [-position_delta(lg, path[i], HOURS_LEFT[i]) for i in range(len(HOURS_LEFT))]
    pnl = sum(hold[i] * (path[i + 1] - path[i]) for i in range(len(hold)))
    traded = abs(hold[0]) * path[0]
    traded += sum(abs(hold[i] - hold[i - 1]) * path[i] for i in range(1, len(hold)))
    traded += abs(hold[-1]) * path[-1]
    return pnl, traded, HEDGE_BPS * 1e-4 * traded, hold


def realized_vol(path: Sequence[float]) -> float:
    return math.sqrt(sum(math.log(b / a) ** 2 for a, b in zip(path, path[1:])) / TAU)


# ---------------------------------------------------------------------------------------------- one week
def _mark_credit(lg, trades: Sequence[Trade], expiry: dt.date) -> Optional[float]:
    """The four legs' last `mark_price` x `index_price` in the window, as the credit; None if a leg never traded."""
    last: Dict[Tuple[str, float], Trade] = {}
    for t in trades:
        p = parse_instrument(t.name)
        if p is not None and math.isfinite(t.mark) and t.mark > 0 and t.index > 0:
            last[(p[2], p[1])] = t
    total = 0.0
    for kind, K, sign, _ in lg:
        if (kind, K) not in last:
            return None
        total -= sign * last[(kind, K)].mark * last[(kind, K)].index
    return total


def evaluate_week(friday: dt.date, trades: Sequence[Trade], deliveries: Mapping[dt.date, float]) -> Union[Week, Skip]:
    """The registered week. `trades` may hold anything fetched around the window; `deliveries` maps a date to its
    08:00 UTC delivery price."""
    win = window_trades(trades, friday)
    table = strike_table(win)
    n_trades = len(win)
    if len(table) < MIN_STRIKES:
        return Skip(friday, FEW_STRIKES, n_trades)
    F = next((t.index for t in reversed(win) if t.index > 0 and math.isfinite(t.index)), None)
    if F is None:
        return Skip(friday, FEW_STRIKES, n_trades)
    picked = pick_strikes(table, F)
    if picked is None:
        return Skip(friday, NO_WING, n_trades)
    days = [friday + dt.timedelta(days=k) for k in range(1, 8)]
    if any(deliveries.get(d) is None or not deliveries[d] > 0 for d in days):
        return Skip(friday, NO_DELIVERY, n_trades)
    K0, Kc, Kp = picked
    lg = legs(K0, Kc, Kp, table)
    prices = [black76(F, K, sig, TAU, kind) for kind, K, _, sig in lg]
    credit = sum(-sign * p for (_, _, sign, _), p in zip(lg, prices))
    gap = sum(half_gap(F, p, sign) for (_, _, sign, _), p in zip(lg, prices))
    fee = sum(trade_fee(F, p) for p in prices)
    M = risk(K0, Kc, Kp, credit, gap + fee)
    if not M > 0:
        return Skip(friday, NO_RISK, n_trades)
    S = deliveries[days[-1]]
    path = [F] + [deliveries[d] for d in days]
    payout = settlement_payout(K0, Kc, Kp, S)
    sfee = sum(settle_fee(S, payoff(kind, K, S)) for kind, K, _, _ in lg)
    pnl, traded, hcost, _ = hedge(lg, path)
    profit_u = credit - gap - fee - payout - sfee
    profit_h = profit_u + pnl - hcost
    profit_h2 = profit_h - gap - hcost
    return Week(friday, F, S, K0, Kc, Kp, table[K0], n_trades, sum(1 for t in win if not _usable(t)), len(table),
                credit, gap, fee, payout, sfee, pnl, hcost, traded, M, profit_h, profit_u, profit_h / M,
                profit_u / M, profit_h2 / M, realized_vol(path), _mark_credit(lg, win, friday + dt.timedelta(days=7)))


# ---------------------------------------------------------------------------------------------- the criteria
@dataclass(frozen=True)
class Check:
    n: int
    ok: bool
    text: str


def profit_factor(values: Sequence[float]) -> Optional[float]:
    won = sum(v for v in values if v > 0)
    lost = -sum(v for v in values if v < 0)
    if lost > 0:
        return won / lost
    return math.inf if won > 0 else None        # no losing week: unbounded, which meets any floor


def two_sided_p(t: float) -> float:
    return math.erfc(abs(t) / math.sqrt(2)) if math.isfinite(t) else float("nan")


def mean(values: Sequence[float]) -> float:
    return sum(values) / len(values) if values else float("nan")


def by_year(weeks: Sequence[Week], attr: str = "ret_h") -> Dict[int, List[float]]:
    out: Dict[int, List[float]] = {}
    for w in weeks:
        out.setdefault(w.friday.year, []).append(getattr(w, attr))
    return out


def criteria(weeks: Sequence[Week], other_p: Sequence[float]) -> Tuple[str, List[Check], Dict[str, float]]:
    """The six registered checks, the verdict and the numbers behind them. `other_p` are the p-values of every other
    judged test in the ledger (a test with none is a 1.0); this test's own p is appended for Benjamini-Hochberg."""
    n = len(weeks)
    rh = [w.ret_h for w in weeks]
    pf = profit_factor(rh)
    m = mean(rh)
    lags = nw_lags(n)
    t = nw_t(np.array(rh), lags) if n >= 2 else float("nan")
    p = two_sided_p(t)
    allp = np.append(np.asarray(list(other_p), float), p if math.isfinite(p) else 1.0)
    q = float(bh(allp)[-1])
    since = [w.ret_h for w in weeks if w.friday >= SINCE]
    m_since = mean(since)
    years = {y: v for y, v in by_year(weeks).items() if len(v) >= MIN_YEAR_WEEKS}
    losing = sorted(y for y, v in years.items() if not mean(v) > 0)
    m2 = mean([w.ret_h2 for w in weeks])
    mu = mean([w.ret_u for w in weeks])
    checks = [
        Check(1, pf is not None and pf >= MIN_PF,
              f"profit factor {pf if pf is None else round(pf, 3)} (need >= {MIN_PF})"),
        Check(2, bool(m > 0 and math.isfinite(t) and t >= MIN_T and q < MAX_Q),
              f"mean {m:+.5f} of M, Newey-West t {t:.2f} ({lags} lags), p {p:.4g}, BH q {q:.4g} over {len(allp)} tests "
              f"(need mean > 0, t >= {MIN_T}, q < {MAX_Q})"),
        Check(3, bool(m_since > 0),
              f"mean since {SINCE.isoformat()} {m_since:+.5f} over {len(since)} weeks (need > 0)"),
        Check(4, len(losing) <= MAX_LOSING_YEARS,
              f"{len(losing)} of {len(years)} years with >= {MIN_YEAR_WEEKS} weeks at or below zero"
              f"{' (' + ', '.join(map(str, losing)) + ')' if losing else ''} (need at most {MAX_LOSING_YEARS})"),
        Check(5, bool(m2 > 0), f"mean with half-gaps and hedge cost doubled {m2:+.5f} (need > 0)"),
        Check(6, bool(mu > 0), f"mean unhedged {mu:+.5f} (need > 0)"),
    ]
    if n < MIN_WEEKS:
        verdict = "INCONCLUSIVE"
    else:
        verdict = "PASS" if all(c.ok for c in checks) else "FAIL"
    stats = {"n": n, "mean": m, "t": t, "lags": lags, "p": p, "q": q, "fam": len(allp),
             "pf": pf if pf is not None else float("nan"), "mean_since": m_since, "n_since": len(since),
             "mean_h2": m2, "mean_u": mu, "losing_years": len(losing)}
    return verdict, checks, stats
