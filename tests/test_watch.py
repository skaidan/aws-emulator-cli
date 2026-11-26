"""awsemu watch: snapshot diffs and the command with fake clients."""

from awsemu.cli import cli
from awsemu.commands import watch as w
from tests.test_services import FakeClient


def test_diff_created_deleted_changed():
    before = {("queue", "jobs"): 0, ("queue", "old"): 1, ("table", "users"): 2, ("topic", "t"): None}
    after = {
        ("queue", "jobs"): 3,
        ("table", "users"): 2,
        ("bucket", "new"): 5,
        ("topic", "t"): None,
        ("topic", "u"): None,
    }
    assert w.diff(before, after) == [
        ("+", "bucket", "new", "5 object(s)"),
        ("+", "topic", "u", ""),
        ("-", "queue", "old", ""),
        ("~", "queue", "jobs", "0 → 3 message(s) (+3)"),
    ]


def test_diff_decrease():
    assert w.diff({("table", "t"): 5}, {("table", "t"): 2}) == [("~", "table", "t", "5 → 2 item(s) (-3)")]


def test_snapshot_isolates_failing_services(monkeypatch):
    class Boom(Exception):
        response = {"Error": {"Code": "InternalFailure", "Message": "nope"}}

    def boom(**_):
        raise Boom()

    clients = {
        "sqs": FakeClient(
            list_queues={"QueueUrls": ["https://x/000000000000/jobs"]},
            get_queue_attributes={"Attributes": {"ApproximateNumberOfMessages": "4"}},
        ),
        "s3": FakeClient(list_buckets=boom),
    }
    monkeypatch.setattr(w, "client", lambda service, port: clients[service])
    snaps, errors = w.snapshot(9297, ["sqs", "s3"])
    assert snaps == {"sqs": {("queue", "jobs"): 4}}
    assert "InternalFailure" in errors["s3"]


def test_watch_once(runner, monkeypatch, running):
    monkeypatch.setattr(w.health, "check", lambda port: type("H", (), {"healthy": True, "detail": ""})())
    clients = {
        "sqs": FakeClient(
            list_queues={"QueueUrls": ["https://x/000000000000/jobs"]},
            get_queue_attributes={"Attributes": {"ApproximateNumberOfMessages": "2"}},
        ),
        "dynamodb": FakeClient(list_tables=[{"TableNames": ["users"]}], scan={"Count": 7}),
    }
    monkeypatch.setattr(w, "client", lambda service, port: clients[service])
    result = runner.invoke(cli, ["watch", "--once", "-s", "sqs", "-s", "dynamodb"])
    assert result.exit_code == 0, result.output
    assert "jobs" in result.output and "2 message(s)" in result.output and "7 item(s)" in result.output


def test_watch_loop_prints_changes(runner, monkeypatch, running):
    monkeypatch.setattr(w.health, "check", lambda port: type("H", (), {"healthy": True, "detail": ""})())
    monkeypatch.setattr(w.health, "port_open", lambda port: True)
    states = iter([{"sqs": {("queue", "jobs"): 0}}, {"sqs": {("queue", "jobs"): 2, ("queue", "dlq"): 0}}])
    monkeypatch.setattr(w, "snapshot", lambda port, services: (next(states), {}))
    sleeps = iter([None, KeyboardInterrupt()])

    def fake_sleep(_):
        v = next(sleeps)
        if isinstance(v, BaseException):
            raise v

    monkeypatch.setattr(w.time, "sleep", fake_sleep)
    result = runner.invoke(cli, ["watch", "-s", "sqs"])
    assert result.exit_code == 0, result.output
    assert "+ queue         dlq" in result.output
    assert "~ queue         jobs  0 → 2 message(s) (+2)" in result.output


def test_watch_needs_emulator(runner):
    result = runner.invoke(cli, ["--port", "1", "watch", "--once"])
    assert result.exit_code == 1 and "awsemu up" in result.output
