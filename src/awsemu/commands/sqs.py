"""``awsemu sqs``: queues and messages."""

from __future__ import annotations

import json

import click

from .. import ui
from ..clients import client
from ..completion import complete
from ..context import Ctx, handle_errors, pass_ctx, json_option, yes_option
from ..services.sqs import queue_url

COUNT_ATTRS = [
    "ApproximateNumberOfMessages",
    "ApproximateNumberOfMessagesNotVisible",
    "ApproximateNumberOfMessagesDelayed",
]


@click.group()
def sqs():
    """SQS: queues and messages."""


@sqs.command(name="ls")
@click.option("--prefix", default="", help="Only queues whose name starts with this.")
@json_option
@pass_ctx
@handle_errors
def ls(c: Ctx, prefix: str, as_json: bool):
    """List queues with their message counts."""
    q = client("sqs", c.port)
    urls = q.list_queues(**({"QueueNamePrefix": prefix} if prefix else {})).get("QueueUrls", [])
    rows, data = [], []
    for url in urls:
        attrs = q.get_queue_attributes(QueueUrl=url, AttributeNames=COUNT_ATTRS).get("Attributes", {})
        name = url.rsplit("/", 1)[-1]
        data.append(
            {
                "name": name,
                "url": url,
                "visible": int(attrs.get("ApproximateNumberOfMessages", 0)),
                "in_flight": int(attrs.get("ApproximateNumberOfMessagesNotVisible", 0)),
                "delayed": int(attrs.get("ApproximateNumberOfMessagesDelayed", 0)),
            }
        )
        rows.append(
            [
                name,
                attrs.get("ApproximateNumberOfMessages", "?"),
                attrs.get("ApproximateNumberOfMessagesNotVisible", "?"),
                attrs.get("ApproximateNumberOfMessagesDelayed", "?"),
            ]
        )
    if as_json:
        ui.print_json(data)
        return
    ui.table(["queue", "visible", "in flight", "delayed"], rows, empty="No queues. Try 'awsemu sqs create NAME'.")


@sqs.command(name="create")
@click.argument("name")
@click.option("--fifo", is_flag=True, help="FIFO queue ('.fifo' is added if missing).")
@click.option("--dedup", is_flag=True, help="Content-based deduplication (FIFO only).")
@click.option("--visibility-timeout", type=int, metavar="SECONDS", help="How long a received message stays hidden.")
@click.option("--dlq", metavar="QUEUE", help="Dead-letter queue (name or URL).", shell_complete=complete("queue"))
@click.option(
    "--max-receive", type=int, default=5, show_default=True, help="Receives before a message goes to the DLQ."
)
@pass_ctx
@handle_errors
def create(
    c: Ctx, name: str, fifo: bool, dedup: bool, visibility_timeout: int | None, dlq: str | None, max_receive: int
):
    """Create a queue."""
    q = client("sqs", c.port)
    attrs: dict[str, str] = {}
    if fifo:
        if not name.endswith(".fifo"):
            name += ".fifo"
        attrs["FifoQueue"] = "true"
        if dedup:
            attrs["ContentBasedDeduplication"] = "true"
    if visibility_timeout is not None:
        attrs["VisibilityTimeout"] = str(visibility_timeout)
    if dlq:
        dlq_url = queue_url(q, dlq)
        arn = q.get_queue_attributes(QueueUrl=dlq_url, AttributeNames=["QueueArn"])["Attributes"]["QueueArn"]
        attrs["RedrivePolicy"] = json.dumps({"deadLetterTargetArn": arn, "maxReceiveCount": str(max_receive)})
    url = q.create_queue(QueueName=name, Attributes=attrs)["QueueUrl"]
    ui.success(f"created {name}")
    ui.echo(url, "muted")


@sqs.command(name="send")
@click.argument("queue", shell_complete=complete("queue"))
@click.argument("body", required=False)
@click.option("--file", "file_", type=click.File("r"), help="Read the body from a file ('-' = stdin).")
@click.option("--group", help="MessageGroupId (FIFO).")
@click.option("--dedup-id", help="MessageDeduplicationId (FIFO).")
@click.option("--delay", type=int, metavar="SECONDS", help="Delay before the message becomes visible.")
@click.option("-a", "--attr", "attrs", multiple=True, metavar="KEY=VALUE", help="String message attribute. Repeatable.")
@pass_ctx
@handle_errors
def send(c: Ctx, queue: str, body: str | None, file_, group, dedup_id, delay, attrs):
    """Send a message. BODY can also come from --file or stdin."""
    if body is None:
        if file_ is None:
            raise click.UsageError("give a BODY or --file")
        body = file_.read()
    q = client("sqs", c.port)
    kwargs = {"QueueUrl": queue_url(q, queue), "MessageBody": body}
    if group:
        kwargs["MessageGroupId"] = group
    if dedup_id:
        kwargs["MessageDeduplicationId"] = dedup_id
    if delay is not None:
        kwargs["DelaySeconds"] = delay
    if attrs:
        parsed = {}
        for a in attrs:
            k, sep, v = a.partition("=")
            if not sep:
                raise click.BadParameter(f"'{a}' is not KEY=VALUE", param_hint="--attr")
            parsed[k] = {"DataType": "String", "StringValue": v}
        kwargs["MessageAttributes"] = parsed
    msg_id = q.send_message(**kwargs)["MessageId"]
    ui.success(f"sent {msg_id}")


@sqs.command(name="receive")
@click.argument("queue", shell_complete=complete("queue"))
@click.option(
    "-n", "--max", "max_", type=click.IntRange(1, 10), default=10, show_default=True, help="Maximum number of messages."
)
@click.option(
    "--wait", type=click.IntRange(0, 20), default=1, show_default=True, metavar="SECONDS", help="Long-poll time."
)
@click.option("--delete", is_flag=True, help="Delete messages after printing them.")
@json_option
@pass_ctx
@handle_errors
def receive(c: Ctx, queue: str, max_: int, wait: int, delete: bool, as_json: bool):
    """Receive messages (they stay in the queue unless --delete)."""
    q = client("sqs", c.port)
    url = queue_url(q, queue)
    msgs = q.receive_message(
        QueueUrl=url,
        MaxNumberOfMessages=max_,
        WaitTimeSeconds=wait,
        MessageAttributeNames=["All"],
        AttributeNames=["All"],
    ).get("Messages", [])
    if as_json:
        ui.print_json(msgs)
    else:
        rows = []
        for m in msgs:
            body = m.get("Body", "")
            try:
                body = json.dumps(json.loads(body), ensure_ascii=False)
            except (ValueError, TypeError):
                pass
            attrs = ", ".join(
                f"{k}={v.get('StringValue', v.get('BinaryValue', ''))}"
                for k, v in m.get("MessageAttributes", {}).items()
            )
            rows.append(
                [
                    m["MessageId"][:8],
                    m.get("Attributes", {}).get("ApproximateReceiveCount", ""),
                    body if len(body) <= 200 else body[:197] + "…",
                    attrs,
                ]
            )
        ui.table(["id", "receives", "body", "attributes"], rows, empty="No messages.")
    if delete and msgs:
        entries = [{"Id": str(i), "ReceiptHandle": m["ReceiptHandle"]} for i, m in enumerate(msgs)]
        q.delete_message_batch(QueueUrl=url, Entries=entries)
        if not as_json:
            ui.echo(f"deleted {len(msgs)} message(s)", "muted")


@sqs.command(name="purge")
@click.argument("queue", shell_complete=complete("queue"))
@yes_option
@pass_ctx
@handle_errors
def purge(c: Ctx, queue: str, yes: bool):
    """Delete every message in a queue."""
    if not yes:
        click.confirm(f"Purge all messages from {queue}?", abort=True)
    q = client("sqs", c.port)
    q.purge_queue(QueueUrl=queue_url(q, queue))
    ui.success(f"purged {queue}")


@sqs.command(name="rm")
@click.argument("queue", shell_complete=complete("queue"))
@yes_option
@pass_ctx
@handle_errors
def rm(c: Ctx, queue: str, yes: bool):
    """Delete a queue."""
    if not yes:
        click.confirm(f"Delete queue {queue}?", abort=True)
    q = client("sqs", c.port)
    q.delete_queue(QueueUrl=queue_url(q, queue))
    ui.success(f"deleted {queue}")


@sqs.command(name="info")
@click.argument("queue", shell_complete=complete("queue"))
@pass_ctx
@handle_errors
def info(c: Ctx, queue: str):
    """Show all attributes of a queue."""
    q = client("sqs", c.port)
    url = queue_url(q, queue)
    attrs = q.get_queue_attributes(QueueUrl=url, AttributeNames=["All"]).get("Attributes", {})
    ui.kv([("url", url), *sorted(attrs.items())], title=queue)
