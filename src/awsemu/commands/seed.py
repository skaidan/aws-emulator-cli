"""``awsemu seed``: apply, validate and export seed files (see ``awsemu.seed``)."""

from __future__ import annotations

import sys
import time
from datetime import datetime
from pathlib import Path

import click

from .. import exitcodes, services
from .. import seed as seedlib
from .. import ui
from ..context import Ctx, handle_errors, pass_ctx
from ..runtime import RuntimeErrorWithHint


class Report:
    def __init__(self):
        self.rows: list[list] = []
        self.failures = 0

    def add(self, kind: str, name: str, result: str, detail: str = "") -> None:
        style = {"created": "ok", "updated": "info", "unchanged": "muted", "failed": "error"}.get(result)
        if result == "failed":
            self.failures += 1
        self.rows.append([kind, name, ui.styled(result, style), detail])


# =========================================================================== apply


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


def apply_seed(seed: seedlib.Seed, port: int) -> Report:
    report = Report()
    by_section = services.seed_sections()
    for section in APPLY_ORDER:
        apply = by_section[section].apply
        if seed.section(section) and apply:  # every seed section has one (tests/test_services_registry.py)
            apply(seed, port, report)
    return report


def load_or_fail(path: str) -> seedlib.Seed:
    try:
        seed = seedlib.load_file(path)
    except seedlib.SeedError as exc:
        for p in exc.problems:
            ui.error(p.format(exc.source))
        raise SystemExit(exitcodes.USAGE) from exc
    for w in seed.warnings:
        ui.warn(w)
    return seed


def run_apply(seed: seedlib.Seed, port: int) -> None:
    """Apply and print the report; exits 1 if anything failed."""
    started = time.monotonic()
    report = apply_seed(seed, port)
    ui.table(["kind", "name", "result", "detail"], report.rows, title=f"seed {seed.source}")
    counts: dict[str, int] = {}
    for row in report.rows:
        key = str(row[2])
        counts[key] = counts.get(key, 0) + 1
    summary = ", ".join(f"{n} {k}" for k, n in counts.items())
    if report.failures:
        ui.error(f"seed applied with errors ({summary})")
        raise SystemExit(exitcodes.FAILED)
    ui.success(f"seed applied in {time.monotonic() - started:.1f}s ({summary})")


# =========================================================================== export


def _export(
    port: int, sections: set[str], objects_dir: Path | None, out_dir: Path, include_secrets: bool
) -> tuple[dict, list[str]]:
    data: dict = {"version": seedlib.VERSION}
    opts = seedlib.ExportOptions(objects_dir, out_dir, include_secrets)
    by_section = services.seed_sections()
    for section in seedlib.SECTIONS:
        export = by_section[section].export
        if section in sections and export:
            items = export(port, opts)
            if items:
                data[section] = items
    return data, opts.notes


# =========================================================================== commands


@click.group()
def seed():
    """Seed files: the same starting data after every start or reset."""


@seed.command(name="apply")
@click.argument("file", type=click.Path(dir_okay=False))
@pass_ctx
@handle_errors
def apply_cmd(c: Ctx, file: str):
    """Create what FILE describes. Safe to run again: existing things are updated or left alone.

    \b
      awsemu seed apply seed.yaml
      awsemu start --seed seed.yaml     # start and apply in one step
      awsemu reset --seed seed.yaml     # empty state + seed
    """
    run_apply(load_or_fail(file), c.port)


@seed.command(name="validate")
@click.argument("file", type=click.Path(dir_okay=False))
def validate_cmd(file: str):
    """Check FILE without touching the emulator (errors show line and field)."""
    s = load_or_fail(file)
    counts = ", ".join(f"{n} {k}" for k, n in s.count().items()) or "nothing"
    ui.success(f"{file} is valid: {counts}")


@seed.command(name="export")
@click.option(
    "-o", "--output", type=click.Path(dir_okay=False, path_type=Path), help="Write to this file (default: stdout)."
)
@click.option(
    "--objects-dir",
    type=click.Path(file_okay=False, path_type=Path),
    help="Save binary or large S3 objects, and Lambda functions' code, here (referenced from the seed).",
)
@click.option("--no-secrets", is_flag=True, help="Leave out secrets and SecureString parameters.")
@click.option(
    "-s",
    "--section",
    "sections",
    multiple=True,
    type=click.Choice(seedlib.SECTIONS),
    help="Only these sections. Repeatable.",
)
@pass_ctx
@handle_errors
def export_cmd(c: Ctx, output: Path | None, objects_dir: Path | None, no_secrets: bool, sections):
    """Write what's in the emulator now as a seed file.

    Secret values and SecureString parameters are exported in plain text
    unless --no-secrets.
    """
    out_dir = (output.parent if output else Path(".")).resolve()
    data, notes = _export(
        c.port,
        set(sections) or set(seedlib.SECTIONS),
        objects_dir.resolve() if objects_dir else None,
        out_dir,
        not no_secrets,
    )
    header = (
        f"# Seed exported by awsemu from port {c.port} on "
        f"{datetime.now().strftime('%Y-%m-%d %H:%M')}.\n"
        "# Apply it with: awsemu seed apply <this file>\n"
    )
    text = header + seedlib.dump(data)
    for n in notes:
        ui.warn(n)
    if output:
        output.write_text(text, encoding="utf-8")
        counts = ", ".join(f"{len(v)} {k}" for k, v in data.items() if isinstance(v, list)) or "nothing"
        ui.success(f"wrote {output} ({counts})")
        if not no_secrets and (
            data.get("secrets") or any(p.get("type") == "SecureString" for p in data.get("parameters", []))
        ):
            ui.warn(f"{output} contains secret values in plain text")
    else:
        click.echo(text, nl=False)


@seed.command(name="import")
@click.option(
    "--profile",
    required=True,
    metavar="NAME",
    help="The AWS profile to read with (required: the default credentials are never used).",
)
@click.option("--region", metavar="REGION", help="Region to read (default: the profile's).")
@click.option(
    "-o", "--output", type=click.Path(dir_okay=False, path_type=Path), help="Write to this file (default: stdout)."
)
@click.option(
    "-s",
    "--section",
    "sections",
    multiple=True,
    type=click.Choice(seedlib.SECTIONS),
    help="Only these sections. Repeatable.",
)
@click.option("--yes", is_flag=True, help="Don't ask before reading the account.")
@handle_errors
def import_cmd(profile: str, region, output: Path | None, sections, yes: bool):
    """Write a seed from a real AWS account's configuration, read-only.

    \\b
      awsemu seed import --profile dev --region eu-west-1 -o seed.yaml
      awsemu seed apply seed.yaml

    Reads buckets (not their objects), queues, tables (not their items),
    topics, parameters (SecureString values replaced), secrets (names only),
    streams, state machines and rules. Any call that isn't a read is refused
    before it's sent, and AWS_ENDPOINT_URL is ignored. Guide: docs/seeds.md.
    """
    from .. import realaccount as ra

    try:
        sess = ra.session(profile, region)
        if not sess.region_name:
            raise click.UsageError(f"profile '{profile}' has no Region: pass --region")
        who = ra.client(sess, "sts").get_caller_identity()
    except ra.NotReadOnly as exc:
        raise RuntimeErrorWithHint(str(exc)) from exc
    except Exception as exc:
        if type(exc).__name__ in ("ProfileNotFound", "NoCredentialsError", "PartialCredentialsError"):
            raise RuntimeErrorWithHint(
                f"can't use profile '{profile}': {exc}", "List your profiles with: aws configure list-profiles"
            ) from exc
        raise
    ui.echo(
        f"Reading AWS account {who['Account']} ({who['Arn']}), Region {sess.region_name}, read-only.", "warn", err=True
    )
    if not yes:
        if not sys.stdin.isatty():
            raise click.UsageError("reading a real account needs --yes when there's no terminal to ask")
        click.confirm("Go on?", abort=True, err=True)
    try:
        data, notes = ra.import_seed(sess, set(sections) or set(seedlib.SECTIONS))
    except ra.NotReadOnly as exc:  # pragma: no cover - a bug if it happens: say so loudly
        raise RuntimeErrorWithHint(str(exc)) from exc
    header = (
        f"# Seed imported by awsemu from AWS account {who['Account']}, {sess.region_name}, on "
        f"{datetime.now().strftime('%Y-%m-%d %H:%M')} (configuration only, read-only).\n"
        "# Secret values are placeholders. Apply it with: awsemu seed apply <this file>\n"
    )
    text = header + seedlib.dump(data)
    for n in notes:
        ui.warn(n)
    if output:
        output.write_text(text, encoding="utf-8")
        counts = ", ".join(f"{len(v)} {k}" for k, v in data.items() if isinstance(v, list)) or "nothing"
        ui.success(f"wrote {output} ({counts})")
    else:
        click.echo(text, nl=False)
