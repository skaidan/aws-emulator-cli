"""Newer releases of the emulator and of awsemu, and the oldest emulator awsemu supports.

``awsemu doctor`` always shows them; ``awsemu start`` mentions a newer one at most once a
day, on a terminal, never in CI (``CI`` set) or with ``AWSEMU_NO_UPDATE_CHECK=1``. The
answers are cached for a day in ``~/.aws/emulator-cli/updates.json``; looking them up
uses GitHub's API with a short timeout and never fails a command.
"""

from __future__ import annotations

import json
import os
import re
import sys
import time
from dataclasses import dataclass

from . import __version__, _meta
from .paths import cli_root

# The oldest emulator release this awsemu is tested with (the "oldest supported" CI job).
# 1.0.290 is the first that logs "emulator server information", which random ports rely on.
MIN_EMULATOR = "1.0.290"
CACHE_SECONDS = 24 * 3600
TIMEOUT = 3.0


def parse(version: str | None) -> tuple[int, ...] | None:
    m = re.match(r"^v?(\d+(?:\.\d+)*)", version or "")
    return tuple(int(x) for x in m.group(1).split(".")) if m else None


def older(a: str | None, b: str | None) -> bool:
    """Is version ``a`` older than ``b``? (False when either is unknown.)"""
    pa, pb = parse(a), parse(b)
    return bool(pa and pb and pa < pb)


@dataclass
class Latest:
    emulator: str | None = None
    awsemu: str | None = None
    checked_at: float = 0.0
    notified_at: float = 0.0


def _path():
    return cli_root() / "updates.json"


def _load() -> Latest:
    try:
        data = json.loads(_path().read_text(encoding="utf-8"))
        return Latest(
            **{k: data.get(k) for k in ("emulator", "awsemu")},
            checked_at=float(data.get("checked_at", 0)),
            notified_at=float(data.get("notified_at", 0)),
        )
    except (OSError, ValueError, TypeError):
        return Latest()


def _save(latest: Latest) -> None:
    try:
        _path().parent.mkdir(parents=True, exist_ok=True)
        _path().write_text(json.dumps(latest.__dict__), encoding="utf-8")
    except OSError:  # pragma: no cover
        pass


def _fetch_latest_tag(repo: str) -> str | None:
    from . import fidelity as fid

    try:
        data = json.loads(fid._get(f"https://api.github.com/repos/{repo}/releases/latest", timeout=TIMEOUT))
    except Exception:  # offline, rate-limited… never a problem for the caller
        return None
    tag = data.get("tag_name") if isinstance(data, dict) else None
    return tag.lstrip("v") if isinstance(tag, str) else None


def disabled() -> bool:
    return os.environ.get("AWSEMU_NO_UPDATE_CHECK", "").lower() in ("1", "true", "yes")


def latest(refresh: bool = False) -> Latest:
    """The newest releases, from the cache when it's less than a day old (or when lookups are off)."""
    cached = _load()
    if disabled():
        return cached
    if not refresh and time.time() - cached.checked_at < CACHE_SECONDS and (cached.emulator or cached.awsemu):
        return cached
    from .fidelity import REPO as EMULATOR_REPO

    found = Latest(_fetch_latest_tag(EMULATOR_REPO), _fetch_latest_tag(_meta.REPO), time.time(), cached.notified_at)
    if found.emulator or found.awsemu:
        _save(found)
        return found
    return cached


def quiet() -> bool:
    """No notices in CI, when asked not to, or when nobody's looking."""
    if os.environ.get("CI") or disabled():
        return True
    return not sys.stderr.isatty()


def notices(installed_emulator: str | None, info: Latest) -> list[str]:
    out = []
    if info.emulator and older(installed_emulator, info.emulator):
        out.append(f"AWS Emulator {info.emulator} is out (you have {installed_emulator}): awsemu install latest")
    if info.awsemu and older(__version__, info.awsemu):
        out.append(f"awsemu {info.awsemu} is out (you have {__version__}): {_meta.REPO_URL}/releases")
    return out


def notify_once_a_day(installed_emulator: str | None) -> list[str]:
    """What ``awsemu start`` should mention, if anything (and remember that it did)."""
    if quiet():
        return []
    info = _load()
    if time.time() - info.notified_at < CACHE_SECONDS:
        return []
    info = latest()
    found = notices(installed_emulator, info)
    info.notified_at = time.time()
    _save(info)
    return found
