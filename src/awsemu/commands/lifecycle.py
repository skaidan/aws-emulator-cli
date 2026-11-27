"""Lifecycle: start, stop, restart, up, down, init and status."""

from __future__ import annotations

import sys
from pathlib import Path

import click

from .. import exitcodes, health, logs, project, runtime, ui
from ..context import Ctx, handle_errors, json_option, pass_ctx
from ..paths import InstanceFiles, known_ports


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
        mode = proj.mode if proj and proj.mode else "auto"
    return runtime.StartOptions(
        port=port,
        mode=mode,
        auth=_pick(auth, proj and proj.auth, True),
        telemetry=_pick(telemetry, proj and proj.telemetry, None),
        idle_timeout=_pick(idle_timeout, proj and proj.idle_timeout, None),
        image=_pick(
            image,
            proj and proj.image,
            f"{runtime.DEFAULT_IMAGE}:{proj.emulator_version}"
            if proj and proj.emulator_version
            else runtime.DEFAULT_IMAGE,
        ),
        memory=_pick(memory, proj and proj.memory, "2g"),
        extra_args=list(extra),
    )


_start_params = [
    click.option("--docker", is_flag=True, help="Run in Docker even if the binary is installed."),
    click.option("--native", is_flag=True, help="Run the installed 'aws-emulator' binary."),
    click.option(
        "--auth/--no-auth", default=None, show_default="auth", help="Require SigV4-signed requests (emulator '-a')."
    ),
    click.option(
        "--telemetry/--no-telemetry",
        default=None,
        help="Force telemetry on/off for this run (default: emulator settings).",
    ),
    click.option(
        "--idle-timeout",
        type=click.IntRange(1, 31536000),
        metavar="SECONDS",
        help="Stop automatically after this many seconds without API calls.",
    ),
    click.option("--image", default=None, show_default=runtime.DEFAULT_IMAGE, help="Docker image to run."),
    click.option("--memory", default=None, show_default="2g", help="Docker memory limit."),
    click.option(
        "--wait",
        type=float,
        default=30,
        show_default=True,
        metavar="SECONDS",
        help="How long to wait for the health check.",
    ),
    click.option(
        "-f", "--foreground", is_flag=True, help="Run attached to this terminal instead of in the background."
    ),
    click.option(
        "--seed",
        "seed_file",
        type=click.Path(dir_okay=False),
        metavar="FILE",
        help="Apply this seed file once the emulator is healthy.",
    ),
]


def start_params(fn):
    for decorator in reversed(_start_params):
        fn = decorator(fn)
    return click.argument("extra", nargs=-1, type=click.UNPROCESSED)(fn)


def pin_mismatch() -> tuple[str, str] | None:
    """``(pinned, installed)`` when the project pins another emulator version than the binary's."""
    from ..fidelity import installed_version

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
        ui.warn(
            f"this project pins emulator {mismatch[0]}, but {mismatch[1]} is installed. Install it with: awsemu install"
        )


def _do_start(
    port,
    docker,
    native,
    auth,
    telemetry,
    idle_timeout,
    image,
    memory,
    wait,
    foreground,
    extra,
    seed_file=None,
    seed=None,
):
    if docker and native:
        raise click.UsageError("--docker and --native are mutually exclusive.")
    if seed_file and foreground:
        raise click.UsageError("--seed can't be used with --foreground.")
    if seed_file and seed is None:
        from ..commands.seed import load_or_fail

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
    ui.kv(
        [
            ("mode", state.mode),
            ("pid" if state.pid else "container", state.pid or state.container),
            ("auth", "on" if files.auth_enabled() else "off"),
            ("files", str(files.dir)),
        ]
    )
    if seed is not None:
        from ..commands.seed import run_apply

        ui.echo()
        run_apply(seed, port)
    ui.echo()
    flag = "" if port == project.default_port() else f" --port {port}"
    ui.echo("Next steps:", "muted")
    ui.echo(f'  eval "$(awsemu{flag} env)"   # point this shell at the emulator', "muted")
    ui.echo(f"  awsemu{flag} overview          # see what's inside", "muted")
    if state.mode == "native":
        _update_notices()


def _update_notices() -> None:
    """At most once a day, on a terminal, never in CI: newer releases (and too-old emulators)."""
    from .. import updates
    from ..fidelity import installed_version

    try:
        if updates.quiet():
            return
        installed = installed_version()
        if installed and updates.older(installed, updates.MIN_EMULATOR):
            ui.warn(
                f"this emulator ({installed}) is older than {updates.MIN_EMULATOR}, the oldest awsemu is "
                "tested with: awsemu install latest"
            )
        for line in updates.notify_once_a_day(installed):
            ui.echo(line, "info", err=True)
    except Exception:  # a notice must never break a start  # pragma: no cover
        pass


@click.command(context_settings={"ignore_unknown_options": True})
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


@click.command()
@click.option("--all", "all_", is_flag=True, help="Stop every instance awsemu knows about.")
@click.option("--force", is_flag=True, help="SIGKILL / docker kill (loses the clean shutdown).")
@click.option(
    "--timeout", type=float, default=15, show_default=True, metavar="SECONDS", help="How long to wait for a clean stop."
)
@pass_ctx
@handle_errors
def stop(c: Ctx, all_: bool, force: bool, timeout: float):
    """Stop the emulator (clean stop: it deletes its files and in-memory state)."""
    ports = _all_ports() if all_ else [c.port]
    if not ports:
        ui.echo("No instances found.", "muted")
    from .. import proxy as px

    for port in ports:
        if px.stop(port):
            ui.echo(f"Port {port}: proxy stopped.", "muted")
        result = runtime.stop(port, timeout=timeout, force=force)
        if result.startswith("not running"):
            ui.echo(f"Port {port}: {result}.", "muted")
        else:
            ui.success(f"Port {port}: {result}")


@click.command(context_settings={"ignore_unknown_options": True})
@start_params
@pass_ctx
@handle_errors
def restart(c: Ctx, **kwargs):
    """Restart the emulator, which empties its state (it's all in memory).

    Alias: 'awsemu reset'. With --seed, the seed is applied to the fresh emulator.
    """
    if kwargs.get("seed_file"):
        from ..commands.seed import load_or_fail

        kwargs["seed"] = load_or_fail(kwargs["seed_file"])  # validate before stopping anything
    state = runtime.State.load(c.port)
    if state and not (kwargs["docker"] or kwargs["native"]):
        kwargs["docker"] = state.mode == "docker"
        kwargs["native"] = state.mode == "native"
    result = runtime.stop(c.port)
    if not result.startswith("not running"):
        ui.echo(f"Stopped ({result}).", "muted")
    # Port may linger for a moment after the process exits.
    health.wait_port_closed(c.port, timeout=5.0)
    _do_start(c.port, **kwargs)


@click.command()
@click.option(
    "--seed",
    "seed_file",
    type=click.Path(dir_okay=False),
    metavar="FILE",
    help="Seed to apply (default: 'seed' from awsemu.toml).",
)
@click.option("--no-seed", is_flag=True, help="Don't apply any seed.")
@click.option(
    "--wait",
    type=float,
    default=30,
    show_default=True,
    metavar="SECONDS",
    help="How long to wait for the health check.",
)
@pass_ctx
@handle_errors
def up(c: Ctx, seed_file: str | None, no_seed: bool, wait: float):
    """Make sure this project's emulator is running and seeded.

    Uses awsemu.toml (port, mode, auth, telemetry, idle_timeout, seed...).
    Starts the emulator if it isn't running; either way, applies the seed,
    which is safe to repeat.
    """
    from ..commands.seed import load_or_fail, run_apply

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
        _do_start(
            c.port,
            docker=False,
            native=False,
            auth=None,
            telemetry=None,
            idle_timeout=None,
            image=None,
            memory=None,
            wait=wait,
            foreground=False,
            extra=(),
            seed=seed,
        )
    if proj and proj.proxy:
        _up_proxy(c.port, proj)


def _up_proxy(port: int, proj) -> None:
    from .. import proxy as px
    from ..commands.proxy import default_listen

    state = px.running(port)
    if state:
        ui.success(f"Proxy already running at {state['endpoint_url']}")
        return
    state = px.start_detached(port, default_listen(port), proj.faults, bodies=proj.proxy_bodies)
    ui.success(
        f"Proxy started at {state['endpoint_url']}" + (f" with faults: {', '.join(proj.faults)}" if proj.faults else "")
    )


@click.command()
@click.option("--all", "all_", is_flag=True, help="Stop every instance awsemu knows about.")
@click.pass_context
def down(ctx: click.Context, all_: bool):
    """Stop this project's emulator (same as 'awsemu stop')."""
    ctx.invoke(stop, all_=all_, force=False, timeout=15)


@click.command()
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
        found = ctx.find_object(Ctx)
        port = found.port if found else project.default_port()
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


@click.command()
@click.option("--all", "all_", is_flag=True, help="Show every known port, not just the selected one.")
@json_option
@pass_ctx
@handle_errors
def status(c: Ctx, all_: bool, as_json: bool):
    """Show whether the emulator is running and healthy."""
    ports = sorted(set(known_ports()) | {c.port} | {p for _, p in runtime.list_cli_containers()}) if all_ else [c.port]
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
        rows.append(
            [
                i["port"],
                ui.styled(i["status"], i["status"]),
                i["mode"],
                ident,
                ui.human_duration(i["uptime_seconds"]),
                auth,
                i["endpoint"],
            ]
        )
    ui.table(["port", "status", "mode", "pid/container", "uptime", "auth", "endpoint"], rows)
    for i in infos:
        if i["status"] != "healthy" and i["detail"] and i["status"] != "stopped":
            ui.warn(f"port {i['port']}: {i['detail']}")
    if not all_ and infos[0]["status"] != "healthy":
        sys.exit(exitcodes.NOT_HEALTHY)
