"""Fidelity scores published with each AWS Emulator release.

Every release on https://github.com/aws/aws-emulator/releases has a
``scores.json.gz`` asset::

    {"commit": "...", "schemaVersion": 1, "scoredAt": "...",
     "units": [{"unitId": "...", "kind": "wire", "outcome": "pass" | "fail" | ...,
                "services": ["com.amazonaws.s3#AmazonS3"],
                "detail": {"operation": "...", "mismatch": "status",
                           "expected": {...}, "actual": {...}, ...}}]}

A service's score is passed / total over the tests that call only that service
(the same "k of n" AWS publishes). Tests that span several services are counted
separately.
"""

from __future__ import annotations

import gzip
import json
import os
import re
import shutil
import subprocess
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path

from ._service_names import BOTO_TO_SCORE
from .paths import cli_root

REPO = "aws/aws-emulator"
API = f"https://api.github.com/repos/{REPO}/releases"
ASSET = "scores.json.gz"


class FidelityError(Exception):
    pass


# --------------------------------------------------------------------------- versions


def installed_version(binary: str | None = None) -> str | None:
    """``1.0.385`` from ``aws-emulator -v`` ("Version: 1.0.385"), or None."""
    from .runtime import binary_command, default_binary

    cmd = binary_command(binary or default_binary())
    if cmd is None:
        return None
    try:
        out = subprocess.run([*cmd, "-v"], capture_output=True, text=True, timeout=10).stdout
    except (OSError, subprocess.TimeoutExpired):
        return None
    return parse_version_output(out)


def parse_version_output(text: str) -> str | None:
    m = re.search(r"Version:\s*v?([0-9][0-9A-Za-z.\-+]*)", text)
    return m.group(1) if m else None


def tag_for(release: str) -> str:
    """``latest`` stays; ``1.0.385`` and ``v1.0.385`` become ``v1.0.385``."""
    if release == "latest":
        return release
    return release if release.startswith("v") else f"v{release}"


# --------------------------------------------------------------------------- download


def _get(
    url: str,
    accept: str = "application/vnd.github+json",
    gzip_ok: bool = False,
    first_bytes: int | None = None,
    timeout: float = 120,
) -> bytes:
    """GET ``url``. ``first_bytes`` asks for only the start of the file (a Range request);
    servers that ignore it send the whole file, which is fine too."""
    headers = {"Accept": accept, "User-Agent": "awsemu"}
    if gzip_ok:
        headers["Accept-Encoding"] = "gzip"
    if first_bytes:
        headers["Range"] = f"bytes=0-{first_bytes - 1}"
    token = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
    if token and "api.github.com" in url:
        headers["Authorization"] = f"Bearer {token}"
    req = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = resp.read()
            if resp.headers.get("Content-Encoding") == "gzip":
                data = gzip.decompress(data)
            return data
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            raise FidelityError(f"not found: {url}") from exc
        if exc.code == 403:
            raise FidelityError("GitHub refused the request (rate limit?). Set GITHUB_TOKEN and retry.") from exc
        raise FidelityError(f"GitHub answered HTTP {exc.code} for {url}") from exc
    except (urllib.error.URLError, OSError) as exc:
        raise FidelityError(f"couldn't reach GitHub: {getattr(exc, 'reason', exc)}") from exc


def cache_dir() -> Path:
    return cli_root() / "fidelity"


def fetch(release: str = "latest", refresh: bool = False) -> tuple[str, dict]:
    """Return ``(tag, scores)`` for a release, downloading once and caching by tag."""
    tag = tag_for(release)
    if tag != "latest" and not refresh:
        cached = cache_dir() / f"{tag}.json.gz"
        if cached.exists():
            return tag, _load_gz(cached.read_bytes())
    meta_url = f"{API}/latest" if tag == "latest" else f"{API}/tags/{tag}"
    try:
        meta = json.loads(_get(meta_url))
    except FidelityError as exc:
        if "not found" in str(exc):
            raise FidelityError(f"no release '{tag}' in {REPO}") from exc
        raise
    tag = meta["tag_name"]
    _save_release_info(tag, meta)
    cached = cache_dir() / f"{tag}.json.gz"
    if cached.exists() and not refresh:
        return tag, _load_gz(cached.read_bytes())
    asset = next((a for a in meta.get("assets", []) if a["name"] == ASSET), None)
    if asset is None:
        raise FidelityError(f"release {tag} has no {ASSET}")
    data = _get(asset["browser_download_url"], accept="application/octet-stream")
    scores = _load_gz(data)
    cache_dir().mkdir(parents=True, exist_ok=True)
    tmp = cached.with_suffix(".tmp")
    tmp.write_bytes(data)
    shutil.move(str(tmp), str(cached))
    return tag, scores


SUITE_PATTERNS = [
    re.compile(r"aws-emulator-evaluation-suite/(?:tree|releases/tag|blob)/(v?\d+\.\d+\.\d+)"),
    re.compile(r"(?i)(?:fidelity tests?|evaluation[- ]suite)\b[^\n]{0,80}?\b(v?\d+\.\d+\.\d+)"),
]


def parse_suite_version(body: str) -> str | None:
    """The fidelity tests version a release says it was scored with (``v1.0.0``), if any."""
    for rx in SUITE_PATTERNS:
        m = rx.search(body or "")
        if m:
            v = m.group(1)
            return v if v.startswith("v") else f"v{v}"
    return None


def _save_release_info(tag: str, meta: dict) -> None:
    info = {"tag": tag, "published_at": meta.get("published_at"), "suite": parse_suite_version(meta.get("body") or "")}
    cache_dir().mkdir(parents=True, exist_ok=True)
    (cache_dir() / f"{tag}.release.json").write_text(json.dumps(info), encoding="utf-8")


def suite_version(tag: str) -> str | None:
    """Fidelity tests version for a release fetched earlier (None if unknown)."""
    path = cache_dir() / f"{tag}.release.json"
    try:
        return json.loads(path.read_text(encoding="utf-8")).get("suite")
    except (OSError, ValueError):
        return None


def list_releases(limit: int = 30) -> list[str]:
    """Most recent release tags, newest first."""
    data = json.loads(_get(f"{API}?per_page={min(limit, 100)}"))
    return [r["tag_name"] for r in data if not r.get("draft")][:limit]


def _load_gz(data: bytes) -> dict:
    try:
        scores = json.loads(gzip.decompress(data))
    except (OSError, ValueError) as exc:
        raise FidelityError(f"{ASSET} is not valid gzip JSON: {exc}") from exc
    if not isinstance(scores, dict) or "units" not in scores:
        raise FidelityError(f"{ASSET} has an unexpected format (no 'units')")
    if scores.get("schemaVersion") not in (None, 1):
        raise FidelityError(
            f"{ASSET} schemaVersion {scores.get('schemaVersion')} isn't supported by this awsemu; update it"
        )
    return scores


# --------------------------------------------------------------------------- scoring


def service_name(shape_id: str) -> str:
    """``com.amazonaws.dynamodb#DynamoDB_20120810`` -> ``dynamodb``."""
    namespace = shape_id.split("#", 1)[0]
    return namespace.rsplit(".", 1)[-1] if namespace.startswith("com.amazonaws.") else namespace


@dataclass
class ServiceScore:
    service: str
    passed: int = 0
    total: int = 0
    multi_passed: int = 0
    multi_total: int = 0
    failures: list[dict] = field(default_factory=list)

    @property
    def percent(self) -> float | None:
        return 100.0 * self.passed / self.total if self.total else None


def summarize(scores: dict) -> dict[str, ServiceScore]:
    out: dict[str, ServiceScore] = {}
    for unit in scores.get("units", []):
        outcome = unit.get("outcome")
        if outcome not in ("pass", "fail"):
            continue  # skipped / errored units don't count, as in AWS's k of n
        services = sorted({service_name(s) for s in unit.get("services", [])})
        single = len(services) == 1
        for name in services:
            s = out.setdefault(name, ServiceScore(name))
            if single:
                s.total += 1
                s.passed += outcome == "pass"
                if outcome == "fail":
                    s.failures.append(unit)
            else:
                s.multi_total += 1
                s.multi_passed += outcome == "pass"
    return out


ALIASES = {
    # names people type that differ from the API namespace in the score file
    **BOTO_TO_SCORE,
    "states": "sfn",
    "secrets": "secretsmanager",
    "ddb": "dynamodb",
    "cognito": "cognitoidentityprovider",
}


def match_services(wanted: list[str], available: list[str]) -> tuple[list[str], list[str]]:
    """Resolve user-typed names to score-file names. Returns ``(found, unknown)``."""
    found, unknown = [], []
    for w in wanted:
        key = ALIASES.get(w.lower(), w.lower()).replace("-", "")
        exact = [a for a in available if a.replace("-", "") == key]
        if exact:
            found += exact
            continue
        partial = [a for a in available if key in a.replace("-", "")]
        if partial:
            found += partial
        else:
            unknown.append(w)
    return list(dict.fromkeys(found)), unknown


def describe_failure(unit: dict) -> dict[str, str]:
    d = unit.get("detail") or {}
    expected, actual = d.get("expected") or {}, d.get("actual") or {}

    def fmt(x: dict) -> str:
        parts = [str(x[k]) for k in ("status", "errorCode") if x.get(k) is not None]
        return " ".join(parts) or (json.dumps(x)[:60] if x else "")

    step = f"{d.get('failedStep')}/{d.get('totalSteps')}" if d.get("failedStep") else ""
    return {
        "test": unit.get("unitId", ""),
        "operation": d.get("operation", ""),
        "mismatch": d.get("mismatch", ""),
        "expected": fmt(expected),
        "actual": fmt(actual),
        "step": step,
    }


# --------------------------------------------------------------------------- compare


@dataclass
class ServiceChange:
    service: str
    before: tuple[int, int] = (0, 0)  # single-service (passed, total), as in the score
    after: tuple[int, int] = (0, 0)
    fixed: list[str] = field(default_factory=list)  # failed before, passes now
    regressed: list[str] = field(default_factory=list)  # passed before, fails now
    added_passing: list[str] = field(default_factory=list)
    added_failing: list[str] = field(default_factory=list)
    removed: list[str] = field(default_factory=list)

    @property
    def changed(self) -> bool:
        return bool(
            self.fixed
            or self.regressed
            or self.added_passing
            or self.added_failing
            or self.removed
            or self.before != self.after
        )


def _outcomes(scores: dict) -> dict[str, tuple[str, list[str]]]:
    out = {}
    for unit in scores.get("units", []):
        if unit.get("outcome") in ("pass", "fail"):
            services = sorted({service_name(s) for s in unit.get("services", [])})
            out[unit.get("unitId", "")] = (unit["outcome"], services)
    return out


def compare(before: dict, after: dict) -> dict[str, ServiceChange]:
    """Per service, what changed between two scores files (test by test, by unitId)."""
    a, b = _outcomes(before), _outcomes(after)
    sa, sb = summarize(before), summarize(after)
    changes: dict[str, ServiceChange] = {}

    def get(name: str) -> ServiceChange:
        return changes.setdefault(name, ServiceChange(name))

    for uid in sorted(set(a) | set(b)):
        old, new = a.get(uid), b.get(uid)
        either = new or old
        assert either is not None  # uid comes from one of them
        for name in either[1]:
            c = get(name)
            if old and not new:
                c.removed.append(uid)
            elif new and not old:
                (c.added_passing if new[0] == "pass" else c.added_failing).append(uid)
            elif old and new and old[0] == "fail" and new[0] == "pass":
                c.fixed.append(uid)
            elif old and new and old[0] == "pass" and new[0] == "fail":
                c.regressed.append(uid)
    for name in set(sa) | set(sb) | set(changes):
        c = get(name)
        if name in sa:
            c.before = (sa[name].passed, sa[name].total)
        if name in sb:
            c.after = (sb[name].passed, sb[name].total)
    return changes
