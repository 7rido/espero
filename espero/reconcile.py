"""Reconcile our record of orders against the exchange's record of fills (#40,
research/PREREGISTRATION_TESTNET.md). Pure: dicts in, lists of breaks out.

Our record, per order id: {"tif": "Alo" | "Ioc", "filled": size, "avg_px": IOC
average price or None}. The exchange's record: Hyperliquid `userFills` rows
(coin, px, sz, oid, crossed, fee, time). A break is any disagreement; the
pre-registration passes only with none.
"""
from __future__ import annotations

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
