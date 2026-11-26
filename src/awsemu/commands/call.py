"""``awsemu call SERVICE OPERATION``: any API call, through boto3.

For the services without their own commands and for machines without the AWS
CLI (``awsemu aws`` needs it). The operation can be written the way the API
reference (``ListBuckets``), boto3 (``list_buckets``) or the AWS CLI
(``list-buckets``) writes it.
"""

from __future__ import annotations

import base64
import difflib
import json
import re
import sys
from functools import lru_cache
from pathlib import Path

import click
from click.shell_completion import CompletionItem

from .. import exitcodes
from .. import ui
from ..clients import client
from ..context import Ctx, handle_errors, pass_ctx

BINARY_PREVIEW = 64


@lru_cache(maxsize=1)
def _botocore():
    import botocore.session

    return botocore.session.get_session()


def services() -> list[str]:
    return sorted(_botocore().get_available_services())


@lru_cache(maxsize=16)
def _model(service: str):
    return _botocore().get_service_model(service)


def operations(service: str) -> list[str]:
    return sorted(_model(service).operation_names)


def _key(name: str) -> str:
    return re.sub(r"[^a-z0-9]", "", name.lower())


def resolve_service(name: str) -> str:
    known = services()
    if name in known:
        return name
    by_key = {_key(s): s for s in known}
    if _key(name) in by_key:
        return by_key[_key(name)]
    close = difflib.get_close_matches(name.lower(), known, n=3)
    raise click.BadParameter(
        f"no service '{name}'"
        + (f"; did you mean {', '.join(close)}?" if close else "")
        + " ('awsemu call' lists them)",
        param_hint="SERVICE",
    )


def resolve_operation(service: str, name: str) -> str:
    """``ListBuckets``, ``list_buckets`` or ``list-buckets`` -> ``ListBuckets``."""
    known = operations(service)
    by_key = {_key(op): op for op in known}
    if _key(name) in by_key:
        return by_key[_key(name)]
    close = difflib.get_close_matches(name, known, n=3) or [
        by_key[k] for k in difflib.get_close_matches(_key(name), list(by_key), n=3)
    ]
    raise click.BadParameter(
        f"{service} has no operation '{name}'"
        + (f"; did you mean {', '.join(close)}?" if close else "")
        + f" ('awsemu call {service}' lists them)",
        param_hint="OPERATION",
    )


def snake(operation: str) -> str:
    from botocore import xform_name

    return xform_name(operation)


def parse_params(text: str | None, pairs) -> dict:
    """``--params`` (JSON, ``@file.json`` or ``-`` for stdin) plus ``-p Key=value`` pairs.

    A pair's value is read as JSON when it parses (numbers, true, lists…) and as
    text otherwise; ``-p Key=@file`` reads the file's bytes (for bodies)."""
    params: dict = {}
    if text:
        if text == "-":
            text = sys.stdin.read()
        elif text.startswith("@"):
            text = Path(text[1:]).read_text(encoding="utf-8")
        try:
            params = json.loads(text)
        except json.JSONDecodeError as exc:
            raise click.BadParameter(f"not JSON: {exc}", param_hint="--params") from exc
        if not isinstance(params, dict):
            raise click.BadParameter("must be a JSON object", param_hint="--params")
    for pair in pairs:
        key, sep, value = pair.partition("=")
        if not sep or not key:
            raise click.BadParameter(f"'{pair}' is not Key=value", param_hint="-p")
        if value.startswith("@"):
            params[key] = Path(value[1:]).read_bytes()
            continue
        try:
            params[key] = json.loads(value)
        except json.JSONDecodeError:
            params[key] = value
    return params


def _readable(value, out: Path | None):
    """Streaming bodies and bytes made printable (or written to ``out``)."""
    if hasattr(value, "read"):
        value = value.read()
        if out is not None:
            out.write_bytes(value)
            return f"<{len(value)} bytes written to {out}>"
    if isinstance(value, bytes | bytearray):
        try:
            return value.decode("utf-8")
        except UnicodeDecodeError:
            preview = base64.b64encode(bytes(value[:BINARY_PREVIEW])).decode()
            return f"<{len(value)} bytes, base64 {preview}{'…' if len(value) > BINARY_PREVIEW else ''}; use --out FILE>"
    if isinstance(value, dict):
        return {k: _readable(v, out) for k, v in value.items()}
    if isinstance(value, list):
        return [_readable(v, out) for v in value]
    return value


def _merge(pages: list[dict]) -> dict:
    """Paginator pages into one response: lists joined, the rest from the last page."""
    merged: dict = {}
    for page in pages:
        for key, value in page.items():
            if isinstance(value, list) and isinstance(merged.get(key), list):
                merged[key] = merged[key] + value
            else:
                merged[key] = value
    return merged


def _complete_service(ctx, param, incomplete):
    try:
        return [CompletionItem(s) for s in services() if s.startswith(incomplete)]
    except Exception:
        return []


def _complete_operation(ctx, param, incomplete):
    try:
        service = resolve_service(ctx.params.get("service") or "")
        names = [snake(op).replace("_", "-") for op in operations(service)]
        return [CompletionItem(n) for n in names if n.startswith(incomplete)]
    except Exception:
        return []


@click.command(name="call")
@click.argument("service", required=False, shell_complete=_complete_service)
@click.argument("operation", required=False, shell_complete=_complete_operation)
@click.option("--params", "params_text", metavar="JSON", help="The request as JSON, '@file.json', or '-' for stdin.")
@click.option(
    "-p",
    "--param",
    "pairs",
    multiple=True,
    metavar="KEY=VALUE",
    help="One parameter (JSON values parsed, '@file' for bytes). Repeatable.",
)
@click.option("--paginate", is_flag=True, help="Follow every page and merge them.")
@click.option("--query", metavar="JMESPATH", help="Keep part of the response, like the AWS CLI's --query.")
@click.option(
    "--out",
    type=click.Path(dir_okay=False, path_type=Path),
    help="Write a streaming body (S3 GetObject…) to this file.",
)
@click.option("--metadata", is_flag=True, help="Keep ResponseMetadata in the output.")
@pass_ctx
@handle_errors
def call(c: Ctx, service, operation, params_text, pairs, paginate, query, out, metadata):
    """Call any operation of any service, and print the response as JSON.

    \b
      awsemu call s3 list-buckets
      awsemu call sqs SendMessage -p QueueUrl=https://… -p MessageBody=hi
      awsemu call dynamodb query --params @query.json --query 'Items[].id.S'
      awsemu call logs describe-log-groups --paginate
      awsemu call ssm                       # the operations of a service
      awsemu call                           # the services

    An error from the service exits with 1 and prints its code and message.
    """
    if service is None:
        for name in services():
            click.echo(name)
        return
    service = resolve_service(service)
    if operation is None:
        for op in operations(service):
            click.echo(f"{snake(op).replace('_', '-'):45} {op}")
        return
    op = resolve_operation(service, operation)
    params = parse_params(params_text, pairs)
    api = client(service, c.port)
    method = snake(op)

    from botocore.exceptions import ParamValidationError

    try:
        if paginate:
            if not api.can_paginate(method):
                raise click.UsageError(f"{service} {op} has no pages; drop --paginate")
            resp = _merge(list(api.get_paginator(method).paginate(**params)))
        else:
            resp = getattr(api, method)(**params)
    except ParamValidationError as exc:
        uid = _model(service).metadata.get("uid", service)
        ui.error(
            str(exc).replace("\n", " ").strip(),
            f"see the parameters: https://docs.aws.amazon.com/goto/boto3/{uid}/{op}",
        )
        raise SystemExit(exitcodes.USAGE) from exc

    if not metadata:
        resp = {k: v for k, v in resp.items() if k != "ResponseMetadata"}
    resp = _readable(resp, out)
    if query:
        import jmespath

        try:
            resp = jmespath.search(query, resp)
        except jmespath.exceptions.JMESPathError as exc:
            raise click.BadParameter(str(exc), param_hint="--query") from exc
    if isinstance(resp, str):
        click.echo(resp)
    else:
        ui.print_json(resp)
