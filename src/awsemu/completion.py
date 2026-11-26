"""Shell completion of resource names (buckets, queues, tables...) from the emulator.

Completers must be fast and silent: if the emulator isn't running or anything
fails, they return nothing and the shell falls back to its default.
"""

from __future__ import annotations

from collections.abc import Callable

from click.shell_completion import CompletionItem

from . import health
from .paths import default_port

MAX_ITEMS = 200  # also services.COMPLETE_MAX


def _port(ctx) -> int:
    root = ctx.find_root() if ctx is not None else None
    port = root.params.get("port") if root is not None else None
    return int(port) if port else default_port()


def _listers() -> dict[str, tuple[str, Callable]]:
    """{kind: (boto3 service, (client, incomplete) -> names)}, from the service registry."""
    from .services import all_services

    return {kind: (s.name, fn) for s in all_services() for kind, fn in s.completions.items()}


def names(kind: str, port: int, incomplete: str = "") -> list[str]:
    """Resource names of ``kind`` starting with ``incomplete`` ([] on any problem)."""
    if not health.port_open(port, timeout=0.3):
        return []
    service, lister = _listers()[kind]
    try:
        from .clients import client

        values = lister(client(service, port), incomplete)
    except Exception:
        return []
    return sorted(v for v in values if v.startswith(incomplete))[:MAX_ITEMS]


def complete(kind: str):
    """A Click ``shell_complete`` callback for resource names of ``kind``."""

    def callback(ctx, param, incomplete):
        return [CompletionItem(v) for v in names(kind, _port(ctx), incomplete)]

    return callback


SHELLS = ("bash", "zsh", "fish")


def script(cli, shell: str, prog: str = "awsemu") -> str:
    from click.shell_completion import get_completion_class

    cls = get_completion_class(shell)
    if cls is None:  # pragma: no cover
        raise ValueError(f"unsupported shell: {shell}")
    return cls(cli, {}, prog, "_AWSEMU_COMPLETE").source()
