"""Shadow mode: read-only calls also go to "AWS" (a second fake server), compared."""

import json

import pytest

from awsemu import proxy as px
from awsemu import shadow as sh
from awsemu.cli import cli
from tests.test_proxy import FakeAWS, client

pytest.importorskip("boto3")


def test_shape_and_compare():
    assert sh.shape(b'{"Table": {"Name": "t", "Keys": [{"A": 1}]}}') == {
        "Table",
        "Table.Name",
        "Table.Keys",
        "Table.Keys[].A",
    }
    assert sh.shape(b"<R><Name>x</Name><Item/></R>") == {"R", "Name", "Item"}
    same = sh.compare((200, {}, b'{"A": 1}'), (200, {}, b'{"A": 2}'))
    assert same["differs"] is False and same["missing_in_emulator"] == []  # values don't matter
    shape_diff = sh.compare((200, {}, b'{"A": 1}'), (200, {}, b'{"A": 1, "B": {"C": 1}}'))
    assert shape_diff["differs"] and shape_diff["missing_in_emulator"] == ["B", "B.C"]
    err = sh.compare((200, {}, b"{}"), (400, {"x-amzn-errortype": "ValidationException"}, b"{}"))
    assert err["differs"] and err["aws"]["error"] == "ValidationException" and not err["same_status"]


@pytest.fixture
def two(tmp_path):
    emulator_dir, aws_dir = tmp_path / "emu", tmp_path / "aws"
    emulator_dir.mkdir()
    aws_dir.mkdir()
    emulator, aws = FakeAWS(emulator_dir), FakeAWS(aws_dir)
    yield emulator, aws, aws_dir / "cert.pem"
    emulator.shutdown()
    aws.shutdown()
    emulator.server_close()
    aws.server_close()


def test_only_reads_go_to_aws_signed_with_the_profile(two, profile, tmp_path):
    from awsemu import realaccount as ra

    emulator, aws, aws_cert = two
    shadow = sh.Shadow(
        profile,
        None,
        tmp_path / "shadow.jsonl",
        max_calls=2,
        endpoint_for=lambda service: f"https://127.0.0.1:{aws.port}",
        verify=str(aws_cert),
        session=ra.session(profile),
    )
    server = px.ProxyServer(emulator.port, 0, calls_file=None, shadow=shadow)
    server.start_thread()
    try:
        ddb = client(server, "dynamodb")
        ddb.put_item(TableName="orders", Item={"id": {"S": "1"}})  # a write: never sent to AWS
        for _ in range(3):  # reads: the limit is 2
            try:
                ddb.describe_table(TableName="orders")
            except Exception:
                pass
        shadow.close()
    finally:
        server.shutdown()
        server.server_close()
    sent = [h for _, _, h, _ in aws.seen]
    assert len(sent) == 2 and all(h.get("X-Amz-Target", "").endswith("DescribeTable") for h in sent)
    assert all("Credential=AKIDEV/" in h["Authorization"] for h in sent)  # re-signed with the profile
    assert all("eu-west-1/dynamodb/aws4_request" in h["Authorization"] for h in sent)
    entries = [json.loads(x) for x in (tmp_path / "shadow.jsonl").read_text().splitlines()]
    assert len(entries) == 2 and entries[0]["operation"] == "DescribeTable" and entries[0]["differs"] is False
    assert shadow.skipped == 2  # the write, and the read over the limit


def test_shadow_command(runner, isolated_home):
    files = px.ProxyFiles(9297)
    files.dir.mkdir(parents=True)
    rows = [
        {
            "id": 1,
            "service": "dynamodb",
            "operation": "DescribeTable",
            "resource": "t",
            "differs": True,
            "emulator": {"status": 200, "error": None},
            "aws": {"status": 400, "error": "ResourceNotFoundException"},
            "same_status": False,
            "same_error": False,
        },
        {
            "id": 2,
            "service": "sqs",
            "operation": "ListQueues",
            "resource": "",
            "differs": False,
            "emulator": {"status": 200, "error": None},
            "aws": {"status": 200, "error": None},
            "same_status": True,
            "same_error": True,
            "missing_in_emulator": [],
            "extra_in_emulator": [],
        },
        {"id": 3, "service": "s3", "operation": "ListBuckets", "resource": "", "differs": None, "failed": "boom"},
    ]
    files.shadow.write_text("".join(json.dumps(r) + "\n" for r in rows))
    out = runner.invoke(cli, ["proxy", "shadow"]).output
    assert "AWS 400 ResourceNotFoundException, emulator 200" in out and "2 call(s) compared, 1 differ" in out
    data = json.loads(runner.invoke(cli, ["proxy", "shadow", "--json"]).output)
    assert data["differ"] == 1 and data["failed"] == 1 and [c["id"] for c in data["calls"]] == [1]


def test_start_needs_confirmation_without_a_terminal(runner, profile, monkeypatch):
    import awsemu.realaccount as ra

    class Sts:
        def get_caller_identity(self):
            return {"Account": "123456789012", "Arn": "arn:aws:iam::123456789012:user/dev"}

    monkeypatch.setattr(ra, "client", lambda sess, service: Sts())
    result = runner.invoke(cli, ["proxy", "start", "-d", "--shadow", "dev"])
    assert result.exit_code == 2 and "needs --yes" in result.output and "123456789012" in result.output
