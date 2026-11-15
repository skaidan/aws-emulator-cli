"""``awsemu describe ARN``: show any supported resource from its ARN."""

from __future__ import annotations

from dataclasses import dataclass

import click

from .. import ui
from ..clients import client
from ..context import Ctx, handle_errors, pass_ctx


@dataclass
class Arn:
    service: str
    region: str
    account: str
    resource: str

    @property
    def kind(self) -> str:
        """``table/users`` -> ``table``; ``function:hi`` -> ``function``."""
        for sep in ("/", ":"):
            if sep in self.resource:
                return self.resource.split(sep, 1)[0]
        return ""

    @property
    def rest(self) -> str:
        """The resource without its kind prefix."""
        for sep in ("/", ":"):
            if sep in self.resource:
                return self.resource.split(sep, 1)[1]
        return self.resource


def parse_arn(text: str) -> Arn:
    parts = text.split(":", 5)
    if len(parts) != 6 or parts[0] != "arn":
        raise click.BadParameter(f"'{text}' is not an ARN (arn:aws:SERVICE:REGION:ACCOUNT:RESOURCE)")
    return Arn(service=parts[2], region=parts[3], account=parts[4], resource=parts[5])


def _clean(resp: dict) -> dict:
    return {k: v for k, v in resp.items() if k != "ResponseMetadata"}


def _s3(a: Arn, port: int):
    bucket, _, key = a.resource.partition("/")
    s3 = client("s3", port)
    if key:
        return {"Bucket": bucket, "Key": key, **_clean(s3.head_object(Bucket=bucket, Key=key))}
    s3.head_bucket(Bucket=bucket)
    count = s3.list_objects_v2(Bucket=bucket, MaxKeys=1000).get("KeyCount", 0)
    return {"Bucket": bucket, "Objects (first 1000)": count,
            **_clean(s3.get_bucket_location(Bucket=bucket))}


def _sqs(a: Arn, port: int):
    q = client("sqs", port)
    url = q.get_queue_url(QueueName=a.resource)["QueueUrl"]
    return {"QueueUrl": url, **q.get_queue_attributes(QueueUrl=url, AttributeNames=["All"])["Attributes"]}


def _dynamodb(a: Arn, port: int):
    return client("dynamodb", port).describe_table(TableName=a.rest.split("/", 1)[0])["Table"]


def _sns(a: Arn, port: int, full: str):
    s = client("sns", port)
    if ":" in a.resource:  # topic:subscription-id
        return s.get_subscription_attributes(SubscriptionArn=full)["Attributes"]
    return s.get_topic_attributes(TopicArn=full)["Attributes"]


def _lambda(a: Arn, port: int):
    name = a.rest.split(":", 1)[0]
    return client("lambda", port).get_function(FunctionName=name)["Configuration"]


def _secrets(a: Arn, port: int, full: str):
    return _clean(client("secretsmanager", port).describe_secret(SecretId=full))


def _ssm(a: Arn, port: int):
    name = "/" + a.rest if not a.rest.startswith("/") else a.rest
    s = client("ssm", port)
    try:
        return s.get_parameter(Name=name)["Parameter"]
    except Exception:
        return s.get_parameter(Name=a.rest)["Parameter"]


def _kinesis(a: Arn, port: int):
    return client("kinesis", port).describe_stream_summary(StreamName=a.rest)["StreamDescriptionSummary"]


def _events(a: Arn, port: int):
    ev = client("events", port)
    if a.kind == "event-bus":
        return _clean(ev.describe_event_bus(Name=a.rest))
    bus, _, name = a.rest.rpartition("/")
    rule = _clean(ev.describe_rule(Name=name, EventBusName=bus or "default"))
    rule["Targets"] = ev.list_targets_by_rule(Rule=name, EventBusName=bus or "default").get("Targets", [])
    return rule


def _states(a: Arn, port: int, full: str):
    s = client("stepfunctions", port)
    if a.kind == "execution":
        return _clean(s.describe_execution(executionArn=full))
    return _clean(s.describe_state_machine(stateMachineArn=full))


def _logs(a: Arn, port: int):
    name = a.rest[:-2] if a.rest.endswith(":*") else a.rest
    groups = client("logs", port).describe_log_groups(logGroupNamePrefix=name).get("logGroups", [])
    match = [g for g in groups if g["logGroupName"] == name]
    if not match:
        raise click.ClickException(f"log group not found: {name}")
    return match[0]


def _iam(a: Arn, port: int):
    iam = client("iam", port)
    name = a.rest.rsplit("/", 1)[-1]
    if a.kind == "role":
        return iam.get_role(RoleName=name)["Role"]
    if a.kind == "user":
        return iam.get_user(UserName=name)["User"]
    if a.kind == "policy":
        return iam.get_policy(PolicyArn=f"arn:aws:iam::{a.account}:{a.resource}")["Policy"]
    raise click.ClickException(f"IAM resource type '{a.kind}' isn't supported by describe")


HANDLERS = {
    "s3": lambda a, p, f: _s3(a, p),
    "sqs": lambda a, p, f: _sqs(a, p),
    "dynamodb": lambda a, p, f: _dynamodb(a, p),
    "sns": _sns,
    "lambda": lambda a, p, f: _lambda(a, p),
    "secretsmanager": _secrets,
    "ssm": lambda a, p, f: _ssm(a, p),
    "kinesis": lambda a, p, f: _kinesis(a, p),
    "events": lambda a, p, f: _events(a, p),
    "states": _states,
    "logs": lambda a, p, f: _logs(a, p),
    "iam": lambda a, p, f: _iam(a, p),
}


@click.command()
@click.argument("arn")
@pass_ctx
@handle_errors
def describe(c: Ctx, arn: str):
    """Show any supported resource from its ARN.

    Works with S3, SQS, DynamoDB, SNS, Lambda, Secrets Manager, SSM, Kinesis,
    EventBridge, Step Functions, CloudWatch Logs and IAM ARNs.
    """
    parsed = parse_arn(arn)
    handler = HANDLERS.get(parsed.service)
    if handler is None:
        raise click.ClickException(
            f"describe doesn't know '{parsed.service}' yet; try 'awsemu aws {parsed.service} ...'")
    ui.print_json(handler(parsed, c.port, arn))
