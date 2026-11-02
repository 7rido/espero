"""Static HTML dashboard for the paper accounts.

Reads tsmom.db / xs.db / mf.db / paper.db and writes one self-contained file with
inline SVG. No server, no framework, no JavaScript dependencies -- open it in
a browser and it works offline.

    espero dashboard                 # -> dashboard.html
    espero dashboard --open          # also opens it
"""
from __future__ import annotations

import html
import json
import re
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from . import tca
from . import tsmom as tsm
from . import xs as xsm

CLASSES = [
    ("Equities", ["SPY"]),
    ("Bonds", ["TLT"]),
    ("Commodities", ["GLD", "USO"]),
    ("Crypto", ["BTC", "ETH"]),
]


def _read_account(path: Path) -> list[dict]:
    if not path.exists():
        return []
    db = sqlite3.connect(path)
    db.row_factory = sqlite3.Row
    try:
        rows = db.execute("SELECT * FROM account ORDER BY ts, id").fetchall()
    except sqlite3.OperationalError:
        return []
    finally:
        db.close()
    return [dict(r) for r in rows]


def _sparkline(values: list[float], w: int = 640, h: int = 160, pad: int = 10) -> str:
    if len(values) < 2:
        return f'<svg width="{w}" height="{h}"><text x="20" y="80" fill="#777" font-size="13">' \
               f'not enough history yet</text></svg>'
    lo, hi = min(values), max(values)
    span = (hi - lo) or 1e-9
    pts = []
    for i, v in enumerate(values):
        x = pad + (w - 2 * pad) * i / (len(values) - 1)
        y = h - pad - (h - 2 * pad) * (v - lo) / span
        pts.append(f"{x:.1f},{y:.1f}")
    up = values[-1] >= values[0]
    color = "#3aa76d" if up else "#d64545"
    return (f'<svg width="{w}" height="{h}" viewBox="0 0 {w} {h}">'
            f'<polyline fill="none" stroke="{color}" stroke-width="2" points="{" ".join(pts)}"/>'
            f'</svg>')


def _positions(latest: dict) -> dict:
    """Mark held units to the latest available price."""
    units = json.loads(latest.get("units") or "{}")
    if not units:
        return {}
    try:
        px = tsm.closes(tsm.load_series("2y")).iloc[-1]
    except Exception:  # noqa: BLE001 - dashboard must render offline
        return {a: 0.0 for a in units}
    return {a: u * float(px[a]) for a, u in units.items() if a in px}


def esc(v) -> str:
    """Text from a database or the network goes into HTML escaped."""
    return html.escape(str(v), quote=True)


def render(tsmom_db: Path = Path("tsmom.db"), paper_db: Path = Path("paper.db"),
           xs_db: Path = Path("xs.db"), offline: bool = False,
           mf_db: Optional[Path] = None, board: bool = False, mf_hl_db: Optional[Path] = None,
           readout: bool = False) -> str:
    """`offline=True` (the daily job's dry run) skips the live-signal preview and the
    signal board, the only network calls here. `mf_db`, `board` and `readout` are opt-in,
    so a render pointed at test databases never picks up the real ones."""
    rows = _read_account(tsmom_db)
    cards = []
    total = 0.0

    if rows:
        latest = rows[-1]
        cash = float(latest["cash"])
        stored = json.loads(latest.get("positions") or "{}")
        positions = {k: float(v) for k, v in stored.items()} or _positions(latest)
        equity = cash + sum(positions.values())
        total += equity
        deposited = sum(float(r.get("deposit") or 0) for r in rows)
        carry_total = sum(float(r.get("carry") or 0) for r in rows)
        vehicle = latest.get("vehicle") or "USD"
        apy = next((v.apy for v in __import__("espero.cash", fromlist=["x"]).DEFAULT_VEHICLES
                    if v.name == vehicle), 0.0)
        pnl = equity - deposited
        pnl_pct = 100 * pnl / deposited if deposited else 0.0
        weights = json.loads(latest.get("weights") or "{}")
        # live signals power the "what would I do now" preview; the stored snapshot
        # powers the audited decision. They are deliberately different numbers.
        try:
            if offline:
                raise RuntimeError("offline")
            live_sig = {k: float(v) for k, v in tsm.signals(tsm.load_series("2y")).items()}
        except Exception:  # noqa: BLE001
            live_sig = {}

        # prefer the snapshot taken at decision time; live signals are a fallback
        sig = {k: float(v) for k, v in json.loads(latest.get("signals") or "{}").items()}
        sig_note = "as of the last decision"
        if not sig and not offline:
            try:
                sig = tsm.signals(tsm.load_series("2y"))
                sig_note = "live (no decision snapshot stored)"
            except Exception:  # noqa: BLE001
                sig_note = ""

        def class_rows(assets):
            rows_out = []
            for a in assets:
                cur = positions.get(a, 0.0)
                tgt = weights.get(a, 0.0) * equity
                delta = tgt - cur
                act = "hold" if abs(delta) < 1 else ("buy" if delta > 0 else "sell")
                rows_out.append((a, sig.get(a), weights.get(a, 0.0), cur, tgt, delta, act))
            return rows_out

        def class_card(title, assets):
            rs = class_rows(assets)
            body = "".join(
                f"<tr><td>{esc(a)}</td>"
                f"<td class='num'>{('' if r is None else f'{100*r:+.1f}%')}</td>"
                f"<td class='num'>{100*w:.0f}%</td>"
                f"<td class='num'>{cur:,.2f}</td>"
                f"<td class='num'>{tgt:,.2f}</td>"
                f"<td class='num {('pos' if act == 'buy' else 'neg' if act == 'sell' else '')}'>"
                f"{act} {abs(delta):,.2f}</td></tr>"
                for a, r, w, cur, tgt, delta, act in rs
            )
            invested = sum(cur for *_, cur, _, _, _ in rs)
            target = sum(tgt for *_, tgt, _, _ in rs)
            return f"""
        <section class="card">
          <h2>{title} <span class="pill">{invested:,.0f} now → {target:,.0f} target</span></h2>
          <table>
            <thead><tr><th>asset</th><th class="num">52w</th><th class="num">target</th>
            <th class="num">now</th><th class="num">plan</th><th class="num">move</th></tr></thead>
            <tbody>{body}</tbody>
          </table>
        </section>"""

        # performance curve: equity net of money put in, so a deposit is not a gain
        cum, curve = 0.0, []
        for r in rows:
            cum += float(r.get("deposit") or 0)
            curve.append(float(r["equity"]) - cum)
        as_of = datetime.fromtimestamp(int(latest["ts"]), timezone.utc).date()

        cards.append(f"""
        <section class="card">
          <h2>Cross-asset trend <span class="pill">paper</span></h2>
          <div class="big">${equity:,.2f}</div>
          <div class="sub">as of {as_of} · cash ${cash:,.2f} ·
            {sum(1 for v in positions.values() if v > 0)} positions
            · {esc(sig_note)}</div>
          <div class="sub">deposited ${deposited:,.2f} · P&amp;L
            <span class="{'pos' if pnl >= 0 else 'neg'}">{pnl:+,.2f} ({pnl_pct:+.2f}%)</span>
            · cash in <b>{esc(vehicle)}</b> {100 * apy:.2f}% · carry ${carry_total:,.2f}</div>
          {_sparkline(curve)}
          <div class="sub">{len(rows)} journal entries · last action: {latest.get('note', '')}</div>
        </section>""")

        for title, assets in CLASSES:
            cards.append(class_card(title, assets))

        if live_sig:
            preview = []
            for a, r in live_sig.items():
                cur = positions.get(a, 0.0)
                tgt = (1 / 6) * equity if r > 0 else 0.0
                delta = tgt - cur
                if abs(delta) >= 1:
                    preview.append((a, r, tgt, delta))
            preview.sort(key=lambda x: -abs(x[3]))
            if preview:
                rows_html = "".join(
                    f"<tr><td>{esc(a)}</td><td class='num'>{100*r:+.1f}%</td>"
                    f"<td class='num'>{tgt:,.2f}</td>"
                    f"<td class='num {('pos' if d > 0 else 'neg')}'>"
                    f"{'buy' if d > 0 else 'sell'} {abs(d):,.2f}</td></tr>"
                    for a, r, tgt, d in preview
                )
            else:
                rows_html = "<tr><td colspan='4' class='muted'>nothing would change</td></tr>"
            cards.append(f"""
        <section class="card">
          <h2>Next rebalance preview <span class="pill">hypothetical</span></h2>
          <div class="sub">live signals · what the rule would do if it rebalanced right now.
            The real decision happens on the first trading day of the month.</div>
          <table>
            <thead><tr><th>asset</th><th class="num">52w</th><th class="num">target</th>
            <th class="num">move</th></tr></thead>
            <tbody>{rows_html}</tbody>
          </table>
        </section>""")

        cards.append(f"""
        <section class="card">
          <h2>Cash <span class="pill">{esc(vehicle)}</span></h2>
          <div class="big">${cash:,.2f}</div>
          <div class="sub">10% kept liquid · remainder swept to {esc(vehicle)} at {100 * apy:.2f}%
            · carry to date ${carry_total:,.2f}</div>
        </section>""")

    if xs_db.exists():
        con = sqlite3.connect(xs_db)
        con.row_factory = sqlite3.Row
        try:
            xr = con.execute("SELECT * FROM xs_account ORDER BY ts, id").fetchall()
        except sqlite3.OperationalError:
            xr = []
        con.close()
        if xr:
            latest = dict(xr[-1])
            equity = float(latest["equity"])
            total += equity
            pos = json.loads(latest.get("positions") or "{}")
            sig = json.loads(latest.get("signals") or "{}")
            w = json.loads(latest.get("weights") or "{}")
            deposited = sum(float(r["deposit"] or 0) for r in xr)
            pnl = equity - deposited
            cum, curve = 0.0, []
            for r in xr:
                cum += float(r["deposit"] or 0)
                curve.append(float(r["equity"]) - cum)
            top = sorted(pos.items(), key=lambda kv: -kv[1])[:10]
            body = "".join(
                f"<tr><td>{esc(c)}</td><td class='num'>{100*sig.get(c, 0):+.1f}%</td>"
                f"<td class='num'>{100*w.get(c, 0):.0f}%</td>"
                f"<td class='num'>{v:,.2f}</td></tr>"
                for c, v in top
            ) or "<tr><td colspan='4' class='muted'>all cash</td></tr>"
            as_of = datetime.fromtimestamp(int(latest["ts"]), timezone.utc).date()
            cards.append(f"""
        <section class="card">
          <h2>Cross-sectional weekly <span class="pill">paper · top 10 of 42</span></h2>
          <div class="big">${equity:,.2f}</div>
          <div class="sub">as of {as_of} · {sum(1 for v in pos.values() if v > 0)} positions
            · cash ${float(latest['cash']):,.2f}
            · last action: {latest.get('note', '')}</div>
          <div class="sub">costs: {tca.format_line(tca.account_tca(xs_db, "xs_account", xsm.COST))}</div>
          <div class="sub">deposited ${deposited:,.2f} · P&amp;L
            <span class="{'pos' if pnl >= 0 else 'neg'}">{pnl:+,.2f}</span></div>
          {_sparkline(curve)}
          <table>
            <thead><tr><th>coin</th><th class="num">7d</th><th class="num">weight</th>
            <th class="num">value</th></tr></thead>
            <tbody>{body}</tbody>
          </table>
        </section>""")

    if mf_db is not None and Path(mf_db).exists():
        cards.append(_mf_card(Path(mf_db)))
        total += _mf_equity(Path(mf_db))
    if mf_hl_db is not None and Path(mf_hl_db).exists():
        cards.append(_mf_card(Path(mf_hl_db), "#8 on Hyperliquid prices", "shadow · information only"))
        total += _mf_equity(Path(mf_hl_db))
    if board and not offline:
        cards.append(_board_card())

    for name, path, label in (("Paper (bar strategy)", paper_db, "paper"),):
        if not path.exists():
            continue
        db = sqlite3.connect(path)
        try:
            eq = db.execute("SELECT ts, equity FROM equity ORDER BY ts").fetchall()
        except sqlite3.OperationalError:
            db.close()
            continue
        db.close()
        if not eq:
            continue
        values = [float(e[1]) for e in eq]
        total += values[-1]
        as_of = datetime.fromtimestamp(int(eq[-1][0]), timezone.utc).date()
        cards.append(f"""
        <section class="card">
          <h2>{esc(name)} <span class="pill">{esc(label)}</span></h2>
          <div class="big">${values[-1]:,.2f}</div>
          <div class="sub">as of {as_of} · {len(values)} marks</div>
          {_sparkline(values)}
        </section>""")

    if not cards:
        cards.append('<section class="card"><h2>No accounts yet</h2>'
                     '<div class="sub">run <code>espero tsmom --cash 100</code> first</div></section>')

    if readout:
        cards.append(_readout_card())

    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    return f"""<!doctype html>
<html><head><meta charset="utf-8"><title>espero dashboard</title>
<style>
  :root {{ color-scheme: dark; }}
  body {{ background:#111315; color:#e6e6e6; font:14px/1.5 ui-sans-serif,system-ui,-apple-system,sans-serif;
         margin:0; padding:32px; }}
  h1 {{ font-size:18px; font-weight:600; margin:0 0 4px; }}
  .muted, .sub {{ color:#8b8f94; font-size:12px; }}
  .wrap {{ max-width:760px; margin:0 auto; }}
  .top {{ display:flex; justify-content:space-between; align-items:baseline; margin-bottom:24px; }}
  .total {{ font-size:24px; font-weight:600; }}
  .card {{ background:#191c1f; border:1px solid #262a2e; border-radius:10px; padding:20px; margin-bottom:16px; }}
  h2 {{ font-size:14px; font-weight:600; margin:0 0 8px; color:#c9ced4; }}
  .pill {{ font-size:10px; text-transform:uppercase; letter-spacing:.06em; color:#8b8f94;
           border:1px solid #33383d; border-radius:999px; padding:2px 8px; margin-left:6px; }}
  .big {{ font-size:28px; font-weight:600; letter-spacing:-.02em; }}
  table {{ width:100%; border-collapse:collapse; margin-top:12px; font-size:13px; }}
  th {{ text-align:left; font-weight:500; color:#8b8f94; font-size:11px; text-transform:uppercase;
        letter-spacing:.04em; border-bottom:1px solid #262a2e; padding:6px 0; }}
  td {{ padding:6px 8px 6px 0; border-bottom:1px solid #1e2225; vertical-align:top; }}
  .num {{ text-align:right; font-variant-numeric:tabular-nums; }}
  .pos {{ color:#3aa76d; }} .neg {{ color:#d64545; }}
  svg {{ display:block; margin:14px 0 4px; }}
  code {{ background:#24282c; padding:1px 5px; border-radius:4px; }}
</style></head>
<body><div class="wrap">
  <div class="top">
    <div><h1>espero</h1><div class="muted">paper accounts · generated {now}</div></div>
    <div class="total">${total:,.2f}</div>
  </div>
  {''.join(cards)}
  <div class="muted">Not investment advice. Paper only — no exchange keys, no orders.</div>
</div></body></html>"""


def _mf_rows(path: Path) -> list:
    con = sqlite3.connect(path)
    con.row_factory = sqlite3.Row
    try:
        return [dict(r) for r in con.execute("SELECT * FROM mf_account ORDER BY ts, id")]
    except sqlite3.OperationalError:
        return []
    finally:
        con.close()


def _mf_equity(path: Path) -> float:
    rows = _mf_rows(path)
    return float(rows[-1]["equity"]) if rows else 0.0


def _mf_card(path: Path, title: str = "#8 multifactor, forward test", pill: str = "") -> str:
    """#8's forward test (research/FORWARD_MF.md), or its Hyperliquid shadow."""
    from . import mf
    rows = _mf_rows(path)
    if not rows:
        return ""
    latest = rows[-1]
    equity = float(latest["equity"])
    pos = json.loads(latest.get("positions") or "{}")
    w = json.loads(latest.get("weights") or "{}")
    deposited = sum(float(r["deposit"] or 0) for r in rows)
    pnl = equity - deposited
    cum, curve = 0.0, []
    for r in rows:
        cum += float(r["deposit"] or 0)
        curve.append(float(r["equity"]) - cum)
    body = "".join(f"<tr><td>{esc(c)}</td><td class='num'>{100 * w.get(c, 0):.1f}%</td>"
                   f"<td class='num'>{v:,.2f}</td></tr>"
                   for c, v in sorted(pos.items(), key=lambda kv: -kv[1])) \
        or "<tr><td colspan='3' class='muted'>all cash</td></tr>"
    decided = (f"last decision: Sunday {esc(latest['decision'])}" if latest.get("decision")
               else f"holding cash until the first fill on {mf.FORWARD_START.date()}")
    as_of = datetime.fromtimestamp(int(latest["ts"]), timezone.utc).date()
    window = f"{mf.FORWARD_START.date()} → {mf.FORWARD_END.date()}"
    return f"""
        <section class="card">
          <h2>{esc(title)} <span class="pill">{esc(pill or "paper · " + window)}</span></h2>
          <div class="big">${equity:,.2f}</div>
          <div class="sub">as of {as_of} · {decided} · last action: {esc(latest.get('note', ''))}</div>
          <div class="sub">deposited ${deposited:,.2f} · P&amp;L
            <span class="{'pos' if pnl >= 0 else 'neg'}">{pnl:+,.2f}</span></div>
          {_sparkline(curve)}
          <table>
            <thead><tr><th>coin</th><th class="num">weight</th><th class="num">value</th></tr></thead>
            <tbody>{body}</tbody>
          </table>
        </section>"""


def _board_card() -> str:
    """#15's trend readings (espero board): a scanner, since #15 failed its test."""
    try:
        import pandas as pd

        from . import board as brd
        from . import trend
        frames, errors = brd.fetch_frames(trend.symbols())
        v = brd.view(frames, pd.Timestamp.now(tz="UTC").tz_localize(None))
    except Exception as exc:  # noqa: BLE001 - the board is context, never a reason to lose the page
        return (f'<section class="card"><h2>Signal board</h2>'
                f'<div class="sub">unavailable: {esc(type(exc).__name__)}: {esc(str(exc)[:160])}</div></section>')
    body = "".join(f"<tr><td>{esc(ln.cls)}</td><td>{esc(ln.symbol)}</td><td class='num'>{esc(brd.price(ln.last))}</td>"
                   f"<td>{esc(ln.arrows)}</td><td class='num'>{esc(ln.today)}</td><td>{esc(ln.change)}</td>"
                   f"<td>{esc(ln.flip)}</td></tr>" for ln in v["lines"])
    failed = f" · {len(errors)} symbols failed to load" if errors else ""
    return f"""
        <section class="card">
          <h2>Signal board <span class="pill">scanner · #15 failed its test</span></h2>
          <div class="sub">1/3/12-month trend per asset: above (▲) or below (▽) the close then. No sizes, no
            alerts: the timing added no return beyond volatility sizing (research/RESULTS_TREND.md).
            Bars through {(v['today'] - pd.Timedelta(days=1)).date()}; next reading {v['next'].date()}{failed}.</div>
          <table>
            <thead><tr><th>class</th><th>asset</th><th class="num">last</th><th>1m 3m 12m</th>
            <th class="num">up</th><th>change</th><th>nearest flip</th></tr></thead>
            <tbody>{body}</tbody>
          </table>
        </section>"""


READOUT = Path(__file__).resolve().parent.parent / "research" / "OPERATOR_READOUT.md"


def _bold(text: str) -> str:
    return re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", esc(text))


def readout_parts(text: str) -> tuple[list[list[str]], list[str]]:
    """The first table's rows, without its header, and the bullets under "## Costs"."""
    lines = text.splitlines()
    start = next((i for i, ln in enumerate(lines) if ln.startswith("|")), len(lines))
    rows = []
    for ln in lines[start + 2:]:
        if not ln.startswith("|"):
            break
        rows.append([cell.strip() for cell in ln.strip().strip("|").split(" | ")])
    costs, inside = [], False
    for ln in lines:
        if ln.startswith("## "):
            inside = ln.startswith("## Costs")
        elif inside and ln.startswith("- "):
            costs.append(ln[2:])
    return rows, costs


def _readout_card(path: Optional[Path] = None) -> str:
    """research/OPERATOR_READOUT.md as a card, so the page and the document can't disagree. Context, not signals."""
    try:
        rows, costs = readout_parts((path or READOUT).read_text(encoding="utf-8"))
    except OSError:
        return ""
    if not rows:
        return ""
    body = "".join("<tr>" + "".join(f"<td>{_bold(c)}</td>" for c in row) + "</tr>" for row in rows)
    cost_lines = "".join(f"<div class='sub'>{_bold(c)}</div>" for c in costs)
    return f"""
        <section class="card">
          <h2>Reading the market <span class="pill">context · not signals · #51–#57</span></h2>
          <div class="sub">What usually followed on 24 calm first-of-month days, with no known crash. Not a
            forecast, and nothing here sets a rule, a rating or an order (research/OPERATOR_READOUT.md).</div>
          <table>
            <thead><tr><th>what you can see</th><th>what usually followed</th><th>how much to trust it</th></tr></thead>
            <tbody>{body}</tbody>
          </table>
          <h2 style="margin-top:16px">Market order costs</h2>
          {cost_lines}
        </section>"""


def write(out: str | Path = "dashboard.html", **paths) -> Path:
    out = Path(out)
    out.write_text(render(**paths), encoding="utf-8")
    return out
