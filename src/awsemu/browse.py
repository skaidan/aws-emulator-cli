"""Data for ``awsemu ui``: list resources and describe one (no UI code here).

Kept apart from the Textual app so it can be tested without Textual.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from .clients import client
from .commands.overview import SERVICES, collect

MAX_OBJECTS = 50
MAX_ITEMS = 20


def resources(port: int) -> list[dict]:
    """``[{"service", "label", "items": [names], "error"}]`` for every service in overview."""
    return collect(port)


def _clean(d: dict) -> dict:
    return {k: v for k, v in d.items() if k != "ResponseMetadata"}


def _s3(port, name):
    s3 = client("s3", port)
    resp = s3.list_objects_v2(Bucket=name, MaxKeys=MAX_OBJECTS)
    objects = [
        {"Key": o["Key"], "Size": o.get("Size"), "LastModified": o.get("LastModified")}
        for o in resp.get("Contents", [])
    ]
    return {"Bucket": name, f"Objects (first {MAX_OBJECTS})": objects, "More": bool(resp.get("IsTruncated"))}


def _sqs(port, name):
    q = client("sqs", port)
    url = q.get_queue_url(QueueName=name)["QueueUrl"]
    return {"QueueUrl": url, **q.get_queue_attributes(QueueUrl=url, AttributeNames=["All"])["Attributes"]}


def _dynamodb(port, name):
    from .commands.dynamodb import from_item

    d = client("dynamodb", port)
    table = d.describe_table(TableName=name)["Table"]
    items = [from_item(i) for i in d.scan(TableName=name, Limit=MAX_ITEMS).get("Items", [])]
    return {"Table": table, f"Items (first {MAX_ITEMS})": items}


def _sns(port, name):
    from .commands.sns import topic_arn

    s = client("sns", port)
    arn = topic_arn(name)
    subs = s.list_subscriptions_by_topic(TopicArn=arn).get("Subscriptions", [])
    return {"Attributes": s.get_topic_attributes(TopicArn=arn)["Attributes"], "Subscriptions": subs}


def _lambda(port, name):
    return client("lambda", port).get_function(FunctionName=name)["Configuration"]


def _secrets(port, name):
    # Metadata only: values stay hidden in the UI.
    return _clean(client("secretsmanager", port).describe_secret(SecretId=name))


def _ssm(port, name):
    p = client("ssm", port).get_parameter(Name=name, WithDecryption=False)["Parameter"]
    if p.get("Type") == "SecureString":
        p["Value"] = "****"
    return p


def _kinesis(port, name):
    return client("kinesis", port).describe_stream_summary(StreamName=name)["StreamDescriptionSummary"]


def _events(port, name):
    """``name`` is an event bus (that's what overview lists): the bus and its rules."""
    ev = client("events", port)
    rules = ev.list_rules(EventBusName=name).get("Rules", [])
    return {"Bus": _clean(ev.describe_event_bus(Name=name)), "Rules": rules}


def _sfn(port, name):
    from .commands.sfn import machine_arn

    s = client("stepfunctions", port)
    machine = _clean(s.describe_state_machine(stateMachineArn=machine_arn(name)))
    runs = s.list_executions(stateMachineArn=machine_arn(name), maxResults=10).get("executions", [])
    return {"StateMachine": machine, "Recent executions": runs}


def _logs(port, name):
    groups = client("logs", port).describe_log_groups(logGroupNamePrefix=name).get("logGroups", [])
    return next((g for g in groups if g["logGroupName"] == name), {"logGroupName": name})


def _iam(port, name):
    return client("iam", port).get_role(RoleName=name)["Role"]


DETAILS: dict[str, Callable[[int, str], Any]] = {
    "s3": _s3,
    "sqs": _sqs,
    "dynamodb": _dynamodb,
    "sns": _sns,
    "lambda": _lambda,
    "secretsmanager": _secrets,
    "ssm": _ssm,
    "kinesis": _kinesis,
    "events": _events,
    "stepfunctions": _sfn,
    "logs": _logs,
    "iam": _iam,
}

assert set(DETAILS) == {s[1] for s in SERVICES}, "every overview service needs a details function"


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
