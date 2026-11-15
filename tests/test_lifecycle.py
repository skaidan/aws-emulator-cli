"""End-to-end lifecycle tests against tests/fake_emulator.py (no real emulator needed)."""

import json
import os

import pytest

from awsemu import runtime
from awsemu.cli import cli
from awsemu.paths import CliFiles, InstanceFiles

pytest.importorskip("cryptography", reason="the fake emulator needs cryptography")


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

        result = runner.invoke(cli, ["--port", port, "env", "--shell", "bash"])
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


@pytest.mark.skipif(os.name == "nt", reason="uses sh")
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


def test_random_port(runner, fake_binary):
    result = runner.invoke(cli, ["--port", "0", "start", "--native"])
    assert result.exit_code == 0, result.output
    assert "free port" in result.output
    ports = [p for p in os.listdir(InstanceFiles(0).dir.parent) if p.isdigit()]
    assert len(ports) == 1
    port = int(ports[0])
    assert f"https://127.0.0.1:{port}" in result.output
    assert f"--port {port}" in result.output
    try:
        state = runtime.State.load(port)
        assert state is not None and state.port == port
        log = runner.invoke(cli, ["--port", str(port), "logs"])
        assert "emulator server information" in log.output
    finally:
        assert runner.invoke(cli, ["--port", str(port), "stop"]).exit_code == 0


def test_random_port_refused_with_docker(runner, monkeypatch):
    monkeypatch.setattr(runtime, "docker_available", lambda: True)
    result = runner.invoke(cli, ["--port", "0", "start", "--docker"])
    assert result.exit_code == 1 and "Port 0 doesn't work with Docker" in result.output


def test_logs_survive_stop(runner, fake_binary, free_port):
    port = str(free_port)
    assert runner.invoke(cli, ["--port", port, "start", "--native"]).exit_code == 0
    runner.invoke(cli, ["--port", port, "stop"])
    result = runner.invoke(cli, ["--port", port, "logs", "--grep", "shutting"])
    assert result.exit_code == 0, result.output
    assert "shutting down" in result.output
    assert "emulator server information" not in result.output  # --grep filtered it


def test_forced_stop_cleans_files(runner, fake_binary, free_port, monkeypatch):
    monkeypatch.setenv("FAKE_EMULATOR_IGNORE_STOP", "1")
    port = str(free_port)
    assert runner.invoke(cli, ["--port", port, "start", "--native"]).exit_code == 0
    files = InstanceFiles(free_port)
    result = runner.invoke(cli, ["--port", port, "stop", "--timeout", "1"])
    assert result.exit_code == 1 and "stop --force" in result.output
    assert files.ca.exists()  # still running
    result = runner.invoke(cli, ["--port", port, "stop", "--force"])
    assert result.exit_code == 0, result.output
    assert "forced pid" in result.output and "removed files it left behind" in result.output
    assert not files.dir.exists()
    assert runtime.State.load(free_port) is None


def test_stop_removes_stale_files_after_crash(runner, free_port):
    files = InstanceFiles(free_port)
    files.dir.mkdir(parents=True)
    for name in ("config", "ca.pem", "emulator_credentials"):
        (files.dir / name).write_text("stale")
    result = runner.invoke(cli, ["--port", str(free_port), "stop"])
    assert result.exit_code == 0 and "removed stale files" in result.output
    assert not files.dir.exists()


def test_cleanup_leaves_unknown_files(free_port):
    files = InstanceFiles(free_port)
    files.dir.mkdir(parents=True)
    files.ca.write_text("stale")
    (files.dir / "mine.txt").write_text("keep me")
    assert runtime.cleanup_instance_files(free_port) is True
    assert (files.dir / "mine.txt").exists() and not files.ca.exists()


def test_awsemu_binary_env(runner, monkeypatch, free_port):
    import sys
    from pathlib import Path

    fake = Path(__file__).with_name("fake_emulator.py")
    monkeypatch.setenv("PATH", os.path.dirname(sys.executable))
    monkeypatch.setenv("AWSEMU_BINARY", f'"{sys.executable}" "{fake}"')
    assert runtime.resolve_mode("auto") == "native"
    port = str(free_port)
    result = runner.invoke(cli, ["--port", port, "start"])
    assert result.exit_code == 0, result.output
    try:
        assert CliFiles(free_port).log.exists()
    finally:
        runner.invoke(cli, ["--port", port, "stop"])
