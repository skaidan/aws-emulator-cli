"""Per-project settings: ``awsemu.toml`` or ``[tool.awsemu]`` in ``pyproject.toml``.

Looked up from the current folder upwards (or ``$AWSEMU_CONFIG``)::

    # awsemu.toml
    port = 9310
    mode = "native"          # auto | native | docker
    auth = true
    telemetry = false
    idle_timeout = 3600
    seed = "tests/seed.yaml" # relative to this file
    sdk = ["node"]           # extra certificate settings for env/exec/shell
    image = "aws-emulator"
    memory = "2g"

Precedence everywhere: command-line flag > environment variable > project file > default.
"""

from __future__ import annotations

import difflib
import os
import sys
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

if sys.version_info >= (3, 11):
    import tomllib
else:  # pragma: no cover
    import tomli as tomllib

FILE_NAME = "awsemu.toml"
MODES = ("auto", "native", "docker")
SDKS = ("node", "java", "rust", "dotnet")

TYPES: dict[str, tuple] = {
    "port": (int,),
    "mode": (str,),
    "auth": (bool,),
    "telemetry": (bool,),
    "idle_timeout": (int,),
    "seed": (str,),
    "sdk": (list,),
    "image": (str,),
    "memory": (str,),
}

TEMPLATE = """\
# awsemu project settings. Every command run in this folder (or below) uses them;
# command-line flags and environment variables (AWSEMU_PORT) still win.
# Docs: https://github.com/skaidan/aws-emulator-cli/blob/main/docs/project-config.md

port = {port}
# mode = "auto"            # auto | native | docker
# auth = true              # false = accept unsigned requests
telemetry = false
idle_timeout = 3600        # stop after an hour without API calls
{seed_line}
# sdk = ["node"]           # also trust the certificate in Node/Java/Rust/.NET (env, exec, shell)
# image = "aws-emulator"   # Docker image (awsemu image build)
# memory = "2g"            # Docker memory limit
"""


class ProjectError(Exception):
    pass


@dataclass
class Project:
    path: Path
    port: int | None = None
    mode: str | None = None
    auth: bool | None = None
    telemetry: bool | None = None
    idle_timeout: int | None = None
    seed: Path | None = None
    sdk: list[str] = field(default_factory=list)
    image: str | None = None
    memory: str | None = None

    @property
    def root(self) -> Path:
        return self.path.parent


def _read(path: Path) -> dict | None:
    """The settings table in ``path``, or None if this file has none."""
    try:
        with path.open("rb") as fh:
            data = tomllib.load(fh)
    except tomllib.TOMLDecodeError as exc:
        raise ProjectError(f"{path}: invalid TOML: {exc}") from exc
    if path.name == "pyproject.toml":
        return data.get("tool", {}).get("awsemu")
    return data


def find(start: Path | None = None) -> Path | None:
    """The settings file that applies to ``start`` (default: current folder)."""
    override = os.environ.get("AWSEMU_CONFIG")
    if override:
        path = Path(override).expanduser()
        if not path.is_file():
            raise ProjectError(f"AWSEMU_CONFIG points to {path}, which doesn't exist")
        return path
    here = (start or Path.cwd()).resolve()
    for folder in (here, *here.parents):
        candidate = folder / FILE_NAME
        if candidate.is_file():
            return candidate
        pyproject = folder / "pyproject.toml"
        if pyproject.is_file():
            try:
                if _read(pyproject) is not None:
                    return pyproject
            except ProjectError:
                pass
    return None


def parse(path: Path) -> Project:
    data = _read(path) or {}
    where = f"{path}" + (" [tool.awsemu]" if path.name == "pyproject.toml" else "")
    problems = []
    for key, value in data.items():
        if key not in TYPES:
            hint = difflib.get_close_matches(key, list(TYPES), n=1)
            problems.append(f"unknown setting '{key}'" + (f" (did you mean '{hint[0]}'?)" if hint else ""))
        elif not isinstance(value, TYPES[key]) or (TYPES[key] == (int,) and isinstance(value, bool)):
            problems.append(f"'{key}' must be {TYPES[key][0].__name__}")
    if not problems:
        if "mode" in data and data["mode"] not in MODES:
            problems.append(f"'mode' must be one of {', '.join(MODES)}")
        if "port" in data and not (0 < data["port"] < 65536):
            problems.append("'port' must be between 1 and 65535")
        if "idle_timeout" in data and data["idle_timeout"] <= 0:
            problems.append("'idle_timeout' must be positive")
        bad_sdk = [s for s in data.get("sdk", []) if s not in SDKS]
        if bad_sdk:
            problems.append(f"'sdk' accepts {', '.join(SDKS)} (got {', '.join(map(str, bad_sdk))})")
    if problems:
        raise ProjectError(f"{where}: " + "; ".join(problems))
    seed = data.get("seed")
    return Project(
        path=path,
        port=data.get("port"),
        mode=data.get("mode"),
        auth=data.get("auth"),
        telemetry=data.get("telemetry"),
        idle_timeout=data.get("idle_timeout"),
        seed=(path.parent / seed) if seed else None,
        sdk=list(data.get("sdk", [])),
        image=data.get("image"),
        memory=data.get("memory"),
    )


@lru_cache(maxsize=32)
def _parse_cached(path: str, mtime_ns: int) -> Project:
    return parse(Path(path))


def load() -> Project | None:
    """The project settings for the current folder (re-read when the file changes)."""
    path = find()
    if path is None:
        return None
    return _parse_cached(str(path), path.stat().st_mtime_ns)


def clear_cache() -> None:
    _parse_cached.cache_clear()


def template(port: int, seed: str | None) -> str:
    seed_line = f'seed = "{seed}"' if seed else '# seed = "tests/seed.yaml"  # applied by awsemu up / start --seed'
    return TEMPLATE.format(port=port, seed_line=seed_line)
