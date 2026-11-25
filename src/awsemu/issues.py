"""The emulator's own list of known gaps: ``issues/`` in https://github.com/aws/aws-emulator.

AWS tracks every difference it knows as a Markdown file: open ones in
``issues/things-that-do-not-work/``, fixed ones moved to ``issues/things-that-now-work/``.
Each starts with headers::

    Issue-Severity: HIGH
    Issue-Corpus-Kind: behavioral
    Issue-Trace-Ids: dynamodb-transact-... other-test-id     <- fidelity test ids (unitId)
    Issue-Commit: ffc87a9...

    # <title>
    ## Operation
    TransactWriteItems
    ## Description
    ...AWS: ... Emulator: ... Fix: ...

File names are ``<UTC timestamp>-<services>-<title words>.md``, so the services an issue
is about can be read from the name, and only the files for the services you care about
are downloaded. Only the start of each file is fetched (the headers and the title), and
it's cached by the file's git blob id, so nothing is downloaded twice.
"""

from __future__ import annotations

import json
import re
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path

from . import fidelity as fid
from .paths import cli_root

REPO = "aws/aws-emulator"
OPEN = "things-that-do-not-work"
FIXED = "things-that-now-work"
STATES = {OPEN: "open", FIXED: "fixed"}
LIST_MAX_AGE = 6 * 3600
HEAD_BYTES = 8192
SEVERITY_ORDER = {"CRITICAL": 0, "HIGH": 1, "MEDIUM": 2, "LOW": 3}
NAME_RE = re.compile(r"^(\d{8}T\d{6}Z)-(.+)\.md$")


class IssuesError(fid.FidelityError):
    pass


class IssueNotFound(IssuesError):
    pass


@dataclass
class IssueFile:
    folder: str  # OPEN or FIXED
    name: str
    sha: str
    services: list[str] = field(default_factory=list)

    @property
    def state(self) -> str:
        return STATES[self.folder]

    @property
    def created(self) -> str:
        m = NAME_RE.match(self.name)
        if not m:
            return ""
        t = m.group(1)
        return f"{t[0:4]}-{t[4:6]}-{t[6:8]}"

    @property
    def url(self) -> str:
        return f"https://github.com/{REPO}/blob/main/issues/{self.folder}/{self.name}"

    @property
    def raw_url(self) -> str:
        return f"https://raw.githubusercontent.com/{REPO}/main/issues/{self.folder}/{self.name}"


@dataclass
class Issue:
    file: IssueFile
    title: str
    severity: str
    kind: str
    operations: list[str]
    tests: set[str]
    commit: str = ""

    @property
    def rank(self) -> tuple:
        return (SEVERITY_ORDER.get(self.severity, 9), self.file.name)

    def as_dict(self) -> dict:
        return {"title": self.title, "severity": self.severity or None, "state": self.file.state,
                "services": self.file.services, "operations": self.operations, "tests": sorted(self.tests),
                "kind": self.kind or None, "created": self.file.created or None, "url": self.file.url,
                "name": self.file.name}


# --------------------------------------------------------------------------- names


def services_in_name(name: str, known: set[str]) -> list[str]:
    """Leading service names of an issue file name (longest match, hyphenated names too)."""
    m = NAME_RE.match(name)
    if not m:
        return []
    tokens = m.group(2).split("-")
    found, i = [], 0
    while i < len(tokens):
        for n in range(min(4, len(tokens) - i), 0, -1):
            candidate = "-".join(tokens[i:i + n])
            if candidate in known:
                found.append(candidate)
                i += n
                break
        else:
            break
    return found


def known_services() -> set[str]:
    """boto3 service names (for reading issue file names)."""
    try:
        import botocore.session

        return set(botocore.session.get_session().get_available_services())
    except ImportError:  # pragma: no cover - boto3 is a dependency
        return set()


# --------------------------------------------------------------------------- listing


def _cache() -> Path:
    return cli_root() / "issues"


def listing(folder: str = OPEN, refresh: bool = False) -> list[IssueFile]:
    """Every issue file in one folder (two GitHub API calls, cached for 6 hours)."""
    cached = _cache() / f"list-{folder}.json"
    if not refresh:
        try:
            if time.time() - cached.stat().st_mtime < LIST_MAX_AGE:
                return [IssueFile(**e) for e in json.loads(cached.read_text(encoding="utf-8"))]
        except (OSError, ValueError, TypeError):
            pass
    try:
        top = json.loads(fid._get(f"https://api.github.com/repos/{REPO}/contents/issues"))
        sha = next(e["sha"] for e in top if e["name"] == folder)
        tree = json.loads(fid._get(f"https://api.github.com/repos/{REPO}/git/trees/{sha}"))
    except (fid.FidelityError, StopIteration, ValueError, KeyError, TypeError) as exc:
        if cached.exists():  # offline: an old list beats nothing
            return [IssueFile(**e) for e in json.loads(cached.read_text(encoding="utf-8"))]
        raise IssuesError(f"couldn't list the emulator's issues: {exc}") from exc
    known = known_services()
    files = [IssueFile(folder, e["path"], e["sha"], services_in_name(e["path"], known))
             for e in tree.get("tree", []) if e.get("type") == "blob" and e["path"].endswith(".md")]
    cached.parent.mkdir(parents=True, exist_ok=True)
    cached.write_text(json.dumps([f.__dict__ for f in files]), encoding="utf-8")
    return files


# --------------------------------------------------------------------------- content


def parse(text: str, file: IssueFile) -> Issue:
    head, _, rest = text.partition("\n# ")
    headers: dict[str, list[str]] = {}
    for line in head.splitlines():
        m = re.match(r"^(Issue-[A-Za-z-]+):\s*(.*)$", line)
        if m:
            headers.setdefault(m.group(1), []).append(m.group(2).strip())
    if text.startswith("# "):
        rest = text[2:]
    title = rest.split("\n", 1)[0].strip() if rest else file.name
    ops = []
    m = re.search(r"^## Operation\s*\n+(.+)$", text, re.M)
    if m:
        ops = [o.strip() for o in m.group(1).split(",") if o.strip()]
    tests = set()
    for key in ("Issue-Trace-Ids", "Issue-Trace"):
        for value in headers.get(key, []):
            tests.update(value.split())

    def one(key: str) -> str:
        return (headers.get(key) or [""])[0]

    return Issue(file=file, title=title, severity=one("Issue-Severity").upper(), kind=one("Issue-Corpus-Kind"),
                 operations=ops, tests=tests, commit=one("Issue-Commit"))


def _blob_path(file: IssueFile, full: bool) -> Path:
    return _cache() / "blobs" / f"{file.sha}{'' if full else '.head'}.md"


def fetch(file: IssueFile, full: bool = False) -> str:
    """The issue's text (only its start unless ``full``), cached by blob id."""
    for candidate in ([_blob_path(file, True)] if full else [_blob_path(file, True), _blob_path(file, False)]):
        try:
            return candidate.read_text(encoding="utf-8")
        except OSError:
            pass
    data = fid._get(file.raw_url, accept="text/plain", first_bytes=None if full else HEAD_BYTES)
    text = data.decode("utf-8", "replace")
    complete = full or len(data) != HEAD_BYTES  # shorter: the whole file; longer: Range was ignored
    if not complete and "\n# " not in text:  # the headers alone are longer than what we got
        text = fid._get(file.raw_url, accept="text/plain").decode("utf-8", "replace")
        complete = True
    path = _blob_path(file, complete)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return text


def load(files: list[IssueFile], workers: int = 16) -> list[Issue]:
    """Parsed issues for these files; files that can't be fetched are skipped."""

    def one(file: IssueFile) -> Issue | None:
        try:
            return parse(fetch(file), file)
        except fid.FidelityError:
            return None

    with ThreadPoolExecutor(max_workers=workers) as pool:
        return [i for i in pool.map(one, files) if i is not None]


def for_services(services: set[str], folder: str = OPEN, refresh: bool = False) -> list[Issue]:
    """Issues whose file name names any of these boto3 services."""
    files = [f for f in listing(folder, refresh) if services & set(f.services)]
    return sorted(load(files), key=lambda i: i.rank)


def by_test(issues: list[Issue]) -> dict[str, list[Issue]]:
    out: dict[str, list[Issue]] = {}
    for issue in issues:
        for test in issue.tests:
            out.setdefault(test, []).append(issue)
    for found in out.values():
        found.sort(key=lambda i: i.rank)
    return out


def remember(issues: list[Issue]) -> None:
    """Keep the last listing, so ``--show N`` can open row N."""
    path = _cache() / "last-listing.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps([i.file.__dict__ for i in issues]), encoding="utf-8")


def find(name: str, refresh: bool = False) -> IssueFile:
    """An issue by row number of the last listing, file name, prefix of it, or URL."""
    if name.isdigit():
        try:
            rows = json.loads((_cache() / "last-listing.json").read_text(encoding="utf-8"))
            return IssueFile(**rows[int(name) - 1])
        except (OSError, ValueError, IndexError, TypeError) as exc:
            raise IssueNotFound(f"no row {name} in the last 'awsemu issues' listing") from exc
    name = name.rstrip("/").rsplit("/", 1)[-1]
    for folder in (OPEN, FIXED):
        matches = [f for f in listing(folder, refresh) if f.name == name or f.name.startswith(name)]
        if len(matches) == 1:
            return matches[0]
        if len(matches) > 1:
            raise IssueNotFound(f"'{name}' matches {len(matches)} issues; give more of the name")
    raise IssueNotFound(f"no issue named '{name}'")
