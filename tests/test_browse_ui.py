"""awsemu ui: the data layer (always) and the Textual app (when Textual is installed)."""

import asyncio
import json
from datetime import datetime

import pytest

from awsemu import browse
from awsemu.cli import cli
from tests.test_services import FakeClient


@pytest.fixture
def fake_emulator(monkeypatch):
    fakes = {
        "s3": FakeClient(
            list_buckets={"Buckets": [{"Name": "photos"}]},
            list_objects_v2={"Contents": [{"Key": "a.txt", "Size": 4, "LastModified": datetime(2026, 11, 16)}]},
        ),
        "sqs": FakeClient(
            list_queues={"QueueUrls": ["https://x/000000000000/jobs"]},
            get_queue_url={"QueueUrl": "https://x/000000000000/jobs"},
            get_queue_attributes={"Attributes": {"ApproximateNumberOfMessages": "3"}},
        ),
        "secretsmanager": FakeClient(describe_secret={"Name": "db", "ARN": "arn:x", "ResponseMetadata": {}}),
        "ssm": FakeClient(get_parameter={"Parameter": {"Name": "/k", "Type": "SecureString", "Value": "plain-secret"}}),
    }

    def fake_client(service, port):
        return fakes.get(service) or FakeClient(
            **{
                "list_tables": {"TableNames": []},
                "list_event_buses": {"EventBuses": []},
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
                        "list_tables",
                    )
                },
            }
        )

    import awsemu.commands.overview as overview

    monkeypatch.setattr(browse, "client", fake_client)
    monkeypatch.setattr(overview, "client", fake_client)
    return fakes


def test_details(fake_emulator):
    s3 = browse.details(9297, "s3", "photos")
    assert s3["Objects (first 50)"][0]["Key"] == "a.txt"
    assert browse.details(9297, "sqs", "jobs")["ApproximateNumberOfMessages"] == "3"
    assert "ResponseMetadata" not in browse.details(9297, "secretsmanager", "db")


def test_secure_values_are_hidden(fake_emulator):
    assert browse.details(9297, "ssm", "/k")["Value"] == "****"


def test_ui_without_textual_explains(runner, monkeypatch):
    import builtins

    real_import = builtins.__import__

    def no_textual(name, *a, **k):
        if name == "textual" or name.startswith("textual.") or name.endswith("tui"):
            raise ImportError("no textual")
        return real_import(name, *a, **k)

    monkeypatch.setattr(builtins, "__import__", no_textual)
    result = runner.invoke(cli, ["ui"])
    from awsemu import _meta

    assert result.exit_code == 1 and _meta.install_hint("ui") in result.output


def test_textual_app(fake_emulator, monkeypatch):
    pytest.importorskip("textual")
    from textual.widgets import Tree

    from awsemu import tui

    monkeypatch.setattr(tui.health, "check", lambda port: type("H", (), {"healthy": True})())

    async def scenario():
        app = tui.EmulatorApp(port=9297)
        async with app.run_test() as pilot:
            await pilot.pause()
            tree = app.query_one(Tree)
            labels = [str(n.label) for n in tree.root.children]
            assert "S3 buckets (1)" in labels and "SQS queues (1)" in labels
            s3_node = next(n for n in tree.root.children if str(n.label).startswith("S3"))
            leaf = s3_node.children[0]
            assert leaf.data == ("s3", "photos")
            app.show_details("s3", "photos")
            assert app.current_details["Bucket"] == "photos"
            await pilot.press("r")
            await pilot.pause()
            assert app.selected == ("s3", "photos") and app.current_details["Bucket"] == "photos"
            await pilot.press("w")
            assert app.auto is True
            await pilot.press("q")

    asyncio.run(scenario())


def test_textual_app_without_emulator(monkeypatch):
    pytest.importorskip("textual")
    from textual.widgets import Tree

    from awsemu import tui

    monkeypatch.setattr(tui.health, "check", lambda port: type("H", (), {"healthy": False})())

    async def scenario():
        app = tui.EmulatorApp(port=1)
        async with app.run_test() as pilot:
            await pilot.pause()
            assert "No healthy emulator" in str(app.query_one(Tree).root.label)
            assert app.last_error == "emulator not running"

    asyncio.run(scenario())


def test_to_json_handles_aws_types():
    pytest.importorskip("textual")
    from decimal import Decimal

    from awsemu import tui

    data = json.loads(tui._to_json({"d": datetime(2026, 1, 1), "n": Decimal("1.5"), "b": b"x"}))
    assert data == {"d": "2026-01-01T00:00:00", "n": 1.5, "b": "x"}


def _write_calls(port, calls):
    import json

    from awsemu import proxy as px

    files = px.ProxyFiles(port)
    files.dir.mkdir(parents=True, exist_ok=True)
    with files.calls.open("a", encoding="utf-8") as fh:
        for c in calls:
            fh.write(json.dumps(c) + "\n")
    return files


def _call(op, error=None, fault=None, n=1):
    return {
        "id": n,
        "time": "2026-11-25T10:00:00.123+00:00",
        "service": "dynamodb",
        "operation": op,
        "resource": "orders",
        "method": "POST",
        "path": "/",
        "status": 400 if error else 200,
        "error": error,
        "latency_ms": 3.2,
        "request_id": None,
        "fault": fault,
        "bytes_in": 1,
        "bytes_out": 2,
    }


def test_proxy_calls_tail():
    from awsemu import browse

    assert browse.proxy_calls(9297) == ([], 0, False)
    files = _write_calls(9297, [_call("PutItem"), _call("GetItem")])
    calls, pos, running = browse.proxy_calls(9297)
    assert [c["operation"] for c in calls] == ["PutItem", "GetItem"] and not running
    assert browse.proxy_calls(9297, pos) == ([], pos, False)
    _write_calls(9297, [_call("Query")])
    calls, pos2, _ = browse.proxy_calls(9297, pos)
    assert [c["operation"] for c in calls] == ["Query"] and pos2 > pos
    files.calls.write_text("")  # rotated
    assert browse.proxy_calls(9297, pos2)[0] == []
    assert [c["operation"] for c in browse.proxy_calls(9297, last=1)[0]] == []


def test_textual_calls_screen(monkeypatch):
    pytest.importorskip("textual")
    from textual.widgets import DataTable, Static

    from awsemu import tui

    monkeypatch.setattr(tui.health, "check", lambda port: type("H", (), {"healthy": False})())
    _write_calls(9297, [_call("PutItem"), _call("GetItem", "ThrottlingException", "dynamodb=throttle")])

    async def scenario():
        app = tui.EmulatorApp(port=9297)
        async with app.run_test() as pilot:
            await pilot.press("c")
            await pilot.pause()
            screen = app.screen
            assert isinstance(screen, tui.CallsScreen)
            table = screen.query_one(DataTable)
            assert table.row_count == 2
            assert "no proxy running" in str(screen.query_one("#calls-status", Static).render())
            _write_calls(9297, [_call("Query", n=3)])
            screen.poll()
            assert table.row_count == 3
            await pilot.press("e")
            assert table.row_count == 1
            await pilot.press("escape")
            assert not isinstance(app.screen, tui.CallsScreen)

    asyncio.run(scenario())
