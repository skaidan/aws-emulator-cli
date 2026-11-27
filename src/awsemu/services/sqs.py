"""Amazon SQS: queues."""

from __future__ import annotations

import json

from .. import clients
from .. import seed as seedlib
from ..awserrors import client_error, is_error
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


def _queue_attrs(q: dict) -> dict[str, str]:
    attrs = {}
    if q.get("fifo"):
        attrs["FifoQueue"] = "true"
    if "content_dedup" in q:
        attrs["ContentBasedDeduplication"] = "true" if q["content_dedup"] else "false"
    if "visibility_timeout" in q:
        attrs["VisibilityTimeout"] = str(q["visibility_timeout"])
    if "delay" in q:
        attrs["DelaySeconds"] = str(q["delay"])
    return attrs


def apply(seed, port, report):
    sqs = clients.client("sqs", port)
    urls: dict[str, str] = {}
    results: dict[str, str] = {}
    for q in seed.section("queues"):
        name = q["name"]
        attrs = _queue_attrs(q)
        try:
            try:
                url = sqs.get_queue_url(QueueName=name)["QueueUrl"]
                current = sqs.get_queue_attributes(QueueUrl=url, AttributeNames=["All"])["Attributes"]
                changes = {k: v for k, v in attrs.items() if k != "FifoQueue" and current.get(k) != v}
                if changes:
                    sqs.set_queue_attributes(QueueUrl=url, Attributes=changes)
                results[name] = "updated" if changes else "unchanged"
            except client_error() as exc:
                if not is_error(exc, "NonExistentQueue", "QueueDoesNotExist"):
                    raise
                url = sqs.create_queue(QueueName=name, Attributes=attrs)["QueueUrl"]
                results[name] = "created"
            urls[name] = url
        except Exception as exc:
            report.add("queue", name, "failed", clients.describe_error(exc))
    # Dead-letter queues once every queue exists.
    for q in seed.section("queues"):
        name = q["name"]
        if name not in urls:
            continue
        detail = ""
        if q.get("dlq"):
            try:
                dlq_url = urls.get(q["dlq"]) or sqs.get_queue_url(QueueName=q["dlq"])["QueueUrl"]
                dlq_arn = sqs.get_queue_attributes(QueueUrl=dlq_url, AttributeNames=["QueueArn"])["Attributes"][
                    "QueueArn"
                ]
                wanted = {"deadLetterTargetArn": dlq_arn, "maxReceiveCount": int(q.get("max_receive", 5))}
                current = (
                    sqs.get_queue_attributes(QueueUrl=urls[name], AttributeNames=["RedrivePolicy"])
                    .get("Attributes", {})
                    .get("RedrivePolicy")
                )
                current_policy = json.loads(current) if current else {}
                if {k: str(v) for k, v in current_policy.items()} != {k: str(v) for k, v in wanted.items()}:
                    sqs.set_queue_attributes(QueueUrl=urls[name], Attributes={"RedrivePolicy": json.dumps(wanted)})
                    if results[name] == "unchanged":
                        results[name] = "updated"
                detail = f"dlq → {q['dlq']}"
            except Exception as exc:
                report.add("queue", name, "failed", f"dlq: {clients.describe_error(exc)}")
                continue
        report.add("queue", name, results[name], detail)


def export(port: int, opts: seedlib.ExportOptions) -> list[dict]:
    sqs = clients.client("sqs", port)
    queues = []
    for url in sqs.list_queues().get("QueueUrls", []):
        a = sqs.get_queue_attributes(QueueUrl=url, AttributeNames=["All"])["Attributes"]
        entry = {"name": url.rsplit("/", 1)[-1]}
        if a.get("FifoQueue") == "true":
            entry["fifo"] = True
            if a.get("ContentBasedDeduplication") == "true":
                entry["content_dedup"] = True
        if a.get("VisibilityTimeout", "30") != "30":
            entry["visibility_timeout"] = int(a["VisibilityTimeout"])
        if a.get("DelaySeconds", "0") != "0":
            entry["delay"] = int(a["DelaySeconds"])
        if a.get("RedrivePolicy"):
            rp = json.loads(a["RedrivePolicy"])
            entry["dlq"] = rp["deadLetterTargetArn"].rsplit(":", 1)[-1]
            entry["max_receive"] = int(rp.get("maxReceiveCount", 5))
        queues.append(entry)
    # DLQs first, for readability (apply doesn't care).
    dlqs = {q.get("dlq") for q in queues}
    queues.sort(key=lambda q: (q["name"] not in dlqs, q["name"]))
    return queues


SERVICE = Service(
    name="sqs",
    label="SQS queues",
    names=queues,
    details=details,
    describe=describe,
    watch=watch,
    completions={"queue": lambda c, i: queues(c)},
    seed_section="queues",
    apply=apply,
    export=export,
)
