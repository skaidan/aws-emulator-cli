"""Amazon SQS: queues."""

from __future__ import annotations

from ..awserrors import client_error, is_error
from .. import clients
from . import Service, Snapshot


def queues(c) -> list[str]:
    return [u.rsplit("/", 1)[-1] for u in c.list_queues().get("QueueUrls", [])]


def details(port, name):
    q = clients.client("sqs", port)
    url = q.get_queue_url(QueueName=name)["QueueUrl"]
    return {"QueueUrl": url, **q.get_queue_attributes(QueueUrl=url, AttributeNames=["All"])["Attributes"]}


def describe(a, port, full):
    return details(port, a.resource)


def watch(c) -> Snapshot:
    out: Snapshot = {}
    for url in c.list_queues().get("QueueUrls", []):
        try:
            a = c.get_queue_attributes(QueueUrl=url, AttributeNames=["ApproximateNumberOfMessages"])
            out[("queue", url.rsplit("/", 1)[-1])] = int(a["Attributes"].get("ApproximateNumberOfMessages", 0))
        except client_error() as exc:
            if not is_error(exc, "NonExistentQueue", "QueueDoesNotExist"):
                raise
    return out


SERVICE = Service(
    name="sqs",
    label="SQS queues",
    names=queues,
    details=details,
    describe=describe,
    watch=watch,
    completions={"queue": lambda c, i: queues(c)},
)
