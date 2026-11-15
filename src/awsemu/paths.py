"""Where AWS Emulator and this CLI keep their files.

AWS Emulator writes, for every running instance, a folder named after its
port: ``~/.aws/emulator/<port>/`` with ``config``, ``emulator_credentials``
(only when auth is on), ``ca.pem`` and ``truststore.p12``. It removes the folder
contents on a clean stop.

This CLI keeps its own bookkeeping (pid, mode, log file) apart from that, in
``~/.aws/emulator-cli/<port>/``, so we never write into the emulator's folder.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

DEFAULT_PORT = 9297
DEFAULT_HOST = "127.0.0.1"
REGION = "us-east-1"
ACCOUNT_ID = "000000000000"
HEALTH_ROUTE = "/__admin/health"


def home() -> Path:
    return Path(os.path.expanduser("~"))


def emulator_root() -> Path:
    """``~/.aws/emulator`` (``%USERPROFILE%\\.aws\\emulator`` on Windows)."""
    return home() / ".aws" / "emulator"


def cli_root() -> Path:
    override = os.environ.get("AWSEMU_HOME")
    if override:
        return Path(override).expanduser()
    return home() / ".aws" / "emulator-cli"


def emulator_settings_file() -> Path:
    """The emulator's own ``config.toml`` (honours ``EMULATOR_CONFIG``)."""
    override = os.environ.get("EMULATOR_CONFIG")
    if override:
        return Path(override).expanduser()
    return emulator_root() / "config.toml"


def default_port() -> int:
    """``$AWSEMU_PORT``, else the project's ``port`` (awsemu.toml), else 9297."""
    raw = os.environ.get("AWSEMU_PORT")
    if raw:
        try:
            return int(raw)
        except ValueError:
            pass
    from . import project

    try:
        proj = project.load()
    except project.ProjectError:
        return DEFAULT_PORT  # reported by the CLI when it loads the project
    if proj and proj.port:
        return proj.port
    return DEFAULT_PORT


@dataclass(frozen=True)
class InstanceFiles:
    """The files AWS Emulator writes for one port."""

    port: int

    @property
    def dir(self) -> Path:
        return emulator_root() / str(self.port)

    @property
    def config(self) -> Path:
        return self.dir / "config"

    @property
    def credentials(self) -> Path:
        return self.dir / "emulator_credentials"

    @property
    def ca(self) -> Path:
        return self.dir / "ca.pem"

    @property
    def truststore(self) -> Path:
        return self.dir / "truststore.p12"

    @property
    def endpoint_url(self) -> str:
        return f"https://{DEFAULT_HOST}:{self.port}"

    @property
    def health_url(self) -> str:
        return self.endpoint_url + HEALTH_ROUTE

    def exists(self) -> bool:
        return self.ca.exists()

    def auth_enabled(self) -> bool:
        return self.credentials.exists()


@dataclass(frozen=True)
class CliFiles:
    """This CLI's bookkeeping for one port."""

    port: int

    @property
    def dir(self) -> Path:
        return cli_root() / str(self.port)

    @property
    def state(self) -> Path:
        return self.dir / "state.json"

    @property
    def log(self) -> Path:
        return self.dir / "emulator.log"


def known_ports() -> list[int]:
    """Ports that have emulator files or CLI state on disk."""
    ports: set[int] = set()
    for root in (emulator_root(), cli_root()):
        if not root.is_dir():
            continue
        for child in root.iterdir():
            if child.is_dir() and child.name.isdigit():
                ports.add(int(child.name))
    return sorted(ports)
