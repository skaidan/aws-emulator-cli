"""``awsemu image``: build the Docker image."""

from __future__ import annotations

import sys

import click

from .. import runtime, ui
from ..context import handle_errors
from ._common import AliasedGroup


@click.group(cls=AliasedGroup)
def image():
    """Build the Docker image (AWS doesn't publish a prebuilt one)."""


@image.command(name="build")
@click.option("--tag", default=runtime.DEFAULT_IMAGE, show_default=True, help="Image name to build.")
@click.option(
    "--arch",
    type=click.Choice(["x86_64", "aarch64"]),
    default=None,
    help="Package architecture (default: this machine's).",
)
@click.option(
    "--version",
    "version",
    metavar="VERSION",
    help="Emulator version to put in the image (default: latest). See 'awsemu install --docker'.",
)
@handle_errors
def image_build(tag: str, arch: str | None, version: str | None):
    """Build the image from the official Dockerfile recipe."""
    from .. import install as inst

    if not runtime.docker_available():
        raise runtime.RuntimeErrorWithHint("Docker not found on PATH.")
    arch = arch or runtime.detect_arch()
    version = inst.normalize(version)
    ui.info(f"Building '{tag}' with the {arch} package{f' {version}' if version else ''}…")
    code = runtime.build_image(tag, arch, version)
    if code == 0:
        ui.success(f"Image '{tag}' is ready. Start it with 'awsemu start --docker'.")
    sys.exit(code)


@image.command(name="dockerfile")
@click.option(
    "--arch",
    type=click.Choice(["x86_64", "aarch64"]),
    default=None,
    help="Package architecture (default: this machine's).",
)
@click.option("--version", "version", metavar="VERSION", help="Emulator version (default: latest).")
@handle_errors
def image_dockerfile(arch: str | None, version: str | None):
    """Print the Dockerfile awsemu builds from."""
    from .. import install as inst

    click.echo(runtime.dockerfile(arch, inst.normalize(version)), nl=False)
