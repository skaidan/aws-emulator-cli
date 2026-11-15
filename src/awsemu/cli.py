"""``awsemu`` — a friendly CLI for AWS Emulator."""

from __future__ import annotations

import os
import platform
import shutil
import subprocess
import sys
import time
from pathlib import Path

import click

from . import __version__, envvars, health, logs, runtime, settings, ui
from .context import Ctx, handle_errors, pass_ctx
from .paths import ACCOUNT_ID, InstanceFiles, default_port, emulator_settings_file, known_ports

CONTEXT_SETTINGS = {"help_option_names": ["-h", "--help"], "max_content_width": 100}


class AliasedGroup(click.Group):
    """Lets users type unambiguous prefixes (``awsemu st`` -> status) and a few aliases."""

    ALIASES = {"ps": "status", "up": "start", "down": "stop", "reset": "restart",
               "ddb": "dynamodb", "ls": "overview"}

    def get_command(self, ctx, cmd_name):
        cmd_name = self.ALIASES.get(cmd_name, cmd_name)
        rv = super().get_command(ctx, cmd_name)
        if rv is not None:
            return rv
        matches = [n for n in self.list_commands(ctx) if n.startswith(cmd_name)]
        if len(matches) == 1:
            return super().get_command(ctx, matches[0])
        if len(matches) > 1:
            ctx.fail(f"'{cmd_name}' is ambiguous: {', '.join(sorted(matches))}")
        return None

    def resolve_command(self, ctx, args):
        _, cmd, args = super().resolve_command(ctx, args)
        return cmd.name if cmd else None, cmd, args


@click.group(cls=AliasedGroup, context_settings=CONTEXT_SETTINGS)
@click.option("-p", "--port", type=int, default=default_port, show_default="9297 or $AWSEMU_PORT",
              help="Port of the emulator instance to work with.")
@click.option("--plain", is_flag=True, envvar="AWSEMU_PLAIN",
              help="Plain text output (no colours or boxes).")
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
    if plain or os.environ.get("NO_COLOR"):
        ui.set_plain(True)
    ctx.obj = Ctx(port)


# =========================================================================== lifecycle


def _start_options(port, docker, native, auth, telemetry, idle_timeout, image, memory, extra):
    mode = "docker" if docker else "native" if native else "auto"
    return runtime.StartOptions(port=port, mode=mode, auth=auth, telemetry=telemetry,
                                idle_timeout=idle_timeout, image=image, memory=memory,
                                extra_args=list(extra))


_start_params = [
    click.option("--docker", is_flag=True, help="Run in Docker even if the binary is installed."),
    click.option("--native", is_flag=True, help="Run the installed 'aws-emulator' binary."),
    click.option("--auth/--no-auth", default=True, show_default=True,
                 help="Require SigV4-signed requests (emulator '-a')."),
    click.option("--telemetry/--no-telemetry", default=None,
                 help="Force telemetry on/off for this run (default: emulator settings)."),
    click.option("--idle-timeout", type=click.IntRange(1, 31536000), metavar="SECONDS",
                 help="Stop automatically after this many seconds without API calls."),
    click.option("--image", default=runtime.DEFAULT_IMAGE, show_default=True,
                 help="Docker image to run."),
    click.option("--memory", default="2g", show_default=True, help="Docker memory limit."),
    click.option("--wait", type=float, default=30, show_default=True, metavar="SECONDS",
                 help="How long to wait for the health check."),
    click.option("-f", "--foreground", is_flag=True,
                 help="Run attached to this terminal instead of in the background."),
]


def start_params(fn):
    for decorator in reversed(_start_params):
        fn = decorator(fn)
    return click.argument("extra", nargs=-1, type=click.UNPROCESSED)(fn)


def _do_start(port, docker, native, auth, telemetry, idle_timeout, image, memory, wait,
              foreground, extra):
    if docker and native:
        raise click.UsageError("--docker and --native are mutually exclusive.")
    opts = _start_options(port, docker, native, auth, telemetry, idle_timeout, image, memory, extra)
    if foreground:
        ui.info(f"Starting AWS Emulator on https://127.0.0.1:{port} (Ctrl+C to stop)…")
        sys.exit(runtime.run_foreground(opts))

    mode = runtime.resolve_mode(opts.mode, opts.binary)
    where = "a free port" if port == 0 else f"port {port}"
    ui.info(f"Starting AWS Emulator ({mode}) on {where}…")
    state, status = runtime.start(opts, wait=wait)
    if not status.healthy:
        ui.error(f"The emulator did not become healthy: {status.detail}")
        if state.log:
            for line in runtime.tail(Path(state.log), 15):
                ui.echo("  " + logs.format_plain(logs.parse(line)), "muted", err=True)
        sys.exit(1)

    port = state.port
    files = InstanceFiles(port)
    ui.success(f"AWS Emulator is up at {files.endpoint_url}")
    ui.kv([
        ("mode", state.mode),
        ("pid" if state.pid else "container", state.pid or state.container),
        ("auth", "on" if files.auth_enabled() else "off"),
        ("files", str(files.dir)),
    ])
    ui.echo()
    flag = "" if port == default_port() else f" --port {port}"
    ui.echo("Next steps:", "muted")
    ui.echo(f'  eval "$(awsemu{flag} env)"   # point this shell at the emulator', "muted")
    ui.echo(f"  awsemu{flag} overview          # see what's inside", "muted")


@cli.command(context_settings={"ignore_unknown_options": True})
@start_params
@pass_ctx
@handle_errors
def start(c: Ctx, **kwargs):
    """Start an emulator in the background and wait until it's healthy.

    Uses the 'aws-emulator' binary if it's on PATH (or $AWSEMU_BINARY),
    otherwise Docker. '--port 0' lets the OS pick a free port (native only).
    Anything after '--' is passed to the emulator as-is.
    """
    _do_start(c.port, **kwargs)


@cli.command()
@click.option("--all", "all_", is_flag=True, help="Stop every instance awsemu knows about.")
@click.option("--force", is_flag=True, help="SIGKILL / docker kill (loses the clean shutdown).")
@click.option("--timeout", type=float, default=15, show_default=True, metavar="SECONDS")
@pass_ctx
@handle_errors
def stop(c: Ctx, all_: bool, force: bool, timeout: float):
    """Stop the emulator (clean stop: it deletes its files and in-memory state)."""
    ports = _all_ports() if all_ else [c.port]
    if not ports:
        ui.echo("No instances found.", "muted")
    for port in ports:
        result = runtime.stop(port, timeout=timeout, force=force)
        if result.startswith("not running"):
            ui.echo(f"Port {port}: {result}.", "muted")
        else:
            ui.success(f"Port {port}: {result}")


@cli.command(context_settings={"ignore_unknown_options": True})
@start_params
@pass_ctx
@handle_errors
def restart(c: Ctx, **kwargs):
    """Restart the emulator. The emulator keeps state in memory, so this also resets it.

    Alias: 'awsemu reset'.
    """
    state = runtime.State.load(c.port)
    if state and not (kwargs["docker"] or kwargs["native"]):
        kwargs["docker"] = state.mode == "docker"
        kwargs["native"] = state.mode == "native"
    result = runtime.stop(c.port)
    if not result.startswith("not running"):
        ui.echo(f"Stopped ({result}).", "muted")
    # Port may linger for a moment after the process exits.
    for _ in range(25):
        if not health.port_open(c.port):
            break
        time.sleep(0.2)
    _do_start(c.port, **kwargs)


def _all_ports() -> list[int]:
    ports = set(known_ports())
    ports.update(p for _, p in runtime.list_cli_containers())
    return sorted(p for p in ports if runtime.is_running(p) or runtime.State.load(p))


@cli.command()
@click.option("--all", "all_", is_flag=True, help="Show every known port, not just the selected one.")
@click.option("--json", "as_json", is_flag=True, help="Machine-readable output.")
@pass_ctx
@handle_errors
def status(c: Ctx, all_: bool, as_json: bool):
    """Show whether the emulator is running and healthy."""
    ports = sorted(set(known_ports()) | {c.port}
                   | {p for _, p in runtime.list_cli_containers()}) if all_ else [c.port]
    infos = [runtime.instance_info(p) for p in ports]
    if as_json:
        ui.print_json(infos if all_ else infos[0])
        return
    rows = []
    for i in infos:
        ident = i["pid"] or i["container"] or ""
        auth = "" if i["auth"] is None else ("on" if i["auth"] else "off")
        rows.append([i["port"], ui.styled(i["status"], i["status"]), i["mode"], ident,
                     ui.human_duration(i["uptime"]), auth, i["endpoint"]])
    ui.table(["port", "status", "mode", "pid/container", "uptime", "auth", "endpoint"], rows)
    for i in infos:
        if i["status"] != "healthy" and i["detail"] and i["status"] != "stopped":
            ui.warn(f"port {i['port']}: {i['detail']}")
    if not all_ and infos[0]["status"] != "healthy":
        sys.exit(3)


@cli.command(name="logs")
@click.option("-f", "--follow", is_flag=True, help="Keep printing new lines.")
@click.option("-n", "--lines", type=int, default=50, show_default=True, help="Lines to show first.")
@click.option("--raw", is_flag=True, help="Print the JSON lines untouched.")
@click.option("--grep", metavar="TEXT", help="Only lines containing TEXT (case-insensitive).")
@pass_ctx
@handle_errors
def logs_cmd(c: Ctx, follow: bool, lines: int, raw: bool, grep: str | None):
    """Show the emulator's log, prettified (also after it stopped)."""
    path = runtime.log_path(c.port)
    state = runtime.State.load(c.port)
    if not path.exists():
        if state and state.mode == "docker":
            # Started by an older awsemu that didn't keep a log file.
            cmd = ["docker", "logs", "--tail", str(lines), *(["-f"] if follow else []),
                   state.container or runtime.container_name(c.port)]
            sys.exit(subprocess.call(cmd))
        raise runtime.RuntimeErrorWithHint(
            f"No log for port {c.port}: awsemu didn't start an emulator there.",
            "Start it with 'awsemu start' (or check 'awsemu status --all').")

    def emit(line: str):
        if grep and grep.lower() not in line.lower():
            return
        if raw:
            print(line.rstrip("\n"), flush=True)
        else:
            ui.log_line(logs.parse(line))

    for line in runtime.tail(path, lines):
        emit(line)
    if not follow:
        return
    if state is None:
        ui.echo("(emulator is not running)", "muted")
        return
    try:
        with path.open("r", encoding="utf-8", errors="replace") as fh:
            fh.seek(0, os.SEEK_END)
            idle = 0
            while True:
                line = fh.readline()
                if line:
                    emit(line)
                    continue
                idle += 1
                if idle % 5 == 0 and not runtime.is_running(c.port):
                    for line in fh.readlines():
                        emit(line)
                    ui.echo("(emulator stopped)", "muted")
                    return
                time.sleep(0.3)
    except KeyboardInterrupt:
        pass


# =========================================================================== environment


@cli.command()
@click.option("--shell", "shell", type=click.Choice(envvars.SHELLS + ("sh", "pwsh")),
              default=None, help="Syntax to print (default: detected from $SHELL).")
@click.option("--sdk", "extras", multiple=True, type=click.Choice(envvars.EXTRAS),
              help="Also trust the certificate for SDKs that ignore AWS_CA_BUNDLE. Repeatable.")
@click.option("--unset", is_flag=True, help="Print the commands that undo 'awsemu env'.")
@click.option("--keep-real-creds", is_flag=True,
              help="Don't unset AWS_ACCESS_KEY_ID & co. (requests will then fail auth).")
@pass_ctx
@handle_errors
def env(c: Ctx, shell: str | None, extras: tuple[str, ...], unset: bool, keep_real_creds: bool):
    """Print shell commands that point the AWS CLI and SDKs at the emulator.

    \b
      eval "$(awsemu env)"                      # bash / zsh
      awsemu env --shell fish | source          # fish
      awsemu env --shell powershell | iex       # PowerShell
      awsemu env --shell dotenv > .env.emulator # for docker compose / IDEs
      eval "$(awsemu env --unset)"              # back to real AWS
    """
    shell = shell or envvars.detect_shell()
    variables = envvars.emulator_env(c.port, extras)
    if unset:
        names = list(variables) + ["NODE_EXTRA_CA_CERTS", "JAVA_TOOL_OPTIONS", "SSL_CERT_FILE"]
        click.echo(envvars.render_unset(dict.fromkeys(names), shell), nl=False)
        return
    if not InstanceFiles(c.port).exists():
        click.echo(f"# warning: no emulator is running on port {c.port} yet "
                   "(start one with 'awsemu start')", err=True)
    click.echo(envvars.render(variables, shell, unset_real=not keep_real_creds), nl=False)


@cli.command(name="exec", context_settings={"ignore_unknown_options": True,
                                             "allow_interspersed_args": False})
@click.argument("command", nargs=-1, required=True, type=click.UNPROCESSED)
@click.option("--sdk", "extras", multiple=True, type=click.Choice(envvars.EXTRAS))
@pass_ctx
@handle_errors
def exec_cmd(c: Ctx, command: tuple[str, ...], extras):
    """Run COMMAND with the environment pointed at the emulator.

    \b
      awsemu exec -- pytest -k integration
      awsemu exec -- terraform apply
      awsemu exec --sdk node -- npm test
    """
    _require_healthy(c.port)
    try:
        code = subprocess.call(list(command), env=envvars.child_env(c.port, extras=extras))
    except FileNotFoundError:
        raise runtime.RuntimeErrorWithHint(f"Command not found: {command[0]}")
    sys.exit(code)


@cli.command()
@click.option("--sdk", "extras", multiple=True, type=click.Choice(envvars.EXTRAS))
@pass_ctx
@handle_errors
def shell(c: Ctx, extras):
    """Open a sub-shell already pointed at the emulator ('exit' to leave)."""
    _require_healthy(c.port)
    if os.name == "nt":  # pragma: no cover
        program = [os.environ.get("COMSPEC", "powershell.exe")]
    else:
        program = [os.environ.get("SHELL", "/bin/sh")]
    child = envvars.child_env(c.port, extras=extras)
    child["AWSEMU_ACTIVE"] = str(c.port)
    if os.path.basename(program[0]) == "bash":
        child["PS1"] = f"(awsemu:{c.port}) " + os.environ.get("PS1", r"\u@\h:\w\$ ")
    ui.info(f"Sub-shell pointed at https://127.0.0.1:{c.port}. Type 'exit' to leave.")
    code = subprocess.call(program, env=child)
    ui.echo("Left the awsemu shell.", "muted")
    sys.exit(code)


@cli.command(name="aws", context_settings={"ignore_unknown_options": True,
                                           "allow_interspersed_args": False,
                                           "help_option_names": []})
@click.argument("args", nargs=-1, type=click.UNPROCESSED)
@pass_ctx
@handle_errors
def aws_cmd(c: Ctx, args: tuple[str, ...]):
    """Run the AWS CLI against the emulator: 'awsemu aws s3 ls'."""
    if not shutil.which("aws"):
        raise runtime.RuntimeErrorWithHint(
            "The AWS CLI ('aws') is not installed.",
            "Install AWS CLI v2: https://docs.aws.amazon.com/cli/latest/userguide/getting-started-install.html")
    _require_healthy(c.port)
    sys.exit(subprocess.call(["aws", *args], env=envvars.child_env(c.port)))


def _require_healthy(port: int) -> None:
    h = health.check(port)
    if not h.healthy:
        flag = "" if port == default_port() else f" --port {port}"
        raise runtime.RuntimeErrorWithHint(
            f"No healthy emulator on port {port} ({h.detail}).",
            f"Start one with 'awsemu{flag} start'.")


@cli.command()
@pass_ctx
@handle_errors
def whoami(c: Ctx):
    """Check that requests reach the emulator (STS GetCallerIdentity)."""
    from .clients import client

    ident = client("sts", c.port).get_caller_identity()
    ok = ident.get("Account") == ACCOUNT_ID
    ui.kv([("account", ident.get("Account")), ("arn", ident.get("Arn")),
           ("user id", ident.get("UserId"))])
    if ok:
        ui.success("Talking to AWS Emulator.")
    else:
        ui.error("This doesn't look like the emulator account (000000000000)!")
        sys.exit(1)


# =========================================================================== setup & diagnostics


@cli.command()
@pass_ctx
def doctor(c: Ctx):
    """Check your setup and explain how to fix what's missing."""
    rows = []
    problems = 0

    def add(name, ok, detail, fix=None, warn_only=False):
        nonlocal problems
        if ok is True:
            mark = ui.styled("ok", "ok")
        elif warn_only or ok is None:
            mark = ui.styled("warn", "warn")
        else:
            mark = ui.styled("fail", "error")
            problems += 1
        sep = "\n→ " if ui.rich_enabled() else "  → "
        rows.append([name, mark, detail + (f"{sep}{fix}" if fix and ok is not True else "")])

    add("python", sys.version_info >= (3, 10), platform.python_version())

    binary = runtime.binary_command(runtime.default_binary())
    if binary:
        out = _run_quiet([*binary, "-v"])
        shown = " ".join(binary)
        add("aws-emulator", True, f"{shown}  {out.splitlines()[0] if out else ''}".strip())
    else:
        add("aws-emulator", None, "binary not on PATH",
            "Linux: install the .rpm/.deb package; macOS/Windows: use Docker")

    if runtime.docker_available():
        has_image = runtime.docker_image_exists(runtime.DEFAULT_IMAGE)
        add("docker", True, "found")
        add("docker image", has_image or None,
            f"'{runtime.DEFAULT_IMAGE}' {'found' if has_image else 'not built'}",
            "awsemu image build")
    else:
        add("docker", None, "not found", "only needed if you don't use the native binary")

    if not binary and not runtime.docker_available():
        problems += 1

    aws = shutil.which("aws")
    if aws:
        version = _run_quiet(["aws", "--version"])
        add("aws cli", True, version.split()[0] if version else aws)
    else:
        add("aws cli", None, "not found", "optional; needed for 'awsemu aws ...'")

    try:
        import boto3  # noqa: F401

        add("boto3", True, getattr(boto3, "__version__", "installed"))
    except ImportError:
        add("boto3", False, "not installed", "pip install boto3")

    add("rich", ui.HAVE_RICH or None, "installed" if ui.HAVE_RICH else "not installed (plain output)",
        "pip install rich")

    h = health.check(c.port)
    add(f"emulator :{c.port}", h.healthy or None, h.detail,
        None if h.healthy else f"awsemu --port {c.port} start")

    real = [v for v in envvars.REAL_CREDENTIAL_VARS if os.environ.get(v)]
    if real:
        add("shell creds", None, f"{', '.join(real)} set in this shell",
            "awsemu env/exec/aws unset them for you; your own scripts must too")

    endpoint = os.environ.get("AWS_ENDPOINT_URL")
    if endpoint and "127.0.0.1" not in endpoint and "localhost" not in endpoint:
        add("endpoint", None, f"AWS_ENDPOINT_URL={endpoint}")
    elif endpoint and "localhost" in endpoint:
        add("endpoint", None, "AWS_ENDPOINT_URL uses 'localhost'",
            "use 127.0.0.1 so S3 SDKs use path-style requests")

    tele = settings.telemetry_enabled()
    env_tele = os.environ.get("EMULATOR_TELEMETRY")
    detail = f"EMULATOR_TELEMETRY={env_tele}" if env_tele else (
        "default (on)" if tele is None else ("on" if tele else "off") + f" in {emulator_settings_file()}")
    add("telemetry", True, detail)

    ui.table(["check", "result", "detail"], rows)
    if problems:
        ui.error(f"{problems} problem(s) found.")
        sys.exit(1)
    ui.success("Looks good.")


def _run_quiet(cmd: list[str]) -> str:
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
        return result.stdout.strip() or result.stderr.strip()
    except (OSError, subprocess.TimeoutExpired):
        return ""


@cli.group(cls=AliasedGroup)
def image():
    """Build the Docker image (AWS doesn't publish a prebuilt one)."""


@image.command(name="build")
@click.option("--tag", default=runtime.DEFAULT_IMAGE, show_default=True)
@click.option("--arch", type=click.Choice(["x86_64", "aarch64"]), default=None,
              help="Package architecture (default: this machine's).")
@handle_errors
def image_build(tag: str, arch: str | None):
    """Build the image from the official Dockerfile recipe."""
    if not runtime.docker_available():
        raise runtime.RuntimeErrorWithHint("Docker not found on PATH.")
    arch = arch or runtime.detect_arch()
    ui.info(f"Building '{tag}' with the {arch} package…")
    code = runtime.build_image(tag, arch)
    if code == 0:
        ui.success(f"Image '{tag}' is ready. Start it with 'awsemu start --docker'.")
    sys.exit(code)


@image.command(name="dockerfile")
@click.option("--arch", type=click.Choice(["x86_64", "aarch64"]), default=None)
def image_dockerfile(arch: str | None):
    """Print the Dockerfile awsemu builds from."""
    click.echo(runtime.dockerfile(arch), nl=False)


@cli.group(cls=AliasedGroup)
def config():
    """Read or change the emulator's settings file (config.toml)."""


@config.command(name="show")
@handle_errors
def config_show():
    """Show the settings file and effective telemetry setting."""
    path = emulator_settings_file()
    ui.kv([("file", f"{path}{'' if path.exists() else '  (not created yet)'}")])
    data = settings.load(path)
    if data:
        ui.print_json(data)
    env_tele = os.environ.get("EMULATOR_TELEMETRY")
    if env_tele:
        ui.echo(f"EMULATOR_TELEMETRY={env_tele} overrides the file in this shell.", "muted")


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


# =========================================================================== services

from .commands import dynamodb as _dynamodb  # noqa: E402
from .commands import overview as _overview  # noqa: E402
from .commands import s3 as _s3  # noqa: E402
from .commands import sqs as _sqs  # noqa: E402

cli.add_command(_overview.overview)
cli.add_command(_s3.s3)
cli.add_command(_sqs.sqs)
cli.add_command(_dynamodb.dynamodb)


def main() -> None:
    cli(prog_name="awsemu")


if __name__ == "__main__":  # pragma: no cover
    main()

