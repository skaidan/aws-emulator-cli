"""The emulator's issue files: listing, parsing, check's explanations, 'awsemu issues'."""

import gzip
import json

import pytest

from awsemu import fidelity as fid
from awsemu import issues as iss
from awsemu.cli import cli

OPEN_FILES = {
    "20261120T225636Z-dynamodb-validationexception-envelope-diverges.md": """\
Issue-Severity: HIGH
Issue-Corpus: simparity-wire-aws-v1
Issue-Corpus-Kind: wire
Issue-Trace-Ids: ddb-tx-1 ddb-other
Issue-Commit: abc123

# DynamoDB ValidationException envelope diverges

## Operation
TransactWriteItems

## Description
AWS: answers 400. Emulator: answers 200.
""",
    "20261112T102720Z-lambda-scheduler-sqs-2-net-new-causes.md": """\
Issue-Severity: MEDIUM
Issue-Corpus-Kind: behavioral
Issue-Trace-Ids: sqs.dead-letter
Issue-Commit: def456

# lambda__scheduler__sqs: 2 net-new causes

## Operation
SendMessage
""",
    "20261101T000000Z-dynamodb-critical-thing.md": """\
Issue-Severity: CRITICAL

# A critical DynamoDB thing

## Operation
GetItem, PutItem
""",
    "20261102T000000Z-scaffold-codegen-cannot-emit.md": "Issue-Severity: LOW\n\n# Not about a service\n",
}
FIXED_FILES = {
    "20261010T000000Z-dynamodb-orders-flow-fixed.md": """\
Issue-Severity: HIGH
Issue-Trace-Ids: dynamodb.orders-flow

# Orders flow now works

## Operation
TransactWriteItems
""",
}


class FakeGitHub:
    def __init__(self, monkeypatch, scores=None):
        self.calls = []
        self.scores = scores or {}
        monkeypatch.setattr(fid, "_get", self.get)

    def get(self, url, accept="", gzip_ok=False, first_bytes=None):
        self.calls.append((url, first_bytes))
        folders = {iss.OPEN: OPEN_FILES, iss.FIXED: FIXED_FILES}
        if url.endswith("/repos/aws/aws-emulator/contents/issues"):
            return json.dumps([{"name": f, "sha": f"tree-{f}"} for f in folders]).encode()
        if "/git/trees/tree-" in url:
            folder = url.rsplit("tree-", 1)[1]
            return json.dumps(
                {"tree": [{"path": n, "type": "blob", "sha": f"blob{abs(hash(n))}"} for n in folders[folder]]}
            ).encode()
        if "raw.githubusercontent.com/aws/aws-emulator/main/issues/" in url:
            folder, name = url.split("/main/issues/", 1)[1].split("/", 1)
            data = folders[folder][name].encode()
            return data[:first_bytes] if first_bytes else data
        if url.endswith("/releases/latest") or "/releases/tags/" in url:
            tag = url.rsplit("/", 1)[1] if "/tags/" in url else "v1.0.390"
            return json.dumps(
                {
                    "tag_name": tag,
                    "assets": [{"name": "scores.json.gz", "browser_download_url": f"https://dl/{tag}/scores.json.gz"}],
                }
            ).encode()
        if url.startswith("https://dl/"):
            return gzip.compress(json.dumps(self.scores[url.split("/")[3]]).encode())
        raise fid.FidelityError(f"not found: {url}")

    def raw_requests(self):
        return [c for c in self.calls if "raw.githubusercontent" in c[0]]


def test_services_in_name():
    known = {"dynamodb", "lambda", "scheduler", "sqs", "chime-sdk-meetings", "s3"}
    assert iss.services_in_name("20261112T102720Z-lambda-scheduler-sqs-2-net-new.md", known) == [
        "lambda",
        "scheduler",
        "sqs",
    ]
    assert iss.services_in_name("20261121T152303Z-chime-sdk-meetings-createmeeting.md", known) == ["chime-sdk-meetings"]
    assert iss.services_in_name("20261102T000000Z-scaffold-codegen.md", known) == []
    assert iss.services_in_name("release-gate-25befc957876.md", known) == []


def test_parse():
    f = iss.IssueFile(iss.OPEN, "20261120T225636Z-dynamodb-x.md", "sha", ["dynamodb"])
    issue = iss.parse(OPEN_FILES["20261120T225636Z-dynamodb-validationexception-envelope-diverges.md"], f)
    assert issue.title == "DynamoDB ValidationException envelope diverges"
    assert (issue.severity, issue.kind, issue.commit) == ("HIGH", "wire", "abc123")
    assert issue.operations == ["TransactWriteItems"] and issue.tests == {"ddb-tx-1", "ddb-other"}
    assert f.created == "2026-11-20"
    assert f.url.endswith("/issues/things-that-do-not-work/20261120T225636Z-dynamodb-x.md")
    multi = iss.parse(OPEN_FILES["20261101T000000Z-dynamodb-critical-thing.md"], f)
    assert multi.operations == ["GetItem", "PutItem"] and multi.tests == set()


def test_listing_fetch_and_cache(monkeypatch):
    gh = FakeGitHub(monkeypatch)
    found = iss.for_services({"dynamodb"})
    assert [i.title for i in found] == ["A critical DynamoDB thing", "DynamoDB ValidationException envelope diverges"]
    assert all(first == iss.HEAD_BYTES for _, first in gh.raw_requests())  # only the start of each file
    before = len(gh.calls)
    iss.for_services({"dynamodb"})
    assert len(gh.calls) == before  # list cached for 6 h, blobs by their id

    def offline(*a, **k):
        raise fid.FidelityError("couldn't reach GitHub")

    monkeypatch.setattr(fid, "_get", offline)
    assert len(iss.listing(refresh=True)) == len(OPEN_FILES)  # an old list beats nothing


def test_long_headers_fetch_the_whole_file(monkeypatch):
    long_ids = " ".join(f"test-{n:05d}" for n in range(2000))
    OPEN_FILES["20261103T000000Z-s3-many-tests.md"] = f"Issue-Severity: LOW\nIssue-Trace-Ids: {long_ids}\n\n# Many\n"
    try:
        gh = FakeGitHub(monkeypatch)
        (issue,) = iss.for_services({"s3"})
        assert len(issue.tests) == 2000
        assert [first for _, first in gh.raw_requests()] == [iss.HEAD_BYTES, None]
    finally:
        del OPEN_FILES["20261103T000000Z-s3-many-tests.md"]


def test_no_network_and_no_cache_is_an_error(monkeypatch):
    monkeypatch.setattr(fid, "_get", lambda *a, **k: (_ for _ in ()).throw(fid.FidelityError("offline")))
    with pytest.raises(iss.IssuesError, match="couldn't list"):
        iss.listing()


# --------------------------------------------------------------------------- check


@pytest.fixture
def scores_cached():
    from tests.test_check import MANIFEST, SCORES

    d = fid.cache_dir()
    d.mkdir(parents=True)
    (d / "v1.0.385.json.gz").write_bytes(gzip.compress(json.dumps(SCORES).encode()))
    (d / "v1.0.385.release.json").write_text(json.dumps({"suite": "v1.0.0"}))
    (d / "manifest-v1.0.0.jsonl.gz").write_bytes(gzip.compress("\n".join(json.dumps(r) for r in MANIFEST).encode()))
    newer = json.loads(json.dumps(SCORES))
    for u in newer["units"]:
        if u["unitId"] == "dynamodb.orders-flow":
            u["outcome"] = "pass"
    return newer


def test_check_explains_differences(runner, monkeypatch, scores_cached, tmp_path):
    from tests.test_check import FILES

    for name, text in FILES.items():
        (tmp_path / name).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / name).write_text(text)
    FakeGitHub(monkeypatch, scores={"v1.0.390": scores_cached})
    monkeypatch.setattr(fid, "installed_version", lambda binary=None: "1.0.385")

    result = runner.invoke(cli, ["check", str(tmp_path)])
    assert result.exit_code == 0, result.output
    out = result.output
    assert "↳ known issue (HIGH): DynamoDB ValidationException envelope diverges" in out
    assert "↳ fixed in v1.0.390: awsemu install latest" in out
    assert "1 of them pass in the latest release, v1.0.390" in out
    assert "1 of them are explained by an open issue" in out

    data = json.loads(runner.invoke(cli, ["check", str(tmp_path), "--json"]).output)
    diffs = {d["test"]: d for o in data["operations"] for d in o["differences"]}
    assert diffs["ddb-tx-1"]["issues"][0]["title"] == "DynamoDB ValidationException envelope diverges"
    assert diffs["ddb-tx-1"]["fixed_in"] is None
    assert diffs["dynamodb.orders-flow"]["fixed_in"] == "v1.0.390"
    assert data["summary"]["explained_by_issues"] == 1 and data["summary"]["fixed_in_latest"] == 1


def test_check_explanations_are_optional(runner, monkeypatch, scores_cached, tmp_path):
    from tests.test_check import FILES

    (tmp_path / "app").mkdir()
    (tmp_path / "app" / "orders.py").write_text(FILES["app/orders.py"])
    monkeypatch.setattr(fid, "installed_version", lambda binary=None: "1.0.385")

    def offline(*a, **k):
        raise fid.FidelityError("couldn't reach GitHub")

    monkeypatch.setattr(fid, "_get", offline)
    result = runner.invoke(cli, ["check", str(tmp_path)])
    assert result.exit_code == 0, result.output
    assert "couldn't list the emulator's issues" in result.output  # a warning, not a failure
    assert "known difference" in result.output


# --------------------------------------------------------------------------- awsemu issues


def test_issues_command(runner, monkeypatch, scores_cached):
    FakeGitHub(monkeypatch, scores={"v1.0.390": scores_cached})
    monkeypatch.setattr(fid, "installed_version", lambda binary=None: "1.0.385")

    out = runner.invoke(cli, ["issues", "dynamodb"]).output
    assert "Open issues: dynamodb" in out and "A critical DynamoDB thing" in out
    assert out.index("A critical DynamoDB thing") < out.index("DynamoDB ValidationException")  # most severe first
    assert "2 issue(s)" in out

    out = runner.invoke(cli, ["issues", "dynamodb:Transact*", "sqs"]).output
    assert "DynamoDB ValidationException" in out and "2 net-new causes" in out and "critical" not in out
    assert "MEDIUM" in runner.invoke(cli, ["issues", "sqs"]).output
    assert "No open issues match" in runner.invoke(cli, ["issues", "sqs", "--severity", "high"]).output
    assert "envelope" in runner.invoke(cli, ["issues", "dynamodb", "--search", "ENVELOPE"]).output

    data = json.loads(runner.invoke(cli, ["issues", "dynamodb", "--json", "-n", "1"]).output)
    assert len(data) == 1 and set(data[0]) == {
        "title",
        "severity",
        "state",
        "services",
        "operations",
        "tests",
        "kind",
        "created",
        "url",
        "name",
    }

    shown = runner.invoke(cli, ["issues", "--show", "1"])
    assert shown.exit_code == 0 and "A critical DynamoDB thing" in shown.output and "state     open" in shown.output
    full = json.loads(runner.invoke(cli, ["issues", "--show", "20261120T225636Z", "--json"]).output)
    assert full["text"].startswith("Issue-Severity: HIGH") and full["severity"] == "HIGH"
    missing = runner.invoke(cli, ["issues", "--show", "99"])
    assert missing.exit_code == 1 and "no row 99" in missing.output

    fixed = runner.invoke(cli, ["issues", "dynamodb", "--fixed"]).output
    assert "Orders flow now works" in fixed and "fails in v1.0.385" in fixed
    assert "1 of them are fixed after v1.0.385" in fixed

    assert runner.invoke(cli, ["issues"]).exit_code == 2


def test_issues_mine(runner, monkeypatch, tmp_path):
    FakeGitHub(monkeypatch)
    (tmp_path / "app.py").write_text("import boto3\nboto3.client('sqs').send_message(QueueUrl='q', MessageBody='m')\n")
    monkeypatch.chdir(tmp_path)
    out = runner.invoke(cli, ["issues", "--mine"]).output
    assert "Open issues: sqs" in out and "2 net-new causes" in out
