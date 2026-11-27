"""Amazon Kinesis Data Streams: streams."""

from __future__ import annotations


from .. import clients
from .. import realaccount
from .. import seed as seedlib
from ..awserrors import client_error, is_error
from . import COMPLETE_MAX, Service, names_snapshot, pages


def streams(c) -> list[str]:
    return pages(c, "list_streams", "StreamNames")


def details(port, name):
    return clients.client("kinesis", port).describe_stream_summary(StreamName=name)["StreamDescriptionSummary"]


def describe(a, port, full):
    return details(port, a.rest)


def apply(seed, port, report):
    k = clients.client("kinesis", port)
    for st in seed.section("streams"):
        name, shards = st["name"], st.get("shards", 1)
        try:
            changes = []
            try:
                summary = k.describe_stream_summary(StreamName=name)["StreamDescriptionSummary"]
                result = "unchanged"
            except client_error() as exc:
                if not is_error(exc, "ResourceNotFound"):
                    raise
                k.create_stream(StreamName=name, ShardCount=shards)
                k.get_waiter("stream_exists").wait(StreamName=name, WaiterConfig={"Delay": 1, "MaxAttempts": 60})
                summary = k.describe_stream_summary(StreamName=name)["StreamDescriptionSummary"]
                result = "created"
            if result == "unchanged" and summary.get("OpenShardCount") != shards:
                k.update_shard_count(StreamName=name, TargetShardCount=shards, ScalingType="UNIFORM_SCALING")
                k.get_waiter("stream_exists").wait(StreamName=name, WaiterConfig={"Delay": 1, "MaxAttempts": 60})
                changes.append(f"{shards} shard(s)")
            hours = st.get("retention_hours")
            if hours and summary.get("RetentionPeriodHours") != hours:
                if hours > summary.get("RetentionPeriodHours", 24):
                    k.increase_stream_retention_period(StreamName=name, RetentionPeriodHours=hours)
                else:
                    k.decrease_stream_retention_period(StreamName=name, RetentionPeriodHours=hours)
                changes.append(f"retention {hours} h")
            if changes and result == "unchanged":
                result = "updated"
            report.add("stream", name, result, ", ".join(changes))
        except Exception as exc:
            report.add("stream", name, "failed", clients.describe_error(exc))


def export(port: int, opts: seedlib.ExportOptions) -> list[dict]:
    k = clients.client("kinesis", port)
    streams = []
    for page in k.get_paginator("list_streams").paginate():
        for name in page.get("StreamNames", []):
            summary = k.describe_stream_summary(StreamName=name)["StreamDescriptionSummary"]
            entry = {"name": name}
            if summary.get("OpenShardCount", 1) != 1:
                entry["shards"] = summary["OpenShardCount"]
            if summary.get("RetentionPeriodHours", 24) != 24:
                entry["retention_hours"] = summary["RetentionPeriodHours"]
            streams.append(entry)
    return streams


def seed_import(sess, opts: seedlib.ImportOptions) -> list[dict]:
    """``streams`` of a real account (read-only), for ``awsemu seed import``."""
    k = realaccount.client(sess, "kinesis")
    streams = []
    for page in k.get_paginator("list_streams").paginate():
        for name in page.get("StreamNames", []):
            summary = k.describe_stream_summary(StreamName=name)["StreamDescriptionSummary"]
            entry = {"name": name}
            if summary.get("OpenShardCount", 1) != 1:
                entry["shards"] = summary["OpenShardCount"]
            if summary.get("RetentionPeriodHours", 24) != 24:
                entry["retention_hours"] = summary["RetentionPeriodHours"]
            streams.append(entry)
    return streams


def cost(call) -> list[tuple[str, float]]:
    if call["operation"] not in ("PutRecord", "PutRecords"):
        return []
    return [("kinesis.put_unit", max(1.0, float(call.get("bytes_in") or 0) / 25_000))]


SERVICE = Service(
    name="kinesis",
    label="Kinesis streams",
    names=streams,
    details=details,
    describe=describe,
    watch=names_snapshot("stream", streams),
    completions={"stream": lambda c, i: pages(c, "list_streams", "StreamNames", cap=COMPLETE_MAX)},
    seed_section="streams",
    apply=apply,
    export=export,
    seed_import=seed_import,
    cost=cost,
)
