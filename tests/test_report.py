"""``awsemu report``: a draft emulator issue from a logged call."""

import json
from urllib.parse import parse_qs, urlsplit

import pytest

from awsemu import proxy as px
from awsemu import report as rp
from awsemu.cli import cli

pytest.importorskip("botocore")


def _call(i, op, resource, status=200, error=None, fault=None, bodies=True, body='{"TableName": "orders"}'):
    call = {
        "id": i,
        "time": f"2026-11-26T12:00:0{i}.000+00:00",
        "service": "dynamodb",
        "operation": op,
        "resource": resource,
        "method": "POST",
        "path": "/",
        "status": status,
        "error": error,
        "latency_ms": 3.0,
        "request_id": f"rid-{i}",
        "fault": fault,
        "bytes_in": 10,
        "bytes_out": 20,
    }
    if bodies:
        call["request"] = {
            "method": "POST",
            "path": "/",
            "headers": [
                ["Authorization", "***"],
                ["X-Amz-Date", "20261126T120000Z"],
                ["Content-Type", "application/x-amz-json-1.0"],
                ["X-Amz-Target", f"DynamoDB_20120810.{op}"],
                ["User-Agent", "Boto3/1.44 md/Botocore#1.44"],
            ],
            "body": {"size": len(body), "text": body},
        }
        call["response"] = {
            "status": status,
            "headers": [["Content-Type", "application/x-amz-json-1.0"], ["x-amzn-RequestId", "rid"]],
            "body": {"size": 2, "text": json.dumps({"__type": error or "", "message": "nope"})},
        }
    return call


def test_the_draft_follows_the_issue_form():
    earlier = [_call(1, "CreateTable", "orders"), _call(2, "PutItem", "users")]
    call = _call(3, "TransactWriteItems", "orders", 400, "ValidationException")
    log = [
        '{"timestamp": "2026-11-26T12:00:03.100Z", "level": "WARN", "message": "transact failed"}',
        '{"timestamp": "2026-11-26T11:00:00Z", "level": "INFO", "message": "long before"}',
    ]
    draft = rp.build(call, earlier, "aws-emulator 1.0.611", log)
    assert draft.title.startswith("dynamodb TransactWriteItems: ValidationException")
    f = draft.fields
    assert "answered **400** with `ValidationException`" in f["actual"] and "HTTP/1.1 400" in f["actual"]
    assert "transact failed" in f["actual"] and "long before" not in f["actual"]
    assert "Authorization" not in f["reproduction"] and "X-Amz-Date" not in f["reproduction"]
    assert "X-Amz-Target: DynamoDB_20120810.TransactWriteItems" in f["reproduction"]
    assert "`dynamodb` `CreateTable` → 200" in f["reproduction"] and "users" not in f["reproduction"]
    assert 'awsemu call dynamodb transact-write-items --params \'{"TableName": "orders"}\'' in f["reproduction"]
    assert "Client: `Boto3/1.44" in f["reproduction"]
    assert "docs.aws.amazon.com/goto/WebAPI/dynamodb-2012-08-10/TransactWriteItems" in f["expected"]
    assert f["version"] == "aws-emulator 1.0.611" and "request ID `rid-3`" in f["context"]
    md = draft.markdown()
    assert md.index("## What happened") < md.index("## What you expected") < md.index("## Steps to reproduce")

    query = parse_qs(urlsplit(draft.url()).query)
    assert query["template"] == ["behavior-differs.yml"] and query["title"] == [draft.title]
    assert query["version"] == ["aws-emulator 1.0.611"] and "ValidationException" in query["actual"][0]


def test_masked_values_and_missing_bodies():
    masked = _call(1, "PutItem", "orders", 400, "ValidationException", body='{"Item": {"Password": "***"}}')
    assert "awsemu call" not in rp.build(masked, [], None, []).fields["reproduction"]  # can't replay ***
    bare = rp.build(_call(2, "PutItem", "orders", 500, "InternalFailure", bodies=False), [], None, [])
    assert "--bodies" in bare.fields["actual"] and "`POST /`" in bare.fields["reproduction"]
    with pytest.raises(rp.ReportError, match="injected"):
        rp.build(_call(3, "PutItem", "orders", 400, "ThrottlingException", fault="dynamodb=throttle"), [], None, [])


def test_long_drafts_still_make_a_valid_link():
    call = _call(1, "PutItem", "orders", 400, "ValidationException", body=json.dumps({"x": "y" * 20000}))
    url = rp.build(call, [], "aws-emulator 1", []).url()
    assert len(url) <= rp.MAX_URL and "version=" in url


def test_command(runner, isolated_home, monkeypatch, tmp_path):
    import awsemu.fidelity as fid

    monkeypatch.setattr(fid, "installed_version", lambda binary=None: "1.0.611")
    files = px.ProxyFiles(9297)
    files.dir.mkdir(parents=True)
    calls = [
        _call(1, "CreateTable", "orders"),
        _call(2, "PutItem", "orders", 400, "ValidationException"),
        _call(3, "PutItem", "orders", 400, "ThrottlingException", fault="dynamodb=throttle"),
    ]
    files.calls.write_text("".join(json.dumps(c) + "\n" for c in calls))
    last = runner.invoke(cli, ["report"])  # 'last' skips the injected fault
    assert last.exit_code == 0, last.output
    assert "# dynamodb PutItem: ValidationException" in last.output and "aws-emulator 1.0.611" in last.output
    out = tmp_path / "draft.md"
    assert runner.invoke(cli, ["report", "2", "-o", str(out)]).exit_code == 0 and "## Steps" in out.read_text()
    assert runner.invoke(cli, ["report", "2", "--url"]).output.startswith(rp.ISSUE_FORM)
    injected = runner.invoke(cli, ["report", "3"])
    assert injected.exit_code == 1 and "injected" in injected.output
    assert runner.invoke(cli, ["report", "9"]).exit_code == 1
    assert runner.invoke(cli, ["report", "abc"]).exit_code == 2
