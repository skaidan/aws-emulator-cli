"""Amazon Kinesis Data Streams: streams."""

from __future__ import annotations

from .. import clients
from . import COMPLETE_MAX, Service, names_snapshot, pages


def streams(c) -> list[str]:
    return pages(c, "list_streams", "StreamNames")


def details(port, name):
    return clients.client("kinesis", port).describe_stream_summary(StreamName=name)["StreamDescriptionSummary"]


def describe(a, port, full):
    return details(port, a.rest)


SERVICE = Service(
    name="kinesis",
    label="Kinesis streams",
    names=streams,
    details=details,
    describe=describe,
    watch=names_snapshot("stream", streams),
    completions={"stream": lambda c, i: pages(c, "list_streams", "StreamNames", cap=COMPLETE_MAX)},
)
