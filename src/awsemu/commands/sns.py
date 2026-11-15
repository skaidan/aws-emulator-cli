"""``awsemu sns``: topics, publishing and subscriptions."""

from __future__ import annotations

import json

import click

from .. import ui
from ..clients import client
from ..context import Ctx, handle_errors, pass_ctx
from ..paths import ACCOUNT_ID, REGION
from ._common import allow_lambda, allow_queue, parse_kv, queue_policy_allowing


def topic_arn(topic: str) -> str:
    """Accept a topic name or ARN."""
    if topic.startswith("arn:"):
        return topic
    return f"arn:aws:sns:{REGION}:{ACCOUNT_ID}:{topic}"


def topic_name(arn: str) -> str:
    return arn.rsplit(":", 1)[-1]


def queue_policy_for_topic(queue_arn: str, topic_arn_: str, existing: str | None = None) -> str:
    """A queue policy that lets ``topic_arn_`` send messages, merged with ``existing``."""
    return queue_policy_allowing(queue_arn, "sns.amazonaws.com", topic_arn_,
                                 f"awsemu-sns-{topic_name(topic_arn_)}", existing)


def _list_subscriptions(sns, arn: str | None = None) -> list[dict]:
    if arn:
        paginator = sns.get_paginator("list_subscriptions_by_topic")
        pages = paginator.paginate(TopicArn=arn)
    else:
        pages = sns.get_paginator("list_subscriptions").paginate()
    out = []
    for page in pages:
        out += page.get("Subscriptions", [])
    return out


def _parse_attrs(attrs) -> dict:
    return {k: {"DataType": "String", "StringValue": v} for k, v in parse_kv(attrs).items()}


@click.group()
def sns():
    """Topics, publishing and subscriptions."""


@sns.command(name="ls")
@click.option("--json", "as_json", is_flag=True)
@pass_ctx
@handle_errors
def ls(c: Ctx, as_json: bool):
    """List topics with their subscriptions."""
    s = client("sns", c.port)
    topics = []
    for page in s.get_paginator("list_topics").paginate():
        topics += [t["TopicArn"] for t in page.get("Topics", [])]
    subs = _list_subscriptions(s)
    by_topic: dict[str, list[dict]] = {}
    for sub in subs:
        by_topic.setdefault(sub["TopicArn"], []).append(sub)
    if as_json:
        ui.print_json([{"arn": t, "subscriptions": by_topic.get(t, [])} for t in topics])
        return
    rows = []
    for arn in topics:
        targets = ", ".join(f"{x['Protocol']}:{x['Endpoint'].rsplit(':', 1)[-1]}"
                            for x in by_topic.get(arn, []))
        rows.append([topic_name(arn), len(by_topic.get(arn, [])), targets])
    ui.table(["topic", "subs", "targets"], rows,
             empty="No topics. Try 'awsemu sns create NAME'.")


@sns.command(name="create")
@click.argument("name")
@click.option("--fifo", is_flag=True, help="FIFO topic ('.fifo' is added if missing).")
@pass_ctx
@handle_errors
def create(c: Ctx, name: str, fifo: bool):
    """Create a topic."""
    attrs = {}
    if fifo:
        if not name.endswith(".fifo"):
            name += ".fifo"
        attrs["FifoTopic"] = "true"
    arn = client("sns", c.port).create_topic(Name=name, Attributes=attrs)["TopicArn"]
    ui.success(f"created {name}")
    ui.echo(arn, "muted")


@sns.command(name="publish")
@click.argument("topic")
@click.argument("message", required=False)
@click.option("--file", "file_", type=click.File("r"), help="Read the message from a file ('-' = stdin).")
@click.option("--subject")
@click.option("-a", "--attr", "attrs", multiple=True, metavar="KEY=VALUE",
              help="String message attribute. Repeatable.")
@click.option("--group", help="MessageGroupId (FIFO).")
@click.option("--dedup-id", help="MessageDeduplicationId (FIFO).")
@pass_ctx
@handle_errors
def publish(c: Ctx, topic: str, message: str | None, file_, subject, attrs, group, dedup_id):
    """Publish a message to a topic."""
    if message is None:
        if file_ is None:
            raise click.UsageError("give a MESSAGE or --file")
        message = file_.read()
    kwargs = {"TopicArn": topic_arn(topic), "Message": message}
    if subject:
        kwargs["Subject"] = subject
    if attrs:
        kwargs["MessageAttributes"] = _parse_attrs(attrs)
    if group:
        kwargs["MessageGroupId"] = group
    if dedup_id:
        kwargs["MessageDeduplicationId"] = dedup_id
    msg_id = client("sns", c.port).publish(**kwargs)["MessageId"]
    ui.success(f"published {msg_id}")


@sns.command(name="subscribe")
@click.argument("topic")
@click.option("--to-sqs", "queue", metavar="QUEUE",
              help="Deliver to this SQS queue (name or URL). Sets the queue policy for you.")
@click.option("--to-lambda", "function", metavar="FUNCTION", help="Invoke this Lambda function.")
@click.option("--endpoint", metavar="PROTOCOL:ENDPOINT",
              help="Any other target, e.g. 'https:https://example.test/hook'.")
@click.option("--raw", is_flag=True, help="Raw message delivery (no SNS JSON envelope).")
@click.option("--filter", "filter_policy", metavar="JSON", help="Subscription filter policy.")
@pass_ctx
@handle_errors
def subscribe(c: Ctx, topic: str, queue, function, endpoint, raw: bool, filter_policy):
    """Subscribe a target to a topic.

    \b
      awsemu sns subscribe orders --to-sqs order-events --raw
      awsemu sns subscribe orders --to-lambda handle-order
    """
    if sum(x is not None for x in (queue, function, endpoint)) != 1:
        raise click.UsageError("give exactly one of --to-sqs, --to-lambda or --endpoint")
    arn = topic_arn(topic)
    s = client("sns", c.port)
    sid = f"awsemu-sns-{topic_name(arn)}"
    if queue:
        target = allow_queue(client("sqs", c.port), queue, "sns.amazonaws.com", arn, sid)
        protocol = "sqs"
    elif function:
        target = allow_lambda(client("lambda", c.port), function, "sns.amazonaws.com", arn, sid)
        protocol = "lambda"
    else:
        protocol, _, target = endpoint.partition(":")
        if not target:
            raise click.BadParameter("use PROTOCOL:ENDPOINT", param_hint="--endpoint")
    attributes = {}
    if raw:
        attributes["RawMessageDelivery"] = "true"
    if filter_policy:
        json.loads(filter_policy)  # fail early on bad JSON
        attributes["FilterPolicy"] = filter_policy
    sub_arn = s.subscribe(TopicArn=arn, Protocol=protocol, Endpoint=target,
                          Attributes=attributes, ReturnSubscriptionArn=True)["SubscriptionArn"]
    ui.success(f"{topic_name(arn)} → {protocol}:{target.rsplit(':', 1)[-1]}")
    ui.echo(sub_arn, "muted")


@sns.command(name="subs")
@click.argument("topic", required=False)
@pass_ctx
@handle_errors
def subs(c: Ctx, topic: str | None):
    """List subscriptions (of one topic, or all)."""
    rows = [[topic_name(x["TopicArn"]), x["Protocol"], x["Endpoint"], x["SubscriptionArn"]]
            for x in _list_subscriptions(client("sns", c.port), topic_arn(topic) if topic else None)]
    ui.table(["topic", "protocol", "endpoint", "subscription"], rows, empty="No subscriptions.")


@sns.command(name="unsubscribe")
@click.argument("subscription_arn")
@pass_ctx
@handle_errors
def unsubscribe(c: Ctx, subscription_arn: str):
    """Remove a subscription by ARN."""
    client("sns", c.port).unsubscribe(SubscriptionArn=subscription_arn)
    ui.success("unsubscribed")


@sns.command(name="rm")
@click.argument("topic")
@click.option("-y", "--yes", is_flag=True)
@pass_ctx
@handle_errors
def rm(c: Ctx, topic: str, yes: bool):
    """Delete a topic (and its subscriptions)."""
    if not yes:
        click.confirm(f"Delete topic {topic}?", abort=True)
    client("sns", c.port).delete_topic(TopicArn=topic_arn(topic))
    ui.success(f"deleted {topic_name(topic_arn(topic))}")
