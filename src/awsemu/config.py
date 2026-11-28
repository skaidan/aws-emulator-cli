"""One configuration model: every setting with its value and where that value came from.

Layers, highest first: the command line, an environment variable, the project file
(``awsemu.toml`` or ``[tool.awsemu]``), then the default. :func:`resolve` applies them
once for everyone, and ``awsemu config explain`` prints the result::

    port       9310   awsemu.toml, line 3
    mode       auto   default
    telemetry  -      not set: the emulator decides (EMULATOR_TELEMETRY=off in this shell)
"""

from __future__ import annotations

import os
import re
from collections.abc import Callable, Mapping
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from . import project
from .paths import DEFAULT_PORT

ENV_VARS = {"port": "AWSEMU_PORT"}
"""Settings that an environment variable can set."""

DEFAULTS: dict[str, Any] = {
    "port": DEFAULT_PORT,
    "mode": "auto",
    "auth": True,
    "telemetry": None,
    "idle_timeout": None,
    "seed": None,
    "sdk": [],
    "image": None,  # computed: see _default_image
    "memory": "2g",
    "emulator_version": None,
    "proxy": False,
    "proxy_port": None,
    "proxy_bodies": False,
    "faults": [],
}


@dataclass(frozen=True)
class Value:
    name: str
    value: Any
    source: str
    """``command line``, ``environment (AWSEMU_PORT)``, ``awsemu.toml, line 3``, ``default``…"""

    def as_dict(self) -> dict:
        return asdict(self)


def _default_image(proj: project.Project | None) -> str:
    from .runtime import DEFAULT_IMAGE

    return f"{DEFAULT_IMAGE}:{proj.emulator_version}" if proj and proj.emulator_version else DEFAULT_IMAGE


def _env(name: str, parse: Callable[[str], Any]) -> tuple[Any, str] | None:
    var = ENV_VARS.get(name)
    raw = os.environ.get(var) if var else None
    if not raw:
        return None
    try:
        return parse(raw), f"environment ({var})"
    except ValueError:
        return None  # an unusable value is ignored, as before


def line_of(path: Path, key: str) -> int | None:
    """The line where ``key`` is set in a project file (in ``[tool.awsemu]`` for pyproject.toml)."""
    table = "tool.awsemu" if path.name == "pyproject.toml" else ""
    current = ""
    key_re = re.compile(rf"^\s*{re.escape(key)}\s*=")
    for number, text in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        header = re.match(r"^\s*\[([^\[\]]+)\]\s*(#.*)?$", text)
        if header:
            current = header.group(1).strip()
        elif current == table and key_re.match(text):
            return number
    return None


def _set_in(proj: project.Project, key: str) -> bool:
    """Whether the project file sets ``key`` (a value equal to the default counts too)."""
    return line_of(proj.path, key) is not None or getattr(proj, key) not in (None, [], False)


def _file_source(proj: project.Project, key: str) -> str:
    line = line_of(proj.path, key)
    where = proj.path.name + (" [tool.awsemu]" if proj.path.name == "pyproject.toml" else "")
    return f"{where}, line {line}" if line else where


def _telemetry_default() -> str:
    from . import settings

    env = os.environ.get("EMULATOR_TELEMETRY")
    if env:
        why = f"EMULATOR_TELEMETRY={env} in this shell"
    else:
        enabled = settings.telemetry_enabled()
        why = "its default, on" if enabled is None else f"{'on' if enabled else 'off'} in its config.toml"
    return f"not set: the emulator decides ({why})"


def resolve(flags: Mapping[str, Any] | None = None) -> dict[str, Value]:
    """Every setting, by name, in the order of the project file's settings.

    ``flags`` are the values given on the command line (only those given). An invalid
    project file raises :class:`project.ProjectError`."""
    flags = flags or {}
    proj = project.load()
    out: dict[str, Value] = {}
    for name in project.TYPES:
        if flags.get(name) is not None:
            out[name] = Value(name, flags[name], "command line")
            continue
        from_env = _env(name, int)
        if from_env:
            out[name] = Value(name, *from_env)
            continue
        if proj is not None and _set_in(proj, name):
            value = getattr(proj, name)
            out[name] = Value(name, str(value) if isinstance(value, Path) else value, _file_source(proj, name))
            continue
        if name == "image":
            pinned = proj is not None and proj.emulator_version is not None
            out[name] = Value(name, _default_image(proj), "default (from emulator_version)" if pinned else "default")
        elif name == "telemetry":
            out[name] = Value(name, None, _telemetry_default())
        else:
            out[name] = Value(name, DEFAULTS[name], "default")
    return out
