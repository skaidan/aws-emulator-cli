"""Amazon CloudWatch Logs: log groups."""

from __future__ import annotations


from .. import clients, errors
from . import Service, pages


def groups(c) -> list[str]:
    return pages(c, "describe_log_groups", "logGroups", "logGroupName")


def details(port, name):
    found = clients.client("logs", port).describe_log_groups(logGroupNamePrefix=name).get("logGroups", [])
    return next((g for g in found if g["logGroupName"] == name), {"logGroupName": name})


def describe(a, port, full):
    name = a.rest[:-2] if a.rest.endswith(":*") else a.rest
    found = clients.client("logs", port).describe_log_groups(logGroupNamePrefix=name).get("logGroups", [])
    match = [g for g in found if g["logGroupName"] == name]
    if not match:
        raise errors.AwsemuError(f"log group not found: {name}")
    return match[0]


def cost(call) -> list[tuple[str, float]]:
    """Ingestion, from the request bytes of PutLogEvents."""
    return [("logs.ingest_gb", float(call.get("bytes_in") or 0) / 1e9)] if call["operation"] == "PutLogEvents" else []


SERVICE = Service(
    name="logs",
    label="Log groups",
    names=groups,
    details=details,
    describe=describe,
    missing={
        "watch": "log groups are created by the functions that log; v0.15 adds `logs tail`",
        "completions": "no command takes a log group name yet (v0.15)",
        "apply": "seeds have no log groups: functions create theirs when they log",
        "export": "seeds have no log groups: functions create theirs when they log",
        "seed_import": "seeds have no log groups: functions create theirs when they log",
    },
    cost=cost,
)
