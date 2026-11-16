"""Seed files: a declarative description of what the emulator should contain.

The emulator keeps everything in memory and has no reset route, so a seed is
how you get the same starting data after every start or reset::

    version: 1
    buckets:
      - name: photos
        objects:
          - {key: hello.txt, content: "hello"}
          - {key: assets/, from: ./assets}        # a local folder or file
    queues:
      - {name: jobs-dlq}
      - {name: jobs, dlq: jobs-dlq, max_receive: 3}
    tables:
      - name: users
        pk: id
        items: [{id: u1, name: Ana}]
    topics:
      - name: orders
        subscriptions: [{sqs: jobs, raw: true}]
    secrets:
      - {name: db/password, value: s3cr3t}
    parameters:
      - {name: /app/db/host, value: localhost}

This module only parses and validates (no AWS calls). Errors carry the line
and the field path, e.g. ``seed.yaml:12 queues[1].dlq: unknown queue 'x'``.
"""

from __future__ import annotations

import difflib
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

VERSION = 1
SECTIONS = ("buckets", "queues", "tables", "topics", "secrets", "parameters")
PARAM_TYPES = ("String", "SecureString", "StringList")
KEY_TYPES = {"S", "N", "B"}

FIELDS = {
    "buckets": {"name", "objects"},
    "objects": {"key", "content", "json", "from"},
    "queues": {"name", "fifo", "content_dedup", "visibility_timeout", "delay", "dlq", "max_receive"},
    "tables": {"name", "pk", "sk", "items", "items_from"},
    "topics": {"name", "fifo", "subscriptions"},
    "subscriptions": {"sqs", "lambda", "raw", "filter"},
    "secrets": {"name", "value", "description"},
    "parameters": {"name", "value", "type", "description"},
}


@dataclass
class Problem:
    line: int | None
    path: str
    message: str

    def format(self, source: str) -> str:
        where = f"{source}:{self.line}" if self.line else source
        return f"{where}  {self.path}: {self.message}" if self.path else f"{where}  {self.message}"


class SeedError(Exception):
    def __init__(self, source: str, problems: list[Problem]):
        self.source = source
        self.problems = problems
        super().__init__("\n".join(p.format(source) for p in problems))


@dataclass
class Seed:
    data: dict[str, Any]
    base_dir: Path
    source: str = "seed"
    warnings: list[str] = field(default_factory=list)

    def section(self, name: str) -> list[dict]:
        return self.data.get(name) or []

    def count(self) -> dict[str, int]:
        return {s: len(self.section(s)) for s in SECTIONS if self.section(s)}


# --------------------------------------------------------------------------- lines


def _node_lines(node, path: tuple = (), out: dict | None = None) -> dict[tuple, int]:
    """Map each path (keys / indexes) to the 1-based line where its value starts."""
    out = {} if out is None else out
    out.setdefault(path, node.start_mark.line + 1)
    if isinstance(node, yaml.MappingNode):
        for key_node, value_node in node.value:
            key = key_node.value
            out[path + (key,)] = key_node.start_mark.line + 1
            _node_lines(value_node, path + (key,), out)
    elif isinstance(node, yaml.SequenceNode):
        for i, item in enumerate(node.value):
            _node_lines(item, path + (i,), out)
    return out


def _fmt_path(path: tuple) -> str:
    out = ""
    for part in path:
        out += f"[{part}]" if isinstance(part, int) else (f".{part}" if out else str(part))
    return out


# --------------------------------------------------------------------------- loading


def load_text(text: str, source: str = "seed", base_dir: Path | None = None) -> Seed:
    try:
        node = yaml.compose(text, Loader=yaml.SafeLoader)
        data = yaml.safe_load(text)
    except yaml.YAMLError as exc:
        mark = getattr(exc, "problem_mark", None)
        line = mark.line + 1 if mark else None
        problem = getattr(exc, "problem", None) or str(exc)
        raise SeedError(source, [Problem(line, "", f"invalid YAML: {problem}")]) from exc
    lines = _node_lines(node) if node is not None else {}
    seed = Seed(data if isinstance(data, dict) else {}, base_dir or Path("."), source)
    problems = sorted(_validate(data, lines, seed), key=lambda pr: pr.line or 0)
    if problems:
        raise SeedError(source, problems)
    return seed


def load_file(path: str | Path) -> Seed:
    path = Path(path)
    if not path.is_file():
        raise SeedError(str(path), [Problem(None, "", "file not found")])
    return load_text(path.read_text(encoding="utf-8"), str(path), path.parent)


# --------------------------------------------------------------------------- validation


class _V:
    def __init__(self, lines: dict[tuple, int]):
        self.lines = lines
        self.problems: list[Problem] = []

    def add(self, path: tuple, message: str) -> None:
        line = None
        for i in range(len(path), -1, -1):  # closest known line
            if path[:i] in self.lines:
                line = self.lines[path[:i]]
                break
        self.problems.append(Problem(line, _fmt_path(path), message))

    def keys(self, obj: dict, allowed: set[str], path: tuple) -> None:
        for key in obj:
            if key not in allowed:
                hint = difflib.get_close_matches(str(key), sorted(allowed), n=1)
                extra = f" (did you mean '{hint[0]}'?)" if hint else \
                    f" (allowed: {', '.join(sorted(allowed))})"
                self.add(path + (key,), f"unknown field{extra}")

    def type(self, obj: dict, key: str, kinds, path: tuple, what: str) -> bool:
        if key in obj and not isinstance(obj[key], kinds) or \
                (key in obj and kinds is int and isinstance(obj[key], bool)):
            self.add(path + (key,), f"must be {what}")
            return False
        return True

    def name(self, obj: dict, path: tuple, seen: dict[str, tuple]) -> str | None:
        name = obj.get("name")
        if not isinstance(name, str) or not name:
            self.add(path + ("name",) if "name" in obj else path, "a non-empty 'name' is required")
            return None
        if name in seen:
            self.add(path + ("name",), f"duplicate name '{name}' (also at {_fmt_path(seen[name])})")
        seen.setdefault(name, path)
        return name


def _key_spec(value) -> tuple[str, str] | None:
    if not isinstance(value, str) or not value:
        return None
    name, _, kind = value.partition(":")
    kind = (kind or "S").upper()
    return (name, kind) if name and kind in KEY_TYPES else None


def _validate(data: Any, lines: dict[tuple, int], seed: Seed) -> list[Problem]:
    v = _V(lines)
    if data is None:
        return [Problem(None, "", "the file is empty")]
    if not isinstance(data, dict):
        return [Problem(1, "", "the top level must be a mapping (version, buckets, queues, ...)")]
    v.keys(data, {"version", *SECTIONS}, ())
    if data.get("version", VERSION) != VERSION:
        v.add(("version",), f"unsupported version {data.get('version')!r} (this awsemu reads version {VERSION})")
    for section in SECTIONS:
        if section in data and data[section] is not None and not isinstance(data[section], list):
            v.add((section,), "must be a list")
            data[section] = []

    def items(section):
        for i, obj in enumerate(data.get(section) or []):
            path = (section, i)
            if not isinstance(obj, dict):
                v.add(path, "each entry must be a mapping with a 'name'")
                continue
            v.keys(obj, FIELDS[section], path)
            yield path, obj

    # buckets
    seen: dict[str, tuple] = {}
    for path, b in items("buckets"):
        v.name(b, path, seen)
        if v.type(b, "objects", list, path, "a list"):
            for j, o in enumerate(b.get("objects") or []):
                op = path + ("objects", j)
                if not isinstance(o, dict):
                    v.add(op, "each object must be a mapping with 'key'")
                    continue
                v.keys(o, FIELDS["objects"], op)
                if not isinstance(o.get("key"), str):
                    v.add(op, "'key' is required")
                sources = [k for k in ("content", "json", "from") if k in o]
                if len(sources) != 1:
                    v.add(op, "give exactly one of 'content', 'json' or 'from'")
                v.type(o, "content", str, op, "text (use 'json' for structured data)")
                if "from" in o:
                    if not isinstance(o["from"], str):
                        v.add(op + ("from",), "must be a path")
                    elif not (seed.base_dir / o["from"]).exists():
                        v.add(op + ("from",), f"'{o['from']}' not found (relative to the seed file)")

    # queues
    queue_names: dict[str, tuple] = {}
    queues = list(items("queues"))
    for path, q in queues:
        name = v.name(q, path, queue_names)
        for key in ("visibility_timeout", "delay", "max_receive"):
            v.type(q, key, int, path, "a whole number")
        for key in ("fifo", "content_dedup"):
            v.type(q, key, bool, path, "true or false")
        if name and q.get("fifo") and not name.endswith(".fifo"):
            v.add(path + ("name",), "FIFO queue names must end with '.fifo'")
        if "max_receive" in q and "dlq" not in q:
            v.add(path + ("max_receive",), "only makes sense with 'dlq'")
    for path, q in queues:
        dlq = q.get("dlq")
        if dlq is not None and (not isinstance(dlq, str) or not dlq):
            v.add(path + ("dlq",), "must be a queue name")
        elif dlq is not None and dlq not in queue_names:
            seed.warnings.append(f"{_fmt_path(path + ('dlq',))}: '{dlq}' isn't in this seed; "
                                 "it must already exist when you apply it")
        if dlq is not None and dlq == q.get("name"):
            v.add(path + ("dlq",), "a queue can't be its own dead-letter queue")

    # tables
    seen = {}
    for path, t in items("tables"):
        v.name(t, path, seen)
        if _key_spec(t.get("pk")) is None:
            v.add(path + ("pk",) if "pk" in t else path, "'pk' is required: NAME or NAME:S|N|B")
        if "sk" in t and _key_spec(t["sk"]) is None:
            v.add(path + ("sk",), "must be NAME or NAME:S|N|B")
        keys = [k for k in (_key_spec(t.get("pk")), _key_spec(t.get("sk"))) if k]
        if v.type(t, "items", list, path, "a list of objects"):
            for j, item in enumerate(t.get("items") or []):
                ip = path + ("items", j)
                if not isinstance(item, dict):
                    v.add(ip, "each item must be an object")
                    continue
                for key_name, kind in keys:
                    if key_name not in item:
                        v.add(ip, f"missing key attribute '{key_name}'")
                    elif kind == "N" and (isinstance(item[key_name], bool) or
                                          not isinstance(item[key_name], (int, float))):
                        v.add(ip + (key_name,), "must be a number (the key type is N)")
                    elif kind == "S" and not isinstance(item[key_name], str):
                        v.add(ip + (key_name,), "must be text (the key type is S)")
        if "items_from" in t:
            if not isinstance(t["items_from"], str):
                v.add(path + ("items_from",), "must be a path")
            elif not (seed.base_dir / t["items_from"]).is_file():
                v.add(path + ("items_from",), f"'{t['items_from']}' not found (relative to the seed file)")

    # topics
    seen = {}
    for path, tp in items("topics"):
        name = v.name(tp, path, seen)
        v.type(tp, "fifo", bool, path, "true or false")
        if name and tp.get("fifo") and not name.endswith(".fifo"):
            v.add(path + ("name",), "FIFO topic names must end with '.fifo'")
        if v.type(tp, "subscriptions", list, path, "a list"):
            for j, s in enumerate(tp.get("subscriptions") or []):
                sp = path + ("subscriptions", j)
                if not isinstance(s, dict):
                    v.add(sp, "each subscription must be a mapping")
                    continue
                v.keys(s, FIELDS["subscriptions"], sp)
                targets = [k for k in ("sqs", "lambda") if k in s]
                if len(targets) != 1:
                    v.add(sp, "give exactly one of 'sqs' or 'lambda'")
                elif targets == ["sqs"] and isinstance(s["sqs"], str) and s["sqs"] not in queue_names:
                    seed.warnings.append(f"{_fmt_path(sp + ('sqs',))}: '{s['sqs']}' isn't in this "
                                         "seed; it must already exist when you apply it")
                v.type(s, "raw", bool, sp, "true or false")
                v.type(s, "filter", dict, sp, "a mapping (an SNS filter policy)")

    # secrets
    seen = {}
    for path, s in items("secrets"):
        v.name(s, path, seen)
        if "value" not in s or s["value"] is None:
            v.add(path, "'value' is required (text, or a mapping/list stored as JSON)")
        elif not isinstance(s["value"], (str, dict, list, int, float, bool)):
            v.add(path + ("value",), "must be text, a mapping or a list")
        v.type(s, "description", str, path, "text")

    # parameters
    seen = {}
    for path, p in items("parameters"):
        name = v.name(p, path, seen)
        if name and name.lstrip("/").lower().startswith(("aws", "ssm")):
            v.add(path + ("name",), "parameter names can't start with 'aws' or 'ssm' (AWS rule)")
        if "value" not in p or p["value"] is None:
            v.add(path, "'value' is required")
        elif isinstance(p["value"], (dict, bool)):
            v.add(path + ("value",), "must be text, a number or a list (for StringList)")
        if "type" in p and p["type"] not in PARAM_TYPES:
            v.add(path + ("type",), f"must be one of {', '.join(PARAM_TYPES)}")
        if isinstance(p.get("value"), list) and p.get("type", "StringList") != "StringList":
            v.add(path + ("value",), "a list value needs type StringList")
        v.type(p, "description", str, path, "text")

    return v.problems


# --------------------------------------------------------------------------- helpers for apply


def key_spec(value: str) -> tuple[str, str]:
    spec = _key_spec(value)
    assert spec is not None
    return spec


def secret_string(value: Any) -> str:
    return value if isinstance(value, str) else json.dumps(value, ensure_ascii=False)


def parameter_value(p: dict) -> tuple[str, str]:
    """``(value, type)`` for a parameter entry."""
    value = p["value"]
    if isinstance(value, list):
        return ",".join(str(x) for x in value), "StringList"
    return str(value), p.get("type", "String")


def object_payloads(obj: dict, base_dir: Path) -> list[tuple[str, bytes | Path]]:
    """Expand one ``objects`` entry into ``[(key, bytes-or-file-path)]``."""
    key = obj["key"]
    if "content" in obj:
        return [(key, obj["content"].encode("utf-8"))]
    if "json" in obj:
        return [(key, json.dumps(obj["json"], ensure_ascii=False, indent=2).encode("utf-8"))]
    src = base_dir / obj["from"]
    if src.is_file():
        return [(key + src.name if key.endswith("/") else key, src)]
    prefix = key if key.endswith("/") or not key else key + "/"
    return [(prefix + p.relative_to(src).as_posix(), p)
            for p in sorted(src.rglob("*")) if p.is_file()]


def load_items(t: dict, base_dir: Path) -> list[dict]:
    items = list(t.get("items") or [])
    if t.get("items_from"):
        data = yaml.safe_load((base_dir / t["items_from"]).read_text(encoding="utf-8"))
        if isinstance(data, dict):
            data = [data]
        if not isinstance(data, list) or not all(isinstance(i, dict) for i in data):
            raise SeedError(t["items_from"], [Problem(None, "", "must contain an object or a list of objects")])
        items += data
    return items


def dump(data: dict) -> str:
    """YAML for ``seed export``: readable, key order kept, unicode as-is."""
    class _Dumper(yaml.SafeDumper):
        pass

    def str_presenter(dumper, value):
        style = "|" if "\n" in value else None
        return dumper.represent_scalar("tag:yaml.org,2002:str", value, style=style)

    _Dumper.add_representer(str, str_presenter)
    return yaml.dump(data, Dumper=_Dumper, sort_keys=False, allow_unicode=True, width=100)
