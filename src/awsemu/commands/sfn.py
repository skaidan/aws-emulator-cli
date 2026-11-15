"""``awsemu sfn``: Step Functions state machines and executions."""

from __future__ import annotations

import json
import time
import uuid
from pathlib import Path

import click

from .. import ui
from ..clients import client
from ..context import Ctx, handle_errors, pass_ctx
from ._common import arn, ensure_service_role, is_error, load_json_arg

DEFAULT_ROLE_NAME = "awsemu-sfn-role"
FINAL = {"SUCCEEDED", "FAILED", "TIMED_OUT", "ABORTED"}
STATUS_STYLE = {"SUCCEEDED": "ok", "RUNNING": "info", "FAILED": "error", "TIMED_OUT": "error",
                "ABORTED": "warn"}


def machine_arn(name: str) -> str:
    return name if name.startswith("arn:") else arn("states", f"stateMachine:{name}")


def read_definition(value: str) -> str:
    """A path to a .json/.asl.json file, or inline JSON."""
    path = Path(value)
    text = path.read_text(encoding="utf-8") if path.is_file() else value
    definition = load_json_arg(text, "definition")
    if not isinstance(definition, dict) or "States" not in definition:
        raise click.BadParameter("a state machine definition needs 'StartAt' and 'States'")
    return json.dumps(definition)


@click.group()
def sfn():
    """Step Functions: state machines and executions."""


@sfn.command(name="ls")
@pass_ctx
@handle_errors
def ls(c: Ctx):
    """List state machines."""
    s = client("stepfunctions", c.port)
    rows = []
    for page in s.get_paginator("list_state_machines").paginate():
        for m in page.get("stateMachines", []):
            rows.append([m["name"], m.get("type", ""), str(m.get("creationDate", ""))[:19]])
    ui.table(["state machine", "type", "created"], rows,
             empty="No state machines. Try 'awsemu sfn deploy NAME definition.json'.")


@sfn.command(name="deploy")
@click.argument("name")
@click.argument("definition")
@click.option("--express", is_flag=True, help="EXPRESS type (default STANDARD).")
@click.option("--role", metavar="ARN", help=f"Execution role (default: creates '{DEFAULT_ROLE_NAME}').")
@pass_ctx
@handle_errors
def deploy(c: Ctx, name: str, definition: str, express: bool, role: str | None):
    """Create or update a state machine from a file or inline JSON.

    \b
      awsemu sfn deploy hello flow.asl.json
      awsemu sfn deploy hello '{"StartAt": "Hi", "States": {"Hi": {"Type": "Pass", "End": true}}}'
    """
    body = read_definition(definition)
    s = client("stepfunctions", c.port)
    target = machine_arn(name)
    try:
        s.describe_state_machine(stateMachineArn=target)
        exists = True
    except Exception as exc:
        if not is_error(exc, "StateMachineDoesNotExist", "ResourceNotFound"):
            raise
        exists = False
    if exists:
        kwargs = {"stateMachineArn": target, "definition": body}
        if role:
            kwargs["roleArn"] = role
        s.update_state_machine(**kwargs)
        ui.success(f"updated {name}")
        return
    role = role or ensure_service_role(client("iam", c.port), DEFAULT_ROLE_NAME,
                                       "states.amazonaws.com", "Created by awsemu for Step Functions")
    created = s.create_state_machine(name=name, definition=body, roleArn=role,
                                     type="EXPRESS" if express else "STANDARD")
    ui.success(f"created {name}")
    ui.echo(created["stateMachineArn"], "muted")


def _history_error(s, execution_arn: str) -> str | None:
    """Find a readable cause in the execution history when the output has none."""
    try:
        events = s.get_execution_history(executionArn=execution_arn, reverseOrder=True,
                                         maxResults=20).get("events", [])
    except Exception:
        return None
    for e in events:
        for key, details in e.items():
            if key.endswith("EventDetails") and isinstance(details, dict) and \
                    ("error" in details or "cause" in details):
                return f"{details.get('error', '')}: {details.get('cause', '')}".strip(": ")
    return None


@sfn.command(name="start")
@click.argument("name")
@click.argument("input_json", required=False, default="{}")
@click.option("--file", "file_", type=click.File("r"), help="Input from a file ('-' = stdin).")
@click.option("--no-wait", is_flag=True, help="Start and return without waiting for the result.")
@click.option("--timeout", type=float, default=120, show_default=True, metavar="SECONDS")
@click.option("--raw", is_flag=True, help="Print only the output JSON.")
@pass_ctx
@handle_errors
def start(c: Ctx, name: str, input_json: str, file_, no_wait: bool, timeout: float, raw: bool):
    """Start an execution and (by default) wait for its result."""
    if file_ is not None:
        input_json = file_.read()
    load_json_arg(input_json, "input")
    s = client("stepfunctions", c.port)
    exec_arn = s.start_execution(stateMachineArn=machine_arn(name), input=input_json,
                                 name=f"awsemu-{uuid.uuid4().hex[:12]}")["executionArn"]
    if no_wait:
        ui.success("started")
        ui.echo(exec_arn, "muted")
        return
    deadline = time.monotonic() + timeout
    while True:
        d = s.describe_execution(executionArn=exec_arn)
        if d["status"] in FINAL:
            break
        if time.monotonic() > deadline:
            raise click.ClickException(f"still {d['status']} after {timeout:.0f}s: {exec_arn}")
        time.sleep(0.5)
    output = d.get("output")
    if raw:
        click.echo(output or "")
        raise SystemExit(0 if d["status"] == "SUCCEEDED" else 1)
    if output:
        try:
            ui.print_json(json.loads(output))
        except ValueError:
            click.echo(output)
    took = (d["stopDate"] - d["startDate"]).total_seconds() if d.get("stopDate") else None
    if d["status"] == "SUCCEEDED":
        ui.success("SUCCEEDED" + (f" in {took:.2f}s" if took is not None else ""))
        return
    cause = " ".join(x for x in (d.get("error"), d.get("cause")) if x) or _history_error(s, exec_arn)
    ui.error(d["status"] + (f": {cause}" if cause else ""))
    raise SystemExit(1)


@sfn.command(name="executions")
@click.argument("name")
@click.option("-n", "--limit", type=int, default=20, show_default=True)
@pass_ctx
@handle_errors
def executions(c: Ctx, name: str, limit: int):
    """Recent executions of a state machine."""
    resp = client("stepfunctions", c.port).list_executions(stateMachineArn=machine_arn(name),
                                                           maxResults=limit)
    rows = [[e["name"], ui.styled(e["status"], STATUS_STYLE.get(e["status"])),
             str(e.get("startDate", ""))[:19], str(e.get("stopDate", "") or "")[:19]]
            for e in resp.get("executions", [])]
    ui.table(["execution", "status", "started", "stopped"], rows, empty="No executions yet.")


@sfn.command(name="rm")
@click.argument("name")
@click.option("-y", "--yes", is_flag=True)
@pass_ctx
@handle_errors
def rm(c: Ctx, name: str, yes: bool):
    """Delete a state machine."""
    if not yes:
        click.confirm(f"Delete state machine {name}?", abort=True)
    client("stepfunctions", c.port).delete_state_machine(stateMachineArn=machine_arn(name))
    ui.success(f"deleted {name}")
