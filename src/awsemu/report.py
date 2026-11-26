"""``awsemu report``: a draft issue for the emulator, from one call in the proxy's log.

It follows the emulator's "Behavior differs from AWS" issue form
(https://github.com/aws/aws-emulator/issues/new?template=behavior-differs.yml): what the
emulator answered, room for what AWS answers (with a link to the operation's
reference), how to reproduce it, the emulator version and the log around the call.

Everything comes from the calls log, where credentials are already masked; this
module drops the signing headers altogether. The draft never claims to know what AWS
answers: that part is for the person who files it.
"""

from __future__ import annotations

import datetime as dt
import json
from dataclasses import dataclass
from urllib.parse import urlencode

ISSUE_FORM = "https://github.com/aws/aws-emulator/issues/new"
TEMPLATE = "behavior-differs.yml"
MAX_URL = 7500  # GitHub refuses longer new-issue URLs
DROP_HEADERS = {
    "authorization",
    "x-amz-date",
    "x-amz-security-token",
    "x-amz-content-sha256",
    "host",
    "content-length",
    "accept-encoding",
    "amz-sdk-invocation-id",
    "amz-sdk-request",
    "connection",
    "expect",
    "x-amzn-requestid",
    "x-amz-request-id",
    "x-amz-id-2",
    "date",
    "server",
    "transfer-encoding",
    "cookie",
    "set-cookie",
}
EXPECTED_PLACEHOLDER = (
    "<!-- What AWS returns for the same request, and how you know: you ran it against AWS, "
    "or the reference says so. -->"
)


class ReportError(Exception):
    pass


@dataclass
class Draft:
    title: str
    fields: dict[str, str]  # issue form field id -> markdown

    def markdown(self) -> str:
        names = {
            "actual": "What happened",
            "expected": "What you expected",
            "reproduction": "Steps to reproduce",
            "version": "Emulator version",
            "impact": "Impact and workaround",
            "context": "Additional context",
        }
        parts = [f"# {self.title}", ""]
        for key, label in names.items():
            value = self.fields.get(key, "")
            if key == "version":
                value = f"```text\n{value}\n```"
            parts += [f"## {label}", "", value or "<!-- -->", ""]
        return "\n".join(parts)

    def url(self) -> str:
        """The emulator's new-issue form, filled in (fields that don't fit are left out)."""
        params = {"template": TEMPLATE, "title": self.title}
        for key in ("version", "actual", "reproduction", "expected", "context"):
            candidate = {**params, key: self.fields.get(key, "")}
            if len(f"{ISSUE_FORM}?{urlencode(candidate)}") <= MAX_URL:
                params = candidate
        return f"{ISSUE_FORM}?{urlencode(params)}"


def _model(service: str):
    try:
        import botocore.session

        return botocore.session.get_session().get_service_model(service)
    except Exception:  # an unknown service still gets a report
        return None


def reference_url(service: str, operation: str) -> str | None:
    model = _model(service)
    uid = model.metadata.get("uid") if model else None
    return f"https://docs.aws.amazon.com/goto/WebAPI/{uid}/{operation}" if uid and operation else None


def _kept(headers) -> list[tuple[str, str]]:
    return [(k, v) for k, v in headers or [] if k.lower() not in DROP_HEADERS and v != "***"]


def _body_text(body: dict | None) -> str | None:
    if not body:
        return None
    if "text" in body:
        text = body["text"]
        try:
            text = json.dumps(json.loads(text), indent=2)
        except ValueError:
            pass
        return text + ("\n… (truncated)" if body.get("truncated") else "")
    if "base64" in body:
        return f"<{body.get('size', 0)} bytes of binary data, base64 in the calls log>"
    return None


def _http(start: str, headers, body: dict | None) -> str:
    lines = [start, *(f"{k}: {v}" for k, v in _kept(headers))]
    text = _body_text(body)
    return "\n".join(lines) + (f"\n\n{text}" if text else "")


def _call_command(call: dict) -> str | None:
    """An ``awsemu call`` line that sends the same request, for JSON-protocol APIs."""
    model = _model(call["service"])
    body = (call.get("request") or {}).get("body") or {}
    if not model or model.metadata.get("protocol") != "json" or "text" not in body or body.get("truncated"):
        return None
    try:
        params = json.loads(body["text"] or "{}")
    except ValueError:
        return None
    if "***" in json.dumps(params):
        return None  # a masked value can't be replayed
    from botocore import xform_name

    return (
        f"awsemu call {call['service']} {xform_name(call['operation']).replace('_', '-')} "
        f"--params '{json.dumps(params)}'"
    )


def _when(text: str | None):
    if not text:
        return None
    try:
        when = dt.datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    return when if when.tzinfo else when.replace(tzinfo=dt.timezone.utc)


def log_around(call: dict, lines: list[str], seconds: float = 2.0, limit: int = 30) -> list[str]:
    """The emulator's log lines from shortly before to shortly after the call."""
    from . import logs

    at = _when(call.get("time"))
    if not at:
        return []
    out = []
    for line in lines:
        entry = logs.parse(line)
        when = _when(entry._first(logs._TIME_KEYS))  # the full timestamp, not the display one
        if when and abs((when - at).total_seconds()) <= seconds:
            out.append(line.rstrip("\n"))
    return out[-limit:]


def build(call: dict, earlier: list[dict], version: str | None, log_lines: list[str]) -> Draft:
    """The draft issue for ``call``. ``earlier``: the calls logged before it."""
    if call.get("fault"):
        raise ReportError(
            f"call {call['id']} got an error the proxy injected ({call['fault']}), "
            "not the emulator's answer: nothing to report"
        )
    service, operation = call.get("service") or "?", call.get("operation") or call["method"]
    outcome = call.get("error") or f"HTTP {call['status']}"
    title = f"{service} {operation}: {outcome} where AWS …"
    req, resp = call.get("request"), call.get("response")
    status = call["status"]

    actual = [
        f"`{service}` `{operation}`"
        + (f" on `{call['resource']}`" if call.get("resource") else "")
        + f" answered **{status}**"
        + (f" with `{call['error']}`" if call.get("error") else "")
        + "."
    ]
    if resp:
        actual += ["", "```http", _http(f"HTTP/1.1 {status}", resp.get("headers"), resp.get("body")), "```"]
    else:
        actual += ["", "<!-- The proxy didn't keep the body: start it with --bodies and run the call again. -->"]
    logs_near = log_around(call, log_lines)
    if logs_near:
        actual += ["", "Emulator log around the request:", "", "```text", *logs_near, "```"]

    ref = reference_url(service, operation)
    expected = [EXPECTED_PLACEHOLDER]
    if ref:
        expected += ["", f"Reference: {ref}"]

    repro = [
        "From a freshly started emulator (`aws-emulator`, default settings, Region us-east-1), "
        "through `AWS_ENDPOINT_URL`:",
        "",
    ]
    resource = call.get("resource")
    before = [
        c
        for c in earlier
        if resource
        and c.get("resource")
        and (c["resource"] == resource or c["resource"].split("/", 1)[0] == resource.split("/", 1)[0])
    ]
    if before:
        repro += ["Calls on the same resource before it:", ""]
        repro += [
            f"{i}. `{c['service']}` `{c['operation']}` → {c.get('error') or c['status']}"
            for i, c in enumerate(before[-10:], 1)
        ]
        repro += [""]
    command = _call_command(call) if req else None
    if command:
        repro += ["Then:", "", "```bash", command, "```", ""]
    if req:
        path = req.get("path") or call["path"]
        repro += [
            "The request:",
            "",
            "```http",
            _http(f"{call['method']} {path} HTTP/1.1", req.get("headers"), req.get("body")),
            "```",
        ]
    else:
        repro += [
            f"`{call['method']} {call['path']}`",
            "",
            "<!-- Start the proxy with --bodies to include the request. -->",
        ]
    agent = next((v for k, v in (req or {}).get("headers", []) if k.lower() == "user-agent"), None)
    if agent:
        repro += ["", f"Client: `{agent}`"]

    context = [
        f"Drafted by awsemu from call {call['id']} of the proxy's log, at {call['time']}"
        + (f", request ID `{call['request_id']}`" if call.get("request_id") else "")
        + ". Credentials and secret values were removed."
    ]
    return Draft(
        title=title,
        fields={
            "actual": "\n".join(actual),
            "expected": "\n".join(expected),
            "reproduction": "\n".join(repro),
            "version": version or "<!-- aws-emulator -v -->",
            "impact": "",
            "context": "\n".join(context),
        },
    )
