"""``awsemu logs``: the emulator's log."""

from __future__ import annotations

import os
import subprocess
import sys
import time

import click

from .. import logs, runtime, ui
from ..context import Ctx, handle_errors, pass_ctx


@click.command(name="logs")
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
            cmd = [
                "docker",
                "logs",
                "--tail",
                str(lines),
                *(["-f"] if follow else []),
                state.container or runtime.container_name(c.port),
            ]
            sys.exit(subprocess.call(cmd))
        raise runtime.RuntimeErrorWithHint(
            f"No log for port {c.port}: awsemu didn't start an emulator there.",
            "Start it with 'awsemu start' (or check 'awsemu status --all').",
        )

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
