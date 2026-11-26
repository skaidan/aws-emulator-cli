"""The proxy, end to end: boto3 -> proxy -> a fake AWS over HTTPS."""

import http.client
import json
import ssl
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from awsemu import proxy as px
from awsemu.paths import InstanceFiles

boto3 = pytest.importorskip("boto3")
pytest.importorskip("cryptography")

from botocore.config import Config  # noqa: E402
from botocore.exceptions import ClientError  # noqa: E402

from tests.fake_emulator import make_cert  # noqa: E402


class FakeAWS(ThreadingHTTPServer):
    """Answers a few DynamoDB, SQS and S3 calls like AWS would."""

    daemon_threads = True

    def __init__(self, folder):
        self.seen = []
        cert, key = folder / "cert.pem", folder / "key.pem"
        make_cert(cert, key)
        super().__init__(("127.0.0.1", 0), FakeHandler)
        ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        ctx.load_cert_chain(cert, key)
        self.socket = ctx.wrap_socket(self.socket, server_side=True)
        files = InstanceFiles(self.server_address[1])
        files.dir.mkdir(parents=True)
        files.ca.write_bytes(cert.read_bytes())
        threading.Thread(target=self.serve_forever, daemon=True).start()

    @property
    def port(self):
        return self.server_address[1]


class FakeHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *a):
        pass

    def reply(self, status, body=b"", headers=(), length=None):
        self.send_response(status)
        for k, v in headers:
            self.send_header(k, v)
        self.send_header("Content-Length", str(len(body) if length is None else length))
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def handle_any(self):
        n = int(self.headers.get("Content-Length") or 0)
        body = self.rfile.read(n) if n else b""
        if self.path == "/__admin/health":
            return self.reply(200, b"ok")
        self.server.seen.append((self.command, self.path, dict(self.headers), body))
        target = self.headers.get("X-Amz-Target", "")
        js = [("Content-Type", "application/x-amz-json-1.0")]
        if target.endswith(".PutItem"):
            if json.loads(body)["TableName"] == "missing":
                err = {"__type": "com.amazonaws.dynamodb.v20120810#ResourceNotFoundException",
                       "message": "Requested resource not found"}
                return self.reply(400, json.dumps(err).encode(), js)
            return self.reply(200, b"{}", js)
        if target.endswith(".CreateQueue"):
            url = f"https://{self.headers['Host']}/000000000000/{json.loads(body)['QueueName']}"
            return self.reply(200, json.dumps({"QueueUrl": url}).encode(), js)
        if self.path.startswith("/b1/k"):
            if self.command == "HEAD":
                return self.reply(200, headers=[("ETag", '"e"')], length=5)
            if self.command == "PUT":
                return self.reply(200, headers=[("ETag", '"e"')])
            return self.reply(200, b"hello", [("Content-Type", "text/plain")])
        return self.reply(404, b"<Error><Code>NoSuchBucket</Code></Error>")

    do_GET = do_PUT = do_POST = do_HEAD = do_DELETE = handle_any


@pytest.fixture
def aws(tmp_path):
    server = FakeAWS(tmp_path)
    yield server
    server.shutdown()


@pytest.fixture
def proxy(aws):
    printed = []
    server = px.ProxyServer(aws.port, 0, calls_file=px.ProxyFiles(aws.port).calls, on_call=printed.append)
    server.files.dir.mkdir(parents=True, exist_ok=True)
    server.start_thread()
    server.printed = printed
    yield server
    server.shutdown()
    server.server_close()


def client(server, service, attempts=3):
    return boto3.client(service, region_name="us-east-1", endpoint_url=server.endpoint_url,
                        verify=str(server.files.ca), aws_access_key_id="test", aws_secret_access_key="test",
                        config=Config(retries={"mode": "standard", "max_attempts": attempts}))


def ops(server):
    return [(c["service"], c["operation"], c["status"], c["error"], c["fault"]) for c in server.calls_after(0)]


def test_calls_are_forwarded_and_recorded(aws, proxy):
    ddb = client(proxy, "dynamodb")
    ddb.put_item(TableName="orders", Item={"id": {"S": "1"}})
    with pytest.raises(ClientError) as exc:
        ddb.put_item(TableName="missing", Item={"id": {"S": "1"}})
    assert exc.value.response["Error"]["Code"] == "ResourceNotFoundException"
    s3 = client(proxy, "s3")
    assert s3.get_object(Bucket="b1", Key="k")["Body"].read() == b"hello"
    assert s3.head_object(Bucket="b1", Key="k")["ContentLength"] == 5
    s3.put_object(Bucket="b1", Key="k", Body=b"12345")

    assert ops(proxy) == [
        ("dynamodb", "PutItem", 200, None, None),
        ("dynamodb", "PutItem", 400, "ResourceNotFoundException", None),
        ("s3", "GetObject", 200, None, None),
        ("s3", "HeadObject", 200, None, None),
        ("s3", "PutObject", 200, None, None),
    ]
    calls = proxy.calls_after(0)
    assert calls[1]["resource"] == "missing" and calls[2]["resource"] == "b1/k"
    assert calls[2]["bytes_out"] == 5 and calls[4]["bytes_in"] >= 5  # aws-chunked adds a checksum
    assert [c["id"] for c in calls] == [1, 2, 3, 4, 5]
    assert len(proxy.printed) == 5
    lines = px.ProxyFiles(aws.port).calls.read_text().splitlines()
    assert json.loads(lines[1])["error"] == "ResourceNotFoundException"
    assert proxy.calls_after(4) == [calls[4]]


def test_bodies_are_logged_masked_only_when_asked(aws, proxy):
    client(proxy, "dynamodb").put_item(TableName="orders", Item={"id": {"S": "1"}, "Password": {"S": "p"}})
    assert "request" not in proxy.calls_after(0)[0]  # off by default
    proxy.bodies = True
    client(proxy, "dynamodb").put_item(TableName="orders", Item={"id": {"S": "2"}, "Password": {"S": "p"}})
    assert client(proxy, "s3").get_object(Bucket="b1", Key="k")["Body"].read() == b"hello"
    put, get = proxy.calls_after(1)
    assert dict(put["request"]["headers"])["Authorization"] == "***"
    sent = json.loads(put["request"]["body"]["text"])
    assert sent["Item"]["id"] == {"S": "2"} and sent["Item"]["Password"] == "***"
    assert put["response"] == {"status": 200, "headers": put["response"]["headers"], "body": {"size": 2, "text": "{}"}}
    assert get["response"]["body"] == {"size": 5, "text": "hello"}
    logged = json.loads(px.ProxyFiles(aws.port).calls.read_text().splitlines()[-1])
    assert logged["response"]["body"]["text"] == "hello"


def test_har_export(runner, aws, proxy, tmp_path):
    from awsemu.cli import cli

    proxy.bodies = True
    client(proxy, "dynamodb").put_item(TableName="orders", Item={"id": {"S": "1"}})
    assert client(proxy, "s3").get_object(Bucket="b1", Key="k")["Body"].read() == b"hello"
    proxy.bodies = False
    with pytest.raises(ClientError):
        client(proxy, "dynamodb").put_item(TableName="missing", Item={"id": {"S": "1"}})
    out = tmp_path / "calls.har"
    result = runner.invoke(cli, ["--port", str(aws.port), "proxy", "har", "-o", str(out)])
    assert result.exit_code == 0, result.output
    log = json.loads(out.read_text())["log"]
    assert log["version"] == "1.2" and len(log["entries"]) == 3
    put, get, missing = log["entries"]
    assert put["request"]["method"] == "POST" and put["request"]["url"].startswith("https://127.0.0.1:")
    assert {"name": "Authorization", "value": "***"} in put["request"]["headers"]
    assert json.loads(put["request"]["postData"]["text"])["TableName"] == "orders"
    assert get["response"]["content"] == {"size": 5, "mimeType": "text/plain", "text": "hello"}
    assert get["_awsemu"]["operation"] == "GetObject" and get["comment"] == "s3 GetObject b1/k"
    assert missing["response"]["status"] == 400 and missing["request"]["headers"] == []  # logged without --bodies
    only = json.loads(runner.invoke(cli, ["--port", str(aws.port), "proxy", "har", "--errors", "-o", "-"]).output)
    assert [e["_awsemu"]["error"] for e in only["log"]["entries"]] == ["ResourceNotFoundException"]


def test_big_and_binary_bodies():
    rec = px.body_record(b"x" * (px.MAX_BODY + 10), "text/plain")
    assert rec["truncated"] and rec["size"] == px.MAX_BODY + 10 and len(rec["text"]) == px.MAX_BODY
    assert px.body_record(b"\xff\x00", "") == {"size": 2, "base64": "/wA="}
    assert px.body_record(b"", "") == {"size": 0}


def test_host_header_and_signature_go_through(aws, proxy):
    sqs = client(proxy, "sqs")
    url = sqs.create_queue(QueueName="jobs")["QueueUrl"]
    assert url == f"https://127.0.0.1:{proxy.port}/000000000000/jobs"  # built from Host: points at the proxy
    method, path, headers, body = aws.seen[-1]
    assert headers["Host"] == f"127.0.0.1:{proxy.port}"
    assert headers["Authorization"].startswith("AWS4-HMAC-SHA256 Credential=test/")
    assert json.loads(body) == {"QueueName": "jobs"}


def test_throttling_is_retried_by_the_sdk(aws, proxy):
    proxy.faults.add(px.faults.parse("dynamodb:PutItem=throttle x2"))
    client(proxy, "dynamodb").put_item(TableName="orders", Item={"id": {"S": "1"}})
    assert ops(proxy) == [
        ("dynamodb", "PutItem", 400, "ThrottlingException", "dynamodb:PutItem=throttle x2"),
        ("dynamodb", "PutItem", 400, "ThrottlingException", "dynamodb:PutItem=throttle x2"),
        ("dynamodb", "PutItem", 200, None, None),
    ]
    assert len(aws.seen) == 1  # the emulator only saw the call that got through


def test_errors_reach_the_code_when_retries_run_out(aws, proxy):
    proxy.faults.add(px.faults.parse("s3=throttle"))
    with pytest.raises(ClientError) as exc:
        client(proxy, "s3", attempts=2).get_object(Bucket="b1", Key="k")
    assert exc.value.response["Error"]["Code"] == "SlowDown"
    assert exc.value.response["ResponseMetadata"]["HTTPStatusCode"] == 503
    proxy.faults.replace([px.faults.parse("dynamodb=ConditionalCheckFailedException")])
    with pytest.raises(ClientError) as exc:
        client(proxy, "dynamodb").put_item(TableName="orders", Item={"id": {"S": "1"}})
    assert exc.value.response["Error"]["Code"] == "ConditionalCheckFailedException"
    assert "Injected by awsemu proxy" in exc.value.response["Error"]["Message"]


def test_a_rule_for_one_resource_leaves_the_others_alone(aws, proxy):
    proxy.faults.add(px.faults.parse("dynamodb:PutItem[orders]=ConditionalCheckFailedException"))
    ddb = client(proxy, "dynamodb")
    with pytest.raises(ClientError):
        ddb.put_item(TableName="orders", Item={"id": {"S": "1"}})
    ddb.put_item(TableName="users", Item={"id": {"S": "1"}})  # not injected


def test_latency(aws, proxy):
    proxy.faults.add(px.faults.parse("s3:GetObject=latency:300ms"))
    started = time.perf_counter()
    client(proxy, "s3").get_object(Bucket="b1", Key="k")["Body"].read()
    assert time.perf_counter() - started >= 0.3
    call = proxy.calls_after(0)[0]
    assert call["latency_ms"] >= 300 and call["fault"] == "s3:GetObject=latency:300ms"


def test_reset_is_retried_as_a_connection_error(aws, proxy):
    proxy.faults.add(px.faults.parse("dynamodb=reset x1"))
    client(proxy, "dynamodb").put_item(TableName="orders", Item={"id": {"S": "1"}})
    assert [c["error"] for c in proxy.calls_after(0)] == ["ConnectionReset", None]


def test_emulator_down_is_a_502(tmp_path, isolated_home):
    server = px.ProxyServer(1, 0)  # nothing on port 1, and no CA file for it
    server.start_thread()
    try:
        with pytest.raises(ClientError) as exc:
            client(server, "dynamodb", attempts=1).list_tables()
        assert exc.value.response["Error"]["Code"] == "EmulatorUnreachable"
        assert server.calls_after(0)[0]["status"] == 502
    finally:
        server.shutdown()
        server.server_close()


def test_chunked_request_body(aws, proxy):
    ctx = ssl.create_default_context(cafile=str(proxy.files.ca))
    conn = http.client.HTTPSConnection("127.0.0.1", proxy.port, context=ctx)
    conn.putrequest("PUT", "/b1/k")
    conn.putheader("Transfer-Encoding", "chunked")
    conn.endheaders()
    for chunk in (b"abc", b"defg"):
        conn.send(f"{len(chunk):x}\r\n".encode() + chunk + b"\r\n")
    conn.send(b"0\r\n\r\n")
    assert conn.getresponse().status == 200
    method, path, headers, body = aws.seen[-1]
    assert body == b"abcdefg" and headers["Content-Length"] == "7"
    assert "Transfer-Encoding" not in headers


def test_admin_api(aws, proxy):
    state = {"endpoint_url": proxy.endpoint_url, "ca": str(proxy.files.ca)}
    assert px.admin(state, "GET", "health")["emulator_port"] == aws.port
    px.admin(state, "PUT", "faults", {"rules": ["s3=503@50%", "sqs=latency:10ms"]})
    px.admin(state, "POST", "faults", {"rules": ["dynamodb=throttle"]})
    rules = px.admin(state, "GET", "faults")["rules"]
    assert [r["spec"] for r in rules] == ["s3=503@50%", "sqs=latency:10ms", "dynamodb=throttle"]
    with pytest.raises(px.ProxyError, match="isn't a fault rule"):
        px.admin(state, "POST", "faults", {"rules": ["nonsense"]})
    assert px.admin(state, "DELETE", "faults")["rules"] == []
    client(proxy, "s3").get_object(Bucket="b1", Key="k")
    data = px.admin(state, "GET", "calls?after=0")
    assert data["last"] == 1 and data["calls"][0]["operation"] == "GetObject"
    with pytest.raises(px.ProxyError, match="unknown admin route"):
        px.admin(state, "GET", "nope")


def test_ca_is_kept_and_server_cert_renewed(isolated_home):
    files = px.ProxyFiles(1)
    px.ensure_certs(files)
    ca = files.ca.read_bytes()
    cert = files.cert.read_bytes()
    px.ensure_certs(files)
    assert files.ca.read_bytes() == ca and files.cert.read_bytes() == cert
    files.cert.unlink()
    px.ensure_certs(files)
    assert files.ca.read_bytes() == ca and files.cert.read_bytes() != cert


# --------------------------------------------------------------------------- commands


from awsemu.cli import cli  # noqa: E402


def test_commands(runner, aws, monkeypatch):
    port = str(aws.port)
    result = runner.invoke(cli, ["--port", port, "proxy", "start", "-d", "--listen", "0",
                                 "--fault", "dynamodb:PutItem=ConditionalCheckFailedException x1"])
    assert result.exit_code == 0, result.output
    try:
        assert "Proxy listening on https://127.0.0.1:" in result.output
        status = json.loads(runner.invoke(cli, ["--port", port, "proxy", "status", "--json"]).output)
        assert status["running"] and status["faults"] == ["dynamodb:PutItem=ConditionalCheckFailedException x1"]
        again = runner.invoke(cli, ["--port", port, "proxy", "start", "-d"])
        assert again.exit_code == 1 and "already running" in again.output

        env = runner.invoke(cli, ["--port", port, "env", "--proxy", "--shell", "dotenv"]).output
        assert f"AWS_ENDPOINT_URL={status['endpoint_url']}" in env
        assert f"AWS_CA_BUNDLE={status['ca']}" in env

        state = px.read_state(aws.port)
        ddb = boto3.client("dynamodb", region_name="us-east-1", endpoint_url=state["endpoint_url"],
                           verify=state["ca"], aws_access_key_id="t", aws_secret_access_key="t")
        with pytest.raises(ClientError):
            ddb.put_item(TableName="orders", Item={"id": {"S": "1"}})
        ddb.put_item(TableName="orders", Item={"id": {"S": "1"}})

        faults_out = runner.invoke(cli, ["--port", port, "proxy", "faults", "add", "s3=latency:5ms"]).output
        assert "s3=latency:5ms" in faults_out
        listed = json.loads(runner.invoke(cli, ["--port", port, "proxy", "faults", "--json"]).output)
        assert listed == [{"rule": "dynamodb:PutItem=ConditionalCheckFailedException x1", "hits": 1,
                           "active": False, "remaining_s": None},
                          {"rule": "s3=latency:5ms", "hits": 0, "active": True, "remaining_s": None}]
        bad = runner.invoke(cli, ["--port", port, "proxy", "faults", "add", "nonsense"])
        assert bad.exit_code == 2
        runner.invoke(cli, ["--port", port, "proxy", "faults", "set", "sqs=503"])
        assert json.loads(runner.invoke(cli, ["--port", port, "proxy", "faults", "--json"]).output)[0]["rule"] == "sqs=503"
        assert "No fault rules" in runner.invoke(cli, ["--port", port, "proxy", "faults", "clear"]).output

        calls = json.loads(runner.invoke(cli, ["--port", port, "proxy", "calls", "--json"]).output)
        assert [(c["operation"], c["error"]) for c in calls] == [
            ("PutItem", "ConditionalCheckFailedException"), ("PutItem", None)]
        assert calls[0]["fault"] == "dynamodb:PutItem=ConditionalCheckFailedException x1"
        errors = json.loads(runner.invoke(cli, ["--port", port, "proxy", "calls", "--errors", "--json"]).output)
        assert len(errors) == 1
        text = runner.invoke(cli, ["--port", port, "watch", "--calls", "--once"]).output
        assert "dynamodb PutItem" in text and "ConditionalCheckFailedException" in text and "⚡" in text
        assert "None of the 2 logged call(s) match" in runner.invoke(
            cli, ["--port", port, "proxy", "calls", "--service", "s3"]).output
    finally:
        stopped = runner.invoke(cli, ["--port", port, "proxy", "stop"])
    assert "stopped" in stopped.output
    assert runner.invoke(cli, ["--port", port, "proxy", "status"]).exit_code == 3
    assert "No proxy running" in runner.invoke(cli, ["--port", port, "proxy", "stop"]).output
    assert "no proxy is running" in runner.invoke(cli, ["--port", port, "env", "--proxy"]).output


def test_bad_fault_option(runner, aws):
    result = runner.invoke(cli, ["--port", str(aws.port), "proxy", "start", "--fault", "s3"])
    assert result.exit_code == 2 and "isn't a fault rule" in result.output


def test_project_proxy_with_up_env_and_stop(runner, fake_binary, free_port, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "awsemu.toml").write_text(
        f'port = {free_port}\nproxy = true\nproxy_port = 0\nfaults = ["s3=throttle@1%"]\n')
    from awsemu import project

    project.clear_cache()
    up = runner.invoke(cli, ["up"])
    try:
        assert up.exit_code == 0, up.output
        assert "Proxy started at https://127.0.0.1:" in up.output and "s3=throttle@1%" in up.output
        state = px.running(free_port)
        env = runner.invoke(cli, ["env", "--shell", "dotenv"]).output
        assert f"AWS_ENDPOINT_URL={state['endpoint_url']}" in env  # proxy = true: on by default
        direct = runner.invoke(cli, ["env", "--shell", "dotenv", "--no-proxy"]).output
        assert f"AWS_ENDPOINT_URL=https://127.0.0.1:{free_port}" in direct
        assert "already running" in runner.invoke(cli, ["up"]).output
    finally:
        down = runner.invoke(cli, ["down"])
    assert "proxy stopped" in down.output
    assert px.running(free_port) is None


def test_bad_project_faults(tmp_path):
    from awsemu import project

    path = tmp_path / "awsemu.toml"
    path.write_text('faults = ["dynamodb"]\n')
    with pytest.raises(project.ProjectError, match="faults"):
        project.parse(path)


# --------------------------------------------------------------------------- pytest fixtures


def test_pytest_fixtures(pytester, aws, monkeypatch):
    import os

    from tests.test_pytest_plugin import SRC, run

    monkeypatch.setenv("PYTHONPATH", os.pathsep.join(filter(None, [SRC, os.environ.get("PYTHONPATH")])))
    InstanceFiles(aws.port).credentials.write_text("[default]\naws_access_key_id = t\naws_secret_access_key = t\n")
    pytester.makepyfile(test_inner="""
        import boto3, pytest
        from botocore.config import Config
        from botocore.exceptions import ClientError

        def save(table):
            ddb = boto3.client("dynamodb", config=Config(retries={"mode": "standard", "max_attempts": 3}))
            ddb.put_item(TableName=table, Item={"id": {"S": "1"}})

        def test_retries_throttling(aws_faults):
            aws_faults.add("dynamodb:PutItem=throttle x2")
            save("orders")
            assert aws_faults.operations() == ["dynamodb:PutItem"] * 3
            assert [c["error"] for c in aws_faults.calls] == ["ThrottlingException"] * 2 + [None]

        def test_rules_were_removed_and_calls_are_per_test(aws_faults):
            assert aws_faults.rules == []
            save("orders")
            assert aws_faults.operations() == ["dynamodb:PutItem"]

        def test_error_reaches_the_code(aws_faults):
            aws_faults.add("dynamodb=ConditionalCheckFailedException")
            with pytest.raises(ClientError) as exc:
                save("orders")
            assert exc.value.response["Error"]["Code"] == "ConditionalCheckFailedException"

        def test_calls(aws_calls):
            aws_calls.client("s3").get_object(Bucket="b1", Key="k")
            save("missing") if False else None
            assert aws_calls.operations() == ["s3:GetObject"]
            assert aws_calls.calls[0]["resource"] == "b1/k"

        def test_bad_rule(aws_faults):
            aws_faults.add("nonsense")

        def test_without_proxy_goes_direct(aws_emulator):
            import os
            assert os.environ["AWS_ENDPOINT_URL"] == aws_emulator.endpoint_url
    """)
    result = run(pytester, "--awsemu-reuse", "--awsemu-port", str(aws.port), "-v")
    result.assert_outcomes(passed=5, failed=1)
    result.stdout.fnmatch_lines(["*test_bad_rule FAILED*", "*awsemu: 'nonsense' isn't a fault rule*"])

    pytester.makepyfile(test_inner="""
        import os
        def test_session_proxy(aws_emulator, aws_proxy):
            assert os.environ["AWS_ENDPOINT_URL"] == aws_proxy.endpoint_url != aws_emulator.endpoint_url
            assert aws_proxy.rules == ["s3=latency:1ms"]
    """)
    pytester.makefile(".toml", awsemu='faults = ["s3=latency:1ms"]\n')
    run(pytester, "--awsemu-reuse", "--awsemu-port", str(aws.port), "--awsemu-proxy").assert_outcomes(passed=1)
