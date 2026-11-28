"""Applying and exporting seeds through the service registry, and the saved snapshots
(a snapshot is an exported seed plus ``snapshot.json``). No printing: the commands, the
pytest plugin and snapshots show the results their own way."""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from pathlib import Path

from . import seed as seedlib
from . import services
from .paths import cli_root

# What others point at first: queues and streams, then functions, then the wiring.
APPLY_ORDER = (
    "buckets",
    "queues",
    "tables",
    "streams",
    "secrets",
    "parameters",
    "functions",
    "state_machines",
    "topics",
    "rules",
)


class Report:
    """One ``[kind, name, result, detail]`` row per resource; result is created, updated, unchanged or failed."""

    def __init__(self, say: Callable[[str], None] | None = None):
        self.rows: list[list[str]] = []
        self.failures = 0
        self.say = say or (lambda message: None)
        """Progress for slow steps (installing a function's requirements)."""

    def add(self, kind: str, name: str, result: str, detail: str = "") -> None:
        if result == "failed":
            self.failures += 1
        self.rows.append([kind, name, result, detail])


def apply(seed: seedlib.Seed, port: int, say: Callable[[str], None] | None = None) -> Report:
    """Create or update what ``seed`` lists in the emulator on ``port``; never deletes."""
    report = Report(say)
    by_section = services.seed_sections()
    for section in APPLY_ORDER:
        hook = by_section[section].apply
        if seed.section(section) and hook:  # every seed section has one (tests/test_services_registry.py)
            hook(seed, port, report)
    return report


def export(
    port: int, sections: set[str], objects_dir: Path | None, out_dir: Path, include_secrets: bool
) -> tuple[dict, list[str]]:
    """The emulator's ``sections`` as seed data, and notes on what was left out."""
    data: dict = {"version": seedlib.VERSION}
    opts = seedlib.ExportOptions(objects_dir, out_dir, include_secrets)
    by_section = services.seed_sections()
    for section in seedlib.SECTIONS:
        hook = by_section[section].export
        if section in sections and hook:
            items = hook(port, opts)
            if items:
                data[section] = items
    return data, opts.notes


@dataclass(frozen=True)
class SavedSnapshot:
    """One saved snapshot, from its ``snapshot.json`` (``awsemu snapshot ls``)."""

    name: str
    created_at: str | None = None
    port: int | None = None
    emulator_version: str | None = None
    counts: dict[str, int] = field(default_factory=dict)
    secrets: bool | None = None
    """Whether it holds secret values in plain text."""
    path: str = ""

    def as_dict(self) -> dict:
        return asdict(self)


def snapshots_dir() -> Path:
    return cli_root() / "snapshots"


def snapshot_meta(folder: Path) -> dict:
    try:
        return json.loads((folder / "snapshot.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def list_snapshots(root: Path | None = None) -> list[SavedSnapshot]:
    """The snapshots saved in ``root`` (default: :func:`snapshots_dir`), by name."""
    root = root or snapshots_dir()
    folders = sorted(p for p in root.iterdir() if (p / "seed.yaml").is_file()) if root.is_dir() else []
    out = []
    for folder in folders:
        meta = snapshot_meta(folder)
        out.append(
            SavedSnapshot(
                name=folder.name,
                path=str(folder),
                created_at=meta.get("created_at"),
                port=meta.get("port"),
                emulator_version=meta.get("emulator_version"),
                counts=meta.get("counts", {}),
                secrets=meta.get("secrets"),
            )
        )
    return out
