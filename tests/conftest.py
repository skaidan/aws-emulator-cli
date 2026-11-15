pytest_plugins = ["pytester"]

import os
import socket
import stat
import sys
from pathlib import Path

import pytest
from click.testing import CliRunner

FAKE = Path(__file__).with_name("fake_emulator.py")


@pytest.fixture(autouse=True)
def isolated_home(tmp_path, monkeypatch):
    """Every test gets its own HOME, so ~/.aws/emulator is a temp folder."""
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("USERPROFILE", str(home))
    for var in ("AWSEMU_HOME", "AWSEMU_PORT", "AWSEMU_BINARY", "AWSEMU_CONFIG", "EMULATOR_CONFIG", "EMULATOR_TELEMETRY",
                "AWS_PROFILE", "AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY"):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setenv("AWSEMU_PLAIN", "1")
    from awsemu import ui

    ui.set_plain(True)
    return home


@pytest.fixture
def runner():
    return CliRunner()


@pytest.fixture
def free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture
def fake_binary(tmp_path, monkeypatch):
    """Make tests/fake_emulator.py the 'aws-emulator' that awsemu runs.

    On Linux/macOS it is a wrapper script found on PATH (the normal lookup);
    on Windows it is set through AWSEMU_BINARY.
    """
    if os.name == "nt":
        monkeypatch.setenv("AWSEMU_BINARY", f'"{sys.executable}" "{FAKE}"')
        return FAKE
    bindir = tmp_path / "bin"
    bindir.mkdir()
    exe = bindir / "aws-emulator"
    exe.write_text(f'#!/bin/sh\nexec "{sys.executable}" "{FAKE}" "$@"\n')
    exe.chmod(exe.stat().st_mode | stat.S_IEXEC)
    monkeypatch.setenv("PATH", f"{bindir}{os.pathsep}{os.environ.get('PATH', '')}")
    return exe
