"""``awsemu mcp``: an MCP server, so coding agents test against the emulator, not AWS.

It speaks the Model Context Protocol over stdio (JSON-RPC 2.0, one message per line)
with no extra dependency. Each tool runs an ``awsemu`` command in a child process,
with ``--json`` where the command has it, and returns its output.

Guard rails, in every tool:

* the child gets an environment without real AWS credentials, profiles or endpoint
  overrides (``AWS_ACCESS_KEY_ID``, ``AWS_PROFILE``, ``AWS_ENDPOINT_URL``…): awsemu's
  clients use the emulator's own keys and address anyway, and this makes sure;
* tools that talk to the emulator refuse unless its endpoint is on this machine
  (``127.0.0.1``, ``::1``, ``localhost``);
* no tool takes an endpoint, a region or credentials as an argument;
* every answer starts by saying where it ran ("AWS Emulator on 127.0.0.1:9297, not
  AWS"), so the agent, and whoever reads its transcript, can't mistake it for AWS.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable
from urllib.parse import urlsplit

from . import __version__
from .paths import InstanceFiles

PROTOCOL_VERSIONS = ("2025-06-18", "2025-03-26", "2024-11-05")
LOCAL_HOSTS = {"127.0.0.1", "::1", "localhost"}
SCRUBBED = ("AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY", "AWS_SESSION_TOKEN", "AWS_SECURITY_TOKEN",
            "AWS_PROFILE", "AWS_DEFAULT_PROFILE", "AWS_ENDPOINT_URL", "AWS_CONFIG_FILE",
            "AWS_SHARED_CREDENTIALS_FILE", "AWS_CA_BUNDLE", "AWS_ROLE_ARN", "AWS_WEB_IDENTITY_TOKEN_FILE",
            "AWS_CONTAINER_CREDENTIALS_FULL_URI", "AWS_CONTAINER_CREDENTIALS_RELATIVE_URI",
            "AWS_CONTAINER_AUTHORIZATION_TOKEN")
MAX_TEXT = 60_000
INSTRUCTIONS = """\
Tools for AWS Emulator, a local emulator of AWS services, managed by awsemu. Use them to run
and test code that calls AWS without touching a real AWS account: every tool works only
against the emulator on this machine (127.0.0.1) and never uses real credentials.

Typical flow: emulator_status, then emulator_start if it isn't running (seed_apply for
starting data), then run the code or tests with the command emulator_env returns (prefix it
with `awsemu exec --`, or set the variables it lists). list_resources and describe_resource
show what the code created; aws_call runs any API operation. When a call fails, explain_failure
says whether it's a known emulator difference or probably the code; fidelity and check_project
say how close the emulator is to AWS for a service or a project. To see every call your code
makes, start the proxy (proxy_start) and read proxy_calls; proxy_faults injects throttling,
errors and latency."""


def scrubbed_env(base: dict[str, str] | None = None) -> dict[str, str]:
    env = {k: v for k, v in (os.environ if base is None else base).items()
           if k not in SCRUBBED and not k.startswith("AWS_ENDPOINT_URL_")}
    env["AWSEMU_PLAIN"] = "1"
    env["NO_COLOR"] = "1"
    return env


class GuardError(Exception):
    pass


def local_endpoint(port: int) -> str:
    """The emulator's endpoint, if it's on this machine; GuardError otherwise.

    Checks the address awsemu uses and the one in the emulator's own config file."""
    import configparser

    files = InstanceFiles(port)
    urls = [files.endpoint_url]
    if files.config.exists():
        parser = configparser.ConfigParser()
        try:
            parser.read(files.config, encoding="utf-8")
            urls += [parser.get(sec, "endpoint_url") for sec in parser.sections()
                     if parser.has_option(sec, "endpoint_url")]
        except configparser.Error:
            pass
    for url in urls:
        host = urlsplit(url).hostname or ""
        if host not in LOCAL_HOSTS:
            raise GuardError(f"refusing: the endpoint {url} isn't on this machine (127.0.0.1); "
                             "these tools only work against a local AWS Emulator")
    return urls[0]


def where(port: int) -> str:
    return f"AWS Emulator on 127.0.0.1:{port} (this machine, not AWS; no real AWS account or credentials are used)"


# --------------------------------------------------------------------------- tools


@dataclass
class Tool:
    name: str
    title: str
    description: str
    properties: dict[str, Any]
    run: Callable[[Server, dict], tuple[list[str], bool]]  # -> (awsemu args, parse JSON)
    required: list[str] = field(default_factory=list)
    read_only: bool = True
    destructive: bool = False
    needs_emulator: bool = True
    timeout: float = 120
    ok_codes: tuple[int, ...] = (0,)  # exit codes that aren't an error

    def spec(self) -> dict:
        return {"name": self.name, "title": self.title, "description": self.description,
                "inputSchema": {"type": "object", "properties": self.properties, "required": self.required,
                                "additionalProperties": False},
                "annotations": {"title": self.title, "readOnlyHint": self.read_only,
                                "destructiveHint": self.destructive, "idempotentHint": self.read_only,
                                "openWorldHint": False}}


def _str(desc: str, **extra) -> dict:
    return {"type": "string", "description": desc, **extra}


def _int(desc: str, **extra) -> dict:
    return {"type": "integer", "description": desc, **extra}


def _bool(desc: str) -> dict:
    return {"type": "boolean", "description": desc}


def _proxy_faults(_s, a):
    action = a.get("action", "list")
    rules = list(a.get("rules") or [])
    if action == "list":
        return ["proxy", "faults", "--json"], True
    if action == "clear":
        return ["proxy", "faults", "clear"], False
    if not rules:
        raise ValueError(f"'{action}' needs 'rules'")
    return ["proxy", "faults", action, *rules], False


def _env(_s, a):
    args = ["env", "--shell", "dotenv"]
    for sdk in a.get("sdk") or []:
        args += ["--sdk", sdk]
    if a.get("proxy"):
        args.append("--proxy")
    return args, False


TOOLS: list[Tool] = [
    Tool("emulator_status", "Emulator status",
         "Is the emulator running and healthy, on which port, in which mode, since when. Call this first.",
         {}, lambda s, a: (["status", "--json"], True), needs_emulator=False, ok_codes=(0, 3)),
    Tool("emulator_start", "Start the emulator",
         "Start AWS Emulator on this machine (the installed binary, or Docker) and wait until it's healthy. "
         "Every start begins empty, with new credentials. Optionally apply a seed file (starting data).",
         {"seed": _str("A seed file (YAML) to apply once it's healthy, relative to the project folder.")},
         lambda s, a: (["start", "--wait", "90", *(["--seed", a["seed"]] if a.get("seed") else [])], False),
         read_only=False, needs_emulator=False, timeout=180),
    Tool("emulator_stop", "Stop the emulator",
         "Stop the emulator. Everything in it is lost (it keeps nothing between runs).",
         {}, lambda s, a: (["stop"], False), read_only=False, destructive=True, needs_emulator=False),
    Tool("emulator_env", "Environment for your code",
         "The environment variables that point AWS SDKs, the AWS CLI and Terraform at the emulator, "
         "as KEY=value lines. Easiest: run your command as `awsemu exec -- <command>`, which sets them.",
         {"sdk": {"type": "array", "items": {"type": "string", "enum": ["node", "java", "rust", "dotnet"]},
                  "description": "Also trust the emulator's certificate in these runtimes."},
          "proxy": _bool("Point the code at the proxy instead (it must be running).")},
         _env),
    Tool("seed_apply", "Apply a seed",
         "Create the resources a seed file describes (buckets, queues, tables with items, topics, secrets, "
         "parameters, functions…). Existing ones are updated, not duplicated.",
         {"file": _str("The seed file (YAML), relative to the project folder.")},
         lambda s, a: (["seed", "apply", a["file"]], False), required=["file"], read_only=False),
    Tool("list_resources", "List resources",
         "What's in the emulator, per service: buckets, queues, tables, topics, functions, secrets, "
         "parameters, streams, rules, state machines, log groups, roles.",
         {"services": {"type": "array", "items": {"type": "string"},
                       "description": "Only these services (s3, sqs, dynamodb, sns, lambda, secretsmanager, ssm, "
                                      "kinesis, events, stepfunctions, logs, iam)."}},
         lambda s, a: (["overview", "--json", *[x for svc in a.get("services") or [] for x in ("-s", svc)]], True)),
    Tool("describe_resource", "Describe a resource",
         "Everything about one resource, from its ARN (tables, queues, buckets, objects, topics, functions…).",
         {"arn": _str("The resource's ARN, like arn:aws:dynamodb:us-east-1:000000000000:table/orders.")},
         lambda s, a: (["describe", a["arn"]], True), required=["arn"]),
    Tool("aws_call", "Call an AWS operation",
         "Any operation of any service, against the emulator, through boto3. Parameters use the API's names. "
         "Errors from the service come back with their code and message.",
         {"service": _str("boto3 service name: s3, dynamodb, sqs, logs, stepfunctions…"),
          "operation": _str("Operation: ListBuckets, list_buckets or list-buckets."),
          "params": {"type": "object", "description": "The request parameters, as JSON."},
          "paginate": _bool("Follow every page and merge them."),
          "query": _str("A JMESPath expression to keep part of the response.")},
         lambda s, a: (["call", a["service"], a["operation"], "--params", json.dumps(a.get("params") or {}),
                        *(["--paginate"] if a.get("paginate") else []),
                        *(["--query", a["query"]] if a.get("query") else [])], True),
         required=["service", "operation"], read_only=False),
    Tool("fidelity", "Fidelity of the emulator",
         "How closely the emulator matches AWS, per service: the share of AWS's fidelity tests that pass "
         "for this emulator release, and with failures=true which tests fail and how.",
         {"services": {"type": "array", "items": {"type": "string"}, "description": "Services to show."},
          "failures": _bool("List the failing tests of those services.")},
         lambda s, a: (["fidelity", "--json", *(a.get("services") or []),
                        *(["--failures"] if a.get("failures") else [])], True), needs_emulator=False),
    Tool("check_project", "Check a project",
         "Find the AWS operations a project's code and infrastructure use and the known emulator differences "
         "for them. from_calls=true uses the operations the proxy saw instead of reading the code.",
         {"path": _str("Folder or file to scan, relative to the project folder (default: all of it)."),
          "from_calls": _bool("Check the operations in the proxy's calls log instead.")},
         lambda s, a: (["check", "--json", *(["--from-calls"] if a.get("from_calls") else [a.get("path") or "."])],
                       True), needs_emulator=False, timeout=180),
    Tool("proxy_start", "Start the proxy",
         "Start the awsemu proxy in front of the emulator: it logs every call your code makes (with headers "
         "and bodies, secrets masked) and can inject faults. Then run code with `awsemu exec --proxy -- …`.",
         {"faults": {"type": "array", "items": {"type": "string"},
                     "description": "Fault rules to start with, like dynamodb=throttle@10%."}},
         lambda s, a: (["proxy", "start", "-d", "--bodies", *[x for f in a.get("faults") or [] for x in ("--fault", f)]],
                       False), read_only=False),
    Tool("proxy_calls", "Calls through the proxy",
         "The API calls that went through the proxy: service, operation, resource, status, error, latency, "
         "and the id that explain_failure takes.",
         {"last": _int("How many of the latest calls (default 50).", minimum=1, maximum=1000),
          "errors_only": _bool("Only failed calls."),
          "service": _str("Only this service.")},
         lambda s, a: (["proxy", "calls", "--json", "-n", str(a.get("last") or 50),
                        *(["--errors"] if a.get("errors_only") else []),
                        *(["--service", a["service"]] if a.get("service") else [])], True)),
    Tool("proxy_faults", "Fault rules",
         "List, add, replace or clear the proxy's fault rules: throttling, AWS errors, latency, resets, "
         "per service, operation and resource, for a number of calls or a time "
         "(dynamodb:PutItem[orders]=throttle, s3=503 for 30s, sqs=latency:500ms@50%).",
         {"action": _str("list, add, set or clear.", enum=["list", "add", "set", "clear"]),
          "rules": {"type": "array", "items": {"type": "string"}, "description": "Rules, for add and set."}},
         _proxy_faults, read_only=False),
    Tool("explain_failure", "Explain a failed call",
         "Given a call from the proxy's log (its id, or 'last' for the last failed one), say whether it matches a "
         "known emulator difference or is probably a bug in the code under test, with the evidence.",
         {"call": _str("The call's id from proxy_calls, or 'last'.")},
         lambda s, a: (["explain", str(a.get("call") or "last"), "--json"], True), needs_emulator=False),
]
BY_NAME = {t.name: t for t in TOOLS}


# --------------------------------------------------------------------------- server


class Server:
    def __init__(self, port: int, cwd: Path | None = None, runner=None):
        self.port = port
        self.cwd = cwd or Path.cwd()
        self._runner = runner or self._run_awsemu

    def _run_awsemu(self, args: list[str], timeout: float) -> tuple[int, str, str]:
        cmd = [sys.executable, "-m", "awsemu", "--port", str(self.port), *args]
        env = scrubbed_env()
        package_root = str(Path(__file__).resolve().parent.parent)  # the same awsemu, even from a checkout
        env["PYTHONPATH"] = os.pathsep.join(filter(None, [package_root, env.get("PYTHONPATH")]))
        try:
            done = subprocess.run(cmd, cwd=self.cwd, env=env, capture_output=True, text=True, timeout=timeout,
                                  stdin=subprocess.DEVNULL)
        except subprocess.TimeoutExpired:
            return 124, "", f"timed out after {timeout:.0f} s"
        return done.returncode, done.stdout, done.stderr

    def call_tool(self, name: str, arguments: dict) -> dict:
        tool = BY_NAME.get(name)
        if tool is None:
            raise KeyError(name)
        header = where(self.port)
        try:
            if tool.needs_emulator:
                local_endpoint(self.port)
            args, parse = tool.run(self, arguments or {})
        except GuardError as exc:
            return _result(f"{header}\n\n{exc}", {"target": header, "refused": str(exc)}, error=True)
        except (KeyError, ValueError) as exc:
            return _result(f"{header}\n\nbad arguments: {exc}", None, error=True)
        code, out, err = self._runner(args, tool.timeout)
        text = out.strip()
        structured = None
        if parse and text and (code in tool.ok_codes or code == 1):
            try:
                structured = {"target": header, "result": json.loads(text)}
            except ValueError:
                pass
        if len(text) > MAX_TEXT:
            text = text[:MAX_TEXT] + f"\n… ({len(out) - MAX_TEXT} more characters)"
        body = "\n\n".join(filter(None, [header, text, err.strip() and f"stderr:\n{err.strip()[-4000:]}"]))
        failed = code not in tool.ok_codes
        if failed:
            body += f"\n\n(awsemu exited with code {code})"
        return _result(body, structured, error=failed)

    # -- JSON-RPC

    def handle(self, message: dict) -> dict | None:
        method, mid = message.get("method"), message.get("id")
        params = message.get("params") or {}
        if mid is None:  # a notification: nothing to answer
            return None
        try:
            if method == "initialize":
                asked = params.get("protocolVersion")
                version = asked if asked in PROTOCOL_VERSIONS else PROTOCOL_VERSIONS[0]
                result = {"protocolVersion": version, "capabilities": {"tools": {"listChanged": False}},
                          "serverInfo": {"name": "awsemu", "title": "awsemu (AWS Emulator)", "version": __version__},
                          "instructions": INSTRUCTIONS}
            elif method == "ping":
                result = {}
            elif method == "tools/list":
                result = {"tools": [t.spec() for t in TOOLS]}
            elif method == "tools/call":
                try:
                    result = self.call_tool(params.get("name", ""), params.get("arguments") or {})
                except KeyError:
                    return _error(mid, -32602, f"unknown tool: {params.get('name')}")
            elif method in ("resources/list", "prompts/list"):
                result = {method.split("/")[0]: []}
            else:
                return _error(mid, -32601, f"method not found: {method}")
        except Exception as exc:  # noqa: BLE001 - one bad request must not end the session
            return _error(mid, -32603, f"internal error: {exc}")
        return {"jsonrpc": "2.0", "id": mid, "result": result}

    def serve(self, stdin=None, stdout=None) -> None:
        stdin = stdin or sys.stdin
        stdout = stdout or sys.stdout
        for line in stdin:
            line = line.strip()
            if not line:
                continue
            try:
                message = json.loads(line)
            except ValueError:
                reply = _error(None, -32700, "parse error")
            else:
                if isinstance(message, list):  # a batch (older protocol versions)
                    replies = [r for r in (self.handle(m) for m in message if isinstance(m, dict)) if r]
                    if replies:
                        stdout.write(json.dumps(replies) + "\n")
                        stdout.flush()
                    continue
                reply = self.handle(message) if isinstance(message, dict) else _error(None, -32600, "invalid request")
            if reply is not None:
                stdout.write(json.dumps(reply) + "\n")
                stdout.flush()


def _result(text: str, structured: dict | None, error: bool = False) -> dict:
    out: dict = {"content": [{"type": "text", "text": text}], "isError": error}
    if structured is not None:
        out["structuredContent"] = structured
    return out


def _error(mid, code: int, message: str) -> dict:
    return {"jsonrpc": "2.0", "id": mid, "error": {"code": code, "message": message}}
