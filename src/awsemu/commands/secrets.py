"""``awsemu secrets`` (Secrets Manager) and ``awsemu ssm`` (Parameter Store)."""

from __future__ import annotations

import json

import click

from .. import exitcodes
from .. import ui
from ..clients import client
from ..completion import complete
from ..context import Ctx, handle_errors, pass_ctx, json_option, yes_option
from ._common import client_error, is_error


def _read_value(value: str | None, file_) -> str:
    if value is None:
        if file_ is None:
            raise click.UsageError("give a VALUE or --file")
        value = file_.read()
    return value


def _show_value(value: str, as_json: bool) -> None:
    """Pretty-print JSON values, print anything else as-is."""
    try:
        parsed = json.loads(value)
    except (ValueError, TypeError):
        parsed = None
    if isinstance(parsed, (dict, list)) and not as_json:
        ui.print_json(parsed)
    else:
        click.echo(value)


# =========================================================================== Secrets Manager


@click.group()
def secrets():
    """Secrets Manager: store and read secrets."""


@secrets.command(name="ls")
@json_option
@pass_ctx
@handle_errors
def secrets_ls(c: Ctx, as_json: bool):
    """List secrets (names only, never values)."""
    sm = client("secretsmanager", c.port)
    items = []
    for page in sm.get_paginator("list_secrets").paginate():
        items += page.get("SecretList", [])
    if as_json:
        ui.print_json(items)
        return
    rows = [[s["Name"], s.get("Description", ""), str(s.get("LastChangedDate", ""))[:19]] for s in items]
    ui.table(["secret", "description", "changed"], rows, empty="No secrets. Try 'awsemu secrets put NAME VALUE'.")


@secrets.command(name="get")
@click.argument("name", shell_complete=complete("secret"))
@click.option("--stage", default="AWSCURRENT", show_default=True, help="Version stage.")
@click.option("--raw", is_flag=True, help="Print the value untouched (no JSON formatting).")
@pass_ctx
@handle_errors
def secrets_get(c: Ctx, name: str, stage: str, raw: bool):
    """Print a secret's value (JSON values are pretty-printed)."""
    resp = client("secretsmanager", c.port).get_secret_value(SecretId=name, VersionStage=stage)
    if "SecretString" in resp:
        _show_value(resp["SecretString"], raw)
    else:
        click.echo(resp.get("SecretBinary", b"").hex() if not raw else resp.get("SecretBinary"))


@secrets.command(name="put")
@click.argument("name", shell_complete=complete("secret"))
@click.argument("value", required=False)
@click.option("--file", "file_", type=click.File("r"), help="Read the value from a file ('-' = stdin).")
@click.option("--description", help="Free text stored with it.")
@pass_ctx
@handle_errors
def secrets_put(c: Ctx, name: str, value: str | None, file_, description: str | None):
    """Create a secret, or store a new version if it exists.

    \b
      awsemu secrets put db/password 's3cr3t'
      awsemu secrets put db/config '{"host": "localhost", "port": 5432}'
      awsemu secrets put tls/key --file key.pem
    """
    value = _read_value(value, file_)
    sm = client("secretsmanager", c.port)
    try:
        kwargs = {"Name": name, "SecretString": value}
        if description:
            kwargs["Description"] = description
        sm.create_secret(**kwargs)
        ui.success(f"created {name}")
    except client_error() as exc:
        if not is_error(exc, "ResourceExists"):
            raise
        sm.put_secret_value(SecretId=name, SecretString=value)
        if description:
            sm.update_secret(SecretId=name, Description=description)
        ui.success(f"stored a new version of {name}")


@secrets.command(name="rm")
@click.argument("name", shell_complete=complete("secret"))
@click.option("--now", is_flag=True, help="Delete immediately, without a recovery window.")
@yes_option
@pass_ctx
@handle_errors
def secrets_rm(c: Ctx, name: str, now: bool, yes: bool):
    """Delete a secret (with a 7-day recovery window unless --now)."""
    if not yes:
        click.confirm(f"Delete secret {name}?", abort=True)
    kwargs: dict = {"SecretId": name}
    if now:
        kwargs["ForceDeleteWithoutRecovery"] = True
    else:
        kwargs["RecoveryWindowInDays"] = 7
    client("secretsmanager", c.port).delete_secret(**kwargs)
    ui.success(f"deleted {name}" + ("" if now else " (recoverable for 7 days)"))


@secrets.command(name="info")
@click.argument("name", shell_complete=complete("secret"))
@pass_ctx
@handle_errors
def secrets_info(c: Ctx, name: str):
    """Show a secret's metadata and versions (not its value)."""
    d = client("secretsmanager", c.port).describe_secret(SecretId=name)
    versions = ", ".join(f"{vid[:8]} ({'/'.join(stages)})" for vid, stages in d.get("VersionIdsToStages", {}).items())
    ui.kv(
        [
            ("arn", d.get("ARN")),
            ("description", d.get("Description")),
            ("created", d.get("CreatedDate")),
            ("changed", d.get("LastChangedDate")),
            ("deleted", d.get("DeletedDate")),
            ("versions", versions),
        ],
        title=name,
    )


# =========================================================================== SSM Parameter Store


@click.group()
def ssm():
    """SSM Parameter Store: configuration parameters."""


@ssm.command(name="ls")
@click.argument("path", required=False)
@click.option("--values", is_flag=True, help="Also show values (SecureString shown as ****).")
@json_option
@pass_ctx
@handle_errors
def ssm_ls(c: Ctx, path: str | None, values: bool, as_json: bool):
    """List parameters, optionally under a PATH like /app/prod."""
    s = client("ssm", c.port)
    params: list[dict] = []
    if path:
        for page in s.get_paginator("get_parameters_by_path").paginate(Path=path, Recursive=True, WithDecryption=False):
            params += page.get("Parameters", [])
    else:
        for page in s.get_paginator("describe_parameters").paginate():
            params += page.get("Parameters", [])
        if values or as_json:
            names = [p["Name"] for p in params]
            found = {}
            for i in range(0, len(names), 10):
                for p in s.get_parameters(Names=names[i : i + 10]).get("Parameters", []):
                    found[p["Name"]] = p.get("Value")
            for p in params:
                p["Value"] = found.get(p["Name"])
    if as_json:
        ui.print_json(params)
        return
    rows = []
    for p in params:
        row = [p["Name"], p.get("Type", ""), p.get("Version", "")]
        if values:
            row.append("****" if p.get("Type") == "SecureString" else p.get("Value", ""))
        rows.append(row)
    cols = ["parameter", "type", "version"] + (["value"] if values else [])
    ui.table(cols, rows, empty="No parameters. Try 'awsemu ssm put /app/name VALUE'.")


@ssm.command(name="get")
@click.argument("name", shell_complete=complete("parameter"))
@click.option("--no-decrypt", is_flag=True, help="Don't decrypt SecureString values.")
@pass_ctx
@handle_errors
def ssm_get(c: Ctx, name: str, no_decrypt: bool):
    """Print a parameter's value."""
    p = client("ssm", c.port).get_parameter(Name=name, WithDecryption=not no_decrypt)["Parameter"]
    click.echo(p.get("Value", ""))


@ssm.command(name="put")
@click.argument("name", shell_complete=complete("parameter"))
@click.argument("value", required=False)
@click.option("--file", "file_", type=click.File("r"), help="Read the value from a file ('-' = stdin).")
@click.option("--secure", is_flag=True, help="Store as SecureString.")
@click.option("--list", "as_list", is_flag=True, help="Store as StringList (comma-separated).")
@click.option("--description", help="Free text stored with it.")
@pass_ctx
@handle_errors
def ssm_put(c: Ctx, name: str, value: str | None, file_, secure: bool, as_list: bool, description: str | None):
    """Create or overwrite a parameter: 'awsemu ssm put /app/db/host localhost'."""
    if secure and as_list:
        raise click.UsageError("--secure and --list are mutually exclusive")
    value = _read_value(value, file_)
    kind = "SecureString" if secure else "StringList" if as_list else "String"
    kwargs = {"Name": name, "Value": value, "Type": kind, "Overwrite": True}
    if description:
        kwargs["Description"] = description
    version = client("ssm", c.port).put_parameter(**kwargs).get("Version")
    ui.success(f"{name} = {'****' if secure else value}  ({kind}, version {version})")


@ssm.command(name="rm")
@click.argument("names", nargs=-1, required=True, shell_complete=complete("parameter"))
@pass_ctx
@handle_errors
def ssm_rm(c: Ctx, names):
    """Delete one or more parameters."""
    s = client("ssm", c.port)
    missing = 0
    for i in range(0, len(names), 10):
        resp = s.delete_parameters(Names=list(names[i : i + 10]))
        for n in resp.get("DeletedParameters", []):
            ui.success(f"deleted {n}")
        for n in resp.get("InvalidParameters", []):
            ui.warn(f"not found: {n}")
            missing += 1
    if missing:
        raise SystemExit(exitcodes.FAILED)
