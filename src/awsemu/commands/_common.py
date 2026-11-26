"""Helpers shared by service commands: roles, queue policies, error codes, wiring targets."""

from __future__ import annotations

import json

import click

from ..paths import ACCOUNT_ID, REGION


def error_code(exc: Exception) -> str:
    """The AWS error code of a botocore error (or the class name)."""
    response = getattr(exc, "response", None)
    if isinstance(response, dict):
        code = response.get("Error", {}).get("Code")
        if code:
            return str(code)
    return type(exc).__name__


def is_error(exc: Exception, *codes: str) -> bool:
    code = error_code(exc)
    return any(c in code or c in type(exc).__name__ for c in codes)


def parse_kv(pairs, option: str = "--attr") -> dict[str, str]:
    out = {}
    for pair in pairs:
        k, sep, v = pair.partition("=")
        if not sep or not k:
            raise click.BadParameter(f"'{pair}' is not KEY=VALUE", param_hint=option)
        out[k] = v
    return out


def load_json_arg(value: str, what: str = "value"):
    try:
        return json.loads(value)
    except json.JSONDecodeError as exc:
        raise click.BadParameter(f"{what} is not valid JSON: {exc}") from exc


def arn(service: str, resource: str) -> str:
    return f"arn:aws:{service}:{REGION}:{ACCOUNT_ID}:{resource}"


def ensure_service_role(iam, role_name: str, service: str, description: str) -> str:
    """Return the ARN of ``role_name``, creating it with a trust policy for ``service``."""
    try:
        return iam.get_role(RoleName=role_name)["Role"]["Arn"]
    except Exception as exc:
        if not is_error(exc, "NoSuchEntity"):
            raise
    trust = {
        "Version": "2012-10-17",
        "Statement": [{"Effect": "Allow", "Principal": {"Service": service}, "Action": "sts:AssumeRole"}],
    }
    return iam.create_role(RoleName=role_name, AssumeRolePolicyDocument=json.dumps(trust), Description=description)[
        "Role"
    ]["Arn"]


def queue_policy_allowing(queue_arn: str, service: str, source_arn: str, sid: str, existing: str | None = None) -> str:
    """A queue policy letting ``service`` send from ``source_arn``, merged with ``existing``.

    Re-running with the same ``sid`` replaces that statement, so it's idempotent.
    """
    policy = json.loads(existing) if existing else {"Version": "2012-10-17", "Statement": []}
    current = policy.get("Statement", [])
    if isinstance(current, dict):  # a single statement may be written without a list
        current = [current]
    statements = [s for s in current if isinstance(s, dict) and s.get("Sid") != sid]
    statements.append(
        {
            "Sid": sid,
            "Effect": "Allow",
            "Principal": {"Service": service},
            "Action": "sqs:SendMessage",
            "Resource": queue_arn,
            "Condition": {"ArnEquals": {"aws:SourceArn": source_arn}},
        }
    )
    policy["Statement"] = statements
    return json.dumps(policy)


def allow_queue(sqs, queue: str, service: str, source_arn: str, sid: str) -> str:
    """Grant ``service`` permission to send to ``queue`` (name or URL); returns the queue ARN."""
    from .sqs import queue_url

    url = queue_url(sqs, queue)
    attrs = sqs.get_queue_attributes(QueueUrl=url, AttributeNames=["QueueArn", "Policy"])["Attributes"]
    sqs.set_queue_attributes(
        QueueUrl=url,
        Attributes={"Policy": queue_policy_allowing(attrs["QueueArn"], service, source_arn, sid, attrs.get("Policy"))},
    )
    return attrs["QueueArn"]


def allow_lambda(lam, function: str, service: str, source_arn: str, sid: str) -> str:
    """Grant ``service`` permission to invoke ``function``; returns the function ARN."""
    fn_arn = lam.get_function(FunctionName=function)["Configuration"]["FunctionArn"]
    try:
        lam.add_permission(
            FunctionName=function,
            StatementId=sid,
            Action="lambda:InvokeFunction",
            Principal=service,
            SourceArn=source_arn,
        )
    except Exception as exc:
        if not is_error(exc, "ResourceConflict"):
            raise
    return fn_arn


class AliasedGroup(click.Group):
    """Lets users type unambiguous prefixes (``awsemu st`` -> status) and a few aliases."""

    ALIASES = {
        "ps": "status",
        "reset": "restart",
        "ddb": "dynamodb",
        "ls": "overview",
        "fn": "lambda",
        "eb": "events",
        "stepfunctions": "sfn",
        "secretsmanager": "secrets",
    }

    def lookup(self, ctx, cmd_name):
        """Find a command by its exact name (subclasses can load it on demand)."""
        return super().get_command(ctx, cmd_name)

    def get_command(self, ctx, cmd_name):
        cmd_name = self.ALIASES.get(cmd_name, cmd_name)
        rv = self.lookup(ctx, cmd_name)
        if rv is not None:
            return rv
        matches = [n for n in self.list_commands(ctx) if n.startswith(cmd_name)]
        if len(matches) == 1:
            return self.lookup(ctx, matches[0])
        if len(matches) > 1:
            ctx.fail(f"'{cmd_name}' is ambiguous: {', '.join(sorted(matches))}")
        return None

    def resolve_command(self, ctx, args):
        _, cmd, args = super().resolve_command(ctx, args)
        return cmd.name if cmd else None, cmd, args
