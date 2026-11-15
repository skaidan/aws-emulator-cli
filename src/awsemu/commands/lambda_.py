"""``awsemu lambda``: deploy, invoke and inspect functions."""

from __future__ import annotations

import base64
import io
import json
import time
import zipfile
from pathlib import Path

import click

from .. import ui
from ..clients import client
from ..context import Ctx, handle_errors, pass_ctx

DEFAULT_ROLE_NAME = "awsemu-lambda-role"
TRUST_POLICY = {
    "Version": "2012-10-17",
    "Statement": [{"Effect": "Allow", "Principal": {"Service": "lambda.amazonaws.com"},
                   "Action": "sts:AssumeRole"}],
}
SKIP_DIRS = {"__pycache__", ".git", ".venv", "venv", "node_modules/.cache", ".pytest_cache",
             ".mypy_cache"}
SKIP_SUFFIXES = (".pyc", ".pyo")

# Guess the runtime from the handler file when --runtime isn't given.
RUNTIME_BY_SUFFIX = {".py": "python3.12", ".js": "nodejs20.x", ".mjs": "nodejs20.x"}


# --------------------------------------------------------------------------- packaging


def _skip(rel: Path) -> bool:
    return any(part in SKIP_DIRS for part in rel.parts) or rel.suffix in SKIP_SUFFIXES


def build_zip(source: Path) -> bytes:
    """Zip a folder (contents at the zip root), a single file, or pass a .zip through."""
    if source.is_file() and source.suffix == ".zip":
        return source.read_bytes()
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        if source.is_file():
            zf.write(source, source.name)
        else:
            files = sorted(p for p in source.rglob("*") if p.is_file())
            for path in files:
                rel = path.relative_to(source)
                if not _skip(rel):
                    zf.write(path, rel.as_posix())
    data = buf.getvalue()
    if len(zipfile.ZipFile(io.BytesIO(data)).namelist()) == 0:
        raise click.BadParameter(f"nothing to package in {source}")
    return data


def guess_handler_and_runtime(source: Path) -> tuple[str | None, str | None]:
    """``app.py`` with ``def handler`` -> ``("app.handler", "python3.12")``."""
    if source.is_file() and source.suffix != ".zip":
        candidates = [source]
    elif source.is_dir():
        preferred = [source / n for n in ("lambda_function.py", "app.py", "handler.py",
                                          "main.py", "index.mjs", "index.js", "app.js")]
        others = sorted(p for p in source.iterdir()
                        if p.is_file() and p.suffix in RUNTIME_BY_SUFFIX and p not in preferred)
        candidates = preferred + others
    else:
        return None, None
    for path in candidates:
        if not path.is_file():
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        for fn in ("lambda_handler", "handler", "main"):
            if (path.suffix == ".py" and f"def {fn}(" in text) or \
                    (path.suffix in (".js", ".mjs") and (f"exports.{fn}" in text or
                                                         f"export const {fn}" in text or
                                                         f"export async function {fn}" in text or
                                                         f"export function {fn}" in text)):
                return f"{path.stem}.{fn}", RUNTIME_BY_SUFFIX.get(path.suffix)
    return None, None


def parse_env(pairs) -> dict[str, str]:
    env = {}
    for pair in pairs:
        k, sep, v = pair.partition("=")
        if not sep or not k:
            raise click.BadParameter(f"'{pair}' is not KEY=VALUE", param_hint="--env")
        env[k] = v
    return env


def ensure_role(iam) -> str:
    try:
        return iam.get_role(RoleName=DEFAULT_ROLE_NAME)["Role"]["Arn"]
    except Exception as exc:
        if "NoSuchEntity" not in type(exc).__name__ and \
                "NoSuchEntity" not in str(getattr(exc, "response", "")):
            raise
    return iam.create_role(RoleName=DEFAULT_ROLE_NAME,
                           AssumeRolePolicyDocument=json.dumps(TRUST_POLICY),
                           Description="Created by awsemu for Lambda functions")["Role"]["Arn"]


def _wait(lam, waiter_name: str, name: str) -> None:
    """Wait until the function is ready (no-op if this botocore lacks the waiter)."""
    try:
        waiter = lam.get_waiter(waiter_name)
    except ValueError:
        return
    waiter.wait(FunctionName=name, WaiterConfig={"Delay": 1, "MaxAttempts": 60})


def _exists(lam, name: str) -> bool:
    try:
        lam.get_function(FunctionName=name)
        return True
    except Exception as exc:
        if "ResourceNotFound" in type(exc).__name__ or \
                "ResourceNotFound" in str(getattr(exc, "response", "")):
            return False
        raise


# --------------------------------------------------------------------------- commands


@click.group(name="lambda")
def lambda_():
    """Deploy, invoke and inspect Lambda functions."""


@lambda_.command(name="ls")
@pass_ctx
@handle_errors
def ls(c: Ctx):
    """List functions."""
    lam = client("lambda", c.port)
    rows = []
    for page in lam.get_paginator("list_functions").paginate():
        for f in page.get("Functions", []):
            rows.append([f["FunctionName"], f.get("Runtime", f.get("PackageType", "")),
                         f.get("Handler", ""), f.get("MemorySize", ""), f.get("Timeout", ""),
                         (f.get("LastModified") or "")[:19]])
    ui.table(["function", "runtime", "handler", "MB", "timeout", "modified"], rows,
             empty="No functions. Try 'awsemu lambda deploy NAME ./src'.")


@lambda_.command(name="deploy")
@click.argument("name")
@click.argument("source", type=click.Path(exists=True, path_type=Path))
@click.option("--handler", help="e.g. app.handler (guessed from the code if omitted).")
@click.option("--runtime", help="e.g. python3.12, nodejs20.x (guessed if omitted).")
@click.option("--role", metavar="ARN", help=f"Execution role (default: creates '{DEFAULT_ROLE_NAME}').")
@click.option("-e", "--env", "env_pairs", multiple=True, metavar="KEY=VALUE",
              help="Environment variable. Repeatable.")
@click.option("--timeout", type=click.IntRange(1, 900), help="Seconds.")
@click.option("--memory", type=click.IntRange(128, 10240), help="MB.")
@pass_ctx
@handle_errors
def deploy(c: Ctx, name: str, source: Path, handler, runtime, role, env_pairs, timeout, memory):
    """Create or update a function from a folder, a single file or a .zip.

    \b
      awsemu lambda deploy hello ./hello.py
      awsemu lambda deploy api ./src --handler app.handler -e STAGE=local
    """
    guessed_handler, guessed_runtime = guess_handler_and_runtime(source)
    handler = handler or guessed_handler
    runtime = runtime or guessed_runtime
    code = build_zip(source)
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

    if _exists(lam, name):
        lam.update_function_code(FunctionName=name, ZipFile=code)
        _wait(lam, "function_updated_v2", name)
        if role:
            config["Role"] = role
        if config:
            lam.update_function_configuration(FunctionName=name, **config)
            _wait(lam, "function_updated_v2", name)
        ui.success(f"updated {name} ({ui.human_size(len(code))})")
        return

    if not handler or not runtime:
        raise click.UsageError("couldn't guess the handler/runtime; pass --handler and --runtime")
    config["Role"] = role or ensure_role(client("iam", c.port))
    lam.create_function(FunctionName=name, Code={"ZipFile": code}, **config)
    _wait(lam, "function_active_v2", name)
    ui.success(f"created {name}: {runtime}, handler {handler} ({ui.human_size(len(code))})")
    ui.echo(f"Try: awsemu lambda invoke {name} '{{}}'", "muted")


@lambda_.command(name="invoke")
@click.argument("name")
@click.argument("payload", required=False)
@click.option("--file", "file_", type=click.File("r"), help="Payload from a file ('-' = stdin).")
@click.option("--async", "is_async", is_flag=True, help="Event invocation (don't wait for the result).")
@click.option("--logs/--no-logs", "show_logs", default=True, show_default=True,
              help="Show the log tail returned by Lambda.")
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
        raise SystemExit(1 if error else 0)

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
        raise SystemExit(1)
    ui.echo(f"HTTP {resp.get('StatusCode')} in {elapsed:.2f}s"
            + (f", version {resp['ExecutedVersion']}" if resp.get("ExecutedVersion") else ""), "muted")


@lambda_.command(name="logs")
@click.argument("name")
@click.option("-f", "--follow", is_flag=True)
@click.option("--since", type=int, default=60, show_default=True, metavar="MINUTES")
@pass_ctx
@handle_errors
def logs_cmd(c: Ctx, name: str, follow: bool, since: int):
    """Show the function's CloudWatch logs (/aws/lambda/NAME)."""
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
            except Exception as exc:
                if "ResourceNotFound" not in type(exc).__name__:
                    raise
                if not follow:
                    ui.echo(f"No logs yet ({group} doesn't exist).", "muted")
                    return
            if not follow:
                return
            time.sleep(2)
    except KeyboardInterrupt:
        pass


@lambda_.command(name="info")
@click.argument("name")
@pass_ctx
@handle_errors
def info(c: Ctx, name: str):
    """Show a function's configuration."""
    cfg = client("lambda", c.port).get_function(FunctionName=name)["Configuration"]
    env = cfg.get("Environment", {}).get("Variables", {})
    ui.kv([("arn", cfg.get("FunctionArn")), ("runtime", cfg.get("Runtime")),
           ("handler", cfg.get("Handler")), ("role", cfg.get("Role")),
           ("memory", f"{cfg.get('MemorySize')} MB"), ("timeout", f"{cfg.get('Timeout')} s"),
           ("state", cfg.get("State")), ("code size", ui.human_size(cfg.get("CodeSize"))),
           ("modified", cfg.get("LastModified")),
           ("env", ", ".join(f"{k}={v}" for k, v in env.items()))], title=name)


@lambda_.command(name="rm")
@click.argument("name")
@click.option("-y", "--yes", is_flag=True)
@pass_ctx
@handle_errors
def rm(c: Ctx, name: str, yes: bool):
    """Delete a function."""
    if not yes:
        click.confirm(f"Delete function {name}?", abort=True)
    client("lambda", c.port).delete_function(FunctionName=name)
    ui.success(f"deleted {name}")
