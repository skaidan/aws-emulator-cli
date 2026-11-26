"""Shell completion of resource names (buckets, queues, tables...) from the emulator.

Completers must be fast and silent: if the emulator isn't running or anything
fails, they return nothing and the shell falls back to its default.
"""

from __future__ import annotations

from collections.abc import Callable

from click.shell_completion import CompletionItem

from . import health
from .paths import default_port

MAX_ITEMS = 200


def _port(ctx) -> int:
    root = ctx.find_root() if ctx is not None else None
    port = root.params.get("port") if root is not None else None
    return int(port) if port else default_port()


def _pages(c, op: str, key: str, field: str | None = None, **kw) -> list[str]:
    out: list[str] = []
    for page in c.get_paginator(op).paginate(**kw):
        out += [x[field] if field else x for x in page.get(key, [])]
        if len(out) >= MAX_ITEMS:
            break
    return out


def _s3_paths(c, incomplete: str) -> list[str]:
    scheme = "s3://" if incomplete.startswith("s3://") else ""
    text = incomplete[len(scheme) :]
    if "/" not in text:
        return [f"{scheme}{b['Name']}/" for b in c.list_buckets().get("Buckets", [])]
    bucket, prefix = text.split("/", 1)
    resp = c.list_objects_v2(Bucket=bucket, Prefix=prefix, Delimiter="/", MaxKeys=MAX_ITEMS)
    keys = [p["Prefix"] for p in resp.get("CommonPrefixes", [])] + [o["Key"] for o in resp.get("Contents", [])]
    return [f"{scheme}{bucket}/{k}" for k in keys]


LISTERS: dict[str, tuple[str, Callable]] = {
    "queue": ("sqs", lambda c, i: [u.rsplit("/", 1)[-1] for u in c.list_queues().get("QueueUrls", [])]),
    "table": ("dynamodb", lambda c, i: _pages(c, "list_tables", "TableNames")),
    "topic": ("sns", lambda c, i: [t.rsplit(":", 1)[-1] for t in _pages(c, "list_topics", "Topics", "TopicArn")]),
    "function": ("lambda", lambda c, i: _pages(c, "list_functions", "Functions", "FunctionName")),
    "secret": ("secretsmanager", lambda c, i: _pages(c, "list_secrets", "SecretList", "Name")),
    "parameter": ("ssm", lambda c, i: _pages(c, "describe_parameters", "Parameters", "Name")),
    "stream": ("kinesis", lambda c, i: _pages(c, "list_streams", "StreamNames")),
    "statemachine": ("stepfunctions", lambda c, i: _pages(c, "list_state_machines", "stateMachines", "name")),
    "rule": ("events", lambda c, i: _pages(c, "list_rules", "Rules", "Name")),
    "s3path": ("s3", _s3_paths),
}


def names(kind: str, port: int, incomplete: str = "") -> list[str]:
    """Resource names of ``kind`` starting with ``incomplete`` ([] on any problem)."""
    if not health.port_open(port, timeout=0.3):
        return []
    service, lister = LISTERS[kind]
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
