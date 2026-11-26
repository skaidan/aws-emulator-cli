"""The MCP server: protocol, tools and guard rails (with a fake awsemu runner)."""

import io
import json

import pytest

from awsemu import mcp
from awsemu.cli import cli
from awsemu.paths import InstanceFiles


class FakeRunner:
    def __init__(self, code=0, out="", err=""):
        self.calls, self.code, self.out, self.err = [], code, out, err

    def __call__(self, args, timeout):
        self.calls.append(args)
        return self.code, self.out, self.err


@pytest.fixture
def running(isolated_home):
    files = InstanceFiles(9297)
    files.dir.mkdir(parents=True)
    files.ca.write_text("cert")
    files.config.write_text("[default]\nregion = us-east-1\nendpoint_url = https://127.0.0.1:9297\n")
    return files


def rpc(server, *messages):
    out = io.StringIO()
    server.serve(io.StringIO("".join(json.dumps(m) + "\n" for m in messages)), out)
    return [json.loads(line) for line in out.getvalue().splitlines()]


def test_handshake_list_and_unknowns():
    server = mcp.Server(9297, runner=FakeRunner())
    init, tools, ping, missing, bad_tool = rpc(
        server,
        {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"protocolVersion": "2025-03-26"}},
        {"jsonrpc": "2.0", "method": "notifications/initialized"},  # no answer
        {"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
        {"jsonrpc": "2.0", "id": 3, "method": "ping"},
        {"jsonrpc": "2.0", "id": 4, "method": "nope"},
        {"jsonrpc": "2.0", "id": 5, "method": "tools/call", "params": {"name": "nope"}},
    )
    assert init["result"]["protocolVersion"] == "2025-03-26" and "127.0.0.1" in init["result"]["instructions"]
    names = [t["name"] for t in tools["result"]["tools"]]
    assert {"emulator_start", "aws_call", "proxy_calls", "explain_failure", "fidelity"} <= set(names)
    for t in tools["result"]["tools"]:
        props = t["inputSchema"]["properties"]
        assert not {"endpoint", "endpoint_url", "region", "profile", "access_key"} & set(
            props
        )  # nothing to aim it elsewhere
        assert t["annotations"]["openWorldHint"] is False and t["description"]
    stop = next(t for t in tools["result"]["tools"] if t["name"] == "emulator_stop")
    assert stop["annotations"]["destructiveHint"] is True
    assert ping["result"] == {} and missing["error"]["code"] == -32601 and bad_tool["error"]["code"] == -32602
    newer = rpc(
        server, {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"protocolVersion": "2099-01-01"}}
    )
    assert newer[0]["result"]["protocolVersion"] == mcp.PROTOCOL_VERSIONS[0]
    assert rpc(server, "not json")[0]["error"]["code"] in (-32700, -32600)


def test_tools_run_awsemu_and_say_where(running):
    runner = FakeRunner(out=json.dumps({"services": []}))
    server = mcp.Server(9297, runner=runner)
    result = server.call_tool("list_resources", {"services": ["s3", "sqs"]})
    assert runner.calls[-1] == ["overview", "--json", "-s", "s3", "-s", "sqs"]
    assert result["content"][0]["text"].startswith("AWS Emulator on 127.0.0.1:9297 (this machine, not AWS")
    assert result["structuredContent"]["result"] == {"services": []} and result["isError"] is False

    server.call_tool(
        "aws_call",
        {"service": "dynamodb", "operation": "put-item", "params": {"TableName": "t"}, "query": "Attributes"},
    )
    assert runner.calls[-1] == [
        "call",
        "dynamodb",
        "put-item",
        "--params",
        '{"TableName": "t"}',
        "--query",
        "Attributes",
    ]
    server.call_tool("proxy_faults", {"action": "add", "rules": ["s3=503 for 30s"]})
    assert runner.calls[-1] == ["proxy", "faults", "add", "s3=503 for 30s"]
    assert server.call_tool("proxy_faults", {"action": "add"})["isError"]  # no rules
    server.call_tool("emulator_env", {"sdk": ["node"], "proxy": True})
    assert runner.calls[-1] == ["env", "--shell", "dotenv", "--sdk", "node", "--proxy"]
    server.call_tool("check_project", {"from_calls": True})
    assert runner.calls[-1] == ["check", "--json", "--from-calls"]


def test_failures_and_exit_codes(running):
    failing = mcp.Server(9297, runner=FakeRunner(1, "", "✗ NoSuchBucket"))
    result = failing.call_tool("describe_resource", {"arn": "arn:aws:s3:::nope"})
    assert (
        result["isError"]
        and "NoSuchBucket" in result["content"][0]["text"]
        and "code 1" in result["content"][0]["text"]
    )
    stopped = mcp.Server(9297, runner=FakeRunner(3, json.dumps({"status": "stopped"})))
    status = stopped.call_tool("emulator_status", {})
    assert status["isError"] is False and status["structuredContent"]["result"]["status"] == "stopped"


def test_guard_rails(running, monkeypatch):
    runner = FakeRunner()
    server = mcp.Server(9297, runner=runner)
    running.config.write_text("[default]\nendpoint_url = https://dynamodb.us-east-1.amazonaws.com\n")
    refused = server.call_tool("aws_call", {"service": "s3", "operation": "ListBuckets"})
    assert refused["isError"] and "refusing" in refused["content"][0]["text"] and runner.calls == []
    assert server.call_tool("emulator_status", {})["isError"] is False  # status still works, it's local

    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "AKIAREAL")
    monkeypatch.setenv("AWS_PROFILE", "prod")
    monkeypatch.setenv("AWS_ENDPOINT_URL_S3", "https://s3.amazonaws.com")
    monkeypatch.setenv("PATH_KEEP", "yes")
    env = mcp.scrubbed_env()
    assert "AWS_ACCESS_KEY_ID" not in env and "AWS_PROFILE" not in env and "AWS_ENDPOINT_URL_S3" not in env
    assert env["PATH_KEEP"] == "yes" and env["AWSEMU_PLAIN"] == "1"


def test_config_snippets(runner):
    assert runner.invoke(cli, ["mcp", "config", "claude-code"]).output.startswith("claude mcp add awsemu -- ")
    desktop = json.loads(runner.invoke(cli, ["mcp", "config", "claude-desktop"]).output)
    assert desktop["mcpServers"]["awsemu"]["args"][-1] == "mcp"
    vscode = json.loads(runner.invoke(cli, ["mcp", "config", "vscode"]).output)
    assert vscode["servers"]["awsemu"]["type"] == "stdio"
    other_port = runner.invoke(cli, ["--port", "9400", "mcp", "config", "json"]).output
    assert '"--port"' in other_port and '"9400"' in other_port
