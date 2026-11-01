"""Command line entry point: `python -m espero ...` or the `espero` script."""
from __future__ import annotations

import argparse
import json
import os
import pathlib
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import pandas as pd

from . import dashboard as dash
from . import data
from . import features as fx
from . import tsmom as tsm
from . import xs as xsm
from .backtest import Config, run
from .broker import BrokerError, broker_from_env
from .journal import Journal
from .live import LiveConfig, LiveTrader
from .loop import run_loop
from .paper import PaperConfig, PaperTrader
from .report import buy_and_hold, equity_png, format_matrix, matrix
from .venues import VENUES


def _cmd_fetch(args: argparse.Namespace) -> int:
    print(f"fetching {args.product} {args.granularity}s x {args.days}d ...")
    df = data.fetch(args.product, args.days, args.granularity)
    out = Path(args.out) if args.out else data.candle_path(args.product, args.granularity)
    data.save(df, out)
    print(f"{len(df)} candles -> {out}")
    print(f"{df['time'].iloc[0]} .. {df['time'].iloc[-1]}")
    return 0


def _waiting(granularity: int) -> str:
    """'no new closed bar' with the time until the next one closes, so a quiet
    loop reads as waiting rather than broken."""
    now = int(time.time())
    next_close = (now // granularity + 1) * granularity
    mins = max(0, (next_close - now) // 60)
    opened = time.strftime("%H:%M", time.gmtime(next_close - granularity))
    closes = time.strftime("%H:%M", time.gmtime(next_close))
    return f"no new closed bar  ·  the {opened} bar closes at {closes} UTC, in {mins} min"


def _load(path: str):
    p = Path(path)
    if not p.exists():
        print(f"no data at {p}. run: espero fetch BTC-USD --days 1460", file=sys.stderr)
        return None
    return data.load(p)


def _cmd_backtest(args: argparse.Namespace) -> int:
    df = _load(args.data)
    if df is None:
        return 2
    cfg = Config(fee=args.fee_bps / 1e4, timing=args.timing, sizing=args.sizing)
    m = run(df, cfg).metrics()
    width = max(len(k) for k in m)
    for k, v in m.items():
        print(f"{k:<{width}}  {v:.4f}" if isinstance(v, float) else f"{k:<{width}}  {v}")
    return 0


def _cmd_matrix(args: argparse.Namespace) -> int:
    df = _load(args.data)
    if df is None:
        return 2
    print(f"{len(df)} bars  {df['dt'].iloc[0].date()} .. {df['dt'].iloc[-1].date()}\n")
    print(format_matrix(matrix(df), buy_and_hold(df)))
    return 0


def _cmd_chart(args: argparse.Namespace) -> int:
    df = _load(args.data)
    if df is None:
        return 2
    out = equity_png(df, Path(args.out))
    print(f"wrote {out}")
    return 0


def _cmd_paper_compare(args: argparse.Namespace) -> int:
    from .paper import compare_venues

    src = Journal(args.journal)
    bars = [dict(r) for r in src.db.execute(
        "SELECT ts, open, high, low, close, volume FROM bars WHERE product=? ORDER BY ts",
        (args.product,)).fetchall()]
    src.db.close()
    if len(bars) < 60:
        print(f"only {len(bars)} bars in {args.journal}; need at least 60")
        return 2
    venues = [v.strip() for v in args.venues.split(",") if v.strip()]
    unknown = [v for v in venues if v not in VENUES]
    if unknown:
        print(f"unknown venue(s): {', '.join(unknown)}; known: {', '.join(sorted(VENUES))}")
        return 2
    rows = compare_venues(bars, venues, product=args.product,
                          granularity=args.granularity, initial=args.cash)
    first = datetime.fromtimestamp(bars[0]["ts"], timezone.utc).strftime("%m-%d %H:%M")
    last = datetime.fromtimestamp(bars[-1]["ts"], timezone.utc).strftime("%m-%d %H:%M")
    print(f"{len(bars)} bars of {args.product}, {first} .. {last} UTC; same signals, same fills\n")
    print(f"{'venue':<28}{'trades':>7}{'wins':>6}{'fees':>9}{'funding':>9}{'P&L':>9}{'equity':>10}")
    for r in rows:
        print(f"{r['name']:<28}{r['trades']:>7}{r['wins']:>6}{r['fees']:>9.2f}"
              f"{r['funding']:>9.2f}{r['pnl']:>+9.2f}{r['equity']:>10.2f}")
    print("\nfees are taker (the loop fills at the next open); perp funding assumed "
          "constant at the venue's average, longs pay")
    return 0


def _cmd_fees(args: argparse.Namespace) -> int:
    """Your Coinbase maker/taker rates from the Exchange API (read-only)."""
    from . import coinbase_fees as cf
    from .broker import load_env

    load_env()
    try:
        f = cf.fetch()
    except cf.FeesError as exc:
        print(f"cannot read fees: {exc}")
        return 2
    v = VENUES["coinbase"]
    same = abs(f.maker_bps - v.maker_bps) < 0.05 and abs(f.taker_bps - v.taker_bps) < 0.05
    print(f"Coinbase fees for this account (30-day volume ${f.usd_volume:,.2f})")
    print(f"  maker {f.maker:.4%} ({f.maker_bps:.1f} bps)   taker {f.taker:.4%} ({f.taker_bps:.1f} bps)")
    print(f"  venue table 'coinbase': maker {v.maker_bps:.1f} / taker {v.taker_bps:.1f} bps  "
          f"[{'matches' if same else 'differs'}]")
    print(f"  round trip at taker {2 * f.taker_bps:.0f} bps, at maker {2 * f.maker_bps:.0f} bps")
    print(f"  paper loops fill at the next open (taker): add --fee-bps {f.taker_bps:.1f} "
          f"to espero paper / espero degen paper")
    return 0


def _cmd_paper(args: argparse.Namespace) -> int:
    from .lock import JournalBusy, JournalLock

    try:
        with JournalLock(args.state):
            return _paper_loop(args)
    except JournalBusy as exc:
        print(f"refusing to start: {exc}")
        return 3


def _cmd_paper_open(args: argparse.Namespace) -> int:
    """Buy by hand: the running paper loop queues a BUY of --usd dollars on its next step
    and fills it at the next bar's open (fee, slippage, the usual stop and target)."""
    from .lock import JournalBusy, JournalLock

    try:
        with JournalLock(args.state):
            print(f"no paper loop is running on {args.state}: start it first, then run paper-open again")
            return 2
    except JournalBusy:
        Path(str(args.state) + ".open").write_text(json.dumps({"usd": args.usd}))
        print(f"queued: the running loop buys ${args.usd:,.2f} at the next bar's open, recorded as 'manual'.\n"
              f"watch its window for 'holding ... P&L'; take it with espero paper-close --state {args.state}")
        return 0


def _cmd_paper_close(args: argparse.Namespace) -> int:
    """Take profit (or cut) by hand. With a paper loop running on the journal, leave a
    request it picks up on its next step: a SELL queued and filled at the next bar's
    open. With none running, close now at the latest recorded bar's close."""
    from .lock import JournalBusy, JournalLock

    request = Path(str(args.state) + ".close")
    try:
        with JournalLock(args.state):
            journal = Journal(args.state)
            try:
                opens = journal.open_positions()
                product = args.product or (opens[0].product if len(opens) == 1 else None)
                if product is None:
                    print("no open position" if not opens else
                          f"several open positions ({', '.join(p.product for p in opens)}): pass --product")
                    return 0 if not opens else 2
                cfg = (PaperConfig.for_venue(args.venue, product=product) if args.venue
                       else PaperConfig(product=product))
                if args.fee_bps is not None:
                    cfg.fee = args.fee_bps / 1e4
                trader = PaperTrader(journal, cfg)
                row = journal.db.execute("SELECT ts, close FROM bars WHERE product=? ORDER BY ts DESC LIMIT 1",
                                         (product,)).fetchone()
                if row is None:
                    print(f"no bars recorded for {product}")
                    return 2
                print(f"no loop is running on {args.state}: closing now at the latest bar's close "
                      f"({row['close']:.2f}), fee {1e4 * cfg.fee:.1f} bps")
                print("  ", trader.close_now(float(row["close"]), int(row["ts"])))
            finally:
                journal.close()
            request.unlink(missing_ok=True)
            return 0
    except JournalBusy as exc:
        request.write_text("manual close requested\n")
        print(f"a loop is running on this journal ({exc}).\n"
              f"queued: it sells at the next bar's open, recorded as 'manual' ({request.name})")
        return 0


def _paper_loop(args: argparse.Namespace) -> int:
    from .data import recent_closed_bars

    hl_source = getattr(args, "source", "coinbase") == "hyperliquid"
    if hl_source:
        from . import hyperliquid as hl
        fetch_bars = hl.closed_bars
        venue = args.venue or "hyperliquid"
    else:
        fetch_bars, venue = recent_closed_bars, args.venue
    journal = Journal(args.state)
    if venue:
        cfg = PaperConfig.for_venue(venue, product=args.product,
                                    granularity=args.granularity, initial=args.cash)
        if args.fee_bps is not None:
            cfg.fee = args.fee_bps / 1e4
    else:
        cfg = PaperConfig(product=args.product, granularity=args.granularity,
                          initial=args.cash, fee=(args.fee_bps or 0.0) / 1e4)
    if hl_source:
        # the perp's own hourly rates, as Hyperliquid publishes them, instead of an assumed constant
        cfg.funding_rates, cfg.funding_8h, cfg.funding_period = hl.funding_rates(args.product), 0.0, 3600
    print(f"prices: {'Hyperliquid perp ' + hl.hl_coin(args.product) if hl_source else 'Coinbase ' + args.product}"
          f" · fees {1e4 * cfg.fee:.1f} bps per side"
          + (" · funding: Hyperliquid's actual hourly rates" if hl_source else
             f", funding {1e4 * cfg.funding_8h:.2f} bps per 8h on longs" if cfg.funding_8h else ""))
    trader = PaperTrader(journal, cfg)
    request = Path(str(args.state) + ".close")
    open_request = Path(str(args.state) + ".open")

    def step() -> None:
        if request.exists():
            # `espero paper-close` asked for a manual close: queue it, fill at the next open
            known = journal.last_bar_ts(args.product)
            if known is not None:
                print("  ", trader.request_close(known))
                request.unlink()
        if open_request.exists():
            # `espero paper-open` asked for a manual buy of N dollars at the next open
            row = journal.db.execute("SELECT ts, close FROM bars WHERE product=? ORDER BY ts DESC LIMIT 1",
                                     (args.product,)).fetchone()
            if row is not None:
                usd = float(json.loads(open_request.read_text() or "{}").get("usd", 0))
                print("  ", trader.request_open(int(row["ts"]), usd, float(row["close"])))
                open_request.unlink()
        df = fetch_bars(args.product, args.granularity, args.seed)
        if df.empty:
            print("no candles returned")
            return
        known = journal.last_bar_ts(args.product)
        fresh = [r for r in df.to_dict("records") if int(r["ts"]) > (known or 0)]
        if not fresh:
            print(_waiting(args.granularity))
            return
        if known is None:
            # a new journal: seed history silently, trade only the most recent closed bar
            with journal.transaction():
                for bar in fresh[:-1]:
                    journal.add_bar(args.product, bar)
            fresh = fresh[-1:]
        elif len(fresh) > 1:
            # the loop slept or was down: every missed bar gets its stops, fills and funding
            print(f"catching up {len(fresh)} bars")
        for bar in fresh:
            print(f"bar {bar['dt']} close={bar['close']:.2f}")
            for event in trader.on_bar(bar):
                print("  ", event)
        print(f"   cash={trader.cash:.2f}  equity={trader._equity(float(fresh[-1]['close'])):.2f}")
        if trader.position is not None:
            print("  ", trader.holding(float(fresh[-1]["close"])), " (espero paper-close to take it)")

    if args.loop:
        print(f"paper trading {args.product} {args.granularity}s -> {args.state} "
              f"(ctrl-c to stop)")
        try:
            run_loop(step, args.interval, label=f"paper {args.product}")
        except KeyboardInterrupt:
            print("stopped")
        finally:
            journal.close()
        return 0

    step()
    journal.close()
    return 0


# ------------------------------------------------------------------ degen (#10)
def _degen_defaults(args: argparse.Namespace) -> argparse.Namespace:
    """Fill the source-dependent defaults: the venue whose fees are charged and the
    paper journal, kept apart per source so Coinbase spot and Hyperliquid perp bars
    never share one book."""
    hl = getattr(args, "source", "hyperliquid") == "hyperliquid"
    if getattr(args, "venue", None) is None:
        args.venue = "hyperliquid" if hl else "binanceus"
    if hasattr(args, "state") and not args.state:
        args.state = "degen-hl.db" if hl else "degen.db"
    return args


def _degen_bars(args: argparse.Namespace):
    """Closed bars (product, granularity, limit) from the chosen source, looked up at
    call time."""
    if getattr(args, "source", "hyperliquid") == "hyperliquid":
        from . import hyperliquid as hl
        return hl.closed_bars
    return data.recent_closed_bars


def _degen_universe(args: argparse.Namespace) -> list:
    if getattr(args, "source", "hyperliquid") == "hyperliquid":
        from . import hyperliquid as hl
        print(f"ranking Hyperliquid perps by 24h dollar volume (top {args.top}) ...", flush=True)
        uni = hl.degen_universe(top=args.top)
    else:
        print(f"ranking Coinbase altcoins by 24h dollar volume (top {args.top}) ...", flush=True)
        uni = data.degen_universe(top=args.top)
    print(f"{len(uni)} coins, {uni[0]['product']} .. {uni[-1]['product']}" if uni else "no products")
    return uni


def _degen_table(rows: list, venue: str) -> None:
    from .venues import round_trip_bps

    cost = round_trip_bps(venue, maker=False)
    try:
        from rich.console import Console
        from rich.table import Table
    except ImportError:  # plain text is fine
        print(f"{'coin':<12}{'status':<20}{'score':>6}{'burst':>8}{'vol_z':>7}{'rng/atr':>8}{'$vol 24h':>12}")
        for r in rows:
            if r.get("error"):
                print(f"{r['product']:<12}{'error':<20}  {r['error']}")
                continue
            print(f"{r['product']:<12}{r['status']:<20}{r['score']:>6.2f}{1e4 * r['burst']:>+8.0f}"
                  f"{r['vol_z']:>7.1f}{r['range_x']:>8.1f}{r['dollar_volume']:>12,.0f}")
        print(f"\nburst in bps over the last hour; round trip on {venue} costs {cost:.0f} bps taker")
        return
    t = Table(title="打板 — altcoins moving now, 5m bars", show_lines=False)
    for col, just in (("coin", "left"), ("status", "left"), ("score", "right"), ("burst bps", "right"),
                      ("vol z", "right"), ("rng/ATR", "right"), ("ATR bps", "right"), ("$M 24h", "right")):
        t.add_column(col, justify=just)
    for r in rows:
        if r.get("error"):
            t.add_row(r["product"], f"[red]{r['error'][:40]}[/red]", "", "", "", "", "", "")
            continue
        style = "bold green" if r["status"] == "BREAKOUT" else ("yellow" if r["status"] == "near" else "")
        st = f"[{style}]{r['status']}[/{style}]" if style else r["status"]
        atr_bps = 1e4 * float(r["atr"]) / float(r["close"]) if r["close"] else float("nan")
        t.add_row(r["product"], st, f"{r['score']:.2f}", f"{1e4 * r['burst']:+.0f}", f"{r['vol_z']:.1f}",
                  f"{r['range_x']:.1f}", f"{atr_bps:.0f}", f"{r['dollar_volume'] / 1e6:.1f}")
    c = Console()
    c.print(t)
    c.print(f"[grey58]stop is 2 ATR, target 3 ATR; a round trip on {venue} costs {cost:.0f} bps taker, "
            f"so the ATR column is the edge budget each stop risks[/grey58]")




def _testnet_exchange():
    from .broker import load_env
    from .hl_exchange import TestnetExchange

    load_env()
    return TestnetExchange()


def _cmd_hl_order(args: argparse.Namespace) -> int:
    """Place one resting testnet order. ALO by default: rejected rather than crossing."""
    from .hl_exchange import TestnetRefused
    try:
        ex = _testnet_exchange()
        r = ex.limit(args.coin.upper(), args.side, args.size, args.price, tif=args.tif,
                     reduce_only=args.reduce_only)
    except TestnetRefused as exc:
        print(f"refused: {exc}")
        return 2
    print(f"testnet {r.coin} {r.side} {r.size} @ {r.price} {r.tif}{' reduce-only' if args.reduce_only else ''}"
          f" -> {r.status}" + (f" oid {r.oid}" if r.oid else "") + (f"  {r.error}" if r.error else "")
          + (f"  filled {r.filled} @ {r.avg_px}" if r.filled else ""))
    return 0 if r.status != "error" else 1


def _cmd_hl_orders(args: argparse.Namespace) -> int:
    from .hl_exchange import TestnetRefused
    try:
        ex = _testnet_exchange()
    except TestnetRefused as exc:
        print(f"refused: {exc}")
        return 2
    if args.cancel:
        coin, oid = args.cancel
        print(f"cancel {coin} {oid}: {'ok' if ex.cancel(coin.upper(), int(oid)) else 'failed'}")
        return 0
    orders = ex.open_orders()
    print(f"testnet {ex.address}: {len(orders)} open orders")
    for o in orders:
        print(f"  {o['coin']:<8}{o['side']:<3}{float(o['sz']):>12,.4f} @ {float(o['limitPx']):<12,.6g} oid {o['oid']}")
    fills = ex.fills(int(time.time()) - args.hours * 3600)
    print(f"{len(fills)} fills in the last {args.hours}h")
    for f in fills[-20:]:
        print(f"  {datetime.fromtimestamp(int(f['time']) // 1000, timezone.utc):%m-%d %H:%M}  {f['coin']:<8}"
              f"{f['side']:<3}{float(f['sz']):>12,.4f} @ {float(f['px']):<12,.6g} fee {float(f.get('fee', 0)):.4f}")
    return 0

def _cmd_hl_account(args: argparse.Namespace) -> int:
    """Read-only Hyperliquid account snapshot by public address. Testnet unless
    HL_NETWORK=mainnet or --mainnet; no key is read and nothing is signed."""
    from . import hyperliquid as hl
    from .broker import load_env

    load_env()
    address = args.address or os.environ.get("HL_WALLET_ADDRESS", "")
    if not address:
        print("no address: pass one or set HL_WALLET_ADDRESS in .env (see .env.example)")
        return 2
    # the account view is a development tool: testnet unless told otherwise
    testnet = (True if args.testnet else False if args.mainnet
               else os.environ.get("HL_NETWORK", "testnet").strip().lower() != "mainnet")
    url = hl.info_url(testnet=testnet)
    st = hl.user_state(address, fetch=lambda body: hl.post(body, url))
    mm = hl.margin_mode(address, fetch=lambda body: hl.post(body, url))
    unified = mm["mode"] in ("unifiedAccount", "portfolioMargin")
    print(f"{'testnet' if testnet else 'MAINNET'}  {address}  ({mm['mode']})")
    if unified:
        print(f"margin (spot USDC) {mm['spot_usdc']:,.2f}  on hold {mm['spot_hold']:,.2f}  "
              f"-- a unified account margins perps with spot USDC, so the perp-only figures below stay 0")
    print(f"{'perp ' if unified else ''}equity {st['equity']:,.2f}  margin used {st['margin_used']:,.2f}  "
          f"notional {st['notional']:,.2f}  withdrawable {st['withdrawable']:,.2f}")
    if not unified and mm["spot_usdc"]:
        print(f"spot USDC {mm['spot_usdc']:,.2f} (not perp margin until transferred)")
    if not st["positions"]:
        print("no open positions")
    for p in st["positions"]:
        liq = f"{p['liquidation']:,.4g}" if p["liquidation"] else "-"
        print(f"  {p['coin']:<8}{p['side']:<6}{p['size']:>12,.4f} @ {p['entry']:<12,.4g}"
              f"{p['leverage']:>4.0f}x  uPnL {p['unrealized']:>+9.2f}  "
              f"funding {p['funding_paid']:>+8.2f}  liq {liq}")
    return 0


def _cmd_carry_scan(args: argparse.Namespace) -> int:
    """What Hyperliquid perps are paying shorts right now (#11). Read-only, no key.
    Always mainnet: the testnet's funding is not the market's."""
    from . import carry
    from . import hyperliquid as hl

    df = carry.scan(hl.asset_contexts(fetch=lambda b: hl.post(b, hl.info_url(testnet=False))), top=args.top)
    print(f"{'coin':<8}{'mark':>12}{'funding ann':>13}{'OI $M':>9}{'24h $M':>9}  state")
    for r in df.itertuples():
        state = ("ENTER" if r.funding_ann > carry.ENTER_ANN else
                 "hold" if r.funding_ann >= carry.EXIT_ANN else "exit")
        print(f"{r.coin:<8}{r.mark:>12,.4g}{r.funding_ann:>+12.1%}{r.open_interest_m:>9,.0f}"
              f"{r.day_volume_m:>9,.0f}  {state}")
    print(f"\nhourly funding x 8760; the rule enters above {carry.ENTER_ANN:.0%} on the trailing-week mean "
          f"and exits below {carry.EXIT_ANN:.0%}. This is the spot rate, not the trailing mean. "
          "Idle market = 10.95%.")
    return 0


def _cmd_carry_paper(args: argparse.Namespace) -> int:
    """#12 forward paper book on live Hyperliquid funding. One loop per journal."""
    from .lock import JournalBusy, JournalLock
    try:
        with JournalLock(args.state):
            return _carry_loop(args)
    except JournalBusy as exc:
        print(exc)
        return 3


def _carry_loop(args: argparse.Namespace) -> int:
    from . import carry_paper as cp

    book = cp.CarryBook(args.state, costs=args.costs, initial=args.cash)
    c = book.c
    mirror = None
    if getattr(args, "execute_testnet", False):
        from .hl_exchange import TestnetMirror, TestnetRefused
        try:
            ex = _testnet_exchange()
        except TestnetRefused as exc:
            print(f"refused: {exc}")
            return 2
        mirror = TestnetMirror(book.db, ex)
        print(f"TESTNET mirror on: perp leg shadowed with ALO orders from {ex.address}; spot leg stays paper")
    print(f"carry paper book ({args.costs}): spot {1e4 * c['spot_fee']:.1f} bps, perp {1e4 * c['perp_fee']:.2f} bps, "
          f"slippage {1e4 * c['slippage']:.1f} bps per leg per side; swap gap {book.swap_gap:.0%}, "
          f"min hold {book.min_hold // 24}d; cash {book.cash:.2f}, {len(book.open_positions())} open -> {args.state}")
    state = {"universe": [], "refreshed": 0.0}

    def step() -> None:
        if time.time() - state["refreshed"] > 86400:
            try:
                state["universe"] = cp.universe(args.top)
                state["refreshed"] = time.time()
                print(f"universe ({len(state['universe'])}): {' '.join(state['universe'])}")
            except Exception as exc:  # noqa: BLE001 - keep the last universe
                print(f"universe refresh failed ({type(exc).__name__}: {exc}); "
                      f"keeping {len(state['universe'])} coins, retrying in 5 min")
                state["refreshed"] = time.time() - 86400 + 300
        last = book.last_ts()
        if last is not None and time.time() < last + 3600:
            nxt = datetime.fromtimestamp(last + 3600, timezone.utc).strftime("%H:%M")
            print(f"hour {cp.stamp(last)} booked  ·  next settlement {nxt} UTC")
            return
        # held coins are always fetched: a hedge is managed until it is closed,
        # even after its coin leaves the top-N; new entries stay inside the universe
        universe = list(state["universe"])
        coins = universe + [p["coin"] for p in book.open_positions() if p["coin"] not in universe]
        hours = cp.settled_hours(coins, since_ts=last)
        if not hours:
            print("no new settled hour yet; retrying")
            return
        if len(hours) > 1:
            print(f"catching up {len(hours)} settled hours")
        for ts, rows in hours:
            events = book.on_hour(ts, rows, universe=universe or None)
            paying = sum(1 for r in rows.values() if r.f_ann > book.enter)
            print(f"{cp.stamp(ts)} UTC  {len(rows)} coins, {paying} above {book.enter:.0%}  "
                  f"cash={book.cash:.2f} equity={book.equity(rows):.2f} open={len(book.open_positions())}")
            for e in events:
                print("  ", e)
        if mirror is not None:
            rows = hours[-1][1]
            for e in mirror.sync(book.open_positions(), book.closed_positions(),
                                 {c: r.perp for c, r in rows.items()}):
                print("  ", e)

    if args.loop:
        print("ctrl-c to stop; a restart resumes the open hedges")
        try:
            run_loop(step, args.interval, label=f"carry {args.costs}")
        except KeyboardInterrupt:
            print("stopped")
        finally:
            book.close()
        return 0
    step()
    book.close()
    return 0


def _cmd_liqfwd(args: argparse.Namespace) -> int:
    """#22: record the days not yet saved, rebuild the paper ledger, show it."""
    from . import liqfwd as lfm

    sd = state_dir(args.state_dir)
    out = lfm.run(sd)
    print(f"recorded: {', '.join(out['saved']) or 'nothing new'}")
    print(out["note"])
    print(f"ledgers: {sd / lfm.LEDGERS['long']} (#22, FORWARD_LIQ.md), {sd / lfm.LEDGERS['short']} "
          f"(#23, FORWARD_LIQSHORT.md); each judged once after 2027-03-31")
    from . import lowsfwd as lwf
    print("#24 (FORWARD_LOWS.md): " + lwf.run(sd)["note"] + f" -> {sd / lwf.LEDGER}")
    from . import liqbreak as lbk
    print("#27 (FORWARD_LIQBREAK.md): " + lbk.run(sd)["note"] + f" -> {sd / lbk.LEDGER}")
    from . import fundsplit as fsp
    print("#32 (FORWARD_FUNDSPLIT.md): " + fsp.run(sd)["note"] + f" -> {sd / fsp.LEDGER}")
    from . import postclose as pc
    print("#29 (FORWARD_POSTCLOSE.md): " + pc.run(sd)["note"] + f" -> {sd / pc.LEDGER}")
    from . import levpush as lpu
    print("#34 (PREREGISTRATION_LEVPUSH.md, part B): " + lpu.run(sd)["note"])
    from . import bidsfwd as bfw
    print("#31 (FORWARD_BIDS2.md): " + bfw.run(sd)["note"] + f" -> {sd / bfw.LEDGER}")
    from . import settlefwd as sfw
    print("#38 (FORWARD_SHORTSPAY.md): " + sfw.run(sd)["note"] + f" -> {sd / sfw.LEDGER}")
    from . import liqhold as lhd
    print("#45 (FORWARD_LIQHOLD.md): " + lhd.run(sd)["note"] + f" -> {sd / lhd.LEDGER}")
    return 0


def _cmd_hlcollect(args: argparse.Namespace) -> int:
    """Hyperliquid's positions, HLP, contexts and 1-minute candles, saved under data/hlcollect/."""
    from . import hlcollect as hc

    data = Path(args.data) if args.data else hc.DATA
    if args.status:
        for kind, s in hc.status(data).items():
            print(f"{kind:10s} {s['files']:6d} files  {s['bytes'] / 1e6:8.1f} MB  latest {s['latest'] or '-'}")
        return 0
    c = hc.Collector(data, top=args.top)
    if args.loop:
        print(f"collecting into {data} (top {args.top} accounts hourly, HLP every 15 min, contexts every 5 min, "
              f"1-minute candles daily); ctrl-c stops", flush=True)
        c.loop()
        return 0
    for note in c.step() or ["nothing due"]:
        print(note)
    return 0


def _cmd_hlp(args: argparse.Namespace) -> int:
    """#58's or #59's paper book on HLP's recorded positions. Fills are simulated; nothing signs."""
    from collections import Counter

    from . import hlpbook as hp
    from .lock import JournalBusy, JournalLock

    data = Path(args.data) if args.data else hp.DATA
    state = args.state or {58: "hlp-book.db", 59: "hlp2-book.db"}[args.test]
    if args.status:
        print("\n".join(hp.status(state, data, args.test)))
        return 0
    if args.verdict:
        if time.time() < hp.WINDOW_END:
            print(f"#{args.test} is judged once, after 2027-03-31. Not before.")
            return 2
        out = hp.ledger(data, guard=hp.GUARDS[args.test])
        print(out["result"], dict(out["counts"]), Counter(r["status"] for r in out["rows"]))
        return 0
    try:
        with JournalLock(state):
            book = hp.Book(state, data, test=args.test)
            try:
                if not args.loop:
                    print(f"{book.step()} trades written")
                    return 0
                print(f"#{args.test} paper book -> {state}; ctrl-c stops", flush=True)
                run_loop(book.step, args.interval, label=f"hlp {args.test}")
            except KeyboardInterrupt:
                print("stopped")
            finally:
                book.close()
    except JournalBusy as exc:
        print(exc)
        return 2
    return 0


def _cmd_hlbook(args: argparse.Namespace) -> int:
    """Hyperliquid's order book every 5 minutes, saved under data/hlbook/. Status shows counts, never values."""
    from . import hlbook as hb

    data = Path(args.data) if args.data else hb.DATA
    if args.status:
        s = hb.status(data)
        print(f"{s['files']} files  {s['bytes'] / 1e6:.1f} MB  latest {s['latest'] or '-'}")
        for day, d in s["days"].items():
            print(f"{day}  {d['slots']} of {d['expected']} slots")
        return 0
    r = hb.Recorder(data)
    if args.loop:
        print(f"recording into {data} (top 20 levels a side, {hb.COINS} coins, every 5 minutes); ctrl-c stops",
              flush=True)
        r.loop()
        return 0
    print(r.step())
    return 0


def _cmd_carry_screen(args: argparse.Namespace) -> int:
    """#12's forward test on one screen. Read-only: the books are read from copies."""
    from . import carry_view as cv

    view = cv.gather(state_dir(args.state_dir), top=args.top, with_funding=not args.no_funding)
    try:
        from rich.console import Console
    except ImportError:  # plain text is fine
        print(cv.format_plain(view))
        return 0
    console = Console()
    for r in cv.renderables(view):
        console.print(r)
    return 0


def _cmd_carry_status(args: argparse.Namespace) -> int:
    import sqlite3

    from . import carry
    from . import carry_paper as cp

    if not Path(args.state).exists():
        print(f"no carry book at {args.state} (status never creates one)")
        return 2
    with sqlite3.connect(args.state) as probe:
        costs = probe.execute("SELECT value FROM meta WHERE key='costs'").fetchone()
    try:
        book = cp.CarryBook(args.state, costs=args.costs or (costs[0] if costs else "maker"))
    except ValueError as exc:
        print(f"refused: {exc}")
        return 2
    s = book.summary()
    span = f"{cp.stamp(s['first_ts'])} -> {cp.stamp(s['last_ts'])}" if s["first_ts"] else "no hours yet"
    print(f"{args.state}  ({s['costs']} costs)  {span}  {s['hours']} hours")
    print(f"equity {s['equity']:.2f}  pnl {s['pnl']:+.2f} ({s['pnl'] / s['initial']:+.2%})  max dd {s['max_dd']:.2%}  "
          f"funding {s['funding']:+.2f}  basis {s['basis']:+.2f}  fees {s['fees']:.2f}  "
          f"open {s['open']}  closed {s['closed']}")
    curve = book.equity_curve()
    if len(curve) > 2:
        eq = pd.Series([r["equity"] for r in curve],
                       index=pd.to_datetime([r["ts"] for r in curve], unit="s", utc=True))
        print(f"sharpe {carry.sharpe_of(eq, carry.HOURS_PER_YEAR):.2f} hourly (the #12 criterion)  "
              f"{carry.daily_sharpe(eq):.2f} on daily closes (info)")
    try:
        from .hl_exchange import MIRROR_SCHEMA  # noqa: F401
        rows = book.db.execute("SELECT * FROM testnet_mirror").fetchall()
    except Exception:  # noqa: BLE001 - no mirror table
        rows = []
    if rows:
        opens = [r for r in rows if r["open_oid"]]
        st = {k: sum(1 for r in opens if r["open_status"] == k) for k in ("filled", "part", "resting", "cancelled")}
        print(f"testnet mirror: {len(opens)} resting shorts placed, {st['filled']} filled, {st['part']} partial, "
              f"{st['resting']} resting, {st['cancelled']} cancelled")
    for p in book.open_positions():
        print(f"  open  {p['coin']:<6} since {cp.stamp(p['entry_ts'])}  {p['qty_spot'] * p['spot_entry']:.2f} a leg  "
              f"funding {p['funding']:+.2f}")
    for r in book.closed_positions()[-args.last:]:
        print(f"  closed {r['coin']:<6} {cp.stamp(r['entry_ts'])} -> {cp.stamp(r['exit_ts'])}  {r['reason']:<12}"
              f"pnl {r['pnl']:+.2f}")
    book.close()
    return 0
def _cmd_degen_scan(args: argparse.Namespace) -> int:
    from .degen import scan

    _degen_defaults(args)
    uni = _degen_universe(args)
    if not uni:
        return 2
    rows = scan(uni, fetch=_degen_bars(args))
    _degen_table(rows, args.venue)
    return 0


def _degen_window(args: argparse.Namespace, gran: int) -> tuple:
    """(days to fetch, first ts kept, ts cut-off). With --start/--end the window
    is fixed in the pre-registration: fetch back far enough to cover it plus the
    warm-up, then keep only [start - warm-up, end). Without them, the last --days."""
    from .degen import WARMUP

    if not args.start:
        return args.days, None, None
    start = int(datetime.fromisoformat(args.start).replace(tzinfo=timezone.utc).timestamp())
    end = int(datetime.fromisoformat(args.end).replace(tzinfo=timezone.utc).timestamp()) if args.end \
        else int(time.time())
    first = start - WARMUP * gran
    days = int((time.time() - first) // 86400) + 2
    return days, first, end


def _degen_frame(p: str, days: int, gran: int, cache: Path, label: str,
                 source: str = "coinbase") -> pd.DataFrame:
    hl = source == "hyperliquid"
    path = cache / f"{p.replace('-', '')}_{gran}s_{days}d{'_hl' if hl else ''}.csv"
    if path.exists():
        df = data.load(path)
    else:
        print(f"{label} fetching {p} {days}d of {gran // 60}m {'Hyperliquid perp bars' if hl else 'candles'} ...",
              flush=True)
        if hl:
            from . import hyperliquid as hlm
            df = hlm.closed_bars(p, gran, min(days * 86400 // gran, hlm.CANDLE_LIMIT))
            df["time"] = df["dt"].map(lambda t: t.isoformat())
            time.sleep(0.5)     # a 5,000-bar page weighs heavily on its rate limit: 60 in a row drew 429s
        else:
            df = data.fetch(p, days, gran)
        data.save(df, path)
    if "ts" not in df:
        df["ts"] = data.unix_seconds(df["time"]).to_numpy()
    step = df["ts"].diff().median() if len(df) > 2 else gran
    if step != gran:
        # a ts in the wrong unit replays a wrong clock without any error (#10, see ERRATA)
        raise ValueError(f"bars are {step}s apart, expected {gran}s")
    return df


def _cmd_degen_backtest(args: argparse.Namespace) -> int:
    from .degen import BENCHMARK, PREREG, RULES, compare_venues, verdict

    if args.end and not args.start:
        print("--end needs --start")
        return 2
    gran = RULES[args.rule]["granularity"]
    days, first, end = _degen_window(args, gran)
    source = getattr(args, "source", "hyperliquid")
    if source == "hyperliquid":
        from .hyperliquid import CANDLE_LIMIT
        most = CANDLE_LIMIT * gran // 86400
        if days > most:
            print(f"Hyperliquid serves the last {CANDLE_LIMIT:,} bars: {most} days of "
                  f"{gran // 60}m bars, not {days}" + (" (the window starts before them)" if args.start else ""))
            days = most

    def cut(df: pd.DataFrame) -> pd.DataFrame:
        # bars after the window are dropped before anything reads them
        return df if first is None else df[(df["ts"] >= first) & (df["ts"] < end)].reset_index(drop=True)

    uni = _degen_universe(args)
    if not uni:
        return 2
    cache = Path(args.cache)
    frames, dv = {}, {}
    for i, u in enumerate(uni, 1):
        p = u["product"]
        try:
            df = cut(_degen_frame(p, days, gran, cache, f"[{i}/{len(uni)}]", source))
        except Exception as exc:  # noqa: BLE001 - one coin missing is reported, not fatal
            print(f"   {p}: {type(exc).__name__}: {exc}")
            continue
        if df.empty:
            print(f"   {p}: no bars in the window")
            continue
        frames[p] = df
        dv[p] = float(u["dollar_volume"])
    if not frames:
        print("nothing to replay")
        return 2
    bench = None
    if RULES[args.rule].get("beat_benchmark"):
        bench = cut(_degen_frame(BENCHMARK, days, gran, cache, "[benchmark]", source))
    venues = [v.strip() for v in args.venues.split(",") if v.strip()]
    span = f"{args.start} -> {args.end or 'now'}" if args.start else f"{days}d"
    print(f"rule {args.rule}: replaying {len(frames)} coins x {span} through {', '.join(venues)} ...", flush=True)
    rows = compare_venues(frames, venues, initial=args.cash, dollar_volume=dv, rule=args.rule, benchmark=bench)
    lines = [f"{'venue':<28}{'trades':>7}{'hit':>6}{'PF':>7}{'fees':>8}{'maxDD%':>8}{'P&L':>9}{'equity':>9}  exits"]
    for r in rows:
        ex = " ".join(f"{k}={v}" for k, v in sorted(r["reasons"].items()))
        lines.append(f"{r['name']:<28}{r['trades']:>7}{r['hit']:>6.2f}{r['profit_factor']:>7.2f}"
                     f"{r['entry_fees']:>8.2f}{100 * r['max_dd_pct']:>8.1f}{r['pnl']:>+9.2f}{r['equity']:>9.2f}  {ex}")
    crit = verdict(rows)
    lines.append("")
    for c in crit:
        lines.append(f"  [{'x' if c['met'] else ' '}] {c['criterion']}")
    passed = all(c["met"] for c in crit)
    lines.append(f"\nverdict: {'PASS' if passed else 'FAIL'} (rule {args.rule}, pre-registered, {PREREG[args.rule]})")
    lines.append(f"bars and coin list: {source}"
                 + ("" if source == "coinbase" else "; information only, the pre-registered runs used Coinbase"))
    text = "\n".join(lines)
    print(text)
    if args.out:
        Path(args.out).write_text(f"```\n{text}\n```\n")
        print(f"-> {args.out}")
    return 0


def _cmd_degen_paper(args: argparse.Namespace) -> int:
    from .lock import JournalBusy, JournalLock

    _degen_defaults(args)
    try:
        with JournalLock(args.state):
            return _degen_loop(args)
    except JournalBusy as exc:
        print(f"refusing to start: {exc}")
        return 3


def _degen_loop(args: argparse.Namespace) -> int:
    from .degen import BENCHMARK, WARMUP, DegenConfig, DegenTrader, features

    _degen_defaults(args)
    bars = _degen_bars(args)
    journal = Journal(args.state)
    rule = getattr(args, "rule", "10")
    cfg = DegenConfig.for_venue(args.venue, rule=rule, initial=args.cash)
    gran = cfg.granularity
    if getattr(args, "fee_bps", None) is not None:
        cfg.fee = args.fee_bps / 1e4        # e.g. your own rate from `espero fees`
    trader = DegenTrader(journal, cfg)
    print(f"打板 paper loop, rule {rule} ({gran // 60}m {args.source} bars) on {args.venue}: "
          f"fees {1e4 * cfg.fee:.1f} bps per side"
          + (f", funding {1e4 * cfg.funding_8h:.2f} bps per 8h" if cfg.funding_8h else "")
          + f"; cash {trader.cash:.2f}, {len(trader.positions)} open -> {args.state}")
    state = {"universe": [], "refreshed": 0.0}

    def step() -> None:
        if time.time() - state["refreshed"] > 3600:
            try:
                state["universe"] = _degen_universe(args)
                state["refreshed"] = time.time()
            except Exception as exc:  # noqa: BLE001 - keep trading the last universe
                print(f"   universe refresh failed ({type(exc).__name__}: {exc}); "
                      f"keeping {len(state['universe'])} coins, retrying in 5 min")
                state["refreshed"] = time.time() - 3600 + 300
        volume = {u["product"]: float(u["dollar_volume"]) for u in state["universe"]}
        # a held coin is watched until it is sold, even after it leaves the top-N
        held = set(trader.held())
        products = list(volume) + sorted(held - set(volume))
        # the last cycle the loop ran: bars after it were missed by everyone and are
        # caught up; a coin not held that sat outside the universe before it only
        # re-enters from here, so its gap is history, not trades it should have made
        cycle = journal.db.execute("SELECT MAX(ts) AS ts FROM equity").fetchone()["ts"] or 0
        by_ts: dict = {}
        errors = 0
        for p in products:
            try:
                df = bars(p, gran, 300)
            except Exception as exc:  # noqa: BLE001 - skip the coin this cycle
                errors += 1
                print(f"   {p}: {type(exc).__name__}: {exc}")
                continue
            if len(df) < WARMUP:
                continue
            known = journal.last_bar_ts(p)
            fresh = df[df["ts"] > (known or 0)]
            if fresh.empty:
                continue
            recs = features(df)                     # causal: row i reads bars <= i only
            if p in held:
                trade_from = known or 0                        # every missed bar gets its exits
            elif known is None:
                # first sight: only the newest bar, and only if it is newer than the last cycle
                trade_from = max(int(fresh["ts"].iloc[-1]) - 1, cycle)
            else:
                trade_from = max(known, cycle)
            silent = fresh[fresh["ts"] <= trade_from]
            if len(silent):
                # seed history silently so the trail and the restart have bars to read
                with journal.transaction():
                    for bar in silent.to_dict("records"):
                        journal.add_bar(p, bar)
            recs = recs[recs["ts"] > trade_from]
            for rec in recs.to_dict("records"):
                rec.pop("dt", None)
                by_ts.setdefault(int(rec["ts"]), {})[p] = dict(
                    rec, product=p, dollar_volume=volume.get(p, float("nan")), in_universe=p in volume)
            time.sleep(0.12)
        if not by_ts:
            print(_waiting(gran))
            return
        bench: dict = {}
        if cfg.beat_benchmark:
            try:
                b = features(bars(BENCHMARK, gran, 300))
                bench = {int(r["ts"]): r for r in b.to_dict("records")}
            except Exception as exc:  # noqa: BLE001 - no benchmark means no entries this cycle
                print(f"   {BENCHMARK}: {type(exc).__name__}: {exc} (no entries this cycle)")
        if len(by_ts) > 1:
            print(f"catching up {len(by_ts)} bar times")
        for ts in sorted(by_ts):
            rows = by_ts[ts]
            stamp = datetime.fromtimestamp(ts, timezone.utc).strftime("%H:%M")
            events = trader.on_cycle(rows, bench.get(ts))
            quiet = [e for e in events if "no slot" not in e and "blocked" not in e]
            print(f"{stamp} UTC  {len(rows)} coins{f', {errors} errors' if errors else ''}  "
                  f"cash={trader.cash:.2f} equity={trader.equity():.2f} open={len(trader.positions)}")
            for e in quiet:
                print("  ", e)

    if args.loop:
        print("ctrl-c to stop; a restart resumes the open positions")
        try:
            run_loop(step, args.interval, label="degen")
        except KeyboardInterrupt:
            print("stopped")
        finally:
            journal.close()
        return 0
    step()
    journal.close()
    return 0


def _cmd_live(args: argparse.Namespace) -> int:
    from .lock import JournalBusy, JournalLock

    try:
        with JournalLock(args.state):
            return _live_loop(args)
    except JournalBusy as exc:
        print(f"refusing to start: {exc}")
        return 3


def _live_loop(args: argparse.Namespace) -> int:
    from .data import recent_closed_bars

    try:
        broker = broker_from_env(dry_run=not args.confirm_live)
    except BrokerError as exc:
        print(f"cannot start: {exc}", file=sys.stderr)
        return 2

    journal = Journal(args.state)
    cfg = LiveConfig(product=args.product, granularity=args.granularity,
                     max_notional=args.max_notional, max_daily_loss=args.max_daily_loss)
    trader = LiveTrader(journal, broker, cfg, kill_file=args.kill_file)

    print(f"broker   {broker.name}   live={broker.live}")
    print(f"product  {args.product} {args.granularity}s")
    try:
        print(f"price    {broker.price(args.product):.2f}")
        print(f"balance  {broker.balance(cfg.quote_currency):.2f} {cfg.quote_currency}")
    except Exception as exc:  # noqa: BLE001 - surface credential problems plainly
        print(f"credential check failed: {exc}", file=sys.stderr)
        journal.close()
        return 2
    if not broker.live:
        print("mode     DRY RUN - orders are logged, never sent")

    def step() -> None:
        df = recent_closed_bars(args.product, args.granularity, args.seed)
        if df.empty:
            print("no candles returned")
            return
        known = journal.last_bar_ts(args.product) or 0
        fresh = [r for r in df.to_dict("records") if int(r["ts"]) > known]
        if not fresh:
            print(_waiting(args.granularity))
            return
        for bar in fresh[:-1]:
            journal.add_bar(args.product, bar)
        print(f"bar {fresh[-1]['dt']} close={fresh[-1]['close']:.2f}")
        for event in trader.on_bar(fresh[-1]):
            print("  ", event)

    if args.loop:
        try:
            run_loop(step, args.interval, label=f"live {args.product}")
        except KeyboardInterrupt:
            print("stopped")
        finally:
            journal.close()
        return 0

    step()
    journal.close()
    return 0


def _cmd_features(args: argparse.Namespace) -> int:
    if args.source == "hl":
        df, col, name = fx.hyperliquid_funding(pages=args.pages), "funding", "hl_funding_btc"
    elif args.source == "okx":
        df, col, name = fx.okx_funding(pages=args.pages), "funding", "okx_funding_btc"
    else:
        if not args.token:
            print("--token is required for --source poly", file=sys.stderr)
            return 2
        df, col, name = fx.polymarket_history(args.token), "prob", f"poly_{args.token[:10]}"

    if df.empty:
        print("no data returned", file=sys.stderr)
        return 2
    n = fx.save(args.out, name, df, col)
    print(f"{n} rows -> {args.out} [{name}]")
    print(f"range {int(df['ts'].min())} .. {int(df['ts'].max())}")
    return 0


def _cmd_tsmom(args: argparse.Namespace) -> int:
    if args.report:   # read-only: a report must not write a mark
        from datetime import datetime, timezone
        acc = tsm.Account(Path(args.state))
        for row in reversed(acc.history(args.limit)):
            day = datetime.fromtimestamp(int(row["ts"]), timezone.utc).date()
            print(f"{day}  equity {row['equity']:8.2f}  {row['note']}")
        return 0
    res = tsm.run(args.state, args.cash, force=args.force, span=args.span,
                  deposit=args.deposit)
    print(tsm.format_report(res))
    return 0


def _cmd_fast(args: argparse.Namespace) -> int:
    from .fast import run as fast_run
    venue = args.venue or ("hyperliquid" if args.source == "hyperliquid" else "coinbase")
    return fast_run(args.product, cash=args.cash, venue=venue, record=args.record,
                    replay_path=Path(args.replay) if args.replay else None, speed=args.speed,
                    interval=args.interval, state_dir=Path(args.state_dir),
                    threshold=args.threshold / 1e4, order_notional=args.order_notional, source=args.source)


def _cmd_scan(args: argparse.Namespace) -> int:
    from rich.console import Console

    from . import fast as fst

    console = Console()
    threshold = args.threshold / 1e4
    bars, _ = fst.source_feed(args.source)
    venue = args.venue or ("hyperliquid" if args.source == "hyperliquid" else "binanceus")
    products = [p.strip().upper() for p in args.products.split(",") if p.strip()] or fst.scan_products(args.source)
    products = [p if "-" in p else f"{p}-USD" for p in products]
    while True:
        with console.status(f"scanning {len(products)} coins against BTC on {args.source} ...", spinner="dots"):
            rows = fst.scan(products, fetch=bars)
        stamp = time.strftime("%H:%M UTC", time.gmtime())
        mins = fst.next_signal_minutes()
        console.print(fst.scan_table(rows, threshold, title=f"lead-lag signal · {args.source} · {stamp} · "
                                     f"acts at ±{args.threshold:.0f} bps · next update in {mins}m"))
        status = [fst.scan_status(r.state, threshold) for r in rows]
        n_buy, n_cold = status.count("BUY candidate"), status.count("BUY (cold)")
        console.print(f"[grey58]{n_buy} buy candidate(s), {n_cold} more past the threshold but cold. pctile = how "
                      f"unusual this gap is for that coin over two weeks. cold = 2-week IC below zero: the "
                      f"signal has pointed the wrong way on that coin lately.[/]")
        console.print(f"[grey58]{fst.REFERENCE_NOTE}[/]")
        if args.once or not sys.stdin.isatty():
            return 0
        try:
            import questionary
        except ImportError:
            return 0
        from .ui import STYLE
        choices = [questionary.Choice(f"{r.coin:6s} {1e4 * r.state.value:+5.0f} bps  IC "
                                      + ("  n/a" if r.state.rolling_ic is None else f"{r.state.rolling_ic:+.2f}")
                                      + f"  {fst.scan_status(r.state, threshold)}", value=r.product)
                   for r in rows if r.state.value is not None][:15]
        choices += [questionary.Choice("rescan", value="__rescan"), questionary.Choice("quit", value=None)]
        pick = questionary.select("Open the fast screen on:", choices=choices, style=STYLE, pointer="❯").ask()
        if pick == "__rescan":
            continue
        if not pick:
            return 0
        from .fast import run as fast_run
        fast_run(pick, cash=args.cash, venue=venue, record=args.record, state_dir=Path(args.state_dir),
                 threshold=threshold, order_notional=args.order_notional, source=args.source)


PROJECT_DIR = Path(__file__).resolve().parents[1]
STATE_FILES = ("tsmom.db", "xs.db", "mf.db", "health.json")


def state_dir(given: Optional[str] = None) -> Path:
    """Where the accounts live. An explicit --state-dir wins; otherwise the current folder if
    it holds any account, else the project folder. Started from anywhere else, the screens
    used to read an empty folder and show $0.00 as if the accounts had gone."""
    if given:
        return Path(given)
    if any((Path.cwd() / name).exists() for name in STATE_FILES):
        return Path(".")
    if (PROJECT_DIR / "pyproject.toml").exists():
        return PROJECT_DIR
    return Path(".")


def _cmd_ui(args: argparse.Namespace) -> int:
    from .ui import main as ui_main
    return ui_main(state_dir(args.state_dir))


def _cmd_dashboard(args: argparse.Namespace) -> int:
    out = dash.write(args.out, tsmom_db=pathlib.Path(args.tsmom_db),
                     paper_db=pathlib.Path(args.paper_db),
                     live_db=pathlib.Path(args.live_db),
                     xs_db=pathlib.Path(args.xs_db), mf_db=pathlib.Path(args.mf_db),
                     mf_hl_db=pathlib.Path(args.mf_db).with_name("mf-hl.db"), board=True, readout=True)
    print(f"wrote {out}")
    if args.open:
        import subprocess
        subprocess.run(["open", str(out)], check=False)
    return 0


def _cmd_readout(args: argparse.Namespace) -> int:
    print(dash.READOUT.read_text(encoding="utf-8"))
    return 0


def _cmd_daily(args: argparse.Namespace) -> int:
    from .runner import run_daily

    try:
        res = run_daily(state_dir=Path(args.state_dir), cash_tsmom=args.cash_tsmom,
                        cash_xs=args.cash_xs, cash_mf=args.cash_mf, force=args.force, dry_run=args.dry_run,
                        notify=not args.no_notify)
    except RuntimeError as exc:   # the lock is held by a live run
        print(f"cannot start: {exc}", file=sys.stderr)
        return 3
    for name, step in res.steps.items():
        status = "skip" if step.skipped else ("ok" if step.ok else "FAIL")
        extra = step.error or step.note
        print(f"{name:<10s} {status:<5s} {step.seconds:5.1f}s  {extra}")
    if res.paused:
        print("paused: KILL file present")
    return res.exit_code


def _cmd_factors(args: argparse.Namespace) -> int:
    from . import factor_eval as fe
    from . import panel as pnl

    if args.panel and Path(args.panel).exists() and not args.refresh:
        p = pnl.MarketPanel.load(args.panel)
        print(f"panel from {args.panel}: {len(p.coins)} coins, {len(p.index)} days")
    else:
        print(f"building panel ({len(xsm.UNIVERSE)} coins, {args.span}) ...")
        p = pnl.build(span=args.span)
        if args.panel:
            p.save(args.panel)
            print(f"saved to {args.panel}")
        if p.errors:
            print(f"{len(p.errors)} coins failed: {', '.join(sorted(p.errors))}")
    mask = pnl.eligible(p, min_history=args.min_history, min_dollar_volume=args.min_dollar_volume)
    names = args.names.split(",") if args.names else None
    t = fe.evaluate(p, names=names, horizon=args.horizon, mask=mask, n_splits=args.splits)
    print(f"\n{len(p.index)} days · horizon {args.horizon}d · eligible today: {int(mask.iloc[-1].sum())}\n")
    print(fe.format_table(t))
    if args.out:
        t.to_csv(args.out)
        print(f"\nwrote {args.out}")
    return 0


def _cmd_board(args: argparse.Namespace) -> int:
    """#15's trend readings for stocks, bonds, commodities and crypto. Read-only: a
    scanner, since #15 failed its test (research/RESULTS_TREND.md)."""
    from . import board, trend

    frames, errors = board.fetch_frames(trend.symbols())
    v = board.view(frames, pd.Timestamp.now(tz="UTC").tz_localize(None), alts=args.alts)
    try:
        from rich.console import Console
        Console().print(board.table(v))
    except ImportError:
        print(board.format_plain(v))
    for line in board.context(state_dir(args.state_dir)):
        print(line)
    if errors:
        print(f"\n{len(errors)} symbols failed to load: {', '.join(sorted(errors))}")
    if args.carry:
        args.top = 10
        print()
        return _cmd_carry_scan(args)
    return 0


def _cmd_rate(args: argparse.Namespace) -> int:
    """A 1-10 directional rating from a symbol's history (research/RATING.md). Read-only: no orders."""
    from . import rate as rt

    if args.scorecard:
        print(rt.format_scorecard(rt.scorecard()))
        return 0
    if not args.symbols:
        print("espero rate: name at least one symbol, for example: espero rate BTC SPY", file=sys.stderr)
        return 2
    kind = "crypto" if args.crypto else "etf" if args.stock else None
    requests, errors = [], {}
    for s in args.symbols:
        try:
            requests.append(rt.resolve(s, kind))
        except rt.RatingError as exc:
            errors[s] = str(exc)
    results, failed = rt.rate(dict.fromkeys(requests), h=args.horizon) if requests else ([], {})
    errors.update(failed)
    for r in results:
        print(rt.format_report(r, rt.context(r["symbol"], r["kind"])), end="\n\n")
        rt.log_rating(r)
    for reason in errors.values():
        print(reason, file=sys.stderr)
    return 1 if errors else 0


def _cmd_mf(args: argparse.Namespace) -> int:
    from . import mf as mfm
    res = mfm.run(args.state, args.cash)
    print(mfm.format_report(res))
    return 0


def _cmd_xs(args: argparse.Namespace) -> int:
    res = xsm.run(args.state, args.cash, force=args.force, deposit=args.deposit)
    print(xsm.format_report(res))
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="espero", description="small honest crypto research harness")
    p.add_argument("--version", action="version", version="espero 0.2.0")
    sub = p.add_subparsers(dest="cmd", required=False)

    u = sub.add_parser("ui", help="interactive home screen (the default when no command is given)")
    u.add_argument("--state-dir", default=None, help="default: here if it holds accounts, else the project folder")
    u.set_defaults(func=_cmd_ui)

    f = sub.add_parser("fetch", help="download public Coinbase candles to CSV")
    f.add_argument("product", nargs="?", default="BTC-USD")
    f.add_argument("--days", type=int, default=1460)
    f.add_argument("--granularity", type=int, default=86400)
    f.add_argument("-o", "--out", default=None)
    f.set_defaults(func=_cmd_fetch)

    b = sub.add_parser("backtest", help="run one configuration")
    b.add_argument("data", nargs="?", default="data/BTCUSD_86400s.csv")
    b.add_argument("--fee-bps", type=float, default=10.0)
    b.add_argument("--timing", choices=["next_bar", "same_bar"], default="next_bar")
    b.add_argument("--sizing", choices=["risk2pct", "full"], default="full")
    b.set_defaults(func=_cmd_backtest)

    m = sub.add_parser("matrix", help="the audit table: timing x fees x sizing")
    m.add_argument("data", nargs="?", default="data/BTCUSD_86400s.csv")
    m.set_defaults(func=_cmd_matrix)

    pp = sub.add_parser("paper", help="run the paper trader against live candles")
    pp.add_argument("--product", default="BTC-USD")
    pp.add_argument("--granularity", type=int, default=3600)
    pp.add_argument("--state", default="paper.db")
    pp.add_argument("--cash", type=float, default=500.0)
    pp.add_argument("--fee-bps", type=float, default=None,
                    help="per side; overrides the venue's taker fee")
    pp.add_argument("--venue", choices=sorted(VENUES), default=None,
                    help="take taker fee and perp funding from the venue table")
    pp.add_argument("--source", choices=["coinbase", "hyperliquid"], default="coinbase",
                    help="whose candles: Coinbase spot, or Hyperliquid's perp with its actual hourly funding "
                         "(fees default to hyperliquid's; fills stay simulated)")
    pp.add_argument("--seed", type=int, default=300, help="bars of history to keep")
    pp.add_argument("--loop", action="store_true")
    pp.add_argument("--interval", type=float, default=60.0)
    pp.set_defaults(func=_cmd_paper)

    po = sub.add_parser("paper-open", help="buy by hand in a running paper loop (filled at the next open)")
    po.add_argument("--state", default="paper.db")
    po.add_argument("--usd", type=float, default=100.0, help="dollars to buy, at most the book's cash")
    po.set_defaults(func=_cmd_paper_open)

    px = sub.add_parser("paper-close", help="close the paper position by hand (take profit early)")
    px.add_argument("--state", default="paper.db")
    px.add_argument("--product", default=None, help="default: the journal's only open position")
    px.add_argument("--venue", choices=sorted(VENUES), default=None, help="fees, when no loop is running")
    px.add_argument("--fee-bps", type=float, default=None, help="per side, when no loop is running")
    px.set_defaults(func=_cmd_paper_close)

    pc = sub.add_parser("paper-compare",
                        help="replay one paper journal's bars under each venue's fees and funding")
    pc.add_argument("journal", help="a paper .db whose bars to replay")
    pc.add_argument("--product", default="BTC-USD")
    pc.add_argument("--granularity", type=int, default=300)
    pc.add_argument("--cash", type=float, default=500.0)
    pc.add_argument("--venues", default="coinbase,kraken,binanceus,perp")
    pc.set_defaults(func=_cmd_paper_compare)

    ft = sub.add_parser("features", help="fetch point-in-time features into SQLite")
    ft.add_argument("--source", choices=["hl", "okx", "poly"], default="hl")
    ft.add_argument("--out", default="features.db")
    ft.add_argument("--pages", type=int, default=70)
    ft.add_argument("--token", default="", help="Polymarket CLOB token id")
    ft.set_defaults(func=_cmd_features)

    lv = sub.add_parser("live", help="trade a real account (dry-run unless confirmed)")
    lv.add_argument("--product", default="BTC-USD")
    lv.add_argument("--granularity", type=int, default=3600)
    lv.add_argument("--state", default="live.db")
    lv.add_argument("--seed", type=int, default=300)
    lv.add_argument("--max-notional", type=float, default=25.0)
    lv.add_argument("--max-daily-loss", type=float, default=15.0)
    lv.add_argument("--kill-file", default="KILL")
    lv.add_argument("--loop", action="store_true")
    lv.add_argument("--interval", type=float, default=60.0)
    lv.add_argument("--confirm-live", action="store_true",
                    help="actually send orders (also needs ESPERO_ALLOW_LIVE=1)")
    lv.set_defaults(func=_cmd_live)

    tm = sub.add_parser("tsmom", help="cross-asset trend paper account")
    tm.add_argument("--state", default="tsmom.db")
    tm.add_argument("--cash", type=float, default=100.0)
    tm.add_argument("--span", default="2y", help="yahoo history window")
    tm.add_argument("--force", action="store_true", help="rebalance now regardless of the calendar")
    tm.add_argument("--deposit", type=float, default=0.0, help="add cash, then deploy it")
    tm.add_argument("--report", action="store_true", help="print account history")
    tm.add_argument("--limit", type=int, default=30)
    tm.set_defaults(func=_cmd_tsmom)

    xs_p = sub.add_parser("xs", help="weekly cross-sectional top-N crypto paper account")
    xs_p.add_argument("--state", default="xs.db")
    xs_p.add_argument("--cash", type=float, default=100.0)
    xs_p.add_argument("--deposit", type=float, default=0.0)
    xs_p.add_argument("--force", action="store_true")
    xs_p.set_defaults(func=_cmd_xs)

    mf_p = sub.add_parser("mf", help="hypothesis #8 forward paper account (multifactor, weekly)")
    mf_p.add_argument("--state", default="mf.db")
    mf_p.add_argument("--cash", type=float, default=100.0, help="starting cash, first run only")
    mf_p.set_defaults(func=_cmd_mf)

    fc = sub.add_parser("factors", help="rank-IC evaluation of the factor zoo on the crypto panel")
    fc.add_argument("--panel", default="data/panel", help="CSV panel directory (built if missing)")
    fc.add_argument("--refresh", action="store_true", help="re-download even if the panel exists")
    fc.add_argument("--span", default="5y")
    fc.add_argument("--horizon", type=int, default=5, help="forward-return horizon in days")
    fc.add_argument("--splits", type=int, default=4, help="purged walk-forward test blocks")
    fc.add_argument("--min-history", type=int, default=365)
    fc.add_argument("--min-dollar-volume", type=float, default=1e6)
    fc.add_argument("--names", default="", help="comma-separated subset of the zoo")
    fc.add_argument("-o", "--out", default="", help="write the table as CSV")
    fc.set_defaults(func=_cmd_factors)

    fs = sub.add_parser("fast", help="semi-automatic resting-order screen on the live book (paper)")
    fs.add_argument("--product", default="ETH-USD")
    fs.add_argument("--cash", type=float, default=500.0)
    fs.add_argument("--source", choices=["hyperliquid", "coinbase"], default="hyperliquid",
                    help="whose candles and live book to use (Hyperliquid: perp prices, paper only)")
    fs.add_argument("--venue", choices=["hyperliquid", "binanceus", "kraken", "coinbase"], default=None,
                    help="whose maker fee to charge (default: the source's own)")
    fs.add_argument("--order-notional", type=float, default=50.0)
    fs.add_argument("--threshold", type=float, default=30.0, help="signal gap in bps that triggers a proposal")
    fs.add_argument("--record", action="store_true", help="record the book to data/book/ for replay")
    fs.add_argument("--replay", default="", help="replay a recorded book file instead of the live one")
    fs.add_argument("--speed", type=float, default=10.0, help="replay speed multiplier")
    fs.add_argument("--interval", type=float, default=1.0)
    fs.add_argument("--state-dir", default=".")
    fs.set_defaults(func=_cmd_fast)

    sc = sub.add_parser("scan", help="the lead-lag signal for every coin, then open the fast screen on one")
    sc.add_argument("--products", default="", help="comma-separated, e.g. ETH,SOL,LINK (default: the XS coins "
                    "the source lists)")
    sc.add_argument("--source", choices=["hyperliquid", "coinbase"], default="hyperliquid",
                    help="whose candles (and, once you pick a coin, live book) to use")
    sc.add_argument("--threshold", type=float, default=30.0, help="bps gap that makes a buy candidate")
    sc.add_argument("--venue", choices=["hyperliquid", "binanceus", "kraken", "coinbase"], default=None,
                    help="whose maker fee the fast screen charges (default: hyperliquid, or binanceus "
                    "with --source coinbase)")
    sc.add_argument("--cash", type=float, default=500.0)
    sc.add_argument("--order-notional", type=float, default=50.0)
    sc.add_argument("--record", action="store_true")
    sc.add_argument("--state-dir", default=".")
    sc.add_argument("--once", action="store_true", help="print the table and exit")
    sc.set_defaults(func=_cmd_scan)

    cr = sub.add_parser("carry", help="perp funding carry: what shorts are being paid on Hyperliquid (#11)")
    crs = cr.add_subparsers(dest="carry_cmd", required=True)
    q = crs.add_parser("scan", help="top perps by open interest with annualised hourly funding (no writes)")
    q.add_argument("--top", type=int, default=20)
    q.set_defaults(func=_cmd_carry_scan)
    q = crs.add_parser("paper", help="#12 forward paper book on live hourly funding (one loop per journal)")
    q.add_argument("--costs", choices=("taker", "maker"), required=True)
    q.add_argument("--state", required=True, help="e.g. carry-maker.db")
    q.add_argument("--cash", type=float, default=500.0)
    q.add_argument("--top", type=int, default=20)
    q.add_argument("--loop", action="store_true")
    q.add_argument("--interval", type=int, default=300, help="seconds between checks for a new settled hour")
    q.add_argument("--execute-testnet", action="store_true",
                   help="mirror the perp leg with real resting orders on the Hyperliquid TESTNET (spot stays paper)")
    q.set_defaults(func=_cmd_carry_paper)
    q = crs.add_parser("screen", help="#12 on one screen: the launchd loops, both books, funding vs the bar")
    q.add_argument("--state-dir", default=None, help="where carry-*.db live (default as for ui)")
    q.add_argument("--top", type=int, default=20, help="the loops' universe: top N perps by open interest")
    q.add_argument("--no-funding", action="store_true", help="skip the live funding table (no network)")
    q.set_defaults(func=_cmd_carry_screen)
    q = crs.add_parser("status", help="summary of a carry paper book")
    q.add_argument("--state", required=True)
    q.add_argument("--costs", choices=("taker", "maker"))
    q.add_argument("--last", type=int, default=10)
    q.set_defaults(func=_cmd_carry_status)

    hp = sub.add_parser("hl", help="Hyperliquid: read-only account view (testnet by default; nothing is signed)")
    hps = hp.add_subparsers(dest="hl_cmd", required=True)
    q = hps.add_parser("account", help="equity, margin and open positions for a public address")
    q.add_argument("address", nargs="?", help="0x... (default HL_WALLET_ADDRESS from .env)")
    q.add_argument("--testnet", action="store_true", help="api.hyperliquid-testnet.xyz (the default)")
    q.add_argument("--mainnet", action="store_true", help="api.hyperliquid.xyz")
    q.set_defaults(func=_cmd_hl_account)
    q = hps.add_parser("order",
                       help="place one resting TESTNET order (needs HL_PRIVATE_KEY + ESPERO_ALLOW_HL_TESTNET=1)")
    q.add_argument("coin")
    q.add_argument("side", choices=("buy", "sell"))
    q.add_argument("size", type=float)
    q.add_argument("price", type=float)
    q.add_argument("--tif", choices=("Alo", "Gtc", "Ioc"), default="Alo",
                   help="Alo: maker only, rejected if it would cross (default)")
    q.add_argument("--reduce-only", action="store_true")
    q.set_defaults(func=_cmd_hl_order)
    q = hps.add_parser("orders", help="open testnet orders and recent fills; --cancel COIN OID")
    q.add_argument("--hours", type=int, default=24)
    q.add_argument("--cancel", nargs=2, metavar=("COIN", "OID"))
    q.set_defaults(func=_cmd_hl_orders)

    dg = sub.add_parser("degen", help="打板: scan altcoins breaking out on volume, backtest it, paper trade it (#10)")
    dgs = dg.add_subparsers(dest="degen_cmd", required=True)
    for name, fn, h in (("scan", _cmd_degen_scan, "rank the altcoins moving now (no writes)"),
                        ("backtest", _cmd_degen_backtest, "replay the last N days through every venue's fees"),
                        ("paper", _cmd_degen_paper, "live-market paper loop on 5m bars")):
        q = dgs.add_parser(name, help=h)
        q.add_argument("--top", type=int, default=60, help="universe: top N altcoins by 24h dollar volume")
        q.add_argument("--source", choices=["hyperliquid", "coinbase"], default="hyperliquid",
                       help="coin list and bars: Hyperliquid perps (default) or Coinbase spot, which "
                       "the pre-registered #10/#13 runs used")
        q.add_argument("--venue", choices=sorted(VENUES), default=None,
                       help="whose fees to charge (default: hyperliquid, or binanceus with --source coinbase)")
        q.add_argument("--cash", type=float, default=500.0)
        q.set_defaults(func=fn)
        if name != "scan":
            q.add_argument("--rule", choices=("10", "13", "13-control"), default="10",
                           help="10: 5m bars (default); 13: 1h bars, one entry per bar, must beat BTC")
        if name == "backtest":
            q.add_argument("--days", type=int, default=30)
            q.add_argument("--start", default="", help="fixed window start, UTC date (as pre-registered)")
            q.add_argument("--end", default="", help="fixed window end, exclusive")
            q.add_argument("--venues", default="binanceus,kraken,coinbase,perp,hyperliquid",
                           help="fee rows to replay; the verdict reads binanceus and kraken")
            q.add_argument("--cache", default="data/degen", help="where the fetched candles are kept")
            q.add_argument("-o", "--out", default="", help="write the table and verdict here")
        if name == "paper":
            q.add_argument("--state", default=None,
                           help="paper journal (default: degen-hl.db, or degen.db with --source coinbase)")
            q.add_argument("--fee-bps", type=float, default=None,
                           help="per side; overrides the venue's taker fee (see `espero fees`)")
            q.add_argument("--loop", action="store_true")
            q.add_argument("--interval", type=float, default=60.0)

    fe_ = sub.add_parser("fees", help="your Coinbase maker/taker rates (Exchange API key, read-only)")
    fe_.set_defaults(func=_cmd_fees)

    dy = sub.add_parser("daily", help="the scheduled run: tsmom -> xs -> mf -> dashboard -> health.json")
    dy.add_argument("--state-dir", default=".", help="where the .db files, dashboard and health live")
    dy.add_argument("--cash-tsmom", type=float, default=100.0)
    dy.add_argument("--cash-xs", type=float, default=100.0)
    dy.add_argument("--cash-mf", type=float, default=100.0)
    dy.add_argument("--force", action="store_true", help="rebalance tsmom and xs now (mf keeps its calendar)")
    dy.add_argument("--dry-run", action="store_true", help="preflight: no network, no account changes")
    dy.add_argument("--no-notify", action="store_true")
    dy.set_defaults(func=_cmd_daily)

    hp = sub.add_parser("hlp", help="#58 and #59: paper books on HLP's recorded positions (simulated; signs nothing)")
    hp.add_argument("--test", type=int, choices=[58, 59], default=58)
    hp.add_argument("--loop", action="store_true")
    hp.add_argument("--interval", type=float, default=60.0)
    hp.add_argument("--state", default=None, help="journal (default hlp-book.db for #58, hlp2-book.db for #59)")
    hp.add_argument("--data", default=None, help="folder (default data/hlcollect in the repo)")
    hp.add_argument("--status", action="store_true", help="what the book holds; running numbers are not a result")
    hp.add_argument("--verdict", action="store_true", help="the registered verdict, once, after 2027-03-31")
    hp.set_defaults(func=_cmd_hlp)

    hc = sub.add_parser("hlcollect", help="record Hyperliquid's positions, HLP, contexts and 1m candles (public data)")
    hc.add_argument("--loop", action="store_true", help="run forever (what launchd runs)")
    hc.add_argument("--status", action="store_true", help="what is on disk, then exit")
    hc.add_argument("--top", type=int, default=2000, help="accounts by account value, snapshotted hourly")
    hc.add_argument("--data", default=None, help="folder (default data/hlcollect in the repo)")
    hc.set_defaults(func=_cmd_hlcollect)

    rt = sub.add_parser("rate", help="a 1-10 directional rating from a symbol's history, with its evidence (read-only)")
    rt.add_argument("symbols", nargs="*", metavar="SYMBOL", help="for example BTC, ETH-USD, SPY")
    rt.add_argument("--horizon", type=int, choices=(1, 7, 30), default=7, help="days ahead (default 7)")
    rtk = rt.add_mutually_exclusive_group()
    rtk.add_argument("--crypto", action="store_true", help="treat the symbols as coins")
    rtk.add_argument("--stock", action="store_true", help="treat the symbols as stocks or ETFs")
    rt.add_argument("--scorecard", action="store_true", help="how past ratings turned out")
    rt.set_defaults(func=_cmd_rate)
    hk = sub.add_parser("hlbook", help="record Hyperliquid's order book every 5 minutes (public data)")
    hk.add_argument("--loop", action="store_true", help="run forever (what launchd runs)")
    hk.add_argument("--status", action="store_true", help="files and slot counts, then exit")
    hk.add_argument("--data", default=None, help="folder (default data/hlbook in the repo)")
    hk.set_defaults(func=_cmd_hlbook)

    lf = sub.add_parser("liqfwd", help="#22 forward paper test: record aggr's bars, show the ledger")
    lf.add_argument("--state-dir", default=None)
    lf.set_defaults(func=_cmd_liqfwd)

    bd = sub.add_parser("board", help="1/3/12-month trend for stocks, bonds, commodities, crypto (#15 scanner)")
    bd.add_argument("--alts", action="store_true", help="list every altcoin instead of one summary row")
    bd.add_argument("--carry", action="store_true", help="also show Hyperliquid funding now (#12's market)")
    bd.add_argument("--state-dir", default=None, help="where mf.db and carry-*.db live (default as for ui)")
    bd.set_defaults(func=_cmd_board)

    d = sub.add_parser("dashboard", help="static HTML dashboard for the paper accounts")
    d.add_argument("-o", "--out", default="dashboard.html")
    d.add_argument("--tsmom-db", default="tsmom.db")
    d.add_argument("--paper-db", default="paper.db")
    d.add_argument("--live-db", default="live.db")
    d.add_argument("--xs-db", default="xs.db")
    d.add_argument("--mf-db", default="mf.db")
    d.add_argument("--open", action="store_true")
    d.set_defaults(func=_cmd_dashboard)

    rd = sub.add_parser("readout", help="what the free Hyperliquid data shows, for reading the market; not signals")
    rd.set_defaults(func=_cmd_readout)

    c = sub.add_parser("chart", help="write the equity curve PNG")
    c.add_argument("data", nargs="?", default="data/BTCUSD_86400s.csv")
    c.add_argument("-o", "--out", default="docs/equity.png")
    c.set_defaults(func=_cmd_chart)
    return p


def main(argv=None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.cmd is None:
        if sys.stdin.isatty():
            return _cmd_ui(argparse.Namespace(state_dir=None))
        parser.print_help()
        return 0
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
