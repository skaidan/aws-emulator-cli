"""``awsemu call``: names, parameters and output, with a fake boto3 client."""

import io
import json

import click
import pytest

from awsemu.cli import cli
from awsemu.commands import call as call_mod
from tests.test_services import FakeClient, running  # noqa: F401  (fixture)

pytest.importorskip("botocore")


@pytest.mark.parametrize("written", ["ListBuckets", "list_buckets", "list-buckets", "listbuckets"])
def test_operation_names_in_every_spelling(written):
    assert call_mod.resolve_operation("s3", written) == "ListBuckets"


def test_close_names_are_suggested():
    with pytest.raises(click.BadParameter, match="did you mean dynamodb"):
        call_mod.resolve_service("dynamo")
    with pytest.raises(click.BadParameter, match="ListBuckets"):
        call_mod.resolve_operation("s3", "list-bucket")
    assert call_mod.resolve_service("Step-Functions") == "stepfunctions"


def test_params_from_json_pairs_and_files(tmp_path):
    body = tmp_path / "body.bin"
    body.write_bytes(b"\x00\x01")
    req = tmp_path / "req.json"
    req.write_text('{"Bucket": "b", "MaxKeys": 5}')
    assert call_mod.parse_params(f"@{req}", ["Prefix=logs/", "MaxKeys=10", "Body=@" + str(body),
                                              "Flag=true"]) == \
        {"Bucket": "b", "MaxKeys": 10, "Prefix": "logs/", "Body": b"\x00\x01", "Flag": True}
    with pytest.raises(click.BadParameter):
        call_mod.parse_params("[1]", [])
    with pytest.raises(click.BadParameter):
        call_mod.parse_params(None, ["nokey"])


def _patch(monkeypatch, fake):
    monkeypatch.setattr(call_mod, "client", lambda service, port: fake)


def test_call_prints_the_response_without_metadata(runner, monkeypatch, running):
    fake = FakeClient(list_buckets={"Buckets": [{"Name": "a"}, {"Name": "b"}],
                                    "ResponseMetadata": {"HTTPStatusCode": 200}})
    _patch(monkeypatch, fake)
    result = runner.invoke(cli, ["call", "s3", "list-buckets"])
    assert result.exit_code == 0, result.output
    assert json.loads(result.output) == {"Buckets": [{"Name": "a"}, {"Name": "b"}]}
    result = runner.invoke(cli, ["call", "s3", "ListBuckets", "--query", "Buckets[].Name"])
    assert json.loads(result.output) == ["a", "b"]
    result = runner.invoke(cli, ["call", "s3", "ListBuckets", "--query", "Buckets[0].Name"])
    assert result.output == "a\n"


def test_call_passes_the_parameters(runner, monkeypatch, running):
    fake = FakeClient(send_message={"MessageId": "m-1"})
    _patch(monkeypatch, fake)
    result = runner.invoke(cli, ["call", "sqs", "SendMessage", "--params", '{"QueueUrl": "u"}',
                                 "-p", "MessageBody=hi", "-p", "DelaySeconds=2"])
    assert result.exit_code == 0, result.output
    assert fake.calls == [("send_message", {"QueueUrl": "u", "MessageBody": "hi", "DelaySeconds": 2})]


def test_streaming_bodies_are_read_or_written(runner, monkeypatch, running, tmp_path):
    _patch(monkeypatch, FakeClient(get_object=lambda **_: {"Body": io.BytesIO(b"hello"), "ContentLength": 5}))
    result = runner.invoke(cli, ["call", "s3", "get-object", "-p", "Bucket=b", "-p", "Key=k"])
    assert json.loads(result.output)["Body"] == "hello"
    out = tmp_path / "copy"
    result = runner.invoke(cli, ["call", "s3", "get-object", "-p", "Bucket=b", "-p", "Key=k",
                                 "--out", str(out)])
    assert out.read_bytes() == b"hello" and "5 bytes written" in result.output
    _patch(monkeypatch, FakeClient(get_object=lambda **_: {"Body": io.BytesIO(b"\xff\xfe\x00")}))
    result = runner.invoke(cli, ["call", "s3", "get-object", "-p", "Bucket=b", "-p", "Key=k"])
    assert "3 bytes, base64" in json.loads(result.output)["Body"]


def test_paginate_merges_the_pages(runner, monkeypatch, running):
    class Pages(FakeClient):
        def can_paginate(self, method):
            return method == "list_queues"

        def get_paginator(self, method):
            return type("P", (), {"paginate": lambda self, **kw: iter([
                {"QueueUrls": ["q1"], "NextToken": "t"}, {"QueueUrls": ["q2"]}])})()

    _patch(monkeypatch, Pages())
    result = runner.invoke(cli, ["call", "sqs", "list-queues", "--paginate"])
    assert json.loads(result.output)["QueueUrls"] == ["q1", "q2"]
    result = runner.invoke(cli, ["call", "sqs", "get-queue-url", "--paginate", "-p", "QueueName=q"])
    assert result.exit_code == 2 and "no pages" in result.output


def test_wrong_parameters_exit_with_usage(runner, monkeypatch, running):
    import boto3

    real = boto3.session.Session(aws_access_key_id="x", aws_secret_access_key="y",
                                 region_name="us-east-1").client("s3", endpoint_url="https://127.0.0.1:1")
    _patch(monkeypatch, real)
    result = runner.invoke(cli, ["call", "s3", "get-object", "-p", "Bucket=b"])
    assert result.exit_code == 2 and "Key" in result.output and "s3-2006-03-01/GetObject" in result.output


def test_listings(runner):
    assert "dynamodb" in runner.invoke(cli, ["call"]).output.split()
    out = runner.invoke(cli, ["call", "sqs"]).output
    assert "send-message" in out and "SendMessage" in out
