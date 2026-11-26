"""``awsemu describe ARN``: show any supported resource from its ARN."""

from __future__ import annotations

import click

from .. import ui
from ..arns import Arn, parse_arn  # noqa: F401  (Arn: re-exported)
from ..context import Ctx, handle_errors, pass_ctx
from ..services import all_services


# {service in the ARN: (arn, port, full arn) -> data}, from the service registry.
HANDLERS = {s.arn: s.describe for s in all_services() if s.describe}


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
            f"describe doesn't know '{parsed.service}' yet; try 'awsemu aws {parsed.service} ...'"
        )
    ui.print_json(handler(parsed, c.port, arn))
