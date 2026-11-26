"""Run AWS's fidelity tests against the emulator on this machine.

The tests and their runner are AWS's public evaluation suite
(https://github.com/aws/aws-emulator-evaluation-suite). awsemu:

1. fetches the suite at the version your emulator release was scored with (a shallow
   ``git clone``, cached in ``~/.aws/emulator-cli/fidelity/suite/<version>``);
2. prepares its environment with ``uv sync --locked`` (adding the ``checks`` extra the
   first time a selected test needs one of its packages);
3. runs each test like the suite's README says: against **its own, fresh emulator**
   (its own ``HOME`` and port), with the suite's runner, which only accepts a loopback
   endpoint, signs with the keys that emulator minted and drops your AWS credentials;
4. reads each JSON report and compares the verdict with the published score.
"""

from __future__ import annotations

import json
import os
import shutil
import socket
import subprocess
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path

from .paths import cli_root

SUITE_REPO = "https://github.com/aws/aws-emulator-evaluation-suite"
SCRUB = (
    "AWS_ACCESS_KEY_ID",
    "AWS_SECRET_ACCESS_KEY",
    "AWS_SESSION_TOKEN",
    "AWS_PROFILE",
    "AWS_DEFAULT_PROFILE",
    "AWS_ENDPOINT_URL",
    "AWS_CONFIG_FILE",
    "AWS_SHARED_CREDENTIALS_FILE",
    "AWS_CA_BUNDLE",
)


class RunError(Exception):
    def __init__(self, message: str, hint: str | None = None):
        super().__init__(message)
        self.hint = hint


@dataclass
class TestResult:
    check_id: str
    path: str
    verdict: str  # passed | failed | error
    kind: str = ""
    detail: str = ""
    duration_ms: int = 0
    published: str | None = None  # pass | fail | None (not scored)

    @property
    def agrees(self) -> bool | None:
        if self.published is None:
            return None
        return (self.verdict == "passed") == (self.published == "pass")

    def as_dict(self) -> dict:
        return {
            "test": self.check_id,
            "path": self.path,
            "verdict": self.verdict,
            "kind": self.kind,
            "detail": self.detail,
            "duration_ms": self.duration_ms,
            "published": self.published,
            "same_as_published": self.agrees,
        }


@dataclass
class Suite:
    root: Path
    ref: str
    manifest: list[dict] = field(default_factory=list)


def _env(extra: dict[str, str] | None = None) -> dict[str, str]:
    env = {k: v for k, v in os.environ.items() if k not in SCRUB and not k.startswith("AWS_ENDPOINT_URL_")}
    env.update(extra or {})
    return env


def suite(ref: str, refresh: bool = False) -> Suite:
    root = cli_root() / "fidelity" / "suite" / ref
    if refresh and ref == "main" and root.exists():
        shutil.rmtree(root)
    if not (root / "manifest.jsonl").exists():
        git = shutil.which("git")
        if not git:
            raise RunError(
                "running the fidelity tests needs git, to fetch AWS's evaluation suite",
                "Install git, or clone the suite yourself and pass --suite PATH.",
            )
        root.parent.mkdir(parents=True, exist_ok=True)
        tmp = root.with_name(ref + ".partial")
        shutil.rmtree(tmp, ignore_errors=True)
        done = subprocess.run(
            [git, "clone", "-q", "--depth", "1", "--branch", ref, SUITE_REPO, str(tmp)],
            capture_output=True,
            text=True,
            env={**_env(), "GIT_LFS_SKIP_SMUDGE": "1"},
        )
        if done.returncode != 0:
            shutil.rmtree(tmp, ignore_errors=True)
            raise RunError(f"couldn't fetch the evaluation suite {ref}: {done.stderr.strip()[-300:]}")
        shutil.rmtree(root, ignore_errors=True)
        tmp.rename(root)
    return local_suite(root, ref)


def local_suite(root: Path, ref: str | None = None) -> Suite:
    manifest = root / "manifest.jsonl"
    if not manifest.exists():
        raise RunError(f"{root} isn't the evaluation suite (no manifest.jsonl)")
    rows = [json.loads(line) for line in manifest.read_text(encoding="utf-8").splitlines() if line.strip()]
    return Suite(root, ref or root.name, rows)


def select(s: Suite, services: list[str], tests: list[str]) -> list[dict]:
    """Manifest rows for SERVICES (a cross-service test counts for each of its services) and --test IDs."""
    rows = []
    wanted = {x.lower() for x in services}
    for row in s.manifest:
        parts = set(row.get("service", "").lower().split("__"))
        if row["check_id"] in tests or (wanted and parts & wanted):
            rows.append(row)
    unknown = [t for t in tests if t not in {r["check_id"] for r in s.manifest}]
    if unknown:
        raise RunError(
            f"no such test in the suite {s.ref}: {', '.join(unknown)}",
            "Test ids look like dynamodb.update-item-...; see 'awsemu fidelity SERVICE --failures'.",
        )
    return rows


def uv() -> str:
    found = shutil.which("uv")
    if not found:
        raise RunError(
            "the fidelity tests run with uv, which isn't installed",
            "Install it: https://docs.astral.sh/uv/getting-started/installation/ (or: pipx install uv)",
        )
    return found


def prepare(s: Suite, paths: list[str], log) -> None:
    """``uv sync``, with the test packages when the selected tests need them."""
    tool = uv()
    marker = s.root / ".awsemu-synced"
    extras_marker = s.root / ".awsemu-synced-checks"
    if not marker.exists():
        log("preparing the suite's environment (uv sync, once)…")
        _sync(tool, s.root, [])
        marker.touch()
    if extras_marker.exists():
        return
    done = subprocess.run(
        [tool, "run", "--locked", "fidelity-tests-runner", "requirements", "--json", *paths],
        cwd=s.root,
        capture_output=True,
        text=True,
        env=_env(),
    )
    try:
        reports = json.loads(done.stdout or "[]")
    except ValueError:
        reports = []
    if any(r.get("missing_python_packages") for r in reports):
        log("installing the packages these tests import (uv sync --extra checks, once)…")
        _sync(tool, s.root, ["--extra", "checks"])
        extras_marker.touch()


def _sync(tool: str, root: Path, extra: list[str]) -> None:
    done = subprocess.run([tool, "sync", "--locked", *extra], cwd=root, capture_output=True, text=True, env=_env())
    if done.returncode != 0:
        raise RunError(f"uv sync failed: {done.stderr.strip()[-500:]}")


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


class Emulator:
    """A fresh emulator for one test: its own HOME and port, stopped afterwards."""

    def __init__(self, command: list[str], telemetry_off: bool = True):
        self.command = command
        self.telemetry_off = telemetry_off

    def __enter__(self):
        self.home = Path(tempfile.mkdtemp(prefix="awsemu-fidelity-"))
        self.port = _free_port()
        args = [*self.command, "-p", str(self.port)]
        if self.telemetry_off:
            args += ["-t", "off"]
        self.log = (self.home / "emulator.log").open("w")
        self.proc = subprocess.Popen(
            args,
            env=_env({"HOME": str(self.home), "USERPROFILE": str(self.home)}),
            stdout=self.log,
            stderr=subprocess.STDOUT,
            stdin=subprocess.DEVNULL,
        )
        creds = self.home / ".aws" / "emulator" / str(self.port) / "ca.pem"
        deadline = time.monotonic() + 60
        while time.monotonic() < deadline:
            if self.proc.poll() is not None:
                raise RunError(
                    f"the emulator exited with code {self.proc.returncode} (log: {self.home / 'emulator.log'})"
                )
            if creds.exists():
                try:
                    with socket.create_connection(("127.0.0.1", self.port), timeout=0.5):
                        return self
                except OSError:
                    pass
            time.sleep(0.2)
        self.__exit__(None, None, None)
        raise RunError("the emulator didn't start within 60 s")

    @property
    def endpoint(self) -> str:
        return f"https://127.0.0.1:{self.port}"

    def __exit__(self, *exc):
        if self.proc.poll() is None:
            self.proc.terminate()
            try:
                self.proc.wait(timeout=15)
            except subprocess.TimeoutExpired:
                self.proc.kill()
                self.proc.wait(timeout=5)
        self.log.close()
        shutil.rmtree(self.home, ignore_errors=True)


def run_one(s: Suite, row: dict, emulator_command: list[str], published: dict[str, str]) -> TestResult:
    tool = uv()
    with Emulator(emulator_command) as emu:
        report = emu.home / "report.json"
        done = subprocess.run(
            [
                tool,
                "run",
                "--locked",
                "fidelity-tests-runner",
                "run",
                row["path"],
                "--endpoint",
                emu.endpoint,
                "--emulator-home",
                str(emu.home),
                "--report",
                str(report),
            ],
            cwd=s.root,
            capture_output=True,
            text=True,
            env=_env(),
            timeout=900,
        )
        try:
            check = json.loads(report.read_text(encoding="utf-8"))["check"]
        except (OSError, ValueError, KeyError):
            check = {
                "verdict": "error",
                "kind": "runner",
                "detail": (done.stderr or done.stdout).strip()[-500:] or f"exit code {done.returncode}",
            }
    return TestResult(
        row["check_id"],
        row["path"],
        check.get("verdict", "error"),
        check.get("kind", ""),
        (check.get("detail") or "").strip(),
        int(check.get("duration_ms") or 0),
        published.get(row["check_id"]),
    )


def published_outcomes(scores: dict) -> dict[str, str]:
    return {
        u["unitId"]: u["outcome"]
        for u in scores.get("units", [])
        if u.get("outcome") in ("pass", "fail") and u.get("unitId")
    }
