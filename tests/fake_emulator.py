#!/usr/bin/env python3
"""A tiny stand-in for the ``aws-emulator`` binary, used by the tests.

It mimics the documented behaviour that awsemu relies on:
- options ``-p`` (including ``-p 0``), ``-a``, ``-t``, ``-b``, ``--idle-timeout``, ``-v``
- writes ``config``, ``emulator_credentials`` (auth on), ``ca.pem`` to ~/.aws/emulator/<port>/
- serves ``GET /__admin/health`` -> ``ok`` over HTTPS with that certificate
- logs JSON lines, including the ``emulator server information`` startup line
- deletes its files on a clean stop (SIGTERM, Ctrl+C, or Ctrl+Break on Windows)

Test-only switches (environment variables):
- ``FAKE_EMULATOR_CRASH=1``       exit with code 1 right away
- ``FAKE_EMULATOR_IGNORE_STOP=1`` ignore stop signals (to test forced stops)

The certificate is generated with ``cryptography`` so this works on Linux,
macOS and Windows without depending on the local ``openssl`` flavour.
"""

import argparse
import datetime
import ipaddress
import json
import os
import shutil
import signal
import ssl
import sys
import tempfile
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.x509.oid import NameOID


def log(message, **fields):
    print(json.dumps({"timestamp": "2026-11-15T12:00:00.123456Z", "level": "INFO",
                      "message": message, **fields}), flush=True)


def make_cert(cert_path: Path, key_path: Path) -> None:
    key = ec.generate_private_key(ec.SECP256R1())
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "127.0.0.1")])
    now = datetime.datetime.now(datetime.timezone.utc)
    cert = (
        x509.CertificateBuilder()
        .subject_name(name)
        .issuer_name(name)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - datetime.timedelta(minutes=5))
        .not_valid_after(now + datetime.timedelta(days=1))
        .add_extension(x509.SubjectAlternativeName([x509.IPAddress(ipaddress.ip_address("127.0.0.1"))]),
                       critical=False)
        .add_extension(x509.BasicConstraints(ca=True, path_length=None), critical=True)
        .sign(key, hashes.SHA256())
    )
    cert_path.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    key_path.write_bytes(key.private_bytes(serialization.Encoding.PEM,
                                           serialization.PrivateFormat.PKCS8,
                                           serialization.NoEncryption()))


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):  # noqa: N802
        if self.path == "/__admin/health":
            body = b"ok"
            self.send_response(200)
        else:
            body = b"UnknownService"
            self.send_response(404)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):
        pass


def main():
    p = argparse.ArgumentParser()
    p.add_argument("-p", "--port", type=int, default=9297)
    p.add_argument("-b", "--bind", default="127.0.0.1")
    p.add_argument("-a", "--auth", default="on")
    p.add_argument("-t", "--telemetry", default="on")
    p.add_argument("--idle-timeout", type=int)
    p.add_argument("-v", "--version", action="store_true")
    args = p.parse_args()
    if args.version:
        print("aws-emulator 0.0.0-fake")
        return 0
    if os.environ.get("FAKE_EMULATOR_CRASH"):
        print("emulator serve failed: boom", file=sys.stderr)
        return 1

    server = ThreadingHTTPServer((args.bind, args.port), Handler)
    port = server.server_address[1]  # the real port, also for -p 0

    root = Path(os.path.expanduser("~")) / ".aws" / "emulator" / str(port)
    root.mkdir(parents=True, exist_ok=True)
    tmp = Path(tempfile.mkdtemp())
    key = tmp / "key.pem"
    make_cert(root / "ca.pem", key)
    (root / "config").write_text(
        f"[default]\nregion = us-east-1\nendpoint_url = https://127.0.0.1:{port}\n"
        f"ca_bundle = {root / 'ca.pem'}\n")
    if args.auth == "on":
        (root / "emulator_credentials").write_text(
            "[default]\naws_access_key_id = EMULATOR0123456789AB\n"
            "aws_secret_access_key = " + "A" * 40 + "\n")

    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    ctx.load_cert_chain(str(root / "ca.pem"), str(key))
    server.socket = ctx.wrap_socket(server.socket, server_side=True)

    def shutdown(*_):
        log("shutting down")
        threading.Thread(target=server.shutdown).start()

    stop_signals = [signal.SIGINT, signal.SIGTERM]
    if hasattr(signal, "SIGBREAK"):  # Windows: Ctrl+Break reaches a process group
        stop_signals.append(signal.SIGBREAK)
    handler = signal.SIG_IGN if os.environ.get("FAKE_EMULATOR_IGNORE_STOP") else shutdown
    for sig in stop_signals:
        signal.signal(sig, handler)

    print(f"telemetry is {args.telemetry}", file=sys.stderr, flush=True)
    log("emulator server information", endpoint_url=f"https://127.0.0.1:{port}",
        health_check_url=f"https://127.0.0.1:{port}/__admin/health",
        config_file=str(root / "config"), ca_file=str(root / "ca.pem"))
    server.serve_forever(poll_interval=0.2)
    shutil.rmtree(root, ignore_errors=True)
    shutil.rmtree(tmp, ignore_errors=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
