"""AWS Systems Manager Parameter Store: parameters."""

from __future__ import annotations

from ..awserrors import client_error
from .. import clients
from . import COMPLETE_MAX, Service, names_snapshot, pages


def parameters(c) -> list[str]:
    return pages(c, "describe_parameters", "Parameters", "Name")


def details(port, name):
    p = clients.client("ssm", port).get_parameter(Name=name, WithDecryption=False)["Parameter"]
    if p.get("Type") == "SecureString":
        p["Value"] = "****"
    return p


def describe(a, port, full):
    name = "/" + a.rest if not a.rest.startswith("/") else a.rest
    s = clients.client("ssm", port)
    try:
        return s.get_parameter(Name=name)["Parameter"]
    except client_error():  # a name without a leading slash
        return s.get_parameter(Name=a.rest)["Parameter"]


SERVICE = Service(
    name="ssm",
    label="SSM parameters",
    names=parameters,
    details=details,
    describe=describe,
    watch=names_snapshot("parameter", parameters),
    completions={"parameter": lambda c, i: pages(c, "describe_parameters", "Parameters", "Name", cap=COMPLETE_MAX)},
)
