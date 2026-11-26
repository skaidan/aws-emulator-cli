"""Find the AWS services and operations a project uses, by reading its files.

This is a static, heuristic scan: it never runs the code. It recognises

* SDK code: boto3/aioboto3 (Python), AWS SDK for JavaScript v2 and v3, AWS SDK for
  Java v1/v2 (and Kotlin), AWS SDK for Go v1/v2;
* infrastructure as code: Terraform (``resource``/``data "aws_*"``), CloudFormation
  and SAM templates (``Type: AWS::...``), and CDK apps (``aws-cdk-lib``/``aws_cdk``).

SDK calls are reported as candidate method names (``put_item``, ``PutItemCommand``,
``putItem``...) together with the services the file talks to. Turning a candidate into
an operation needs the list of real operations, which :mod:`awsemu.check` gets from
the fidelity tests; anything that isn't a real operation of those services is dropped.
Infrastructure files are reported per service (and resource type).
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from pathlib import Path

from ._service_names import BOTO_TO_SCORE

SKIP_DIRS = {
    ".git",
    ".hg",
    ".svn",
    "node_modules",
    ".venv",
    "venv",
    "env",
    ".env",
    "__pycache__",
    ".tox",
    ".nox",
    ".terraform",
    "dist",
    "build",
    "target",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    ".idea",
    ".vscode",
    "site-packages",
    "cdk.out",
    ".aws-sam",
    ".serverless",
    "vendor",
    ".gradle",
    ".next",
    "coverage",
}
CODE_EXT = {
    ".py": "python",
    ".js": "node",
    ".mjs": "node",
    ".cjs": "node",
    ".ts": "node",
    ".tsx": "node",
    ".jsx": "node",
    ".java": "java",
    ".kt": "java",
    ".go": "go",
}
TEMPLATE_EXT = {".json", ".yaml", ".yml", ".template"}
MAX_BYTES = 2_000_000


# --------------------------------------------------------------------------- names


SCORE_TO_BOTO = {v: k for k, v in BOTO_TO_SCORE.items()}
EXTRA_ALIASES = {
    # SDK class/package names that match neither the boto3 nor the score-file name
    "cognitoidentityserviceprovider": "cognito-idp",
    "cloudwatchevents": "events",
    "states": "stepfunctions",
    "eventbridge": "events",
    "certificatemanager": "acm",
    "opensearchservice": "opensearch",
    "kinesisfirehose": "firehose",
    "elbv2": "elbv2",
    "applicationautoscaling": "application-autoscaling",
    "kafka": "kafka",
    "msk": "kafka",
    "resourcegroupstaggingapi": "resourcegroupstaggingapi",
    "lexmodelbuildingservice": "lex-models",
}


def key(name: str) -> str:
    return re.sub(r"[-_ .]", "", name.lower())


def score_name(service: str) -> str:
    """boto3 client name -> service name in scores.json.gz (``logs`` -> ``cloudwatchlogs``)."""
    return BOTO_TO_SCORE.get(service, service.replace("-", ""))


class Names:
    """Maps any spelling of a service (boto3, JS/Java/Go package, Smithy) to its boto3 name."""

    def __init__(self, known: set[str]):
        self.known = known
        self.by_key: dict[str, str] = {}
        for name in known:
            self.by_key.setdefault(key(name), name)
            self.by_key.setdefault(key(score_name(name)), name)

    def resolve(self, name: str) -> str | None:
        k = key(name)
        if k in EXTRA_ALIASES and EXTRA_ALIASES[k] in self.known:
            return EXTRA_ALIASES[k]
        if k in SCORE_TO_BOTO and SCORE_TO_BOTO[k] in self.known:
            return SCORE_TO_BOTO[k]
        return self.by_key.get(k)


# --------------------------------------------------------------------------- results


@dataclass
class Location:
    file: str
    line: int
    source: str  # python | node | java | go | terraform | cloudformation | cdk


@dataclass
class Usage:
    """What one file uses."""

    services: dict[str, list[Location]] = field(default_factory=dict)  # boto3 name -> where
    calls: list[tuple[str, Location]] = field(default_factory=list)  # (candidate, where)
    resources: list[tuple[str, str, Location]] = field(default_factory=list)  # (svc, type, where)


@dataclass
class ScanResult:
    root: Path
    files: int = 0
    by_file: dict[str, Usage] = field(default_factory=dict)
    sources: set[str] = field(default_factory=set)

    def code_services(self, source: str | None = None) -> set[str]:
        return {
            s
            for u in self.by_file.values()
            for s, locs in u.services.items()
            if any(loc.source not in IAC and (source is None or loc.source == source) for loc in locs)
        }

    def iac(self) -> dict[str, list[tuple[str, Location]]]:
        """service -> [(resource type, where)] from Terraform, CloudFormation and CDK."""
        out: dict[str, list[tuple[str, Location]]] = {}
        for u in self.by_file.values():
            for svc, rtype, loc in u.resources:
                out.setdefault(svc, []).append((rtype, loc))
        return out


IAC = ("terraform", "cloudformation", "cdk")


def _line(text: str, pos: int) -> int:
    return text.count("\n", 0, pos) + 1


# --------------------------------------------------------------------------- SDK code

PY_CLIENT = re.compile(r"""\.(?:client|resource)\(\s*(?:service_name\s*=\s*)?['"]([a-z0-9-]+)['"]""")
PY_CALL = re.compile(r"\.([a-z][a-z0-9]*(?:_[a-z0-9]+)*)\s*\(")
PY_PAGINATOR = re.compile(r"""get_(?:paginator|waiter)\(\s*['"]([a-z0-9_]+)['"]""")

JS_V3_PKG = re.compile(r"""@aws-sdk/client-([a-z0-9-]+)""")
JS_LIB_DDB = re.compile(r"""@aws-sdk/lib-dynamodb""")
JS_COMMAND = re.compile(r"\bnew\s+([A-Z][A-Za-z0-9]+)Command\s*\(")  # sent, not just imported
JS_V2 = re.compile(r"""\b(?:AWS\.|new\s+)([A-Z][A-Za-z0-9]+)\s*(?:\.DocumentClient)?\s*\(""")
JS_V2_IMPORT = re.compile(r"""['"]aws-sdk(?:/clients/([a-z0-9]+))?['"]""")
CAMEL_CALL = re.compile(r"\.([a-z][A-Za-z0-9]*)\s*\(")
DOC_CLIENT_OPS = {
    # DynamoDB DocumentClient (v2 methods and lib-dynamodb commands) -> real operations
    "put": "PutItem",
    "get": "GetItem",
    "update": "UpdateItem",
    "delete": "DeleteItem",
    "query": "Query",
    "scan": "Scan",
    "batchget": "BatchGetItem",
    "batchwrite": "BatchWriteItem",
    "transactget": "TransactGetItems",
    "transactwrite": "TransactWriteItems",
}

JAVA_PKG = re.compile(r"(?:software\.amazon\.awssdk\.services|com\.amazonaws\.services)\.([a-z0-9]+)")
JAVA_REQUEST = re.compile(r"\b([A-Z][A-Za-z0-9]+)Request\b")

GO_PKG = re.compile(r"""github\.com/aws/aws-sdk-go(?:-v2)?/service/([a-z0-9]+)""")
GO_CALL = re.compile(r"\.([A-Z][A-Za-z0-9]+)\s*\(")
GO_INPUT = re.compile(r"\b([A-Z][A-Za-z0-9]+)Input\b")


def _add_service(usage: Usage, names: Names, raw: str, loc: Location) -> str | None:
    svc = names.resolve(raw)
    if svc:
        usage.services.setdefault(svc, []).append(loc)
    return svc


def scan_python(text: str, rel: str, names: Names, usage: Usage) -> None:
    for m in PY_CLIENT.finditer(text):
        _add_service(usage, names, m.group(1), Location(rel, _line(text, m.start()), "python"))
    # Calls are kept even without a client in this file: clients are often created in
    # another module. check.py then matches them against the project's Python services.
    for rx in (PY_CALL, PY_PAGINATOR):
        for m in rx.finditer(text):
            usage.calls.append((m.group(1), Location(rel, _line(text, m.start()), "python")))


def scan_node(text: str, rel: str, names: Names, usage: Usage) -> None:
    for m in JS_V3_PKG.finditer(text):
        _add_service(usage, names, m.group(1), Location(rel, _line(text, m.start()), "node"))
    lib_ddb = JS_LIB_DDB.search(text)
    if lib_ddb:
        _add_service(usage, names, "dynamodb", Location(rel, _line(text, lib_ddb.start()), "node"))
    v2 = JS_V2_IMPORT.search(text)
    if v2:
        if v2.group(1):
            _add_service(usage, names, v2.group(1), Location(rel, _line(text, v2.start()), "node"))
        for m in JS_V2.finditer(text):
            _add_service(usage, names, m.group(1), Location(rel, _line(text, m.start()), "node"))
    doc_client = bool(lib_ddb) or "DocumentClient" in text
    for m in JS_COMMAND.finditer(text):
        name = m.group(1)
        if doc_client and name.lower() in DOC_CLIENT_OPS:
            name = DOC_CLIENT_OPS[name.lower()]
        usage.calls.append((name, Location(rel, _line(text, m.start()), "node")))
    if v2:
        for m in CAMEL_CALL.finditer(text):
            name = m.group(1)
            if doc_client and name.lower() in DOC_CLIENT_OPS:
                name = DOC_CLIENT_OPS[name.lower()]
            usage.calls.append((name, Location(rel, _line(text, m.start()), "node")))


def scan_java(text: str, rel: str, names: Names, usage: Usage) -> None:
    for m in JAVA_PKG.finditer(text):
        _add_service(usage, names, m.group(1), Location(rel, _line(text, m.start()), "java"))
    if not usage.services:
        return
    for rx in (JAVA_REQUEST, CAMEL_CALL):
        for m in rx.finditer(text):
            usage.calls.append((m.group(1), Location(rel, _line(text, m.start()), "java")))


def scan_go(text: str, rel: str, names: Names, usage: Usage) -> None:
    for m in GO_PKG.finditer(text):
        _add_service(usage, names, m.group(1), Location(rel, _line(text, m.start()), "go"))
    if not usage.services:
        return
    for rx in (GO_CALL, GO_INPUT):
        for m in rx.finditer(text):
            usage.calls.append((m.group(1), Location(rel, _line(text, m.start()), "go")))


# --------------------------------------------------------------------------- IaC

TF_RESOURCE = re.compile(r"""^\s*(?:resource|data)\s+"aws_([a-z0-9_]+)"\s""", re.M)
TF_PREFIXES = [
    # longest prefix first wins; values are boto3 names
    ("cloudwatch_event_", "events"),
    ("cloudwatch_log_", "logs"),
    ("cloudwatch_", "cloudwatch"),
    ("sfn_", "stepfunctions"),
    ("api_gateway_", "apigateway"),
    ("apigatewayv2_", "apigatewayv2"),
    ("db_", "rds"),
    ("rds_", "rds"),
    ("lb", "elbv2"),
    ("alb", "elbv2"),
    ("elb", "elb"),
    ("instance", "ec2"),
    ("vpc", "ec2"),
    ("subnet", "ec2"),
    ("security_group", "ec2"),
    ("internet_gateway", "ec2"),
    ("nat_gateway", "ec2"),
    ("route_table", "ec2"),
    ("main_route_table", "ec2"),
    ("route", "ec2"),
    ("eip", "ec2"),
    ("ami", "ec2"),
    ("key_pair", "ec2"),
    ("launch_template", "ec2"),
    ("network_", "ec2"),
    ("ebs_", "ec2"),
    ("default_", "ec2"),
    ("availability_zone", "ec2"),
    ("placement_group", "ec2"),
    ("appautoscaling_", "application-autoscaling"),
    ("autoscaling_", "autoscaling"),
    ("cognito_identity_pool", "cognito-identity"),
    ("cognito_", "cognito-idp"),
    ("kinesis_firehose_", "firehose"),
    ("msk_", "kafka"),
    ("elasticsearch_", "es"),
    ("opensearch_", "opensearch"),
    ("caller_identity", "sts"),
    ("region", None),
    ("partition", None),
    ("availability_zones", "ec2"),
    ("iam_", "iam"),
    ("secretsmanager_", "secretsmanager"),
    ("ses_", "ses"),
    ("sesv2_", "sesv2"),
    ("s3control_", "s3control"),
    ("s3_", "s3"),
]


def _tf_service(name: str, names: Names) -> str | None:
    for prefix, svc in sorted(TF_PREFIXES, key=lambda p: -len(p[0])):
        if name.startswith(prefix):
            return svc if svc is None or svc in names.known else names.resolve(svc)
    tokens = name.split("_")
    for n in range(len(tokens), 0, -1):
        svc = names.resolve("".join(tokens[:n]))
        if svc:
            return svc
    return None


CFN_TYPE = re.compile(r"""(?:Type['"]?\s*:\s*['"]?)(AWS::([A-Za-z0-9]+)::([A-Za-z0-9]+))""")
CFN_NAMESPACES = {
    "serverless": {
        "function": "lambda",
        "layerversion": "lambda",
        "api": "apigateway",
        "httpapi": "apigatewayv2",
        "simpletable": "dynamodb",
        "statemachine": "stepfunctions",
        "graphqlapi": "appsync",
        "application": "serverlessrepo",
    },
    "cognito": {"identitypool": "cognito-identity", "identitypoolroleattachment": "cognito-identity"},
}
CFN_ALIASES = {
    "elasticloadbalancingv2": "elbv2",
    "elasticloadbalancing": "elb",
    "elasticsearch": "es",
    "stepfunctions": "stepfunctions",
    "cognito": "cognito-idp",
    "applicationautoscaling": "application-autoscaling",
    "msk": "kafka",
}


def _cfn_service(namespace: str, rtype: str, names: Names) -> str | None:
    ns = namespace.lower()
    special = CFN_NAMESPACES.get(ns, {})
    if rtype.lower() in special:
        return special[rtype.lower()]
    if ns == "serverless":
        return None
    return names.resolve(CFN_ALIASES.get(ns, ns))


CDK_MODULE = re.compile(r"""(?:aws-cdk-lib/aws-|@aws-cdk/aws-|aws_cdk\.aws_|\baws_)([a-z0-9_-]+)""")
CDK_SUFFIXES = (
    "_tasks",
    "_targets",
    "_actions",
    "_patterns",
    "_nodejs",
    "_python",
    "_go",
    "_subscriptions",
    "_notifications",
    "_deployment",
    "_event_sources",
    "_origins",
    "_alpha",
    "_integrations",
    "_authorizers",
    "_destinations",
)


def _cdk_service(module: str, names: Names) -> str | None:
    m = module.replace("-", "_")
    for suffix in CDK_SUFFIXES:
        if m.endswith(suffix):
            m = m[: -len(suffix)]
    return names.resolve(CFN_ALIASES.get(m.replace("_", ""), m))


def scan_terraform(text: str, rel: str, names: Names, usage: Usage) -> None:
    for m in TF_RESOURCE.finditer(text):
        svc = _tf_service(m.group(1), names)
        if svc:
            usage.resources.append((svc, f"aws_{m.group(1)}", Location(rel, _line(text, m.start()), "terraform")))


def scan_template(text: str, rel: str, names: Names, usage: Usage) -> None:
    if "AWS::" not in text or "Resources" not in text:
        return
    for m in CFN_TYPE.finditer(text):
        svc = _cfn_service(m.group(2), m.group(3), names)
        if svc:
            usage.resources.append((svc, m.group(1), Location(rel, _line(text, m.start()), "cloudformation")))


def scan_cdk(text: str, rel: str, names: Names, usage: Usage) -> bool:
    if "aws-cdk-lib" not in text and "aws_cdk" not in text and "@aws-cdk/" not in text:
        return False
    for m in CDK_MODULE.finditer(text):
        svc = _cdk_service(m.group(1), names)
        if svc:
            usage.resources.append((svc, f"cdk:{m.group(1)}", Location(rel, _line(text, m.start()), "cdk")))
    return True


# --------------------------------------------------------------------------- walking


def iter_files(paths: list[Path]):
    for base in paths:
        if base.is_file():
            yield base
            continue
        for folder, dirs, files in os.walk(base):
            dirs[:] = sorted(d for d in dirs if d not in SKIP_DIRS and not d.endswith(".egg-info"))
            for name in sorted(files):
                yield Path(folder, name)


def scan(paths: list[Path], known_services: set[str]) -> ScanResult:
    names = Names(known_services)
    root = paths[0] if len(paths) == 1 and paths[0].is_dir() else Path.cwd()
    result = ScanResult(root=root.resolve())
    for path in iter_files(paths):
        ext = path.suffix.lower()
        is_tf = ext == ".tf"
        if ext not in CODE_EXT and ext not in TEMPLATE_EXT and not is_tf:
            continue
        try:
            if path.stat().st_size > MAX_BYTES:
                continue
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        try:
            rel = path.resolve().relative_to(result.root).as_posix()
        except ValueError:
            rel = path.as_posix()
        result.files += 1
        usage = Usage()
        if is_tf:
            scan_terraform(text, rel, names, usage)
        elif ext in TEMPLATE_EXT:
            scan_template(text, rel, names, usage)
        else:
            source = CODE_EXT[ext]
            is_cdk = scan_cdk(text, rel, names, usage) if source in ("python", "node", "java", "go") else False
            if not is_cdk:
                {"python": scan_python, "node": scan_node, "java": scan_java, "go": scan_go}[source](
                    text, rel, names, usage
                )
        if usage.services or usage.resources:
            result.by_file[rel] = usage
            result.sources |= {loc.source for locs in usage.services.values() for loc in locs}
            result.sources |= {loc.source for _, _, loc in usage.resources}
        elif usage.calls:
            result.by_file[rel] = usage  # calls on a client created elsewhere
    return result
