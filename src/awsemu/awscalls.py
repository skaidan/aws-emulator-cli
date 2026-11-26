"""Recognise an AWS API call from its HTTP request: service, operation, resource, error.

Used by the proxy. Everything comes from the service models of the installed botocore,
so it matches the SDK you have:

* the **service** from the SigV4 signing name (``Credential=…/us-east-1/states/aws4_request``),
  disambiguated by ``X-Amz-Target`` (``DynamoDBStreams_20120810.GetRecords``) or by
  which service's URIs match;
* the **operation** from ``X-Amz-Target`` (JSON), ``Action=`` (query/EC2), the
  ``/service/X/operation/Op`` path (Smithy RPC v2 CBOR), or the HTTP method and URI
  template of the operation (REST: S3, Lambda, API Gateway…);
* the **resource** from well-known parameters (``TableName``, ``QueueUrl``, ``Bucket``…);
* the **error code** from ``x-amzn-ErrorType``, a JSON ``__type`` or an XML ``<Code>``.

Building the signing-name tables reads every model once (about 2 s); they're cached on
disk per botocore version.
"""

from __future__ import annotations

import json
import re
import threading
from dataclasses import asdict, dataclass, field
from pathlib import Path
from urllib.parse import parse_qsl, unquote

from .paths import cli_root

CREDENTIAL_RE = re.compile(r"Credential=[^/,\s]+/\d{8}/[^/,\s]+/([^/,\s]+)/aws4_request")
QUERY_CREDENTIAL_RE = re.compile(r"^[^/]+/\d{8}/[^/]+/([^/]+)/aws4_request$")
CBOR_PATH_RE = re.compile(r"^/service/([^/]+)/operation/([^/?]+)")
XML_CODE_RE = re.compile(rb"<Code>([^<]{1,200})</Code>")

RESOURCE_KEYS = (
    "TableName",
    "QueueUrl",
    "QueueName",
    "TopicArn",
    "TargetArn",
    "StreamName",
    "StreamARN",
    "FunctionName",
    "StateMachineArn",
    "stateMachineArn",
    "executionArn",
    "SecretId",
    "Bucket",
    "LogGroupName",
    "logGroupName",
    "EventBusName",
    "Name",
    "KeyId",
    "RoleName",
    "UserName",
    "StackName",
    "ClusterName",
    "RestApiId",
    "ResourceArn",
    "resourceArn",
    "Arn",
    "name",
)
REST_XML = {"s3", "s3control", "route53", "cloudfront"}


@dataclass
class Call:
    """One API call that went through the proxy."""

    time: str  # ISO 8601, UTC
    service: str  # boto3 name: "dynamodb", "s3", "stepfunctions"…
    operation: str  # "PutItem"; "" if unknown
    resource: str  # "orders", "my-bucket/key.txt"; "" if none
    method: str
    path: str
    status: int
    error: str | None  # error code, e.g. "ConditionalCheckFailedException"
    latency_ms: float
    request_id: str | None = None
    fault: str | None = None  # the fault rule that changed this call, if any
    bytes_in: int = 0
    bytes_out: int = 0

    def as_dict(self) -> dict:
        return asdict(self)


@dataclass
class Identified:
    service: str = ""
    operation: str = ""
    resource: str = ""
    protocol: str = ""  # json | rest-json | rest-xml | query | ec2 | smithy-rpc-v2-cbor


# --------------------------------------------------------------------------- tables


@dataclass
class _Tables:
    signing: dict[str, list[str]] = field(default_factory=dict)  # signing name -> services
    target: dict[str, str] = field(default_factory=dict)  # X-Amz-Target prefix -> service
    protocol: dict[str, str] = field(default_factory=dict)  # service -> protocol


_tables: _Tables | None = None
_rest: dict[str, list[tuple]] = {}
_lock = threading.Lock()


def _loader():
    import botocore.session

    return botocore.session.get_session().get_component("data_loader")


def _cache_file() -> Path:
    import botocore

    return cli_root() / "proxy" / f"botocore-{botocore.__version__}.json"


def tables() -> _Tables:
    """Signing names, target prefixes and protocols of every service botocore knows."""
    global _tables
    with _lock:
        if _tables is not None:
            return _tables
        cache = _cache_file()
        try:
            data = json.loads(cache.read_text(encoding="utf-8"))
            _tables = _Tables(**data)
            return _tables
        except (OSError, ValueError, TypeError):
            pass
        loader = _loader()
        t = _Tables()
        for name in loader.list_available_services("service-2"):
            meta = loader.load_service_model(name, "service-2").get("metadata", {})
            signing = meta.get("signingName") or meta.get("endpointPrefix") or name
            t.signing.setdefault(signing, []).append(name)
            if meta.get("targetPrefix"):
                t.target.setdefault(meta["targetPrefix"], name)
            t.protocol[name] = meta.get("protocol", "")
        for signing, names in t.signing.items():  # the service named like its signing name first
            names.sort(key=lambda n: (n != signing, len(n), n))
        try:
            cache.parent.mkdir(parents=True, exist_ok=True)
            cache.write_text(json.dumps(asdict(t)), encoding="utf-8")
        except OSError:
            pass
        _tables = t
        return t


def _rest_ops(service: str) -> list[tuple]:
    """``(method, regex, requirements, specificity, operation)`` for each operation of a REST service.

    Requirements are ``(where, name, value)``: literal query parameters of the URI
    (``?uploads``, ``?list-type=2``) and required header/query members of the input
    (``x-amz-copy-source`` tells CopyObject from PutObject, ``uploadId`` UploadPart).
    """
    with _lock:
        if service in _rest:
            return _rest[service]
    model = _loader().load_service_model(service, "service-2")
    ops = []
    for name, op in model.get("operations", {}).items():
        http = op.get("http", {})
        uri = http.get("requestUri")
        if not uri:
            continue
        path, _, query = uri.partition("?")
        pattern, literal = "", 0
        for part in re.split(r"(\{[^}]+\})", path):
            if part.startswith("{"):
                label = part[1:-1]
                greedy = label.endswith("+")
                label = re.sub(r"\W", "_", label.rstrip("+"))
                pattern += f"(?P<{label}>.+)" if greedy else f"(?P<{label}>[^/]+)"
            else:
                pattern += re.escape(part)
                literal += len(part)
        pattern = "^" + pattern.rstrip("/") + "/?$"
        required = []
        for item in filter(None, query.split("&")):
            key, _, value = item.partition("=")
            required.append(("query", key, value or None))
        shape = model.get("shapes", {}).get(op.get("input", {}).get("shape", ""), {})
        for member_name in shape.get("required", []):
            member = shape.get("members", {}).get(member_name, {})
            where = {"header": "header", "querystring": "query"}.get(member.get("location", ""))
            if where:
                key = member.get("locationName", member_name)
                required.append((where, key.lower() if where == "header" else key, None))
        specificity = literal + 100 * len(required)
        ops.append((http.get("method", "GET"), re.compile(pattern), required, specificity, name))
    ops.sort(key=lambda o: -o[3])
    with _lock:
        _rest[service] = ops
    return ops


def _match_rest(
    service: str, method: str, path: str, query: dict[str, str], headers: dict[str, str]
) -> tuple[str, dict] | None:
    try:
        ops = _rest_ops(service)
    except Exception:  # no model for this service
        return None
    for op_method, regex, required, _, name in ops:
        if op_method != method:
            continue
        m = regex.match(path)
        if not m:
            continue
        if all(
            k in (query if where == "query" else headers) and (v is None or query.get(k) == v)
            for where, k, v in required
        ):
            return name, {k: unquote(v) for k, v in m.groupdict().items()}
    return None


# --------------------------------------------------------------------------- identify


def _short(value: str) -> str:
    value = str(value)
    if value.startswith("arn:"):
        rest = value.split(":", 5)[-1]
        return re.split(r"[:/]", rest)[-1] or rest
    if value.startswith(("http://", "https://")):  # QueueUrl
        return value.rstrip("/").rsplit("/", 1)[-1]
    return value


def _resource(params: dict) -> str:
    if "Bucket" in params and params.get("Key"):
        return f"{params['Bucket']}/{params['Key']}"
    for key in RESOURCE_KEYS:
        value = params.get(key)
        if isinstance(value, str) and value:
            return _short(value)[:200]
    return ""


def signing_name(headers: dict[str, str], query: dict[str, str]) -> str:
    m = CREDENTIAL_RE.search(headers.get("authorization", ""))
    if m:
        return m.group(1)
    m = QUERY_CREDENTIAL_RE.match(query.get("X-Amz-Credential", ""))  # presigned URL
    if m:
        return m.group(1)
    if "AWSAccessKeyId" in query and "Signature" in query:  # SigV2 presigned URL: only S3 uses it
        return "s3"
    return ""


def identify(method: str, raw_path: str, headers: dict[str, str], body: bytes) -> Identified:
    """What this request is. ``headers`` must have lower-case names."""
    path, _, qs = raw_path.partition("?")
    query = dict(parse_qsl(qs, keep_blank_values=True))
    t = tables()
    signing = signing_name(headers, query)
    candidates = t.signing.get(signing, [signing] if signing else [])
    found = Identified(service=candidates[0] if candidates else "")
    content_type = headers.get("content-type", "")

    target = headers.get("x-amz-target")
    if target and "." in target:
        prefix, _, op = target.rpartition(".")
        found.service = t.target.get(prefix, found.service)
        found.operation = op
        found.protocol = "json"
        if body and len(body) < 1_000_000:
            try:
                params = json.loads(body)
                if isinstance(params, dict):
                    found.resource = _resource(params)
            except ValueError:
                pass
        return found

    cbor = CBOR_PATH_RE.match(path)
    if cbor or headers.get("smithy-protocol") == "rpc-v2-cbor":
        found.protocol = "smithy-rpc-v2-cbor"
        if cbor:
            found.operation = cbor.group(2)
        return found

    form = {}
    if "x-www-form-urlencoded" in content_type and body and len(body) < 1_000_000:
        form = dict(parse_qsl(body.decode("utf-8", "replace"), keep_blank_values=True))
    action = form.get("Action") or query.get("Action")
    if action:
        found.operation = action
        found.protocol = "ec2" if found.service == "ec2" else "query"
        found.resource = _resource({**query, **form})
        return found

    for service in candidates or []:
        match = _match_rest(service, method, path, query, headers)
        if match:
            found.service, found.operation = service, match[0]
            found.resource = _resource(match[1])
            break
    found.protocol = t.protocol.get(found.service) or ("rest-xml" if found.service in REST_XML else "rest-json")
    if found.protocol not in ("rest-json", "rest-xml"):
        found.protocol = "rest-xml" if found.service in REST_XML else "rest-json"
    return found


def error_code(status: int, headers: dict[str, str], body: bytes) -> str | None:
    """The AWS error code of a response, if it's an error."""
    if status < 300:
        return None
    header = headers.get("x-amzn-errortype") or headers.get("x-amzn-query-error")
    if header:
        return header.split(":", 1)[0].split(";", 1)[0].rsplit("#", 1)[-1]
    if body and len(body) < 256_000:
        stripped = body.lstrip()
        if stripped[:1] == b"{":
            try:
                data = json.loads(body)
                code = data.get("__type") or data.get("code") or data.get("Code")
                if code:
                    return str(code).rsplit("#", 1)[-1].split(":", 1)[0]
            except ValueError:
                pass
        m = XML_CODE_RE.search(body)
        if m:
            return m.group(1).decode("utf-8", "replace")
    return f"HTTP{status}"


def request_id(headers: dict[str, str]) -> str | None:
    return headers.get("x-amzn-requestid") or headers.get("x-amz-request-id") or headers.get("x-amz-id-2")
