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
    emulator_version = "1.0.385"  # the team's emulator (awsemu install)

Precedence everywhere: command-line flag > environment variable > project file > default.
"""

from __future__ import annotations

import difflib
import os
import re
import sys
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

if sys.version_info >= (3, 11):
    import tomllib
else:  # pragma: no cover
    import tomli as tomllib

FILE_NAME = "awsemu.toml"
VERSION_RE = re.compile(r"^v?\d+\.\d+\.\d+$")
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
    "emulator_version": (str,),
    "proxy": (bool,),
    "proxy_port": (int,),
    "proxy_bodies": (bool,),
    "faults": (list,),
}

TEMPLATE = """\
# awsemu project settings. Every command run in this folder (or below) uses them;
# command-line flags and environment variables (AWSEMU_PORT) still win.
# Docs: {docs_url}/project-config.md

port = {port}
# mode = "auto"            # auto | native | docker
# auth = true              # false = accept unsigned requests
telemetry = false
idle_timeout = 3600        # stop after an hour without API calls
{seed_line}
# sdk = ["node"]           # also trust the certificate in Node/Java/Rust/.NET (env, exec, shell)
# image = "aws-emulator"   # Docker image (awsemu image build)
# memory = "2g"            # Docker memory limit
# emulator_version = "1.0.385"  # pin the emulator: awsemu install, warnings at start
# proxy = true             # awsemu up also starts the proxy (calls log, faults); env/exec use it
# faults = ["dynamodb=throttle@5%"]  # fault rules for that proxy (docs: proxy.md)
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
    emulator_version: str | None = None
    proxy: bool = False
    proxy_port: int | None = None
    proxy_bodies: bool = False
    faults: list[str] = field(default_factory=list)

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
    where = f"{path}" + (" [tool.awsemu]" if path.name == "pyproject.toml" else "")
    from . import deprecation

    data = deprecation.settings(_read(path) or {}, where)
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
        version = data.get("emulator_version")
        if version is not None and not VERSION_RE.match(version):
            problems.append(f"'emulator_version' must be a version like 1.0.385 (got '{version}')")
        if "proxy_port" in data and not (0 <= data["proxy_port"] < 65536):
            problems.append("'proxy_port' must be between 0 and 65535")
        for spec in data.get("faults", []):
            from . import faults as _faults

            try:
                _faults.parse(str(spec))
            except _faults.FaultError as exc:
                problems.append(f"'faults': {exc}")
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
        emulator_version=data["emulator_version"].lstrip("v") if data.get("emulator_version") else None,
        proxy=bool(data.get("proxy", False)),
        proxy_port=data.get("proxy_port"),
        proxy_bodies=bool(data.get("proxy_bodies", False)),
        faults=[str(x) for x in data.get("faults", [])],
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
    from ._meta import DOCS_URL

    return TEMPLATE.format(port=port, seed_line=seed_line, docs_url=DOCS_URL)


def set_value(key: str, value: str, path: Path | None = None) -> Path:
    """Set a top-level setting in the project file (``[tool.awsemu]`` in pyproject.toml),
    creating ``awsemu.toml`` in the current folder when there's none. Keeps comments."""
    from . import settings

    path = path or find() or Path.cwd() / FILE_NAME
    if path.name == "pyproject.toml":
        settings.set_value("tool.awsemu", key, value, path)
        clear_cache()
        return path
    text = path.read_text(encoding="utf-8") if path.exists() else ""
    line = f'{key} = "{value}"'
    lines = text.splitlines()
    key_re = re.compile(rf"^\s*{re.escape(key)}\s*=")
    for i, existing in enumerate(lines):
        if existing.lstrip().startswith("["):
            lines.insert(i, line)  # top-level keys must come before any table
            break
        if key_re.match(existing):
            lines[i] = line
            break
    else:
        lines.append(line)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    parse(path)  # still valid?
    clear_cache()
    return path
