"""Fault injection rules for the proxy, and AWS-shaped error responses.

A rule is written ``TARGET=EFFECT[,EFFECT]...[@RATE][xTIMES][for DURATION]``::

    dynamodb=throttle@10%              # 10% of DynamoDB calls are throttled
    s3=latency:500ms                   # every S3 call waits 500 ms more
    s3:GetObject=503@50%               # half the GetObject calls get a 503
    sqs:Send*=reset@5%                 # 5% of SendMessage/SendMessageBatch lose the connection
    lambda:Invoke=latency:2s,TooManyRequestsException@20%x3   # at most 3 times
    *=InternalFailure:500@1%           # 1% of everything fails
    dynamodb:PutItem[orders]=throttle  # only on the table "orders"
    s3[uploads-*]=503 for 30s          # an outage of 30 s on those buckets, then it recovers

TARGET is ``service``, ``service:Operation``, and optionally ``[resource]`` (boto3 service
names; ``*`` and ``?`` globs; service and operation case-insensitive). The resource is the
table, queue, bucket, function… the call names (an S3 rule's resource matches the bucket
or ``bucket/key``). EFFECTs:

* ``latency:500ms`` / ``latency:2s`` (or just ``500ms``): wait before forwarding the call;
* ``throttle``: the throttling error that service's SDKs retry (``ThrottlingException``,
  ``Throttling`` for query APIs, ``SlowDown`` for S3, ``TooManyRequestsException`` for Lambda);
* an error code, optionally with its HTTP status: ``ThrottlingException``, ``InternalFailure:500``;
* an HTTP status: ``500``, ``503`` (with a matching code);
* ``reset``: close the connection without answering.

RATE is a percentage (``10%``) or a fraction (``0.1``); default 100%. ``xTIMES`` stops the
rule after it has fired that many times; ``for 30s`` (``ms``, ``s``, ``m``) after that long,
counted from when the rule is added.

Errors are written in the protocol of the API (JSON, REST-JSON, query, EC2, REST-XML,
Smithy RPC v2 CBOR) so the SDK parses them as the real error, retries included.
"""

from __future__ import annotations

import fnmatch
import json
import random
import re
import threading
import time
import uuid
from dataclasses import asdict, dataclass
from . import errors

STATUS_BY_CODE = {
    "SlowDown": 503,
    "ServiceUnavailable": 503,
    "ServiceUnavailableException": 503,
    "RequestLimitExceeded": 503,
    "InternalError": 500,
    "InternalFailure": 500,
    "InternalServerError": 500,
    "InternalServerException": 500,
    "InternalServiceError": 500,
    "TooManyRequestsException": 429,
    "RequestTimeout": 400,
}
CODE_BY_STATUS = {
    400: "BadRequest",
    403: "AccessDenied",
    404: "NotFound",
    408: "RequestTimeout",
    429: "TooManyRequestsException",
    500: "InternalFailure",
    502: "BadGateway",
    503: "ServiceUnavailable",
    504: "GatewayTimeout",
}
REST_XML_CODE_BY_STATUS = {500: "InternalError", 503: "SlowDown"}

RULE_RE = re.compile(r"^(?P<target>[^=]+)=(?P<effects>.+?)(?P<mods>(?:@[0-9.]+%?|x\d+|for\d+(?:\.\d+)?(?:ms|s|m))*)$")
MOD_RE = re.compile(r"@(?P<rate>[0-9.]+%?)|x(?P<times>\d+)|for(?P<for>\d+(?:\.\d+)?)(?P<unit>ms|s|m)")
TARGET_RE = re.compile(r"^(?P<service>[^:\[\]]*)(?::(?P<operation>[^\[\]]*))?(?:\[(?P<resource>[^\]]+)\])?$")
DURATION_RE = re.compile(r"^(?:latency:|delay:)?(?P<n>\d+(?:\.\d+)?)(?P<unit>ms|s)$")
CODE_RE = re.compile(r"^[A-Za-z][A-Za-z0-9.]*$")


class FaultError(errors.UsageError, ValueError):
    pass


@dataclass
class Fault:
    service: str = "*"
    operation: str = "*"
    resource: str = "*"
    latency_ms: int = 0
    error: str | None = None  # error code, or "throttle"
    status: int | None = None
    reset: bool = False
    rate: float = 1.0
    times: int | None = None
    hits: int = 0
    spec: str = ""
    duration_s: float | None = None  # "for 30s"
    added_at: float = 0.0  # time.time() when parsed (the window starts then)

    def matches(self, service: str, operation: str, resource: str = "") -> bool:
        if not (
            fnmatch.fnmatch((service or "").lower(), self.service.lower())
            and fnmatch.fnmatch((operation or "").lower(), self.operation.lower())
        ):
            return False
        if self.resource == "*":
            return True
        resource = resource or ""
        return fnmatch.fnmatchcase(resource, self.resource) or fnmatch.fnmatchcase(
            resource.split("/", 1)[0], self.resource
        )  # S3: the bucket

    def remaining_s(self, now: float | None = None) -> float | None:
        if self.duration_s is None:
            return None
        return max(0.0, self.added_at + self.duration_s - (time.time() if now is None else now))

    @property
    def expired(self) -> bool:
        return self.duration_s is not None and self.remaining_s() == 0

    @property
    def exhausted(self) -> bool:
        return (self.times is not None and self.hits >= self.times) or self.expired

    def as_dict(self) -> dict:
        data = asdict(self)
        remaining = self.remaining_s()
        data["remaining_s"] = None if remaining is None else round(remaining, 1)
        data["active"] = not self.exhausted
        return data


def parse(spec: str) -> Fault:
    """A rule from its text form (see the module docs)."""
    text = spec.strip()
    m = RULE_RE.match(text.replace(" ", ""))
    if not m:
        raise FaultError(
            f"'{spec}' isn't a fault rule; expected TARGET=EFFECT[@RATE], "
            "like dynamodb=throttle@10% or s3=latency:500ms"
        )
    t = TARGET_RE.match(m.group("target"))
    if not t:
        raise FaultError(
            f"'{m.group('target')}' in '{spec}' isn't a target: use service, "
            "service:Operation or service:Operation[resource]"
        )
    fault = Fault(
        service=t.group("service") or "*",
        operation=t.group("operation") or "*",
        resource=t.group("resource") or "*",
        spec=text,
        added_at=time.time(),
    )
    for effect in m.group("effects").split(","):
        if not effect:
            continue
        d = DURATION_RE.match(effect)
        if d:
            n = float(d.group("n"))
            fault.latency_ms += int(n * 1000 if d.group("unit") == "s" else n)
        elif effect == "reset":
            fault.reset = True
        elif effect.isdigit():
            status = int(effect)
            if not 400 <= status <= 599:
                raise FaultError(f"'{effect}' in '{spec}': an injected status must be 400-599")
            fault.status = status
        elif effect == "throttle":
            fault.error = "throttle"
        else:
            code, _, status_text = effect.partition(":")
            if not CODE_RE.match(code) or (status_text and not status_text.isdigit()):
                raise FaultError(
                    f"'{effect}' in '{spec}' isn't an effect: use latency:500ms, "
                    "throttle, reset, a status like 503, or an error code like "
                    "ThrottlingException[:400]"
                )
            fault.error = code
            if status_text:
                fault.status = int(status_text)
    if not (fault.latency_ms or fault.error or fault.status or fault.reset):
        raise FaultError(f"'{spec}' has no effect")
    for mod in MOD_RE.finditer(m.group("mods")):
        if mod.group("rate"):
            raw = mod.group("rate")
            rate = float(raw[:-1]) / 100 if raw.endswith("%") else float(raw)
            if not 0 < rate <= 1:
                raise FaultError(f"rate in '{spec}' must be between 0% and 100%")
            fault.rate = rate
        elif mod.group("times"):
            fault.times = int(mod.group("times"))
        else:
            n = float(mod.group("for"))
            fault.duration_s = n / 1000 if mod.group("unit") == "ms" else n * 60 if mod.group("unit") == "m" else n
            if fault.duration_s <= 0:
                raise FaultError(f"'for' in '{spec}' must be longer than 0")
    return fault


@dataclass
class Decision:
    """What the proxy does to one call."""

    latency_ms: int = 0
    error: Fault | None = None  # the rule that answers with an error or reset
    rules: tuple[str, ...] = ()

    @property
    def label(self) -> str | None:
        return " + ".join(self.rules) or None


class FaultSet:
    """Thread-safe list of rules. Each matching rule rolls its own dice."""

    def __init__(self, rules: list[Fault] | None = None, rng: random.Random | None = None):
        self._rules = list(rules or [])
        self._lock = threading.Lock()
        self._rng = rng or random.Random()

    def add(self, *rules: Fault) -> None:
        with self._lock:
            self._rules.extend(rules)

    def replace(self, rules: list[Fault]) -> None:
        with self._lock:
            self._rules = list(rules)

    def clear(self) -> None:
        self.replace([])

    def rules(self) -> list[Fault]:
        with self._lock:
            return list(self._rules)

    def decide(self, service: str, operation: str, resource: str = "") -> Decision:
        decision = Decision()
        fired = []
        with self._lock:
            for rule in self._rules:
                if rule.exhausted or not rule.matches(service, operation, resource):
                    continue
                if rule.rate < 1 and self._rng.random() >= rule.rate:
                    continue
                if (rule.error or rule.status or rule.reset) and decision.error:
                    continue  # one error per call: the first rule wins
                rule.hits += 1
                fired.append(rule.spec)
                decision.latency_ms += rule.latency_ms
                if rule.error or rule.status or rule.reset:
                    decision.error = rule
        decision.rules = tuple(fired)
        return decision


# --------------------------------------------------------------------------- responses


def _throttle(service: str, protocol: str) -> tuple[str, int]:
    if protocol == "rest-xml":
        return "SlowDown", 503
    if service == "lambda" or protocol == "rest-json":
        return "TooManyRequestsException", 429
    if protocol in ("query", "ec2"):
        return ("RequestLimitExceeded", 503) if protocol == "ec2" else ("Throttling", 400)
    return "ThrottlingException", 400


def code_and_status(fault: Fault, service: str, protocol: str) -> tuple[str, int]:
    if fault.error == "throttle":
        code, status = _throttle(service, protocol)
        return code, fault.status or status
    if fault.error:
        return fault.error, fault.status or STATUS_BY_CODE.get(fault.error, 400)
    status = fault.status or 500
    if protocol == "rest-xml" and status in REST_XML_CODE_BY_STATUS:
        return REST_XML_CODE_BY_STATUS[status], status
    return CODE_BY_STATUS.get(status, f"HTTP{status}"), status


def _cbor_text(s: str) -> bytes:
    data = s.encode("utf-8")
    n = len(data)
    if n < 24:
        head = bytes([0x60 + n])
    elif n < 256:
        head = bytes([0x78, n])
    else:
        head = bytes([0x79]) + n.to_bytes(2, "big")
    return head + data


def cbor_map(items: dict[str, str]) -> bytes:
    """A CBOR map of text to text (all the CBOR an error body needs)."""
    out = bytes([0xA0 + len(items)])
    for k, v in items.items():
        out += _cbor_text(k) + _cbor_text(v)
    return out


def error_response(
    code: str, status: int, protocol: str, message: str, request_content_type: str = ""
) -> tuple[int, dict[str, str], bytes]:
    """``(status, headers, body)`` of an AWS error in the given protocol."""
    rid = str(uuid.uuid4())
    headers = {"x-amzn-RequestId": rid}
    if protocol == "json":
        headers["Content-Type"] = request_content_type or "application/x-amz-json-1.1"
        headers["x-amzn-ErrorType"] = code
        body = json.dumps({"__type": code, "message": message}).encode()
    elif protocol == "smithy-rpc-v2-cbor":
        headers["Content-Type"] = "application/cbor"
        headers["smithy-protocol"] = "rpc-v2-cbor"
        body = cbor_map({"__type": code, "message": message})
    elif protocol in ("query", "ec2"):
        headers["Content-Type"] = "text/xml"
        side = "Receiver" if status >= 500 else "Sender"
        xml: str
        if protocol == "ec2":
            xml = (
                f'<?xml version="1.0" encoding="UTF-8"?><Response><Errors><Error><Code>{code}</Code>'
                f"<Message>{message}</Message></Error></Errors><RequestID>{rid}</RequestID></Response>"
            )
        else:
            xml = (
                f"<ErrorResponse><Error><Type>{side}</Type><Code>{code}</Code><Message>{message}</Message>"
                f"</Error><RequestId>{rid}</RequestId></ErrorResponse>"
            )
        body = xml.encode()
    elif protocol == "rest-xml":
        headers["Content-Type"] = "application/xml"
        headers["x-amz-request-id"] = rid
        body = (
            f'<?xml version="1.0" encoding="UTF-8"?><Error><Code>{code}</Code><Message>{message}'
            f"</Message><RequestId>{rid}</RequestId></Error>"
        ).encode()
    else:  # rest-json
        headers["Content-Type"] = "application/json"
        headers["x-amzn-ErrorType"] = code
        body = json.dumps({"message": message, "code": code}).encode()
    headers["Content-Length"] = str(len(body))
    return status, headers, body
