"""What ``awsemu doctor`` checks: the machine, the install and the instance on a port.

:func:`run` returns a :class:`Diagnosis`; the command prints it as a table or as JSON.
"""

from __future__ import annotations

import importlib.util
import os
import platform
import shutil
import subprocess
import sys
from dataclasses import asdict, dataclass, field

from . import __version__, _meta, envvars, fidelity, health, project, runtime, settings
from .paths import emulator_settings_file


@dataclass(frozen=True)
class Check:
    check: str
    result: str
    """ok, warn (doesn't make doctor fail) or fail."""
    detail: str
    fix: str | None = None
    """How to fix it; only when the result isn't ok."""


@dataclass
class Diagnosis:
    checks: list[Check] = field(default_factory=list)

    @property
    def problems(self) -> int:
        return sum(c.result == "fail" for c in self.checks)

    def as_dict(self) -> dict:
        return {"ok": self.problems == 0, "problems": self.problems, "checks": [asdict(c) for c in self.checks]}


def run(port: int) -> Diagnosis:
    """Every check, in the order doctor shows them."""
    diag = Diagnosis()

    def add(name, ok, detail, fix=None, warn_only=False):
        result = "ok" if ok is True else "warn" if warn_only or ok is None else "fail"
        diag.checks.append(Check(name, result, detail, fix if result != "ok" else None))

    add("python", sys.version_info >= (3, 11), platform.python_version())

    proj = project.load()
    add("project", True, str(proj.path) if proj else "none (no awsemu.toml here or above)")

    binary = runtime.binary_command(runtime.default_binary())
    if binary:
        out = _run_quiet([*binary, "-v"])
        shown = " ".join(binary)
        add("aws-emulator", True, f"{shown}  {out.splitlines()[0] if out else ''}".strip())
    else:
        add(
            "aws-emulator",
            None,
            "binary not on PATH",
            "Linux: awsemu install (or the .rpm/.deb package); macOS/Windows: use Docker",
        )

    from . import updates

    installed = fidelity.installed_version() if binary else None
    newest = updates.latest()
    if installed:
        if updates.older(installed, updates.MIN_EMULATOR):
            add(
                "emulator support",
                False,
                f"{installed} is older than {updates.MIN_EMULATOR}, the oldest release this awsemu is tested with",
                "awsemu install latest",
            )
        elif newest.emulator and updates.older(installed, newest.emulator):
            add(
                "emulator support",
                None,
                f"{installed} (supported from {updates.MIN_EMULATOR}); {newest.emulator} is out",
                "awsemu install latest",
            )
        else:
            add(
                "emulator support",
                True,
                f"{installed}, the latest (supported from {updates.MIN_EMULATOR})"
                if newest.emulator
                else f"{installed} (supported from {updates.MIN_EMULATOR})",
            )
    if newest.awsemu and updates.older(__version__, newest.awsemu):
        add("awsemu", None, f"{__version__}; {newest.awsemu} is out", f"see {_meta.REPO_URL}/releases")
    else:
        add("awsemu", True, __version__ + (", the latest" if newest.awsemu else ""))

    pinned = proj.emulator_version if proj else None
    if pinned and binary:
        mismatch = fidelity.pin_mismatch()
        add(
            "emulator version",
            None if mismatch else True,
            f"project pins {pinned}, installed {mismatch[1]}" if mismatch else f"{pinned}, as pinned",
            f"awsemu install {pinned}",
        )

    if runtime.docker_available():
        image_name = (
            proj.image
            if proj and proj.image
            else (f"{runtime.DEFAULT_IMAGE}:{pinned}" if pinned else runtime.DEFAULT_IMAGE)
        )
        has_image = runtime.docker_image_exists(image_name)
        add("docker", True, "found")
        add(
            "docker image",
            has_image or None,
            f"'{image_name}' {'found' if has_image else 'not built'}",
            f"awsemu install --docker{f' {pinned}' if pinned else ''}",
        )
    else:
        add("docker", None, "not found", "only needed if you don't use the native binary")

    if not binary and not runtime.docker_available():
        add(
            "emulator runtime",
            False,
            "neither the aws-emulator binary nor Docker is available",
            "install the Linux package, set AWSEMU_BINARY, or install Docker",
        )

    aws = shutil.which("aws")
    if aws:
        version = _run_quiet(["aws", "--version"])
        add("aws cli", True, version.split()[0] if version else aws)
    else:
        add("aws cli", None, "not found", "optional; needed for 'awsemu aws ...'")

    try:
        import boto3

        add("boto3", True, getattr(boto3, "__version__", "installed"))
    except ImportError:
        add("boto3", False, "not installed", "pip install boto3")

    has_rich = importlib.util.find_spec("rich") is not None
    add("rich", has_rich or None, "installed" if has_rich else "not installed (plain output)", "pip install rich")

    h = health.check(port)
    add(f"emulator :{port}", h.healthy or None, h.detail, None if h.healthy else f"awsemu --port {port} start")

    real = [v for v in envvars.REAL_CREDENTIAL_VARS if os.environ.get(v)]
    if real:
        add(
            "shell creds",
            None,
            f"{', '.join(real)} set in this shell",
            "awsemu env/exec/aws unset them for you; your own scripts must too",
        )

    endpoint = os.environ.get("AWS_ENDPOINT_URL")
    if endpoint and not any(h in endpoint for h in ("127.0.0.1", "localhost", "[::1]")):
        add("endpoint", None, f"AWS_ENDPOINT_URL={endpoint}", "not the emulator: unset it, or use awsemu exec")

    from . import traps

    for finding in traps.all_findings(port):
        add(finding.check, None, finding.detail, finding.fix)

    tele = settings.telemetry_enabled()
    env_tele = os.environ.get("EMULATOR_TELEMETRY")
    detail = (
        f"EMULATOR_TELEMETRY={env_tele}"
        if env_tele
        else ("default (on)" if tele is None else ("on" if tele else "off") + f" in {emulator_settings_file()}")
    )
    add("telemetry", True, detail)

    return diag


def _run_quiet(cmd: list[str]) -> str:
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
        return result.stdout.strip() or result.stderr.strip()
    except (OSError, subprocess.TimeoutExpired):
        return ""
