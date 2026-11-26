"""Seed files: parsing, validation messages and helpers (no emulator needed)."""

import json
from pathlib import Path

import pytest

from awsemu import runtime, seed
from awsemu.cli import cli

GOOD = """\
version: 1
buckets:
  - name: photos
    objects:
      - {key: hello.txt, content: "hello"}
      - {key: config.json, json: {debug: true}}
      - {key: assets/, from: ./assets}
queues:
  - {name: jobs-dlq}
  - {name: jobs, dlq: jobs-dlq, max_receive: 3, visibility_timeout: 10}
tables:
  - name: users
    pk: id
    sk: created:N
    items:
      - {id: u1, created: 1, name: Ana}
    items_from: users.json
topics:
  - name: orders
    subscriptions:
      - {sqs: jobs, raw: true, filter: {kind: [created]}}
secrets:
  - {name: db/password, value: s3cr3t}
  - {name: db/config, value: {host: db, port: 5432}}
parameters:
  - {name: /app/host, value: localhost}
  - {name: /app/key, value: abc, type: SecureString}
  - {name: /app/hosts, value: [a, b]}
"""


@pytest.fixture
def seed_dir(tmp_path):
    (tmp_path / "assets" / "img").mkdir(parents=True)
    (tmp_path / "assets" / "a.css").write_text("body{}")
    (tmp_path / "assets" / "img" / "x.svg").write_text("<svg/>")
    (tmp_path / "users.json").write_text(json.dumps([{"id": "u2", "created": 2}]))
    (tmp_path / "seed.yaml").write_text(GOOD)
    return tmp_path


def problems(text, base=None):
    with pytest.raises(seed.SeedError) as info:
        seed.load_text(text, "seed.yaml", base)
    return [p.format("seed.yaml") for p in info.value.problems]


def test_good_seed_loads(seed_dir):
    s = seed.load_file(seed_dir / "seed.yaml")
    assert s.count() == {"buckets": 1, "queues": 2, "tables": 1, "topics": 1, "secrets": 2, "parameters": 3}
    assert s.warnings == []


def test_errors_have_line_and_field():
    out = problems("""\
version: 1
queues:
  - name: jobs
    visibilty_timeout: 10
  - {name: jobs}
tables:
  - {name: t, pk: "id:BOOL"}
""")
    assert out == [
        "seed.yaml:4  queues[0].visibilty_timeout: unknown field (did you mean 'visibility_timeout'?)",
        "seed.yaml:5  queues[1].name: duplicate name 'jobs' (also at queues[0])",
        "seed.yaml:7  tables[0].pk: 'pk' is required: NAME or NAME:S|N|B",
    ]


def test_yaml_syntax_error_has_line():
    out = problems("queues:\n  - {name: a\n  - {name: b}\n")
    assert out[0].startswith("seed.yaml:3  invalid YAML")


@pytest.mark.parametrize(
    "text,needle",
    [
        ("buckets:\n  - name: b\n    objects:\n      - {key: k}\n", "exactly one of 'content', 'json' or 'from'"),
        ("buckets:\n  - name: b\n    objects:\n      - {key: k, from: ./nope}\n", "'./nope' not found"),
        ("queues:\n  - {name: q, fifo: true}\n", "must end with '.fifo'"),
        ("queues:\n  - {name: q, dlq: q}\n", "its own dead-letter queue"),
        ("queues:\n  - {name: q, max_receive: 3}\n", "only makes sense with 'dlq'"),
        ("tables:\n  - {name: t, pk: id:N, items: [{id: 'x'}]}\n", "must be a number"),
        ("tables:\n  - {name: t, pk: id, items: [{other: 1}]}\n", "missing key attribute 'id'"),
        ("topics:\n  - name: t\n    subscriptions: [{raw: true}]\n", "exactly one of 'sqs' or 'lambda'"),
        ("secrets:\n  - {name: s}\n", "'value' is required"),
        ("parameters:\n  - {name: /aws/x, value: 1}\n", "can't start with 'aws' or 'ssm'"),
        ("parameters:\n  - {name: /x, value: [a], type: String}\n", "needs type StringList"),
        ("streams:\n  - {name: s, shards: 0}\n", "between 1 and 500"),
        ("streams:\n  - {name: s, retention_hours: 1}\n", "between 24 and 8760"),
        ("functions:\n  - {name: f}\n", "'code' is required"),
        ("functions:\n  - {name: f, code: ./nope}\n", "'./nope' not found"),
        ("functions:\n  - {name: f, code: ., timeout: 901}\n", "between 1 and 900 seconds"),
        ("functions:\n  - {name: f, code: ., env: {A: [1]}}\n", "must be text or a number"),
        (
            "functions:\n  - name: f\n    code: .\n    triggers: [{batch_size: 1}]\n",
            "exactly one of 'sqs' or 'kinesis'",
        ),
        (
            "functions:\n  - name: f\n    code: .\n    triggers: [{sqs: q, starting_position: LATEST}]\n",
            "only applies to Kinesis",
        ),
        ("state_machines:\n  - {name: m}\n", "'definition' is required"),
        ("state_machines:\n  - {name: m, definition: {States: {}}}\n", "needs 'StartAt' and 'States'"),
        ("rules:\n  - {name: r}\n", "exactly one of 'pattern' or 'schedule'"),
        ("rules:\n  - {name: r, schedule: every day}\n", "rate(5 minutes)"),
        ("rules:\n  - name: r\n    pattern: {source: [a]}\n    targets: [{http: x}]\n", "unknown field"),
        (
            "rules:\n  - name: r\n    pattern: {source: [a]}\n    targets: [{}, {}, {}, {}, {}, {}]\n",
            "at most 5 targets",
        ),
        ("version: 2\n", "unsupported version 2"),
        ("bucket:\n  - name: x\n", "did you mean 'buckets'?"),
        ("- just a list\n", "top level must be a mapping"),
        ("", "the file is empty"),
    ],
)
def test_validation_messages(tmp_path, text, needle):
    assert any(needle in p for p in problems(text, tmp_path)), problems(text, tmp_path)


def test_references_outside_the_seed_are_warnings():
    s = seed.load_text(
        "queues:\n  - {name: q, dlq: existing-dlq}\ntopics:\n  - name: t\n    subscriptions: [{sqs: existing}]\n"
    )
    assert len(s.warnings) == 2 and "must already exist" in s.warnings[0]


def test_new_sections_load_with_cross_references(tmp_path):
    (tmp_path / "fn").mkdir()
    (tmp_path / "fn" / "app.py").write_text("def handler(event, context):\n    return event\n")
    (tmp_path / "flow.yaml").write_text("StartAt: Hi\nStates:\n  Hi: {Type: Pass, End: true}\n")
    s = seed.load_text(
        """
queues: [{name: jobs}]
streams: [{name: clicks, shards: 2}]
functions:
  - {name: echo, code: ./fn, env: {A: 1}, triggers: [{sqs: jobs}, {kinesis: clicks}, {sqs: elsewhere}]}
state_machines:
  - {name: flow, definition: ./flow.yaml}
rules:
  - name: r
    pattern: {source: [app]}
    targets: [{sqs: jobs}, {lambda: echo}, {stepfunctions: flow}, {kinesis: clicks}, {sns: alerts}]
""",
        "seed.yaml",
        tmp_path,
    )
    assert s.count() == {"queues": 1, "streams": 1, "functions": 1, "state_machines": 1, "rules": 1}
    assert len(s.warnings) == 2 and "'elsewhere'" in s.warnings[0] and "'alerts'" in s.warnings[1]
    assert seed.read_definition(s.section("state_machines")[0], tmp_path)["StartAt"] == "Hi"


def test_lambda_zip_is_reproducible(tmp_path):
    import os
    import time

    from awsemu.commands.lambda_ import build_zip

    (tmp_path / "app.py").write_text("x = 1\n")
    first = build_zip(tmp_path)
    time.sleep(0.01)
    os.utime(tmp_path / "app.py", (time.time() + 100, time.time() + 100))
    assert build_zip(tmp_path) == first  # same content, same bytes, whatever the dates


def test_object_payloads(seed_dir):
    s = seed.load_file(seed_dir / "seed.yaml")
    objs = s.section("buckets")[0]["objects"]
    assert seed.object_payloads(objs[0], seed_dir) == [("hello.txt", b"hello")]
    assert json.loads(seed.object_payloads(objs[1], seed_dir)[0][1]) == {"debug": True}
    folder = seed.object_payloads(objs[2], seed_dir)
    assert [k for k, _ in folder] == ["assets/a.css", "assets/img/x.svg"]
    single = seed.object_payloads({"key": "dir/", "from": "users.json"}, seed_dir)
    assert single[0][0] == "dir/users.json" and isinstance(single[0][1], Path)


def test_items_and_values(seed_dir):
    s = seed.load_file(seed_dir / "seed.yaml")
    assert [i["id"] for i in seed.load_items(s.section("tables")[0], seed_dir)] == ["u1", "u2"]
    assert seed.secret_string({"host": "db"}) == '{"host": "db"}'
    assert seed.parameter_value({"value": ["a", "b"]}) == ("a,b", "StringList")
    assert seed.parameter_value({"value": 5}) == ("5", "String")
    assert seed.key_spec("created:n") == ("created", "N")


def test_dump_roundtrip():
    data = {
        "version": 1,
        "secrets": [{"name": "s", "value": "multi\nline"}],
        "tables": [{"name": "t", "pk": "id", "items": [{"id": "café", "n": 1.5}]}],
    }
    text = seed.dump(data)
    assert "value: |" in text and "café" in text
    assert seed.load_text(text).data == data


def test_validate_command(runner, seed_dir, tmp_path):
    result = runner.invoke(cli, ["seed", "validate", str(seed_dir / "seed.yaml")])
    assert result.exit_code == 0 and "is valid" in result.output and "3 parameters" in result.output
    bad = tmp_path / "bad.yaml"
    bad.write_text("queues:\n  - {nme: q}\n")
    result = runner.invoke(cli, ["seed", "validate", str(bad)])
    assert result.exit_code == 2
    assert f"{bad}:2  queues[0].nme: unknown field (did you mean 'name'?)" in result.output


def test_start_with_invalid_seed_starts_nothing(runner, fake_binary, free_port, tmp_path):
    bad = tmp_path / "bad.yaml"
    bad.write_text("tables:\n  - {name: t}\n")
    result = runner.invoke(cli, ["--port", str(free_port), "start", "--native", "--seed", str(bad)])
    assert result.exit_code == 2 and "'pk' is required" in result.output
    assert runtime.State.load(free_port) is None


def test_example_seed_is_valid():
    """examples/seed.yaml is documentation: keep it valid."""
    example = Path(__file__).resolve().parents[1] / "examples" / "seed.yaml"
    s = seed.load_file(example)
    assert s.warnings == []
    assert s.count() == {"buckets": 1, "queues": 3, "tables": 2, "topics": 1, "secrets": 2, "parameters": 3}
