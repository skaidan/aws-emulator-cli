"""Read and edit the emulator's own settings file (``config.toml``).

Today the documented setting is ``[telemetry] enabled``. Edits are done on the
text so comments and unknown keys in the user's file are kept.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import tomllib

from .paths import emulator_settings_file

_SECTION_RE = re.compile(r"^\s*\[([^\[\]]+)\]\s*(#.*)?$")


def load(path: Path | None = None) -> dict[str, Any]:
    path = path or emulator_settings_file()
    if not path.exists():
        return {}
    with path.open("rb") as fh:
        return tomllib.load(fh)


def _format_value(value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return str(value)
    escaped = str(value).replace("\\", "\\\\").replace('"', '\\"')
    return f'"{escaped}"'


def set_value(section: str, key: str, value: Any, path: Path | None = None) -> Path:
    """Set ``[section] key = value``, creating the file/section if needed."""
    path = path or emulator_settings_file()
    text = path.read_text(encoding="utf-8") if path.exists() else ""
    lines = text.splitlines()
    new_line = f"{key} = {_format_value(value)}"
    key_re = re.compile(rf"^\s*{re.escape(key)}\s*=")

    start = None
    for i, line in enumerate(lines):
        m = _SECTION_RE.match(line)
        if m and m.group(1).strip() == section:
            start = i
            break

    if start is None:
        if lines and lines[-1].strip():
            lines.append("")
        lines += [f"[{section}]", new_line]
    else:
        end = len(lines)
        for j in range(start + 1, len(lines)):
            if _SECTION_RE.match(lines[j]):
                end = j
                break
        for j in range(start + 1, end):
            if key_re.match(lines[j]):
                lines[j] = new_line
                break
        else:
            insert_at = end
            while insert_at > start + 1 and not lines[insert_at - 1].strip():
                insert_at -= 1
            lines.insert(insert_at, new_line)

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    # Validate we wrote something TOML can read.
    load(path)
    return path


def telemetry_enabled(path: Path | None = None) -> bool | None:
    """``True``/``False`` if set in the file, ``None`` if unset (emulator default: on)."""
    value = load(path).get("telemetry", {}).get("enabled")
    return value if isinstance(value, bool) else None
