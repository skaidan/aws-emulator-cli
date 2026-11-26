"""``awsemu proxy cost``: request charges from the calls log."""

import json

import pytest

from awsemu import cost as cs
from awsemu import proxy as px
from awsemu.cli import cli


def c(service, op, resource="", **extra):
    return {
        "service": service,
        "operation": op,
        "resource": resource,
        "status": 200,
        "latency_ms": 100.0,
        "bytes_in": 0,
        **extra,
    }


CALLS = (
    [c("dynamodb", "PutItem")] * 4
    + [c("dynamodb", "TransactWriteItems"), c("dynamodb", "GetItem"), c("dynamodb", "CreateTable")]
    + [c("sqs", "SendMessage", "jobs")] * 10
    + [c("sqs", "SendMessage", "jobs.fifo")]
    + [c("s3", "PutObject", "b/k"), c("s3", "GetObject", "b/k"), c("s3", "DeleteObject", "b/k")]
    + [c("lambda", "Invoke", "fn", latency_ms=2000.0), c("logs", "PutLogEvents", bytes_in=1_000_000_000)]
    + [c("sts", "GetCallerIdentity"), c("apigateway", "GetRestApis"), c("sqs", "SendMessage", status=0)]
)


def test_units_and_prices():
    est = cs.estimate(CALLS)
    lines = {(x.service, x.item): x for x in est.lines}
    assert lines[("dynamodb", "write")].units == 6  # 4 puts + a transaction (2)
    assert lines[("dynamodb", "read")].units == 1
    assert lines[("sqs", "standard")].units == 10 and lines[("sqs", "fifo")].units == 1
    assert lines[("s3", "put")].units == 1 and lines[("s3", "get")].units == 1  # DELETE is free
    assert lines[("lambda", "gb_second")].units == pytest.approx(0.25)  # 2 s at 128 MB
    assert lines[("logs", "ingest_gb")].cost == pytest.approx(0.50)
    assert est.unpriced == {"apigateway": 1}
    assert est.calls == len(CALLS) - 1  # the reset call was never answered
    assert est.total == pytest.approx(sum(x.cost for x in est.lines))
    assert est.as_dict(runs=10)["total_usd"] == pytest.approx(est.total * 10, rel=1e-6)


def test_own_prices(tmp_path):
    f = tmp_path / "prices.json"
    f.write_text(json.dumps({"sqs.standard": 1.0}))
    est = cs.estimate(CALLS, cs.load_prices(f))
    assert next(x for x in est.lines if x.item == "standard").cost == 10.0


def test_command(runner, isolated_home):
    files = px.ProxyFiles(9297)
    files.dir.mkdir(parents=True)
    files.calls.write_text("".join(json.dumps(x) + "\n" for x in CALLS))
    out = runner.invoke(cli, ["proxy", "cost", "--runs", "1000"])
    assert out.exit_code == 0, out.output
    assert "Estimated total" in out.output and "per run" in out.output and "apigateway" in out.output
    data = json.loads(runner.invoke(cli, ["proxy", "cost", "--json"]).output)
    assert data["estimate"] is True and data["region"] == "us-east-1" and "free tier" in data["excludes"]
