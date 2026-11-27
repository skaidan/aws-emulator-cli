"""``awsemu proxy``: a local HTTPS proxy in front of the emulator.

Your code talks to the proxy (``https://127.0.0.1:<proxy port>``, its own CA) and the
proxy talks to the emulator. On the way it

* records every call (service, operation, resource, status, error code, latency) in
  ``~/.aws/emulator-cli/proxy/<emulator port>/calls.jsonl`` and a ring buffer;
* applies fault rules (:mod:`awsemu.faults`): extra latency, AWS errors, resets.

The request goes upstream untouched, ``Host`` header included, so SigV4 signatures
stay valid and URLs the emulator builds from it (SQS queue URLs) point at the proxy.

A small admin API lives under ``/__awsemu/proxy/`` on the same port (``health``,
``faults``, ``calls``); ``awsemu proxy faults`` and the pytest fixtures use it. It needs
the token in the ``X-Awsemu-Token`` header (in the state file, readable only by you),
so other local processes, or the network with ``--host 0.0.0.0``, can't change the
faults or read the calls.
"""

from __future__ import annotations

import datetime as dt
import hmac
import http.client
import ipaddress
import json
import os
import secrets
import signal
import socket
import ssl
import struct
import sys
import threading
import time
from collections import deque
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qsl, urlsplit

from . import awscalls, errors, faults, redact, waiting
from .paths import DEFAULT_HOST, InstanceFiles, cli_root

ADMIN = "/__awsemu/proxy"
TOKEN_HEADER = "X-Awsemu-Token"
# Names containers use to reach the host (Docker Desktop, and Linux with host-gateway)
CONTAINER_HOST = "host.docker.internal"
HOP_BY_HOP = {
    "connection",
    "keep-alive",
    "proxy-authenticate",
    "proxy-authorization",
    "te",
    "trailer",
    "transfer-encoding",
    "upgrade",
    "expect",
}
MAX_LOG_BYTES = 20_000_000
RING = 5000
MAX_BODY = 64 * 1024  # per body, with --bodies


def body_record(data: bytes, content_type: str) -> dict:
    """A body for the log: text with secrets masked, or base64 when it isn't text."""
    import base64

    out: dict = {"size": len(data)}
    if not data:
        return out
    part = data[:MAX_BODY]
    if len(data) > MAX_BODY:
        out["truncated"] = True
    try:
        out["text"] = redact.text_body(part.decode("utf-8"), content_type)
    except UnicodeDecodeError:
        out["base64"] = base64.b64encode(part).decode()
    return out


def exchange(method: str, path: str, req_headers, req_body: bytes, status: int, resp_headers, resp_body: bytes) -> dict:
    """``request`` and ``response`` of one call, masked, for the calls log."""
    req_h = redact.headers(list(req_headers))
    resp_h = redact.headers(list(resp_headers))
    req_ct = next((v for k, v in req_h if k.lower() == "content-type"), "")
    resp_ct = next((v for k, v in resp_h if k.lower() == "content-type"), "")
    return {
        "request": {
            "method": method,
            "path": redact.url(path),
            "headers": req_h,
            "body": body_record(req_body, req_ct),
        },
        "response": {"status": status, "headers": resp_h, "body": body_record(resp_body, resp_ct)},
    }


class ProxyError(errors.AwsemuError):
    pass


# --------------------------------------------------------------------------- files


@dataclass(frozen=True)
class ProxyFiles:
    """Files of the proxy in front of the emulator on ``emulator_port``."""

    emulator_port: int

    @property
    def dir(self) -> Path:
        return cli_root() / "proxy" / str(self.emulator_port)

    @property
    def state(self) -> Path:
        return self.dir / "state.json"

    @property
    def calls(self) -> Path:
        return self.dir / "calls.jsonl"

    @property
    def log(self) -> Path:
        return self.dir / "proxy.log"

    @property
    def shadow(self) -> Path:
        return self.dir / "shadow.jsonl"

    @property
    def ca(self) -> Path:
        return cli_root() / "proxy" / "ca.pem"

    @property
    def ca_key(self) -> Path:
        return cli_root() / "proxy" / "ca-key.pem"

    @property
    def cert(self) -> Path:
        return cli_root() / "proxy" / "server.pem"

    @property
    def key(self) -> Path:
        return cli_root() / "proxy" / "server-key.pem"


def _san_entries(x509, names) -> list:
    out = []
    for name in names:
        try:
            out.append(x509.IPAddress(ipaddress.ip_address(name)))
        except ValueError:
            out.append(x509.DNSName(name))
    return out


BASE_NAMES = ("127.0.0.1", "::1", "localhost", CONTAINER_HOST)


def ensure_certs(files: ProxyFiles, extra_names: tuple[str, ...] = ()) -> None:
    """The proxy's CA and server certificate, made once.

    The server certificate is for 127.0.0.1, ::1, localhost and host.docker.internal
    (for containers), plus ``extra_names``. The CA stays the same across restarts, so
    ``AWS_CA_BUNDLE`` keeps working; the server certificate is renewed when it's about
    to expire or lacks a name.
    """
    try:
        from cryptography import x509
        from cryptography.hazmat.primitives import hashes, serialization
        from cryptography.hazmat.primitives.asymmetric import ec
        from cryptography.x509.oid import ExtendedKeyUsageOID, NameOID
    except ImportError as exc:  # pragma: no cover - cryptography is a dependency
        raise ProxyError("the proxy needs the 'cryptography' package for its certificate") from exc

    now = dt.datetime.now(dt.UTC)
    files.ca.parent.mkdir(parents=True, exist_ok=True)

    def write_key(path: Path, key) -> None:
        path.write_bytes(
            key.private_bytes(
                serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()
            )
        )
        try:
            path.chmod(0o600)
        except OSError:  # pragma: no cover
            pass

    if files.ca.exists() and files.ca_key.exists():
        ca_cert = x509.load_pem_x509_certificate(files.ca.read_bytes())
        loaded = serialization.load_pem_private_key(files.ca_key.read_bytes(), None)
        if not isinstance(loaded, ec.EllipticCurvePrivateKey):  # awsemu only ever writes EC keys
            raise ProxyError(f"{files.ca_key} isn't the proxy's EC key: delete it and the CA to make new ones")
        ca_key = loaded
    else:
        ca_key = ec.generate_private_key(ec.SECP256R1())
        name = x509.Name(
            [
                x509.NameAttribute(NameOID.COMMON_NAME, "awsemu proxy local CA"),
                x509.NameAttribute(NameOID.ORGANIZATION_NAME, "awsemu"),
            ]
        )
        ca_cert = (
            x509.CertificateBuilder()
            .subject_name(name)
            .issuer_name(name)
            .public_key(ca_key.public_key())
            .serial_number(x509.random_serial_number())
            .not_valid_before(now - dt.timedelta(minutes=5))
            .not_valid_after(now + dt.timedelta(days=3650))
            .add_extension(x509.BasicConstraints(ca=True, path_length=0), critical=True)
            .add_extension(
                x509.KeyUsage(
                    digital_signature=True,
                    key_cert_sign=True,
                    crl_sign=True,
                    content_commitment=False,
                    key_encipherment=False,
                    data_encipherment=False,
                    key_agreement=False,
                    encipher_only=False,
                    decipher_only=False,
                ),
                critical=True,
            )
            .add_extension(x509.SubjectKeyIdentifier.from_public_key(ca_key.public_key()), critical=False)
            .sign(ca_key, hashes.SHA256())
        )
        write_key(files.ca_key, ca_key)
        files.ca.write_bytes(ca_cert.public_bytes(serialization.Encoding.PEM))
        files.cert.unlink(missing_ok=True)

    names = tuple(dict.fromkeys(BASE_NAMES + tuple(n for n in extra_names if n not in ("0.0.0.0", "::"))))
    wanted = _san_entries(x509, names)
    if files.cert.exists() and files.key.exists():
        cert = x509.load_pem_x509_certificate(files.cert.read_bytes())
        expires = getattr(cert, "not_valid_after_utc", None) or cert.not_valid_after.replace(tzinfo=dt.UTC)
        try:
            have = set(cert.extensions.get_extension_for_class(x509.SubjectAlternativeName).value)
        except x509.ExtensionNotFound:
            have = set()
        if expires - now > dt.timedelta(days=7) and set(wanted) <= have:
            return
    key = ec.generate_private_key(ec.SECP256R1())
    cert = (
        x509.CertificateBuilder()
        .subject_name(x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "127.0.0.1")]))
        .issuer_name(ca_cert.subject)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - dt.timedelta(minutes=5))
        .not_valid_after(now + dt.timedelta(days=397))
        .add_extension(x509.SubjectAlternativeName(wanted), critical=False)
        .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
        .add_extension(x509.ExtendedKeyUsage([ExtendedKeyUsageOID.SERVER_AUTH]), critical=False)
        .add_extension(x509.AuthorityKeyIdentifier.from_issuer_public_key(ca_key.public_key()), critical=False)
        .sign(ca_key, hashes.SHA256())
    )
    write_key(files.key, key)
    files.cert.write_bytes(cert.public_bytes(serialization.Encoding.PEM))


# --------------------------------------------------------------------------- server


class _Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    server: ProxyServer

    def log_message(self, format, *args):  # quiet
        pass

    def _body(self) -> bytes:
        if "chunked" in self.headers.get("Transfer-Encoding", "").lower():
            chunks: list[bytes] = []
            while True:
                size = int(self.rfile.readline().split(b";")[0].strip() or b"0", 16)
                if size == 0:
                    while self.rfile.readline() not in (b"\r\n", b"\n", b""):
                        pass
                    return b"".join(chunks)
                chunks.append(self.rfile.read(size))
                self.rfile.readline()
        length = int(self.headers.get("Content-Length") or 0)
        return self.rfile.read(length) if length else b""

    def _send(self, status: int, headers: list[tuple[str, str]], body: bytes, head: bool = False) -> None:
        self.send_response_only(status)
        has_length = False
        for k, v in headers:
            if k.lower() in HOP_BY_HOP:
                continue
            if k.lower() == "content-length":
                has_length = True
                if not head:
                    continue
            self.send_header(k, v)
        if not head:
            self.send_header("Content-Length", str(len(body)))
        elif not has_length:
            self.send_header("Content-Length", "0")
        self.end_headers()
        if body and not head and status not in (204, 304):
            self.wfile.write(body)

    def _handle(self) -> None:
        started = time.perf_counter()
        body = self._body()
        if self.path.startswith(ADMIN):
            return self._admin(body)
        headers = {k.lower(): v for k, v in self.headers.items()}
        try:
            ident = awscalls.identify(self.command, self.path, headers, body)
        except Exception:  # never break a call because we can't name it
            ident = awscalls.Identified()
        decision = self.server.faults.decide(ident.service, ident.operation, ident.resource)
        if decision.latency_ms:
            time.sleep(decision.latency_ms / 1000)
        rule = decision.error
        if rule and rule.reset:
            self.server.record(
                ident, self, 0, "ConnectionReset", started, None, decision.label, len(body), 0, (body, [], b"")
            )
            self._reset()
            return
        if rule:
            code, status = faults.code_and_status(rule, ident.service, ident.protocol)
            status, h, data = faults.error_response(
                code, status, ident.protocol, f"Injected by awsemu proxy ({rule.spec})", headers.get("content-type", "")
            )
            # Recorded before answering: once the client has its answer, the call is in the log.
            self.server.record(
                ident,
                self,
                status,
                code,
                started,
                h.get("x-amzn-RequestId"),
                decision.label,
                len(body),
                len(data),
                (body, list(h.items()), data),
            )
            self._send(status, list(h.items()), data, head=self.command == "HEAD")
            return
        try:
            status, resp_headers, data = self.server.forward(self.command, self.path, self.headers.items(), body)
        except (OSError, http.client.HTTPException) as exc:
            status, h, data = faults.error_response(
                "EmulatorUnreachable",
                502,
                ident.protocol,
                f"awsemu proxy: the emulator on port {self.server.emulator_port} didn't answer ({exc})",
                headers.get("content-type", ""),
            )
            self.server.record(
                ident,
                self,
                502,
                "EmulatorUnreachable",
                started,
                None,
                decision.label,
                len(body),
                len(data),
                (body, list(h.items()), data),
            )
            self._send(status, list(h.items()), data, head=self.command == "HEAD")
            return
        lower = {k.lower(): v for k, v in resp_headers}
        logged = self.server.record(
            ident,
            self,
            status,
            awscalls.error_code(status, lower, data),
            started,
            awscalls.request_id(lower),
            decision.label,
            len(body),
            len(data),
            (body, resp_headers, data),
        )
        if self.server.shadow is not None:
            self.server.shadow.offer(logged, self.command, self.path, self.headers.items(), body, (status, lower, data))
        self._send(status, resp_headers, data, head=self.command == "HEAD")

    def _reset(self) -> None:
        self.close_connection = True
        try:
            self.connection.setsockopt(socket.SOL_SOCKET, socket.SO_LINGER, struct.pack("ii", 1, 0))
            self.connection.close()
        except OSError:  # pragma: no cover
            pass

    def _admin(self, body: bytes) -> None:
        url = urlsplit(self.path)
        route = url.path[len(ADMIN) :].strip("/")
        query = dict(parse_qsl(url.query))
        status, data = 200, {}  # type: tuple[int, dict]
        token = self.server.admin_token
        if token and not hmac.compare_digest(self.headers.get(TOKEN_HEADER, ""), token):
            payload = json.dumps(
                {"message": f"the admin API needs the proxy's token ({TOKEN_HEADER}); awsemu proxy commands send it"}
            ).encode()
            self._send(401, [("Content-Type", "application/json")], payload)
            return
        try:
            if route == "health":
                data = {"ok": True, "emulator_port": self.server.emulator_port, "calls": self.server.count}
            elif route == "faults":
                if self.command in ("PUT", "POST"):
                    specs = json.loads(body or b"{}").get("rules", [])
                    rules = [faults.parse(s) for s in specs]
                    if self.command == "PUT":
                        self.server.faults.replace(rules)
                    else:
                        self.server.faults.add(*rules)
                elif self.command == "DELETE":
                    self.server.faults.clear()
                data = {"rules": [r.as_dict() for r in self.server.faults.rules()]}
            elif route == "calls":
                after = int(query.get("after", 0))
                calls = self.server.calls_after(after, int(query.get("limit", 1000)))
                data = {"calls": calls, "last": self.server.count}
            else:
                status, data = 404, {"message": f"unknown admin route '{route}'"}
        except (ValueError, faults.FaultError) as exc:
            status, data = 400, {"message": str(exc)}
        payload = json.dumps(data).encode()
        self._send(status, [("Content-Type", "application/json")], payload)

    do_GET = do_POST = do_PUT = do_DELETE = do_HEAD = do_PATCH = do_OPTIONS = _handle


class ProxyServer(ThreadingHTTPServer):
    """The proxy. ``serve_forever()`` in a thread or the main loop."""

    daemon_threads = True
    allow_reuse_address = True

    def __init__(
        self,
        emulator_port: int,
        listen_port: int = 0,
        rules: list[faults.Fault] | None = None,
        tls: bool = True,
        calls_file: Path | None = None,
        on_call=None,
        timeout: float = 120.0,
        bodies: bool = False,
        host: str = DEFAULT_HOST,
        admin_token: str | None = "",
        shadow=None,
    ):
        """``admin_token``: "" makes a random one; None turns the check off (tests)."""
        self.emulator_port = emulator_port
        self.bodies = bodies
        self.shadow = shadow  # awsemu.shadow.Shadow, or None
        self.host = host
        self.admin_token = secrets.token_urlsafe(24) if admin_token == "" else admin_token
        self.faults = faults.FaultSet(rules)
        self.files = ProxyFiles(emulator_port)
        self.calls_file = calls_file
        self.on_call = on_call
        self.timeout_s = timeout
        self.count = 0
        self._ring: deque[dict] = deque(maxlen=RING)
        self._lock = threading.Lock()
        self._upstream_ctx: tuple[float, ssl.SSLContext] | None = None
        self._local = threading.local()
        self._upstream_conns: set[http.client.HTTPSConnection] = set()  # closed with the server
        self._open_sockets: set[ssl.SSLSocket] = set()
        self.tls = tls
        self._ctx = None
        if tls:
            ensure_certs(self.files, (host,))
            self._ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
            self._ctx.load_cert_chain(self.files.cert, self.files.key)
        if ":" in host:
            self.address_family = socket.AF_INET6
        super().__init__((host, listen_port), _Handler)

    def server_bind(self):
        # HTTPServer.server_bind() looks up the host's FQDN (reverse DNS), which can take
        # tens of seconds on some machines (macOS CI runners). We know the name.
        import socketserver

        socketserver.TCPServer.server_bind(self)
        host, port = self.server_address[:2]
        self.server_name, self.server_port = str(host), int(port)

    # TLS handshake in the worker thread, not in the accept loop
    def finish_request(self, request, client_address):
        if not self._ctx:
            super().finish_request(request, client_address)
            return
        try:
            wrapped = self._ctx.wrap_socket(request, server_side=True)
        except (ssl.SSLError, OSError):
            return
        with self._lock:
            self._open_sockets.add(wrapped)
        try:
            super().finish_request(wrapped, client_address)
        finally:
            with self._lock:
                self._open_sockets.discard(wrapped)
            # socketserver closes the raw socket it accepted; the TLS one owns the descriptor now
            try:
                wrapped.close()
            except OSError:  # pragma: no cover
                pass

    def server_close(self):
        super().server_close()
        with self._lock:
            conns, self._upstream_conns = self._upstream_conns, set()
            open_sockets, self._open_sockets = self._open_sockets, set()
        for conn in conns:
            conn.close()
        for sock in open_sockets:  # clients' keep-alive connections, still waiting for a request
            try:
                sock.close()
            except OSError:  # pragma: no cover
                pass

    @property
    def port(self) -> int:
        return self.server_address[1]

    @property
    def endpoint_url(self) -> str:
        """For programs on this machine."""
        return f"{'https' if self.tls else 'http'}://{DEFAULT_HOST}:{self.port}"

    @property
    def container_endpoint_url(self) -> str | None:
        """For containers, when the proxy listens beyond 127.0.0.1."""
        if self.host in (DEFAULT_HOST, "localhost", "::1"):
            return None
        return f"{'https' if self.tls else 'http'}://{CONTAINER_HOST}:{self.port}"

    # -- upstream

    def _context(self) -> ssl.SSLContext:
        ca = InstanceFiles(self.emulator_port).ca
        try:
            mtime = ca.stat().st_mtime
        except OSError as exc:
            raise ConnectionRefusedError(f"no emulator on port {self.emulator_port} ({ca} is missing)") from exc
        with self._lock:
            if not self._upstream_ctx or self._upstream_ctx[0] != mtime:
                ctx = ssl.create_default_context(cafile=str(ca))
                self._upstream_ctx = (mtime, ctx)  # the emulator makes a new CA on every start
            return self._upstream_ctx[1]

    def forward(self, method: str, path: str, headers, body: bytes):
        ctx = self._context()
        for attempt in (1, 2):
            conn = getattr(self._local, "conn", None)
            if conn is None or getattr(self._local, "ctx", None) is not ctx:
                conn = http.client.HTTPSConnection(
                    DEFAULT_HOST, self.emulator_port, context=ctx, timeout=self.timeout_s
                )
                self._local.conn, self._local.ctx = conn, ctx
                with self._lock:
                    self._upstream_conns.add(conn)
            try:
                conn.putrequest(method, path, skip_host=True, skip_accept_encoding=True)
                for k, v in headers:
                    if k.lower() not in HOP_BY_HOP and k.lower() != "content-length":
                        conn.putheader(k, v)
                if body or method in ("POST", "PUT", "PATCH"):
                    conn.putheader("Content-Length", str(len(body)))
                conn.endheaders(body or None)
                resp = conn.getresponse()
                data = resp.read()
                if resp.will_close:
                    conn.close()
                    self._local.conn = None
                return resp.status, resp.getheaders(), data
            except (
                http.client.RemoteDisconnected,
                BrokenPipeError,
                ConnectionResetError,
                http.client.CannotSendRequest,
            ):
                conn.close()
                self._local.conn = None
                if attempt == 2:
                    raise
        raise AssertionError("unreachable")  # pragma: no cover

    # -- calls

    def record(
        self, ident, handler, status, error, started, request_id, fault, bytes_in, bytes_out, bodies=None
    ) -> dict:
        """Log one call. ``bodies`` is ``(request body, response headers, response body)``,
        kept (masked) only when the proxy runs with --bodies."""
        call = awscalls.Call(
            time=dt.datetime.now(dt.UTC).isoformat(timespec="milliseconds"),
            service=ident.service,
            operation=ident.operation,
            resource=ident.resource,
            method=handler.command,
            path=redact.url(handler.path)[:300],
            status=status,
            error=error,
            latency_ms=round((time.perf_counter() - started) * 1000, 1),
            request_id=request_id,
            fault=fault,
            bytes_in=bytes_in,
            bytes_out=bytes_out,
        )
        data = call.as_dict()
        if self.bodies and bodies is not None:
            req_body, resp_headers, resp_body = bodies
            data.update(
                exchange(
                    handler.command, handler.path, handler.headers.items(), req_body, status, resp_headers, resp_body
                )
            )
        with self._lock:
            self.count += 1
            data["id"] = self.count
            self._ring.append(data)
            if self.calls_file:
                self._append(data)
        if self.on_call:
            try:
                self.on_call(data)
            except Exception:
                pass
        return data

    def _append(self, data: dict) -> None:
        if self.calls_file is None:
            return
        try:
            if self.calls_file.exists() and self.calls_file.stat().st_size > MAX_LOG_BYTES:
                self.calls_file.replace(self.calls_file.with_suffix(".1.jsonl"))
            with self.calls_file.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(data) + "\n")
        except OSError:  # pragma: no cover
            pass

    def calls_after(self, after: int, limit: int = 1000) -> list[dict]:
        with self._lock:
            return [c for c in self._ring if c["id"] > after][:limit]

    def start_thread(self) -> threading.Thread:
        thread = threading.Thread(target=self.serve_forever, name="awsemu-proxy", daemon=True)
        thread.start()
        return thread


# --------------------------------------------------------------------------- state and control


def read_state(emulator_port: int) -> dict | None:
    try:
        return json.loads(ProxyFiles(emulator_port).state.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def running(emulator_port: int) -> dict | None:
    """The state of the proxy in front of ``emulator_port`` if it answers, else None."""
    from .runtime import pid_alive

    state = read_state(emulator_port)
    if not state or not pid_alive(int(state.get("pid", 0))):
        return None
    try:
        admin(state, "GET", "health", timeout=3)
    except ProxyError:
        return None
    return state


def admin(state: dict, method: str, route: str, payload: dict | None = None, timeout: float = 10) -> dict:
    """Call the admin API of a running proxy."""
    url = urlsplit(state["endpoint_url"])
    conn: http.client.HTTPConnection
    if url.scheme == "https":
        ctx = ssl.create_default_context(cafile=state["ca"])
        conn = http.client.HTTPSConnection(url.hostname or "127.0.0.1", url.port, context=ctx, timeout=timeout)
    else:
        conn = http.client.HTTPConnection(url.hostname or "127.0.0.1", url.port, timeout=timeout)
    body = json.dumps(payload).encode() if payload is not None else None
    headers = {"Content-Type": "application/json"} if body else {}
    if state.get("token"):
        headers[TOKEN_HEADER] = state["token"]
    try:
        conn.request(method, f"{ADMIN}/{route}", body=body, headers=headers)
        resp = conn.getresponse()
        data = json.loads(resp.read() or b"{}")
    except (OSError, http.client.HTTPException, ValueError) as exc:
        raise ProxyError(f"the proxy didn't answer: {exc}") from exc
    finally:
        conn.close()
    if resp.status >= 400:
        raise ProxyError(data.get("message", f"HTTP {resp.status}"))
    return data


def _write_private(path: Path, text: str) -> None:
    """Write a file only its owner can read (it holds the admin token)."""
    flags = os.O_WRONLY | os.O_CREAT | os.O_TRUNC
    fd = os.open(path, flags, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        fh.write(text)
    try:
        path.chmod(0o600)
    except OSError:  # pragma: no cover
        pass


def serve(
    emulator_port: int,
    listen_port: int,
    rules: list[faults.Fault],
    tls: bool = True,
    on_call=None,
    on_ready=None,
    bodies: bool = False,
    host: str = DEFAULT_HOST,
    shadow: dict | None = None,
) -> int:
    """Run the proxy in this process until SIGTERM/Ctrl-C, keeping the state file."""
    files = ProxyFiles(emulator_port)
    files.dir.mkdir(parents=True, exist_ok=True)
    shadow_obj = None
    if shadow:
        from .shadow import Shadow

        shadow_obj = Shadow(shadow["profile"], shadow.get("region"), files.shadow, shadow.get("max", 500))
    server = ProxyServer(
        emulator_port,
        listen_port,
        rules,
        tls=tls,
        calls_file=files.calls,
        on_call=on_call,
        bodies=bodies,
        host=host,
        shadow=shadow_obj,
    )
    state = {
        "pid": os.getpid(),
        "emulator_port": emulator_port,
        "port": server.port,
        "endpoint_url": server.endpoint_url,
        "host": host,
        "container_endpoint_url": server.container_endpoint_url,
        "tls": tls,
        "ca": str(files.ca) if tls else None,
        "bodies": bodies,
        "token": server.admin_token,
        "shadow": (
            {"profile": shadow["profile"], "region": shadow_obj.region, "max": shadow_obj.max_calls}
            if shadow_obj and shadow
            else None
        ),
        "calls": str(files.calls),
        "started_at": dt.datetime.now(dt.UTC).isoformat(),
    }
    _write_private(files.state, json.dumps(state))

    def stop(*_):
        threading.Thread(target=server.shutdown, daemon=True).start()

    for sig in ("SIGTERM", "SIGBREAK", "SIGHUP"):
        if hasattr(signal, sig):
            try:
                signal.signal(getattr(signal, sig), stop)
            except (ValueError, OSError):  # pragma: no cover - not the main thread
                pass
    if on_ready:
        on_ready(state)
    try:
        server.serve_forever(poll_interval=0.2)
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
        if shadow_obj is not None:
            shadow_obj.close()
        current = read_state(emulator_port)
        if current and current.get("pid") == os.getpid():
            files.state.unlink(missing_ok=True)
    return 0


def start_detached(
    emulator_port: int,
    listen_port: int,
    specs: list[str],
    tls: bool = True,
    wait: float = 20.0,
    bodies: bool = False,
    host: str = DEFAULT_HOST,
    shadow: dict | None = None,
) -> dict:
    """Start ``awsemu proxy start`` in the background and wait until it answers."""
    from .runtime import _popen_detached

    files = ProxyFiles(emulator_port)
    files.dir.mkdir(parents=True, exist_ok=True)
    files.state.unlink(missing_ok=True)
    cmd = [
        sys.executable,
        "-m",
        "awsemu",
        "--port",
        str(emulator_port),
        "proxy",
        "start",
        "--listen",
        str(listen_port),
        "--quiet",
        "--foreground",
    ]
    if not tls:
        cmd.append("--no-tls")
    if bodies:
        cmd.append("--bodies")
    if host != DEFAULT_HOST:
        cmd += ["--host", host]
    if shadow:
        cmd += ["--shadow", shadow["profile"], "--shadow-max", str(shadow.get("max", 500)), "--yes"]
        if shadow.get("region"):
            cmd += ["--shadow-region", shadow["region"]]
    for spec in specs:
        cmd += ["--fault", spec]
    # The child runs this same awsemu, even from a source checkout that isn't installed.
    package_root = str(Path(__file__).resolve().parent.parent)
    env = dict(os.environ)
    env["PYTHONPATH"] = os.pathsep.join(filter(None, [package_root, env.get("PYTHONPATH")]))
    proc = _popen_detached(cmd, files.log, env=env)

    def log_tail() -> str:
        try:
            return files.log.read_text(encoding="utf-8", errors="replace")[-1500:].strip()
        except OSError:
            return ""

    def answering():
        if proc.poll() is not None:
            raise ProxyError(f"the proxy exited with code {proc.returncode}:\n{log_tail()}")
        return running(emulator_port) or None

    state = waiting.poll(answering, timeout=wait, interval=0.15)
    if state:
        return state
    state = read_state(emulator_port)
    detail = f"state: {state}" if state else "it never wrote its state file"
    raise ProxyError(f"the proxy didn't answer within {wait:.0f} s ({detail}; log: {files.log})\n{log_tail()}")


def stop(emulator_port: int, timeout: float = 10.0) -> bool:
    """Stop the background proxy. False if none was running."""
    from .runtime import _send_stop, _wait_gone, pid_alive

    state = read_state(emulator_port)
    if not state:
        return False
    pid = int(state.get("pid", 0))
    files = ProxyFiles(emulator_port)
    if not pid_alive(pid):
        files.state.unlink(missing_ok=True)
        return False
    _send_stop(pid, force=False)
    if not _wait_gone(pid, timeout):
        _send_stop(pid, force=True)
        _wait_gone(pid, 5)
    files.state.unlink(missing_ok=True)
    return True


def client_env(state: dict) -> dict[str, str]:
    """Variables that send SDKs to the proxy instead of the emulator."""
    env = {"AWS_ENDPOINT_URL": state["endpoint_url"]}
    if state.get("ca"):
        env["AWS_CA_BUNDLE"] = state["ca"]
    return env


# --------------------------------------------------------------------------- the calls log, for the commands


def default_listen(emulator_port: int) -> int:
    """The proxy's port: the project's ``proxy_port``, else the emulator's + 1 (0 with ``--port 0``)."""
    from . import project

    try:
        proj = project.load()
    except project.ProjectError:
        proj = None
    if proj and proj.proxy_port is not None:
        return proj.proxy_port
    return emulator_port + 1 if emulator_port else 0


def read_calls(path: Path, last: int | None = None) -> list[dict]:
    """The calls in a calls log (the ``last`` ones, if given); unreadable lines are skipped."""
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return []
    out = []
    for line in lines[-last:] if last else lines:
        try:
            out.append(json.loads(line))
        except ValueError:
            continue
    return out


def load_calls(port: int, calls_file: Path | None) -> tuple[list[dict], Path]:
    """The calls of ``calls_file`` or of the proxy in front of ``port``; an error if there are none."""
    log = calls_file or ProxyFiles(port).calls
    calls = read_calls(log)
    if not calls:
        raise errors.RuntimeErrorWithHint(
            f"no calls in {log}",
            "Run your tests through the proxy first: awsemu proxy start -d, then awsemu exec --proxy -- pytest.",
        )
    return calls, log
