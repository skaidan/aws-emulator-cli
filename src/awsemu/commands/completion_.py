"""``awsemu completion``: shell completion scripts."""

from __future__ import annotations

import click

from .. import envvars


@click.command()
@click.argument("shell", type=click.Choice(["bash", "zsh", "fish"]), required=False)
def completion(shell: str | None):
    """Print the shell completion script (commands, options and resource names).

    \b
      bash:  echo 'eval "$(awsemu completion bash)"' >> ~/.bashrc
      zsh:   echo 'eval "$(awsemu completion zsh)"' >> ~/.zshrc
      fish:  awsemu completion fish > ~/.config/fish/completions/awsemu.fish

    Bucket, queue, table, topic, function, secret, parameter, stream, state
    machine and rule names are completed from the running emulator.
    """
    from ..cli import cli
    from ..completion import script

    shell = shell or envvars.detect_shell()
    if shell not in ("bash", "zsh", "fish"):
        raise click.UsageError(f"completion isn't available for {shell}; use bash, zsh or fish")
    click.echo(script(cli, shell))
