"""Which IAM actions your code needs that your infrastructure doesn't grant.

``needed``: the actions of the calls the proxy logged, or of the operations the static
scan finds in the code (:mod:`awsemu.iampolicy` turns operations into actions).
``granted``: the ``Allow`` actions in the policies your infrastructure defines:

* Terraform: ``aws_iam_policy_document`` statements (``actions = [...]``) and JSON
  policies, inline (``jsonencode({...})``, heredocs) with ``Action``;
* CloudFormation and SAM templates: every ``PolicyDocument``/``Statement`` with
  ``Action``; SAM policy templates (``DynamoDBCrudPolicy``) and managed policies
  (``ManagedPolicyArns``, ``arn:aws:iam::aws:policy/...``) are listed, not expanded;
* CDK: the synthesized templates in ``cdk.out`` (run ``cdk synth`` first).

It compares actions, with wildcards (``dynamodb:*``, ``s3:Get*``), not resources or
conditions, and doesn't know which role the code runs as: an action is "granted" if
any policy in the project allows it. ``Deny`` statements and permission boundaries
aren't taken into account.
"""

from __future__ import annotations

import fnmatch
import json
import re
from dataclasses import dataclass, field
from pathlib import Path

import yaml

from . import scan as sc

ACTION_RE = re.compile(r"^[a-z0-9-]+:[A-Za-z0-9*?]+$")
TF_ACTIONS_RE = re.compile(r"\bactions\s*=\s*\[(.*?)\]", re.S)
TF_JSON_ACTION_RE = re.compile(r"\"?Action\"?\s*[:=]\s*(\[.*?\]|\"[^\"]*\")", re.S)
TF_EFFECT_DENY_RE = re.compile(r"effect\s*=\s*\"Deny\"", re.I)
QUOTED_RE = re.compile(r"\"([^\"]+)\"")
MANAGED_RE = re.compile(r"arn:aws:iam::aws:policy/[A-Za-z0-9+=,.@_/-]+")


@dataclass
class Grant:
    pattern: str
    file: str
    line: int


@dataclass
class Grants:
    actions: list[Grant] = field(default_factory=list)
    unexpanded: list[tuple[str, str]] = field(default_factory=list)  # (managed policy or SAM template, file)
    files: int = 0

    def allows(self, action: str) -> list[Grant]:
        low = action.lower()
        return [g for g in self.actions if fnmatch.fnmatchcase(low, g.pattern.lower())]


def _line(text: str, pos: int) -> int:
    return text.count("\n", 0, pos) + 1


def _terraform(text: str, rel: str, grants: Grants) -> None:
    for m in TF_ACTIONS_RE.finditer(text):
        # skip a Deny statement: look back to the start of its block
        block_start = text.rfind("statement", 0, m.start())
        if block_start != -1 and TF_EFFECT_DENY_RE.search(text[block_start : m.start()]):
            continue
        for q in QUOTED_RE.finditer(m.group(1)):
            if ACTION_RE.match(q.group(1)):
                grants.actions.append(Grant(q.group(1), rel, _line(text, m.start())))
    for m in TF_JSON_ACTION_RE.finditer(text):
        before = text[max(0, m.start() - 300) : m.start()]
        if re.search(r"\"?Effect\"?\s*[:=]\s*\"Deny\"", before[before.rfind("{") :] if "{" in before else before):
            continue
        for q in QUOTED_RE.finditer(m.group(1)):
            if ACTION_RE.match(q.group(1)):
                grants.actions.append(Grant(q.group(1), rel, _line(text, m.start())))
    for m in MANAGED_RE.finditer(text):
        grants.unexpanded.append((m.group(0), rel))


class _AnyTagLoader(yaml.SafeLoader):
    """YAML with CloudFormation's short tags (!Sub, !Ref, !GetAtt…), read as plain values."""


def _any_tag(loader, suffix, node):
    if isinstance(node, yaml.ScalarNode):
        return loader.construct_scalar(node)
    if isinstance(node, yaml.SequenceNode):
        return loader.construct_sequence(node)
    return loader.construct_mapping(node)


_AnyTagLoader.add_multi_constructor("!", _any_tag)


def _template(text: str, rel: str, grants: Grants) -> None:
    if "AWS::" not in text and "Statement" not in text:
        return
    try:
        data = json.loads(text) if text.lstrip().startswith("{") else yaml.load(text, Loader=_AnyTagLoader)
    except (ValueError, yaml.YAMLError):
        return
    if not isinstance(data, dict):
        return

    def walk(node, key=None):
        if isinstance(node, dict):
            if "Action" in node and node.get("Effect", "Allow") == "Allow":
                acts = node["Action"] if isinstance(node["Action"], list) else [node["Action"]]
                for a in acts:
                    if isinstance(a, str) and ACTION_RE.match(a):
                        grants.actions.append(Grant(a, rel, _line(text, max(text.find(a), 0))))
            for k, v in node.items():
                if k == "ManagedPolicyArns" and isinstance(v, list):
                    grants.unexpanded += [(str(x), rel) for x in v if isinstance(x, str)]
                if k == "Policies" and isinstance(v, list):  # SAM: names, ARNs and policy templates
                    for item in v:
                        if isinstance(item, str):
                            grants.unexpanded.append((item, rel))
                        elif isinstance(item, dict):
                            grants.unexpanded += [(t, rel) for t in item if t.endswith("Policy")]
                walk(v, k)
        elif isinstance(node, list):
            for item in node:
                walk(item, key)

    walk(data)


def granted(paths: list[Path]) -> Grants:
    grants = Grants()
    roots = [p for p in paths if p.is_dir()]
    extra = [t for r in roots for t in sorted((r / "cdk.out").glob("*.template.json"))]  # cdk synth output
    base = paths[0] if len(paths) == 1 and paths[0].is_dir() else Path.cwd()
    for path in [*sc.iter_files(paths), *extra]:
        ext = path.suffix.lower()
        if ext != ".tf" and ext not in sc.TEMPLATE_EXT:
            continue
        try:
            if path.stat().st_size > sc.MAX_BYTES:
                continue
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        try:
            rel = path.resolve().relative_to(base.resolve()).as_posix()
        except ValueError:
            rel = path.as_posix()
        before = len(grants.actions) + len(grants.unexpanded)
        if ext == ".tf":
            _terraform(text, rel, grants)
        else:
            _template(text, rel, grants)
        if len(grants.actions) + len(grants.unexpanded) > before:
            grants.files += 1
    grants.unexpanded = sorted(set(grants.unexpanded))
    return grants


@dataclass
class Comparison:
    needed: dict[str, list[str]]  # action -> where it's used ("calls.jsonl:12", "app/x.py:3")
    grants: Grants
    missing: list[str]
    unused: list[Grant]

    def as_dict(self) -> dict:
        return {
            "needed": [
                {
                    "action": a,
                    "used_in": w,
                    "granted_by": [f"{g.pattern} ({g.file}:{g.line})" for g in self.grants.allows(a)],
                }
                for a, w in sorted(self.needed.items())
            ],
            "missing": self.missing,
            "unused_grants": [{"action": g.pattern, "file": g.file, "line": g.line} for g in self.unused],
            "not_expanded": [{"policy": p, "file": f} for p, f in self.grants.unexpanded],
            "policy_files": self.grants.files,
        }


def compare(needed: dict[str, list[str]], grants: Grants) -> Comparison:
    missing = sorted(a for a in needed if not grants.allows(a))
    used_patterns = {id(g) for a in needed for g in grants.allows(a)}
    unused = [g for g in grants.actions if id(g) not in used_patterns]
    return Comparison(needed, grants, missing, unused)


class BotoIndex:
    """Enough of :class:`awsemu.check.Index` to resolve the scan's method names into
    operations from botocore's models, offline (no fidelity data needed)."""

    def __init__(self):
        import botocore.session

        self._session = botocore.session.get_session()
        self.known_services = set(self._session.get_available_services())
        self.names = sc.Names(self.known_services)
        self._ops: dict[str, dict[str, str]] = {}

    def _ops_for(self, service: str) -> dict[str, str]:
        if service not in self._ops:
            try:
                names = self._session.get_service_model(service).operation_names
            except Exception:
                names = []
            self._ops[service] = {sc.key(n): n for n in names}
        return self._ops[service]

    def resolve_call(self, candidate: str, services: set[str]) -> list[str]:
        k = sc.key(candidate)
        return [f"{s}:{self._ops_for(s)[k]}" for s in sorted(services) if k in self._ops_for(s)]


def needed_from_calls(calls: list[dict], label: str) -> dict[str, list[str]]:
    from .iampolicy import action

    out: dict[str, list[str]] = {}
    for call in calls:
        act = action(call.get("service") or "", call.get("operation") or "")
        if act:
            where = out.setdefault(act, [])
            if len(where) < 3:
                where.append(f"{label}:{call.get('id')}")
    return out


def needed_from_code(paths: list[Path]) -> dict[str, list[str]]:
    from . import check as chk
    from .iampolicy import action

    index = BotoIndex()
    result = sc.scan(paths, index.known_services)
    out: dict[str, list[str]] = {}
    for op, locations in chk.find_operations(result, index).items():
        service, operation = op.split(":", 1)
        act = action(service, operation)
        if act:
            out.setdefault(act, []).extend(f"{loc.file}:{loc.line}" for loc in locations[:3])
    return out
