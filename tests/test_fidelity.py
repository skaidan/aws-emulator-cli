"""awsemu fidelity with a synthetic scores file (same shape as scores.json.gz)."""

import gzip
import json

import pytest

from awsemu import fidelity as fid
from awsemu.cli import cli

S3 = "com.amazonaws.s3#AmazonS3"
SQS = "com.amazonaws.sqs#AmazonSQS"
DDB = "com.amazonaws.dynamodb#DynamoDB_20120810"
SFN = "com.amazonaws.sfn#AWSStepFunctions"


def unit(uid, outcome, *services, **detail):
    return {
        "unitId": uid,
        "kind": "wire",
        "outcome": outcome,
        "services": list(services),
        **({"detail": detail} if detail else {}),
    }


SCORES = {
    "commit": "813af480bf7f16d5418b64e4f5644a74a7da11c5",
    "schemaVersion": 1,
    "scoredAt": "2026-11-14T18:34:58.642796+00:00",
    "units": [
        unit("s3-1", "pass", S3),
        unit("s3-2", "pass", S3),
        unit("s3-3", "pass", S3),
        unit(
            "s3-4",
            "fail",
            S3,
            operation="PutObject",
            mismatch="status",
            expected={"status": 400, "errorCode": "InvalidArgument"},
            actual={"status": 200},
            failedStep=2,
            totalSteps=3,
        ),
        unit("sqs-1", "pass", SQS),
        unit("sqs-2", "skip", SQS),
        unit(
            "ddb-1",
            "fail",
            DDB,
            operation="CreateTable",
            mismatch="errorCode",
            expected={"status": 400, "errorCode": "ValidationException"},
            actual={"status": 400, "errorCode": "SerializationException"},
        ),
        unit("sfn-1", "pass", SFN),
        unit("s3-sqs-1", "pass", S3, SQS),
    ],
}


def test_service_names():
    assert fid.service_name(DDB) == "dynamodb"
    assert fid.service_name("com.amazonaws.bedrockagentcorecontrol#AmazonBedrockAgentCore") == "bedrockagentcorecontrol"
    assert fid.parse_version_output("Version: 1.0.385\nRelease date: 2026.11.14\n") == "1.0.385"
    assert fid.tag_for("1.0.385") == fid.tag_for("v1.0.385") == "v1.0.385"
    assert fid.tag_for("latest") == "latest"


def test_summarize_counts_single_service_tests_only():
    t = fid.summarize(SCORES)
    assert (t["s3"].passed, t["s3"].total) == (3, 4)
    assert (t["s3"].multi_passed, t["s3"].multi_total) == (1, 1)
    assert (t["sqs"].passed, t["sqs"].total) == (1, 1)  # skipped units don't count
    assert t["s3"].percent == 75.0
    assert [u["unitId"] for u in t["dynamodb"].failures] == ["ddb-1"]


def test_match_services_aliases_and_partial():
    available = [
        "cloudwatchevents",
        "cloudwatchlogs",
        "dynamodb",
        "dynamodbstreams",
        "eventbridge",
        "s3",
        "s3control",
        "sfn",
    ]
    assert fid.match_services(["s3"], available) == (["s3"], [])
    assert fid.match_services(["dynamo"], available) == (["dynamodb", "dynamodbstreams"], [])
    assert fid.match_services(["stepfunctions"], available) == (["sfn"], [])
    assert fid.match_services(["events"], available) == (["eventbridge"], [])
    assert fid.match_services(["logs"], available) == (["cloudwatchlogs"], [])
    assert fid.match_services(["nope"], available) == ([], ["nope"])


def test_parse_suite_version():
    assert fid.parse_suite_version("Scored with fidelity tests v1.2.0 (abc)") == "v1.2.0"
    assert fid.parse_suite_version("see https://github.com/aws/aws-emulator-evaluation-suite/tree/v1.0.0") == "v1.0.0"
    assert fid.parse_suite_version("Evaluation suite: 1.1.0") == "v1.1.0"
    assert fid.parse_suite_version("Bug fixes.") is None


def test_describe_failure():
    f = fid.describe_failure(SCORES["units"][3])
    assert f == {
        "test": "s3-4",
        "operation": "PutObject",
        "mismatch": "status",
        "expected": "400 InvalidArgument",
        "actual": "200",
        "step": "2/3",
    }


@pytest.fixture
def cached_release(isolated_home, monkeypatch):
    """Put the synthetic file in the cache as v1.0.385 and pretend that's installed."""
    fid.cache_dir().mkdir(parents=True)
    (fid.cache_dir() / "v1.0.385.json.gz").write_bytes(gzip.compress(json.dumps(SCORES).encode()))
    monkeypatch.setattr(fid, "installed_version", lambda binary=None: "1.0.385")

    def no_network(*a, **k):
        raise AssertionError("should use the cache")

    monkeypatch.setattr(fid, "_get", no_network)


def test_command_summary(runner, cached_release):
    result = runner.invoke(cli, ["fidelity"])
    assert result.exit_code == 0, result.output
    assert "v1.0.385" in result.output and "813af480bf7f" in result.output
    lines = {line.split()[0]: line for line in result.output.splitlines() if line.strip()}
    assert "3/4" in lines["s3"] and "75%" in lines["s3"] and "1/1" in lines["s3"]
    assert "5 of 7 single-service tests pass" in result.output


def test_command_filter_and_failures(runner, cached_release):
    result = runner.invoke(cli, ["fidelity", "dynamodb", "--failures"])
    assert result.exit_code == 0, result.output
    assert "1 failing of 1" in result.output and "CreateTable" in result.output
    assert "ValidationException" in result.output and "SerializationException" in result.output
    assert runner.invoke(cli, ["fidelity", "--failures"]).exit_code == 2
    bad = runner.invoke(cli, ["fidelity", "nope"])
    assert bad.exit_code == 1 and "no fidelity tests for: nope" in bad.output


def test_command_json(runner, cached_release):
    data = json.loads(runner.invoke(cli, ["fidelity", "s3", "--json"]).output)
    assert data["release"] == "v1.0.385" and data["installed"] == "1.0.385"
    assert data["services"]["s3"]["passed"] == 3 and "s3control" not in data["services"]


def test_version_mismatch_warns(runner, cached_release, monkeypatch):
    monkeypatch.setattr(fid, "installed_version", lambda binary=None: "1.0.300")
    monkeypatch.setattr(fid, "fetch", lambda release, refresh=False: ("v1.0.385", SCORES))
    result = runner.invoke(cli, ["fidelity", "--release", "latest"])
    assert result.exit_code == 0 and "your emulator is v1.0.300" in result.output


def test_bad_file_is_reported(isolated_home):
    with pytest.raises(fid.FidelityError, match="unexpected format"):
        fid._load_gz(gzip.compress(b'{"nope": 1}'))
    with pytest.raises(fid.FidelityError, match="not valid gzip"):
        fid._load_gz(b"plain")
