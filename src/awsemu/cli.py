"""``awsemu`` — a friendly CLI for AWS Emulator."""

from __future__ import annotations

import importlib
import os
import sys

import click

from . import __version__
from .commands._common import AliasedGroup
from .paths import default_port

CONTEXT_SETTINGS = {"help_option_names": ["-h", "--help"], "max_content_width": 100}

# Commands are imported only when they run (or when --help lists them), so
# ``awsemu --version`` and completion don't pay for every module.
LAZY_COMMANDS: dict[str, str] = {
    # lifecycle
    "start": "lifecycle:start",
    "stop": "lifecycle:stop",
    "restart": "lifecycle:restart",
    "up": "lifecycle:up",
    "down": "lifecycle:down",
    "init": "lifecycle:init",
    "status": "lifecycle:status",
    "logs": "logs_:logs_cmd",
    # environment
    "env": "env:env",
    "exec": "env:exec_cmd",
    "shell": "env:shell",
    "aws": "env:aws_cmd",
    "whoami": "env:whoami",
    # setup & diagnostics
    "doctor": "doctor:doctor",
    "image": "image:image",
    "config": "config:config",
    "install": "install:install",
    "completion": "completion_:completion",
    # services
    "overview": "overview:overview",
    "s3": "s3:s3",
    "sqs": "sqs:sqs",
    "dynamodb": "dynamodb:dynamodb",
    "sns": "sns:sns",
    "lambda": "lambda_:lambda_",
    "secrets": "secrets:secrets",
    "ssm": "secrets:ssm",
    "events": "events:events",
    "kinesis": "kinesis:kinesis",
    "sfn": "sfn:sfn",
    "describe": "describe:describe",
    "call": "call:call",
    "ui": "ui:ui_cmd",
    "watch": "watch:watch",
    # state
    "seed": "seed:seed",
    "snapshot": "snapshot:snapshot",
    "compose": "compose:compose",
    # will it work, and the proxy
    "fidelity": "fidelity:fidelity",
    "check": "check:check",
    "issues": "issues:issues",
    "proxy": "proxy:proxy",
    "report": "report:report",
    "explain": "explain:explain",
    "iam": "iam:iam",
    "mcp": "mcp:mcp",
}


class LazyGroup(AliasedGroup):
    """The root group: knows its commands by name and imports each one on first use."""

    def list_commands(self, ctx):
        return sorted({*self.commands, *LAZY_COMMANDS})

    def lookup(self, ctx, cmd_name):
        if cmd_name not in self.commands and cmd_name in LAZY_COMMANDS:
            module, _, attr = LAZY_COMMANDS[cmd_name].partition(":")
            command = getattr(importlib.import_module(f".commands.{module}", __package__), attr)
            self.add_command(command, cmd_name)
        return super().lookup(ctx, cmd_name)


@click.group(cls=LazyGroup, context_settings=CONTEXT_SETTINGS)
@click.option(
    "-p",
    "--port",
    type=int,
    default=default_port,
    show_default="$AWSEMU_PORT, else awsemu.toml, else 9297",
    help="Port of the emulator instance to work with.",
)
@click.option("--plain", is_flag=True, envvar="AWSEMU_PLAIN", help="Plain text output (no colours or boxes).")
@click.version_option(__version__, "-V", "--version", prog_name="awsemu")
@click.pass_context
def cli(ctx: click.Context, port: int, plain: bool):
    """A friendly CLI for AWS Emulator (https://github.com/aws/aws-emulator).

    \b
    Quick start:
      awsemu start                 # start in the background (binary or Docker)
      eval "$(awsemu env)"         # point this shell's AWS CLI/SDKs at it
      awsemu overview              # see what's inside
      awsemu stop
    """
    # Imported here, not at the top, so `awsemu --version` and `--help` stay fast.
    from . import exitcodes, project, ui
    from .context import Ctx

    if plain or os.environ.get("NO_COLOR"):
        ui.set_plain(True)
    try:
        project.load()
    except project.ProjectError as exc:
        ui.error(str(exc), "Fix the file, or set AWSEMU_CONFIG to another one.")
        sys.exit(exitcodes.USAGE)
    ctx.obj = Ctx(port)


def main() -> None:
    cli(prog_name="awsemu")


if __name__ == "__main__":  # pragma: no cover
    main()
