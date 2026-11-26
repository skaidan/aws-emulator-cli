"""AWS Secrets Manager: secrets (their values are never shown by the UI)."""

from __future__ import annotations

from .. import clients
from . import COMPLETE_MAX, Service, clean, names_snapshot, pages


def secrets(c) -> list[str]:
    return pages(c, "list_secrets", "SecretList", "Name")


def details(port, name):
    # Metadata only: values stay hidden in the UI.
    return clean(clients.client("secretsmanager", port).describe_secret(SecretId=name))


def describe(a, port, full):
    return clean(clients.client("secretsmanager", port).describe_secret(SecretId=full))


SERVICE = Service(
    name="secretsmanager",
    alias="secrets",
    label="Secrets",
    names=secrets,
    details=details,
    describe=describe,
    watch=names_snapshot("secret", secrets),
    completions={"secret": lambda c, i: pages(c, "list_secrets", "SecretList", "Name", cap=COMPLETE_MAX)},
)
