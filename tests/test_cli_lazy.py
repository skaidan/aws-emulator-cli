"""The root command loads its subcommands on demand."""

from __future__ import annotations

import subprocess
import sys

import click
import pytest
from click.testing import CliRunner

from awsemu.cli import LAZY_COMMANDS, cli
from awsemu.commands._common import AliasedGroup


@pytest.mark.parametrize("name", sorted(LAZY_COMMANDS))
def test_every_lazy_command_loads_under_its_name(name):
    ctx = click.Context(cli)
    command = cli.get_command(ctx, name)
    assert command is not None, name
    assert command.name == name


@pytest.mark.parametrize(("alias", "target"), sorted(AliasedGroup.ALIASES.items()))
def test_aliases_load_their_command(alias, target):
    assert cli.get_command(click.Context(cli), alias).name == target


def test_unambiguous_prefixes_load_their_command():
    ctx = click.Context(cli)
    assert cli.get_command(ctx, "stat").name == "status"
    assert cli.get_command(ctx, "overv").name == "overview"


def test_help_lists_every_command():
    result = CliRunner().invoke(cli, ["--help"])
    assert result.exit_code == 0
    for name in LAZY_COMMANDS:
        assert f"  {name} " in result.output, name


def test_version_imports_no_command_and_no_heavy_dependency():
    code = (
        "import sys\n"
        "from awsemu.cli import cli\n"
        "try:\n"
        "    cli(['--version'], prog_name='awsemu')\n"
        "except SystemExit:\n"
        "    pass\n"
        "heavy = ['rich', 'boto3', 'botocore', 'awsemu.ui', 'awsemu.proxy', 'awsemu.runtime', 'yaml']\n"
        "loaded = [m for m in sys.modules if m.startswith('awsemu.commands.') and m != 'awsemu.commands._common']\n"
        "loaded += [m for m in heavy if m in sys.modules]\n"
        "print('loaded=' + ','.join(loaded))\n"
    )
    out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, check=True).stdout
    assert "loaded=\n" in out, out
