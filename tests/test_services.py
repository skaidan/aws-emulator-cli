"""Service commands with a fake boto3 client (no network, no boto3 needed)."""

import json
from datetime import datetime

import pytest

from awsemu.cli import cli
from awsemu.commands import dynamodb, overview, s3, sqs
from awsemu.paths import InstanceFiles


class FakePaginator:
    def __init__(self, pages):
        self.pages = pages
        self.kwargs = None

    def paginate(self, **kwargs):
        self.kwargs = kwargs
        return iter(self.pages)


class FakeClient:
    def __init__(self, **responses):
        self.responses = responses
        self.calls = []

    def get_paginator(self, op):
        return FakePaginator(self.responses[op])

    def __getattr__(self, op):
        def call(**kwargs):
            self.calls.append((op, kwargs))
            value = self.responses.get(op, {})
            return value(**kwargs) if callable(value) else value
        return call


@pytest.fixture
def running(isolated_home):
    files = InstanceFiles(9297)
    files.dir.mkdir(parents=True)
    files.ca.write_text("cert")
    return files


def patch_client(monkeypatch, module, fake):
    monkeypatch.setattr(module, "client", lambda service, port: fake)


def test_s3_ls_buckets(runner, monkeypatch, running):
    fake = FakeClient(list_buckets={"Buckets": [{"Name": "photos",
                                                 "CreationDate": datetime(2026, 11, 15, 9, 0)}]})
    patch_client(monkeypatch, s3, fake)
    result = runner.invoke(cli, ["s3", "ls"])
    assert result.exit_code == 0, result.output
    assert "photos" in result.output and "2026-11-15 09:00:00" in result.output


def test_s3_ls_objects(runner, monkeypatch, running):
    fake = FakeClient(list_objects_v2=[{
        "CommonPrefixes": [{"Prefix": "2026/"}],
        "Contents": [{"Key": "a.txt", "Size": 2048, "LastModified": datetime(2026, 1, 1)}],
    }])
    patch_client(monkeypatch, s3, fake)
    result = runner.invoke(cli, ["s3", "ls", "s3://photos/"])
    assert result.exit_code == 0, result.output
    assert "2026/" in result.output and "a.txt" in result.output and "2.0 KiB" in result.output


def test_s3_mb(runner, monkeypatch, running):
    fake = FakeClient()
    patch_client(monkeypatch, s3, fake)
    result = runner.invoke(cli, ["s3", "mb", "a", "s3://b"])
    assert result.exit_code == 0
    assert [c[1]["Bucket"] for c in fake.calls] == ["a", "b"]


def test_sqs_ls_and_send(runner, monkeypatch, running):
    url = "https://127.0.0.1:9297/000000000000/jobs"
    fake = FakeClient(
        list_queues={"QueueUrls": [url]},
        get_queue_attributes={"Attributes": {"ApproximateNumberOfMessages": "3",
                                             "ApproximateNumberOfMessagesNotVisible": "1",
                                             "ApproximateNumberOfMessagesDelayed": "0"}},
        get_queue_url={"QueueUrl": url},
        send_message={"MessageId": "m-1"},
    )
    patch_client(monkeypatch, sqs, fake)
    result = runner.invoke(cli, ["sqs", "ls"])
    assert result.exit_code == 0 and "jobs" in result.output and "3" in result.output
    result = runner.invoke(cli, ["sqs", "send", "jobs", '{"x":1}', "-a", "kind=test"])
    assert result.exit_code == 0, result.output
    op, kwargs = fake.calls[-1]
    assert op == "send_message" and kwargs["QueueUrl"] == url
    assert kwargs["MessageAttributes"]["kind"]["StringValue"] == "test"


def test_dynamodb_put_and_scan(runner, monkeypatch, running):
    fake = FakeClient(
        scan=[{"Items": [{"id": {"S": "u1"}, "age": {"N": "30"}}]}],
        describe_table={"Table": {"KeySchema": [{"AttributeName": "id", "KeyType": "HASH"}]}},
    )
    patch_client(monkeypatch, dynamodb, fake)
    result = runner.invoke(cli, ["ddb", "put", "users", '{"id": "u2", "age": 41}'])
    assert result.exit_code == 0, result.output
    assert fake.calls[0][1]["Item"] == {"id": {"S": "u2"}, "age": {"N": "41"}}
    result = runner.invoke(cli, ["ddb", "scan", "users", "--json"])
    assert json.loads(result.output) == [{"id": "u1", "age": 30}]


def test_overview_survives_failing_service(runner, monkeypatch, running):
    class Boom(Exception):
        pass

    def fake_client(service, port):
        if service == "s3":
            return FakeClient(list_buckets={"Buckets": [{"Name": "b1"}]})
        if service == "sqs":
            def fail(**_):
                raise Boom("not implemented")
            return FakeClient(list_queues=fail)
        return FakeClient(list_tables={"TableNames": []}, list_event_buses={"EventBuses": []},
                          **{op: [{}] for op in ("list_topics", "list_functions", "list_secrets",
                                                 "describe_parameters", "list_streams",
                                                 "list_state_machines", "describe_log_groups",
                                                 "list_roles")})

    monkeypatch.setattr(overview, "client", fake_client)
    result = runner.invoke(cli, ["overview"])
    assert result.exit_code == 0, result.output
    assert "S3 buckets" in result.output and "b1" in result.output
    assert "SQS queues" in result.output and "not implemented" in result.output
    assert "DynamoDB" not in result.output  # empty services hidden by default


def test_service_command_without_emulator(runner):
    result = runner.invoke(cli, ["s3", "ls"])
    assert result.exit_code == 1
    assert "awsemu start" in result.output


def test_client_errors_show_hint(runner, monkeypatch, running):
    class ClientError(Exception):  # same name as botocore's, which is what awsemu checks
        response = {"Error": {"Code": "AccessDenied",
                              "Message": "Sign the request with the emulator credentials"}}

    def boom(**_):
        raise ClientError("denied")

    patch_client(monkeypatch, s3, FakeClient(list_buckets=boom))
    result = runner.invoke(cli, ["s3", "ls"])
    assert result.exit_code == 1
    assert "AccessDenied" in result.output and 'eval "$(awsemu env)"' in result.output
