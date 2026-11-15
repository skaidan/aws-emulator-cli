"""``awsemu overview``: one screen with what exists in the emulator."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor

import click

from .. import ui
from ..clients import client, describe_error, ensure_running
from ..context import Ctx, handle_errors, pass_ctx


def _s3(c):
    return [b["Name"] for b in c.list_buckets().get("Buckets", [])]


def _sqs(c):
    return [u.rsplit("/", 1)[-1] for u in c.list_queues().get("QueueUrls", [])]


def _ddb(c):
    names, kwargs = [], {}
    while True:
        page = c.list_tables(**kwargs)
        names += page.get("TableNames", [])
        if not page.get("LastEvaluatedTableName"):
            return names
        kwargs["ExclusiveStartTableName"] = page["LastEvaluatedTableName"]


def _paginate(c, op, key, field=None, **kwargs):
    out = []
    for page in c.get_paginator(op).paginate(**kwargs):
        for item in page.get(key, []):
            out.append(item[field] if field else item)
    return out


# (label, boto3 service, lister)
SERVICES = [
    ("S3 buckets", "s3", _s3),
    ("SQS queues", "sqs", _sqs),
    ("DynamoDB tables", "dynamodb", _ddb),
    ("SNS topics", "sns",
     lambda c: [t["TopicArn"].rsplit(":", 1)[-1] for t in _paginate(c, "list_topics", "Topics")]),
    ("Lambda functions", "lambda",
     lambda c: _paginate(c, "list_functions", "Functions", "FunctionName")),
    ("Secrets", "secretsmanager",
     lambda c: _paginate(c, "list_secrets", "SecretList", "Name")),
    ("SSM parameters", "ssm",
     lambda c: _paginate(c, "describe_parameters", "Parameters", "Name")),
    ("Kinesis streams", "kinesis",
     lambda c: _paginate(c, "list_streams", "StreamNames")),
    ("EventBridge buses", "events",
     lambda c: [b["Name"] for b in c.list_event_buses().get("EventBuses", [])]),
    ("Step Functions", "stepfunctions",
     lambda c: _paginate(c, "list_state_machines", "stateMachines", "name")),
    ("Log groups", "logs",
     lambda c: _paginate(c, "describe_log_groups", "logGroups", "logGroupName")),
    ("IAM roles", "iam",
     lambda c: _paginate(c, "list_roles", "Roles", "RoleName")),
]


def collect(port: int, only: set[str] | None = None) -> list[dict]:
    selected = [s for s in SERVICES if not only or s[1] in only]

    def run(entry):
        label, service, lister = entry
        try:
            items = lister(client(service, port))
            return {"service": service, "label": label, "items": items, "error": None}
        except Exception as exc:  # one failing service must not hide the others
            return {"service": service, "label": label, "items": [], "error": describe_error(exc)}

    with ThreadPoolExecutor(max_workers=6) as pool:
        return list(pool.map(run, selected))


@click.command()
@click.option("-s", "--service", "services", multiple=True,
              type=click.Choice([s[1] for s in SERVICES]),
              help="Only these services. Repeatable.")
@click.option("--all", "show_empty", is_flag=True, help="Also list services with nothing in them.")
@click.option("--json", "as_json", is_flag=True)
@pass_ctx
@handle_errors
def overview(c: Ctx, services, show_empty: bool, as_json: bool):
    """What's inside the emulator, across common services. Alias: 'awsemu ls'."""
    ensure_running(c.port)
    results = collect(c.port, set(services) or None)
    if as_json:
        ui.print_json({r["service"]: (r["items"] if not r["error"] else {"error": r["error"]})
                       for r in results})
        return
    rows = []
    for r in results:
        if r["error"]:
            rows.append([r["label"], ui.styled("?", "warn"), ui.styled(r["error"][:80], "warn")])
            continue
        if not r["items"] and not show_empty and not services:
            continue
        names = ", ".join(map(str, r["items"][:8]))
        if len(r["items"]) > 8:
            names += f", … (+{len(r['items']) - 8})"
        rows.append([r["label"], len(r["items"]), names])
    ui.table(["resource", "count", "names"], rows,
             title=f"AWS Emulator on port {c.port}",
             empty="The emulator is empty. (Use --all to list every service checked.)")
