#!/usr/bin/env python3
"""A tiny stand-in for the ``aws-emulator`` binary, used by the tests.

It mimics the documented behaviour that awsemu relies on:
- options ``-p``, ``-a``, ``-t``, ``-b``, ``--idle-timeout``, ``-v``
- writes ``config``, ``emulator_credentials`` (auth on), ``ca.pem`` to ~/.aws/emulator/<port>/
- serves ``GET /__admin/health`` -> ``ok`` over HTTPS with that certificate
- logs JSON lines, including the ``emulator server information`` startup line
- deletes its files on SIGTERM / Ctrl+C
"""

import argparse
import json
import os
import shutil
import signal
import ssl
import subprocess
import sys
import tempfile
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path


def log(message, **fields):
    print(json.dumps({"timestamp": "2026-11-15T12:00:00.123456Z", "level": "INFO",
                      "message": message, **fields}), flush=True)


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

    root = Path(os.path.expanduser("~")) / ".aws" / "emulator" / str(args.port)
    root.mkdir(parents=True, exist_ok=True)
    tmp = Path(tempfile.mkdtemp())
    key = tmp / "key.pem"
    subprocess.run(["openssl", "req", "-x509", "-newkey", "rsa:2048", "-nodes", "-days", "1",
                    "-keyout", str(key), "-out", str(root / "ca.pem"), "-subj", "/CN=127.0.0.1",
                    "-addext", "subjectAltName=IP:127.0.0.1"],
                   check=True, capture_output=True)
    (root / "config").write_text(
        f"[default]\nregion = us-east-1\nendpoint_url = https://127.0.0.1:{args.port}\n"
        f"ca_bundle = {root / 'ca.pem'}\n")
    if args.auth == "on":
        (root / "emulator_credentials").write_text(
            "[default]\naws_access_key_id = EMULATOR0123456789AB\n"
            "aws_secret_access_key = " + "A" * 40 + "\n")

    server = ThreadingHTTPServer((args.bind, args.port), Handler)
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    ctx.load_cert_chain(str(root / "ca.pem"), str(key))
    server.socket = ctx.wrap_socket(server.socket, server_side=True)

    def shutdown(*_):
        log("shutting down")
        threading.Thread(target=server.shutdown).start()

    signal.signal(signal.SIGTERM, shutdown)
    signal.signal(signal.SIGINT, shutdown)
    print(f"telemetry is {args.telemetry}", file=sys.stderr, flush=True)
    log("emulator server information", endpoint_url=f"https://127.0.0.1:{args.port}",
        health_check_url=f"https://127.0.0.1:{args.port}/__admin/health",
        config_file=str(root / "config"), ca_file=str(root / "ca.pem"))
    server.serve_forever()
    shutil.rmtree(root, ignore_errors=True)
    shutil.rmtree(tmp, ignore_errors=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
