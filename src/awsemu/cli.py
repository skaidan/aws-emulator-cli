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

from . import exitcodes
from . import __version__, _meta, envvars, health, logs, project, runtime, settings, ui
from .context import Ctx, handle_errors, json_option, pass_ctx, proxy_option
from .paths import ACCOUNT_ID, InstanceFiles, default_port, emulator_settings_file, known_ports

CONTEXT_SETTINGS = {"help_option_names": ["-h", "--help"], "max_content_width": 100}


class AliasedGroup(click.Group):
    """Lets users type unambiguous prefixes (``awsemu st`` -> status) and a few aliases."""

    ALIASES = {"ps": "status", "reset": "restart",
               "ddb": "dynamodb", "ls": "overview", "fn": "lambda",
               "eb": "events", "stepfunctions": "sfn", "secretsmanager": "secrets"}

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
@click.option("-p", "--port", type=int, default=default_port,
              show_default="$AWSEMU_PORT, else awsemu.toml, else 9297",
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
    try:
        project.load()
    except project.ProjectError as exc:
        ui.error(str(exc), "Fix the file, or set AWSEMU_CONFIG to another one.")
        sys.exit(exitcodes.USAGE)
    ctx.obj = Ctx(port)


# =========================================================================== lifecycle


def _pick(flag, project_value, default):
    """Command-line flag > project setting > default."""
    if flag is not None:
        return flag
    return project_value if project_value is not None else default


def _start_options(port, docker, native, auth, telemetry, idle_timeout, image, memory, extra):
    proj = project.load()
    if docker:
        mode = "docker"
    elif native:
        mode = "native"
    else:
        mode = (proj.mode if proj and proj.mode else "auto")
    return runtime.StartOptions(
        port=port, mode=mode,
        auth=_pick(auth, proj and proj.auth, True),
        telemetry=_pick(telemetry, proj and proj.telemetry, None),
        idle_timeout=_pick(idle_timeout, proj and proj.idle_timeout, None),
        image=_pick(image, proj and proj.image,
                    f"{runtime.DEFAULT_IMAGE}:{proj.emulator_version}" if proj and proj.emulator_version
                    else runtime.DEFAULT_IMAGE),
        memory=_pick(memory, proj and proj.memory, "2g"),
        extra_args=list(extra))


_start_params = [
    click.option("--docker", is_flag=True, help="Run in Docker even if the binary is installed."),
    click.option("--native", is_flag=True, help="Run the installed 'aws-emulator' binary."),
    click.option("--auth/--no-auth", default=None, show_default="auth",
                 help="Require SigV4-signed requests (emulator '-a')."),
    click.option("--telemetry/--no-telemetry", default=None,
                 help="Force telemetry on/off for this run (default: emulator settings)."),
    click.option("--idle-timeout", type=click.IntRange(1, 31536000), metavar="SECONDS",
                 help="Stop automatically after this many seconds without API calls."),
    click.option("--image", default=None, show_default=runtime.DEFAULT_IMAGE,
                 help="Docker image to run."),
    click.option("--memory", default=None, show_default="2g", help="Docker memory limit."),
    click.option("--wait", type=float, default=30, show_default=True, metavar="SECONDS",
                 help="How long to wait for the health check."),
    click.option("-f", "--foreground", is_flag=True,
                 help="Run attached to this terminal instead of in the background."),
    click.option("--seed", "seed_file", type=click.Path(dir_okay=False), metavar="FILE",
                 help="Apply this seed file once the emulator is healthy."),
]


def start_params(fn):
    for decorator in reversed(_start_params):
        fn = decorator(fn)
    return click.argument("extra", nargs=-1, type=click.UNPROCESSED)(fn)


def pin_mismatch() -> tuple[str, str] | None:
    """``(pinned, installed)`` when the project pins another emulator version than the binary's."""
    from .fidelity import installed_version

    try:
        proj = project.load()
    except project.ProjectError:
        return None
    if not proj or not proj.emulator_version:
        return None
    installed = installed_version()
    if installed and installed != proj.emulator_version:
        return proj.emulator_version, installed
    return None


def _warn_version_pin(mode: str) -> None:
    if mode != "native":
        return
    mismatch = pin_mismatch()
    if mismatch:
        ui.warn(f"this project pins emulator {mismatch[0]}, but {mismatch[1]} is installed. "
                f"Install it with: awsemu install")


def _do_start(port, docker, native, auth, telemetry, idle_timeout, image, memory, wait,
              foreground, extra, seed_file=None, seed=None):
    if docker and native:
        raise click.UsageError("--docker and --native are mutually exclusive.")
    if seed_file and foreground:
        raise click.UsageError("--seed can't be used with --foreground.")
    if seed_file and seed is None:
        from .commands.seed import load_or_fail

        seed = load_or_fail(seed_file)  # fail before starting anything
    opts = _start_options(port, docker, native, auth, telemetry, idle_timeout, image, memory, extra)
    if foreground:
        ui.info(f"Starting AWS Emulator on https://127.0.0.1:{port} (Ctrl+C to stop)…")
        sys.exit(runtime.run_foreground(opts))

    mode = runtime.resolve_mode(opts.mode, opts.binary)
    _warn_version_pin(mode)
    where = "a free port" if port == 0 else f"port {port}"
    ui.info(f"Starting AWS Emulator ({mode}) on {where}…")
    state, status = runtime.start(opts, wait=wait)
    if not status.healthy:
        ui.error(f"The emulator did not become healthy: {status.detail}")
        if state.log:
            for line in runtime.tail(Path(state.log), 15):
                ui.echo("  " + logs.format_plain(logs.parse(line)), "muted", err=True)
        sys.exit(exitcodes.FAILED)

    port = state.port
    files = InstanceFiles(port)
    ui.success(f"AWS Emulator is up at {files.endpoint_url}")
    ui.kv([
        ("mode", state.mode),
        ("pid" if state.pid else "container", state.pid or state.container),
        ("auth", "on" if files.auth_enabled() else "off"),
        ("files", str(files.dir)),
    ])
    if seed is not None:
        from .commands.seed import run_apply

        ui.echo()
        run_apply(seed, port)
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
@click.option("--timeout", type=float, default=15, show_default=True, metavar="SECONDS",
              help="How long to wait for a clean stop.")
@pass_ctx
@handle_errors
def stop(c: Ctx, all_: bool, force: bool, timeout: float):
    """Stop the emulator (clean stop: it deletes its files and in-memory state)."""
    ports = _all_ports() if all_ else [c.port]
    if not ports:
        ui.echo("No instances found.", "muted")
    from . import proxy as px

    for port in ports:
        if px.stop(port):
            ui.echo(f"Port {port}: proxy stopped.", "muted")
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
    """Restart the emulator, which empties its state (it's all in memory).

    Alias: 'awsemu reset'. With --seed, the seed is applied to the fresh emulator.
    """
    if kwargs.get("seed_file"):
        from .commands.seed import load_or_fail

        kwargs["seed"] = load_or_fail(kwargs["seed_file"])  # validate before stopping anything
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


@cli.command()
@click.option("--seed", "seed_file", type=click.Path(dir_okay=False), metavar="FILE",
              help="Seed to apply (default: 'seed' from awsemu.toml).")
@click.option("--no-seed", is_flag=True, help="Don't apply any seed.")
@click.option("--wait", type=float, default=30, show_default=True, metavar="SECONDS",
              help="How long to wait for the health check.")
@pass_ctx
@handle_errors
def up(c: Ctx, seed_file: str | None, no_seed: bool, wait: float):
    """Make sure this project's emulator is running and seeded.

    Uses awsemu.toml (port, mode, auth, telemetry, idle_timeout, seed...).
    Starts the emulator if it isn't running; either way, applies the seed,
    which is safe to repeat.
    """
    from .commands.seed import load_or_fail, run_apply

    proj = project.load()
    if proj:
        ui.echo(f"project: {proj.path}", "muted")
    seed_path = None if no_seed else (seed_file or (str(proj.seed) if proj and proj.seed else None))
    seed = load_or_fail(seed_path) if seed_path else None
    if health.check(c.port).healthy:
        ui.success(f"AWS Emulator is already running at https://127.0.0.1:{c.port}")
        if seed is not None:
            run_apply(seed, c.port)
    else:
        _do_start(c.port, docker=False, native=False, auth=None, telemetry=None, idle_timeout=None,
                  image=None, memory=None, wait=wait, foreground=False, extra=(), seed=seed)
    if proj and proj.proxy:
        _up_proxy(c.port, proj)


def _up_proxy(port: int, proj) -> None:
    from . import proxy as px
    from .commands.proxy import default_listen

    state = px.running(port)
    if state:
        ui.success(f"Proxy already running at {state['endpoint_url']}")
        return
    state = px.start_detached(port, default_listen(port), proj.faults, bodies=proj.proxy_bodies)
    ui.success(f"Proxy started at {state['endpoint_url']}"
               + (f" with faults: {', '.join(proj.faults)}" if proj.faults else ""))


@cli.command()
@click.option("--all", "all_", is_flag=True, help="Stop every instance awsemu knows about.")
@click.pass_context
def down(ctx: click.Context, all_: bool):
    """Stop this project's emulator (same as 'awsemu stop')."""
    ctx.invoke(stop, all_=all_, force=False, timeout=15)


@cli.command()
@click.option("--seed", "seed_rel", metavar="PATH", help="Seed file to reference (default: auto-detect).")
@click.option("--force", is_flag=True, help="Overwrite an existing awsemu.toml.")
@click.pass_context
@handle_errors
def init(ctx: click.Context, seed_rel: str | None, force: bool):
    """Create awsemu.toml in this folder.

    Without '--port', picks a port from the folder name (9300-9399), so
    several projects can run their emulators side by side.
    """
    target = Path.cwd() / project.FILE_NAME
    if target.exists() and not force:
        raise runtime.RuntimeErrorWithHint(f"{target} already exists.", "Use --force to overwrite it.")
    parent = ctx.parent
    if parent is not None and parent.get_parameter_source("port") == click.core.ParameterSource.DEFAULT:
        port = 9300 + sum(Path.cwd().name.encode()) % 100
    else:
        port = ctx.find_object(Ctx).port
    if seed_rel is None:
        for candidate in ("tests/seed.yaml", "seed.yaml", "awsemu-seed.yaml"):
            if (Path.cwd() / candidate).is_file():
                seed_rel = candidate
                break
    target.write_text(project.template(port, seed_rel), encoding="utf-8")
    project.clear_cache()
    ui.success(f"wrote {target.name}: port {port}" + (f", seed {seed_rel}" if seed_rel else ""))
    ui.echo("Next: 'awsemu up' to start and seed it, 'awsemu down' to stop it.", "muted")


def _all_ports() -> list[int]:
    ports = set(known_ports())
    ports.update(p for _, p in runtime.list_cli_containers())
    return sorted(p for p in ports if runtime.is_running(p) or runtime.State.load(p))


@cli.command()
@click.option("--all", "all_", is_flag=True, help="Show every known port, not just the selected one.")
@json_option
@pass_ctx
@handle_errors
def status(c: Ctx, all_: bool, as_json: bool):
    """Show whether the emulator is running and healthy."""
    ports = sorted(set(known_ports()) | {c.port}
                   | {p for _, p in runtime.list_cli_containers()}) if all_ else [c.port]
    infos = [runtime.instance_info(p) for p in ports]
    if as_json:
        ui.print_json(infos if all_ else infos[0])
        if not all_ and infos[0]["status"] != "healthy":
            sys.exit(exitcodes.NOT_HEALTHY)
        return
    rows = []
    for i in infos:
        ident = i["pid"] or i["container"] or ""
        auth = "" if i["auth"] is None else ("on" if i["auth"] else "off")
        rows.append([i["port"], ui.styled(i["status"], i["status"]), i["mode"], ident,
                     ui.human_duration(i["uptime_seconds"]), auth, i["endpoint"]])
    ui.table(["port", "status", "mode", "pid/container", "uptime", "auth", "endpoint"], rows)
    for i in infos:
        if i["status"] != "healthy" and i["detail"] and i["status"] != "stopped":
            ui.warn(f"port {i['port']}: {i['detail']}")
    if not all_ and infos[0]["status"] != "healthy":
        sys.exit(exitcodes.NOT_HEALTHY)


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
@proxy_option
@pass_ctx
@handle_errors
def env(c: Ctx, shell: str | None, extras: tuple[str, ...], unset: bool, keep_real_creds: bool,
        use_proxy: bool | None):
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
        click.echo(f"# warning: no emulator is running on port {c.port} yet "
                   "(start one with 'awsemu start')", err=True)
    click.echo(envvars.render(variables, shell, unset_real=not keep_real_creds), nl=False)


@cli.command(name="exec", context_settings={"ignore_unknown_options": True,
                                             "allow_interspersed_args": False})
@click.argument("command", nargs=-1, required=True, type=click.UNPROCESSED)
@click.option("--sdk", "extras", multiple=True, type=click.Choice(envvars.EXTRAS),
              help="Also trust the certificate in these SDKs (default: awsemu.toml 'sdk'). Repeatable.")
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
    _require_healthy(c.port)
    child = envvars.child_env(c.port, extras=_sdk(extras))
    child.update(_proxy_env(c.port, use_proxy, _sdk(extras)))
    try:
        code = subprocess.call(list(command), env=child)
    except FileNotFoundError:
        raise runtime.RuntimeErrorWithHint(f"Command not found: {command[0]}")
    sys.exit(code)


@cli.command()
@click.option("--sdk", "extras", multiple=True, type=click.Choice(envvars.EXTRAS),
              help="Also trust the certificate in these SDKs (default: awsemu.toml 'sdk'). Repeatable.")
@proxy_option
@pass_ctx
@handle_errors
def shell(c: Ctx, extras, use_proxy: bool | None):
    """Open a sub-shell already pointed at the emulator ('exit' to leave)."""
    _require_healthy(c.port)
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
    ui.info(f"Sub-shell pointed at {through.get('AWS_ENDPOINT_URL', f'https://127.0.0.1:{c.port}')}"
            f"{' (the proxy)' if through else ''}. Type 'exit' to leave.")
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
    """Run the AWS CLI against the emulator: 'awsemu aws s3 ls'.

    Goes through the proxy when awsemu.toml has proxy = true and it's running.
    """
    if not shutil.which("aws"):
        raise runtime.RuntimeErrorWithHint(
            "The AWS CLI ('aws') is not installed.",
            "Install AWS CLI v2: https://docs.aws.amazon.com/cli/latest/userguide/getting-started-install.html")
    _require_healthy(c.port)
    child = envvars.child_env(c.port)
    child.update(_proxy_env(c.port, None, []))
    sys.exit(subprocess.call(["aws", *args], env=child))


def _proxy_env(port: int, use_proxy: bool | None, extras) -> dict[str, str]:
    """Variables that send the SDKs to the proxy, when asked (or set up in the project)."""
    from . import proxy as px

    if use_proxy is False:
        return {}
    state = px.running(port)
    if use_proxy is None:
        proj = project.load()
        if not (proj and proj.proxy and state):
            return {}
    if not state:
        raise runtime.RuntimeErrorWithHint(f"no proxy is running in front of port {port}",
                                           "Start one with: awsemu proxy start -d")
    env = px.client_env(state)
    if state.get("ca") and "node" in extras:
        env["NODE_EXTRA_CA_CERTS"] = state["ca"]
    if state.get("ca") and "java" in extras:
        from .javatrust import combined

        current = os.environ.get("JAVA_TOOL_OPTIONS", "")
        store, password = combined(port, current, also=Path(state["ca"]))
        if password:
            env["JAVA_TOOL_OPTIONS"] = envvars.java_tool_options(current, store, password)
        else:
            ui.warn("Java ignores AWS_CA_BUNDLE, and without keytool awsemu can't add the proxy's certificate "
                    f"to a truststore: import it yourself (keytool -importcert -file {state['ca']}) "
                    "or start the proxy with --no-tls")
    return env


def _sdk(extras) -> list[str]:
    """--sdk flags, or the project's 'sdk' list when none were given."""
    if extras:
        return list(extras)
    proj = project.load()
    return list(proj.sdk) if proj else []


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
        sys.exit(exitcodes.FAILED)


# =========================================================================== setup & diagnostics


@cli.command()
@json_option
@pass_ctx
def doctor(c: Ctx, as_json: bool):
    """Check your setup and explain how to fix what's missing.

    Exits with 1 if something required is missing (warnings don't count).
    """
    rows = []
    checks = []
    problems = 0

    def add(name, ok, detail, fix=None, warn_only=False):
        nonlocal problems
        if ok is True:
            result = "ok"
        elif warn_only or ok is None:
            result = "warn"
        else:
            result = "fail"
            problems += 1
        checks.append({"check": name, "result": result, "detail": detail,
                       "fix": fix if result != "ok" else None})
        mark = ui.styled(result, {"ok": "ok", "warn": "warn", "fail": "error"}[result])
        sep = "\n→ " if ui.rich_enabled() else "  → "
        rows.append([name, mark, detail + (f"{sep}{fix}" if fix and ok is not True else "")])

    add("python", sys.version_info >= (3, 10), platform.python_version())

    proj = project.load()
    add("project", True, str(proj.path) if proj else "none (no awsemu.toml here or above)")

    binary = runtime.binary_command(runtime.default_binary())
    if binary:
        out = _run_quiet([*binary, "-v"])
        shown = " ".join(binary)
        add("aws-emulator", True, f"{shown}  {out.splitlines()[0] if out else ''}".strip())
    else:
        add("aws-emulator", None, "binary not on PATH",
            "Linux: awsemu install (or the .rpm/.deb package); macOS/Windows: use Docker")

    pinned = proj.emulator_version if proj else None
    if pinned and binary:
        mismatch = pin_mismatch()
        add("emulator version", None if mismatch else True,
            f"project pins {pinned}, installed {mismatch[1]}" if mismatch else f"{pinned}, as pinned",
            f"awsemu install {pinned}")

    if runtime.docker_available():
        image_name = proj.image if proj and proj.image else (
            f"{runtime.DEFAULT_IMAGE}:{pinned}" if pinned else runtime.DEFAULT_IMAGE)
        has_image = runtime.docker_image_exists(image_name)
        add("docker", True, "found")
        add("docker image", has_image or None,
            f"'{image_name}' {'found' if has_image else 'not built'}",
            f"awsemu install --docker{f' {pinned}' if pinned else ''}")
    else:
        add("docker", None, "not found", "only needed if you don't use the native binary")

    if not binary and not runtime.docker_available():
        add("emulator runtime", False, "neither the aws-emulator binary nor Docker is available",
            "install the Linux package, set AWSEMU_BINARY, or install Docker")

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
    if endpoint and not any(h in endpoint for h in ("127.0.0.1", "localhost", "[::1]")):
        add("endpoint", None, f"AWS_ENDPOINT_URL={endpoint}", "not the emulator: unset it, or use awsemu exec")

    from . import traps

    for finding in traps.all_findings(c.port):
        add(finding.check, None, finding.detail, finding.fix)

    tele = settings.telemetry_enabled()
    env_tele = os.environ.get("EMULATOR_TELEMETRY")
    detail = f"EMULATOR_TELEMETRY={env_tele}" if env_tele else (
        "default (on)" if tele is None else ("on" if tele else "off") + f" in {emulator_settings_file()}")
    add("telemetry", True, detail)

    if as_json:
        ui.print_json({"ok": problems == 0, "problems": problems, "checks": checks})
        if problems:
            sys.exit(exitcodes.FAILED)
        return
    ui.table(["check", "result", "detail"], rows)
    if problems:
        ui.error(f"{problems} problem(s) found.")
        sys.exit(exitcodes.FAILED)
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
@click.option("--tag", default=runtime.DEFAULT_IMAGE, show_default=True, help="Image name to build.")
@click.option("--arch", type=click.Choice(["x86_64", "aarch64"]), default=None,
              help="Package architecture (default: this machine's).")
@click.option("--version", "version", metavar="VERSION",
              help="Emulator version to put in the image (default: latest). See 'awsemu install --docker'.")
@handle_errors
def image_build(tag: str, arch: str | None, version: str | None):
    """Build the image from the official Dockerfile recipe."""
    from . import install as inst

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
@click.option("--arch", type=click.Choice(["x86_64", "aarch64"]), default=None,
              help="Package architecture (default: this machine's).")
@click.option("--version", "version", metavar="VERSION", help="Emulator version (default: latest).")
@handle_errors
def image_dockerfile(arch: str | None, version: str | None):
    """Print the Dockerfile awsemu builds from."""
    from . import install as inst

    click.echo(runtime.dockerfile(arch, inst.normalize(version)), nl=False)


@cli.group(cls=AliasedGroup)
def config():
    """Read or change the emulator's settings file (config.toml)."""


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
    ui.kv([(k, v) for k, v in (
        ("project file", proj.path), ("port", proj.port), ("mode", proj.mode), ("auth", proj.auth),
        ("telemetry", proj.telemetry), ("idle_timeout", proj.idle_timeout), ("seed", proj.seed),
        ("sdk", ", ".join(proj.sdk) or None), ("image", proj.image), ("memory", proj.memory),
        ("emulator_version", proj.emulator_version),
    ) if v is not None])


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

from .commands import call as _call  # noqa: E402
from .commands import check as _check  # noqa: E402
from .commands import compose as _compose  # noqa: E402
from .commands import describe as _describe  # noqa: E402
from .commands import dynamodb as _dynamodb  # noqa: E402
from .commands import events as _events  # noqa: E402
from .commands import explain as _explain  # noqa: E402
from .commands import fidelity as _fidelity  # noqa: E402
from .commands import iam as _iam  # noqa: E402
from .commands import install as _install  # noqa: E402
from .commands import issues as _issues  # noqa: E402
from .commands import proxy as _proxy  # noqa: E402
from .commands import report as _report  # noqa: E402
from .commands import snapshot as _snapshot  # noqa: E402
from .commands import kinesis as _kinesis  # noqa: E402
from .commands import mcp as _mcp  # noqa: E402
from .commands import overview as _overview  # noqa: E402
from .commands import lambda_ as _lambda  # noqa: E402
from .commands import s3 as _s3  # noqa: E402
from .commands import secrets as _secrets  # noqa: E402
from .commands import seed as _seed  # noqa: E402
from .commands import sfn as _sfn  # noqa: E402
from .commands import sns as _sns  # noqa: E402
from .commands import sqs as _sqs  # noqa: E402
from .commands import watch as _watch  # noqa: E402

cli.add_command(_overview.overview)
cli.add_command(_s3.s3)
cli.add_command(_sqs.sqs)
cli.add_command(_dynamodb.dynamodb)
cli.add_command(_sns.sns)
cli.add_command(_lambda.lambda_)
cli.add_command(_secrets.secrets)
cli.add_command(_secrets.ssm)
cli.add_command(_events.events)
cli.add_command(_kinesis.kinesis)
cli.add_command(_sfn.sfn)
cli.add_command(_describe.describe)
cli.add_command(_call.call)
cli.add_command(_seed.seed)
cli.add_command(_compose.compose)
cli.add_command(_fidelity.fidelity)
cli.add_command(_check.check)
cli.add_command(_install.install)
cli.add_command(_issues.issues)
cli.add_command(_proxy.proxy)
cli.add_command(_report.report)
cli.add_command(_explain.explain)
cli.add_command(_mcp.mcp)
cli.add_command(_iam.iam)
cli.add_command(_snapshot.snapshot)
cli.add_command(_watch.watch)


@cli.command(name="ui")
@pass_ctx
@handle_errors
def ui_cmd(c: Ctx):
    """Browse the emulator in the terminal: services, resources and their details.

    Keys: arrows/enter to navigate, r refresh, w auto-refresh, q quit.
    Needs the 'ui' extra (Textual); if it's missing, this command says how to install it.
    """
    try:
        from . import tui
    except ImportError as exc:
        raise runtime.RuntimeErrorWithHint(
            "The terminal UI needs Textual, which isn't installed.",
            f"{_meta.install_hint('ui')}  (or: pip install textual)") from exc
    _require_healthy(c.port)
    tui.run(c.port)


@cli.command()
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
    from .completion import script

    shell = shell or envvars.detect_shell()
    if shell not in ("bash", "zsh", "fish"):
        raise click.UsageError(f"completion isn't available for {shell}; use bash, zsh or fish")
    click.echo(script(cli, shell))


def main() -> None:
    cli(prog_name="awsemu")


if __name__ == "__main__":  # pragma: no cover
    main()

