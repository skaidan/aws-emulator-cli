"""``awsemu events``: EventBridge buses, rules and events."""

from __future__ import annotations

import json

import click

from .. import ui
from ..clients import client
from ..completion import complete
from ..context import Ctx, handle_errors, pass_ctx, json_option, yes_option
from ._common import allow_lambda, allow_queue, is_error, load_json_arg

bus_option = click.option("--bus", default="default", show_default=True, help="Event bus name.")


@click.group()
def events():
    """EventBridge: buses, rules and events. Alias: 'awsemu eb'."""


@events.command(name="buses")
@json_option
@pass_ctx
@handle_errors
def buses(c: Ctx, as_json: bool):
    """List event buses."""
    items = client("events", c.port).list_event_buses().get("EventBuses", [])
    if as_json:
        ui.print_json(items)
        return
    ui.table(["bus", "arn"], [[b["Name"], b["Arn"]] for b in items])


@events.command(name="create-bus")
@click.argument("name")
@pass_ctx
@handle_errors
def create_bus(c: Ctx, name: str):
    """Create a custom event bus."""
    arn = client("events", c.port).create_event_bus(Name=name)["EventBusArn"]
    ui.success(f"created bus {name}")
    ui.echo(arn, "muted")


@events.command(name="rules")
@bus_option
@json_option
@pass_ctx
@handle_errors
def rules(c: Ctx, bus: str, as_json: bool):
    """List rules on a bus with their pattern and targets."""
    ev = client("events", c.port)
    items = []
    for page in ev.get_paginator("list_rules").paginate(EventBusName=bus):
        items += page.get("Rules", [])
    for r in items:
        r["Targets"] = ev.list_targets_by_rule(Rule=r["Name"], EventBusName=bus).get("Targets", [])
    if as_json:
        ui.print_json(items)
        return
    rows = []
    for r in items:
        what = r.get("ScheduleExpression") or r.get("EventPattern", "")
        targets = ", ".join(t["Arn"].split(":", 5)[-1] for t in r["Targets"])
        rows.append([r["Name"], r.get("State", ""), what if len(what) <= 60 else what[:57] + "…", targets])
    ui.table(
        ["rule", "state", "pattern / schedule", "targets"],
        rows,
        title=f"bus: {bus}",
        empty="No rules. Try 'awsemu events rule NAME --pattern ... --to-sqs QUEUE'.",
    )


@events.command(name="rule")
@click.argument("name", shell_complete=complete("rule"))
@click.option("--pattern", metavar="JSON", help='Event pattern, e.g. \'{"source": ["app.orders"]}\'.')
@click.option("--source", "sources", multiple=True, help="Shortcut for a pattern matching these sources. Repeatable.")
@click.option("--schedule", metavar="EXPR", help="e.g. 'rate(5 minutes)' (instead of a pattern).")
@click.option(
    "--to-sqs",
    "queue",
    metavar="QUEUE",
    help="Send matches to this queue (sets its policy).",
    shell_complete=complete("queue"),
)
@click.option(
    "--to-lambda",
    "function",
    metavar="FUNCTION",
    help="Invoke this function (adds permission).",
    shell_complete=complete("function"),
)
@click.option("--to-sns", "topic", metavar="TOPIC", help="Publish to this SNS topic.", shell_complete=complete("topic"))
@bus_option
@pass_ctx
@handle_errors
def rule(c: Ctx, name: str, pattern, sources, schedule, queue, function, topic, bus: str):
    """Create or update a rule and (optionally) its target in one step.

    \b
      awsemu events rule orders-created --source app.orders --to-sqs order-events
      awsemu events rule big-orders --pattern '{"detail": {"total": [{"numeric": [">", 100]}]}}' --to-lambda alert
    """
    if sum(x is not None for x in (pattern, schedule)) + bool(sources) != 1:
        raise click.UsageError("give exactly one of --pattern, --source or --schedule")
    if sum(x is not None for x in (queue, function, topic)) > 1:
        raise click.UsageError("give at most one of --to-sqs, --to-lambda or --to-sns")
    ev = client("events", c.port)
    kwargs = {"Name": name, "EventBusName": bus, "State": "ENABLED"}
    if schedule:
        kwargs["ScheduleExpression"] = schedule
    else:
        if sources:
            pattern = json.dumps({"source": list(sources)})
        load_json_arg(pattern, "--pattern")
        kwargs["EventPattern"] = pattern
    rule_arn = ev.put_rule(**kwargs)["RuleArn"]
    ui.success(f"rule {name} on bus {bus}")

    sid = f"awsemu-events-{name}"
    target = None
    if queue:
        target = allow_queue(client("sqs", c.port), queue, "events.amazonaws.com", rule_arn, sid)
    elif function:
        target = allow_lambda(client("lambda", c.port), function, "events.amazonaws.com", rule_arn, sid)
    elif topic:
        from .sns import topic_arn

        target = topic_arn(topic)
    if target:
        resp = ev.put_targets(Rule=name, EventBusName=bus, Targets=[{"Id": "awsemu", "Arn": target}])
        if resp.get("FailedEntryCount"):
            entry = resp["FailedEntries"][0]
            raise click.ClickException(f"target rejected: {entry.get('ErrorCode')}: {entry.get('ErrorMessage')}")
        ui.success(f"→ {target.split(':', 5)[-1]}")


@events.command(name="put")
@click.argument("source")
@click.argument("detail_type")
@click.argument("detail", required=False, default="{}")
@bus_option
@pass_ctx
@handle_errors
def put(c: Ctx, source: str, detail_type: str, detail: str, bus: str):
    """Send an event: 'awsemu events put app.orders OrderCreated '{"id": 42}''."""
    load_json_arg(detail, "DETAIL")
    resp = client("events", c.port).put_events(
        Entries=[{"Source": source, "DetailType": detail_type, "Detail": detail, "EventBusName": bus}]
    )
    if resp.get("FailedEntryCount"):
        entry = resp["Entries"][0]
        raise click.ClickException(f"event rejected: {entry.get('ErrorCode')}: {entry.get('ErrorMessage')}")
    ui.success(f"sent {resp['Entries'][0].get('EventId', '')}")


@events.command(name="rm")
@click.argument("name", shell_complete=complete("rule"))
@bus_option
@yes_option
@pass_ctx
@handle_errors
def rm(c: Ctx, name: str, bus: str, yes: bool):
    """Delete a rule (its targets are removed first)."""
    if not yes:
        click.confirm(f"Delete rule {name}?", abort=True)
    ev = client("events", c.port)
    try:
        ids = [t["Id"] for t in ev.list_targets_by_rule(Rule=name, EventBusName=bus).get("Targets", [])]
    except Exception as exc:
        if not is_error(exc, "ResourceNotFound"):
            raise
        ids = []
    if ids:
        ev.remove_targets(Rule=name, EventBusName=bus, Ids=ids)
    ev.delete_rule(Name=name, EventBusName=bus)
    ui.success(f"deleted rule {name}")
