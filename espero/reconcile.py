"""Reconcile our record of orders against the exchange's record of fills (#40,
research/PREREGISTRATION_TESTNET.md). Pure: dicts in, lists of breaks out.

Our record, per order id: {"tif": "Alo" | "Ioc", "filled": size, "avg_px": IOC
average price or None}. The exchange's record: Hyperliquid `userFills` rows
(coin, px, sz, oid, crossed, fee, time). A break is any disagreement; the
pre-registration passes only with none.
"""
from __future__ import annotations

import bisect
from typing import Dict, Iterable, List


def by_oid(fills: Iterable[dict]) -> Dict[int, dict]:
    """The exchange's fills grouped per order: total size, average price, the
    set of `crossed` flags seen."""
    out: Dict[int, dict] = {}
    for f in fills:
        o = out.setdefault(int(f["oid"]), {"sz": 0.0, "notional": 0.0, "crossed": set(), "n": 0})
        sz, px = float(f["sz"]), float(f["px"])
        o["sz"] += sz
        o["notional"] += sz * px
        o["crossed"].add(bool(f["crossed"]))
        o["n"] += 1
    for o in out.values():
        o["avg_px"] = o["notional"] / o["sz"] if o["sz"] else None
    return out


def fills_match(ours: Dict[int, dict], fills: Iterable[dict], size_step: Dict[int, float],
                tick: Dict[int, float]) -> List[str]:
    """Criterion 2: every order id with a fill on either side agrees on size
    (within its size step) and, for IOC orders, average price (within a tick)."""
    theirs = by_oid(fills)
    breaks = []
    for oid in sorted(set(theirs) | {o for o, r in ours.items() if r["filled"] > 0}):
        mine, ex = ours.get(oid), theirs.get(oid)
        if mine is None:
            breaks.append(f"oid {oid}: exchange fill not in our record")
            continue
        if ex is None:
            breaks.append(f"oid {oid}: we recorded {mine['filled']} filled, the exchange has no fill")
            continue
        if abs(mine["filled"] - ex["sz"]) > size_step[oid] / 2:
            breaks.append(f"oid {oid}: size ours {mine['filled']} vs exchange {ex['sz']}")
        if mine["tif"] == "Ioc" and mine.get("avg_px") is not None \
                and abs(mine["avg_px"] - ex["avg_px"]) > tick[oid] + 1e-12:
            breaks.append(f"oid {oid}: avg price ours {mine['avg_px']} vs exchange {ex['avg_px']:.8g}")
    return breaks


def fees_match(fills: Iterable[dict], maker_rate: float, taker_rate: float,
               abs_tol: float = 1e-6, rel_tol: float = 1e-3) -> List[str]:
    """Criterion 3: fee = px x sz x (taker rate if crossed else maker rate)."""
    breaks = []
    for f in fills:
        rate = taker_rate if f["crossed"] else maker_rate
        want = float(f["px"]) * float(f["sz"]) * rate
        got = float(f["fee"])
        if abs(got - want) > max(abs_tol, rel_tol * abs(want)):
            breaks.append(f"oid {f['oid']} tid {f.get('tid')}: fee {got} vs schedule {want:.8g}")
    return breaks


def flags_match(ours: Dict[int, dict], fills: Iterable[dict]) -> List[str]:
    """Criterion 4: an ALO order only ever makes; an IOC order only ever takes."""
    breaks = []
    for oid, ex in by_oid(fills).items():
        mine = ours.get(oid)
        if mine is None:
            continue                        # reported by fills_match
        want = {"Alo": {False}, "Ioc": {True}}.get(mine["tif"])
        if want is not None and ex["crossed"] != want:
            breaks.append(f"oid {oid}: {mine['tif']} order filled with crossed={sorted(ex['crossed'])}")
    return breaks


def post_only_refused(attempts: Iterable[dict], fills: Iterable[dict]) -> List[str]:
    """Criterion 1: every crossing ALO attempt was rejected (no resting order,
    no fill) and nothing it could have become appears among the fills."""
    filled_oids = set(by_oid(fills))
    breaks = []
    for a in attempts:
        if a["status"] != "error":
            breaks.append(f"{a['coin']} {a['side']} at {a['price']}: {a['status']} (oid {a.get('oid')})")
        if a.get("oid") is not None and int(a["oid"]) in filled_oids:
            breaks.append(f"{a['coin']} oid {a['oid']}: a crossing ALO order filled")
    return breaks


def positions_match(intended: Dict[str, float], actual: Dict[str, float], step: Dict[str, float]) -> List[str]:
    """#42's criterion 2: the exchange's position per coin equals the one our
    own fills say we should hold, within half a size step. A coin missing on
    either side counts as flat."""
    breaks = []
    for coin in sorted(set(intended) | set(actual)):
        want, got = intended.get(coin, 0.0), actual.get(coin, 0.0)
        if abs(want - got) > step.get(coin, 0.0) / 2 + 1e-12:
            breaks.append(f"{coin}: intended {want:+.8g}, exchange holds {got:+.8g}")
    return breaks


def fill_markouts(fills: Iterable[dict], book: List[tuple], horizons_s=(1, 10, 60, 300),
                  max_gap_ms: int = 2000) -> List[dict]:
    """Each fill marked to the recorded mid at fill time + h: maker's side x
    (mid / price - 1) in bps, using the first book row at or after the target
    time and no later than `max_gap_ms` past it (else None). `book` rows are
    (t_ms, coin, mid)."""
    by_coin: Dict[str, List[tuple]] = {}
    for t, c, m in sorted(book):
        by_coin.setdefault(c, []).append((t, m))
    out = []
    for f in fills:
        rows = by_coin.get(f["coin"], [])
        times = [t for t, _ in rows]
        s = 1 if f["side"] == "B" else -1
        px, t0 = float(f["px"]), int(f["time"])
        r = {"oid": int(f["oid"]), "coin": f["coin"], "crossed": bool(f["crossed"])}
        for h in horizons_s:
            target = t0 + h * 1000
            i = bisect.bisect_left(times, target)
            ok = i < len(rows) and rows[i][0] - target <= max_gap_ms
            r[h] = s * (rows[i][1] / px - 1) * 1e4 if ok else None
        out.append(r)
    return out
