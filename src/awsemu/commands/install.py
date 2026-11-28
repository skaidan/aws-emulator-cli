"""``awsemu install``: install (and pin) a given AWS Emulator version."""

from __future__ import annotations

import sys

import click

from .. import exitcodes
from .. import fidelity as fid
from .. import install as inst
from .. import project, runtime, ui
from ..context import handle_errors, json_option, yes_option


@click.command()
@click.argument("version", required=False)
@click.option("--docker", is_flag=True, help="Build a Docker image of that version instead (macOS, Windows).")
@click.option("--native", is_flag=True, help="Install the Linux package (the default on Linux with apt or rpm).")
@click.option(
    "--pin",
    is_flag=True,
    help="Also write emulator_version to the project file (awsemu.toml), so the team and CI use it.",
)
@click.option("--list", "list_", is_flag=True, help="List the published versions, newest first.")
@click.option("--no-verify", is_flag=True, help="Don't check the package signature with gpg (not recommended).")
@click.option("--dry-run", is_flag=True, help="Show what would be downloaded and run, and stop.")
@yes_option
@json_option
@handle_errors
def install(version, docker, native, pin, list_, no_verify, dry_run, yes, as_json):
    """Install a given emulator version: the Linux package, or a Docker image.

    \b
      awsemu install --list            # published versions
      awsemu install 1.0.385 --pin     # install it and pin it for the project
      awsemu install                   # the project's pinned version, else latest
      awsemu install --docker          # image aws-emulator:<version> (macOS/Windows)

    On Linux it downloads the .deb/.rpm from downloads.aws.com, checks its
    signature against AWS's key, and installs it with apt-get or rpm (sudo).
    With a pinned emulator_version, 'awsemu start' warns when the installed
    emulator differs, and uses the image aws-emulator:<version> in Docker mode.
    """
    if docker and native:
        raise click.UsageError("--docker and --native are mutually exclusive.")
    if list_:
        found = inst.available()
        if as_json:
            ui.print_json(found.as_dict())
            return
        for v in found.versions[:30]:
            marks = [m for m, on in (("installed", v == found.installed), ("pinned", v == found.pinned)) if on]
            ui.echo(v + (f"  ({', '.join(marks)})" if marks else ""), "ok" if marks else None)
        if len(found.versions) > 30:
            ui.echo(f"… {len(found.versions) - 30} older (--json lists them all)", "muted")
        return
    if as_json:
        raise click.UsageError("--json only goes with --list")

    proj = _project()
    wanted = inst.normalize(version or (proj.emulator_version if proj else None))
    if pin and wanted is None:
        wanted = _latest_version()
    mode = "docker" if docker else "native" if native else ("native" if inst.package_kind() else "docker")

    if mode == "docker":
        if not runtime.docker_available() and not dry_run:
            raise runtime.RuntimeErrorWithHint("Docker not found on PATH.")
        tag = inst.image_tag(wanted)
        ui.kv(
            [("version", wanted or "latest"), ("image", tag), ("package", runtime.dockerfile(None, wanted).split()[3])]
        )
        if dry_run:
            return
        code = runtime.build_image(tag, None, wanted)
        if code != 0:
            sys.exit(code)
        ui.success(f"Image '{tag}' is ready.")
    else:
        plan = inst.native_plan(wanted, verify=not no_verify)
        ui.kv(plan.describe())
        if dry_run:
            return
        if not yes and not click.confirm("Install it?", default=True):
            sys.exit(exitcodes.FAILED)
        code = inst.run_native(plan)
        if code != 0:
            raise inst.InstallError(f"the package manager exited with code {code}")
        now = fid.installed_version()
        ui.success(f"AWS Emulator {now or wanted or 'latest'} is installed.")
        wanted = wanted or now

    if pin and wanted:
        path = project.set_value("emulator_version", wanted, proj.path if proj else None)
        ui.success(f'Pinned emulator_version = "{wanted}" in {path}')
    if mode == "docker" and wanted:
        ui.echo(
            f"Start it with: awsemu start --docker --image {tag}"
            if not (pin or (proj and proj.emulator_version == wanted))
            else "Start it with: awsemu start --docker",
            "muted",
        )


def _project():
    try:
        return project.load()
    except project.ProjectError:
        return None


def _latest_version() -> str:
    versions = inst.list_versions()
    if not versions:
        raise inst.InstallError("couldn't find the latest version to pin", "Pass a VERSION.")
    return versions[0]
