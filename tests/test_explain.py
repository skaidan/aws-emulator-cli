"""``awsemu explain``: a failed call against the fidelity data."""

import json

import pytest

from awsemu import check as chk
from awsemu import explain as ex
from awsemu import proxy as px
from awsemu.cli import cli
from tests.test_check import MANIFEST, SCORES, cached  # noqa: F401  (fixture)


def call(service, operation, status=400, error=None, fault=None, i=1):
    return {"id": i, "time": "2026-11-26T12:00:00+00:00", "service": service, "operation": operation,
            "resource": "orders", "status": status, "error": error, "fault": fault, "request_id": None}


@pytest.fixture
def index():
    return chk.Index(SCORES, MANIFEST)


@pytest.mark.parametrize("the_call, verdict", [
    (call("dynamodb", "PutItem", fault="dynamodb=throttle", error="ThrottlingException"), "injected"),
    (call("dynamodb", "TransactWriteItems", 200), "known_difference"),  # AWS says 400, the emulator 200
    (call("dynamodb", "TransactWriteItems", 400, "TransactionCanceledException"), "possible_difference"),
    (call("sqs", "SendMessage", 400, "AWS.SimpleQueueService.NonExistentQueue"), "likely_your_code"),
    (call("sqs", "SendMessage", 500, "InternalFailure"), "emulator_gap"),
    (call("sqs", "PurgeQueue", 400, "PurgeQueueInProgress"), "unknown"),  # no tests know it
    (call("sqs", "SendMessage", 200), "succeeded"),
])
def test_verdicts(index, the_call, verdict):
    data = ex.explain(the_call, index, "v1.0.385", "v1.0.0", with_issues=False)
    assert data["verdict"] == verdict, data
    assert data["advice"] == ex.ADVICE[verdict]


def test_the_evidence_comes_with_the_verdict(index):
    data = ex.explain(call("dynamodb", "TransactWriteItems", 200), index, "v1.0.385", "v1.0.0", with_issues=False)
    assert data["operation"] == "dynamodb:TransactWriteItems" and (data["tests"], data["passed"]) == (3, 1)
    assert data["matching"] == ["ddb-tx-1"]
    assert data["differences"][0]["expected"] == "400 ValidationException"


def test_command(runner, cached, isolated_home):  # noqa: F811
    files = px.ProxyFiles(9297)
    files.dir.mkdir(parents=True)
    files.calls.write_text(json.dumps(call("dynamodb", "TransactWriteItems", 200, i=1)) + "\n"
                           + json.dumps(call("sqs", "SendMessage", 400, "AWS.SimpleQueueService.NonExistentQueue",
                                             i=2)) + "\n")
    result = runner.invoke(cli, ["explain", "--json"])  # last failed: the SQS one
    assert result.exit_code == 0, result.output
    assert json.loads(result.output)["verdict"] == "likely_your_code"
    text = runner.invoke(cli, ["explain", "1"]).output
    assert "Verdict: a known emulator difference" in text and "= ddb-tx-1: AWS 400 ValidationException" in text
