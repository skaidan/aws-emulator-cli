"""``awsemu watch``: resources appearing, disappearing and changing, live.

AWS Emulator doesn't log API calls (checked in CI, also with RUST_LOG=debug),
so this polls the resources and prints what changed between two looks.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime

import click

from .. import exitcodes
from .. import health, ui
from ..clients import client
from ..context import Ctx, handle_errors, pass_ctx
from ..services import Snapshot, all_services

# {awsemu name: (boto3 service, snapshot function)}, from the service registry.
COLLECTORS: dict[str, tuple[str, Callable]] = {s.alias: (s.name, s.watch) for s in all_services() if s.watch}


UNITS = {"bucket": "object(s)", "queue": "message(s)", "table": "item(s)"}


def snapshot(port: int, services: list[str]) -> tuple[dict[str, Snapshot], dict[str, str]]:
    """Look at every selected service in parallel.

    Returns ``({service: snapshot}, {service: error})``. A service that fails is
    left out, so a hiccup is never reported as everything being deleted.
    """

    def one(name):
        boto_name, fn = COLLECTORS[name]
        try:
            return name, fn(client(boto_name, port)), None
        except Exception as exc:
            from ..clients import describe_error

            return name, None, describe_error(exc)

    snaps: dict[str, Snapshot] = {}
    errors: dict[str, str] = {}
    with ThreadPoolExecutor(max_workers=6) as pool:
        for name, part, err in pool.map(one, services):
            if err:
                errors[name] = err
            else:
                snaps[name] = part
    return snaps, errors


def diff(before: Snapshot, after: Snapshot) -> list[tuple[str, str, str, str]]:
    """``[(sign, kind, name, detail)]`` with ``+`` created, ``-`` deleted, ``~`` changed."""
    events = []
    for key in sorted(after.keys() - before.keys()):
        value = after[key]
        detail = f"{value} {UNITS.get(key[0], '')}".strip() if value else ""
        events.append(("+", key[0], key[1], detail))
    for key in sorted(before.keys() - after.keys()):
        events.append(("-", key[0], key[1], ""))
    for key in sorted(before.keys() & after.keys()):
        old, new = before[key], after[key]
        if old != new and old is not None and new is not None:
            delta = new - old
            events.append(
                ("~", key[0], key[1], f"{old} → {new} {UNITS.get(key[0], '')} ({'+' if delta > 0 else ''}{delta})")
            )
    return events


STYLE = {"+": "ok", "-": "error", "~": "info"}


def _print_event(sign: str, kind: str, name: str, detail: str) -> None:
    stamp = datetime.now().strftime("%H:%M:%S")
    line = f"{stamp}  {sign} {kind:<13} {name}" + (f"  {detail}" if detail else "")
    ui.echo(line, STYLE.get(sign))


@click.command()
@click.option(
    "-s",
    "--service",
    "services",
    multiple=True,
    metavar="NAME",
    help=f"Only these services. Repeatable (default: all; resources: {', '.join(sorted(COLLECTORS))}).",
)
@click.option(
    "-i",
    "--interval",
    type=click.FloatRange(0.5, 3600),
    default=2,
    show_default=True,
    metavar="SECONDS",
    help="Time between looks.",
)
@click.option("--once", is_flag=True, help="Print the current state and exit.")
@click.option(
    "--calls",
    is_flag=True,
    help="Show every API call instead (service, operation, result, latency), through the proxy.",
)
@click.option("--errors", "errors_only", is_flag=True, help="With --calls: only failed calls.")
@pass_ctx
@handle_errors
def watch(c: Ctx, services, interval: float, once: bool, calls: bool, errors_only: bool):
    """Show resources being created, deleted or changed, live (Ctrl+C to stop).

    Buckets show their object count, queues their visible messages and tables
    their items, so you can see your app working.

    \b
      awsemu watch
      awsemu watch -s sqs -s dynamodb -i 1
      awsemu watch --calls            # API calls, through 'awsemu proxy'
      awsemu watch --calls --errors -s dynamodb

    The emulator doesn't log API calls, so --calls needs the proxy
    ('awsemu proxy start -d', and your code going through it).
    """
    if calls:
        from .proxy import show_calls

        show_calls(c.port, 20, follow=not once, services=set(services), errors_only=errors_only, as_json=False)
        return
    unknown = [s for s in services if s not in COLLECTORS]
    if unknown:
        raise click.BadParameter(
            f"{', '.join(unknown)} (choose from {', '.join(sorted(COLLECTORS))}, or use --calls)",
            param_hint="'--service'",
        )
    h = health.check(c.port)
    if not h.healthy:
        from ..runtime import RuntimeErrorWithHint

        raise RuntimeErrorWithHint(
            f"No healthy emulator on port {c.port} ({h.detail}).", "Start one with 'awsemu up' or 'awsemu start'."
        )
    selected = list(services) or sorted(COLLECTORS)
    current, errors = snapshot(c.port, selected)
    for name, err in errors.items():
        ui.warn(f"{name}: {err[:100]} (not watched)")
    watched = [s for s in selected if s not in errors]

    everything = {k: v for part in current.values() for k, v in part.items()}
    rows = [
        [kind, name, f"{v} {UNITS.get(kind, '')}".strip() if v is not None else ""]
        for (kind, name), v in sorted(everything.items())
    ]
    ui.table(["kind", "name", "count"], rows, title=f"AWS Emulator on port {c.port}", empty="(empty)")
    if once:
        return
    ui.echo(f"Watching {', '.join(watched)} every {interval:g}s. Ctrl+C to stop.", "muted")
    try:
        while True:
            time.sleep(interval)
            if not health.port_open(c.port):
                ui.error("The emulator stopped.")
                raise SystemExit(exitcodes.FAILED)
            nxt, _ = snapshot(c.port, watched)  # failed services keep their last state
            for service, part in nxt.items():
                for event in diff(current.get(service, {}), part):
                    _print_event(*event)
                current[service] = part
    except KeyboardInterrupt:
        ui.echo("", None)
