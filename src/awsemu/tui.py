"""``awsemu ui``: browse the emulator in the terminal (needs the ``ui`` extra: Textual).

Left: services and their resources. Right: details of the selected resource.
Keys: r refresh, w toggle auto-refresh, c API calls (through 'awsemu proxy'), q quit.
"""

from __future__ import annotations

import json
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from rich.json import JSON
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, VerticalScroll
from textual.screen import Screen
from textual.widgets import DataTable, Footer, Header, Static, Tree

from . import browse, health


def _to_json(data: Any) -> str:
    def default(o):
        if isinstance(o, (datetime, date)):
            return o.isoformat()
        if isinstance(o, Decimal):
            return float(o)
        if isinstance(o, bytes):
            return o.decode("utf-8", "replace")
        return str(o)

    return json.dumps(data, default=default, ensure_ascii=False)


class CallsScreen(Screen):
    """Every API call that went through the proxy, newest at the bottom, live."""

    BINDINGS = [
        Binding("c,escape", "app.pop_screen", "Resources"),
        Binding("e", "toggle_errors", "Only errors"),
        Binding("q", "app.quit", "Quit"),
    ]
    COLUMNS = ("time", "service", "operation", "resource", "result", "ms", "fault")

    def __init__(self, port: int, interval: float = 1.0):
        super().__init__()
        self.port = port
        self.interval = interval
        self.position = 0
        self.calls: list[dict] = []
        self.errors_only = False

    def compose(self) -> ComposeResult:
        yield Header(show_clock=False)
        yield Static("", id="calls-status")
        yield DataTable(id="calls", zebra_stripes=True, cursor_type="row")
        yield Footer()

    def on_mount(self) -> None:
        self.query_one(DataTable).add_columns(*self.COLUMNS)
        self.poll()
        self.set_interval(self.interval, self.poll)

    def _row(self, call: dict) -> tuple:
        result = call["error"] or str(call["status"])
        style = "yellow" if call.get("fault") else "red" if call["error"] else ""
        return (
            call["time"][11:23],
            call["service"],
            call["operation"] or call["method"],
            call["resource"][:40],
            f"[{style}]{result}[/{style}]" if style else result,
            f"{call['latency_ms']:.0f}",
            call.get("fault") or "",
        )

    def poll(self) -> None:
        new, self.position, running = browse.proxy_calls(self.port, self.position)
        self.calls = (self.calls + new)[-2000:]
        table = self.query_one(DataTable)
        if new:
            for call in new:
                if not self.errors_only or call["error"]:
                    table.add_row(*self._row(call))
            table.move_cursor(row=table.row_count - 1)
        status = (
            f"{len(self.calls)} call(s) via the proxy in front of port {self.port}"
            + ("" if running else " · no proxy running: start it with 'awsemu proxy start -d'")
            + (" · only errors" if self.errors_only else "")
        )
        self.query_one("#calls-status", Static).update(status)

    def action_toggle_errors(self) -> None:
        self.errors_only = not self.errors_only
        table = self.query_one(DataTable)
        table.clear()
        for call in self.calls:
            if not self.errors_only or call["error"]:
                table.add_row(*self._row(call))
        self.poll()


class EmulatorApp(App):
    CSS = """
    #tree { width: 40%; min-width: 30; border-right: solid $primary; }
    #details-box { width: 1fr; padding: 0 1; }
    """
    BINDINGS = [
        Binding("r", "refresh", "Refresh"),
        Binding("w", "toggle_auto", "Auto-refresh"),
        Binding("c", "calls", "API calls"),
        Binding("q", "quit", "Quit"),
    ]

    def __init__(self, port: int, auto_refresh: float = 5.0):
        super().__init__()
        self.port = port
        self.auto_interval = auto_refresh
        self.auto = False
        self._timer = None
        self.selected: tuple[str, str] | None = None
        self.current_details: Any = None  # last details shown (also handy for tests)
        self.last_error: str | None = None

    def compose(self) -> ComposeResult:
        yield Header(show_clock=False)
        with Horizontal():
            yield Tree("Services", id="tree")
            with VerticalScroll(id="details-box"):
                yield Static("Select a resource on the left.", id="details")
        yield Footer()

    def on_mount(self) -> None:
        self.title = "AWS Emulator"
        self.sub_title = f"https://127.0.0.1:{self.port}"
        self.load_tree()

    # ------------------------------------------------------------------ data

    def load_tree(self) -> None:
        tree = self.query_one(Tree)
        expanded = {n.data for n in tree.root.children if n.is_expanded and n.data}
        tree.clear()
        tree.root.expand()
        if not health.check(self.port).healthy:
            tree.root.set_label(f"No healthy emulator on port {self.port}")
            self.last_error = "emulator not running"
            return
        tree.root.set_label("Services")
        self.last_error = None
        for entry in browse.resources(self.port):
            service, label, items, error = entry["service"], entry["label"], entry["items"], entry["error"]
            text = f"{label} (!)" if error else f"{label} ({len(items)})"
            node = tree.root.add(text, data=("service", service), expand=service in {d[1] for d in expanded})
            if error:
                node.add_leaf(f"error: {error[:80]}")
            for name in items:
                node.add_leaf(str(name), data=(service, str(name)))
        if self.selected:
            self.show_details(*self.selected)

    def show_details(self, service: str, name: str) -> None:
        self.selected = (service, name)
        box = self.query_one("#details", Static)
        try:
            data = browse.details(self.port, service, name)
        except Exception as exc:  # resource gone, not supported, ...
            from .clients import describe_error

            self.current_details = None
            box.update(f"[b]{name}[/b]\n\n[red]{describe_error(exc)}[/red]")
            return
        self.current_details = data
        box.update(JSON(_to_json(data)))

    # ------------------------------------------------------------------ events

    def on_tree_node_selected(self, event: Tree.NodeSelected) -> None:
        data = event.node.data
        if data and data[0] != "service":
            self.show_details(*data)

    def action_refresh(self) -> None:
        self.load_tree()
        self.notify("Refreshed", timeout=1)

    def action_calls(self) -> None:
        self.push_screen(CallsScreen(self.port))

    def action_toggle_auto(self) -> None:
        self.auto = not self.auto
        if self.auto:
            self._timer = self.set_interval(self.auto_interval, self.load_tree)
        elif self._timer is not None:
            self._timer.stop()
            self._timer = None
        self.notify(f"Auto-refresh {'on' if self.auto else 'off'}", timeout=1)


def run(port: int) -> None:
    EmulatorApp(port).run()
