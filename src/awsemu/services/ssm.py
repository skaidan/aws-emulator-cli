"""AWS Systems Manager Parameter Store: parameters."""

from __future__ import annotations


from .. import clients
from .. import realaccount
from .. import seed as seedlib
from ..awserrors import client_error, is_error
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


def apply(seed, port, report):
    ssm = clients.client("ssm", port)
    for p in seed.section("parameters"):
        name = p["name"]
        value, kind = seedlib.parameter_value(p)
        try:
            try:
                cur = ssm.get_parameter(Name=name, WithDecryption=True)["Parameter"]
                if cur.get("Value") == value and cur.get("Type") == kind:
                    report.add("parameter", name, "unchanged")
                    continue
                result = "updated"
            except client_error() as exc:
                if not is_error(exc, "ParameterNotFound"):
                    raise
                result = "created"
            kwargs = {"Name": name, "Value": value, "Type": kind, "Overwrite": True}
            if p.get("description"):
                kwargs["Description"] = p["description"]
            ssm.put_parameter(**kwargs)
            report.add("parameter", name, result, kind if kind != "String" else "")
        except Exception as exc:
            report.add("parameter", name, "failed", clients.describe_error(exc))


def export(port: int, opts: seedlib.ExportOptions) -> list[dict]:
    ssm = clients.client("ssm", port)
    params = []
    described = []
    for page in ssm.get_paginator("describe_parameters").paginate():
        described += page.get("Parameters", [])
    values = {}
    names = [p["Name"] for p in described]
    for i in range(0, len(names), 10):
        for p in ssm.get_parameters(Names=names[i : i + 10], WithDecryption=True).get("Parameters", []):
            values[p["Name"]] = p
    for d in described:
        p = values.get(d["Name"])
        if p is None:
            continue
        if p["Type"] == "SecureString" and not opts.include_secrets:
            continue
        entry = {"name": d["Name"]}
        if p["Type"] == "StringList":
            entry["value"] = p["Value"].split(",")
        else:
            entry["value"] = p["Value"]
            if p["Type"] != "String":
                entry["type"] = p["Type"]
        if d.get("Description"):
            entry["description"] = d["Description"]
        params.append(entry)
    return params


def seed_import(sess, opts: seedlib.ImportOptions) -> list[dict]:
    """``parameters`` of a real account (read-only), for ``awsemu seed import``."""
    ssm = realaccount.client(sess, "ssm")
    params = []
    for page in ssm.get_paginator("describe_parameters").paginate():
        for d in page.get("Parameters", []):
            entry = {"name": d["Name"]}
            if d.get("Type") == "SecureString":
                entry.update(value=realaccount.PLACEHOLDER, type="SecureString")
            else:
                entry["value"] = None  # filled below, without decryption
                if d.get("Type") == "StringList":
                    entry["type"] = "StringList"
            if d.get("Description"):
                entry["description"] = d["Description"]
            params.append(entry)
    plain = [p for p in params if p["value"] is None]
    for i in range(0, len(plain), 10):
        batch = {p["name"]: p for p in plain[i : i + 10]}
        # DescribeParameters doesn't return values; GetParameters without decryption is allowed
        for p in ssm.get_parameters(Names=list(batch), WithDecryption=False).get("Parameters", []):
            if p["Type"] in ("String", "StringList") and p["Name"] in batch:
                batch[p["Name"]]["value"] = p["Value"].split(",") if p["Type"] == "StringList" else p["Value"]
                batch[p["Name"]].pop("type", None)
    params = [p for p in params if p["value"] is not None]
    return params


def cost(call) -> list[tuple[str, float]]:
    return []  # standard parameters have no request charge


SERVICE = Service(
    name="ssm",
    label="SSM parameters",
    names=parameters,
    details=details,
    describe=describe,
    watch=names_snapshot("parameter", parameters),
    completions={"parameter": lambda c, i: pages(c, "describe_parameters", "Parameters", "Name", cap=COMPLETE_MAX)},
    seed_section="parameters",
    apply=apply,
    export=export,
    seed_import=seed_import,
    cost=cost,
)
