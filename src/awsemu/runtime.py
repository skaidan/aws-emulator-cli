"""Start, stop and inspect AWS Emulator instances (native binary or Docker).

The emulator itself always runs in the foreground and has no subcommands, so
this module runs it in the background, remembers how (pid or container name)
and stops it cleanly: SIGTERM on Linux/macOS, Ctrl+Break on Windows. If the
emulator can't clean up after itself (forced stop, Windows), awsemu removes the
stale files it left in ``~/.aws/emulator/<port>/``.
"""

from __future__ import annotations

import json
import atexit
import os
import platform
import shlex
import shutil
import signal
import subprocess
import tempfile
import time
from dataclasses import asdict, dataclass, field
from typing import Literal
from pathlib import Path

from . import errors, health, logs, waiting
from .paths import CliFiles, InstanceFiles, cli_root, emulator_root

BINARY = "aws-emulator"
DEFAULT_IMAGE = "aws-emulator"
CONTAINER_PREFIX = "awsemu-"
PACKAGE_BASE = "https://downloads.aws.com/aws-emulator/packages/aws-emulator/LTS/latest"
IS_WINDOWS = os.name == "nt"

DOCKERFILE_TEMPLATE = """\
FROM public.ecr.aws/amazonlinux/amazonlinux:2023-minimal
ADD {package_url} /tmp/aws-emulator.rpm
RUN rpm -i /tmp/aws-emulator.rpm && rm /tmp/aws-emulator.rpm \\
    && mkdir -p /home/emulator && chown 1000 /home/emulator
USER 1000
ENV HOME=/home/emulator
EXPOSE 9297
ENTRYPOINT ["aws-emulator", "-b", "0.0.0.0"]
"""


# Defined in errors.py; imported from here by much of the code (and by users' tests).
RuntimeErrorWithHint = errors.RuntimeErrorWithHint


def default_binary() -> str:
    """The emulator command: ``$AWSEMU_BINARY`` or ``aws-emulator``.

    ``AWSEMU_BINARY`` may include arguments, e.g. ``"/opt/emu/aws-emulator"`` or
    ``"python fake_emulator.py"``.
    """
    return os.environ.get("AWSEMU_BINARY") or BINARY


@dataclass
class StartOptions:
    port: int
    mode: str = "auto"  # auto | native | docker
    auth: bool = True
    telemetry: bool | None = None  # None = leave to env/config.toml
    idle_timeout: int | None = None
    image: str = DEFAULT_IMAGE
    memory: str = "2g"
    binary: str = field(default_factory=default_binary)
    extra_args: list[str] = field(default_factory=list)


@dataclass
class State:
    port: int
    mode: str
    started_at: float
    command: list[str]
    pid: int | None = None
    container: str | None = None
    log: str | None = None

    def save(self) -> None:
        files = CliFiles(self.port)
        files.dir.mkdir(parents=True, exist_ok=True)
        files.state.write_text(json.dumps(asdict(self), indent=2), encoding="utf-8")

    @classmethod
    def load(cls, port: int) -> State | None:
        path = CliFiles(port).state
        if not path.exists():
            return None
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            return cls(**data)
        except (ValueError, TypeError):
            return None

    @staticmethod
    def clear(port: int) -> None:
        CliFiles(port).state.unlink(missing_ok=True)


# --------------------------------------------------------------------------- helpers


def split_binary(binary: str) -> list[str]:
    parts = shlex.split(binary, posix=not IS_WINDOWS)
    if IS_WINDOWS:  # shlex keeps the quotes with posix=False
        parts = [p[1:-1] if len(p) > 1 and p[0] == p[-1] == '"' else p for p in parts]
    return parts or [BINARY]


def binary_command(binary: str) -> list[str] | None:
    """Resolve ``binary`` to an argv prefix, or ``None`` if it can't be found."""
    parts = split_binary(binary)
    exe = shutil.which(parts[0])
    if exe is None:
        return None
    return [exe, *parts[1:]]


def docker_available() -> bool:
    return shutil.which("docker") is not None


def native_available(binary: str | None = None) -> bool:
    return binary_command(binary or default_binary()) is not None


def resolve_mode(mode: str, binary: str | None = None) -> str:
    if mode in ("native", "docker"):
        return mode
    if mode != "auto":
        raise ValueError(f"unknown mode: {mode}")
    if native_available(binary):
        return "native"
    if docker_available():
        return "docker"
    raise RuntimeErrorWithHint(
        "Neither the 'aws-emulator' binary nor Docker was found.",
        "Install the Linux package (https://github.com/aws/aws-emulator), set "
        "AWSEMU_BINARY, or install Docker and run 'awsemu image build'.",
    )


def container_name(port: int) -> str:
    return f"{CONTAINER_PREFIX}{port}"


def emulator_args(opts: StartOptions) -> list[str]:
    """Options shared by the native binary and the container entrypoint."""
    args = ["-p", str(opts.port)]
    if not opts.auth:
        args += ["-a", "off"]
    if opts.telemetry is not None:
        args += ["-t", "on" if opts.telemetry else "off"]
    if opts.idle_timeout:
        args += ["--idle-timeout", str(opts.idle_timeout)]
    return args + list(opts.extra_args)


def native_command(opts: StartOptions) -> list[str]:
    prefix = binary_command(opts.binary) or split_binary(opts.binary)
    return [*prefix, *emulator_args(opts)]


def docker_command(opts: StartOptions, detach: bool = True, system: str | None = None) -> list[str]:
    """``docker run`` following the official "Getting started with Docker" recipe."""
    system = system or platform.system()
    port = opts.port
    cmd = [
        "docker",
        "run",
        "--rm",
        "--name",
        container_name(port),
        f"--memory={opts.memory}",
        f"--memory-swap={opts.memory}",
        "-p",
        f"127.0.0.1:{port}:{port}",
    ]
    cmd.insert(2, "-d" if detach else "-it")
    root = emulator_root()
    if system == "Windows":
        cmd += ["-v", f"{root}:/home/emulator/.aws/emulator"]
    else:
        home = str(Path(os.path.expanduser("~")))
        cmd += ["-e", f"HOME={home}", "-v", f"{root}:{root}"]
        if system == "Linux" and hasattr(os, "getuid"):
            cmd[2:2] = ["--user", f"{os.getuid()}:{os.getgid()}"]
    if opts.telemetry is False or os.environ.get("EMULATOR_TELEMETRY"):
        value = "off" if opts.telemetry is False else os.environ["EMULATOR_TELEMETRY"]
        cmd += ["-e", f"EMULATOR_TELEMETRY={value}"]
    cmd.append(opts.image)
    cmd += emulator_args(opts)
    return cmd


def docker_image_exists(image: str) -> bool:
    result = subprocess.run(["docker", "image", "inspect", image], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return result.returncode == 0


def docker_container_running(name: str) -> bool:
    result = subprocess.run(["docker", "inspect", "-f", "{{.State.Running}}", name], capture_output=True, text=True)
    return result.returncode == 0 and result.stdout.strip() == "true"


def list_cli_containers() -> list[tuple[str, int]]:
    """Running containers started by this CLI: ``[(name, port), ...]``."""
    if not docker_available():
        return []
    result = subprocess.run(
        ["docker", "ps", "--filter", f"name=^{CONTAINER_PREFIX}", "--format", "{{.Names}}"],
        capture_output=True,
        text=True,
    )
    out = []
    for name in result.stdout.split():
        suffix = name[len(CONTAINER_PREFIX) :]
        if suffix.isdigit():
            out.append((name, int(suffix)))
    return out


def pid_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    if IS_WINDOWS:  # pragma: no cover - windows only
        result = subprocess.run(
            ["tasklist", "/FI", f"PID eq {pid}", "/FO", "CSV", "/NH"], capture_output=True, text=True
        )
        return f'"{pid}"' in result.stdout
    _reap(pid)
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def _reap(pid: int) -> None:
    """Collect a zombie child if we happen to be its parent."""
    if IS_WINDOWS:  # pragma: no cover
        return
    try:
        os.waitpid(pid, os.WNOHANG)
    except ChildProcessError:
        pass


def detect_arch(machine: str | None = None) -> str:
    machine = (machine or platform.machine()).lower()
    return "aarch64" if machine in ("arm64", "aarch64", "armv8", "armv8l") else "x86_64"


def dockerfile(arch: str | None = None, version: str | None = None) -> str:
    """The official recipe; ``version`` pins the package (default: the latest one)."""
    arch = arch or detect_arch()
    if version:
        url = f"{PACKAGE_BASE.rsplit('/', 1)[0]}/aws-emulator-{version}-1-{arch}.rpm"
    else:
        url = f"{PACKAGE_BASE}/aws-emulator-{arch}.rpm"
    return DOCKERFILE_TEMPLATE.format(package_url=url)


def tail(path: Path, lines: int = 20) -> list[str]:
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8", errors="replace") as fh:
        return fh.readlines()[-lines:]


def log_path(port: int) -> Path:
    """Where the log of the instance on ``port`` is (also after it stopped)."""
    state = State.load(port)
    if state and state.log:
        return Path(state.log)
    return CliFiles(port).log


INSTANCE_FILE_NAMES = ("config", "emulator_credentials", "ca.pem", "truststore.p12")


def cleanup_instance_files(port: int) -> bool:
    """Remove files a stopped emulator left behind. Returns True if anything was removed.

    Only touches the documented files, and only when nothing listens on the port.
    """
    files = InstanceFiles(port)
    if not files.dir.is_dir() or health.port_open(port):
        return False
    removed = False
    for name in INSTANCE_FILE_NAMES:
        path = files.dir / name
        if path.exists():
            path.unlink()
            removed = True
    try:
        files.dir.rmdir()
    except OSError:
        pass  # not empty: something else lives there, leave it alone
    return removed


# --------------------------------------------------------------------------- lifecycle


def is_running(port: int) -> bool:
    state = State.load(port)
    if state and state.mode == "native" and state.pid:
        return pid_alive(state.pid)
    if state and state.mode == "docker" and state.container:
        return docker_container_running(state.container)
    return health.port_open(port)


def _popen_detached(
    cmd: list[str], log_file: Path, append: bool = False, env: dict[str, str] | None = None
) -> subprocess.Popen:
    log_file.parent.mkdir(parents=True, exist_ok=True)
    with log_file.open("a" if append else "w", encoding="utf-8") as fh:
        kwargs: dict = {"stdout": fh, "stderr": subprocess.STDOUT, "stdin": subprocess.DEVNULL, "env": env}
        if IS_WINDOWS:  # pragma: no cover
            # Own process group, so Ctrl+Break can be sent to it (and only to it).
            kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP  # type: ignore[attr-defined]
        else:
            kwargs["start_new_session"] = True
        proc = subprocess.Popen(cmd, **kwargs)
    _DETACHED.append(proc)  # outlives this function on purpose: don't warn when the object goes
    return proc


# Background processes awsemu started and left running (the emulator, the proxy). Holding
# them keeps Python from warning "subprocess is still running" when the Popen is collected.
_DETACHED: list[subprocess.Popen] = []


@atexit.register
def _forget_detached() -> None:
    """Reap the ones that ended; the others keep running after awsemu exits, on purpose."""
    for proc in _DETACHED:
        if proc.poll() is None:
            proc.returncode = 0  # detached: not ours to wait for (silences Popen.__del__)
    _DETACHED.clear()


def _wait_for_startup(log_file: Path, proc: subprocess.Popen, timeout: float) -> dict | None:
    """Wait for the ``emulator server information`` line (used with ``-p 0``)."""

    def started() -> dict | None:
        if log_file.exists():
            info = logs.find_startup(tail(log_file, 200))
            if info:
                return info
        if proc.poll() is not None:
            return {}  # it exited: stop waiting, and report nothing
        return None

    return waiting.poll(started, timeout=timeout) or None


def _port_from_url(url: str) -> int | None:
    try:
        return int(url.rsplit(":", 1)[1].split("/", 1)[0])
    except (IndexError, ValueError):
        return None


def start(opts: StartOptions, wait: float = 30.0) -> tuple[State, health.Health]:
    """Start in the background. With ``opts.port == 0`` the OS picks the port (native only).

    Returns the saved state (``state.port`` is the real port) and the health result.
    """
    mode = resolve_mode(opts.mode, opts.binary)
    random_port = opts.port == 0
    if random_port and mode == "docker":
        raise RuntimeErrorWithHint(
            "Port 0 doesn't work with Docker: Docker can't forward a port chosen at startup.",
            "Pick a port with --port, or use --native.",
        )
    if not random_port and health.port_open(opts.port):
        raise RuntimeErrorWithHint(
            f"Something is already listening on 127.0.0.1:{opts.port}.",
            "Run 'awsemu status --all' or pick another port with '--port'.",
        )

    if mode == "native":
        if not native_available(opts.binary):
            raise RuntimeErrorWithHint(
                f"'{split_binary(opts.binary)[0]}' not found on PATH.",
                "Install the package, set AWSEMU_BINARY, or use '--docker'.",
            )
        cmd = native_command(opts)
        if random_port:
            log_file = cli_root() / "pending" / f"{time.time_ns()}.log"
        else:
            log_file = CliFiles(opts.port).log
        proc = _popen_detached(cmd, log_file)
        port = opts.port

        def abort() -> str | None:
            code = proc.poll()
            return f"emulator exited with code {code}" if code is not None else None

        if random_port:
            info = _wait_for_startup(log_file, proc, wait)
            port = _port_from_url(str((info or {}).get("endpoint_url", ""))) or 0
            if not port:
                reason = abort() or "no startup line with endpoint_url in the log"
                return (
                    State(port=0, mode="native", started_at=time.time(), command=cmd, pid=proc.pid, log=str(log_file)),
                    health.Health(0, False, False, reason),
                )
            final_log = CliFiles(port).log
            if not IS_WINDOWS:  # an open file can be renamed on POSIX
                final_log.parent.mkdir(parents=True, exist_ok=True)
                log_file.replace(final_log)
                log_file = final_log

        state = State(port=port, mode="native", started_at=time.time(), command=cmd, pid=proc.pid, log=str(log_file))
    else:
        if not docker_available():
            raise RuntimeErrorWithHint("Docker not found on PATH.")
        if not docker_image_exists(opts.image):
            raise RuntimeErrorWithHint(
                f"Docker image '{opts.image}' not found.",
                "Build it once with 'awsemu image build' (AWS doesn't publish a prebuilt image).",
            )
        emulator_root().mkdir(parents=True, exist_ok=True)
        cmd = docker_command(opts, detach=True)
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode != 0:
            raise RuntimeErrorWithHint(f"docker run failed: {result.stderr.strip()}")
        name = container_name(opts.port)
        # Keep a copy of the log on disk: with --rm, 'docker logs' is gone after a stop.
        log_file = CliFiles(opts.port).log
        _popen_detached(["docker", "logs", "-f", name], log_file)
        state = State(
            port=opts.port, mode="docker", started_at=time.time(), command=cmd, container=name, log=str(log_file)
        )

        def abort() -> str | None:
            if not docker_container_running(name):
                return "container stopped"
            return None

    state.save()
    status = health.wait_healthy(state.port, timeout=wait, abort=abort)
    if not status.healthy and abort():
        State.clear(state.port)
    return state, status


def run_foreground(opts: StartOptions) -> int:
    """Run attached to the terminal (Ctrl+C stops it cleanly)."""
    mode = resolve_mode(opts.mode, opts.binary)
    if mode == "native":
        cmd = native_command(opts)
    else:
        emulator_root().mkdir(parents=True, exist_ok=True)
        cmd = docker_command(opts, detach=False)
    try:
        return subprocess.call(cmd)
    except KeyboardInterrupt:
        return 130


def _send_stop(pid: int, force: bool) -> None:
    if IS_WINDOWS:  # pragma: no cover - windows only
        if force:
            subprocess.run(["taskkill", "/PID", str(pid), "/T", "/F"], capture_output=True)
        else:
            # The process was started in its own group; Ctrl+Break is the closest
            # thing to SIGTERM that can be delivered to it.
            os.kill(pid, signal.CTRL_BREAK_EVENT)  # type: ignore[attr-defined]
        return
    os.kill(pid, signal.SIGKILL if force else signal.SIGTERM)


def _wait_gone(pid: int, timeout: float) -> bool:
    return waiting.until(lambda: not pid_alive(pid), timeout=timeout)


def stop(port: int, timeout: float = 15.0, force: bool = False) -> str:
    """Stop the instance on ``port``. Returns a human description of what happened."""
    state = State.load(port)

    if state is None:
        name = container_name(port)
        if docker_available() and docker_container_running(name):
            state = State(port=port, mode="docker", started_at=0, command=[], container=name)
        elif health.port_open(port):
            raise RuntimeErrorWithHint(
                f"An emulator is listening on port {port} but wasn't started by awsemu.",
                "Stop it where it runs (Ctrl+C or SIGTERM).",
            )
        else:
            cleaned = cleanup_instance_files(port)
            return "not running" + (" (removed stale files)" if cleaned else "")

    if state.mode == "docker":
        name = state.container or container_name(port)
        if docker_container_running(name):
            cmd = ["docker", "kill" if force else "stop"]
            if not force:
                cmd += ["-t", str(int(timeout))]
            subprocess.run(cmd + [name], capture_output=True, text=True)
        State.clear(port)
        cleanup_instance_files(port)
        return f"stopped container {name}"

    pid = state.pid or 0
    if not pid_alive(pid):
        State.clear(port)
        cleanup_instance_files(port)
        return "was not running (cleaned up stale state)"

    _send_stop(pid, force)
    if not _wait_gone(pid, timeout):
        raise RuntimeErrorWithHint(f"pid {pid} is still running after {timeout:.0f}s.", "Try 'awsemu stop --force'.")
    # Give the port a moment to close before deciding the files are stale.
    health.wait_port_closed(port, timeout=1.0)
    State.clear(port)
    cleaned = cleanup_instance_files(port)
    how = "forced" if force else "stopped"
    return f"{how} pid {pid}" + (" (removed files it left behind)" if cleaned else "")


def build_image(image: str = DEFAULT_IMAGE, arch: str | None = None, version: str | None = None) -> int:
    with tempfile.TemporaryDirectory() as tmp:
        Path(tmp, "Dockerfile").write_text(dockerfile(arch, version), encoding="utf-8")
        return subprocess.call(["docker", "build", "-t", image, tmp])


@dataclass
class Instance:
    """Everything we know about the instance on a port (``awsemu status``)."""

    port: int
    status: Literal["healthy", "unhealthy", "stopped"]
    detail: str
    endpoint: str
    mode: str
    """native, docker, external (running, not started by awsemu) or ``-``."""
    pid: int | None
    container: str | None
    uptime_seconds: float | None
    auth: bool | None
    files: str
    log: str | None

    def as_dict(self) -> dict:
        return asdict(self)


def instance_info(port: int) -> Instance:
    """Everything we know about the instance on ``port`` (for ``status``)."""
    state = State.load(port)
    files = InstanceFiles(port)
    h = health.check(port)
    detail = h.detail
    if state and not h.port_open and state.mode == "native" and state.pid and not pid_alive(state.pid):
        detail = "stale state: process is gone"
    return Instance(
        port=port,
        status=h.label,
        detail=detail,
        endpoint=files.endpoint_url,
        mode=state.mode if state else ("external" if h.port_open else "-"),
        pid=state.pid if state else None,
        container=state.container if state else None,
        uptime_seconds=round(time.time() - state.started_at, 1) if state and state.started_at else None,
        auth=files.auth_enabled() if files.exists() else None,
        files=str(files.dir),
        log=state.log if state else None,
    )
