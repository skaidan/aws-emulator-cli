"""What works without boto3/botocore and cryptography (a minimal install, docs/getting-started.md).

The emulator's lifecycle and the environment for your code don't need them; commands that
talk to AWS APIs or run the proxy say what to install."""

import importlib.abc
import json
import sys

import pytest

from awsemu.cli import cli

HEAVY = ("boto3", "botocore", "s3transfer", "cryptography")


class Block(importlib.abc.MetaPathFinder):
    def find_spec(self, name, path=None, target=None):
        if name.split(".")[0] in HEAVY:
            raise ModuleNotFoundError(f"No module named {name!r} (blocked by the test)", name=name)
        return None


@pytest.fixture
def without_heavy(monkeypatch):
    for name in list(sys.modules):
        if name.split(".")[0] in HEAVY:
            monkeypatch.delitem(sys.modules, name)
    blocker = Block()
    sys.meta_path.insert(0, blocker)
    yield
    sys.meta_path.remove(blocker)


def test_lifecycle_and_environment_need_neither(runner, fake_binary, free_port, without_heavy):
    port = str(free_port)
    started = runner.invoke(cli, ["--port", port, "start", "--wait", "20"])
    assert started.exit_code == 0, started.output
    try:
        assert json.loads(runner.invoke(cli, ["--port", port, "status", "--json"]).output)["status"] == "healthy"
        env = runner.invoke(cli, ["--port", port, "env", "--shell", "dotenv"])
        assert env.exit_code == 0 and f"AWS_ENDPOINT_URL=https://127.0.0.1:{port}" in env.output
        code = "import os; print(os.environ['AWS_ENDPOINT_URL'])"
        ran = runner.invoke(cli, ["--port", port, "exec", "--", sys.executable, "-c", code])
        assert ran.exit_code == 0, ran.output
        assert runner.invoke(cli, ["--port", port, "logs", "-n", "5"]).exit_code == 0
        doctor = json.loads(runner.invoke(cli, ["--port", port, "doctor", "--json"]).output)
        boto = next(c for c in doctor["checks"] if c["check"] == "boto3")
        assert boto["result"] == "fail" and boto["fix"]  # says what to install
        assert runner.invoke(cli, ["--port", port, "compose"]).exit_code == 0
    finally:
        assert runner.invoke(cli, ["--port", port, "stop"]).exit_code == 0
    assert "boto3" not in sys.modules and "cryptography" not in sys.modules


def test_commands_that_need_them_say_so(runner, running, without_heavy):
    result = runner.invoke(cli, ["s3", "ls"])
    assert result.exit_code == 1 and "boto3" in result.output and "pip install" in result.output
