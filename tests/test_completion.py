"""Shell completion: commands, and resource names from the (fake) emulator."""

import pytest
from click.shell_completion import ShellComplete

from awsemu import clients, completion
from awsemu.cli import cli
from tests.test_services import FakeClient


def complete(args, incomplete):
    comp = ShellComplete(cli, {}, "awsemu", "_AWSEMU_COMPLETE")
    return [c.value for c in comp.get_completions(args, incomplete)]


@pytest.fixture
def emulator(monkeypatch):
    """A 'running' emulator whose clients are fakes; records the port used."""
    used = []
    fakes = {
        "sqs": FakeClient(list_queues={"QueueUrls": ["https://x/000000000000/jobs",
                                                     "https://x/000000000000/jobs-dlq",
                                                     "https://x/000000000000/mail"]}),
        "dynamodb": FakeClient(list_tables=[{"TableNames": ["users", "orders"]}]),
        "s3": FakeClient(list_buckets={"Buckets": [{"Name": "photos"}, {"Name": "logs"}]},
                         list_objects_v2=lambda **kw: {
                             "CommonPrefixes": [{"Prefix": kw["Prefix"] + "2026/"}],
                             "Contents": [{"Key": kw["Prefix"] + "cat.jpg"}]}),
        "ssm": FakeClient(describe_parameters=[{"Parameters": [{"Name": "/app/host"}, {"Name": "/app/key"}]}]),
    }
    monkeypatch.setattr(completion.health, "port_open", lambda port, timeout=0.5: True)

    def fake_client(service, port):
        used.append(port)
        return fakes[service]
    monkeypatch.setattr(clients, "client", fake_client)
    return used


def test_commands_complete():
    assert "fidelity" in complete([], "fi")
    assert {"send", "receive"} <= set(complete(["sqs"], ""))


def test_queue_names(emulator):
    assert complete(["sqs", "send"], "jo") == ["jobs", "jobs-dlq"]
    assert complete(["sqs", "create", "x", "--dlq"], "") == ["jobs", "jobs-dlq", "mail"]
    assert complete(["sns", "subscribe", "t", "--to-sqs"], "m") == ["mail"]


def test_table_and_parameter_names(emulator):
    assert complete(["dynamodb", "scan"], "") == ["orders", "users"]
    assert complete(["ddb", "get"], "u") == ["users"]
    assert complete(["ssm", "get"], "/app/k") == ["/app/key"]
    assert complete(["ssm", "rm", "/app/host"], "/app/") == ["/app/host", "/app/key"]


def test_s3_paths(emulator):
    assert complete(["s3", "ls"], "") == ["logs/", "photos/"]
    assert complete(["s3", "cat"], "photos/") == ["photos/2026/", "photos/cat.jpg"]
    assert complete(["s3", "cat"], "s3://ph") == ["s3://photos/"]


def test_global_port_is_used(emulator):
    complete(["--port", "9411", "sqs", "send"], "")
    assert emulator[-1] == 9411


def test_nothing_when_emulator_is_down(monkeypatch):
    monkeypatch.setattr(completion.health, "port_open", lambda port, timeout=0.5: False)
    assert complete(["sqs", "send"], "") == []


def test_errors_are_silent(monkeypatch):
    monkeypatch.setattr(completion.health, "port_open", lambda port, timeout=0.5: True)

    def boom(service, port):
        raise RuntimeError("no")
    monkeypatch.setattr(clients, "client", boom)
    assert complete(["dynamodb", "scan"], "") == []


@pytest.mark.parametrize("shell,needle", [("bash", "_AWSEMU_COMPLETE=bash_complete"),
                                          ("zsh", "#compdef awsemu"),
                                          ("fish", "complete --no-files --command awsemu")])
def test_completion_scripts(runner, shell, needle):
    result = runner.invoke(cli, ["completion", shell])
    assert result.exit_code == 0 and needle in result.output
