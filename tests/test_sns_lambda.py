"""SNS and Lambda commands with fake boto3 clients."""

import base64
import io
import json
import zipfile
from pathlib import Path

import click

import pytest

from awsemu.cli import cli
from tests.conftest import aws_error
from awsemu.commands import lambda_ as lam_mod
from awsemu.commands import sns as sns_mod
from tests.test_services import FakeClient

QUEUE_URL = "https://127.0.0.1:9297/000000000000/events"
QUEUE_ARN = "arn:aws:sqs:us-east-1:000000000000:events"
TOPIC_ARN = "arn:aws:sns:us-east-1:000000000000:orders"


# ---------------------------------------------------------------- SNS


def test_topic_arn():
    assert sns_mod.topic_arn("orders") == TOPIC_ARN
    assert sns_mod.topic_arn(TOPIC_ARN) == TOPIC_ARN


def test_queue_policy_merges_and_is_idempotent():
    existing = json.dumps({"Version": "2012-10-17", "Statement": [{"Sid": "mine", "Effect": "Allow"}]})
    once = sns_mod.queue_policy_for_topic(QUEUE_ARN, TOPIC_ARN, existing)
    twice = sns_mod.queue_policy_for_topic(QUEUE_ARN, TOPIC_ARN, once)
    statements = json.loads(twice)["Statement"]
    assert [s["Sid"] for s in statements] == ["mine", "awsemu-sns-orders"]
    assert statements[1]["Condition"]["ArnEquals"]["aws:SourceArn"] == TOPIC_ARN


def test_subscribe_to_sqs_sets_policy(runner, monkeypatch, running):
    sqs = FakeClient(
        get_queue_url={"QueueUrl": QUEUE_URL}, get_queue_attributes={"Attributes": {"QueueArn": QUEUE_ARN}}
    )
    sns = FakeClient(subscribe={"SubscriptionArn": TOPIC_ARN + ":sub-1"})
    monkeypatch.setattr(sns_mod, "client", lambda service, port: {"sqs": sqs, "sns": sns}[service])
    result = runner.invoke(cli, ["sns", "subscribe", "orders", "--to-sqs", "events", "--raw"])
    assert result.exit_code == 0, result.output
    op, kwargs = sqs.calls[-1]
    assert op == "set_queue_attributes"
    assert json.loads(kwargs["Attributes"]["Policy"])["Statement"][0]["Resource"] == QUEUE_ARN
    op, kwargs = sns.calls[-1]
    assert (op, kwargs["Protocol"], kwargs["Endpoint"]) == ("subscribe", "sqs", QUEUE_ARN)
    assert kwargs["Attributes"] == {"RawMessageDelivery": "true"}


def test_subscribe_needs_one_target(runner, running):
    result = runner.invoke(cli, ["sns", "subscribe", "orders"])
    assert result.exit_code == 2 and "exactly one" in result.output


def test_publish_with_attributes(runner, monkeypatch, running):
    sns = FakeClient(publish={"MessageId": "m-1"})
    monkeypatch.setattr(sns_mod, "client", lambda service, port: sns)
    result = runner.invoke(cli, ["sns", "publish", "orders", "hello", "--subject", "s", "-a", "k=v"])
    assert result.exit_code == 0, result.output
    kwargs = sns.calls[-1][1]
    assert kwargs["TopicArn"] == TOPIC_ARN and kwargs["Message"] == "hello"
    assert kwargs["MessageAttributes"]["k"]["StringValue"] == "v"


# ---------------------------------------------------------------- Lambda packaging


def test_build_zip_from_folder_skips_junk(tmp_path):
    (tmp_path / "app.py").write_text("def handler(e, c): return e\n")
    (tmp_path / "pkg").mkdir()
    (tmp_path / "pkg" / "util.py").write_text("X = 1\n")
    (tmp_path / "__pycache__").mkdir()
    (tmp_path / "__pycache__" / "app.cpython-312.pyc").write_bytes(b"x")
    names = zipfile.ZipFile(io.BytesIO(lam_mod.build_zip(tmp_path))).namelist()
    assert sorted(names) == ["app.py", "pkg/util.py"]


def test_build_zip_single_file_and_passthrough(tmp_path):
    f = tmp_path / "hello.py"
    f.write_text("def handler(e, c): pass\n")
    assert zipfile.ZipFile(io.BytesIO(lam_mod.build_zip(f))).namelist() == ["hello.py"]
    z = tmp_path / "code.zip"
    z.write_bytes(b"PK-already-a-zip")
    assert lam_mod.build_zip(z) == b"PK-already-a-zip"


@pytest.mark.parametrize(
    "filename,code,expected",
    [
        ("hello.py", "def handler(event, context):\n", ("hello.handler", "python3.12")),
        (
            "lambda_function.py",
            "def lambda_handler(event, context):\n",
            ("lambda_function.lambda_handler", "python3.12"),
        ),
        ("index.mjs", "export const handler = async (event) => event;\n", ("index.handler", "nodejs20.x")),
        ("index.js", "exports.handler = async (event) => event;\n", ("index.handler", "nodejs20.x")),
    ],
)
def test_guess_handler(tmp_path, filename, code, expected):
    (tmp_path / filename).write_text(code)
    assert lam_mod.guess_handler_and_runtime(tmp_path) == expected
    assert lam_mod.guess_handler_and_runtime(tmp_path / filename) == expected


# ---------------------------------------------------------------- Lambda commands


def _lambda_client(exists: bool):
    def get_function(**_):
        if not exists:
            raise aws_error("ResourceNotFoundException", "missing")
        return {"Configuration": {"FunctionArn": "arn:aws:lambda:us-east-1:000000000000:function:hi"}}

    fake = FakeClient(
        get_function=get_function, create_function={}, update_function_code={}, update_function_configuration={}
    )
    fake.get_waiter = lambda name: type("W", (), {"wait": lambda self, **kw: None})()
    return fake


def test_deploy_creates_function_and_role(runner, monkeypatch, running, tmp_path):
    (tmp_path / "hi.py").write_text("def handler(event, context):\n    return {'ok': True}\n")
    lam = _lambda_client(exists=False)

    def get_role(**_):
        raise aws_error("NoSuchEntity", "no role")

    iam = FakeClient(
        get_role=get_role, create_role={"Role": {"Arn": "arn:aws:iam::000000000000:role/awsemu-lambda-role"}}
    )
    monkeypatch.setattr(lam_mod, "client", lambda service, port: {"lambda": lam, "iam": iam}[service])
    result = runner.invoke(cli, ["lambda", "deploy", "hi", str(tmp_path / "hi.py"), "-e", "A=1"])
    assert result.exit_code == 0, result.output
    op, kwargs = [c for c in lam.calls if c[0] == "create_function"][0]
    assert kwargs["Handler"] == "hi.handler" and kwargs["Runtime"] == "python3.12"
    assert kwargs["Role"].endswith("role/awsemu-lambda-role")
    assert kwargs["Environment"] == {"Variables": {"A": "1"}}
    assert zipfile.ZipFile(io.BytesIO(kwargs["Code"]["ZipFile"])).namelist() == ["hi.py"]


def test_deploy_updates_existing(runner, monkeypatch, running, tmp_path):
    (tmp_path / "hi.py").write_text("def handler(event, context):\n    return 1\n")
    lam = _lambda_client(exists=True)
    monkeypatch.setattr(lam_mod, "client", lambda service, port: lam)
    result = runner.invoke(cli, ["lambda", "deploy", "hi", str(tmp_path / "hi.py"), "--timeout", "30"])
    assert result.exit_code == 0, result.output
    ops = [c[0] for c in lam.calls]
    assert "update_function_code" in ops and "create_function" not in ops
    assert dict(lam.calls)["update_function_configuration"]["Timeout"] == 30


def test_invoke_shows_payload_and_logs(runner, monkeypatch, running):
    resp = {
        "StatusCode": 200,
        "Payload": io.BytesIO(b'{"greeting": "hello Ana"}'),
        "LogResult": base64.b64encode(b"START RequestId: 1\nhello log\nEND").decode(),
    }
    lam = FakeClient(invoke=resp)
    monkeypatch.setattr(lam_mod, "client", lambda service, port: lam)
    result = runner.invoke(cli, ["lambda", "invoke", "hi", '{"name": "Ana"}'])
    assert result.exit_code == 0, result.output
    assert "hello Ana" in result.output and "hello log" in result.output
    assert lam.calls[0][1]["Payload"] == b'{"name": "Ana"}'


def test_invoke_function_error_exit_code(runner, monkeypatch, running):
    resp = {"StatusCode": 200, "FunctionError": "Unhandled", "Payload": io.BytesIO(b'{"errorMessage": "boom"}')}
    monkeypatch.setattr(lam_mod, "client", lambda service, port: FakeClient(invoke=resp))
    result = runner.invoke(cli, ["lambda", "invoke", "hi"])
    assert result.exit_code == 1 and "boom" in result.output and "function error" in result.output


def test_invoke_rejects_bad_json(runner, running):
    result = runner.invoke(cli, ["lambda", "invoke", "hi", "{nope"])
    assert result.exit_code == 2 and "not JSON" in result.output


# ---------------------------------------------------------------- the deploy loop


def test_deploy_with_only_a_path_names_the_function_after_it(runner, monkeypatch, running, tmp_path):
    src = tmp_path / "orders"
    src.mkdir()
    (src / "app.py").write_text("def handler(event, context):\n    return 1\n")
    lam = _lambda_client(exists=True)
    monkeypatch.setattr(lam_mod, "client", lambda service, port: lam)
    result = runner.invoke(cli, ["lambda", "deploy", str(src)])
    assert result.exit_code == 0, result.output
    assert dict(lam.calls)["update_function_code"]["FunctionName"] == "orders"
    assert runner.invoke(cli, ["lambda", "deploy"]).exit_code == 2


def test_deploy_then_invoke(runner, monkeypatch, running, tmp_path):
    (tmp_path / "hi.py").write_text("def handler(event, context):\n    return 1\n")
    lam = _lambda_client(exists=True)
    lam.responses["invoke"] = {
        "StatusCode": 200,
        "Payload": io.BytesIO(b'{"ok": true}'),
        "LogResult": base64.b64encode(b"START x\nfrom the code\nEND x").decode(),
    }
    monkeypatch.setattr(lam_mod, "client", lambda service, port: lam)
    result = runner.invoke(cli, ["lambda", "deploy", "hi", str(tmp_path / "hi.py"), "--invoke", '{"a": 1}'])
    assert result.exit_code == 0, result.output
    assert "from the code" in result.output and '"ok": true' in result.output and "START" not in result.output
    assert dict(lam.calls)["invoke"]["Payload"] == b'{"a": 1}'
    bad = runner.invoke(cli, ["lambda", "deploy", "hi", str(tmp_path / "hi.py"), "--invoke", "{nope"])
    assert bad.exit_code == 2 and "--invoke" in bad.output


def test_dependencies_go_in_the_zip_and_your_files_win(tmp_path):
    src, deps = tmp_path / "src", tmp_path / "deps"
    (deps / "requests").mkdir(parents=True)
    src.mkdir()
    (src / "app.py").write_text("mine")
    (deps / "app.py").write_text("theirs")
    (deps / "requests" / "__init__.py").write_text("")
    zf = zipfile.ZipFile(io.BytesIO(lam_mod.build_zip(src, deps)))
    assert zf.namelist() == ["app.py", "requests/__init__.py"]
    assert zf.read("app.py") == b"mine"
    assert lam_mod.build_zip(src, deps) == lam_mod.build_zip(src, deps)


def test_requirements_are_installed_once_per_contents(monkeypatch, tmp_path, isolated_home):
    src = tmp_path / "fn"
    src.mkdir()
    (src / "app.py").write_text("def handler(e, c): pass\n")
    (src / "requirements.txt").write_text("tinylib==1.0\n")
    installs = []

    class Done:
        def __init__(self, code=0, stderr=""):
            self.returncode, self.stderr, self.stdout = code, stderr, ""

    def fake_run(cmd, **kwargs):
        if "--version" in cmd:
            return Done()
        installs.append(cmd)
        target = Path(cmd[cmd.index("-t") + 1])
        (target / "tinylib").mkdir()
        (target / "tinylib" / "__init__.py").write_text("")
        return Done()

    monkeypatch.setattr(lam_mod.subprocess, "run", fake_run)
    names = zipfile.ZipFile(io.BytesIO(lam_mod.package(src, "python3.12"))).namelist()
    assert "tinylib/__init__.py" in names and "requirements.txt" in names
    lam_mod.package(src, "python3.12")
    assert len(installs) == 1  # cached
    assert (
        "tinylib/__init__.py"
        not in zipfile.ZipFile(io.BytesIO(lam_mod.package(src, "python3.12", deps=False))).namelist()
    )
    assert lam_mod.python_dependencies(src, "nodejs20.x") is None

    (src / "requirements.txt").write_text("missing-lib==9\n")
    monkeypatch.setattr(
        lam_mod.subprocess,
        "run",
        lambda cmd, **kw: Done() if "--version" in cmd else Done(1, "No matching distribution"),
    )
    with pytest.raises(click.ClickException, match="No matching distribution"):
        lam_mod.package(src, "python3.12")


def test_watch_redeploys_on_save_and_survives_errors(monkeypatch, tmp_path, capsys):
    src = tmp_path / "fn"
    src.mkdir()
    app = src / "app.py"
    app.write_text("def handler(e, c):\n    return 1\n")
    lam = _lambda_client(exists=True)
    lam.responses["invoke"] = lambda **_: {"StatusCode": 200, "Payload": io.BytesIO(b"2")}
    edits = iter(
        [
            lambda: app.write_text("def handler(e, c):\n    return 2\n"),  # a real change
            lambda: (src / "__pycache__").mkdir() or (src / "__pycache__" / "x.pyc").write_text(""),
            lambda: app.write_text("def handler(e, c):\n    return 3\n"),  # the update fails
        ]
    )
    sleeps = []

    def fake_sleep(seconds):
        sleeps.append(seconds)
        if seconds == lam_mod.POLL_SECONDS:
            next(edits, lambda: None)()
            import os

            os.utime(app, ns=(len(sleeps) * 10**9, len(sleeps) * 10**9))

    monkeypatch.setattr(lam_mod.time, "sleep", fake_sleep)
    calls = {"n": 0}

    def update_function_code(**kwargs):
        calls["n"] += 1
        if calls["n"] == 2:
            raise RuntimeError("emulator said no")
        return {}

    lam.responses["update_function_code"] = update_function_code
    code = lam_mod.build_zip(src)
    lam_mod._watch(lam, "fn", src, "python3.12", False, "{}", code, max_rounds=4)
    out = capsys.readouterr()
    text = out.out + out.err
    # round 1 deploys, round 2 only touched __pycache__, round 3 fails,
    # round 4 (any save) retries the code that didn't make it
    assert text.count("updated fn") == 2 and "emulator said no" in text
    assert [c[0] for c in lam.calls].count("update_function_code") == 3
    assert [c[0] for c in lam.calls].count("invoke") == 2
