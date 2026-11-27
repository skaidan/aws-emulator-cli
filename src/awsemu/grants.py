"""Wiring services together in the emulator: ARNs, service roles, and the permissions
one service needs to send to a queue or invoke a function."""

from __future__ import annotations

import json

from .awserrors import client_error, is_error
from .paths import ACCOUNT_ID, REGION


def arn(service: str, resource: str) -> str:
    return f"arn:aws:{service}:{REGION}:{ACCOUNT_ID}:{resource}"


def ensure_service_role(iam, role_name: str, service: str, description: str) -> str:
    """Return the ARN of ``role_name``, creating it with a trust policy for ``service``."""
    try:
        return iam.get_role(RoleName=role_name)["Role"]["Arn"]
    except client_error() as exc:
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
    from .services.sqs import queue_url

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
    except client_error() as exc:
        if not is_error(exc, "ResourceConflict"):
            raise
    return fn_arn
