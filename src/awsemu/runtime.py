"""Start, stop and inspect AWS Emulator instances (native binary or Docker).

The emulator itself always runs in the foreground and has no subcommands, so
this module runs it in the background, remembers how (pid or container name)
and stops it with SIGTERM, which is a clean stop for the emulator.
"""

from __future__ import annotations

import json
import os
import platform
import shutil
import signal
import subprocess
import tempfile
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path

from . import health
from .paths import CliFiles, InstanceFiles, emulator_root

BINARY = "aws-emulator"
DEFAULT_IMAGE = "aws-emulator"
CONTAINER_PREFIX = "awsemu-"
PACKAGE_BASE = "https://downloads.aws.com/aws-emulator/packages/aws-emulator/LTS/latest"

DOCKERFILE_TEMPLATE = """\
FROM public.ecr.aws/amazonlinux/amazonlinux:2023-minimal
ADD {package_base}/aws-emulator-{arch}.rpm /tmp/aws-emulator.rpm
RUN rpm -i /tmp/aws-emulator.rpm && rm /tmp/aws-emulator.rpm \\
    && mkdir -p /home/emulator && chown 1000 /home/emulator
USER 1000
ENV HOME=/home/emulator
EXPOSE 9297
ENTRYPOINT ["aws-emulator", "-b", "0.0.0.0"]
"""


class RuntimeErrorWithHint(RuntimeError):
    def __init__(self, message: str, hint: str | None = None):
        super().__init__(message)
        self.hint = hint


@dataclass
class StartOptions:
    port: int
    mode: str = "auto"  # auto | native | docker
    auth: bool = True
    telemetry: bool | None = None  # None = leave to env/config.toml
    idle_timeout: int | None = None
    image: str = DEFAULT_IMAGE
    memory: str = "2g"
    binary: str = BINARY
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
    def load(cls, port: int) -> "State | None":
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


def docker_available() -> bool:
    return shutil.which("docker") is not None


def native_available(binary: str = BINARY) -> bool:
    return shutil.which(binary) is not None


def resolve_mode(mode: str, binary: str = BINARY) -> str:
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
        "Install the Linux package (https://github.com/aws/aws-emulator) or install "
        "Docker and run 'awsemu image build'.",
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
    return [opts.binary, *emulator_args(opts)]


def docker_command(opts: StartOptions, detach: bool = True,
                   system: str | None = None) -> list[str]:
    """``docker run`` following the official "Getting started with Docker" recipe."""
    system = system or platform.system()
    port = opts.port
    cmd = ["docker", "run", "--rm", "--name", container_name(port),
           f"--memory={opts.memory}", f"--memory-swap={opts.memory}",
           "-p", f"127.0.0.1:{port}:{port}"]
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
    result = subprocess.run(["docker", "image", "inspect", image],
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return result.returncode == 0


def docker_container_running(name: str) -> bool:
    result = subprocess.run(
        ["docker", "inspect", "-f", "{{.State.Running}}", name],
        capture_output=True, text=True)
    return result.returncode == 0 and result.stdout.strip() == "true"


def list_cli_containers() -> list[tuple[str, int]]:
    """Running containers started by this CLI: ``[(name, port), ...]``."""
    if not docker_available():
        return []
    result = subprocess.run(
        ["docker", "ps", "--filter", f"name=^{CONTAINER_PREFIX}", "--format", "{{.Names}}"],
        capture_output=True, text=True)
    out = []
    for name in result.stdout.split():
        suffix = name[len(CONTAINER_PREFIX):]
        if suffix.isdigit():
            out.append((name, int(suffix)))
    return out


def pid_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    if os.name == "nt":  # pragma: no cover - windows only
        result = subprocess.run(["tasklist", "/FI", f"PID eq {pid}", "/NH"],
                                capture_output=True, text=True)
        return str(pid) in result.stdout
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def detect_arch(machine: str | None = None) -> str:
    machine = (machine or platform.machine()).lower()
    return "aarch64" if machine in ("arm64", "aarch64", "armv8", "armv8l") else "x86_64"


def dockerfile(arch: str | None = None) -> str:
    return DOCKERFILE_TEMPLATE.format(package_base=PACKAGE_BASE, arch=arch or detect_arch())


def tail(path: Path, lines: int = 20) -> list[str]:
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8", errors="replace") as fh:
        return fh.readlines()[-lines:]


# --------------------------------------------------------------------------- lifecycle


def is_running(port: int) -> bool:
    state = State.load(port)
    if state and state.mode == "native" and state.pid:
        return pid_alive(state.pid)
    if state and state.mode == "docker" and state.container:
        return docker_container_running(state.container)
    return health.port_open(port)


def start(opts: StartOptions, wait: float = 30.0) -> tuple[State, health.Health]:
    mode = resolve_mode(opts.mode, opts.binary)
    if health.port_open(opts.port):
        raise RuntimeErrorWithHint(
            f"Something is already listening on 127.0.0.1:{opts.port}.",
            f"Run 'awsemu status' or pick another port with '--port'.")

    cli_files = CliFiles(opts.port)
    cli_files.dir.mkdir(parents=True, exist_ok=True)

    if mode == "native":
        if not native_available(opts.binary):
            raise RuntimeErrorWithHint(f"'{opts.binary}' not found on PATH.",
                                       "Install the package or use '--docker'.")
        cmd = native_command(opts)
        log_fh = cli_files.log.open("w", encoding="utf-8")
        kwargs: dict = {"stdout": log_fh, "stderr": subprocess.STDOUT,
                        "stdin": subprocess.DEVNULL}
        if os.name == "nt":  # pragma: no cover
            kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP  # type: ignore[attr-defined]
        else:
            kwargs["start_new_session"] = True
        proc = subprocess.Popen(cmd, **kwargs)
        log_fh.close()
        state = State(port=opts.port, mode="native", started_at=time.time(),
                      command=cmd, pid=proc.pid, log=str(cli_files.log))

        def abort() -> str | None:
            code = proc.poll()
            if code is not None:
                return f"emulator exited with code {code}"
            return None
    else:
        if not docker_available():
            raise RuntimeErrorWithHint("Docker not found on PATH.")
        if not docker_image_exists(opts.image):
            raise RuntimeErrorWithHint(
                f"Docker image '{opts.image}' not found.",
                "Build it once with 'awsemu image build' (AWS doesn't publish a prebuilt image).")
        emulator_root().mkdir(parents=True, exist_ok=True)
        cmd = docker_command(opts, detach=True)
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode != 0:
            raise RuntimeErrorWithHint(f"docker run failed: {result.stderr.strip()}")
        state = State(port=opts.port, mode="docker", started_at=time.time(),
                      command=cmd, container=container_name(opts.port))

        def abort() -> str | None:
            if not docker_container_running(state.container or ""):
                return "container stopped (see 'docker logs' output above)"
            return None

    state.save()
    status = health.wait_healthy(opts.port, timeout=wait, abort=abort)
    if not status.healthy and abort():
        State.clear(opts.port)
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


def stop(port: int, timeout: float = 15.0, force: bool = False) -> str:
    """Stop the instance on ``port``. Returns a human description of what happened."""
    state = State.load(port)

    if state is None:
        # Maybe a container we started from another machine state, or nothing at all.
        name = container_name(port)
        if docker_available() and docker_container_running(name):
            state = State(port=port, mode="docker", started_at=0, command=[], container=name)
        elif health.port_open(port):
            raise RuntimeErrorWithHint(
                f"An emulator is listening on port {port} but wasn't started by awsemu.",
                "Stop it where it runs (Ctrl+C or SIGTERM).")
        else:
            return "not running"

    if state.mode == "docker":
        name = state.container or container_name(port)
        if docker_container_running(name):
            cmd = ["docker", "kill" if force else "stop"]
            if not force:
                cmd += ["-t", str(int(timeout))]
            subprocess.run(cmd + [name], capture_output=True, text=True)
        State.clear(port)
        return f"stopped container {name}"

    pid = state.pid or 0
    if not pid_alive(pid):
        State.clear(port)
        return "was not running (cleaned up stale state)"
    sig = signal.SIGKILL if (force and hasattr(signal, "SIGKILL")) else signal.SIGTERM
    os.kill(pid, sig)
    deadline = time.monotonic() + timeout
    while pid_alive(pid) and time.monotonic() < deadline:
        time.sleep(0.2)
        _reap(pid)
    if pid_alive(pid):
        raise RuntimeErrorWithHint(f"pid {pid} is still running after {timeout:.0f}s.",
                                   "Try 'awsemu stop --force'.")
    State.clear(port)
    return f"stopped pid {pid}"


def _reap(pid: int) -> None:
    """Collect a zombie child if we happen to be its parent."""
    if os.name == "nt":  # pragma: no cover
        return
    try:
        os.waitpid(pid, os.WNOHANG)
    except ChildProcessError:
        pass


def build_image(image: str = DEFAULT_IMAGE, arch: str | None = None) -> int:
    with tempfile.TemporaryDirectory() as tmp:
        Path(tmp, "Dockerfile").write_text(dockerfile(arch), encoding="utf-8")
        return subprocess.call(["docker", "build", "-t", image, tmp])


def instance_info(port: int) -> dict:
    """Everything we know about the instance on ``port`` (for ``status``)."""
    state = State.load(port)
    files = InstanceFiles(port)
    h = health.check(port)
    info = {
        "port": port,
        "status": h.label,
        "detail": h.detail,
        "endpoint": files.endpoint_url,
        "mode": state.mode if state else ("external" if h.port_open else "-"),
        "pid": state.pid if state else None,
        "container": state.container if state else None,
        "uptime": time.time() - state.started_at if state and state.started_at else None,
        "auth": files.auth_enabled() if files.exists() else None,
        "files": str(files.dir),
        "log": state.log if state else None,
    }
    if state and not h.port_open and state.mode == "native" and state.pid and not pid_alive(state.pid):
        info["detail"] = "stale state: process is gone"
    return info
