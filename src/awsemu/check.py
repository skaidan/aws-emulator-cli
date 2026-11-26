"""``awsemu check``: will this project work with the emulator?

Cross-references what a project uses (:mod:`awsemu.scan`) with the fidelity tests:

* ``scores.json.gz`` of a release says which tests pass or fail;
* ``manifest.jsonl`` of the fidelity tests repository
  (https://github.com/aws/aws-emulator-evaluation-suite) says which AWS operations
  each behavioral test calls. Wire tests carry their operations in the scores file.

A failing test is a *known difference* for an operation you call when either

* it fails **at** that operation (wire tests say which call didn't match AWS), or
* it calls **only operations your project also calls** (so it is close to what your
  code does).

Other failing tests that merely include the operation (often as setup) are counted,
not listed.
"""

from __future__ import annotations

import gzip
import json
import re
import time
from dataclasses import dataclass, field
from typing import Protocol
from pathlib import Path

from . import fidelity as fid
from . import scan as sc

SUITE_REPO = "aws/aws-emulator-evaluation-suite"
SUITE_URL = f"https://github.com/{SUITE_REPO}"
RAW = f"https://raw.githubusercontent.com/{SUITE_REPO}"
MAIN_MAX_AGE = 24 * 3600
IGNORED_OPS = {"sts:GetCallerIdentity"}  # in many tests, never the point of them


# --------------------------------------------------------------------------- manifest


def latest_suite_version() -> str | None:
    """Newest ``vX.Y.Z`` tag of the fidelity tests repository (cached for a day), or None.

    Releases don't always say which version of the fidelity tests scored them; then the
    newest published version is the best match (``main`` may have tests added since).
    """
    cached = fid.cache_dir() / "suite-tags.json"
    try:
        if time.time() - cached.stat().st_mtime < MAIN_MAX_AGE:
            return json.loads(cached.read_text(encoding="utf-8")).get("latest")
    except (OSError, ValueError):
        pass
    try:
        tags = [t["name"] for t in json.loads(fid._get(f"https://api.github.com/repos/{SUITE_REPO}/tags"))]
    except (fid.FidelityError, ValueError, KeyError, TypeError):
        return None
    versions = [t for t in tags if re.match(r"^v\d+\.\d+\.\d+$", t)]
    latest = max(versions, key=lambda t: tuple(map(int, t[1:].split("."))), default=None)
    cached.parent.mkdir(parents=True, exist_ok=True)
    cached.write_text(json.dumps({"latest": latest}), encoding="utf-8")
    return latest


def manifest_path(ref: str) -> Path:
    return fid.cache_dir() / f"manifest-{ref.replace('/', '_')}.jsonl.gz"


def load_manifest(ref: str = "main", refresh: bool = False) -> list[dict]:
    """Rows of ``manifest.jsonl`` at a git ref of the tests repository (cached)."""
    cached = manifest_path(ref)
    fresh = cached.exists() and (ref != "main" or time.time() - cached.stat().st_mtime < MAIN_MAX_AGE)
    if fresh and not refresh:
        return parse_manifest(gzip.decompress(cached.read_bytes()))
    try:
        data = fid._get(f"{RAW}/{ref}/manifest.jsonl", accept="text/plain", gzip_ok=True)
    except fid.FidelityError as exc:
        if cached.exists():  # offline: an old copy beats nothing
            return parse_manifest(gzip.decompress(cached.read_bytes()))
        if "not found" in str(exc):
            raise fid.FidelityError(f"no manifest.jsonl at '{ref}' in {SUITE_REPO}") from exc
        raise
    rows = parse_manifest(data)
    cached.parent.mkdir(parents=True, exist_ok=True)
    tmp = cached.with_suffix(".tmp")
    tmp.write_bytes(gzip.compress(data))
    tmp.replace(cached)
    return rows


def parse_manifest(data: bytes) -> list[dict]:
    rows = []
    for n, line in enumerate(data.decode("utf-8").splitlines(), 1):
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except ValueError as exc:
            raise fid.FidelityError(f"manifest.jsonl line {n} isn't JSON: {exc}") from exc
        if "check_id" not in row or "operations" not in row:
            raise fid.FidelityError(f"manifest.jsonl line {n} has no check_id/operations")
        rows.append(row)
    return rows


def read_manifest_file(path: Path) -> list[dict]:
    data = path.read_bytes()
    if path.suffix == ".gz":
        data = gzip.decompress(data)
    return parse_manifest(data)


# --------------------------------------------------------------------------- index


@dataclass
class Test:
    id: str
    outcome: str
    kind: str
    services: set[str]
    ops: set[str]
    failed_at: str | None = None
    labels: list[str] = field(default_factory=list)
    path: str | None = None
    group: str | None = None  # manifest "service": "dynamodb", "apigateway__cloudformation"...
    detail: dict = field(default_factory=dict)

    @property
    def single_service(self) -> bool:
        return len(self.services) == 1


class Index:
    def __init__(self, scores: dict, manifest: list[dict]):
        rows = {r["check_id"]: r for r in manifest}
        known = {op.split(":", 1)[0] for r in manifest for op in r["operations"]}
        known |= {s for r in manifest for s in r.get("service", "").split("__") if s}
        self.names = sc.Names(known)
        self.tests: list[Test] = []
        for unit in scores.get("units", []):
            if unit.get("outcome") not in ("pass", "fail"):
                continue
            services = set()
            for shape in unit.get("services", []):
                raw = fid.service_name(shape)
                services.add(self.names.resolve(raw) or raw)
            detail = unit.get("detail") or {}
            test = Test(
                id=unit.get("unitId", ""),
                outcome=unit["outcome"],
                kind=unit.get("kind", ""),
                services=services,
                ops=set(),
                detail=detail,
            )
            row = rows.get(test.id)
            if row:
                test.ops = set(row["operations"])
                test.labels = row.get("labels", [])
                test.path = row.get("path")
                test.group = row.get("service")
            if len(services) == 1:
                (svc,) = services
                steps = {s.get("operation") for s in detail.get("steps", []) if s.get("operation")}
                if detail.get("operation"):
                    steps.add(detail["operation"])
                test.ops |= {f"{svc}:{op}" for op in steps}
                if test.outcome == "fail" and detail.get("operation"):
                    test.failed_at = f"{svc}:{detail['operation']}"
            self.tests.append(test)
        self.by_op: dict[str, list[Test]] = {}
        self.ops_by_service: dict[str, dict[str, str]] = {}
        for test in self.tests:
            for op in test.ops:
                self.by_op.setdefault(op, []).append(test)
                svc, name = op.split(":", 1)
                self.ops_by_service.setdefault(svc, {})[sc.key(name)] = op
        self.known_services = known | set(self.ops_by_service)
        self.names = sc.Names(self.known_services)

    def resolve_call(self, candidate: str, services: set[str]) -> list[str]:
        k = sc.key(candidate)
        return [self.ops_by_service[s][k] for s in sorted(services) if k in self.ops_by_service.get(s, {})]


# --------------------------------------------------------------------------- report


@dataclass
class Difference:
    test: Test
    at_operation: bool
    matches_usage: bool
    issues: list = field(default_factory=list)  # awsemu.issues.Issue, most severe first
    fixed_in: str | None = None  # a newer release where this test passes

    def as_dict(self, suite_ref: str) -> dict:
        d = self.test.detail
        desc = fid.describe_failure({"unitId": self.test.id, "detail": d})
        return {
            "test": self.test.id,
            "kind": self.test.kind,
            "operation": desc["operation"] or None,
            "mismatch": desc["mismatch"] or None,
            "expected": desc["expected"] or None,
            "actual": desc["actual"] or None,
            "step": desc["step"] or None,
            "at_operation": self.at_operation,
            "matches_usage": self.matches_usage,
            "url": f"{SUITE_URL}/blob/{suite_ref}/{self.test.path}" if self.test.path else None,
            "issues": [
                {"title": i.title, "severity": i.severity or None, "state": i.file.state, "url": i.file.url}
                for i in self.issues
            ],
            "fixed_in": self.fixed_in,
        }


@dataclass
class OperationReport:
    operation: str
    locations: list[sc.Location]
    tests: int = 0
    passed: int = 0
    differences: list[Difference] = field(default_factory=list)
    other_failing: int = 0

    @property
    def service(self) -> str:
        return self.operation.split(":", 1)[0]


@dataclass
class ServiceReport:
    service: str
    sources: list[str]
    tests: int
    passed: int
    resources: list[tuple[str, sc.Location]] = field(default_factory=list)
    cfn_tests: int = 0
    cfn_passed: int = 0
    cfn_failing: list[Test] = field(default_factory=list)


@dataclass
class Report:
    release: str
    suite: str
    files: int
    sources: list[str]
    operations: list[OperationReport]
    uncovered: list[str]
    services: list[ServiceReport]
    issues_checked: bool = False
    latest: str | None = None  # the newer release compared with, if any

    def _unique_differences(self) -> list[Difference]:
        seen: dict[str, Difference] = {}
        for o in self.operations:
            for d in o.differences:
                seen.setdefault(d.test.id, d)
        return list(seen.values())

    @property
    def with_differences(self) -> list[OperationReport]:
        return [o for o in self.operations if o.differences]

    def as_dict(self, limit: int | None = None) -> dict:
        def loc(location: sc.Location) -> dict:
            return {"file": location.file, "line": location.line, "source": location.source}

        return {
            "release": self.release,
            "suite": self.suite,
            "scanned_files": self.files,
            "sources": self.sources,
            "operations": [
                {
                    "operation": o.operation,
                    "service": o.service,
                    "locations": [loc(x) for x in o.locations],
                    "tests": o.tests,
                    "passed": o.passed,
                    "differences": [d.as_dict(self.suite) for d in o.differences[:limit]],
                    "other_failing": o.other_failing,
                }
                for o in self.operations
            ],
            "uncovered": self.uncovered,
            "services": [
                {
                    "service": s.service,
                    "sources": s.sources,
                    "tests": s.tests,
                    "passed": s.passed,
                    "resources": [{"type": t, **loc(x)} for t, x in s.resources],
                    "cloudformation": (
                        {"tests": s.cfn_tests, "passed": s.cfn_passed, "failing": [t.id for t in s.cfn_failing[:limit]]}
                        if s.cfn_tests
                        else None
                    ),
                }
                for s in self.services
            ],
            "summary": {
                "operations": len(self.operations),
                "services": len(self.services),
                "operations_with_differences": len(self.with_differences),
                # distinct failing tests (one can be a difference for several operations)
                "differences": len(self._unique_differences()),
                "explained_by_issues": (
                    sum(bool(d.issues) for d in self._unique_differences()) if self.issues_checked else None
                ),
                "fixed_in_latest": (sum(bool(d.fixed_in) for d in self._unique_differences()) if self.latest else None),
                "latest": self.latest,
            },
        }


class Resolver(Protocol):
    """What :func:`find_operations` needs: an :class:`Index`, or botocore's models (``iamcheck``)."""

    def resolve_call(self, candidate: str, services: set[str]) -> list[str]: ...


def find_operations(result: sc.ScanResult, index: Resolver) -> dict[str, list[sc.Location]]:
    used: dict[str, list[sc.Location]] = {}
    by_source = {src: result.code_services(src) for src in ("python", "node", "java", "go")}
    for usage in result.by_file.values():
        local = {s for s, locs in usage.services.items() if any(loc.source not in sc.IAC for loc in locs)}
        for candidate, location in usage.calls:
            services = local or by_source.get(location.source, set())
            for op in index.resolve_call(candidate, services):
                where = used.setdefault(op, [])
                if not any(w.file == location.file for w in where):
                    where.append(location)
    return used


CALLS_SOURCE = "proxy calls"


def scan_from_calls(calls: list[dict], index: Index, label: str = "calls.jsonl") -> tuple[sc.ScanResult, list[str]]:
    """The operations the proxy saw, as if a scan had found them (one "file" per service).

    Also returns the operations that have no fidelity tests (they were called, so they're
    real, but the tests don't know them)."""
    result = sc.ScanResult(root=Path(label))
    result.files = len(calls)
    unknown: set[str] = set()
    for call in calls:
        service, operation = call.get("service"), call.get("operation")
        if not service or not operation:
            continue
        svc = index.names.resolve(service) or service
        usage = result.by_file.setdefault(f"{label} ({service})", sc.Usage())
        loc = sc.Location(file=label, line=int(call.get("id") or 0), source=CALLS_SOURCE)
        usage.services.setdefault(svc, []).append(loc)
        if not any(candidate == operation for candidate, _ in usage.calls):
            usage.calls.append((operation, loc))
        if not index.resolve_call(operation, {svc}):
            unknown.add(f"{svc}:{operation}")
    if result.by_file:
        result.sources.add(CALLS_SOURCE)
    return result, sorted(unknown)


def analyze(result: sc.ScanResult, index: Index, release: str, suite: str) -> Report:
    used = find_operations(result, index)
    used_ops = set(used)
    operations, uncovered = [], []
    for op in sorted(used):
        tests = index.by_op.get(op, [])
        if not tests:
            uncovered.append(op)
            continue
        report = OperationReport(op, used[op], tests=len(tests), passed=sum(t.outcome == "pass" for t in tests))
        for t in tests:
            if t.outcome != "fail":
                continue
            at_op = t.failed_at == op
            matches = bool(t.ops) and (t.ops - IGNORED_OPS) <= used_ops
            if at_op or matches:
                report.differences.append(Difference(t, at_op, matches))
            else:
                report.other_failing += 1
        report.differences.sort(key=lambda d: (not d.at_operation, not d.matches_usage, d.test.id))
        operations.append(report)
    operations.sort(key=lambda o: (-len(o.differences), o.operation))

    services: list[ServiceReport] = []
    iac = result.iac()
    code: dict[str, set[str]] = {}
    for usage in result.by_file.values():
        for svc, locs in usage.services.items():
            code.setdefault(svc, set()).update(loc.source for loc in locs)
    for op in used:
        code.setdefault(op.split(":", 1)[0], set())
    for svc in sorted(set(code) | set(iac)):
        single = [t for t in index.tests if t.single_service and svc in t.services]
        sources = set(code.get(svc, set())) | {loc.source for _, loc in iac.get(svc, [])}
        service_report = ServiceReport(
            svc,
            sorted(sources),
            tests=len(single),
            passed=sum(t.outcome == "pass" for t in single),
            resources=iac.get(svc, []),
        )
        if any(loc.source in ("cloudformation", "cdk") for _, loc in iac.get(svc, [])):
            cfn = [
                t
                for t in index.tests
                if t.group and "cloudformation" in t.group.split("__") and svc in t.group.split("__")
            ]
            service_report.cfn_tests = len(cfn)
            service_report.cfn_passed = sum(t.outcome == "pass" for t in cfn)
            service_report.cfn_failing = sorted((t for t in cfn if t.outcome == "fail"), key=lambda t: t.id)
        services.append(service_report)
    return Report(
        release=release,
        suite=suite,
        files=result.files,
        sources=sorted(result.sources),
        operations=operations,
        uncovered=uncovered,
        services=services,
    )


def attach_issues(report: Report, refresh: bool = False) -> None:
    """Link each known difference to the emulator's open issue that explains it, if any."""
    from . import issues as iss

    differences = [d for o in report.operations for d in o.differences]
    if not differences:
        report.issues_checked = True
        return
    services = {svc for d in differences for svc in d.test.services}
    found = iss.by_test(iss.for_services(services, refresh=refresh))
    for d in differences:
        d.issues = found.get(d.test.id, [])
    report.issues_checked = True


def attach_fixes(report: Report, latest_tag: str, latest_scores: dict) -> None:
    """Mark differences whose test passes in a newer release (an upgrade fixes them)."""
    if latest_tag == report.release:
        return
    passing = {u.get("unitId") for u in latest_scores.get("units", []) if u.get("outcome") == "pass"}
    for o in report.operations:
        for d in o.differences:
            if d.test.id in passing:
                d.fixed_in = latest_tag
    report.latest = latest_tag
