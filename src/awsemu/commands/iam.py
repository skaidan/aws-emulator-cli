"""``awsemu iam``: the IAM permissions your code needs, from what it called."""

from __future__ import annotations

import json
from pathlib import Path

import click

from .. import iampolicy as ip
from .. import proxy as px
from .. import ui
from ..context import Ctx, handle_errors, pass_ctx
from ..runtime import RuntimeErrorWithHint


@click.group()
def iam():
    """IAM permissions your code needs, from the calls it made (the proxy's log)."""


def load_calls(port: int, calls_file: Path | None) -> tuple[list[dict], Path]:
    from .proxy import read_calls

    log = calls_file or px.ProxyFiles(port).calls
    calls = read_calls(log)
    if not calls:
        raise RuntimeErrorWithHint(f"no calls in {log}",
                                   "Run your tests through the proxy first: awsemu proxy start -d, "
                                   "then awsemu exec --proxy -- pytest.")
    return calls, log


@iam.command()
@click.option("--calls-file", type=click.Path(exists=True, dir_okay=False, path_type=Path), metavar="FILE",
              help="A calls log (default: the proxy's, for --port).")
@click.option("--region", default="*", show_default=True, help="Region in the ARNs.")
@click.option("--account", default="*", show_default=True, help="Account ID in the ARNs.")
@click.option("--service", "services", multiple=True, metavar="NAME", help="Only this service. Repeatable.")
@click.option("--format", "fmt", type=click.Choice(["json", "terraform"]), default="json", show_default=True,
              help="A policy document, or a Terraform aws_iam_policy_document.")
@click.option("-o", "--output", type=click.Path(dir_okay=False, path_type=Path), help="Write it to this file.")
@pass_ctx
@handle_errors
def policy(c: Ctx, calls_file, region, account, services, fmt, output):
    """The least-privilege IAM policy for the calls your code made.

    \\b
      awsemu proxy start -d && awsemu exec --proxy -- pytest
      awsemu iam policy                                # JSON policy document
      awsemu iam policy --account 123456789012 --region eu-west-1
      awsemu iam policy --format terraform -o policy.tf

    Each call becomes an action and, where the call names a resource, its ARN
    (region and account '*' unless you give them). Review it: it covers only
    the calls the proxy saw, and some calls need more (kms for encrypted data,
    iam:PassRole). Guide: docs/iam.md.
    """
    calls, log = load_calls(c.port, calls_file)
    result = ip.build(calls, region, account, set(services) or None)
    if not result.actions:
        raise RuntimeErrorWithHint(f"none of the {len(calls)} logged call(s) needs a permission")
    text = ip.terraform(result) if fmt == "terraform" else json.dumps(result.document, indent=2) + "\n"
    if output:
        output.write_text(text, encoding="utf-8")
        ui.success(f"{len(result.actions)} action(s) from {result.calls} call(s) in {output}")
    else:
        click.echo(text, nl=False)
    if result.skipped:
        ui.echo(f"Need no permission or unrecognised: {', '.join(result.skipped)}", "muted", err=True)
    wide = sorted(a for a, r in result.actions.items() if r == {"*"})
    if wide:
        ui.echo(f"Resource \"*\" (no resource in the calls, or the action allows no other): {', '.join(wide)}",
                "muted", err=True)
