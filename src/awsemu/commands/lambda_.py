"""``awsemu lambda``: deploy, invoke and inspect functions."""

from __future__ import annotations

import base64
import hashlib
import io
import json
import shutil
import subprocess
import sys
import time
import zipfile
from datetime import datetime
from pathlib import Path

import click

from .. import exitcodes
from .. import ui
from ..clients import client
from ..completion import complete
from ..context import Ctx, handle_errors, json_option, pass_ctx, yes_option
from ..paths import cli_root
from ._common import client_error, ensure_service_role, is_error, parse_kv

DEFAULT_ROLE_NAME = "awsemu-lambda-role"
SKIP_DIRS = {"__pycache__", ".git", ".venv", "venv", "node_modules/.cache", ".pytest_cache", ".mypy_cache"}
SKIP_SUFFIXES = (".pyc", ".pyo")

# Guess the runtime from the handler file when --runtime isn't given.
RUNTIME_BY_SUFFIX = {".py": "python3.12", ".js": "nodejs20.x", ".mjs": "nodejs20.x"}


# --------------------------------------------------------------------------- packaging


def _skip(rel: Path) -> bool:
    return any(part in SKIP_DIRS for part in rel.parts) or rel.suffix in SKIP_SUFFIXES


def _add(zf: zipfile.ZipFile, path: Path, name: str) -> None:
    # A fixed date: the same files always give the same zip, so CodeSha256 tells
    # whether the code changed (seeds don't redeploy unchanged functions).
    info = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
    info.external_attr = (path.stat().st_mode & 0o777 | 0o100000) << 16
    info.compress_type = zipfile.ZIP_DEFLATED
    zf.writestr(info, path.read_bytes())


def _files(folder: Path) -> list[tuple[Path, str]]:
    """The files to package from a folder, as (path, name in the zip), sorted."""
    out = []
    for path in sorted(p for p in folder.rglob("*") if p.is_file()):
        rel = path.relative_to(folder)
        if not _skip(rel):
            out.append((path, rel.as_posix()))
    return out


def build_zip(source: Path, dependencies: Path | None = None) -> bytes:
    """Zip a folder (contents at the zip root), a single file, or pass a .zip through.

    ``dependencies`` is a folder of installed packages added at the zip root too
    (your own files win over a package's file with the same name).
    The zip is reproducible: same files, same bytes."""
    if source.is_file() and source.suffix == ".zip":
        return source.read_bytes()
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        own = [(source, source.name)] if source.is_file() else _files(source)
        names = {name for _, name in own}
        extra = [(p, n) for p, n in _files(dependencies) if n not in names] if dependencies else []
        for path, name in sorted(own + extra, key=lambda item: item[1]):
            _add(zf, path, name)
    data = buf.getvalue()
    if len(zipfile.ZipFile(io.BytesIO(data)).namelist()) == 0:
        raise click.BadParameter(f"nothing to package in {source}")
    return data


def requirements_file(source: Path) -> Path | None:
    req = source / "requirements.txt" if source.is_dir() else None
    return req if req and req.is_file() else None


def _pip() -> list[str]:
    probe = subprocess.run([sys.executable, "-m", "pip", "--version"], capture_output=True)
    if probe.returncode == 0:
        return [sys.executable, "-m", "pip"]
    found = shutil.which("pip3") or shutil.which("pip")
    if not found:
        raise click.ClickException(
            "requirements.txt needs pip, and there's none (install it, or pass --no-deps and package them yourself)"
        )
    return [found]


def python_dependencies(source: Path, runtime: str | None) -> Path | None:
    """Install requirements.txt once into a cache folder and return it (None without one).

    The folder is keyed by the file's contents and the runtime, so it's reused until
    either changes; the packages are installed for this machine, which is where the
    emulator runs the function."""
    req = requirements_file(source)
    if req is None or (runtime and not runtime.startswith("python")):
        return None
    digest = hashlib.sha256(req.read_bytes() + (runtime or "").encode()).hexdigest()[:16]
    target = cli_root() / "lambda-deps" / digest
    if (target / ".awsemu-complete").exists():
        return target
    partial = target.with_name(digest + ".partial")
    shutil.rmtree(partial, ignore_errors=True)
    partial.mkdir(parents=True)
    ui.info(f"installing {req.name} for the function…")
    done = subprocess.run(
        [
            *_pip(),
            "install",
            "--quiet",
            "--disable-pip-version-check",
            "--no-compile",
            "-r",
            str(req),
            "-t",
            str(partial),
        ],
        capture_output=True,
        text=True,
    )
    if done.returncode != 0:
        shutil.rmtree(partial, ignore_errors=True)
        tail = "\n".join((done.stderr or done.stdout).strip().splitlines()[-5:])
        raise click.ClickException(f"pip couldn't install {req}:\n{tail}")
    shutil.rmtree(target, ignore_errors=True)
    partial.rename(target)
    (target / ".awsemu-complete").touch()
    return target


def package(source: Path, runtime: str | None, deps: bool = True) -> bytes:
    """The function's zip: the code plus, for Python, what requirements.txt asks for."""
    return build_zip(source, python_dependencies(source, runtime) if deps else None)


def fingerprint(source: Path) -> tuple:
    """What changes when a packaged file is saved, added or removed (cheap to poll)."""
    files = [(source, source.name)] if source.is_file() else _files(source)
    out = []
    for path, name in files:
        try:
            st = path.stat()
        except OSError:  # removed while listing
            continue
        out.append((name, st.st_mtime_ns, st.st_size))
    return tuple(out)


def guess_handler_and_runtime(source: Path) -> tuple[str | None, str | None]:
    """``app.py`` with ``def handler`` -> ``("app.handler", "python3.12")``."""
    if source.is_file() and source.suffix != ".zip":
        candidates = [source]
    elif source.is_dir():
        preferred = [
            source / n
            for n in ("lambda_function.py", "app.py", "handler.py", "main.py", "index.mjs", "index.js", "app.js")
        ]
        others = sorted(
            p for p in source.iterdir() if p.is_file() and p.suffix in RUNTIME_BY_SUFFIX and p not in preferred
        )
        candidates = preferred + others
    else:
        return None, None
    for path in candidates:
        if not path.is_file():
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        for fn in ("lambda_handler", "handler", "main"):
            if (path.suffix == ".py" and f"def {fn}(" in text) or (
                path.suffix in (".js", ".mjs")
                and (
                    f"exports.{fn}" in text
                    or f"export const {fn}" in text
                    or f"export async function {fn}" in text
                    or f"export function {fn}" in text
                )
            ):
                return f"{path.stem}.{fn}", RUNTIME_BY_SUFFIX.get(path.suffix)
    return None, None


def parse_env(pairs) -> dict[str, str]:
    return parse_kv(pairs, "--env")


def ensure_role(iam) -> str:
    return ensure_service_role(iam, DEFAULT_ROLE_NAME, "lambda.amazonaws.com", "Created by awsemu for Lambda functions")


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
        if is_error(exc, "ResourceNotFound"):
            return False
        raise


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

    code = package(source, runtime, deps)
    if _exists(lam, name):
        lam.update_function_code(FunctionName=name, ZipFile=code)
        _wait(lam, "function_updated_v2", name)
        if role:
            config["Role"] = role
        if config:
            lam.update_function_configuration(FunctionName=name, **config)
            _wait(lam, "function_updated_v2", name)
        ui.success(f"updated {name} ({ui.human_size(len(code))})")
    else:
        if not handler or not runtime:
            raise click.UsageError("couldn't guess the handler/runtime; pass --handler and --runtime")
        config["Role"] = role or ensure_role(client("iam", c.port))
        lam.create_function(FunctionName=name, Code={"ZipFile": code}, **config)
        _wait(lam, "function_active_v2", name)
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
                code = package(source, runtime, deps)
            except click.ClickException as exc:
                ui.error(f"{stamp} {exc.format_message()}")
                continue
            sha = hashlib.sha256(code).digest()
            if sha == last_sha:
                continue  # only a skipped file, or a save without changes
            try:
                lam.update_function_code(FunctionName=name, ZipFile=code)
                _wait(lam, "function_updated_v2", name)
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
