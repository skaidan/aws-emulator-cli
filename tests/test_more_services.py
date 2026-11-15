"""Secrets, SSM, EventBridge, Kinesis, Step Functions and describe, with fake clients."""

import json
from datetime import datetime, timedelta

import click
import pytest

from awsemu.cli import cli
from awsemu.commands import describe as describe_mod
from awsemu.commands import events as events_mod
from awsemu.commands import kinesis as kinesis_mod
from awsemu.commands import secrets as secrets_mod
from awsemu.commands import sfn as sfn_mod
from tests.test_services import FakeClient, running  # noqa: F401  (fixture)


def err(code):
    cls = type(code, (Exception,), {})
    exc = cls(code)
    exc.response = {"Error": {"Code": code, "Message": code}}
    return exc


def raises(code):
    def fn(**_):
        raise err(code)
    return fn


def use(monkeypatch, module, **clients):
    monkeypatch.setattr(module, "client", lambda service, port: clients[service])


# ---------------------------------------------------------------- Secrets / SSM


def test_secrets_put_creates_then_versions(runner, monkeypatch, running):
    sm = FakeClient(create_secret={})
    use(monkeypatch, secrets_mod, secretsmanager=sm)
    assert "created db/pass" in runner.invoke(cli, ["secrets", "put", "db/pass", "x"]).output

    sm = FakeClient(create_secret=raises("ResourceExistsException"), put_secret_value={})
    use(monkeypatch, secrets_mod, secretsmanager=sm)
    result = runner.invoke(cli, ["secrets", "put", "db/pass", "y"])
    assert result.exit_code == 0, result.output
    assert "new version" in result.output
    assert sm.calls[-1] == ("put_secret_value", {"SecretId": "db/pass", "SecretString": "y"})


def test_secrets_get_pretty_and_raw(runner, monkeypatch, running):
    sm = FakeClient(get_secret_value={"SecretString": '{"host":"db","port":5432}'})
    use(monkeypatch, secrets_mod, secretsmanager=sm)
    pretty = runner.invoke(cli, ["secrets", "get", "db/config"]).output
    assert json.loads(pretty) == {"host": "db", "port": 5432} and "\n  " in pretty
    raw = runner.invoke(cli, ["secrets", "get", "db/config", "--raw"]).output
    assert raw.strip() == '{"host":"db","port":5432}'


def test_ssm_put_types(runner, monkeypatch, running):
    s = FakeClient(put_parameter={"Version": 3})
    use(monkeypatch, secrets_mod, ssm=s)
    out = runner.invoke(cli, ["ssm", "put", "/app/key", "abc", "--secure"]).output
    assert "****" in out and "abc" not in out and "version 3" in out
    assert s.calls[-1][1]["Type"] == "SecureString" and s.calls[-1][1]["Overwrite"] is True
    assert runner.invoke(cli, ["ssm", "put", "/x", "a", "--secure", "--list"]).exit_code == 2


def test_ssm_rm_reports_missing(runner, monkeypatch, running):
    s = FakeClient(delete_parameters={"DeletedParameters": ["/a"], "InvalidParameters": ["/b"]})
    use(monkeypatch, secrets_mod, ssm=s)
    result = runner.invoke(cli, ["ssm", "rm", "/a", "/b"])
    assert result.exit_code == 1 and "deleted /a" in result.output and "not found: /b" in result.output


# ---------------------------------------------------------------- EventBridge


RULE_ARN = "arn:aws:events:us-east-1:000000000000:rule/orders-created"


def test_events_rule_to_sqs(runner, monkeypatch, running):
    ev = FakeClient(put_rule={"RuleArn": RULE_ARN}, put_targets={"FailedEntryCount": 0})
    sqs = FakeClient(get_queue_url={"QueueUrl": "https://q/events"},
                     get_queue_attributes={"Attributes": {"QueueArn": "arn:aws:sqs:us-east-1:000000000000:events"}})
    use(monkeypatch, events_mod, events=ev, sqs=sqs)
    result = runner.invoke(cli, ["events", "rule", "orders-created", "--source", "app.orders",
                                 "--to-sqs", "events"])
    assert result.exit_code == 0, result.output
    put_rule = ev.calls[0][1]
    assert json.loads(put_rule["EventPattern"]) == {"source": ["app.orders"]}
    policy = json.loads(sqs.calls[-1][1]["Attributes"]["Policy"])["Statement"][0]
    assert policy["Principal"] == {"Service": "events.amazonaws.com"}
    assert policy["Condition"]["ArnEquals"]["aws:SourceArn"] == RULE_ARN
    assert ev.calls[-1][1]["Targets"][0]["Arn"].endswith(":events")


@pytest.mark.parametrize("args", [[], ["--pattern", "{}", "--schedule", "rate(1 minute)"]])
def test_events_rule_needs_one_trigger(runner, running, args):
    assert runner.invoke(cli, ["events", "rule", "r", *args]).exit_code == 2


def test_events_put_rejects_bad_json(runner, running):
    result = runner.invoke(cli, ["events", "put", "app", "T", "{nope"])
    assert result.exit_code == 2 and "not valid JSON" in result.output


# ---------------------------------------------------------------- Kinesis


def test_kinesis_decode():
    assert kinesis_mod.decode(b'{"a":1}') == '{"a": 1}'
    assert kinesis_mod.decode(b"plain") == "plain"
    assert kinesis_mod.decode(b"\xff\x00") == "0xff00"


def test_kinesis_read_stops_when_caught_up(runner, monkeypatch, running):
    pages = iter([
        {"Records": [{"SequenceNumber": "1", "PartitionKey": "k1", "Data": b'{"n":1}'}],
         "NextShardIterator": "it2", "MillisBehindLatest": 0},
        {"Records": [], "NextShardIterator": "it3", "MillisBehindLatest": 0},
    ])
    k = FakeClient(list_shards=[{"Shards": [{"ShardId": "shard-0"}]}],
                   get_shard_iterator={"ShardIterator": "it1"},
                   get_records=lambda **_: next(pages))
    use(monkeypatch, kinesis_mod, kinesis=k)
    result = runner.invoke(cli, ["kinesis", "read", "clicks"])
    assert result.exit_code == 0, result.output
    assert '{"n": 1}' in result.output and "1 record(s)" in result.output


# ---------------------------------------------------------------- Step Functions


def test_sfn_definition_validation(tmp_path):
    f = tmp_path / "flow.asl.json"
    f.write_text('{"StartAt": "A", "States": {"A": {"Type": "Pass", "End": true}}}')
    assert json.loads(sfn_mod.read_definition(str(f)))["StartAt"] == "A"
    with pytest.raises(click.BadParameter):
        sfn_mod.read_definition('{"StartAt": "A"}')


def test_sfn_start_waits_and_reports_failure(runner, monkeypatch, running):
    now = datetime(2026, 11, 15, 12, 0, 0)
    states = iter([{"status": "RUNNING"},
                   {"status": "FAILED", "error": "States.TaskFailed", "cause": "boom",
                    "startDate": now, "stopDate": now + timedelta(seconds=1)}])
    s = FakeClient(start_execution={"executionArn": "arn:exec"},
                   describe_execution=lambda **_: next(states))
    use(monkeypatch, sfn_mod, stepfunctions=s)
    monkeypatch.setattr(sfn_mod.time, "sleep", lambda _: None)
    result = runner.invoke(cli, ["sfn", "start", "flow", '{"x": 1}'])
    assert result.exit_code == 1
    assert "FAILED: States.TaskFailed boom" in result.output
    assert s.calls[0][1]["stateMachineArn"] == "arn:aws:states:us-east-1:000000000000:stateMachine:flow"


def test_sfn_start_success_raw(runner, monkeypatch, running):
    s = FakeClient(start_execution={"executionArn": "arn:exec"},
                   describe_execution={"status": "SUCCEEDED", "output": '{"ok": true}'})
    use(monkeypatch, sfn_mod, stepfunctions=s)
    result = runner.invoke(cli, ["sfn", "start", "flow", "--raw"])
    assert result.exit_code == 0 and json.loads(result.output) == {"ok": True}


# ---------------------------------------------------------------- describe


@pytest.mark.parametrize("arn,service,kind,rest", [
    ("arn:aws:dynamodb:us-east-1:000000000000:table/users", "dynamodb", "table", "users"),
    ("arn:aws:lambda:us-east-1:000000000000:function:hello", "lambda", "function", "hello"),
    ("arn:aws:s3:::bucket/a/b.txt", "s3", "bucket", "a/b.txt"),
    ("arn:aws:states:us-east-1:000000000000:execution:flow:run-1", "states", "execution", "flow:run-1"),
    ("arn:aws:sqs:us-east-1:000000000000:jobs", "sqs", "", "jobs"),
])
def test_parse_arn(arn, service, kind, rest):
    a = describe_mod.parse_arn(arn)
    assert (a.service, a.kind, a.rest) == (service, kind, rest)


def test_describe_dispatch(runner, monkeypatch, running):
    ddb = FakeClient(describe_table={"Table": {"TableName": "users", "ItemCount": 2}})
    use(monkeypatch, describe_mod, dynamodb=ddb)
    result = runner.invoke(cli, ["describe", "arn:aws:dynamodb:us-east-1:000000000000:table/users"])
    assert result.exit_code == 0, result.output
    assert json.loads(result.output) == {"TableName": "users", "ItemCount": 2}


def test_describe_unknown_and_invalid(runner, running):
    result = runner.invoke(cli, ["describe", "arn:aws:ec2:us-east-1:000000000000:instance/i-1"])
    assert result.exit_code == 1 and "awsemu aws ec2" in result.output
    assert runner.invoke(cli, ["describe", "not-an-arn"]).exit_code == 2
