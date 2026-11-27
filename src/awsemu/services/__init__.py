"""The service registry: everything awsemu knows about one AWS service, in one place.

Each module in this package declares one ``Service``. The commands that work
across services read the registry instead of keeping their own lists:

==================  ============================================================
``overview``        ``label`` and ``names`` (also ``awsemu ui``'s resource list)
``ui``              ``details``: what the terminal UI shows for one resource
``describe``        ``arn`` and ``describe``: show a resource from its ARN
``watch``           ``alias`` and ``watch``: a snapshot to compare between looks
completion          ``completions``: resource names by kind, for the shell
``seed apply``      ``seed_section`` and ``apply``: create what a seed section lists
``seed export``     ``export``: a seed section from what's there (also ``snapshot``)
==================  ============================================================

A hook a service doesn't have is ``None`` and must be listed in ``missing``
with the reason, so a forgotten hook fails ``tests/test_services_registry.py``.

To add a service: write ``services/<name>.py`` with a ``SERVICE``, add it to
``ORDER`` below, and run the tests. See CONTRIBUTING.md.
"""

from __future__ import annotations

import importlib
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from typing import Any

# A snapshot maps (kind, name) -> a number to compare (messages, items, objects) or None.
Snapshot = dict[tuple[str, str], "int | None"]

HOOKS = ("names", "details", "describe", "watch", "completions", "apply", "export")
COMPLETE_MAX = 200  # names offered by shell completion


@dataclass(frozen=True)
class Service:
    name: str
    """boto3's name for the service; the key in ``overview --json`` and ``awsemu ui``."""
    label: str
    """What ``overview`` calls its resources: "SQS queues"."""
    names: Callable[[Any], list]
    """Names (or ARNs) of the service's main resources, from a boto3 client."""
    details: Callable[[int, str], Any] | None = None
    """``(port, name) -> data`` for ``awsemu ui`` (never secret values)."""
    arn: str = ""
    """The service as written in ARNs (``states`` for Step Functions); defaults to ``name``."""
    describe: Callable[..., Any] | None = None
    """``(arn: Arn, port, full_arn) -> data`` for ``awsemu describe``."""
    alias: str = ""
    """awsemu's short name (``watch -s secrets``); defaults to ``name``."""
    watch: Callable[[Any], Snapshot] | None = None
    """A snapshot of the service from a boto3 client, for ``awsemu watch``."""
    completions: Mapping[str, Callable[[Any, str], list[str]]] = field(default_factory=dict)
    """``{kind: (client, incomplete) -> names}`` for shell completion of resource names."""
    seed_section: str = ""
    """The seed file's section for this service (``queues``), if it has one."""
    apply: Callable[..., None] | None = None
    """``(seed, port, report)``: create or update what ``seed_section`` lists; never deletes."""
    export: Callable[..., list[dict]] | None = None
    """``(port, opts: seed.ExportOptions) -> entries`` of ``seed_section`` from the emulator."""
    missing: Mapping[str, str] = field(default_factory=dict)
    """``{hook: why}`` for each hook this service doesn't have."""

    def __post_init__(self):
        if not self.arn:
            object.__setattr__(self, "arn", self.name)
        if not self.alias:
            object.__setattr__(self, "alias", self.name)


# The order of overview, watch and the UI.
ORDER = (
    "s3",
    "sqs",
    "dynamodb",
    "sns",
    "lambda_",
    "secretsmanager",
    "ssm",
    "kinesis",
    "events",
    "stepfunctions",
    "logs",
    "iam",
)

_REGISTRY: dict[str, Service] | None = None


def registry() -> dict[str, Service]:
    """``{boto3 name: Service}``, in ``ORDER`` (loaded on first use)."""
    global _REGISTRY
    if _REGISTRY is None:
        services = [importlib.import_module(f".{m}", __name__).SERVICE for m in ORDER]
        _REGISTRY = {s.name: s for s in services}
    return _REGISTRY


def all_services() -> list[Service]:
    return list(registry().values())


def seed_sections() -> dict[str, Service]:
    """``{seed section: Service}`` for the services seeds know."""
    return {s.seed_section: s for s in all_services() if s.seed_section}


def get(name: str) -> Service:
    """A service by its boto3 name, awsemu alias or ARN name."""
    for s in all_services():
        if name in (s.name, s.alias, s.arn):
            return s
    raise KeyError(name)


def pages(c, op: str, key: str, field: str | None = None, cap: int | None = None, **kwargs) -> list:
    """Every ``key`` item of a paginated call (``field`` of each, if given), up to ``cap``."""
    out: list = []
    for page in c.get_paginator(op).paginate(**kwargs):
        out += [x[field] if field else x for x in page.get(key, [])]
        if cap is not None and len(out) >= cap:
            break
    return out


def clean(resp: dict) -> dict:
    """A boto3 response without its ``ResponseMetadata``."""
    return {k: v for k, v in resp.items() if k != "ResponseMetadata"}


def names_snapshot(kind: str, lister: Callable[[Any], list]) -> Callable[[Any], Snapshot]:
    """A ``watch`` hook that only notices resources appearing and disappearing."""

    def collect(c) -> Snapshot:
        return {(kind, n): None for n in lister(c)}

    return collect
