"""awsemu check: the scanner, the cross-reference with the fidelity tests, the command."""

import gzip
import json
import textwrap

import pytest

from awsemu import check as chk
from awsemu import fidelity as fid
from awsemu import scan as sc
from awsemu.cli import cli

DDB = "com.amazonaws.dynamodb#DynamoDB_20120810"
SQS = "com.amazonaws.sqs#AmazonSQS"
SFN = "com.amazonaws.sfn#AWSStepFunctions"
LOGS = "com.amazonaws.cloudwatchlogs#Logs_20140328"
CFN = "com.amazonaws.cloudformation#CloudFormation"
SNS = "com.amazonaws.sns#AmazonSimpleNotificationService"
KINESIS = "com.amazonaws.kinesis#Kinesis_20131202"
S3 = "com.amazonaws.s3#AmazonS3"


def wire(uid, outcome, service, *ops, failed=None, **detail):
    steps = [{"operation": op, "outcome": "mismatch" if op == failed else "pass"} for op in ops]
    d = {"steps": steps, **detail}
    if failed:
        d.update(operation=failed, failedStep=ops.index(failed) + 1, totalSteps=len(ops))
    else:
        d["operation"] = ops[0]
    return {"unitId": uid, "kind": "wire", "outcome": outcome, "services": [service], "detail": d}


def behavioral(uid, outcome, *services):
    return {"unitId": uid, "kind": "behavioral", "outcome": outcome, "services": list(services),
            "detail": {"checkId": uid}}


SCORES = {"commit": "abc", "schemaVersion": 1, "scoredAt": "2026-11-16T10:00:00+00:00", "units": [
    wire("ddb-tx-1", "fail", DDB, "CreateTable", "TransactWriteItems", failed="TransactWriteItems",
         mismatch="status", expected={"status": 400, "errorCode": "ValidationException"},
         actual={"status": 200}),
    wire("ddb-tx-2", "pass", DDB, "CreateTable", "TransactWriteItems"),
    wire("ddb-get-1", "fail", DDB, "CreateTable", "GetItem", failed="CreateTable", mismatch="body",
         expected={"status": 400, "errorCode": "ValidationException"},
         actual={"status": 400, "errorCode": "ValidationException"}),
    wire("sqs-send-1", "pass", SQS, "CreateQueue", "SendMessage"),
    behavioral("dynamodb.orders-flow", "fail", DDB),
    behavioral("dynamodb.big-flow", "fail", DDB),
    behavioral("sqs.queue-flow", "pass", SQS),
    behavioral("stepfunctions.start", "pass", SFN),
    behavioral("logs.put", "pass", LOGS),
    behavioral("cloudformation__dynamodb.cfn-table", "fail", CFN, DDB),
    behavioral("cloudformation__dynamodb.cfn-table-ok", "pass", CFN, DDB),
    behavioral("sns.publish", "pass", SNS),
    behavioral("kinesis.put", "pass", KINESIS),
    behavioral("s3.put", "pass", S3),
    {"unitId": "skipped-one", "kind": "wire", "outcome": "skipped", "services": [DDB]},
]}

MANIFEST = [
    {"check_id": "dynamodb.orders-flow", "service": "dynamodb", "labels": ["plane:data"],
     "path": "behavioral/dynamodb/check_orders_flow.py",
     "operations": ["dynamodb:GetItem", "dynamodb:TransactWriteItems", "sts:GetCallerIdentity"]},
    {"check_id": "dynamodb.big-flow", "service": "dynamodb", "labels": ["plane:data"],
     "path": "behavioral/dynamodb/check_big_flow.py",
     "operations": ["dynamodb:GetItem", "dynamodb:CreateBackup", "dynamodb:Scan"]},
    {"check_id": "sqs.queue-flow", "service": "sqs", "labels": [], "path": "behavioral/sqs/x.py",
     "operations": ["sqs:CreateQueue", "sqs:SendMessage", "sqs:ReceiveMessage"]},
    {"check_id": "stepfunctions.start", "service": "stepfunctions", "labels": [], "path": "p",
     "operations": ["stepfunctions:StartExecution"]},
    {"check_id": "logs.put", "service": "logs", "labels": [], "path": "p",
     "operations": ["logs:PutLogEvents"]},
    {"check_id": "cloudformation__dynamodb.cfn-table", "service": "cloudformation__dynamodb",
     "labels": [], "path": "p", "operations": ["cloudformation:CreateStack"]},
    {"check_id": "cloudformation__dynamodb.cfn-table-ok", "service": "cloudformation__dynamodb",
     "labels": [], "path": "p", "operations": ["cloudformation:CreateStack"]},
    {"check_id": "sns.publish", "service": "sns", "labels": [], "path": "p", "operations": ["sns:Publish"]},
    {"check_id": "kinesis.put", "service": "kinesis", "labels": [], "path": "p",
     "operations": ["kinesis:PutRecord"]},
    {"check_id": "s3.put", "service": "s3", "labels": [], "path": "p",
     "operations": ["s3:PutObject", "s3:GetObject"]},
]

FILES = {
    "app/orders.py": """
        import boto3
        ddb = boto3.client("dynamodb")
        sqs = boto3.client(service_name="sqs")
        def place():
            ddb.transact_write_items(TransactItems=[])
            sqs.send_message(QueueUrl="q", MessageBody="m")
            {}.update(a=1)
    """,
    "app/repo.py": """
        class Repo:
            def get(self, table, k):
                return table.get_item(Key=k)
    """,
    "web/index.ts": """
        import { SFNClient, StartExecutionCommand } from "@aws-sdk/client-sfn";
        import { CloudWatchLogsClient, PutLogEventsCommand } from "@aws-sdk/client-cloudwatch-logs";
        await sfn.send(new StartExecutionCommand({}));
    """,
    "web/legacy.js": """
        const AWS = require('aws-sdk');
        const s3 = new AWS.S3();
        s3.putObject({}).promise();
    """,
    "svc/Main.java": """
        import software.amazon.awssdk.services.sns.SnsClient;
        class Main { void f(SnsClient sns) { sns.publish(PublishRequest.builder().build()); } }
    """,
    "svc/main.go": """
        import "github.com/aws/aws-sdk-go-v2/service/kinesis"
        func f(c *kinesis.Client) { c.PutRecord(ctx, &kinesis.PutRecordInput{}) }
    """,
    "infra/main.tf": """
        resource "aws_dynamodb_table" "orders" {}
        resource "aws_cloudwatch_event_rule" "nightly" {}
        data "aws_caller_identity" "me" {}
    """,
    "infra/template.yaml": """
        Resources:
          Table:
            Type: AWS::DynamoDB::Table
          Fn:
            Type: "AWS::Serverless::Function"
    """,
    "cdk/stack.py": """
        from aws_cdk import Stack, aws_sqs as sqs, aws_stepfunctions_tasks as tasks
    """,
    "node_modules/pkg/index.js": """
        import { S3Client, DeleteBucketCommand } from "@aws-sdk/client-s3";
    """,
    "README.md": "boto3.client('dynamodb').delete_table()",
}


@pytest.fixture
def project(tmp_path):
    root = tmp_path / "proj"
    for name, text in FILES.items():
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(textwrap.dedent(text).lstrip())
    return root


@pytest.fixture
def index():
    return chk.Index(SCORES, MANIFEST)


def test_names_resolve_every_spelling(index):
    n = index.names
    assert n.resolve("cloudwatch-logs") == n.resolve("CloudWatchLogs") == n.resolve("logs") == "logs"
    assert n.resolve("sfn") == n.resolve("StepFunctions") == n.resolve("states") == "stepfunctions"
    assert n.resolve("DynamoDB") == "dynamodb"
    assert n.resolve("nonsense") is None
    assert sc.score_name("logs") == "cloudwatchlogs"
    assert sc.score_name("cognito-identity") == "cognitoidentity"


def test_index_reads_wire_and_manifest_operations(index):
    tests = {t.id: t for t in index.tests}
    assert "skipped-one" not in tests
    assert tests["ddb-tx-1"].ops == {"dynamodb:CreateTable", "dynamodb:TransactWriteItems"}
    assert tests["ddb-tx-1"].failed_at == "dynamodb:TransactWriteItems"
    assert tests["dynamodb.orders-flow"].path == "behavioral/dynamodb/check_orders_flow.py"
    assert tests["logs.put"].services == {"logs"}
    assert index.resolve_call("transact_write_items", {"dynamodb"}) == ["dynamodb:TransactWriteItems"]
    assert index.resolve_call("PutRecordInput"[:-5], {"kinesis"}) == ["kinesis:PutRecord"]


def test_scan_finds_code_and_infrastructure(project, index):
    result = sc.scan([project], index.known_services)
    assert "node_modules/pkg/index.js" not in result.by_file
    assert "README.md" not in result.by_file
    assert set(result.by_file["app/orders.py"].services) == {"dynamodb", "sqs"}
    assert set(result.by_file["web/index.ts"].services) == {"stepfunctions", "logs"}
    assert set(result.by_file["web/legacy.js"].services) == {"s3"}
    iac = result.iac()
    assert {t for t, _ in iac["dynamodb"]} == {"aws_dynamodb_table", "AWS::DynamoDB::Table"}
    assert {t for t, _ in iac["lambda"]} == {"AWS::Serverless::Function"}
    assert "sts" in iac
    assert "events" not in iac  # not in this (synthetic) manifest, so not a known service
    assert {t for t, _ in iac["sqs"]} == {"cdk:sqs"}
    assert {t for t, _ in iac["stepfunctions"]} == {"cdk:stepfunctions_tasks"}
    assert result.sources == {"python", "node", "java", "go", "terraform", "cloudformation", "cdk"}


def test_analyze_lists_known_differences(project, index):
    result = sc.scan([project], index.known_services)
    report = chk.analyze(result, index, "v1.0.385", "v1.0.0")
    ops = {o.operation: o for o in report.operations}
    assert set(ops) == {"dynamodb:TransactWriteItems", "dynamodb:GetItem", "sqs:SendMessage",
                        "stepfunctions:StartExecution", "sns:Publish", "kinesis:PutRecord",
                        "s3:PutObject"}
    assert "logs:PutLogEvents" not in ops  # imported, never sent
    assert [l.file for l in ops["dynamodb:GetItem"].locations] == ["app/repo.py"]  # client made elsewhere

    tx = ops["dynamodb:TransactWriteItems"]
    assert (tx.tests, tx.passed) == (3, 1)
    diffs = {d.test.id: d for d in tx.differences}
    assert diffs["ddb-tx-1"].at_operation and not diffs["ddb-tx-1"].matches_usage
    # calls GetItem + TransactWriteItems (+ sts, ignored): all things the project calls
    assert diffs["dynamodb.orders-flow"].matches_usage and not diffs["dynamodb.orders-flow"].at_operation
    assert tx.other_failing == 0

    get = ops["dynamodb:GetItem"]
    assert {d.test.id for d in get.differences} == {"dynamodb.orders-flow"}
    assert get.other_failing == 2  # fails at CreateTable / uses operations the project doesn't
    assert report.operations[0].operation == "dynamodb:TransactWriteItems"  # most differences first

    services = {s.service: s for s in report.services}
    assert services["dynamodb"].sources == ["cloudformation", "python", "terraform"]
    assert (services["dynamodb"].cfn_passed, services["dynamodb"].cfn_tests) == (1, 2)

    data = report.as_dict(limit=1)
    first = data["operations"][0]
    assert len(first["differences"]) == 1 and first["differences"][0]["test"] == "ddb-tx-1"
    assert first["differences"][0]["expected"] == "400 ValidationException"
    assert data["summary"] == {"operations": 7, "services": len(report.services),
                               "operations_with_differences": 2, "differences": 2,  # orders-flow is in both
                               "explained_by_issues": None, "fixed_in_latest": None, "latest": None}


def test_differences_link_to_the_tests_version(project, index):
    report = chk.analyze(sc.scan([project], index.known_services), index, "v1.0.385", "v1.0.0")
    links = [d["url"] for o in report.as_dict()["operations"] for d in o["differences"] if d["url"]]
    assert links[0] == ("https://github.com/aws/aws-emulator-evaluation-suite/blob/v1.0.0/"
                        "behavioral/dynamodb/check_orders_flow.py")


def test_manifest_download_and_cache(isolated_home, monkeypatch):
    calls = []
    body = "\n".join(json.dumps(r) for r in MANIFEST).encode()

    def fake_get(url, accept="", gzip_ok=False):
        calls.append(url)
        return body

    monkeypatch.setattr(fid, "_get", fake_get)
    assert len(chk.load_manifest("v1.0.0")) == len(MANIFEST)
    assert len(chk.load_manifest("v1.0.0")) == len(MANIFEST)  # cached: tags don't change
    assert calls == ["https://raw.githubusercontent.com/aws/aws-emulator-evaluation-suite/v1.0.0/manifest.jsonl"]

    def offline(*a, **k):
        raise fid.FidelityError("couldn't reach GitHub")

    monkeypatch.setattr(fid, "_get", offline)
    assert len(chk.load_manifest("v1.0.0", refresh=True)) == len(MANIFEST)  # old copy beats nothing
    with pytest.raises(fid.FidelityError):
        chk.load_manifest("main")


def test_latest_suite_version(isolated_home, monkeypatch):
    calls = []

    def fake_get(url, accept="", gzip_ok=False):
        calls.append(url)
        return json.dumps([{"name": "v1.2.0"}, {"name": "v1.10.0"}, {"name": "nightly"}]).encode()

    monkeypatch.setattr(fid, "_get", fake_get)
    assert chk.latest_suite_version() == "v1.10.0"
    assert chk.latest_suite_version() == "v1.10.0"  # cached for a day
    assert len(calls) == 1

    (fid.cache_dir() / "suite-tags.json").unlink()
    monkeypatch.setattr(fid, "_get", lambda *a, **k: (_ for _ in ()).throw(fid.FidelityError("offline")))
    assert chk.latest_suite_version() is None  # the command then falls back to main


def test_bad_manifest_is_reported():
    with pytest.raises(fid.FidelityError, match="line 2"):
        chk.parse_manifest(b'{"check_id": "a", "operations": []}\nnot json\n')


@pytest.fixture
def cached(isolated_home, monkeypatch):
    d = fid.cache_dir()
    d.mkdir(parents=True)
    (d / "v1.0.385.json.gz").write_bytes(gzip.compress(json.dumps(SCORES).encode()))
    (d / "v1.0.385.release.json").write_text(json.dumps({"suite": "v1.0.0"}))
    (d / "manifest-v1.0.0.jsonl.gz").write_bytes(
        gzip.compress("\n".join(json.dumps(r) for r in MANIFEST).encode()))
    monkeypatch.setattr(fid, "installed_version", lambda binary=None: "1.0.385")

    def no_network(*a, **k):
        raise AssertionError("should use the cache")

    monkeypatch.setattr(fid, "_get", no_network)


def test_command_text(runner, cached, project):
    result = runner.invoke(cli, ["check", str(project), "--no-explain"])
    assert result.exit_code == 0, result.output
    out = result.output
    assert "v1.0.385" in out and "fidelity tests  v1.0.0" in out
    assert "dynamodb:TransactWriteItems" in out
    assert "ddb-tx-1  fails here (step 2/2): AWS 400 ValidationException, emulator 200" in out
    assert "dynamodb.orders-flow  fails; calls only operations you use" in out
    assert "2 of 7 operation(s) you use have known differences (2 failing test(s))" in out
    assert "aws_dynamodb_table (infra/main.tf)" in out


def test_command_json_and_strict(runner, cached, project):
    result = runner.invoke(cli, ["check", str(project), "--json", "--no-explain"])
    assert result.exit_code == 0, result.output
    data = json.loads(result.output)
    assert data["release"] == "v1.0.385" and data["suite"] == "v1.0.0"
    assert data["summary"]["operations_with_differences"] == 2

    strict = runner.invoke(cli, ["check", str(project), "--strict", "--no-explain"])
    assert strict.exit_code == 1
    clean = runner.invoke(cli, ["check", str(project / "svc"), "--strict", "--no-explain"])
    assert clean.exit_code == 0, clean.output
    assert "No known differences for the 2 operation(s) you use" in clean.output


def test_command_local_manifest_file(runner, cached, project, tmp_path):
    path = tmp_path / "manifest.jsonl"
    path.write_text("\n".join(json.dumps(r) for r in MANIFEST))
    result = runner.invoke(cli, ["check", str(project / "app"), "--manifest", str(path), "--json", "--no-explain"])
    assert result.exit_code == 0, result.output
    assert json.loads(result.output)["suite"] == "manifest.jsonl"


def test_command_nothing_found(runner, cached, tmp_path):
    (tmp_path / "empty").mkdir()
    result = runner.invoke(cli, ["check", str(tmp_path / "empty"), "--no-explain"])
    assert result.exit_code == 0
    assert "found no AWS SDK calls" in result.output


def test_release_defaults_to_the_project_pin(runner, cached, project, monkeypatch):
    d = fid.cache_dir()
    other = {**SCORES, "units": [u for u in SCORES["units"] if u["unitId"] != "ddb-tx-1"]}
    (d / "v1.0.390.json.gz").write_bytes(gzip.compress(json.dumps(other).encode()))
    (d / "suite-tags.json").write_text(json.dumps({"latest": "v1.0.0"}))
    (project / "awsemu.toml").write_text('emulator_version = "1.0.390"\n')
    monkeypatch.chdir(project)
    result = runner.invoke(cli, ["check", "--json", "--no-explain"])
    assert result.exit_code == 0, result.output
    data = json.loads(result.output)
    assert data["release"] == "v1.0.390"
    assert data["suite"] == "v1.0.0"  # the release doesn't say -> the newest tests version
    ids = {d["test"] for o in data["operations"] for d in o["differences"]}
    assert "ddb-tx-1" not in ids


def test_fidelity_compare(runner, cached, project, monkeypatch):
    newer = json.loads(json.dumps(SCORES))
    for u in newer["units"]:
        if u["unitId"] == "ddb-tx-1":
            u["outcome"] = "pass"
        if u["unitId"] == "sqs-send-1":
            u["outcome"] = "fail"
    newer["units"].append(behavioral("dynamodb.new-one", "fail", DDB))
    newer["units"] = [u for u in newer["units"] if u["unitId"] != "s3.put"]
    (fid.cache_dir() / "v1.0.390.json.gz").write_bytes(gzip.compress(json.dumps(newer).encode()))

    changes = fid.compare(SCORES, newer)
    assert changes["dynamodb"].fixed == ["ddb-tx-1"]
    assert changes["dynamodb"].added_failing == ["dynamodb.new-one"]
    assert changes["sqs"].regressed == ["sqs-send-1"]
    assert changes["s3"].removed == ["s3.put"]
    assert changes["dynamodb"].before == (1, 5) and changes["dynamodb"].after == (2, 6)
    assert not changes["sns"].changed

    result = runner.invoke(cli, ["fidelity", "--compare", "1.0.390"])
    assert result.exit_code == 0, result.output
    assert "Regressed (passed before, fail now): 1" in result.output
    assert "sqs  sqs-send-1" in result.output
    assert "sns" not in result.output  # unchanged services are left out

    result = runner.invoke(cli, ["fidelity", "--compare", "1.0.390", "--json", "sqs", "sns"])
    data = json.loads(result.output)
    assert set(data["services"]) == {"sqs", "sns"}
    assert data["services"]["sqs"]["regressed"] == ["sqs-send-1"]
    assert data["from"] == {"release": "v1.0.385", "suite": "v1.0.0"}

    monkeypatch.chdir(project / "svc")
    mine = runner.invoke(cli, ["fidelity", "--compare", "1.0.390", "--mine", "--json"])
    assert mine.exit_code == 0, mine.output
    assert set(json.loads(mine.output)["services"]) == {"kinesis", "sns"}

    assert runner.invoke(cli, ["fidelity", "sqs", "--failures", "--compare", "1.0.390"]).exit_code == 2


def _calls_log(path, *calls):
    path.write_text("".join(json.dumps({"id": i + 1, "service": s, "operation": op, "resource": "",
                                        "status": 200, "error": None}) + "\n"
                            for i, (s, op) in enumerate(calls)))
    return path


def test_scan_from_calls(index, tmp_path):
    calls = [json.loads(line) for line in _calls_log(
        tmp_path / "calls.jsonl", ("dynamodb", "TransactWriteItems"), ("dynamodb", "TransactWriteItems"),
        ("logs", "PutLogEvents"), ("dynamodb", "DescribeLimits"), ("", "")).read_text().splitlines()]
    result, unknown = chk.scan_from_calls(calls, index)
    report = chk.analyze(result, index, "v1.0.385", "v1.0.0")
    ops = {o.operation: o for o in report.operations}
    assert set(ops) == {"dynamodb:TransactWriteItems", "logs:PutLogEvents"}  # what was really called
    assert ops["dynamodb:TransactWriteItems"].locations[0].file == "calls.jsonl"
    assert unknown == ["dynamodb:DescribeLimits"]  # called, but no fidelity test knows it
    assert result.sources == {"proxy calls"} and result.files == 5


def test_command_from_calls(runner, cached, tmp_path, monkeypatch):
    from awsemu import proxy as px

    px.ProxyFiles(9297).dir.mkdir(parents=True)
    log = _calls_log(px.ProxyFiles(9297).calls, ("dynamodb", "TransactWriteItems"), ("sqs", "SendMessage"))
    result = runner.invoke(cli, ["check", "--from-calls", "--no-explain"])
    assert result.exit_code == 0, result.output
    assert "2 call(s) in calls.jsonl" in result.output and "dynamodb:TransactWriteItems" in result.output
    data = json.loads(runner.invoke(cli, ["check", "--calls-file", str(log), "--json", "--no-explain"]).output)
    assert {o["operation"] for o in data["operations"]} == {"dynamodb:TransactWriteItems", "sqs:SendMessage"}
    assert runner.invoke(cli, ["check", "--from-calls", str(tmp_path)]).exit_code == 2
    log.write_text("")
    empty = runner.invoke(cli, ["check", "--from-calls", "--no-explain"])
    assert empty.exit_code == 1 and "no calls" in empty.output
