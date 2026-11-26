"""The proxy's shadow mode: the same read-only calls to a real AWS account, compared.

Your code always gets the emulator's answer. In the background, each call that is a
configuration read (:func:`awsemu.realaccount.allowed`, data reads excluded) is signed
again with a profile you name and sent to AWS; the two answers are compared on what
matters for fidelity: the HTTP status, the error code, and the response's shape (the
fields present, not their values). Only that comparison is written, to
``shadow.jsonl`` next to the calls log: never AWS's response bodies.

Care for the account: it needs ``--shadow PROFILE``; it never sends a write; data reads
(``GetItem``, ``GetObject``, ``GetSecretValue``…) aren't sent; it stops after
``--shadow-max`` calls (default 500); and every call it sends is an ordinary request on
your AWS bill (most reads are free or a fraction of a cent).
"""

from __future__ import annotations

import datetime as dt
import json
import queue
import re
import threading
from dataclasses import dataclass
from pathlib import Path

from . import awscalls, realaccount

DROP = {
    "authorization",
    "x-amz-date",
    "x-amz-security-token",
    "x-amz-content-sha256",
    "host",
    "content-length",
    "amz-sdk-invocation-id",
    "amz-sdk-request",
    "expect",
    "connection",
    "accept-encoding",
    "transfer-encoding",
    "x-amz-user-agent",
    "user-agent",
}
XML_TAG_RE = re.compile(rb"<([A-Za-z_][\w.-]*)[\s>/]")
DEFAULT_MAX = 500


def shape(data: bytes, content_type: str = "") -> set[str]:
    """The field paths of a JSON or XML body (lists collapsed): what's there, not the values."""
    text = data.strip()
    if not text:
        return set()
    if text[:1] in (b"{", b"["):
        try:
            value = json.loads(text)
        except ValueError:
            return set()
        out: set[str] = set()

        def walk(v, path):
            if isinstance(v, dict):
                for k, x in v.items():
                    p = f"{path}.{k}" if path else k
                    out.add(p)
                    walk(x, p)
            elif isinstance(v, list):
                for x in v:
                    walk(x, path + "[]")

        walk(value, "")
        return out
    if text[:1] == b"<":
        return {m.decode() for m in XML_TAG_RE.findall(text)} - {"?xml"}
    return set()


def compare(emu: tuple[int, dict, bytes], aws: tuple[int, dict, bytes]) -> dict:
    (es, eh, eb), (as_, ah, ab) = emu, aws
    e_err, a_err = awscalls.error_code(es, eh, eb), awscalls.error_code(as_, ah, ab)
    out = {
        "emulator": {"status": es, "error": e_err},
        "aws": {"status": as_, "error": a_err},
        "same_status": es == as_,
        "same_error": e_err == a_err,
    }
    if es < 300 and as_ < 300:
        e_shape, a_shape = shape(eb), shape(ab)
        out["missing_in_emulator"] = sorted(a_shape - e_shape)[:50]
        out["extra_in_emulator"] = sorted(e_shape - a_shape)[:50]
    out["differs"] = (
        not out["same_status"]
        or not out["same_error"]
        or bool(out.get("missing_in_emulator"))
        or bool(out.get("extra_in_emulator"))
    )
    return out


@dataclass
class Job:
    call: dict
    method: str
    path: str
    headers: list[tuple[str, str]]
    body: bytes
    emulator: tuple[int, dict, bytes]


class Shadow:
    """Sends eligible calls to AWS in a background thread and logs the comparisons."""

    def __init__(
        self,
        profile: str,
        region: str | None,
        log: Path,
        max_calls: int = DEFAULT_MAX,
        endpoint_for=None,
        verify=True,
        session=None,
    ):
        self.session = session or realaccount.session(profile, region)
        self.region = self.session.region_name
        self.log = log
        self.max_calls = max_calls
        self.sent = 0
        self.skipped = 0
        self._endpoint_for = endpoint_for
        self._verify = verify
        self._endpoints: dict[str, str] = {}
        self._queue: queue.Queue[Job | None] = queue.Queue(maxsize=1000)
        self._lock = threading.Lock()
        self._thread = threading.Thread(target=self._work, name="awsemu-shadow", daemon=True)
        self._thread.start()

    def account(self) -> dict:
        return realaccount.client(self.session, "sts").get_caller_identity()

    def offer(self, call: dict, method: str, path: str, headers, body: bytes, emulator) -> bool:
        """Queue a call if it may be sent (a configuration read, under the limit)."""
        op = call.get("operation") or ""
        # GetParameter(s) pass the read-only guard without decryption; here the body isn't
        # parsed, so they're treated as the data reads they can be.
        if not call.get("service") or not realaccount.allowed(op, {"WithDecryption": True}) or call.get("fault"):
            self.skipped += 1
            return False
        with self._lock:
            if self.sent >= self.max_calls:
                self.skipped += 1
                return False
            self.sent += 1
        try:
            self._queue.put_nowait(Job(call, method, path, list(headers), body, emulator))
        except queue.Full:
            self.skipped += 1
            return False
        return True

    def close(self, timeout: float = 10) -> None:
        self._queue.put(None)
        self._thread.join(timeout)

    # -- the worker

    def _endpoint(self, service: str) -> str:
        if self._endpoint_for:
            return self._endpoint_for(service)
        if service not in self._endpoints:
            self._endpoints[service] = realaccount.client(self.session, service).meta.endpoint_url
        return self._endpoints[service]

    def send(self, job: Job) -> tuple[int, dict, bytes]:
        from botocore.auth import S3SigV4Auth, SigV4Auth
        from botocore.awsrequest import AWSRequest
        from botocore.httpsession import URLLib3Session

        service = job.call["service"]
        model = self.session._session.get_service_model(service)
        signing = model.signing_name or model.endpoint_prefix
        headers = {k: v for k, v in job.headers if k.lower() not in DROP}
        request = AWSRequest(
            method=job.method,
            url=self._endpoint(service).rstrip("/") + job.path,
            data=job.body or None,
            headers=headers,
        )
        creds = self.session.get_credentials().get_frozen_credentials()
        (S3SigV4Auth if service == "s3" else SigV4Auth)(creds, signing, self.region).add_auth(request)
        resp = URLLib3Session(verify=self._verify, timeout=30).send(request.prepare())
        return resp.status_code, {k.lower(): v for k, v in resp.headers.items()}, resp.content

    def _work(self) -> None:
        while True:
            job = self._queue.get()
            if job is None:
                return
            entry = {
                "id": job.call.get("id"),
                "time": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
                "service": job.call.get("service"),
                "operation": job.call.get("operation"),
                "resource": job.call.get("resource"),
            }
            try:
                entry.update(compare(job.emulator, self.send(job)))
            except Exception as exc:
                entry.update({"differs": None, "failed": f"{type(exc).__name__}: {str(exc)[:200]}"})
            try:
                with self.log.open("a", encoding="utf-8") as fh:
                    fh.write(json.dumps(entry) + "\n")
            except OSError:  # pragma: no cover
                pass
