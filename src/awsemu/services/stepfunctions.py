"""AWS Step Functions: state machines and executions."""

from __future__ import annotations

from .. import clients
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
)
