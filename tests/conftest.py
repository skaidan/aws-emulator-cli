import os
import socket
import stat
import sys
from pathlib import Path

import pytest
from click.testing import CliRunner

pytest_plugins = ["pytester"]

FAKE = Path(__file__).with_name("fake_emulator.py")


@pytest.fixture(autouse=True)
def isolated_home(tmp_path, monkeypatch):
    """Every test gets its own HOME, so ~/.aws/emulator is a temp folder."""
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("USERPROFILE", str(home))
    for var in (
        "AWSEMU_HOME",
        "AWSEMU_PORT",
        "AWSEMU_BINARY",
        "AWSEMU_CONFIG",
        "EMULATOR_CONFIG",
        "EMULATOR_TELEMETRY",
        "AWS_PROFILE",
        "AWS_ACCESS_KEY_ID",
        "AWS_SECRET_ACCESS_KEY",
    ):
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


@pytest.fixture
def running(isolated_home):
    """The files of an emulator on port 9297, as if one were running."""
    from awsemu.paths import InstanceFiles

    files = InstanceFiles(9297)
    files.dir.mkdir(parents=True)
    files.ca.write_text("cert")
    return files


@pytest.fixture
def cached(isolated_home, monkeypatch):
    """The release scores and manifest of tests/test_check.py in the fidelity cache, no network."""
    import gzip
    import json

    from awsemu import fidelity as fid
    from tests.test_check import MANIFEST, SCORES

    d = fid.cache_dir()
    d.mkdir(parents=True)
    (d / "v1.0.385.json.gz").write_bytes(gzip.compress(json.dumps(SCORES).encode()))
    (d / "v1.0.385.release.json").write_text(json.dumps({"suite": "v1.0.0"}))
    (d / "manifest-v1.0.0.jsonl.gz").write_bytes(gzip.compress("\n".join(json.dumps(r) for r in MANIFEST).encode()))
    monkeypatch.setattr(fid, "installed_version", lambda binary=None: "1.0.385")

    def no_network(*a, **k):
        raise AssertionError("should use the cache")

    monkeypatch.setattr(fid, "_get", no_network)


@pytest.fixture
def profile(tmp_path, monkeypatch):
    """An AWS profile 'dev' (eu-west-1), with credentials and an endpoint in the environment that must be ignored."""
    cfg = tmp_path / "config"
    cfg.write_text("[profile dev]\nregion = eu-west-1\naws_access_key_id = AKIDEV\naws_secret_access_key = s\n")
    monkeypatch.setenv("AWS_CONFIG_FILE", str(cfg))
    monkeypatch.setenv("AWS_SHARED_CREDENTIALS_FILE", str(tmp_path / "none"))
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "AKIAENVIRONMENT")  # must not be used
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "x")
    monkeypatch.setenv("AWS_ENDPOINT_URL", "https://127.0.0.1:9")  # must be ignored
    return "dev"
