"""``awsemu lambda``: deploy, invoke and inspect functions."""

from __future__ import annotations

import base64
import hashlib
import json
import time
from datetime import datetime
from pathlib import Path

import click

from .. import errors, exitcodes
from .. import ui
from ..clients import client
from ..completion import complete
from ..context import Ctx, handle_errors, json_option, pass_ctx, yes_option
from ._common import client_error, is_error, parse_kv
from ..services.lambda_ import (
    DEFAULT_ROLE_NAME,
    ensure_role,
    fingerprint,
    function_exists,
    guess_handler_and_runtime,
    package,
    wait_function,
)


def parse_env(pairs) -> dict[str, str]:
    return parse_kv(pairs, "--env")


# --------------------------------------------------------------------------- commands


@click.group(name="lambda")
def lambda_():
    """Lambda: deploy, invoke and inspect functions. Alias: 'awsemu fn'."""


@lambda_.command(name="ls")
@json_option
@pass_ctx
@handle_errors
def ls(c: Ctx, as_json: bool):
    """List functions."""
    lam = client("lambda", c.port)
    functions = []
    for page in lam.get_paginator("list_functions").paginate():
        functions += page.get("Functions", [])
    if as_json:
        ui.print_json(functions)
        return
    rows = [
        [
            f["FunctionName"],
            f.get("Runtime", f.get("PackageType", "")),
            f.get("Handler", ""),
            f.get("MemorySize", ""),
            f.get("Timeout", ""),
            (f.get("LastModified") or "")[:19],
        ]
        for f in functions
    ]
    ui.table(
        ["function", "runtime", "handler", "MB", "timeout", "modified"],
        rows,
        empty="No functions. Try 'awsemu lambda deploy NAME ./src'.",
    )


@lambda_.command(name="deploy")
@click.argument("name", required=False, shell_complete=complete("function"))
@click.argument("source", type=click.Path(exists=True, path_type=Path), required=False)
@click.option("--handler", help="e.g. app.handler (guessed from the code if omitted).")
@click.option("--runtime", help="e.g. python3.12, nodejs20.x (guessed if omitted).")
@click.option("--role", metavar="ARN", help=f"Execution role (default: creates '{DEFAULT_ROLE_NAME}').")
@click.option("-e", "--env", "env_pairs", multiple=True, metavar="KEY=VALUE", help="Environment variable. Repeatable.")
@click.option("--timeout", type=click.IntRange(1, 900), help="Seconds.")
@click.option("--memory", type=click.IntRange(128, 10240), help="MB.")
@click.option(
    "--deps/--no-deps",
    default=True,
    show_default=True,
    help="Install a folder's requirements.txt into the package (Python).",
)
@click.option("-w", "--watch", is_flag=True, help="Keep running and redeploy when a file changes.")
@click.option(
    "--invoke", "invoke_payload", metavar="JSON", help="Invoke the function with this payload after each deploy."
)
@pass_ctx
@handle_errors
def deploy(c: Ctx, name, source, handler, runtime, role, env_pairs, timeout, memory, deps, watch, invoke_payload):
    """Create or update a function from a folder, a single file or a .zip.

    With only a path, the function is named after it (./orders -> orders).
    --watch redeploys on every save, and --invoke runs it each time: the loop
    of changing a function, without a zip and three commands.

    \b
      awsemu lambda deploy hello ./hello.py
      awsemu lambda deploy api ./src --handler app.handler -e STAGE=local
      awsemu lambda deploy ./orders --watch --invoke '{"id": 1}'
    """
    if source is None:
        if name is None or not Path(name).exists():
            raise click.UsageError("pass the code: 'awsemu lambda deploy [NAME] PATH'")
        source = Path(name)
        name = (source.stem if source.is_file() else source.resolve().name).replace(" ", "-")
    if invoke_payload is not None:
        try:
            json.loads(invoke_payload)
        except json.JSONDecodeError as exc:
            raise click.BadParameter(f"not JSON: {exc}", param_hint="--invoke") from exc
    if watch and source.is_file() and source.suffix == ".zip":
        raise click.UsageError("--watch needs a folder or a source file, not a .zip")

    guessed_handler, guessed_runtime = guess_handler_and_runtime(source)
    handler = handler or guessed_handler
    runtime = runtime or guessed_runtime
    lam = client("lambda", c.port)
    env = parse_env(env_pairs)

    config: dict = {}
    if handler:
        config["Handler"] = handler
    if runtime:
        config["Runtime"] = runtime
    if timeout:
        config["Timeout"] = timeout
    if memory:
        config["MemorySize"] = memory
    if env:
        config["Environment"] = {"Variables": env}

    code = package(source, runtime, deps, ui.info)
    if function_exists(lam, name):
        lam.update_function_code(FunctionName=name, ZipFile=code)
        wait_function(lam, "function_updated_v2", name)
        if role:
            config["Role"] = role
        if config:
            lam.update_function_configuration(FunctionName=name, **config)
            wait_function(lam, "function_updated_v2", name)
        ui.success(f"updated {name} ({ui.human_size(len(code))})")
    else:
        if not handler or not runtime:
            raise click.UsageError("couldn't guess the handler/runtime; pass --handler and --runtime")
        config["Role"] = role or ensure_role(client("iam", c.port))
        lam.create_function(FunctionName=name, Code={"ZipFile": code}, **config)
        wait_function(lam, "function_active_v2", name)
        ui.success(f"created {name}: {runtime}, handler {handler} ({ui.human_size(len(code))})")
        if not watch and invoke_payload is None:
            ui.echo(f"Try: awsemu lambda invoke {name} '{{}}'", "muted")

    ok = True
    if invoke_payload is not None:
        ok = _invoke_and_show(lam, name, invoke_payload)
    if not watch:
        if not ok:
            raise SystemExit(exitcodes.FAILED)
        return
    _watch(lam, name, source, runtime, deps, invoke_payload, code)


POLL_SECONDS = 0.5
SETTLE_SECONDS = 0.3  # editors save in several writes; wait until they're done


def _invoke_and_show(lam, name: str, payload: str) -> bool:
    """Invoke once and print the result in one block; False on a function error."""
    started = time.monotonic()
    resp = lam.invoke(FunctionName=name, Payload=payload.encode("utf-8"), LogType="Tail")
    elapsed = time.monotonic() - started
    body = resp["Payload"].read().decode("utf-8", "replace") if resp.get("Payload") else ""
    if resp.get("LogResult"):
        for line in base64.b64decode(resp["LogResult"]).decode("utf-8", "replace").splitlines():
            if line and not line.startswith(("START ", "END ", "REPORT ")):
                ui.echo(f"  {line}", "muted")
    try:
        ui.print_json(json.loads(body))
    except (json.JSONDecodeError, ValueError):
        click.echo(body)
    if resp.get("FunctionError"):
        ui.error(f"function error ({resp['FunctionError']}) after {elapsed:.2f}s")
        return False
    ui.echo(f"invoked in {elapsed:.2f}s", "muted")
    return True


def _watch(lam, name, source, runtime, deps, invoke_payload, code, *, max_rounds=None) -> None:
    """Poll the files and redeploy the code when it changes, until Ctrl+C.

    A failed deploy (a syntax error the emulator rejects, pip failing) is shown and
    the watch goes on: the next save tries again. ``max_rounds`` is for tests."""
    last_print = fingerprint(source)
    last_sha = hashlib.sha256(code).digest()
    ui.echo(f"watching {source} — save a file to redeploy {name}, Ctrl+C to stop", "muted")
    rounds = 0
    try:
        while max_rounds is None or rounds < max_rounds:
            rounds += 1
            time.sleep(POLL_SECONDS)
            current = fingerprint(source)
            if current == last_print:
                continue
            time.sleep(SETTLE_SECONDS)
            current = fingerprint(source)
            last_print = current
            stamp = datetime.now().strftime("%H:%M:%S")
            try:
                code = package(source, runtime, deps, ui.info)
            except errors.AwsemuError as exc:  # nothing to package, or pip failed: keep watching
                ui.error(f"{stamp} {exc}")
                continue
            sha = hashlib.sha256(code).digest()
            if sha == last_sha:
                continue  # only a skipped file, or a save without changes
            try:
                lam.update_function_code(FunctionName=name, ZipFile=code)
                wait_function(lam, "function_updated_v2", name)
            except Exception as exc:  # keep watching; the next save retries
                ui.error(f"{stamp} couldn't update {name}: {exc}")
                continue
            last_sha = sha
            ui.success(f"{stamp} updated {name} ({ui.human_size(len(code))})")
            if invoke_payload is not None:
                try:
                    _invoke_and_show(lam, name, invoke_payload)
                except Exception as exc:
                    ui.error(f"{stamp} couldn't invoke {name}: {exc}")
    except KeyboardInterrupt:
        ui.echo("stopped watching", "muted")


@lambda_.command(name="invoke")
@click.argument("name", shell_complete=complete("function"))
@click.argument("payload", required=False)
@click.option("--file", "file_", type=click.File("r"), help="Payload from a file ('-' = stdin).")
@click.option("--async", "is_async", is_flag=True, help="Event invocation (don't wait for the result).")
@click.option(
    "--logs/--no-logs", "show_logs", default=True, show_default=True, help="Show the log tail returned by Lambda."
)
@click.option("--raw", is_flag=True, help="Print only the response payload.")
@pass_ctx
@handle_errors
def invoke(c: Ctx, name: str, payload: str | None, file_, is_async: bool, show_logs: bool, raw: bool):
    """Invoke a function with a JSON payload: 'awsemu lambda invoke hello '{"name": "Ana"}''."""
    if payload is None and file_ is not None:
        payload = file_.read()
    payload = payload if payload is not None else "{}"
    try:
        json.loads(payload)
    except json.JSONDecodeError as exc:
        raise click.BadParameter(f"payload is not JSON: {exc}") from exc

    lam = client("lambda", c.port)
    kwargs = {"FunctionName": name, "Payload": payload.encode("utf-8")}
    if is_async:
        kwargs["InvocationType"] = "Event"
    elif show_logs and not raw:
        kwargs["LogType"] = "Tail"
    started = time.monotonic()
    resp = lam.invoke(**kwargs)
    elapsed = time.monotonic() - started
    if is_async:
        ui.success(f"queued (HTTP {resp.get('StatusCode')})")
        return

    body = resp["Payload"].read().decode("utf-8", "replace") if resp.get("Payload") else ""
    error = resp.get("FunctionError")
    if raw:
        click.echo(body)
        raise SystemExit(exitcodes.FAILED if error else exitcodes.OK)

    if show_logs and resp.get("LogResult"):
        ui.echo("── logs ──", "muted")
        for line in base64.b64decode(resp["LogResult"]).decode("utf-8", "replace").splitlines():
            ui.echo(line, "muted")
        ui.echo("──────────", "muted")
    try:
        ui.print_json(json.loads(body))
    except (json.JSONDecodeError, ValueError):
        click.echo(body)
    if error:
        ui.error(f"function error ({error}) after {elapsed:.2f}s")
        raise SystemExit(exitcodes.FAILED)
    ui.echo(
        f"HTTP {resp.get('StatusCode')} in {elapsed:.2f}s"
        + (f", version {resp['ExecutedVersion']}" if resp.get("ExecutedVersion") else ""),
        "muted",
    )


@lambda_.command(name="logs")
@click.argument("name", shell_complete=complete("function"))
@click.option("-f", "--follow", is_flag=True, help="Keep printing new log events.")
@click.option(
    "--since", type=int, default=60, show_default=True, metavar="MINUTES", help="Start this many minutes ago."
)
@pass_ctx
@handle_errors
def logs_cmd(c: Ctx, name: str, follow: bool, since: int):
    """Show the function's CloudWatch logs (/aws/lambda/NAME).

    Note: AWS Emulator doesn't write Lambda output to CloudWatch Logs; use
    'awsemu lambda invoke', which prints the log of that invocation.
    """
    logs = client("logs", c.port)
    group = f"/aws/lambda/{name}"
    start = int((time.time() - since * 60) * 1000)
    seen: set[str] = set()
    try:
        while True:
            kwargs = {"logGroupName": group, "startTime": start}
            try:
                for page in logs.get_paginator("filter_log_events").paginate(**kwargs):
                    for ev in page.get("events", []):
                        if ev["eventId"] in seen:
                            continue
                        seen.add(ev["eventId"])
                        ts = time.strftime("%H:%M:%S", time.localtime(ev["timestamp"] / 1000))
                        ui.echo(f"{ts}  {ev['message'].rstrip()}")
                        start = max(start, ev["timestamp"])
            except client_error() as exc:
                if not is_error(exc, "ResourceNotFound"):
                    raise
                if not follow:
                    ui.warn(f"No log group {group}.")
                    ui.echo(
                        "AWS Emulator doesn't send Lambda output to CloudWatch Logs. "
                        f"'awsemu lambda invoke {name}' shows the log of each invocation.",
                        "muted",
                        err=True,
                    )
                    return
            if not follow:
                return
            time.sleep(2)
    except KeyboardInterrupt:
        pass


@lambda_.command(name="info")
@click.argument("name", shell_complete=complete("function"))
@pass_ctx
@handle_errors
def info(c: Ctx, name: str):
    """Show a function's configuration."""
    cfg = client("lambda", c.port).get_function(FunctionName=name)["Configuration"]
    env = cfg.get("Environment", {}).get("Variables", {})
    ui.kv(
        [
            ("arn", cfg.get("FunctionArn")),
            ("runtime", cfg.get("Runtime")),
            ("handler", cfg.get("Handler")),
            ("role", cfg.get("Role")),
            ("memory", f"{cfg.get('MemorySize')} MB"),
            ("timeout", f"{cfg.get('Timeout')} s"),
            ("state", cfg.get("State")),
            ("code size", ui.human_size(cfg.get("CodeSize"))),
            ("modified", cfg.get("LastModified")),
            ("env", ", ".join(f"{k}={v}" for k, v in env.items())),
        ],
        title=name,
    )


@lambda_.command(name="rm")
@click.argument("name", shell_complete=complete("function"))
@yes_option
@pass_ctx
@handle_errors
def rm(c: Ctx, name: str, yes: bool):
    """Delete a function."""
    if not yes:
        click.confirm(f"Delete function {name}?", abort=True)
    client("lambda", c.port).delete_function(FunctionName=name)
    ui.success(f"deleted {name}")
