"""Data for ``awsemu ui``: list resources and describe one (no UI code here).

Kept apart from the Textual app so it can be tested without Textual.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from .commands.overview import collect
from .services import all_services


def resources(port: int) -> list[dict]:
    """``[{"service", "label", "items": [names], "error"}]`` for every service in overview."""
    return collect(port)


DETAILS: dict[str, Callable[[int, str], Any]] = {s.name: s.details for s in all_services() if s.details}


def details(port: int, service: str, name: str) -> Any:
    """What ``awsemu ui`` shows for one resource (secret values are never included)."""
    return DETAILS[service](port, name)


def proxy_calls(port: int, position: int = 0, last: int = 500) -> tuple[list[dict], int, bool]:
    """New calls in the proxy's log since ``position`` (a byte offset).

    Returns ``(calls, new_position, proxy_running)``. From position 0 it returns the
    ``last`` ones; a rotated (shorter) log starts over.
    """
    import json

    from . import proxy as px

    path = px.ProxyFiles(port).calls
    running = px.read_state(port) is not None
    try:
        size = path.stat().st_size
    except OSError:
        return [], 0, running
    if size < position:
        position = 0
    if size == position:
        return [], position, running
    with path.open("r", encoding="utf-8") as fh:
        fh.seek(position)
        chunk = fh.read()
        new_position = fh.tell()
    calls = []
    for line in chunk.splitlines():
        try:
            calls.append(json.loads(line))
        except ValueError:
            continue
    return (calls[-last:] if position == 0 else calls), new_position, running
