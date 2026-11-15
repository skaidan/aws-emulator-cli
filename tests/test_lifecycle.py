"""End-to-end lifecycle tests against tests/fake_emulator.py (no real emulator needed)."""

import json
import shutil

import pytest

from awsemu import runtime
from awsemu.cli import cli
from awsemu.paths import InstanceFiles

pytestmark = pytest.mark.skipif(shutil.which("openssl") is None, reason="needs openssl")


def test_start_status_logs_stop(runner, fake_binary, free_port):
    port = str(free_port)

    result = runner.invoke(cli, ["--port", port, "start", "--native", "--wait", "20"])
    assert result.exit_code == 0, result.output
    assert f"AWS Emulator is up at https://127.0.0.1:{port}" in result.output
    assert "--port" in result.output  # next steps mention the non-default port
    files = InstanceFiles(free_port)
    assert files.ca.exists() and files.credentials.exists()

    try:
        result = runner.invoke(cli, ["--port", port, "status", "--json"])
        info = json.loads(result.output)
        assert info["status"] == "healthy" and info["mode"] == "native" and info["auth"] is True

        result = runner.invoke(cli, ["--port", port, "status"])
        assert result.exit_code == 0 and "healthy" in result.output

        result = runner.invoke(cli, ["--port", port, "logs", "-n", "10"])
        assert "emulator server information" in result.output
        assert "endpoint_url=https://127.0.0.1" in result.output

        # Starting twice on the same port is refused with a hint.
        result = runner.invoke(cli, ["--port", port, "start", "--native"])
        assert result.exit_code == 1 and "already listening" in result.output

        result = runner.invoke(cli, ["--port", port, "env"])
        assert f"export AWS_ENDPOINT_URL=https://127.0.0.1:{port}" in result.output
    finally:
        result = runner.invoke(cli, ["--port", port, "stop"])
    assert result.exit_code == 0, result.output
    assert "stopped pid" in result.output
    assert not files.ca.exists()  # emulator cleaned up after SIGTERM

    result = runner.invoke(cli, ["--port", port, "status"])
    assert result.exit_code == 3 and "stopped" in result.output


def test_restart_resets(runner, fake_binary, free_port):
    port = str(free_port)
    assert runner.invoke(cli, ["--port", port, "start", "--native", "--no-auth"]).exit_code == 0
    try:
        first = runtime.State.load(free_port).pid
        assert not InstanceFiles(free_port).credentials.exists()  # --no-auth
        result = runner.invoke(cli, ["--port", port, "reset", "--no-auth"])
        assert result.exit_code == 0, result.output
        assert runtime.State.load(free_port).pid != first
    finally:
        runner.invoke(cli, ["--port", port, "stop"])


def test_crash_on_start_is_reported(runner, fake_binary, free_port, monkeypatch):
    monkeypatch.setenv("FAKE_EMULATOR_CRASH", "1")
    result = runner.invoke(cli, ["--port", str(free_port), "start", "--native", "--wait", "5"])
    assert result.exit_code == 1
    assert "exited with code 1" in result.output
    assert "boom" in result.output  # log tail shown
    assert runtime.State.load(free_port) is None


def test_stop_when_not_running(runner, free_port):
    result = runner.invoke(cli, ["--port", str(free_port), "stop"])
    assert result.exit_code == 0 and "not running" in result.output


def test_exec_requires_running_emulator(runner, free_port):
    result = runner.invoke(cli, ["--port", str(free_port), "exec", "--", "true"])
    assert result.exit_code == 1 and "awsemu --port" in result.output


def test_exec_passes_environment(runner, fake_binary, free_port, tmp_path):
    port = str(free_port)
    assert runner.invoke(cli, ["--port", port, "start", "--native"]).exit_code == 0
    try:
        out = tmp_path / "env.txt"
        result = runner.invoke(cli, ["--port", port, "exec", "--", "sh", "-c",
                                     f"env > {out}"])
        assert result.exit_code == 0, result.output
        text = out.read_text()
        assert f"AWS_ENDPOINT_URL=https://127.0.0.1:{port}" in text
        assert "AWS_ACCESS_KEY_ID" not in text
    finally:
        runner.invoke(cli, ["--port", port, "stop"])


def test_config_telemetry(runner, isolated_home):
    assert "on (default)" in runner.invoke(cli, ["config", "telemetry"]).output
    result = runner.invoke(cli, ["config", "telemetry", "off"])
    assert result.exit_code == 0
    assert (isolated_home / ".aws" / "emulator" / "config.toml").read_text() == \
        "[telemetry]\nenabled = false\n"
    assert "telemetry: off" in runner.invoke(cli, ["config", "telemetry"]).output


def test_aliases_and_prefixes(runner, free_port):
    result = runner.invoke(cli, ["--port", str(free_port), "ps"])
    assert "stopped" in result.output
    result = runner.invoke(cli, ["--port", str(free_port), "stat"])
    assert "stopped" in result.output
    result = runner.invoke(cli, ["st"])
    assert "ambiguous" in result.output
