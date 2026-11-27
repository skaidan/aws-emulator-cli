"""AWS Lambda: functions."""

from __future__ import annotations

import io
import shutil
import subprocess
import sys
import zipfile
from collections.abc import Callable
import base64
import hashlib
import json
import os
from pathlib import Path

from .. import clients, errors
from ..awserrors import is_error
from ..paths import cli_root
from ..grants import ensure_service_role
from .. import seed as seedlib
from ..grants import arn

from . import COMPLETE_MAX, Service, names_snapshot, pages


# --------------------------------------------------------------------------- packaging


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
        raise errors.UsageError(f"nothing to package in {source}")
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
        raise errors.RuntimeErrorWithHint(
            "requirements.txt needs pip, and there's none (install it, or pass --no-deps and package them yourself)"
        )
    return [found]


def python_dependencies(source: Path, runtime: str | None, say: Callable[[str], None] | None = None) -> Path | None:
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
    if say:
        say(f"installing {req.name} for the function…")
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
        raise errors.RuntimeErrorWithHint(f"pip couldn't install {req}:\n{tail}")
    shutil.rmtree(target, ignore_errors=True)
    partial.rename(target)
    (target / ".awsemu-complete").touch()
    return target


def package(source: Path, runtime: str | None, deps: bool = True, say: Callable[[str], None] | None = None) -> bytes:
    """The function's zip: the code plus, for Python, what requirements.txt asks for."""
    return build_zip(source, python_dependencies(source, runtime, say) if deps else None)


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


def ensure_role(iam) -> str:
    return ensure_service_role(iam, DEFAULT_ROLE_NAME, "lambda.amazonaws.com", "Created by awsemu for Lambda functions")


def wait_function(lam, waiter_name: str, name: str) -> None:
    """Wait until the function is ready (no-op if this botocore lacks the waiter)."""
    try:
        waiter = lam.get_waiter(waiter_name)
    except ValueError:
        return
    waiter.wait(FunctionName=name, WaiterConfig={"Delay": 1, "MaxAttempts": 60})


def function_exists(lam, name: str) -> bool:
    try:
        lam.get_function(FunctionName=name)
        return True
    except Exception as exc:
        if is_error(exc, "ResourceNotFound"):
            return False
        raise


def functions(c) -> list[str]:
    return pages(c, "list_functions", "Functions", "FunctionName")


def details(port, name):
    return clients.client("lambda", port).get_function(FunctionName=name)["Configuration"]


def describe(a, port, full):
    return details(port, a.rest.split(":", 1)[0])


def _function_config(fn: dict, handler: str | None, runtime: str | None) -> dict:
    config: dict = {}
    if handler:
        config["Handler"] = handler
    if runtime:
        config["Runtime"] = runtime
    for key, field in (("timeout", "Timeout"), ("memory", "MemorySize"), ("description", "Description")):
        if key in fn:
            config[field] = fn[key]
    if "env" in fn:
        config["Environment"] = {"Variables": {k: str(v) for k, v in (fn["env"] or {}).items()}}
    return config


def _config_changes(current: dict, wanted: dict) -> dict:
    changed = {}
    for key, value in wanted.items():
        if key == "Environment":
            if (current.get("Environment") or {}).get("Variables", {}) != value["Variables"]:
                changed[key] = value
        elif current.get(key) != value:
            changed[key] = value
    return changed


TRIGGER_ACTIONS = {  # what Lambda needs to read each kind of source (AWS checks it; so does the emulator)
    "sqs": ["sqs:ReceiveMessage", "sqs:DeleteMessage", "sqs:GetQueueAttributes", "sqs:ChangeMessageVisibility"],
    "kinesis": [
        "kinesis:GetRecords",
        "kinesis:GetShardIterator",
        "kinesis:DescribeStream",
        "kinesis:DescribeStreamSummary",
        "kinesis:ListShards",
        "kinesis:ListStreams",
        "kinesis:SubscribeToShard",
    ],
}


def _allow_role_to_read(lam, iam, function: str, kind: str, source_arn: str, label: str) -> None:
    """Give the function's role the permissions to poll ``source_arn``."""
    role_arn = lam.get_function_configuration(FunctionName=function)["Role"]
    policy = {
        "Version": "2012-10-17",
        "Statement": [{"Effect": "Allow", "Action": TRIGGER_ACTIONS[kind], "Resource": source_arn}],
    }
    name = f"awsemu-trigger-{label.replace(':', '-')}"[:128]
    iam.put_role_policy(RoleName=role_arn.rsplit("/", 1)[-1], PolicyName=name, PolicyDocument=json.dumps(policy))


def _apply_triggers(fn: dict, lam, port: int) -> list[str]:
    """Event source mappings from SQS queues and Kinesis streams to the function."""
    wanted = fn.get("triggers") or []
    if not wanted:
        return []
    iam = clients.client("iam", port)
    current = {}
    for page in lam.get_paginator("list_event_source_mappings").paginate(FunctionName=fn["name"]):
        for m in page.get("EventSourceMappings", []):
            current[m["EventSourceArn"]] = m
    changes = []
    for tr in wanted:
        if "sqs" in tr:
            source = arn("sqs", tr["sqs"])
            label = f"sqs:{tr['sqs']}"
        else:
            source = arn("kinesis", f"stream/{tr['kinesis']}")
            label = f"kinesis:{tr['kinesis']}"
        enabled = tr.get("enabled", True)
        mapping = current.get(source)
        if mapping is None:
            _allow_role_to_read(lam, iam, fn["name"], "sqs" if "sqs" in tr else "kinesis", source, label)
            kwargs = {"EventSourceArn": source, "FunctionName": fn["name"], "Enabled": enabled}
            if "batch_size" in tr:
                kwargs["BatchSize"] = tr["batch_size"]
            if "kinesis" in tr:
                kwargs["StartingPosition"] = tr.get("starting_position", "TRIM_HORIZON")
            lam.create_event_source_mapping(**kwargs)
            changes.append(f"trigger {label}")
            continue
        update = {}
        if "batch_size" in tr and mapping.get("BatchSize") != tr["batch_size"]:
            update["BatchSize"] = tr["batch_size"]
        state = mapping.get("State", "Enabled")
        if enabled != (state in ("Enabled", "Enabling", "Creating", "Updating")):
            update["Enabled"] = enabled
        if update:
            lam.update_event_source_mapping(UUID=mapping["UUID"], **update)
            changes.append(f"trigger {label}")
    return changes


def apply(seed, port, report):
    lam = clients.client("lambda", port)
    for fn in seed.section("functions"):
        name = fn["name"]
        try:
            source = seed.base_dir / fn["code"]
            guessed_handler, guessed_runtime = guess_handler_and_runtime(source)
            handler = fn.get("handler") or guessed_handler
            runtime = fn.get("runtime") or guessed_runtime
            code = package(source, runtime, fn.get("deps", True), report.say)
            sha = base64.b64encode(hashlib.sha256(code).digest()).decode()
            exists = function_exists(lam, name)
            # An existing function keeps its handler/runtime unless the seed sets them
            wanted = _function_config(
                fn,
                fn.get("handler") or (None if exists else handler),
                fn.get("runtime") or (None if exists else runtime),
            )
            changes = []
            if exists:
                current = lam.get_function_configuration(FunctionName=name)
                if current.get("CodeSha256") != sha:
                    lam.update_function_code(FunctionName=name, ZipFile=code)
                    wait_function(lam, "function_updated_v2", name)
                    changes.append("code")
                diff = _config_changes(current, wanted)
                if diff:
                    lam.update_function_configuration(FunctionName=name, **diff)
                    wait_function(lam, "function_updated_v2", name)
                    changes += [k.lower() for k in diff]
                result = "updated" if changes else "unchanged"
            else:
                if not handler or not runtime:
                    report.add(
                        "function",
                        name,
                        "failed",
                        "couldn't guess the handler/runtime from the code; set 'handler' and 'runtime'",
                    )
                    continue
                lam.create_function(
                    FunctionName=name, Code={"ZipFile": code}, Role=ensure_role(clients.client("iam", port)), **wanted
                )
                wait_function(lam, "function_active_v2", name)
                result = "created"
            triggers = _apply_triggers(fn, lam, port)
            if triggers and result == "unchanged":
                result = "updated"
            detail = ", ".join(([f"{runtime} {handler}"] if result == "created" else changes) + triggers)
            report.add("function", name, result, detail)
        except Exception as exc:
            report.add("function", name, "failed", clients.describe_error(exc))


def _download_code(location: str, dest: Path, port: int) -> None:
    """Fetch a function's code zip from the URL Lambda returns (served by the emulator)."""
    import ssl
    import urllib.request

    from ..paths import InstanceFiles

    ctx = ssl.create_default_context(cafile=str(InstanceFiles(port).ca))
    with urllib.request.urlopen(location, context=ctx, timeout=60) as resp:  # the emulator's URL
        data = resp.read()
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(data)


def export(port: int, opts: seedlib.ExportOptions) -> list[dict]:
    lam = clients.client("lambda", port)
    functions = []
    for page in lam.get_paginator("list_functions").paginate():
        for f in page.get("Functions", []):
            name = f["FunctionName"]
            if opts.objects_dir is None:
                opts.notes.append(f"skipped function {name} (its code needs a place: use --objects-dir)")
                continue
            dest = opts.objects_dir / "functions" / f"{name}.zip"
            try:
                _download_code(lam.get_function(FunctionName=name)["Code"]["Location"], dest, port)
            except Exception as exc:
                opts.notes.append(f"skipped function {name}: couldn't download its code ({exc})")
                continue
            entry = {"name": name, "code": os.path.relpath(dest, opts.out_dir)}
            for key, field in (("handler", "Handler"), ("runtime", "Runtime")):
                if f.get(field):
                    entry[key] = f[field]
            if f.get("Timeout", 3) != 3:
                entry["timeout"] = f["Timeout"]
            if f.get("MemorySize", 128) != 128:
                entry["memory"] = f["MemorySize"]
            if f.get("Description"):
                entry["description"] = f["Description"]
            variables = (f.get("Environment") or {}).get("Variables")
            if variables:
                entry["env"] = variables
            triggers = []
            for mp in lam.get_paginator("list_event_source_mappings").paginate(FunctionName=name):
                for m in mp.get("EventSourceMappings", []):
                    source = m["EventSourceArn"]
                    if ":sqs:" in source:
                        tr = {"sqs": source.rsplit(":", 1)[-1]}
                        default_batch = 10
                    elif ":kinesis:" in source:
                        tr = {"kinesis": source.rsplit("/", 1)[-1]}
                        default_batch = 100
                        if m.get("StartingPosition", "TRIM_HORIZON") != "TRIM_HORIZON":
                            tr["starting_position"] = m["StartingPosition"]
                    else:
                        opts.notes.append(f"skipped trigger {source} of {name} (only SQS and Kinesis)")
                        continue
                    if m.get("BatchSize", default_batch) != default_batch:
                        tr["batch_size"] = m["BatchSize"]
                    if m.get("State") in ("Disabled", "Disabling"):
                        tr["enabled"] = False
                    triggers.append(tr)
            if triggers:
                entry["triggers"] = triggers
            functions.append(entry)
    return functions


def seed_import(sess, opts: seedlib.ImportOptions) -> list[dict]:
    """``functions`` of a real account (read-only), for ``awsemu seed import``."""
    opts.notes.append("functions aren't imported: their code isn't read from the account")
    return []


MEMORY_GB = 0.125  # what the cost estimate assumes


def cost(call) -> list[tuple[str, float]]:
    """Requests, plus duration from the proxy's latency (which errs high: it includes the emulator's)."""
    if call["operation"] not in ("Invoke", "InvokeWithResponseStream", "InvokeAsync"):
        return []
    return [("lambda.request", 1), ("lambda.gb_second", MEMORY_GB * float(call.get("latency_ms") or 0) / 1000)]


SERVICE = Service(
    name="lambda",
    label="Lambda functions",
    names=functions,
    details=details,
    describe=describe,
    watch=names_snapshot("function", functions),
    completions={"function": lambda c, i: pages(c, "list_functions", "Functions", "FunctionName", cap=COMPLETE_MAX)},
    seed_section="functions",
    apply=apply,
    export=export,
    seed_import=seed_import,
    cost=cost,
)
