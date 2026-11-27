"""Applying and exporting seeds through the service registry (no printing: the commands,
the pytest plugin and snapshots show the results their own way)."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from . import seed as seedlib
from . import services

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
