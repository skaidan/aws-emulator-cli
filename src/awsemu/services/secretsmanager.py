"""AWS Secrets Manager: secrets (their values are never shown by the UI)."""

from __future__ import annotations

import json

from .. import clients
from .. import seed as seedlib
from ..awserrors import client_error, is_error
from . import COMPLETE_MAX, Service, clean, names_snapshot, pages


def secrets(c) -> list[str]:
    return pages(c, "list_secrets", "SecretList", "Name")


def details(port, name):
    # Metadata only: values stay hidden in the UI.
    return clean(clients.client("secretsmanager", port).describe_secret(SecretId=name))


def describe(a, port, full):
    return clean(clients.client("secretsmanager", port).describe_secret(SecretId=full))


def apply(seed, port, report):
    sm = clients.client("secretsmanager", port)
    for s in seed.section("secrets"):
        name = s["name"]
        value = seedlib.secret_string(s["value"])
        try:
            try:
                current = sm.get_secret_value(SecretId=name).get("SecretString")
                if current == value:
                    result = "unchanged"
                else:
                    sm.put_secret_value(SecretId=name, SecretString=value)
                    result = "updated"
                if s.get("description"):
                    sm.update_secret(SecretId=name, Description=s["description"])
            except client_error() as exc:
                if not is_error(exc, "ResourceNotFound"):
                    raise
                kwargs = {"Name": name, "SecretString": value}
                if s.get("description"):
                    kwargs["Description"] = s["description"]
                sm.create_secret(**kwargs)
                result = "created"
            report.add("secret", name, result)
        except Exception as exc:
            report.add("secret", name, "failed", clients.describe_error(exc))


def export(port: int, opts: seedlib.ExportOptions) -> list[dict]:
    if not opts.include_secrets:
        return []
    sm = clients.client("secretsmanager", port)
    secrets = []
    for page in sm.get_paginator("list_secrets").paginate():
        for s in page.get("SecretList", []):
            value = sm.get_secret_value(SecretId=s["Name"]).get("SecretString")
            if value is None:
                opts.notes.append(f"skipped binary secret {s['Name']}")
                continue
            try:
                parsed = json.loads(value)
                value = parsed if isinstance(parsed, (dict, list)) else value
            except ValueError:
                pass
            entry = {"name": s["Name"], "value": value}
            if s.get("Description"):
                entry["description"] = s["Description"]
            secrets.append(entry)
    return secrets


SERVICE = Service(
    name="secretsmanager",
    alias="secrets",
    label="Secrets",
    names=secrets,
    details=details,
    describe=describe,
    watch=names_snapshot("secret", secrets),
    completions={"secret": lambda c, i: pages(c, "list_secrets", "SecretList", "Name", cap=COMPLETE_MAX)},
    seed_section="secrets",
    apply=apply,
    export=export,
)
