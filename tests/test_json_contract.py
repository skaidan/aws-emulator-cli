"""The --json output is a stable interface (docs/scripting.md). These tests pin
its shape: if one fails, you changed the contract. Update docs/scripting.md and
CHANGELOG.md (as a breaking change) together with the test.
"""

import gzip
import json
from datetime import datetime, UTC

import pytest

from awsemu.cli import cli
from awsemu.commands import dynamodb as ddb_mod
from awsemu.commands import kinesis as kinesis_mod
from awsemu.commands import s3 as s3_mod
from awsemu.commands import sns as sns_mod
from awsemu.commands import sqs as sqs_mod
from tests.schema_check import schema_for, validate
from tests.test_services import FakeClient

NOW = datetime(2026, 11, 16, 12, 0, tzinfo=UTC)


def run_json(runner, *args):
    """Run ``awsemu ARGS`` and parse its JSON, validated against its published schema."""
    result = runner.invoke(cli, list(args))
    assert result.exit_code in (0, 1, 3), result.output
    data = json.loads(result.output)
    name = schema_for(args)
    if name:
        validate(name, data)
    elif isinstance(data, list):
        validate("aws-list", data)  # AWS resources passed through
    return data


def use(monkeypatch, module, **clients):
    monkeypatch.setattr(module, "client", lambda service, port: clients[service])


def test_status(runner, free_port):
    result = runner.invoke(cli, ["--port", str(free_port), "status", "--json"])
    assert result.exit_code == 3  # not healthy: same exit code as without --json
    data = json.loads(result.output)
    validate("status", data)
    assert set(data) == {
        "port",
        "status",
        "detail",
        "endpoint",
        "mode",
        "pid",
        "container",
        "uptime_seconds",
        "auth",
        "files",
        "log",
    }
    assert data["status"] in ("healthy", "unhealthy", "stopped") and data["port"] == free_port
    assert isinstance(run_json(runner, "--port", str(free_port), "status", "--all", "--json"), list)


def test_overview(runner, monkeypatch, running):
    def fake(service, port):
        if service == "s3":
            return FakeClient(list_buckets={"Buckets": [{"Name": "b1"}]})
        if service == "sqs":

            def boom(**_):
                raise RuntimeError("nope")

            return FakeClient(list_queues=boom)
        return FakeClient(
            list_tables={"TableNames": []},
            list_event_buses={"EventBuses": []},
            **{
                op: [{}]
                for op in (
                    "list_topics",
                    "list_functions",
                    "list_secrets",
                    "describe_parameters",
                    "list_streams",
                    "list_state_machines",
                    "describe_log_groups",
                    "list_roles",
                )
            },
        )

    monkeypatch.setattr("awsemu.clients.client", fake)
    data = run_json(runner, "overview", "--json")
    assert data["s3"] == {"label": "S3 buckets", "items": ["b1"], "error": None}
    assert data["sqs"]["items"] == [] and "nope" in data["sqs"]["error"]
    assert all(set(v) == {"label", "items", "error"} for v in data.values())


def test_sqs_ls(runner, monkeypatch, running):
    use(
        monkeypatch,
        sqs_mod,
        sqs=FakeClient(
            list_queues={"QueueUrls": ["https://x/000000000000/jobs"]},
            get_queue_attributes={
                "Attributes": {
                    "ApproximateNumberOfMessages": "3",
                    "ApproximateNumberOfMessagesNotVisible": "1",
                    "ApproximateNumberOfMessagesDelayed": "0",
                }
            },
        ),
    )
    assert run_json(runner, "sqs", "ls", "--json") == [
        {"name": "jobs", "url": "https://x/000000000000/jobs", "visible": 3, "in_flight": 1, "delayed": 0}
    ]


def test_sns_ls(runner, monkeypatch, running):
    arn = "arn:aws:sns:us-east-1:000000000000:orders"
    sub = {
        "TopicArn": arn,
        "Protocol": "sqs",
        "Endpoint": "arn:aws:sqs:us-east-1:000000000000:q",
        "SubscriptionArn": arn + ":1",
    }
    use(
        monkeypatch,
        sns_mod,
        sns=FakeClient(list_topics=[{"Topics": [{"TopicArn": arn}]}], list_subscriptions=[{"Subscriptions": [sub]}]),
    )
    assert run_json(runner, "sns", "ls", "--json") == [{"name": "orders", "arn": arn, "subscriptions": [sub]}]


def test_dynamodb_ls(runner, monkeypatch, running):
    table = {
        "TableName": "events",
        "ItemCount": 2,
        "TableStatus": "ACTIVE",
        "KeySchema": [{"AttributeName": "user", "KeyType": "HASH"}, {"AttributeName": "at", "KeyType": "RANGE"}],
        "AttributeDefinitions": [
            {"AttributeName": "user", "AttributeType": "S"},
            {"AttributeName": "at", "AttributeType": "N"},
        ],
    }
    use(
        monkeypatch,
        ddb_mod,
        dynamodb=FakeClient(list_tables=[{"TableNames": ["events"]}], describe_table={"Table": table}),
    )
    assert run_json(runner, "ddb", "ls", "--json") == [
        {
            "name": "events",
            "partition_key": {"name": "user", "type": "S"},
            "sort_key": {"name": "at", "type": "N"},
            "item_count": 2,
            "status": "ACTIVE",
        }
    ]


def test_s3_ls_with_prefix_and_iso_dates(runner, monkeypatch, running):
    use(
        monkeypatch,
        s3_mod,
        s3=FakeClient(
            list_objects_v2=[
                {"CommonPrefixes": [{"Prefix": "a/"}], "Contents": [{"Key": "x.txt", "Size": 1, "LastModified": NOW}]}
            ]
        ),
    )
    data = run_json(runner, "s3", "ls", "photos", "--json")
    assert set(data) == {"prefixes", "objects"}
    assert data["prefixes"] == ["a/"] and data["objects"][0]["LastModified"] == "2026-11-16T12:00:00+00:00"


def test_kinesis_read_lines(runner, monkeypatch, running):
    pages = iter(
        [
            {
                "Records": [
                    {"SequenceNumber": "1", "PartitionKey": "k", "Data": b'{"n":1}', "ApproximateArrivalTimestamp": NOW}
                ],
                "NextShardIterator": "i2",
                "MillisBehindLatest": 0,
            },
            {"Records": [], "NextShardIterator": "i3", "MillisBehindLatest": 0},
        ]
    )
    use(
        monkeypatch,
        kinesis_mod,
        kinesis=FakeClient(
            list_shards=[{"Shards": [{"ShardId": "s-0"}]}],
            get_shard_iterator={"ShardIterator": "i1"},
            get_records=lambda **_: next(pages),
        ),
    )
    result = runner.invoke(cli, ["kinesis", "read", "clicks", "--json"])
    lines = [json.loads(line) for line in result.output.strip().splitlines()]
    for line in lines:
        validate("kinesis-read-line", line)
    assert lines == [
        {"shard": "s-0", "sequence": "1", "key": "k", "data": '{"n": 1}', "arrived": "2026-11-16T12:00:00+00:00"}
    ]


def test_fidelity(runner, isolated_home, monkeypatch):
    from awsemu import fidelity as fid

    scores = {
        "commit": "abc",
        "schemaVersion": 1,
        "scoredAt": "2026-11-14T18:34:58+00:00",
        "units": [
            {
                "unitId": "t1",
                "outcome": "fail",
                "services": ["com.amazonaws.s3#AmazonS3"],
                "detail": {
                    "operation": "PutObject",
                    "mismatch": "status",
                    "expected": {"status": 400},
                    "actual": {"status": 200},
                },
            }
        ],
    }
    fid.cache_dir().mkdir(parents=True)
    (fid.cache_dir() / "v1.0.385.json.gz").write_bytes(gzip.compress(json.dumps(scores).encode()))
    monkeypatch.setattr(fid, "installed_version", lambda binary=None: "1.0.385")
    data = run_json(runner, "fidelity", "s3", "--failures", "--json")
    assert set(data) == {"release", "commit", "scored_at", "installed", "services"}
    assert set(data["services"]["s3"]) == {"passed", "total", "multi_service_passed", "multi_service_total", "failures"}
    assert set(data["services"]["s3"]["failures"][0]) == {"test", "operation", "mismatch", "expected", "actual", "step"}


def test_doctor(runner):
    data = run_json(runner, "doctor", "--json")
    assert set(data) == {"ok", "problems", "checks"}
    assert all(set(c) == {"check", "result", "detail", "fix"} for c in data["checks"])
    assert {c["result"] for c in data["checks"]} <= {"ok", "warn", "fail"}
    assert data["problems"] == sum(c["result"] == "fail" for c in data["checks"])


@pytest.mark.parametrize(
    "args,module,service,fake,expected",
    [
        (
            ["lambda", "ls", "--json"],
            "lambda_",
            "lambda",
            {"list_functions": [{"Functions": [{"FunctionName": "f"}]}]},
            [{"FunctionName": "f"}],
        ),
        (
            ["sfn", "ls", "--json"],
            "sfn",
            "stepfunctions",
            {"list_state_machines": [{"stateMachines": [{"name": "m", "creationDate": NOW}]}]},
            [{"name": "m", "creationDate": "2026-11-16T12:00:00+00:00"}],
        ),
        (
            ["events", "buses", "--json"],
            "events",
            "events",
            {"list_event_buses": {"EventBuses": [{"Name": "default"}]}},
            [{"Name": "default"}],
        ),
        (
            ["sns", "subs", "--json"],
            "sns",
            "sns",
            {"list_subscriptions": [{"Subscriptions": [{"Protocol": "sqs"}]}]},
            [{"Protocol": "sqs"}],
        ),
    ],
)
def test_aws_shapes_pass_through(runner, monkeypatch, running, args, module, service, fake, expected):
    """Listings of AWS resources keep AWS's own field names."""
    import importlib

    mod = importlib.import_module(f"awsemu.commands.{module}")
    use(monkeypatch, mod, **{service: FakeClient(**fake)})
    assert run_json(runner, *args) == expected


def test_every_listing_has_json():
    """New listing commands must offer --json too."""
    import click

    missing = []

    def walk(cmd, path):
        ctx = click.Context(cmd)
        if isinstance(cmd, click.Group):
            for n in cmd.list_commands(ctx):
                walk(cmd.get_command(ctx, n), path + [n])
            return
        if path[-1] in ("ls", "subs", "buses", "executions", "rules", "doctor", "status") and not any(
            "--json" in p.opts for p in cmd.params if hasattr(p, "opts")
        ):
            missing.append(" ".join(path))

    walk(cli, [])
    assert missing == []


def test_check(runner, monkeypatch, tmp_path):
    from tests.test_check import FILES, MANIFEST, SCORES
    from awsemu import fidelity as fid

    d = fid.cache_dir()
    d.mkdir(parents=True)
    (d / "v1.0.385.json.gz").write_bytes(gzip.compress(json.dumps(SCORES).encode()))
    (d / "v1.0.385.release.json").write_text(json.dumps({"suite": "v1.0.0"}))
    (d / "manifest-v1.0.0.jsonl.gz").write_bytes(gzip.compress("\n".join(json.dumps(r) for r in MANIFEST).encode()))
    monkeypatch.setattr(fid, "installed_version", lambda binary=None: "1.0.385")
    for name, text in FILES.items():
        (tmp_path / name).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / name).write_text(text)
    data = run_json(runner, "check", str(tmp_path), "--json", "--no-explain")
    assert set(data) == {
        "release",
        "suite",
        "scanned_files",
        "sources",
        "operations",
        "uncovered",
        "services",
        "summary",
    }
    op = data["operations"][0]
    assert set(op) == {"operation", "service", "locations", "tests", "passed", "differences", "other_failing"}
    assert set(op["locations"][0]) == {"file", "line", "source"}
    assert set(op["differences"][0]) == {
        "test",
        "kind",
        "operation",
        "mismatch",
        "expected",
        "actual",
        "step",
        "at_operation",
        "matches_usage",
        "url",
        "issues",
        "fixed_in",
    }
    svc = next(s for s in data["services"] if s["cloudformation"])
    assert set(svc) == {"service", "sources", "tests", "passed", "resources", "cloudformation"}
    assert set(svc["cloudformation"]) == {"tests", "passed", "failing"}
    assert set(svc["resources"][0]) == {"type", "file", "line", "source"}
    assert set(data["summary"]) == {
        "operations",
        "services",
        "operations_with_differences",
        "differences",
        "explained_by_issues",
        "fixed_in_latest",
        "latest",
    }

    fid.cache_dir().joinpath("v1.0.390.json.gz").write_bytes(gzip.compress(json.dumps(SCORES).encode()))
    cmp = run_json(runner, "fidelity", "--compare", "1.0.390", "sqs", "--json")
    assert set(cmp) == {"from", "to", "services"}
    assert set(cmp["from"]) == {"release", "suite"}
    assert set(cmp["services"]["sqs"]) == {
        "from",
        "to",
        "fixed",
        "regressed",
        "added_passing",
        "added_failing",
        "removed",
    }
    assert set(cmp["services"]["sqs"]["from"]) == {"passed", "total"}


def test_install_list(runner, monkeypatch):
    from awsemu import fidelity as fid
    from awsemu import install as inst

    monkeypatch.setattr(inst, "list_versions", lambda: ["1.0.390"])
    monkeypatch.setattr(fid, "installed_version", lambda binary=None: None)
    assert run_json(runner, "install", "--list", "--json") == {
        "versions": ["1.0.390"],
        "installed": None,
        "pinned": None,
    }


CALL_KEYS = {
    "id",
    "time",
    "service",
    "operation",
    "resource",
    "method",
    "path",
    "status",
    "error",
    "latency_ms",
    "request_id",
    "fault",
    "bytes_in",
    "bytes_out",
}


def test_proxy(runner, monkeypatch):
    from awsemu import proxy as px

    files = px.ProxyFiles(9297)
    files.dir.mkdir(parents=True)
    call = dict.fromkeys(CALL_KEYS) | {
        "id": 1,
        "time": "2026-11-25T10:00:00.000+00:00",
        "service": "s3",
        "operation": "GetObject",
        "resource": "b/k",
        "method": "GET",
        "path": "/b/k",
        "status": 200,
        "latency_ms": 1.0,
        "bytes_in": 0,
        "bytes_out": 5,
    }
    files.calls.write_text(json.dumps(call) + "\n")
    calls = run_json(runner, "--port", "9297", "proxy", "calls", "--json")
    assert len(calls) == 1 and set(calls[0]) == CALL_KEYS

    result = runner.invoke(cli, ["--port", "9297", "proxy", "status", "--json"])
    assert result.exit_code == 3
    assert json.loads(result.output) == {"running": False, "emulator_port": 9297}
    validate("proxy-status", json.loads(result.output))

    state = {
        "pid": 1,
        "port": 9298,
        "endpoint_url": "https://127.0.0.1:9298",
        "ca": "/ca.pem",
        "calls": str(files.calls),
    }
    monkeypatch.setattr(px, "running", lambda port: state)
    answers = {
        "health": {"ok": True, "emulator_port": 9297, "calls": 1},
        "faults": {"rules": [{"spec": "s3=503", "hits": 2}]},
    }
    monkeypatch.setattr(px, "admin", lambda st, method, route, payload=None, timeout=10: answers[route])
    data = run_json(runner, "--port", "9297", "proxy", "status", "--json")
    assert set(data) == {
        "running",
        "emulator_port",
        "port",
        "endpoint_url",
        "pid",
        "ca",
        "calls",
        "faults",
        "calls_file",
    }
    assert data["faults"] == ["s3=503"]
    assert run_json(runner, "--port", "9297", "proxy", "faults", "--json") == [
        {"rule": "s3=503", "hits": 2, "active": True, "remaining_s": None}
    ]


def test_snapshot_ls(runner, monkeypatch):

    monkeypatch.setattr("awsemu.seeding.export", lambda *a, **k: ({"version": 1, "queues": [{"name": "q"}]}, []))
    monkeypatch.setattr("awsemu.fidelity.installed_version", lambda binary=None: None)
    assert runner.invoke(cli, ["snapshot", "save", "s1"]).exit_code == 0
    (row,) = run_json(runner, "snapshot", "ls", "--json")
    assert set(row) == {"name", "created_at", "port", "emulator_version", "counts", "secrets", "path"}
    assert row["counts"] == {"queues": 1}

    # a folder without snapshot.json (copied by hand, or a crash while saving) still lists, and fits the schema
    from awsemu.seeding import snapshots_dir

    bare = snapshots_dir() / "bare"
    bare.mkdir(parents=True)
    (bare / "seed.yaml").write_text("version: 1\n")
    rows = {r["name"]: r for r in run_json(runner, "snapshot", "ls", "--json")}
    assert rows["bare"]["created_at"] is None and rows["bare"]["secrets"] is None


def test_schemas_reject_what_breaks_the_contract():
    jsonschema = pytest.importorskip("jsonschema")
    with pytest.raises(jsonschema.ValidationError):
        validate("status", {"port": "9297"})  # a missing field, and the wrong type
    with pytest.raises(jsonschema.ValidationError):
        validate("doctor", {"ok": True, "problems": 0, "checks": [{"check": "x", "result": "maybe"}]})
    validate("sqs-ls", [{"name": "q", "url": "u", "visible": 1, "in_flight": 0, "delayed": 0, "new_field": 1}])


def test_every_schema_names_its_command():
    from awsemu import schemas

    assert set(schemas.SCHEMAS) == set(schemas.COMMANDS)
