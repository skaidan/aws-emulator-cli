"""Setup traps: environment settings that quietly break SDK calls to the emulator.

Each check takes the environment (and the port) and returns findings for
``awsemu doctor``; nothing here changes anything.
"""

from __future__ import annotations

import configparser
import os
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit

from .paths import InstanceFiles, cli_root, emulator_root

LOCAL_HOSTS = {"127.0.0.1", "localhost", "::1", "[::1]"}
PROXY_VARS = ("HTTPS_PROXY", "https_proxy", "HTTP_PROXY", "http_proxy", "ALL_PROXY", "all_proxy")

# ~/.aws/config settings that change SDK behaviour, and the variable that does the same
# (environment variables still apply under the emulator; the config file doesn't).
CONFIG_TO_ENV = {
    "retry_mode": "AWS_RETRY_MODE",
    "max_attempts": "AWS_MAX_ATTEMPTS",
    "defaults_mode": "AWS_DEFAULTS_MODE",
    "request_checksum_calculation": "AWS_REQUEST_CHECKSUM_CALCULATION",
    "response_checksum_validation": "AWS_RESPONSE_CHECKSUM_VALIDATION",
    "account_id_endpoint_mode": "AWS_ACCOUNT_ID_ENDPOINT_MODE",
    "sigv4a_signing_region_set": "AWS_SIGV4A_SIGNING_REGION_SET",
    "tcp_keepalive": None,
    "s3": None,
}


@dataclass
class Finding:
    check: str
    detail: str
    fix: str


def _local_endpoint(env) -> tuple[str, str, int | None] | None:
    value = env.get("AWS_ENDPOINT_URL")
    if not value:
        return None
    url = urlsplit(value)
    if url.hostname not in LOCAL_HOSTS and f"[{url.hostname}]" not in LOCAL_HOSTS:
        return None
    return url.scheme, url.hostname, url.port


def endpoint(env, answers) -> list[Finding]:
    """``AWS_ENDPOINT_URL`` problems. ``answers(port) -> str|None`` names what listens there."""
    found = _local_endpoint(env)
    if not found:
        return []
    scheme, host, port = found
    out = []
    if host == "localhost":
        out.append(
            Finding(
                "endpoint",
                "AWS_ENDPOINT_URL uses 'localhost'",
                "use 127.0.0.1: with 'localhost' the JavaScript, Java and Go SDKs put the S3 bucket "
                "in the host name, which the emulator doesn't serve",
            )
        )
    if port is None:
        return out
    what = answers(port)
    if what is None:
        out.append(
            Finding(
                "endpoint",
                f"AWS_ENDPOINT_URL={env['AWS_ENDPOINT_URL']}, but nothing answers there",
                'probably left from an earlier start: eval "$(awsemu env)" again, or use awsemu exec',
            )
        )
    elif scheme == "http" and what == "emulator":
        out.append(
            Finding(
                "endpoint",
                "AWS_ENDPOINT_URL uses http://, the emulator only speaks HTTPS",
                "use https:// (awsemu env sets it)",
            )
        )
    return out


def ca_bundle(env, answers) -> list[Finding]:
    """An ``AWS_CA_BUNDLE`` that can't verify the endpoint in use."""
    value = env.get("AWS_CA_BUNDLE")
    local = _local_endpoint(env)
    if not value or not local:
        return []
    path = Path(value)
    if not path.exists():
        return [
            Finding(
                "ca bundle",
                f"AWS_CA_BUNDLE={value} doesn't exist",
                'eval "$(awsemu env)" again (the emulator makes a new certificate on every start)',
            )
        ]
    proxy_ca = cli_root() / "proxy" / "ca.pem"
    try:
        resolved = path.resolve()
        instance = resolved.parent.parent == emulator_root().resolve() and resolved.name == "ca.pem"
    except OSError:  # pragma: no cover
        instance = False
    port = local[2]
    if instance:
        cert_port = resolved.parent.name
        if port is not None and str(port) != cert_port and answers(port) == "emulator":
            return [
                Finding(
                    "ca bundle",
                    f"AWS_CA_BUNDLE is the certificate of port {cert_port}, but AWS_ENDPOINT_URL is port {port}",
                    'eval "$(awsemu --port N env)" with the port you use',
                )
            ]
        return []
    if path.resolve() == proxy_ca.resolve():
        return []
    if port is not None and answers(port) == "emulator":
        return [
            Finding(
                "ca bundle",
                f"AWS_CA_BUNDLE={value} isn't the emulator's certificate",
                'requests to the emulator will fail certificate checks; eval "$(awsemu env)" or use awsemu exec',
            )
        ]
    return []


def proxies(env) -> list[Finding]:
    """An HTTP(S) proxy without an exception for 127.0.0.1."""
    set_vars = [v for v in PROXY_VARS if env.get(v)]
    if not set_vars:
        return []
    bypass = ",".join(env.get(v, "") for v in ("NO_PROXY", "no_proxy")).replace(" ", "")
    entries = {e for e in bypass.split(",") if e}
    if "*" in entries or "127.0.0.1" in entries:
        return []
    return [
        Finding(
            "http proxy",
            f"{set_vars[0]} is set and NO_PROXY doesn't include 127.0.0.1",
            "your own scripts send emulator calls to that proxy: export NO_PROXY=127.0.0.1,localhost"
            "${NO_PROXY:+,$NO_PROXY} (awsemu env/exec add it for you)",
        )
    ]


def no_proxy_value(env) -> str | None:
    """``NO_PROXY`` with 127.0.0.1 and localhost added, if a proxy is set; else None."""
    if not any(env.get(v) for v in PROXY_VARS):
        return None
    current = env.get("NO_PROXY") or env.get("no_proxy") or ""
    entries = [e for e in current.replace(" ", "").split(",") if e]
    for host in ("127.0.0.1", "localhost"):
        if host not in entries and "*" not in entries:
            entries.append(host)
    return ",".join(entries)


def hidden_config(env, home: Path | None = None) -> list[Finding]:
    """Settings of your own ~/.aws/config that don't apply while AWS_CONFIG_FILE is the emulator's."""
    own = env.get("AWS_CONFIG_FILE")
    try:
        ours = own and Path(own).resolve().is_relative_to(emulator_root().resolve())
    except OSError:  # pragma: no cover
        ours = False
    path = Path(own) if own and not ours else (home or Path.home()) / ".aws" / "config"
    parser = configparser.ConfigParser(interpolation=None)
    try:
        parser.read(path, encoding="utf-8")
    except (configparser.Error, OSError, UnicodeDecodeError):
        return []
    if not parser.has_section("default"):
        return []
    keys = [k for k in parser.options("default") if k in CONFIG_TO_ENV]
    if not keys:
        return []
    exports = [f"{CONFIG_TO_ENV[k]}={parser.get('default', k).strip()}" for k in keys if CONFIG_TO_ENV[k]]
    others = [k for k in keys if not CONFIG_TO_ENV[k]]
    fix = "awsemu points AWS_CONFIG_FILE at the emulator's config, so the SDKs don't read yours"
    if exports:
        fix += f"; to keep them, export {' '.join(exports)} (environment variables still apply)"
    if others:
        fix += f"; {', '.join(others)} have no environment variable: set them in code"
    return [Finding("your aws config", f"{path} [default] sets {', '.join(keys)}", fix)]


def all_findings(port: int, env=None, answers=None, home: Path | None = None) -> list[Finding]:
    env = os.environ if env is None else env
    answers = answers or listening
    return [*endpoint(env, answers), *ca_bundle(env, answers), *proxies(env), *hidden_config(env, home)]


def listening(port: int) -> str | None:
    """``"emulator"``, ``"proxy"`` or None: what answers on a local port."""
    from . import health
    from . import proxy as px

    for emulator_port in _proxy_ports():
        state = px.read_state(emulator_port)
        if state and state.get("port") == port and px.running(emulator_port):
            return "proxy"
    if InstanceFiles(port).exists() and health.check(port).healthy:
        return "emulator"
    return None


def _proxy_ports() -> list[int]:
    base = cli_root() / "proxy"
    try:
        return [int(p.name) for p in base.iterdir() if p.is_dir() and p.name.isdigit()]
    except OSError:
        return []
