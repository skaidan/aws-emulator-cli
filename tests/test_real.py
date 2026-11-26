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
from awsemu.clients import client
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
    src = tmp_path / "hello.txt"
    src.write_text("hello from the emulator\n")
    run(emu, "s3", "mb", "awsemu-real")
    run(emu, "s3", "put", str(src), "awsemu-real/docs/")
    assert "docs/hello.txt" in run(emu, "s3", "ls", "awsemu-real", "-r").output
    assert run(emu, "s3", "cat", "awsemu-real/docs/hello.txt").output == "hello from the emulator\n"
    dest = tmp_path / "copia.txt"
    run(emu, "s3", "get", "awsemu-real/docs/hello.txt", str(dest))
    assert dest.read_text() == src.read_text()
    assert run(emu, "s3", "presign", "awsemu-real/docs/hello.txt").output.startswith(
        f"https://127.0.0.1:{emu}/awsemu-real/docs/hello.txt?")
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
    assert "awsemu-overview" in data["s3"]["items"]
    errors = {k: v["error"] for k, v in data.items() if v["error"]}
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
        "    return {'greeting': f\"hello {event.get('name', 'nobody')}\", 'stage': os.environ.get('STAGE')}\n")
    out = run(emu, "lambda", "deploy", "awsemu-hello", str(src), "-e", "STAGE=local").output
    assert "created awsemu-hello" in out and "app.handler" in out
    assert "awsemu-hello" in run(emu, "lambda", "ls").output
    assert "STAGE=local" in run(emu, "lambda", "info", "awsemu-hello").output

    result = run(emu, "lambda", "invoke", "awsemu-hello", '{"name": "Ana"}', "--raw")
    assert json.loads(result.output) == {"greeting": "hello Ana", "stage": "local"}

    # Redeploy updates in place.
    (src / "app.py").write_text("def handler(event, context):\n    return {'v': 2}\n")
    assert "updated awsemu-hello" in run(emu, "lambda", "deploy", "awsemu-hello", str(src)).output
    assert json.loads(run(emu, "lambda", "invoke", "awsemu-hello", "--raw").output) == {"v": 2}
    run(emu, "lambda", "rm", "awsemu-hello", "--yes")


def test_secrets_and_ssm(emu):
    run(emu, "secrets", "put", "awsemu/db", '{"user": "app", "pass": "x"}', "--description", "db")
    run(emu, "secrets", "put", "awsemu/db", '{"user": "app", "pass": "y"}')
    assert json.loads(run(emu, "secrets", "get", "awsemu/db", "--raw").output) == {"user": "app", "pass": "y"}
    assert "awsemu/db" in run(emu, "secrets", "ls").output
    info = run(emu, "secrets", "info", "awsemu/db").output
    assert "AWSCURRENT" in info and "AWSPREVIOUS" in info
    run(emu, "secrets", "rm", "awsemu/db", "--now", "--yes")

    run(emu, "ssm", "put", "/demo/app/host", "localhost")
    run(emu, "ssm", "put", "/demo/app/key", "s3cr3t", "--secure")
    assert run(emu, "ssm", "get", "/demo/app/key").output.strip() == "s3cr3t"
    listing = run(emu, "ssm", "ls", "/demo/app", "--values").output
    assert "localhost" in listing and "s3cr3t" not in listing
    run(emu, "ssm", "rm", "/demo/app/host", "/demo/app/key")


def test_eventbridge_to_sqs(emu):
    run(emu, "sqs", "create", "awsemu-eb-target")
    run(emu, "events", "rule", "awsemu-orders", "--source", "awsemu.orders", "--to-sqs", "awsemu-eb-target")
    rules = json.loads(run(emu, "events", "rules", "--json").output)
    assert any(r["Name"] == "awsemu-orders" and r["Targets"] for r in rules)
    run(emu, "events", "put", "awsemu.orders", "OrderCreated", '{"id": 7}')
    run(emu, "events", "put", "other.source", "Ignored", "{}")
    msgs = json.loads(run(emu, "sqs", "receive", "awsemu-eb-target", "--wait", "5", "--delete",
                          "--json").output)
    assert len(msgs) == 1, msgs
    event = json.loads(msgs[0]["Body"])
    assert event["source"] == "awsemu.orders" and event["detail"] == {"id": 7}
    run(emu, "events", "rm", "awsemu-orders", "--yes")
    run(emu, "sqs", "rm", "awsemu-eb-target", "--yes")


def test_kinesis_roundtrip(emu):
    run(emu, "kinesis", "create", "awsemu-clicks")
    assert "awsemu-clicks" in run(emu, "kinesis", "ls").output
    run(emu, "kinesis", "put", "awsemu-clicks", '{"page": "/"}', "-k", "user-1")
    run(emu, "kinesis", "put", "awsemu-clicks", "plain text", "-k", "user-2")
    lines = run(emu, "kinesis", "read", "awsemu-clicks", "--json").output.strip().splitlines()
    records = [json.loads(line) for line in lines]
    assert [r["data"] for r in records] == ['{"page": "/"}', "plain text"]
    run(emu, "kinesis", "rm", "awsemu-clicks", "--yes")


def test_step_functions(emu, tmp_path):
    flow = tmp_path / "flow.asl.json"
    flow.write_text(json.dumps({
        "StartAt": "Greet",
        "States": {
            "Greet": {"Type": "Pass", "Parameters": {"greeting.$": "States.Format('hello {}', $.name)"},
                      "Next": "Done"},
            "Done": {"Type": "Succeed"},
        }}))
    run(emu, "sfn", "deploy", "awsemu-flow", str(flow))
    out = run(emu, "sfn", "start", "awsemu-flow", '{"name": "Ana"}', "--raw").output
    assert json.loads(out) == {"greeting": "hello Ana"}

    run(emu, "sfn", "deploy", "awsemu-flow",
        '{"StartAt": "X", "States": {"X": {"Type": "Fail", "Error": "Nope", "Cause": "on purpose"}}}')
    result = run(emu, "sfn", "start", "awsemu-flow", ok=False)
    assert result.exit_code == 1 and "FAILED" in result.output and "Nope" in result.output
    assert "SUCCEEDED" in run(emu, "sfn", "executions", "awsemu-flow").output
    run(emu, "sfn", "rm", "awsemu-flow", "--yes")


def test_describe_arns(emu):
    run(emu, "ddb", "create", "awsemu-describe", "--pk", "id")
    run(emu, "sqs", "create", "awsemu-describe-q")
    run(emu, "sns", "create", "awsemu-describe-t")
    table = json.loads(run(emu, "describe", "arn:aws:dynamodb:us-east-1:000000000000:table/awsemu-describe").output)
    assert table["TableName"] == "awsemu-describe"
    queue = json.loads(run(emu, "describe", "arn:aws:sqs:us-east-1:000000000000:awsemu-describe-q").output)
    assert queue["QueueArn"].endswith(":awsemu-describe-q")
    topic = json.loads(run(emu, "describe", "arn:aws:sns:us-east-1:000000000000:awsemu-describe-t").output)
    assert topic["TopicArn"].endswith(":awsemu-describe-t")
    run(emu, "ddb", "drop", "awsemu-describe", "--yes")
    run(emu, "sqs", "rm", "awsemu-describe-q", "--yes")
    run(emu, "sns", "rm", "awsemu-describe-t", "--yes")


def test_call_any_operation(emu, tmp_path):
    body = tmp_path / "data.bin"
    body.write_bytes(b"\x00binary\xff")
    run(emu, "call", "s3", "create-bucket", "-p", "Bucket=awsemu-call")
    run(emu, "call", "s3", "PutObject", "-p", "Bucket=awsemu-call", "-p", "Key=a.bin", "-p", f"Body=@{body}")
    names = json.loads(run(emu, "call", "s3", "list_objects_v2", "--params", '{"Bucket": "awsemu-call"}',
                           "--query", "Contents[].Key").output)
    assert names == ["a.bin"]
    out = tmp_path / "back.bin"
    run(emu, "call", "s3", "get-object", "-p", "Bucket=awsemu-call", "-p", "Key=a.bin", "--out", str(out))
    assert out.read_bytes() == body.read_bytes()
    missing = run(emu, "call", "s3", "head-bucket", "-p", "Bucket=awsemu-nope", ok=False)
    assert missing.exit_code == 1
    run(emu, "call", "s3", "delete-object", "-p", "Bucket=awsemu-call", "-p", "Key=a.bin")
    run(emu, "call", "s3", "delete-bucket", "-p", "Bucket=awsemu-call")
    # a service without its own command, with pages
    run(emu, "call", "logs", "create-log-group", "-p", "logGroupName=/awsemu/call")
    groups = json.loads(run(emu, "call", "logs", "describe-log-groups", "--paginate",
                            "--query", "logGroups[].logGroupName").output)
    assert "/awsemu/call" in groups
    run(emu, "call", "logs", "delete-log-group", "-p", "logGroupName=/awsemu/call")


def test_lambda_watch_redeploys_and_installs_requirements(emu, tmp_path, real_home):
    """The loop: deploy a folder with requirements.txt, save, see the new result."""
    import subprocess
    import time

    src = tmp_path / "awsemu-loop"
    src.mkdir()
    (src / "requirements.txt").write_text("six==1.16.0\n")
    app = src / "app.py"
    app.write_text("import six\ndef handler(event, context):\n    return {'v': 1, 'six': six.__version__}\n")
    env = {**os.environ, "HOME": str(real_home), "USERPROFILE": str(real_home), "AWSEMU_PLAIN": "1",
           "PYTHONUNBUFFERED": "1"}
    proc = subprocess.Popen([sys.executable, "-m", "awsemu", "--port", str(emu), "lambda", "deploy",
                             str(src), "--watch", "--invoke", "{}"],
                            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, env=env)
    lines: list[str] = []

    def wait_for(text, timeout=120):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            line = proc.stdout.readline()
            if not line:
                break
            lines.append(line)
            if text in line:
                return
        raise AssertionError(f"no {text!r} in:\n{''.join(lines)}")

    try:
        wait_for("watching")
        assert '"six": "1.16.0"' in "".join(lines) and "created awsemu-loop" in "".join(lines)
        time.sleep(1)
        app.write_text("import six\ndef handler(event, context):\n    return {'v': 2}\n")
        wait_for('"v": 2')
        assert "updated awsemu-loop" in "".join(lines)
    finally:
        proc.terminate()
        proc.wait(timeout=10)
    assert json.loads(run(emu, "lambda", "invoke", "awsemu-loop", "--raw").output) == {"v": 2}
    run(emu, "lambda", "rm", "awsemu-loop", "--yes")


def test_lambda_invoke_log_async_and_sns_subscription(emu, tmp_path):
    src = tmp_path / "echo.py"
    src.write_text("def handler(event, context):\n"
                   "    print('AWSEMU-MARK', event)\n"
                   "    return event\n")
    run(emu, "lambda", "deploy", "awsemu-echo", str(src))

    # The invocation log tail is how you see function output with the emulator.
    out = run(emu, "lambda", "invoke", "awsemu-echo", '{"via": "sync"}').output
    assert "AWSEMU-MARK {'via': 'sync'}" in out and "REPORT RequestId" in out

    assert "queued (HTTP 202)" in run(emu, "lambda", "invoke", "awsemu-echo", "{}", "--async").output

    run(emu, "sns", "create", "awsemu-to-lambda")
    run(emu, "sns", "subscribe", "awsemu-to-lambda", "--to-lambda", "awsemu-echo")
    assert "lambda" in run(emu, "sns", "subs", "awsemu-to-lambda").output
    run(emu, "sns", "publish", "awsemu-to-lambda", "from-sns")

    # The emulator doesn't write Lambda output to CloudWatch Logs: explain, don't fail.
    result = run(emu, "lambda", "logs", "awsemu-echo")
    assert "doesn't send Lambda output to CloudWatch Logs" in result.output

    run(emu, "sns", "rm", "awsemu-to-lambda", "--yes")
    run(emu, "lambda", "rm", "awsemu-echo", "--yes")


SEED = """\
version: 1
buckets:
  - name: seed-photos
    objects:
      - {key: hello.txt, content: "hello seed"}
      - {key: web/, from: ./site}
queues:
  - {name: seed-dlq}
  - {name: seed-jobs, dlq: seed-dlq, max_receive: 3, visibility_timeout: 10}
tables:
  - name: seed-users
    pk: id
    sk: created:N
    items:
      - {id: u1, created: 1, name: Ana, tags: [admin]}
    items_from: users.json
topics:
  - name: seed-orders
    subscriptions:
      - {sqs: seed-jobs, raw: true, filter: {kind: [created]}}
secrets:
  - {name: seed/db, value: {user: app, pass: x}, description: database}
parameters:
  - {name: /seed/host, value: localhost}
  - {name: /seed/key, value: abc, type: SecureString}
  - {name: /seed/hosts, value: [a, b]}
"""


def _write_seed(tmp_path, text=SEED):
    (tmp_path / "site").mkdir(exist_ok=True)
    (tmp_path / "site" / "index.html").write_text("<h1>hello</h1>")
    (tmp_path / "users.json").write_text(json.dumps([{"id": "u2", "created": 2, "score": 9.5}]))
    path = tmp_path / "seed.yaml"
    path.write_text(text)
    return path


def _results(output):
    """{(kind, name): result} from the plain-text report table."""
    out = {}
    for line in output.splitlines():
        parts = line.split()
        if len(parts) >= 3 and parts[0] in ("bucket", "queue", "table", "topic", "secret", "parameter",
                                            "stream", "function", "state_machine", "rule"):
            out[(parts[0], parts[1])] = parts[2]
    return out


def test_seed_apply_is_idempotent_and_works(emu, tmp_path):
    path = _write_seed(tmp_path)
    first = _results(run(emu, "seed", "apply", str(path)).output)
    assert len(first) == 9 and set(first.values()) == {"created"}, first

    # The wiring works: SNS -> SQS with the filter and raw delivery the seed asked for.
    run(emu, "sns", "publish", "seed-orders", '{"n": 1}', "-a", "kind=created")
    run(emu, "sns", "publish", "seed-orders", '{"n": 2}', "-a", "kind=deleted")
    msgs = json.loads(run(emu, "sqs", "receive", "seed-jobs", "--wait", "5", "--delete", "--json").output)
    assert [json.loads(m["Body"]) for m in msgs] == [{"n": 1}]
    assert run(emu, "s3", "cat", "seed-photos/web/index.html").output == "<h1>hello</h1>"
    assert len(json.loads(run(emu, "ddb", "scan", "seed-users", "--json").output)) == 2
    assert json.loads(run(emu, "secrets", "get", "seed/db", "--raw").output) == {"user": "app", "pass": "x"}
    assert run(emu, "ssm", "get", "/seed/key").output.strip() == "abc"
    assert "RedrivePolicy" in run(emu, "sqs", "info", "seed-jobs").output

    # Second run: nothing to create. Buckets/tables rewrite their content ("updated").
    second = _results(run(emu, "seed", "apply", str(path)).output)
    assert {k: v for k, v in second.items() if k[0] not in ("bucket", "table")} == \
        {k: "unchanged" for k in first if k[0] not in ("bucket", "table")}, second

    # A changed value is updated, the rest left alone.
    changed = _write_seed(tmp_path, SEED.replace("value: localhost", "value: db.local"))
    third = _results(run(emu, "seed", "apply", str(changed)).output)
    assert third[("parameter", "/seed/host")] == "updated"
    assert third[("parameter", "/seed/key")] == "unchanged"
    assert run(emu, "ssm", "get", "/seed/host").output.strip() == "db.local"


def test_seed_export_roundtrip_and_reset(emu, tmp_path):
    path = _write_seed(tmp_path)
    run(emu, "seed", "apply", str(path))
    exported = tmp_path / "exported.yaml"
    out = run(emu, "seed", "export", "-o", str(exported)).output
    assert "contains secret values" in out
    text = exported.read_text()
    for needle in ("seed-photos", "hello seed", "seed-dlq", "max_receive: 3", "sk: created:N",
                   "score: 9.5", "kind:", "seed/db", "/seed/hosts"):
        assert needle in text, (needle, text)
    run(emu, "seed", "validate", str(exported))

    # reset --seed: empty emulator, then the exported seed brings everything back.
    run(emu, "reset", "--native", "--no-telemetry", "--idle-timeout", "900", "--wait", "60",
        "--seed", str(exported))
    assert "seed-users" in run(emu, "ddb", "ls").output
    assert run(emu, "s3", "cat", "seed-photos/web/index.html").output == "<h1>hello</h1>"
    assert json.loads(run(emu, "secrets", "get", "seed/db", "--raw").output)["user"] == "app"

    no_secrets = run(emu, "seed", "export", "--no-secrets").output
    assert "seed/db" not in no_secrets and "/seed/key" not in no_secrets and "/seed/host" in no_secrets


def test_example_seed_applies(emu):
    from pathlib import Path

    example = Path(__file__).resolve().parents[1] / "examples" / "seed.yaml"
    results = _results(run(emu, "seed", "apply", str(example)).output)
    assert len(results) == 12 and "failed" not in results.values(), results
    assert "invoices.fifo" in run(emu, "sqs", "ls").output


def test_pytest_plugin_with_real_emulator(emu, pytester):
    """A pytest session using the plugin: own emulator, seed, plain boto3, fresh state."""
    import importlib.metadata

    pytester.makefile(".yaml", seed="version: 1\nbuckets:\n  - name: plugin-bucket\n"
                                    "    objects: [{key: a.txt, content: hello}]\n")
    pytester.makepyfile(test_inner="""
        import boto3

        def test_seeded(aws_emulator):
            s3 = boto3.client("s3")                     # plain boto3: env points at the emulator
            body = s3.get_object(Bucket="plugin-bucket", Key="a.txt")["Body"].read()
            assert body == b"hello"
            s3.create_bucket(Bucket="made-in-test")
            assert boto3.client("sts").get_caller_identity()["Account"] == "000000000000"

        def test_fresh_is_back_to_seed(aws_emulator_fresh):
            names = [b["Name"] for b in aws_emulator_fresh.client("s3").list_buckets()["Buckets"]]
            assert names == ["plugin-bucket"]
    """)
    eps = importlib.metadata.entry_points()
    group = eps.select(group="pytest11") if hasattr(eps, "select") else eps.get("pytest11", [])
    plugin = [] if any(ep.value == "awsemu.pytest_plugin" for ep in group) else ["-p", "awsemu.pytest_plugin"]
    result = pytester.runpytest_subprocess(*plugin, "-p", "no:cacheprovider", "--awsemu-seed", "seed.yaml", "-v")
    result.assert_outcomes(passed=2)


def test_fidelity_for_installed_version(emu):
    import subprocess

    version = subprocess.run(["aws-emulator", "-v"], capture_output=True, text=True).stdout
    data = json.loads(run(emu, "fidelity", "s3", "sqs", "dynamodb", "--json").output)
    assert f"Version: {data['release'].lstrip('v')}" in version, (data["release"], version)
    for service in ("s3", "sqs", "dynamodb"):
        s = data["services"][service]
        assert s["total"] > 0 and 0 <= s["passed"] <= s["total"], (service, s)
    out = run(emu, "fidelity", "dynamodb", "--failures").output
    assert "failing of" in out


def test_watch_sees_changes(emu):
    import signal
    import subprocess
    import sys
    import time

    proc = subprocess.Popen([sys.executable, "-m", "awsemu", "--plain", "--port", str(emu), "watch",
                             "-s", "sqs", "-i", "1"],
                            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
                            env={**os.environ, "AWSEMU_PLAIN": "1"})
    try:
        time.sleep(4)
        run(emu, "sqs", "create", "awsemu-watched")
        time.sleep(3)
        run(emu, "sqs", "send", "awsemu-watched", "hello")
        time.sleep(3)
    finally:
        proc.send_signal(signal.SIGINT)
        out = proc.communicate(timeout=15)[0]
    assert "+ queue         awsemu-watched" in out, out
    assert "~ queue         awsemu-watched  0 → 1 message(s) (+1)" in out, out
    run(emu, "sqs", "rm", "awsemu-watched", "--yes")


def test_shell_completion_with_real_names(emu):
    import subprocess
    import sys

    run(emu, "sqs", "create", "awsemu-complete-me")
    words = f"awsemu --port {emu} sqs send awsemu-comp"
    env = {**os.environ, "_AWSEMU_COMPLETE": "bash_complete", "COMP_WORDS": words, "COMP_CWORD": "5"}
    out = subprocess.run([sys.executable, "-c", "from awsemu.cli import main; main()"],
                         capture_output=True, text=True, env=env).stdout
    assert "awsemu-complete-me" in out, out
    run(emu, "sqs", "rm", "awsemu-complete-me", "--yes")


def test_tui_against_real_emulator(emu):
    pytest.importorskip("textual")
    import asyncio

    from textual.widgets import Tree

    from awsemu import tui

    run(emu, "ddb", "create", "awsemu-tui", "--pk", "id")
    run(emu, "ddb", "put", "awsemu-tui", '{"id": "x", "n": 1}')

    async def scenario():
        app = tui.EmulatorApp(port=emu)
        async with app.run_test() as pilot:
            await pilot.pause()
            labels = [str(n.label) for n in app.query_one(Tree).root.children]
            assert any(label.startswith("DynamoDB tables") for label in labels), labels
            app.show_details("dynamodb", "awsemu-tui")
            assert app.current_details["Items (first 20)"] == [{"id": "x", "n": 1}]
            await pilot.press("q")

    asyncio.run(scenario())
    run(emu, "ddb", "drop", "awsemu-tui", "--yes")



def test_json_listings_against_real_emulator(emu):
    """The --json contract holds with real responses too (types, ISO dates)."""
    run(emu, "ddb", "create", "awsemu-json", "--pk", "id", "--sk", "at:N")
    run(emu, "sqs", "create", "awsemu-json-q")
    tables = json.loads(run(emu, "ddb", "ls", "--json").output)
    t = next(x for x in tables if x["name"] == "awsemu-json")
    assert t["partition_key"] == {"name": "id", "type": "S"} and t["sort_key"] == {"name": "at", "type": "N"}
    q = next(x for x in json.loads(run(emu, "sqs", "ls", "--json").output) if x["name"] == "awsemu-json-q")
    assert q["visible"] == 0 and isinstance(q["in_flight"], int)
    for args in (["lambda", "ls"], ["sfn", "ls"], ["kinesis", "ls"], ["events", "buses"], ["sns", "subs"]):
        assert isinstance(json.loads(run(emu, *args, "--json").output), list), args
    doctor = json.loads(run(emu, "doctor", "--json", ok=False).output)
    assert any(c["check"] == f"emulator :{emu}" and c["result"] == "ok" for c in doctor["checks"])
    run(emu, "ddb", "drop", "awsemu-json", "--yes")
    run(emu, "sqs", "rm", "awsemu-json-q", "--yes")


def test_proxy_against_real_emulator(emu):
    """Every protocol through the proxy: signatures, Host-based URLs, identification, faults."""
    from botocore.exceptions import ClientError

    from awsemu import proxy as px
    from awsemu.clients import client

    server = px.ProxyServer(emu, 0)
    server.start_thread()
    try:
        def c(service):
            return client(service, emu, endpoint_url=server.endpoint_url, ca=str(server.files.ca))

        s3 = c("s3")
        s3.create_bucket(Bucket="via-proxy")
        s3.put_object(Bucket="via-proxy", Key="dir/a.txt", Body=b"hello")
        assert s3.get_object(Bucket="via-proxy", Key="dir/a.txt")["Body"].read() == b"hello"
        assert s3.head_object(Bucket="via-proxy", Key="dir/a.txt")["ContentLength"] == 5
        url = c("sqs").create_queue(QueueName="via-proxy")["QueueUrl"]
        c("sqs").send_message(QueueUrl=url, MessageBody="m")
        assert c("sqs").receive_message(QueueUrl=url, WaitTimeSeconds=1)["Messages"][0]["Body"] == "m"
        ddb = c("dynamodb")
        ddb.create_table(TableName="via-proxy", BillingMode="PAY_PER_REQUEST",
                         AttributeDefinitions=[{"AttributeName": "id", "AttributeType": "S"}],
                         KeySchema=[{"AttributeName": "id", "KeyType": "HASH"}])
        ddb.get_waiter("table_exists").wait(TableName="via-proxy", WaiterConfig={"Delay": 1, "MaxAttempts": 30})
        ddb.put_item(TableName="via-proxy", Item={"id": {"S": "1"}})
        with pytest.raises(ClientError) as exc:
            ddb.put_item(TableName="via-proxy", Item={"id": {"S": "1"}}, ConditionExpression="attribute_not_exists(id)")
        assert exc.value.response["Error"]["Code"] == "ConditionalCheckFailedException"
        c("sns").create_topic(Name="via-proxy")
        c("sts").get_caller_identity()
        c("lambda").list_functions()

        calls = server.calls_after(0)
        print("\n" + "\n".join(f"{x['service']}:{x['operation']} {x['resource']} {x['status']} {x['error']}"
                               for x in calls))
        ops = [f"{x['service']}:{x['operation']}" for x in calls]
        for expected in ("s3:CreateBucket", "s3:PutObject", "s3:GetObject", "s3:HeadObject", "sqs:CreateQueue",
                         "sqs:SendMessage", "sqs:ReceiveMessage", "dynamodb:CreateTable", "dynamodb:PutItem",
                         "sns:CreateTopic", "sts:GetCallerIdentity", "lambda:ListFunctions"):
            assert expected in ops, expected
        assert not [x for x in calls if x["status"] in (401, 403, 502)], "signature or forwarding problem"
        failed = [x for x in calls if x["error"]]
        assert [x["error"] for x in failed] == ["ConditionalCheckFailedException"]
        assert next(x for x in calls if x["operation"] == "PutObject")["resource"] == "via-proxy/dir/a.txt"

        server.faults.add(px.faults.parse("dynamodb:GetItem=throttle x1"),
                          px.faults.parse("s3:GetObject=InternalError x1"))
        assert ddb.get_item(TableName="via-proxy", Key={"id": {"S": "1"}})["Item"]
        assert s3.get_object(Bucket="via-proxy", Key="dir/a.txt")["Body"].read() == b"hello"
        tail = [(x["operation"], x["error"]) for x in server.calls_after(len(calls))]
        assert tail == [("GetItem", "ThrottlingException"), ("GetItem", None),
                        ("GetObject", "InternalError"), ("GetObject", None)]
    finally:
        server.shutdown()
        server.server_close()


def test_proxy_commands_against_real_emulator(emu, tmp_path):
    """awsemu proxy start -d, exec --proxy with the AWS CLI-free boto3, calls, stop."""
    run(emu, "proxy", "start", "-d", "--listen", "0", "--fault", "sqs:ListQueues=latency:200ms")
    try:
        script = tmp_path / "use.py"
        script.write_text("import boto3\nboto3.client('sqs').list_queues()\nprint('ok')\n")
        result = run(emu, "exec", "--proxy", "--", sys.executable, str(script))
        assert result.exit_code == 0
        calls = json.loads(run(emu, "proxy", "calls", "--json").output)
        assert [(x["service"], x["operation"]) for x in calls][-1] == ("sqs", "ListQueues")
        assert calls[-1]["latency_ms"] >= 200 and calls[-1]["fault"] == "sqs:ListQueues=latency:200ms"
    finally:
        run(emu, "proxy", "stop")


def test_auth_off_exec_signs_with_placeholder_keys(real_home, tmp_path):
    """With --no-auth, programs run through awsemu work and never sign with your real profile."""
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    real = real_home / ".aws" / "credentials"
    real.parent.mkdir(parents=True, exist_ok=True)
    saved = real.read_text() if real.exists() else None
    real.write_text("[default]\naws_access_key_id = AKIAREALKEY000000000\naws_secret_access_key = secret\n")
    run(port, "start", "--native", "--no-auth", "--no-telemetry", "--idle-timeout", "300", "--wait", "60")
    try:
        assert not InstanceFiles(port).credentials.exists()  # the emulator writes none with auth off
        script = tmp_path / "use.py"
        script.write_text("import boto3\ns = boto3.Session()\n"
                          "assert s.get_credentials().access_key == 'EMULATORAUTHOFF00000'\n"
                          "s.client('s3').create_bucket(Bucket='auth-off')\n"
                          "assert 'auth-off' in [b['Name'] for b in s.client('s3').list_buckets()['Buckets']]\n")
        result = run(port, "exec", "--", sys.executable, str(script))
        assert result.exit_code == 0
    finally:
        run(port, "stop")
        if saved is None:
            real.unlink()
        else:
            real.write_text(saved)


SEED_MORE = """
version: 1
queues:
  - {name: more-jobs}
  - {name: more-events}
streams:
  - {name: more-clicks, shards: 2}
functions:
  - name: more-echo
    code: ./fn
    env: {STAGE: test}
    timeout: 10
    triggers: [{sqs: more-jobs, batch_size: 5}]
state_machines:
  - name: more-flow
    definition: ./flow.yaml
rules:
  - name: more-orders
    pattern: {source: [app.orders]}
    targets: [{sqs: more-events}, {stepfunctions: more-flow}]
"""


def _write_more(tmp_path, text=SEED_MORE):
    (tmp_path / "fn").mkdir(exist_ok=True)
    (tmp_path / "fn" / "app.py").write_text(
        "import os\n\ndef handler(event, context):\n    return {'stage': os.environ.get('STAGE'), 'event': event}\n")
    (tmp_path / "flow.yaml").write_text("StartAt: Hi\nStates:\n  Hi: {Type: Pass, Result: done, End: true}\n")
    path = tmp_path / "more.yaml"
    path.write_text(text)
    return path


def test_seed_functions_streams_machines_rules(emu, tmp_path):
    path = _write_more(tmp_path)
    first = _results(run(emu, "seed", "apply", str(path)).output)
    assert set(first.values()) == {"created"} and len(first) == 6, first

    out = json.loads(run(emu, "lambda", "invoke", "more-echo", '{"n": 1}', "--raw").output)
    assert out == {"stage": "test", "event": {"n": 1}}
    assert "2" in run(emu, "kinesis", "ls").output
    mappings = client("lambda", emu).list_event_source_mappings(FunctionName="more-echo")["EventSourceMappings"]
    assert [(m["EventSourceArn"].rsplit(":", 1)[-1], m["BatchSize"]) for m in mappings] == [("more-jobs", 5)]
    run(emu, "events", "put", "app.orders", "Created", '{"id": 7}')
    msgs = json.loads(run(emu, "sqs", "receive", "more-events", "--wait", "10", "--delete", "--json").output)
    assert json.loads(msgs[0]["Body"])["detail"] == {"id": 7}

    # Applied again: nothing changes (the zip is reproducible, so the code isn't redeployed)
    second = _results(run(emu, "seed", "apply", str(path)).output)
    assert set(second.values()) == {"unchanged"}, second

    # Changes are applied
    changed = _write_more(tmp_path, SEED_MORE.replace("STAGE: test", "STAGE: prod")
                          .replace("shards: 2", "shards: 3").replace("batch_size: 5", "batch_size: 7"))
    third = _results(run(emu, "seed", "apply", str(changed)).output)
    assert third[("function", "more-echo")] == "updated" and third[("stream", "more-clicks")] == "updated", third
    assert third[("rule", "more-orders")] == "unchanged"
    assert json.loads(run(emu, "lambda", "invoke", "more-echo", "{}", "--raw").output)["stage"] == "prod"

    # Export with the code, and apply the export to an empty emulator
    exported = tmp_path / "out" / "seed.yaml"
    exported.parent.mkdir()
    run(emu, "seed", "export", "-o", str(exported), "--objects-dir", str(tmp_path / "out" / "files"))
    text = exported.read_text()
    for needle in ("more-echo", "code: files/functions/more-echo.zip", "STAGE: prod", "more-clicks", "shards: 3",
                   "more-flow", "StartAt: Hi", "more-orders", "app.orders", "stepfunctions: more-flow",
                   "batch_size: 7"):
        assert needle in text, (needle, text)
    run(emu, "seed", "validate", str(exported))
    run(emu, "reset", "--native", "--no-telemetry", "--idle-timeout", "900", "--wait", "60", "--seed", str(exported))
    assert json.loads(run(emu, "lambda", "invoke", "more-echo", "{}", "--raw").output)["stage"] == "prod"
    assert "more-orders" in run(emu, "events", "rules").output


def test_snapshot_save_and_restore(emu, tmp_path):
    path = _write_seed(tmp_path)
    run(emu, "seed", "apply", str(path))
    more = _write_more(tmp_path)
    run(emu, "seed", "apply", str(more))
    run(emu, "snapshot", "save", "real-snap", "--dir", str(tmp_path / "snaps"))

    # Change things: a new bucket, a deleted queue, a changed parameter
    run(emu, "s3", "mb", "after-snapshot")
    client("sqs", emu).delete_queue(QueueUrl=client("sqs", emu).get_queue_url(QueueName="seed-jobs")["QueueUrl"])
    run(emu, "ssm", "put", "/seed/host", "changed")

    run(emu, "snapshot", "restore", "real-snap", "--dir", str(tmp_path / "snaps"))
    assert "after-snapshot" not in run(emu, "s3", "ls").output
    assert "seed-jobs" in run(emu, "sqs", "ls").output
    assert run(emu, "ssm", "get", "/seed/host").output.strip() == "localhost"
    assert json.loads(run(emu, "lambda", "invoke", "more-echo", "{}", "--raw").output)["stage"] == "test"
    assert "more-orders" in run(emu, "events", "rules").output
