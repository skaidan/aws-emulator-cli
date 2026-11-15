"""Output helpers. Uses Rich when installed, plain text otherwise.

Everything user-facing goes through here so commands also work in minimal
environments (CI images, containers) and with ``--plain`` / ``NO_COLOR``.
"""

from __future__ import annotations

import json
import os
import sys
from collections.abc import Iterable, Sequence
from typing import Any

try:  # pragma: no cover - depends on environment
    from rich.console import Console
    from rich.table import Table
    from rich.text import Text

    HAVE_RICH = True
except ImportError:  # pragma: no cover
    HAVE_RICH = False

_plain = bool(os.environ.get("AWSEMU_PLAIN"))
_console = None
_err_console = None

STYLES = {
    "healthy": "bold green",
    "ok": "green",
    "stopped": "dim",
    "unhealthy": "bold yellow",
    "warn": "yellow",
    "error": "bold red",
    "info": "cyan",
    "muted": "dim",
}

LEVEL_STYLES = {"ERROR": "bold red", "WARN": "yellow", "WARNING": "yellow",
                "INFO": "cyan", "DEBUG": "dim", "TRACE": "dim"}


def set_plain(value: bool) -> None:
    global _plain, _console, _err_console
    _plain = value
    _console = _err_console = None


def rich_enabled() -> bool:
    return HAVE_RICH and not _plain


def console():
    global _console
    if _console is None and rich_enabled():
        _console = Console(highlight=False)
    return _console


def err_console():
    global _err_console
    if _err_console is None and rich_enabled():
        _err_console = Console(stderr=True, highlight=False)
    return _err_console


def echo(message: str = "", style: str | None = None, err: bool = False) -> None:
    con = err_console() if err else console()
    if con is not None:
        con.print(Text(message, style=STYLES.get(style, style) if style else ""))
    else:
        print(message, file=sys.stderr if err else sys.stdout, flush=True)


def success(message: str) -> None:
    echo(f"✓ {message}", "ok")


def info(message: str) -> None:
    echo(message, "info")


def warn(message: str) -> None:
    echo(f"! {message}", "warn", err=True)


def error(message: str, hint: str | None = None) -> None:
    echo(f"✗ {message}", "error", err=True)
    if hint:
        echo(f"  {hint}", "muted", err=True)


def styled(value: Any, style: str | None) -> Any:
    if style and rich_enabled():
        return Text(str(value), style=STYLES.get(style, style))
    return value


def table(columns: Sequence[str], rows: Iterable[Sequence[Any]], title: str | None = None,
          empty: str = "(nothing here)") -> None:
    rows = [["" if c is None else c for c in row] for row in rows]
    if not rows:
        echo(empty if not title else f"{title}: {empty}", "muted")
        return
    con = console()
    if con is not None:
        t = Table(title=title, title_justify="left", header_style="bold")
        for col in columns:
            t.add_column(col, overflow="fold")
        for row in rows:
            t.add_row(*[c if isinstance(c, Text) else str(c) for c in row])
        con.print(t)
        return
    str_rows = [[str(c) for c in row] for row in rows]
    widths = [max(len(columns[i]), *(len(r[i]) for r in str_rows)) for i in range(len(columns))]
    if title:
        print(title)
    print("  ".join(c.ljust(w) for c, w in zip(columns, widths)).rstrip())
    print("  ".join("-" * w for w in widths))
    for r in str_rows:
        print("  ".join(c.ljust(w) for c, w in zip(r, widths)).rstrip())


def kv(pairs: Sequence[tuple[str, Any]], title: str | None = None) -> None:
    con = console()
    if con is not None:
        t = Table(title=title, title_justify="left", show_header=False, box=None, pad_edge=False)
        t.add_column(style="bold")
        t.add_column(overflow="fold")
        for k, v in pairs:
            t.add_row(k, v if isinstance(v, Text) else str("" if v is None else v))
        con.print(t)
        return
    if title:
        print(title)
    width = max((len(k) for k, _ in pairs), default=0)
    for k, v in pairs:
        print(f"{k.ljust(width)}  {'' if v is None else v}")


def print_json(data: Any) -> None:
    text = json.dumps(data, indent=2, default=str, ensure_ascii=False)
    con = console()
    if con is not None:
        con.print_json(text)
    else:
        print(text)


def log_line(entry) -> None:
    """Print a parsed :class:`awsemu.logs.LogLine`."""
    from .logs import _short, format_plain

    con = console()
    if con is None or not entry.is_json:
        print(format_plain(entry), flush=True)
        return
    t = Text()
    if entry.time:
        t.append(entry.time + "  ", style="dim")
    if entry.level:
        t.append(entry.level.ljust(5) + "  ", style=LEVEL_STYLES.get(entry.level, ""))
    t.append(entry.message, style="bold" if entry.is_startup else "")
    for k, v in entry.extra.items():
        t.append(f"  {k}=", style="dim")
        t.append(_short(v))
    con.print(t)


def human_size(num: float | int | None) -> str:
    if num is None:
        return ""
    num = float(num)
    for unit in ("B", "KiB", "MiB", "GiB", "TiB"):
        if num < 1024 or unit == "TiB":
            return f"{num:.0f} {unit}" if unit == "B" else f"{num:.1f} {unit}"
        num /= 1024
    return str(num)


def human_duration(seconds: float | None) -> str:
    if seconds is None:
        return ""
    seconds = int(seconds)
    days, rem = divmod(seconds, 86400)
    hours, rem = divmod(rem, 3600)
    minutes, secs = divmod(rem, 60)
    if days:
        return f"{days}d {hours}h"
    if hours:
        return f"{hours}h {minutes}m"
    if minutes:
        return f"{minutes}m {secs}s"
    return f"{secs}s"
