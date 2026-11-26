"""The proxy's calls as a HAR file (HTTP Archive 1.2), for a browser's developer tools.

Every call becomes an entry with its method, URL, status, timing and, if the proxy ran
with ``--bodies``, its headers and bodies (already masked). AWS's service, operation,
resource, error and fault go in a ``_awsemu`` field of each entry, which HAR viewers ignore.
"""

from __future__ import annotations

import base64
from http import HTTPStatus
from urllib.parse import parse_qsl, urlsplit

from . import __version__


def _headers(pairs) -> list[dict]:
    return [{"name": k, "value": v} for k, v in pairs or []]


def _find(pairs, name: str, default: str = "") -> str:
    return next((v for k, v in pairs or [] if k.lower() == name), default)


def entry(call: dict, base_url: str) -> dict:
    req = call.get("request") or {}
    resp = call.get("response") or {}
    path = req.get("path") or call["path"]
    url = base_url.rstrip("/") + path
    req_headers = req.get("headers") or []
    resp_headers = resp.get("headers") or []
    req_body = req.get("body") or {}
    resp_body = resp.get("body") or {}
    status = call["status"]
    try:
        status_text = HTTPStatus(status).phrase
    except ValueError:
        status_text = "Connection reset" if status == 0 else ""
    request = {
        "method": call["method"], "url": url, "httpVersion": "HTTP/1.1", "cookies": [],
        "headers": _headers(req_headers),
        "queryString": [{"name": k, "value": v} for k, v in parse_qsl(urlsplit(path).query, keep_blank_values=True)],
        "headersSize": -1, "bodySize": call.get("bytes_in", 0),
    }
    if req_body.get("text") is not None or req_body.get("base64") is not None or call.get("bytes_in"):
        request["postData"] = {"mimeType": _find(req_headers, "content-type", "application/octet-stream"),
                               "text": req_body.get("text") or _decoded(req_body)}
    content = {"size": call.get("bytes_out", 0), "mimeType": _find(resp_headers, "content-type", "")}
    if "text" in resp_body:
        content["text"] = resp_body["text"]
    elif "base64" in resp_body:
        content["text"], content["encoding"] = resp_body["base64"], "base64"
    latency = float(call.get("latency_ms") or 0)
    return {
        "startedDateTime": call["time"],
        "time": latency,
        "request": request,
        "response": {"status": status, "statusText": status_text, "httpVersion": "HTTP/1.1", "cookies": [],
                     "headers": _headers(resp_headers), "content": content, "redirectURL": "",
                     "headersSize": -1, "bodySize": call.get("bytes_out", 0)},
        "cache": {},
        "timings": {"send": 0, "wait": latency, "receive": 0},
        "comment": " ".join(filter(None, [call.get("service"), call.get("operation"), call.get("resource"),
                                          call.get("error"), call.get("fault") and f"fault: {call['fault']}"])),
        "_awsemu": {k: call.get(k) for k in ("id", "service", "operation", "resource", "error", "fault",
                                             "request_id")},
    }


def _decoded(body: dict) -> str:
    if "base64" in body:
        try:
            return base64.b64decode(body["base64"]).decode("utf-8", "replace")
        except ValueError:
            return ""
    return ""


def har(calls: list[dict], base_url: str) -> dict:
    return {"log": {"version": "1.2", "creator": {"name": "awsemu proxy", "version": __version__},
                    "pages": [], "entries": [entry(c, base_url) for c in calls]}}
