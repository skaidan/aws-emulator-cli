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
            "Greet": {"Type": "Pass", "Parameters": {"greeting.$": "States.Format('hola {}', $.name)"},
                      "Next": "Done"},
            "Done": {"Type": "Succeed"},
        }}))
    run(emu, "sfn", "deploy", "awsemu-flow", str(flow))
    out = run(emu, "sfn", "start", "awsemu-flow", '{"name": "Ana"}', "--raw").output
    assert json.loads(out) == {"greeting": "hola Ana"}

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
  - name: seed-fotos
    objects:
      - {key: hola.txt, content: "hola seed"}
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
    (tmp_path / "site" / "index.html").write_text("<h1>hola</h1>")
    (tmp_path / "users.json").write_text(json.dumps([{"id": "u2", "created": 2, "score": 9.5}]))
    path = tmp_path / "seed.yaml"
    path.write_text(text)
    return path


def _results(output):
    """{(kind, name): result} from the plain-text report table."""
    out = {}
    for line in output.splitlines():
        parts = line.split()
        if len(parts) >= 3 and parts[0] in ("bucket", "queue", "table", "topic", "secret", "parameter"):
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
    assert run(emu, "s3", "cat", "seed-fotos/web/index.html").output == "<h1>hola</h1>"
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
    for needle in ("seed-fotos", "hola seed", "seed-dlq", "max_receive: 3", "sk: created:N",
                   "score: 9.5", "kind:", "seed/db", "/seed/hosts"):
        assert needle in text, (needle, text)
    run(emu, "seed", "validate", str(exported))

    # reset --seed: empty emulator, then the exported seed brings everything back.
    run(emu, "reset", "--native", "--no-telemetry", "--idle-timeout", "900", "--wait", "60",
        "--seed", str(exported))
    assert "seed-users" in run(emu, "ddb", "ls").output
    assert run(emu, "s3", "cat", "seed-fotos/web/index.html").output == "<h1>hola</h1>"
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
                                    "    objects: [{key: a.txt, content: hola}]\n")
    pytester.makepyfile(test_inner="""
        import boto3

        def test_seeded(aws_emulator):
            import os, pathlib, botocore.session
            print("### DIAG HOME", os.environ.get("HOME"))
            for k in sorted(os.environ):
                if k.startswith("AWS"):
                    print("### DIAG", k, os.environ[k])
            cf = os.environ.get("AWS_SHARED_CREDENTIALS_FILE")
            print("### DIAG creds exists", cf and pathlib.Path(cf).exists())
            if cf and pathlib.Path(cf).exists():
                print("### DIAG creds sections", [l for l in pathlib.Path(cf).read_text().splitlines() if l.startswith("[")])
            cfg = os.environ.get("AWS_CONFIG_FILE")
            if cfg and pathlib.Path(cfg).exists():
                print("### DIAG config", pathlib.Path(cfg).read_text().replace(chr(10), " | "))
            c = botocore.session.get_session().get_credentials()
            print("### DIAG botocore creds", c and c.method)
            s3 = boto3.client("s3")                     # plain boto3: env points at the emulator
            body = s3.get_object(Bucket="plugin-bucket", Key="a.txt")["Body"].read()
            assert body == b"hola"
            s3.create_bucket(Bucket="made-in-test")
            assert boto3.client("sts").get_caller_identity()["Account"] == "000000000000"

        def test_fresh_is_back_to_seed(aws_emulator_fresh):
            names = [b["Name"] for b in aws_emulator_fresh.client("s3").list_buckets()["Buckets"]]
            assert names == ["plugin-bucket"]
    """)
    eps = importlib.metadata.entry_points()
    group = eps.select(group="pytest11") if hasattr(eps, "select") else eps.get("pytest11", [])
    plugin = [] if any(ep.value == "awsemu.pytest_plugin" for ep in group) else ["-p", "awsemu.pytest_plugin"]
    result = pytester.runpytest_subprocess(*plugin, "-p", "no:cacheprovider", "--awsemu-seed", "seed.yaml", "-v", "-s")
    print(result.stdout.str())
    result.assert_outcomes(passed=2)
