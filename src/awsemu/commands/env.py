"""Pointing tools at the emulator: env, exec, shell, aws and whoami."""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

import click

from .. import envvars, exitcodes, health, project, runtime, ui
from ..context import Ctx, handle_errors, pass_ctx, proxy_option
from ..paths import ACCOUNT_ID, InstanceFiles


@click.command()
@click.option(
    "--shell",
    "shell",
    type=click.Choice(envvars.SHELLS + ("sh", "pwsh")),
    default=None,
    help="Syntax to print (default: detected from $SHELL).",
)
@click.option(
    "--sdk",
    "extras",
    multiple=True,
    type=click.Choice(envvars.EXTRAS),
    help="Also trust the certificate for SDKs that ignore AWS_CA_BUNDLE. Repeatable.",
)
@click.option("--unset", is_flag=True, help="Print the commands that undo 'awsemu env'.")
@click.option(
    "--keep-real-creds", is_flag=True, help="Don't unset AWS_ACCESS_KEY_ID & co. (requests will then fail auth)."
)
@proxy_option
@pass_ctx
@handle_errors
def env(c: Ctx, shell: str | None, extras: tuple[str, ...], unset: bool, keep_real_creds: bool, use_proxy: bool | None):
    """Print shell commands that point the AWS CLI and SDKs at the emulator.

    \b
      eval "$(awsemu env)"                      # bash / zsh
      awsemu env --shell fish | source          # fish
      awsemu env --shell powershell | iex       # PowerShell
      awsemu env --shell dotenv > .env.emulator # for docker compose / IDEs
      eval "$(awsemu env --unset)"              # back to real AWS
    """
    shell = shell or envvars.detect_shell()
    variables = envvars.emulator_env(c.port, _sdk(extras))
    if not unset:
        variables.update(_proxy_env(c.port, use_proxy, _sdk(extras)))
    if unset:
        # NO_PROXY was yours before (awsemu only adds to it): keep it
        names = [n for n in variables if n not in ("NO_PROXY", "no_proxy")]
        names += ["NODE_EXTRA_CA_CERTS", "JAVA_TOOL_OPTIONS", "SSL_CERT_FILE"]
        click.echo(envvars.render_unset(dict.fromkeys(names), shell), nl=False)
        return
    if not InstanceFiles(c.port).exists():
        click.echo(f"# warning: no emulator is running on port {c.port} yet (start one with 'awsemu start')", err=True)
    click.echo(envvars.render(variables, shell, unset_real=not keep_real_creds), nl=False)


@click.command(name="exec", context_settings={"ignore_unknown_options": True, "allow_interspersed_args": False})
@click.argument("command", nargs=-1, required=True, type=click.UNPROCESSED)
@click.option(
    "--sdk",
    "extras",
    multiple=True,
    type=click.Choice(envvars.EXTRAS),
    help="Also trust the certificate in these SDKs (default: awsemu.toml 'sdk'). Repeatable.",
)
@proxy_option
@pass_ctx
@handle_errors
def exec_cmd(c: Ctx, command: tuple[str, ...], extras, use_proxy: bool | None):
    """Run COMMAND with the environment pointed at the emulator.

    \b
      awsemu exec -- pytest -k integration
      awsemu exec -- terraform apply
      awsemu exec --sdk node -- npm test
      awsemu exec --proxy -- pytest       # through the proxy (calls log, faults)
    """
    health.require_healthy(c.port)
    child = envvars.child_env(c.port, extras=_sdk(extras))
    child.update(_proxy_env(c.port, use_proxy, _sdk(extras)))
    try:
        code = subprocess.call(list(command), env=child)
    except FileNotFoundError as exc:
        raise runtime.RuntimeErrorWithHint(f"Command not found: {command[0]}") from exc
    sys.exit(code)


@click.command()
@click.option(
    "--sdk",
    "extras",
    multiple=True,
    type=click.Choice(envvars.EXTRAS),
    help="Also trust the certificate in these SDKs (default: awsemu.toml 'sdk'). Repeatable.",
)
@proxy_option
@pass_ctx
@handle_errors
def shell(c: Ctx, extras, use_proxy: bool | None):
    """Open a sub-shell already pointed at the emulator ('exit' to leave)."""
    health.require_healthy(c.port)
    if os.name == "nt":  # pragma: no cover
        program = [os.environ.get("COMSPEC", "powershell.exe")]
    else:
        program = [os.environ.get("SHELL", "/bin/sh")]
    child = envvars.child_env(c.port, extras=_sdk(extras))
    through = _proxy_env(c.port, use_proxy, _sdk(extras))
    child.update(through)
    child["AWSEMU_ACTIVE"] = str(c.port)
    if os.path.basename(program[0]) == "bash":
        child["PS1"] = f"(awsemu:{c.port}) " + os.environ.get("PS1", r"\u@\h:\w\$ ")
    ui.info(
        f"Sub-shell pointed at {through.get('AWS_ENDPOINT_URL', f'https://127.0.0.1:{c.port}')}"
        f"{' (the proxy)' if through else ''}. Type 'exit' to leave."
    )
    code = subprocess.call(program, env=child)
    ui.echo("Left the awsemu shell.", "muted")
    sys.exit(code)


@click.command(
    name="aws",
    context_settings={"ignore_unknown_options": True, "allow_interspersed_args": False, "help_option_names": []},
)
@click.argument("args", nargs=-1, type=click.UNPROCESSED)
@pass_ctx
@handle_errors
def aws_cmd(c: Ctx, args: tuple[str, ...]):
    """Run the AWS CLI against the emulator: 'awsemu aws s3 ls'.

    Goes through the proxy when awsemu.toml has proxy = true and it's running.
    """
    if not shutil.which("aws"):
        raise runtime.RuntimeErrorWithHint(
            "The AWS CLI ('aws') is not installed.",
            "Install AWS CLI v2: https://docs.aws.amazon.com/cli/latest/userguide/getting-started-install.html",
        )
    health.require_healthy(c.port)
    child = envvars.child_env(c.port)
    child.update(_proxy_env(c.port, None, []))
    sys.exit(subprocess.call(["aws", *args], env=child))


def _proxy_env(port: int, use_proxy: bool | None, extras) -> dict[str, str]:
    """Variables that send the SDKs to the proxy, when asked (or set up in the project)."""
    from .. import proxy as px

    if use_proxy is False:
        return {}
    state = px.running(port)
    if use_proxy is None:
        proj = project.load()
        if not (proj and proj.proxy and state):
            return {}
    if not state:
        raise runtime.RuntimeErrorWithHint(
            f"no proxy is running in front of port {port}", "Start one with: awsemu proxy start -d"
        )
    env = px.client_env(state)
    if state.get("ca") and "node" in extras:
        env["NODE_EXTRA_CA_CERTS"] = state["ca"]
    if state.get("ca") and "java" in extras:
        from ..javatrust import combined

        current = os.environ.get("JAVA_TOOL_OPTIONS", "")
        store, password = combined(port, current, also=Path(state["ca"]))
        if password:
            env["JAVA_TOOL_OPTIONS"] = envvars.java_tool_options(current, store, password)
        else:
            ui.warn(
                "Java ignores AWS_CA_BUNDLE, and without keytool awsemu can't add the proxy's certificate "
                f"to a truststore: import it yourself (keytool -importcert -file {state['ca']}) "
                "or start the proxy with --no-tls"
            )
    return env


def _sdk(extras) -> list[str]:
    """--sdk flags, or the project's 'sdk' list when none were given."""
    if extras:
        return list(extras)
    proj = project.load()
    return list(proj.sdk) if proj else []


@click.command()
@pass_ctx
@handle_errors
def whoami(c: Ctx):
    """Check that requests reach the emulator (STS GetCallerIdentity)."""
    from ..clients import client

    ident = client("sts", c.port).get_caller_identity()
    ok = ident.get("Account") == ACCOUNT_ID
    ui.kv([("account", ident.get("Account")), ("arn", ident.get("Arn")), ("user id", ident.get("UserId"))])
    if ok:
        ui.success("Talking to AWS Emulator.")
    else:
        ui.error("This doesn't look like the emulator account (000000000000)!")
        sys.exit(exitcodes.FAILED)
