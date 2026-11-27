"""Health checks against the emulator's ``GET /__admin/health`` route."""

from __future__ import annotations

import socket
import ssl
import urllib.error
import urllib.request
from dataclasses import dataclass

from . import errors
from .paths import DEFAULT_HOST, InstanceFiles


@dataclass
class Health:
    port: int
    port_open: bool
    healthy: bool
    detail: str

    @property
    def label(self) -> str:
        if self.healthy:
            return "healthy"
        if self.port_open:
            return "unhealthy"
        return "stopped"


def port_open(port: int, host: str = DEFAULT_HOST, timeout: float = 0.5) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def check(port: int, timeout: float = 2.0) -> Health:
    files = InstanceFiles(port)
    is_open = port_open(port)
    if not is_open:
        return Health(port, False, False, "nothing is listening on the port")
    if not files.ca.exists():
        return Health(port, True, False, f"port is open but {files.ca} is missing (not AWS Emulator?)")
    try:
        ctx = ssl.create_default_context(cafile=str(files.ca))
        with urllib.request.urlopen(files.health_url, context=ctx, timeout=timeout) as resp:
            body = resp.read().decode("utf-8", "replace").strip()
            if resp.status == 200 and body == "ok":
                return Health(port, True, True, "ok")
            return Health(port, True, False, f"HTTP {resp.status}: {body[:80]}")
    except ssl.SSLError as exc:
        return Health(port, True, False, f"TLS error (stale certificate?): {exc}")
    except urllib.error.HTTPError as exc:
        return Health(port, True, False, f"HTTP {exc.code}")
    except (urllib.error.URLError, OSError) as exc:
        return Health(port, True, False, str(getattr(exc, "reason", exc)))


def wait_healthy(port: int, timeout: float = 30.0, interval: float = 0.5, abort=None) -> Health:
    """Poll until healthy or ``timeout`` seconds. ``abort()`` returning a string stops early."""
    from .waiting import poll

    last = check(port)
    first = True

    def attempt() -> Health | None:
        nonlocal last, first
        if not first:
            last = check(port)
        first = False
        if last.healthy:
            return last
        if abort is not None:
            reason = abort()
            if reason:
                return Health(port, last.port_open, False, reason)
        return None

    return poll(attempt, timeout=timeout, interval=interval) or last


def wait_port_closed(port: int, timeout: float = 5.0) -> bool:
    """Wait until nothing listens on ``port`` (it may linger after the process exits)."""
    from .waiting import until

    return until(lambda: not port_open(port), timeout=timeout, interval=0.1)


def require_healthy(port: int) -> None:
    """Raise, with how to start one, unless a healthy emulator answers on ``port``."""
    from . import project

    h = check(port)
    if not h.healthy:
        flag = "" if port == project.default_port() else f" --port {port}"
        raise errors.RuntimeErrorWithHint(
            f"No healthy emulator on port {port} ({h.detail}).", f"Start one with 'awsemu{flag} start'."
        )
