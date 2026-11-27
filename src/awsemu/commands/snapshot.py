"""``awsemu snapshot``: save and restore a whole scenario.

The emulator has no snapshots of its own (its state lives in memory), so a snapshot is
a seed: ``seed export`` of everything, with the files it needs, plus a little metadata.
Restoring empties the emulator (a restart) and applies it.

Layout of ``<dir>/<NAME>/``::

    seed.yaml        # what to recreate
    files/           # S3 objects that don't fit in the seed, Lambda code
    snapshot.json    # when, from which port and emulator version, what's inside
"""

from __future__ import annotations

import datetime as dt
import json
import re
import shutil
import sys
from pathlib import Path

import click

from .. import __version__, exitcodes, ui, seeding
from .. import seed as seedlib
from ..context import Ctx, handle_errors, json_option, pass_ctx, yes_option
from ..paths import cli_root
from ..runtime import RuntimeErrorWithHint

NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")


def default_dir() -> Path:
    return cli_root() / "snapshots"


def _dir_option(fn):
    return click.option(
        "--dir",
        "base",
        type=click.Path(file_okay=False, path_type=Path),
        metavar="DIR",
        help="Where snapshots are kept (default: ~/.aws/emulator-cli/snapshots).",
    )(fn)


def _folder(base: Path | None, name: str) -> Path:
    if not NAME_RE.match(name):
        raise click.BadParameter("use letters, digits, '.', '_' and '-' (up to 64)", param_hint="'NAME'")
    return (base or default_dir()) / name


def _meta(folder: Path) -> dict:
    try:
        return json.loads((folder / "snapshot.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _installed_version() -> str | None:
    from ..fidelity import installed_version

    try:
        return installed_version()
    except Exception:  # only informative
        return None


@click.group()
def snapshot():
    """Save and restore a whole scenario (the emulator has no snapshots of its own).

    \b
      awsemu snapshot save checkout-ready     # everything in the emulator now
      awsemu snapshot restore checkout-ready  # empty it and put that back
      awsemu snapshot ls

    A snapshot is a seed (see 'awsemu seed') with the files it needs: S3 objects
    and Lambda code. It may contain secrets in plain text, so the default place
    is your home folder; --no-secrets leaves them out.
    """


@snapshot.command()
@click.argument("name")
@_dir_option
@click.option("--no-secrets", is_flag=True, help="Leave out secrets and SecureString parameters.")
@click.option("--force", is_flag=True, help="Replace a snapshot with the same name.")
@pass_ctx
@handle_errors
def save(c: Ctx, name: str, base: Path | None, no_secrets: bool, force: bool):
    """Save everything in the emulator as snapshot NAME."""
    folder = _folder(base, name)
    if folder.exists() and not force:
        raise RuntimeErrorWithHint(f"snapshot '{name}' already exists ({folder})", "Use --force to replace it.")
    staging = folder.with_name(f".{name}.saving")
    shutil.rmtree(staging, ignore_errors=True)
    staging.mkdir(parents=True)
    try:
        data, notes = seeding.export(c.port, set(seedlib.SECTIONS), staging / "files", staging, not no_secrets)
        text = (
            f"# awsemu snapshot '{name}', saved from port {c.port} on "
            f"{dt.datetime.now().strftime('%Y-%m-%d %H:%M')}.\n"
            f"# Restore it with: awsemu snapshot restore {name}\n"
        ) + seedlib.dump(data)
        (staging / "seed.yaml").write_text(text, encoding="utf-8")
        counts = {k: len(v) for k, v in data.items() if isinstance(v, list)}
        secrets = bool(data.get("secrets")) or any(p.get("type") == "SecureString" for p in data.get("parameters", []))
        meta = {
            "name": name,
            "created_at": dt.datetime.now(dt.UTC).isoformat(timespec="seconds"),
            "port": c.port,
            "emulator_version": _installed_version(),
            "awsemu_version": __version__,
            "counts": counts,
            "secrets": secrets,
            "notes": notes,
        }
        (staging / "snapshot.json").write_text(json.dumps(meta, indent=2), encoding="utf-8")
        seedlib.load_file(staging / "seed.yaml")  # it must apply later: check it now
        if folder.exists():
            shutil.rmtree(folder)
        staging.rename(folder)
    except BaseException:
        shutil.rmtree(staging, ignore_errors=True)
        raise
    for note in notes:
        ui.warn(note)
    summary = ", ".join(f"{n} {k}" for k, n in counts.items()) or "nothing (the emulator is empty)"
    ui.success(f"Saved snapshot '{name}': {summary}")
    ui.echo(str(folder), "muted")
    if secrets:
        ui.warn("it contains secret values in plain text (--no-secrets leaves them out)")


@snapshot.command()
@click.argument("name")
@_dir_option
@click.option(
    "--no-reset", is_flag=True, help="Apply it on top of what's there instead of emptying the emulator first."
)
@pass_ctx
@click.pass_context
@handle_errors
def restore(ctx, c: Ctx, name: str, base: Path | None, no_reset: bool):
    """Empty the emulator (a restart) and recreate snapshot NAME."""
    from .seed import load_or_fail, run_apply

    folder = _folder(base, name)
    if not (folder / "seed.yaml").is_file():
        raise RuntimeErrorWithHint(f"no snapshot '{name}' in {folder.parent}", "List them with: awsemu snapshot ls")
    meta = _meta(folder)
    saved_with, now = meta.get("emulator_version"), _installed_version()
    if saved_with and now and saved_with != now:
        ui.warn(f"saved with emulator {saved_with}, restoring into {now}: behaviour may differ")
    if no_reset:
        run_apply(load_or_fail(str(folder / "seed.yaml")), c.port)
        return
    from .lifecycle import restart

    ctx.invoke(restart, seed_file=str(folder / "seed.yaml"))


@snapshot.command(name="ls")
@_dir_option
@json_option
@handle_errors
def ls(base: Path | None, as_json: bool):
    """List the saved snapshots."""
    root = base or default_dir()
    folders = sorted(p for p in root.iterdir() if (p / "seed.yaml").is_file()) if root.is_dir() else []
    rows = []
    for folder in folders:
        meta = _meta(folder)
        rows.append(
            {
                "name": folder.name,
                "created_at": meta.get("created_at"),
                "port": meta.get("port"),
                "emulator_version": meta.get("emulator_version"),
                "counts": meta.get("counts", {}),
                "secrets": meta.get("secrets"),
                "path": str(folder),
            }
        )
    if as_json:
        ui.print_json(rows)
        return
    if not rows:
        ui.echo(f"No snapshots in {root}. Save one with: awsemu snapshot save NAME", "muted")
        return
    ui.table(
        ["name", "saved", "emulator", "contents"],
        [
            [
                r["name"],
                (r["created_at"] or "")[:16].replace("T", " "),
                r["emulator_version"] or "-",
                ", ".join(f"{n} {k}" for k, n in r["counts"].items()) or "empty",
            ]
            for r in rows
        ],
    )


@snapshot.command(name="rm")
@click.argument("name")
@_dir_option
@yes_option
@handle_errors
def rm(name: str, base: Path | None, yes: bool):
    """Delete snapshot NAME."""
    folder = _folder(base, name)
    if not (folder / "seed.yaml").is_file():
        raise RuntimeErrorWithHint(f"no snapshot '{name}' in {folder.parent}", "List them with: awsemu snapshot ls")
    if not yes and not click.confirm(f"Delete snapshot '{name}'?", default=False):
        sys.exit(exitcodes.FAILED)
    shutil.rmtree(folder)
    ui.success(f"Deleted snapshot '{name}'.")
