"""AWS Step Functions: state machines and executions."""

from __future__ import annotations

import json

from .. import clients
from .. import seed as seedlib
from ..commands._common import arn, ensure_service_role
from ..awserrors import client_error, is_error
from . import COMPLETE_MAX, Service, clean, names_snapshot, pages


def machines(c) -> list[str]:
    return pages(c, "list_state_machines", "stateMachines", "name")


def details(port, name):
    from ..commands.sfn import machine_arn

    s = clients.client("stepfunctions", port)
    machine = clean(s.describe_state_machine(stateMachineArn=machine_arn(name)))
    runs = s.list_executions(stateMachineArn=machine_arn(name), maxResults=10).get("executions", [])
    return {"StateMachine": machine, "Recent executions": runs}


def describe(a, port, full):
    s = clients.client("stepfunctions", port)
    if a.kind == "execution":
        return clean(s.describe_execution(executionArn=full))
    return clean(s.describe_state_machine(stateMachineArn=full))


def apply(seed, port, report):
    from ..commands.sfn import DEFAULT_ROLE_NAME

    sf = clients.client("stepfunctions", port)
    for sm in seed.section("state_machines"):
        name = sm["name"]
        try:
            definition = seedlib.read_definition(sm, seed.base_dir)
            kind = "EXPRESS" if sm.get("express") else "STANDARD"
            target = arn("states", f"stateMachine:{name}")
            try:
                current = sf.describe_state_machine(stateMachineArn=target)
            except client_error() as exc:
                if not is_error(exc, "StateMachineDoesNotExist", "ResourceNotFound"):
                    raise
                role = ensure_service_role(
                    clients.client("iam", port),
                    DEFAULT_ROLE_NAME,
                    "states.amazonaws.com",
                    "Created by awsemu for Step Functions",
                )
                sf.create_state_machine(name=name, definition=json.dumps(definition), roleArn=role, type=kind)
                report.add("state_machine", name, "created", kind.lower())
                continue
            if current.get("type", "STANDARD") != kind:
                report.add(
                    "state_machine",
                    name,
                    "failed",
                    f"it's {current.get('type')} and the seed says {kind}: the type can't change; "
                    "delete it first (awsemu sfn rm)",
                )
                continue
            if json.loads(current["definition"]) != definition:
                sf.update_state_machine(stateMachineArn=target, definition=json.dumps(definition))
                report.add("state_machine", name, "updated", "definition")
            else:
                report.add("state_machine", name, "unchanged")
        except Exception as exc:
            report.add("state_machine", name, "failed", clients.describe_error(exc))


def export(port: int, opts: seedlib.ExportOptions) -> list[dict]:
    sf = clients.client("stepfunctions", port)
    machines = []
    for page in sf.get_paginator("list_state_machines").paginate():
        for m in page.get("stateMachines", []):
            d = sf.describe_state_machine(stateMachineArn=m["stateMachineArn"])
            entry = {"name": m["name"], "definition": json.loads(d["definition"])}
            if d.get("type") == "EXPRESS":
                entry["express"] = True
            machines.append(entry)
    return machines


SERVICE = Service(
    name="stepfunctions",
    arn="states",
    alias="sfn",
    label="Step Functions",
    names=machines,
    details=details,
    describe=describe,
    watch=names_snapshot("state machine", machines),
    completions={
        "statemachine": lambda c, i: pages(c, "list_state_machines", "stateMachines", "name", cap=COMPLETE_MAX)
    },
    seed_section="state_machines",
    apply=apply,
    export=export,
)
