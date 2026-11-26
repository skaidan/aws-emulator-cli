"""AWS Lambda: functions."""

from __future__ import annotations

from .. import clients
from . import COMPLETE_MAX, Service, names_snapshot, pages


def functions(c) -> list[str]:
    return pages(c, "list_functions", "Functions", "FunctionName")


def details(port, name):
    return clients.client("lambda", port).get_function(FunctionName=name)["Configuration"]


def describe(a, port, full):
    return details(port, a.rest.split(":", 1)[0])


SERVICE = Service(
    name="lambda",
    label="Lambda functions",
    names=functions,
    details=details,
    describe=describe,
    watch=names_snapshot("function", functions),
    completions={"function": lambda c, i: pages(c, "list_functions", "Functions", "FunctionName", cap=COMPLETE_MAX)},
)
