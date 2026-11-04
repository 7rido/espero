"""`espero` with no arguments: the home screen, in five tabs (the account holder's design of 2026-11-04).

    Today     what waits for your answer, and whether everything is running
    Market    prices and today's moves against each coin's normal day, the biggest movers, who pays funding,
              the last hour's liquidations, and next week's volatility from #66's forecast
    Books     the canary's progress and the paper accounts
    Research  the tools and readouts, each opened in the plain terminal and back
    Settings  your answers, pause and resume, the daily job, the log, the classic menu

← and → (or 1 to 5) switch tabs. On Today, ↑ and ↓ pick a proposal, `a` approves it and `x` rejects it, each with
the code from your authenticator app; the answer is left in the approvals inbox, where the canary takes it within
five minutes. Nothing here places an order. The data is gathered by `espero.screen_data`; this module only draws.
Needs the `tui` extra (rich, questionary, textual).
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, List, Optional, Sequence, Tuple

from rich.table import Table
from rich.text import Text
from textual import work
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Vertical, VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import DataTable, Footer, Input, Label, OptionList, Static, TabbedContent, TabPane

from . import screen_data as D

TABS = ("today", "market", "books", "research", "settings")
ACCENT = "#d97757"
MUTED = "grey58"


@dataclass
class Sources:
    """Where each tab's data comes from; tests replace them."""
    contexts: Callable[[], List[D.Coin]] = D.fetch_contexts
    closes: Callable[[str], Sequence[float]] = D.hl_closes
    liquidations: Callable[[], Optional[dict]] = D.last_hour_liquidations
    outlook: Callable[[], List[D.Outlook]] = D.volatility_outlook
    now: Callable[[], float] = time.time
    extra: dict = field(default_factory=dict)


def size_word(sigmas: Optional[float]) -> str:
    """Today's move against the coin's normal day, in words."""
    if sigmas is None:
        return ""
    a = abs(sigmas)
    word = "normal" if a < 1 else "large" if a < 2 else "very large" if a < 3 else "extreme"
    return f"{word} ({a:.1f}× a normal day)"


def money(x: float) -> str:
    a = abs(x)
    return f"${a / 1e9:,.1f}B" if a >= 1e9 else f"${a / 1e6:,.1f}M" if a >= 1e6 else f"${a / 1e3:,.0f}K" if a >= 1e3 \
        else f"${a:,.0f}"


def price(x: float) -> str:
    return f"{x:,.2f}" if x >= 1 else f"{x:,.4f}" if x >= 0.01 else f"{x:.6g}"


def change(x: float) -> Text:
    return Text(f"{x:+.1%}", style="green" if x > 0 else "red" if x < 0 else "")


# ---------------------------------------------------------------------------------------------- the code dialog
class AnswerScreen(ModalScreen):
    """Asks for a reason (a rejection needs one) and the six-digit code; returns (code, reason) or None."""

    BINDINGS = [Binding("escape", "cancel", "Cancel")]

    def __init__(self, title: str, need_reason: bool):
        super().__init__()
        self.title_text, self.need_reason = title, need_reason

    def compose(self) -> ComposeResult:
        with Vertical(id="dialog"):
            yield Label(self.title_text, id="dialog-title")
            if self.need_reason:
                yield Input(placeholder="Why? (kept in the journal)", id="reason")
            yield Input(placeholder="6-digit code from your authenticator app", password=True, id="code")
            yield Label("Enter to send · Esc to cancel", id="dialog-hint")

    def on_mount(self) -> None:
        self.query_one("#reason" if self.need_reason else "#code", Input).focus()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        if event.input.id == "reason":
            if event.value.strip():
                self.query_one("#code", Input).focus()
            return
        code = event.value.strip()
        if not (code.isdigit() and len(code) == 6):
            self.query_one("#dialog-hint", Label).update("The code is the 6 digits your authenticator app shows now.")
            return
        reason = self.query_one("#reason", Input).value.strip() if self.need_reason else ""
        if self.need_reason and not reason:
            self.query_one("#dialog-hint", Label).update("A rejection needs a reason.")
            return
        self.dismiss((code, reason))

    def action_cancel(self) -> None:
        self.dismiss(None)


# ------------------------------------------------------------------------------------------------------- the app
def research_actions() -> List[Tuple[str, Callable]]:
    from . import ui
    return [
        ("Why: the last decision, as each book saw it", ui.act_why),
        ("Preview: what each rule would do right now", ui.act_preview),
        ("Signal board: 1, 3 and 12-month trends", ui.act_board),
        ("Account history", ui.act_history),
        ("Forward tests: the paper ledgers, judged after March 2027", ui.act_forward),
        ("Carry: the funding books", ui.act_carry),
        ("Reading the market: what usually follows, and what orders cost", ui.act_readout),
        ("Research results: every test's verdict", ui.act_findings),
        ("Scan: which coins follow BTC", ui.act_scan),
        ("Fast screen: resting orders on the live book (paper)", ui.act_fast),
        ("Paper trading by hand", ui.act_paper),
        ("Factor table", ui.act_factors),
        ("Open the dashboard in the browser", ui.act_dashboard),
        ("Run the tests", ui.act_tests),
    ]


def settings_actions() -> List[Tuple[str, Callable]]:
    from . import ui

    def classic(console, state):
        ui.main(state)

    return [
        ("Your answers: capital, venues, your hours, the lift", ui.act_holder),
        ("Pause or resume everything", ui.act_pause),
        ("Run the daily job now", ui.act_daily),
        ("Deposit paper capital", ui.act_deposit),
        ("Status and health in detail", ui.act_status),
        ("Show the log", ui.act_logs),
        ("The classic menu", classic),
    ]


class EsperoApp(App):
    TITLE = "espero"
    CSS = """
    Screen { background: $surface; }
    #topbar { height: 1; padding: 0 1; background: $panel; }
    .h { text-style: bold; color: #d97757; padding: 1 1 0 1; }
    .body { padding: 0 1; }
    #waiting { height: auto; max-height: 12; margin: 0 1; }
    OptionList { margin: 1 1; }
    AnswerScreen { align: center middle; }
    #dialog { width: 64; height: auto; padding: 1 2; border: round #d97757; background: $panel; }
    #dialog-title { text-style: bold; padding-bottom: 1; }
    #dialog-hint { color: grey; padding-top: 1; }
    """
    BINDINGS = [
        Binding("left", "tab(-1)", "Tab", priority=True, show=False),
        Binding("right", "tab(1)", "Tab", priority=True, show=False),
        *[Binding(str(i + 1), f"go('{t}')", t.title(), show=False) for i, t in enumerate(TABS)],
        Binding("a", "answer('approve')", "Approve"),
        Binding("x", "answer('reject')", "Reject"),
        Binding("r", "reload", "Refresh"),
        Binding("q", "quit", "Quit"),
    ]

    def __init__(self, state: Path, sources: Optional[Sources] = None, post=None):
        super().__init__()
        self.state = Path(state)
        self.src = sources or Sources()
        self.sent: dict = {}
        self.items: List[D.Waiting] = []
        self._post = post
        self.market_rows: List[D.Coin] = []

    # -------------------------------------------------------------- layout
    def compose(self) -> ComposeResult:
        yield Static(id="topbar")
        with TabbedContent(initial="today"):
            with TabPane("Today", id="today"):
                yield Static("Waiting for you", classes="h")
                yield DataTable(id="waiting", cursor_type="row", zebra_stripes=True)
                yield Static(id="waiting-note", classes="body")
                yield Static("System", classes="h")
                yield Static(id="system", classes="body")
            with TabPane("Market", id="market"):
                with VerticalScroll():
                    yield Static("Your coins today", classes="h")
                    yield Static("loading…", id="prices", classes="body")
                    yield Static("Biggest moves today", classes="h")
                    yield Static("loading…", id="movers", classes="body")
                    yield Static("Funding", classes="h")
                    yield Static("loading…", id="funding", classes="body")
                    yield Static("Liquidations, last hour", classes="h")
                    yield Static("loading…", id="liqs", classes="body")
                    yield Static("Volatility, next 7 days", classes="h")
                    yield Static("loading… (the first load of the day takes about a minute)", id="vol",
                                 classes="body")
            with TabPane("Books", id="books"):
                with VerticalScroll():
                    yield Static(id="books-body", classes="body")
            with TabPane("Research", id="research"):
                yield OptionList(*[label for label, _ in research_actions()], id="research-list")
            with TabPane("Settings", id="settings"):
                yield OptionList(*[label for label, _ in settings_actions()], id="settings-list")
        yield Footer()

    def on_mount(self) -> None:
        table = self.query_one("#waiting", DataTable)
        table.add_columns("", "What", "For", "Answer by", "")
        self.refresh_today()
        self.refresh_books()
        self.load_market()
        self.load_liquidations()
        self.load_outlook()
        self.set_interval(30, self.refresh_today)
        self.set_interval(60, self.load_market)
        self.set_interval(D.LIQ_EVERY_S, self.load_liquidations)
        self.set_interval(300, self.refresh_books)

    def on_tabbed_content_tab_activated(self, event: TabbedContent.TabActivated) -> None:
        """Each tab's own list takes the keys: ↑↓ move in it without a click."""
        target = {"today": "#waiting", "research": "#research-list", "settings": "#settings-list"}.get(
            self.query_one(TabbedContent).active)
        if target:
            self.query_one(target).focus()

    # -------------------------------------------------------------- tabs
    def check_action(self, action: str, parameters: tuple) -> Optional[bool]:
        """While a dialog is open, the arrows and letters belong to it."""
        if isinstance(self.screen, ModalScreen) and action in ("tab", "go", "answer", "reload"):
            return False
        return True

    def action_tab(self, step: int) -> None:
        tabs = self.query_one(TabbedContent)
        i = TABS.index(tabs.active) if tabs.active in TABS else 0
        tabs.active = TABS[(i + step) % len(TABS)]

    def action_go(self, tab: str) -> None:
        self.query_one(TabbedContent).active = tab

    def action_reload(self) -> None:
        self.refresh_today()
        self.refresh_books()
        self.load_market()

    # -------------------------------------------------------------- Today
    def refresh_today(self) -> None:
        now = self.src.now()
        sysd = D.system(self.state, now)
        top = Text()
        top.append("espero", style=f"bold {ACCENT}")
        top.append(f"  ·  {D.local_time(now, '%a %-d %b, %-I:%M %p %Z')}", style=MUTED)
        top.append("  ·  ")
        top.append(sysd.line, style=MUTED if sysd.fresh else "green" if sysd.ok else "bold red")
        self.query_one("#topbar", Static).update(top)

        self.items = D.waiting(self.state, int(now))
        table = self.query_one("#waiting", DataTable)
        table.clear()
        for i, w in enumerate(self.items):
            table.add_row(str(i + 1), w.what, w.who, w.by, Text(self.sent.get(w.id, ""), style="green"), key=w.id)
        table.display = bool(self.items)
        note = self.query_one("#waiting-note", Static)
        if self.items:
            note.update(Text("↑↓ pick one · a approve · x reject · each needs the code from your app", style=MUTED))
        else:
            note.update(Text("Nothing waits for you. The canary proposes on Sunday evenings, 7 pm Eastern.",
                             style=MUTED))
        body = Text()
        if sysd.fresh:
            body.append("Nothing runs in the background on this copy, and that is fine for trying it: the Market "
                        "tab reads public data live. To keep paper accounts every day on a Mac: "
                        "./scripts/install-launchd.sh", style=MUTED)
        elif sysd.ok:
            body.append("Recorders, the daily job and the canary are running.", style="green")
        for p in sysd.problems:
            body.append(f"• {p}\n", style="red")
        self.query_one("#system", Static).update(body)

    def action_answer(self, answer: str) -> None:
        if self.query_one(TabbedContent).active != "today" or not self.items:
            return
        table = self.query_one("#waiting", DataTable)
        row = table.cursor_row
        if row is None or not (0 <= row < len(self.items)):
            return
        w = self.items[row]
        verb = "Approve" if answer == "approve" else "Reject"

        def done(result) -> None:
            if not result:
                return
            code, reason = result
            from . import approvals as ap
            post = self._post or ap.post
            post(self.state, ap.Reply(w.id, answer, code, reason, None, "tui", int(self.src.now())))
            self.sent[w.id] = "approval sent" if answer == "approve" else "rejection sent"
            self.notify(f"{verb} sent for {w.what}. The canary takes it within 5 minutes.", timeout=6)
            self.refresh_today()

        self.push_screen(AnswerScreen(f"{verb}: {w.what}, {w.who}", need_reason=answer == "reject"), done)

    # -------------------------------------------------------------- Market
    @work(thread=True, exclusive=True, group="market")
    def load_market(self) -> None:
        try:
            rows = self.src.contexts()
            mine = D.focus(rows)
            top = D.movers(rows)
            D.sigmas_for(mine, self.src.closes)
        except Exception as exc:  # noqa: BLE001 - the tab says what failed rather than closing the screen
            self.call_from_thread(self.query_one("#prices", Static).update,
                                  Text(f"Hyperliquid did not answer: {exc}", style="red"))
            return
        self.market_rows = rows
        self.call_from_thread(self._draw_market, mine, top, D.funding(rows))

    def _draw_market(self, mine, top, fund) -> None:
        t = Table(box=None, pad_edge=False, header_style=MUTED)
        for col in ("Coin", "Price", "Today", "Size of the move", "Funding"):
            t.add_column(col, justify="right" if col in ("Price", "Today") else "left")
        for c in mine:
            who = "longs pay" if c.funding_h > 0 else "shorts pay" if c.funding_h < 0 else "-"
            t.add_row(c.coin, price(c.price), change(c.change), size_word(c.sigmas), who)
        self.query_one("#prices", Static).update(t)

        m = Table(box=None, pad_edge=False, header_style=MUTED)
        for col in ("Coin", "Price", "Today", "Traded today"):
            m.add_column(col, justify="left" if col == "Coin" else "right")
        for c in top:
            m.add_row(c.coin, price(c.price), change(c.change), money(c.volume_usd))
        self.query_one("#movers", Static).update(m)

        f = Text()
        f.append(f"{fund['who'].capitalize()}", style="bold")
        f.append(f": about {abs(fund['yearly']):.1%} a year on the 20 most traded coins. ")
        f.append(f"At rest the venue charges longs {D.RESTING_H * 24 * 365:.0%}; well above that, longs are crowded.\n",
                 style=MUTED)
        f.append("Crowded longs: ", style=MUTED)
        f.append((", ".join(f"{c.coin} pays {c.funding_h * 24 * 365:.0%} a year" for c in fund["crowded_long"])
                  or "none right now") + "\n")
        f.append("Crowded shorts (shorts pay): ", style=MUTED)
        f.append(", ".join(f"{c.coin} pays {-c.funding_h * 24 * 365:.0%} a year" for c in fund["crowded_short"])
                 or "none right now")
        self.query_one("#funding", Static).update(f)

    @work(thread=True, exclusive=True, group="liq")
    def load_liquidations(self) -> None:
        got = self.src.liquidations()
        self.call_from_thread(self._draw_liqs, got)

    def _draw_liqs(self, got) -> None:
        w = self.query_one("#liqs", Static)
        if not got:
            w.update(Text("aggr did not answer; nothing cached yet.", style=MUTED))
            return
        out = Text()
        for coin in ("BTC", "ETH"):
            d = got["coins"].get(coin)
            if not d:
                continue
            out.append(f"{coin}: ", style="bold")
            out.append(f"{money(d['longs'])} of longs and {money(d['shorts'])} of shorts force-closed")
            side = "shorts squeezed" if d["shorts"] > 3 * max(d["longs"], 1) else \
                "longs flushed" if d["longs"] > 3 * max(d["shorts"], 1) else ""
            if side:
                out.append(f"  ({side})", style=ACCENT)
            out.append("\n")
        out.append(f"Binance, Bybit and OKX, from aggr · as of {D.local_time(float(got['at']), '%-I:%M %p')}",
                   style=MUTED)
        w.update(out)

    @work(thread=True, exclusive=True, group="vol")
    def load_outlook(self) -> None:
        try:
            out = self.src.outlook()
        except Exception as exc:  # noqa: BLE001
            out, err = [], str(exc)
        else:
            err = ""
        self.call_from_thread(self._draw_outlook, out, err)

    def _draw_outlook(self, out, err: str) -> None:
        w = self.query_one("#vol", Static)
        if not out:
            w.update(Text(err or "The archive this needs is not on this machine.", style=MUTED))
            return
        t = Text()
        for o in out:
            style = "red" if o.word == "stormier" else "green" if o.word == "calmer" else ""
            t.append(f"{o.coin}: ", style="bold")
            t.append(f"a typical week's move of ±{o.next_week:.1%}, ")
            t.append(f"{o.word}", style=style)
            t.append(f" than the last month's ±{o.last_month:.1%}\n")
        t.append("From the volatility forecast that passed its test (#66). Information, not a signal.", style=MUTED)
        w.update(t)

    # -------------------------------------------------------------- Books
    def refresh_books(self) -> None:
        c = D.canary(self.state)
        out = Text()
        out.append("Rule 8 canary", style=f"bold {ACCENT}")
        out.append("  testnet, play money\n", style=MUTED)
        out.append(f"{c['round_trips']} of {c['needed']} round trips")
        out.append(f"  ·  holds {', '.join(c['held']) if c['held'] else 'nothing'}")
        if c["last_week"]:
            sunday, status = c["last_week"]
            words = {"late": "skipped: decided after the answer window", "decided": "decided"}.get(status, status)
            out.append(f"  ·  week of {sunday}: {words}")
        out.append("\n\n")
        out.append("Paper accounts", style=f"bold {ACCENT}")
        out.append("  no real money\n", style=MUTED)
        t = Table(box=None, pad_edge=False, header_style=MUTED)
        for col in ("Account", "Value", "Since start"):
            t.add_column(col, justify="left" if col == "Account" else "right")
        for name, eq, dep in D.paper(self.state):
            t.add_row(name, f"${eq:,.2f}", change(eq / dep - 1 if dep else 0.0))
        tail = Text(f"\nForward tests: judged once, after 2027-03-31, in {D.judgment_days(self.src.now())} days. "
                    "Their running numbers are not results.", style=MUTED)
        from rich.console import Group
        self.query_one("#books-body", Static).update(Group(out, t, tail))

    # -------------------------------------------------------------- Research and Settings
    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        actions = research_actions() if event.option_list.id == "research-list" else settings_actions()
        label, fn = actions[event.option_index]
        from rich.console import Console
        with self.suspend():
            console = Console()
            console.rule(label)
            try:
                fn(console, self.state)
            except KeyboardInterrupt:
                pass
            except Exception as exc:  # noqa: BLE001 - a tool failing returns to the screen
                console.print(f"[red]{type(exc).__name__}: {exc}[/red]")
            input("\nPress Enter to go back to espero ")
        self.action_reload()


def main(state: Path) -> int:
    EsperoApp(state).run()
    return 0
