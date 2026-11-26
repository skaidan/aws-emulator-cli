"""``awsemu fidelity run``: selection, results against the published scores, the command."""

import json

import pytest

from awsemu import fidelityrun as fr
from awsemu.cli import cli
from awsemu.commands import fidelity as fid_cmd

ROWS = [
    {"check_id": "dynamodb.a", "service": "dynamodb", "path": "behavioral/dynamodb/check_a.py"},
    {"check_id": "dynamodb.b", "service": "dynamodb", "path": "behavioral/dynamodb/check_b.py"},
    {"check_id": "sqs.c", "service": "sqs", "path": "behavioral/sqs/check_c.py"},
    {"check_id": "lambda__sqs.d", "service": "lambda__sqs", "path": "behavioral/lambda__sqs/check_d.py"},
]
SCORES = {
    "units": [
        {"unitId": "dynamodb.a", "outcome": "pass"},
        {"unitId": "dynamodb.b", "outcome": "fail"},
        {"unitId": "sqs.c", "outcome": "pass"},
        {"unitId": "x", "outcome": "skipped"},
    ]
}


@pytest.fixture
def suite(tmp_path):
    root = tmp_path / "suite"
    root.mkdir()
    (root / "manifest.jsonl").write_text("".join(json.dumps(r) + "\n" for r in ROWS))
    return fr.local_suite(root, "v1.0.1")


def test_selection(suite):
    assert [r["check_id"] for r in fr.select(suite, ["dynamodb"], [])] == ["dynamodb.a", "dynamodb.b"]
    assert [r["check_id"] for r in fr.select(suite, ["sqs"], [])] == ["sqs.c", "lambda__sqs.d"]  # cross-service too
    assert [r["check_id"] for r in fr.select(suite, [], ["sqs.c"])] == ["sqs.c"]
    with pytest.raises(fr.RunError, match="no such test"):
        fr.select(suite, [], ["sqs.nope"])
    with pytest.raises(fr.RunError, match="manifest"):
        fr.local_suite(suite.root.parent)


def test_results_against_published():
    published = fr.published_outcomes(SCORES)
    assert published == {"dynamodb.a": "pass", "dynamodb.b": "fail", "sqs.c": "pass"}
    assert fr.TestResult("dynamodb.a", "p", "passed", published="pass").agrees is True
    assert fr.TestResult("dynamodb.b", "p", "passed", published="fail").agrees is False  # fixed here
    assert fr.TestResult("new", "p", "failed").agrees is None


def test_run_one_reads_the_report(suite, monkeypatch, tmp_path):
    class FakeEmulator:
        def __init__(self, command):
            self.home = tmp_path / "home"
            self.home.mkdir(exist_ok=True)
            self.endpoint = "https://127.0.0.1:1234"

        def __enter__(self):
            return self

        def __exit__(self, *a):
            pass

    seen = []

    def fake_run(cmd, **kw):
        seen.append(cmd)
        report = cmd[cmd.index("--report") + 1]
        with open(report, "w") as fh:
            json.dump(
                {
                    "check": {
                        "verdict": "failed",
                        "kind": "assertion",
                        "detail": "expected 400\nmore",
                        "duration_ms": 1200,
                    }
                },
                fh,
            )
        return type("Done", (), {"returncode": 11, "stdout": "", "stderr": ""})()

    monkeypatch.setattr(fr, "Emulator", FakeEmulator)
    monkeypatch.setattr(fr, "uv", lambda: "uv")
    monkeypatch.setattr(fr.subprocess, "run", fake_run)
    result = fr.run_one(suite, ROWS[0], ["aws-emulator"], {"dynamodb.a": "pass"})
    assert (result.verdict, result.kind, result.duration_ms) == ("failed", "assertion", 1200)
    assert result.agrees is False and result.detail.startswith("expected 400")
    cmd = seen[0]
    assert cmd[:5] == ["uv", "run", "--locked", "fidelity-tests-runner", "run"]
    assert "--endpoint" in cmd and "--emulator-home" in cmd


def test_command(runner, isolated_home, suite, monkeypatch):
    monkeypatch.setattr(fid_cmd, "pick_release", lambda release, refresh=False: ("v1.0.611", SCORES, "1.0.611"))
    monkeypatch.setattr("awsemu.runtime.binary_command", lambda b: ["aws-emulator"])
    monkeypatch.setattr(fr, "prepare", lambda s, paths, log: None)
    ran = []

    def fake_run_one(s, row, command, published):
        ran.append(row["check_id"])
        verdict = "passed" if row["check_id"] != "dynamodb.b" else "failed"
        return fr.TestResult(
            row["check_id"], row["path"], verdict, detail="boom", published=published.get(row["check_id"])
        )

    monkeypatch.setattr(fr, "run_one", fake_run_one)
    result = runner.invoke(cli, ["fidelity", "run", "dynamodb", "--suite", str(suite.root)])
    assert result.exit_code == 1 and ran == ["dynamodb.a", "dynamodb.b"]
    assert "1 passed, 1 failed" in result.output
    ran.clear()
    data = json.loads(
        runner.invoke(cli, ["fidelity", "run", "dynamodb", "--failing", "--json", "--suite", str(suite.root)]).output
    )
    assert ran == ["dynamodb.b"] and data["summary"]["differ_from_published"] == []
    from tests.schema_check import validate

    validate("fidelity-run", data)
    assert runner.invoke(cli, ["fidelity", "run"]).exit_code == 2
    assert (
        runner.invoke(
            cli, ["fidelity", "run", "sqs", "--test", "sqs.c", "--limit", "1", "--suite", str(suite.root)]
        ).exit_code
        == 0
    )
