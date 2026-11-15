"""pytest plugin: an AWS Emulator for your tests.

Installed automatically with awsemu (entry point ``pytest11``). It adds
fixtures and options, and does nothing until a test asks for a fixture::

    def test_upload(aws_emulator):
        s3 = boto3.client("s3")          # already pointed at the emulator
        s3.create_bucket(Bucket="demo")

Fixtures:

- ``aws_emulator`` (session): starts an emulator on a free port (or reuses one
  with ``--awsemu-reuse``), applies the seed, points ``os.environ`` at it, and
  stops it at the end. Returns an :class:`Emulator`.
- ``aws_emulator_fresh`` (function): the same emulator, reset to the seed
  before the test (a restart: slower, but a clean slate).

Settings (command line > ``pytest.ini``/``pyproject`` ini > ``awsemu.toml``):

- ``--awsemu-seed FILE`` / ini ``awsemu_seed``
- ``--awsemu-port N`` / ini ``awsemu_port``: use this port instead of a free one
- ``--awsemu-reuse`` / ini ``awsemu_reuse = true``: use an emulator that's already
  running on the port (``awsemu up``) instead of starting one; it isn't stopped
- ``--awsemu-docker`` / ini ``awsemu_mode = docker``
"""

from __future__ import annotations

import os
import socket
from dataclasses import dataclass, field
from pathlib import Path

import pytest

from . import envvars, health, project, runtime
from .paths import InstanceFiles, default_port


def pytest_addoption(parser):
    group = parser.getgroup("awsemu", "AWS Emulator (awsemu)")
    group.addoption("--awsemu-seed", metavar="FILE", help="Seed applied when the emulator starts.")
    group.addoption("--awsemu-port", type=int, metavar="N", help="Port for the emulator (default: a free one).")
    group.addoption("--awsemu-reuse", action="store_true",
                    help="Use an emulator already running on the port; don't start or stop one.")
    group.addoption("--awsemu-docker", action="store_true", help="Run the emulator in Docker.")
    parser.addini("awsemu_seed", "Seed file for the aws_emulator fixture (relative to rootdir).")
    parser.addini("awsemu_port", "Port for the aws_emulator fixture.")
    parser.addini("awsemu_reuse", "Reuse a running emulator (true/false).", default="false")
    parser.addini("awsemu_mode", "auto | native | docker", default="")


def pytest_configure(config):
    config.addinivalue_line("markers", "awsemu: test uses the AWS Emulator (informational)")


@dataclass
class Emulator:
    """Handle returned by the ``aws_emulator`` fixture."""

    port: int
    seed_path: Path | None = None
    started_here: bool = False
    mode: str = "auto"
    _seed: object = field(default=None, repr=False)

    @property
    def endpoint_url(self) -> str:
        return InstanceFiles(self.port).endpoint_url

    @property
    def env(self) -> dict[str, str]:
        """The variables the fixture put in ``os.environ``."""
        return envvars.emulator_env(self.port, _project_sdk())

    def client(self, service: str):
        """A boto3 client for ``service`` wired to this emulator."""
        from .clients import client

        return client(service, self.port)

    def apply_seed(self, path: str | Path | None = None) -> None:
        """Apply a seed (default: the fixture's seed). Fails the test on errors."""
        from .commands.seed import apply_seed

        seed = _load_seed(Path(path)) if path else self._seed
        if seed is None:
            return
        report = apply_seed(seed, self.port)
        if report.failures:
            rows = "\n".join(" ".join(str(c) for c in r) for r in report.rows if "failed" in str(r[2]))
            pytest.fail(f"awsemu: seed {seed.source} failed:\n{rows}", pytrace=False)

    def reset(self) -> None:
        """Restart the emulator (empty state) and re-apply the seed."""
        if not self.started_here:
            pytest.fail("awsemu: reset() needs an emulator started by the fixture "
                        "(not --awsemu-reuse)", pytrace=False)
        runtime.stop(self.port)
        _wait_port_closed(self.port)
        _start(self.port, self.mode)
        self.apply_seed()


def _project_sdk() -> list[str]:
    proj = project.load()
    return list(proj.sdk) if proj else []


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _wait_port_closed(port: int, tries: int = 25) -> None:
    import time

    for _ in range(tries):
        if not health.port_open(port):
            return
        time.sleep(0.2)


def _load_seed(path: Path):
    from . import seed as seedlib

    try:
        return seedlib.load_file(path)
    except seedlib.SeedError as exc:
        pytest.fail(f"awsemu: invalid seed\n{exc}", pytrace=False)


def _start(port: int, mode: str) -> None:
    proj = project.load()
    opts = runtime.StartOptions(
        port=port,
        mode=mode,
        auth=proj.auth if proj and proj.auth is not None else True,
        telemetry=proj.telemetry if proj and proj.telemetry is not None else False,
        # Safety net: never leave an emulator behind if pytest is killed.
        idle_timeout=proj.idle_timeout if proj and proj.idle_timeout else 1800,
        image=proj.image if proj and proj.image else runtime.DEFAULT_IMAGE,
        memory=proj.memory if proj and proj.memory else "2g",
    )
    try:
        state, status = runtime.start(opts, wait=60)
    except runtime.RuntimeErrorWithHint as exc:
        pytest.fail(f"awsemu: couldn't start the emulator: {exc}" + (f"\n{exc.hint}" if exc.hint else ""),
                    pytrace=False)
    if not status.healthy:
        tail = "".join(runtime.tail(Path(state.log), 15)) if state.log else ""
        pytest.fail(f"awsemu: the emulator didn't become healthy: {status.detail}\n{tail}", pytrace=False)


def _setting(config, option: str, ini: str):
    value = config.getoption(option)
    if value not in (None, False):
        return value
    raw = config.getini(ini)
    return raw if raw not in ("", None) else None


@pytest.fixture(scope="session")
def aws_emulator(request):
    config = request.config
    proj = project.load()

    reuse = bool(config.getoption("--awsemu-reuse")) or str(config.getini("awsemu_reuse")).lower() in ("1", "true", "yes")
    port_setting = _setting(config, "--awsemu-port", "awsemu_port")
    if config.getoption("--awsemu-docker"):
        mode = "docker"
    else:
        mode = config.getini("awsemu_mode") or (proj.mode if proj and proj.mode else "auto")

    seed_setting = _setting(config, "--awsemu-seed", "awsemu_seed")
    if seed_setting:
        seed_path = Path(seed_setting)
        if not seed_path.is_absolute():
            seed_path = Path(config.rootpath) / seed_path
    else:
        seed_path = proj.seed if proj and proj.seed else None
    seed = _load_seed(seed_path) if seed_path else None  # validate before starting anything

    if reuse:
        port = int(port_setting) if port_setting else default_port()
        h = health.check(port)
        if not h.healthy:
            pytest.fail(f"awsemu: --awsemu-reuse but no healthy emulator on port {port} ({h.detail}). "
                        "Start one with 'awsemu up'.", pytrace=False)
        emu = Emulator(port=port, seed_path=seed_path, started_here=False, mode=mode, _seed=seed)
    else:
        port = int(port_setting) if port_setting else _free_port()
        _start(port, mode)
        emu = Emulator(port=port, seed_path=seed_path, started_here=True, mode=mode, _seed=seed)

    saved = dict(os.environ)
    # Compute first: paths depend on HOME, which must still be in os.environ.
    new_env = envvars.child_env(port, base=saved, extras=_project_sdk())
    os.environ.clear()
    os.environ.update(new_env)
    try:
        emu.apply_seed()
        yield emu
    finally:
        os.environ.clear()
        os.environ.update(saved)
        if emu.started_here:
            try:
                runtime.stop(port)
            except runtime.RuntimeErrorWithHint:
                runtime.stop(port, force=True)


@pytest.fixture
def aws_emulator_fresh(aws_emulator):
    """The session emulator, restarted and re-seeded before this test."""
    aws_emulator.reset()
    return aws_emulator
