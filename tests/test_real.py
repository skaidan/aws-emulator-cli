"""Tests against the REAL AWS Emulator.

Skipped unless ``AWSEMU_REAL_TESTS=1``. They need the ``aws-emulator`` binary on
PATH (or ``AWSEMU_BINARY``) and boto3. Run them with:

    AWSEMU_REAL_TESTS=1 pytest -m real -v

One emulator is started for the whole module on a free port and stopped at the end.
"""

import json
import os
import socket
import sys

import pytest
from click.testing import CliRunner

from awsemu import runtime
from awsemu.cli import cli
from awsemu.paths import ACCOUNT_ID, InstanceFiles

pytestmark = [
    pytest.mark.real,
    pytest.mark.skipif(os.environ.get("AWSEMU_REAL_TESTS") != "1",
                       reason="set AWSEMU_REAL_TESTS=1 to run against the real emulator"),
]


@pytest.fixture(scope="module")
def real_home(tmp_path_factory):
    home = tmp_path_factory.mktemp("real-home")
    return home


@pytest.fixture(autouse=True)
def isolated_home(real_home, monkeypatch):
    """Override conftest's per-test HOME: the emulator writes its files once, at start."""
    monkeypatch.setenv("HOME", str(real_home))
    monkeypatch.setenv("USERPROFILE", str(real_home))
    monkeypatch.setenv("AWSEMU_PLAIN", "1")
    for var in ("AWS_PROFILE", "AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY", "AWS_SESSION_TOKEN"):
        monkeypatch.delenv(var, raising=False)
    from awsemu import ui

    ui.set_plain(True)
    return real_home


@pytest.fixture(scope="module")
def emu(real_home):
    pytest.importorskip("boto3")
    if not runtime.native_available():
        pytest.skip("aws-emulator binary not found")
    with pytest.MonkeyPatch.context() as mp:
        mp.setenv("HOME", str(real_home))
        mp.setenv("USERPROFILE", str(real_home))
        with socket.socket() as s:
            s.bind(("127.0.0.1", 0))
            port = s.getsockname()[1]
        result = CliRunner().invoke(cli, ["--port", str(port), "start", "--native",
                                          "--no-telemetry", "--idle-timeout", "900", "--wait", "60"])
        assert result.exit_code == 0, result.output
        yield port
        result = CliRunner().invoke(cli, ["--port", str(port), "stop"])
        assert result.exit_code == 0, result.output
        assert not InstanceFiles(port).ca.exists(), "emulator should delete its files on stop"


def run(port, *args, ok=True):
    result = CliRunner().invoke(cli, ["--port", str(port), *args])
    if ok:
        assert result.exit_code == 0, result.output
    return result


def test_status_and_files(emu):
    info = json.loads(run(emu, "status", "--json").output)
    assert info["status"] == "healthy" and info["auth"] is True
    files = InstanceFiles(emu)
    assert files.ca.exists() and files.config.exists() and files.credentials.exists()


def test_startup_line_in_log(emu):
    out = run(emu, "logs", "-n", "200").output
    assert "emulator server information" in out
    assert f"endpoint_url=https://127.0.0.1:{emu}" in out


def test_whoami(emu):
    out = run(emu, "whoami").output
    assert ACCOUNT_ID in out and "Talking to AWS Emulator" in out


def test_s3_roundtrip(emu, tmp_path):
    src = tmp_path / "hola.txt"
    src.write_text("hola desde el emulador\n")
    run(emu, "s3", "mb", "awsemu-real")
    run(emu, "s3", "put", str(src), "awsemu-real/docs/")
    assert "docs/hola.txt" in run(emu, "s3", "ls", "awsemu-real", "-r").output
    assert run(emu, "s3", "cat", "awsemu-real/docs/hola.txt").output == "hola desde el emulador\n"
    dest = tmp_path / "copia.txt"
    run(emu, "s3", "get", "awsemu-real/docs/hola.txt", str(dest))
    assert dest.read_text() == src.read_text()
    assert run(emu, "s3", "presign", "awsemu-real/docs/hola.txt").output.startswith(
        f"https://127.0.0.1:{emu}/awsemu-real/docs/hola.txt?")
    run(emu, "s3", "rb", "awsemu-real", "--force", "--yes")
    assert "awsemu-real" not in run(emu, "s3", "ls").output


def test_sqs_roundtrip(emu):
    run(emu, "sqs", "create", "awsemu-dlq")
    run(emu, "sqs", "create", "awsemu-jobs", "--dlq", "awsemu-dlq", "--visibility-timeout", "5")
    run(emu, "sqs", "send", "awsemu-jobs", '{"job": 1}', "-a", "kind=test")
    assert "awsemu-jobs" in run(emu, "sqs", "ls").output
    msgs = json.loads(run(emu, "sqs", "receive", "awsemu-jobs", "--delete", "--json").output)
    assert len(msgs) == 1 and json.loads(msgs[0]["Body"]) == {"job": 1}
    assert msgs[0]["MessageAttributes"]["kind"]["StringValue"] == "test"
    assert "RedrivePolicy" in run(emu, "sqs", "info", "awsemu-jobs").output
    run(emu, "sqs", "rm", "awsemu-jobs", "--yes")
    run(emu, "sqs", "rm", "awsemu-dlq", "--yes")


def test_dynamodb_roundtrip(emu):
    run(emu, "ddb", "create", "awsemu-users", "--pk", "id", "--sk", "created:N")
    run(emu, "ddb", "put", "awsemu-users",
        '[{"id": "u1", "created": 1, "name": "Ana", "tags": ["a"]},'
        ' {"id": "u2", "created": 2, "name": "Luis", "score": 9.5}]')
    item = json.loads(run(emu, "ddb", "get", "awsemu-users", '{"id": "u2", "created": 2}').output)
    assert item == {"id": "u2", "created": 2, "name": "Luis", "score": 9.5}
    rows = json.loads(run(emu, "ddb", "scan", "awsemu-users", "--json").output)
    assert {r["id"] for r in rows} == {"u1", "u2"}
    run(emu, "ddb", "delete", "awsemu-users", '{"id": "u1", "created": 1}')
    assert run(emu, "ddb", "get", "awsemu-users", '{"id": "u1", "created": 1}', ok=False).exit_code == 1
    run(emu, "ddb", "drop", "awsemu-users", "--yes")


def test_overview_reports_every_service(emu):
    run(emu, "s3", "mb", "awsemu-overview")
    data = json.loads(run(emu, "overview", "--json").output)
    assert "awsemu-overview" in data["s3"]
    errors = {k: v for k, v in data.items() if isinstance(v, dict) and "error" in v}
    # Not a failure (fidelity varies by release) but worth seeing in the CI log.
    if errors:
        print("overview errors:", json.dumps(errors, indent=2))
    run(emu, "s3", "rb", "awsemu-overview")


def test_exec_environment_reaches_emulator(emu):
    """The variables from 'awsemu env' must work for plain boto3 code."""
    code = ("import boto3; i = boto3.client('sts').get_caller_identity(); "
            f"assert i['Account'] == '{ACCOUNT_ID}', i")
    env = os.environ.copy()
    env["AWS_ACCESS_KEY_ID"] = "AKIAREALKEYSHOULDBEDROPPED"
    result = CliRunner().invoke(cli, ["--port", str(emu), "exec", "--", sys.executable, "-c", code],
                                env=env)
    assert result.exit_code == 0, result.output


def test_restart_resets_state(emu):
    run(emu, "s3", "mb", "awsemu-gone")
    run(emu, "restart", "--native", "--no-telemetry", "--idle-timeout", "900", "--wait", "60")
    assert "awsemu-gone" not in run(emu, "s3", "ls").output


def test_random_port_with_real_binary(emu):
    """--port 0 relies on the real startup line format (message under "fields")."""
    result = run(0, "start", "--native", "--no-telemetry", "--idle-timeout", "300", "--wait", "60")
    ports = [int(p) for p in os.listdir(InstanceFiles(0).dir.parent) if p.isdigit() and int(p) != emu]
    assert len(ports) == 1, (ports, result.output)
    port = ports[0]
    try:
        assert f"https://127.0.0.1:{port}" in result.output
        assert ACCOUNT_ID in run(port, "whoami").output
    finally:
        run(port, "stop")


def test_sns_to_sqs_end_to_end(emu):
    run(emu, "sns", "create", "awsemu-orders")
    run(emu, "sqs", "create", "awsemu-order-events")
    run(emu, "sns", "subscribe", "awsemu-orders", "--to-sqs", "awsemu-order-events", "--raw")
    assert "awsemu-order-events" in run(emu, "sns", "ls").output
    run(emu, "sns", "publish", "awsemu-orders", '{"order": 42}', "-a", "kind=created")
    msgs = json.loads(run(emu, "sqs", "receive", "awsemu-order-events", "--wait", "5",
                          "--delete", "--json").output)
    assert len(msgs) == 1, msgs
    assert json.loads(msgs[0]["Body"]) == {"order": 42}  # raw delivery: no SNS envelope
    run(emu, "sns", "rm", "awsemu-orders", "--yes")
    run(emu, "sqs", "rm", "awsemu-order-events", "--yes")


def test_lambda_deploy_invoke(emu, tmp_path):
    src = tmp_path / "fn"
    src.mkdir()
    (src / "app.py").write_text(
        "import os\n"
        "def handler(event, context):\n"
        "    print('hello from the emulator')\n"
        "    return {'greeting': f\"hola {event.get('name', 'nadie')}\", 'stage': os.environ.get('STAGE')}\n")
    out = run(emu, "lambda", "deploy", "awsemu-hello", str(src), "-e", "STAGE=local").output
    assert "created awsemu-hello" in out and "app.handler" in out
    assert "awsemu-hello" in run(emu, "lambda", "ls").output
    assert "STAGE=local" in run(emu, "lambda", "info", "awsemu-hello").output

    result = run(emu, "lambda", "invoke", "awsemu-hello", '{"name": "Ana"}', "--raw")
    assert json.loads(result.output) == {"greeting": "hola Ana", "stage": "local"}

    # Redeploy updates in place.
    (src / "app.py").write_text("def handler(event, context):\n    return {'v': 2}\n")
    assert "updated awsemu-hello" in run(emu, "lambda", "deploy", "awsemu-hello", str(src)).output
    assert json.loads(run(emu, "lambda", "invoke", "awsemu-hello", "--raw").output) == {"v": 2}
    run(emu, "lambda", "rm", "awsemu-hello", "--yes")
