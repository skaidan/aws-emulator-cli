"""``awsemu config``: show and change the settings."""

from __future__ import annotations

import os

import click

from .. import config as cfg
from .. import project, settings, ui
from ..context import Ctx, handle_errors, json_option, pass_ctx
from ..paths import emulator_settings_file
from ._common import AliasedGroup


@click.group(cls=AliasedGroup)
def config():
    """Read or change the settings: awsemu's (explain) and the emulator's (config.toml)."""


@config.command(name="show")
@handle_errors
def config_show():
    """Show the emulator's settings file and this project's awsemu.toml."""
    path = emulator_settings_file()
    ui.kv([("file", f"{path}{'' if path.exists() else '  (not created yet)'}")])
    data = settings.load(path)
    if data:
        ui.print_json(data)
    env_tele = os.environ.get("EMULATOR_TELEMETRY")
    if env_tele:
        ui.echo(f"EMULATOR_TELEMETRY={env_tele} overrides the file in this shell.", "muted")
    proj = project.load()
    ui.echo()
    if proj is None:
        ui.echo("No project settings (awsemu.toml) here or above. Create one with 'awsemu init'.", "muted")
        return
    ui.kv(
        [
            (k, v)
            for k, v in (
                ("project file", proj.path),
                ("port", proj.port),
                ("mode", proj.mode),
                ("auth", proj.auth),
                ("telemetry", proj.telemetry),
                ("idle_timeout", proj.idle_timeout),
                ("seed", proj.seed),
                ("sdk", ", ".join(proj.sdk) or None),
                ("image", proj.image),
                ("memory", proj.memory),
                ("emulator_version", proj.emulator_version),
            )
            if v is not None
        ]
    )


@config.command(name="explain")
@json_option
@pass_ctx
@click.pass_context
@handle_errors
def config_explain(ctx: click.Context, c: Ctx, as_json: bool):
    """Every awsemu setting here, its value, and where it comes from.

    \b
      awsemu config explain            # port 9310  awsemu.toml, line 3
      AWSEMU_PORT=9400 awsemu config explain

    Highest first: the command line (--port), an environment variable
    (AWSEMU_PORT), the project file (awsemu.toml or [tool.awsemu]), the default.
    """
    root = ctx.find_root()
    given = root.get_parameter_source("port") == click.core.ParameterSource.COMMANDLINE
    values = list(cfg.resolve({"port": c.port} if given else None).values())
    if as_json:
        ui.print_json([v.as_dict() for v in values])
        return
    shown = [", ".join(map(str, v.value)) if isinstance(v.value, list) else v.value for v in values]
    ui.table(
        ["setting", "value", "from"],
        [
            [v.name, "-" if x in (None, "") else x, ui.styled(v.source, "muted")]
            for v, x in zip(values, shown, strict=True)
        ],
    )


@config.command(name="telemetry")
@click.argument("value", type=click.Choice(["on", "off"]), required=False)
@handle_errors
def config_telemetry(value: str | None):
    """Show or set telemetry ('awsemu config telemetry off')."""
    if value is None:
        current = settings.telemetry_enabled()
        ui.echo("telemetry: " + ("on (default)" if current is None else ("on" if current else "off")))
        return
    path = settings.set_value("telemetry", "enabled", value == "on")
    ui.success(f"telemetry {value} in {path} (applies to the next start)")


@config.command(name="path")
def config_path():
    """Print the settings file path."""
    click.echo(str(emulator_settings_file()))
