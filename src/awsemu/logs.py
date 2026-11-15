"""Make the emulator's JSON-lines log readable.

Only the startup line (``message == "emulator server information"``) is a stable
interface; every other field is shown generically. The emulator logs in the
``tracing`` JSON format, where the message and its fields sit under ``"fields"``.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

STARTUP_MESSAGE = "emulator server information"

_TIME_KEYS = ("timestamp", "time", "ts", "@timestamp")
_LEVEL_KEYS = ("level", "severity", "lvl")
_MSG_KEYS = ("message", "msg")
_SKIP_KEYS = {"target", "fields"}


@dataclass
class LogLine:
    raw: str
    data: dict[str, Any] | None

    @property
    def is_json(self) -> bool:
        return self.data is not None

    def _first(self, keys) -> str | None:
        if not self.data:
            return None
        nested = self.data.get("fields")
        sources = [self.data] + ([nested] if isinstance(nested, dict) else [])
        for source in sources:
            for k in keys:
                if k in source and source[k] is not None:
                    return str(source[k])
        return None

    @property
    def time(self) -> str | None:
        t = self._first(_TIME_KEYS)
        if t and "T" in t:
            # 2026-11-15T12:00:00.123456Z -> 12:00:00.123
            t = t.split("T", 1)[1].rstrip("Z")
            if "." in t:
                head, frac = t.split(".", 1)
                t = f"{head}.{frac[:3]}"
        return t

    @property
    def level(self) -> str:
        return (self._first(_LEVEL_KEYS) or "").upper()

    @property
    def message(self) -> str:
        if not self.data:
            return self.raw
        return self._first(_MSG_KEYS) or ""

    @property
    def extra(self) -> dict[str, Any]:
        if not self.data:
            return {}
        used = set(_TIME_KEYS) | set(_LEVEL_KEYS) | set(_MSG_KEYS) | _SKIP_KEYS
        out = {k: v for k, v in self.data.items() if k not in used}
        nested = self.data.get("fields")
        if isinstance(nested, dict):
            out.update({k: v for k, v in nested.items() if k not in used})
        return out

    @property
    def is_startup(self) -> bool:
        return self.message == STARTUP_MESSAGE


def parse(line: str) -> LogLine:
    line = line.rstrip("\r\n")
    stripped = line.strip()
    if stripped.startswith("{"):
        try:
            data = json.loads(stripped)
            if isinstance(data, dict):
                return LogLine(line, data)
        except json.JSONDecodeError:
            pass
    return LogLine(line, None)


def format_plain(entry: LogLine) -> str:
    if not entry.is_json:
        return entry.raw
    parts = [p for p in (entry.time, entry.level.ljust(5) if entry.level else None) if p]
    parts.append(entry.message)
    extra = " ".join(f"{k}={_short(v)}" for k, v in entry.extra.items())
    if extra:
        parts.append(extra)
    return "  ".join(parts)


def _short(value: Any) -> str:
    text = value if isinstance(value, str) else json.dumps(value, separators=(",", ":"))
    return text if len(text) <= 120 else text[:117] + "..."


def find_startup(lines) -> dict[str, Any] | None:
    """Return the startup line's fields (endpoint_url, ca_file, ...) if present."""
    for line in lines:
        entry = parse(line)
        if entry.is_startup:
            fields = dict(entry.data or {})
            nested = fields.get("fields")
            if isinstance(nested, dict):
                fields.update(nested)
            return fields
    return None
