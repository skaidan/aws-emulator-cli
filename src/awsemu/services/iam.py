"""AWS IAM: roles, users and policies (the emulator doesn't enforce them)."""

from __future__ import annotations


from .. import clients, errors
from . import Service, pages


def roles(c) -> list[str]:
    return pages(c, "list_roles", "Roles", "RoleName")


def details(port, name):
    return clients.client("iam", port).get_role(RoleName=name)["Role"]


def describe(a, port, full):
    iam = clients.client("iam", port)
    name = a.rest.rsplit("/", 1)[-1]
    if a.kind == "role":
        return iam.get_role(RoleName=name)["Role"]
    if a.kind == "user":
        return iam.get_user(UserName=name)["User"]
    if a.kind == "policy":
        return iam.get_policy(PolicyArn=f"arn:aws:iam::{a.account}:{a.resource}")["Policy"]
    raise errors.AwsemuError(f"IAM resource type '{a.kind}' isn't supported by describe")


SERVICE = Service(
    name="iam",
    label="IAM roles",
    names=roles,
    details=details,
    describe=describe,
    missing={
        "watch": "roles change rarely; `awsemu lambda deploy` creates the one it needs",
        "completions": "no command takes a role name",
        "apply": "seeds have no IAM section: `functions` create the role they need",
        "export": "seeds have no IAM section: `functions` create the role they need",
    },
)
