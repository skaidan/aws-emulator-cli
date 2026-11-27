"""``awsemu overview``: one screen with what exists in the emulator."""

from __future__ import annotations


import click

from .. import ui
from ..clients import ensure_running
from ..context import Ctx, handle_errors, pass_ctx, json_option
from ..services import all_services, collect


# (label, boto3 service, lister), from the service registry.
SERVICES = [(s.label, s.name, s.names) for s in all_services()]


@click.command()
@click.option(
    "-s",
    "--service",
    "services",
    multiple=True,
    type=click.Choice([s[1] for s in SERVICES]),
    help="Only these services. Repeatable.",
)
@click.option("--all", "show_empty", is_flag=True, help="Also list services with nothing in them.")
@json_option
@pass_ctx
@handle_errors
def overview(c: Ctx, services, show_empty: bool, as_json: bool):
    """What's inside the emulator, across common services. Alias: 'awsemu ls'."""
    ensure_running(c.port)
    results = collect(c.port, set(services) or None)
    if as_json:
        ui.print_json({r.service: {"label": r.label, "items": r.items, "error": r.error} for r in results})
        return
    rows = []
    for r in results:
        if r.error:
            rows.append([r.label, ui.styled("?", "warn"), ui.styled(r.error[:80], "warn")])
            continue
        if not r.items and not show_empty and not services:
            continue
        names = ", ".join(map(str, r.items[:8]))
        if len(r.items) > 8:
            names += f", … (+{len(r.items) - 8})"
        rows.append([r.label, len(r.items), names])
    ui.table(
        ["resource", "count", "names"],
        rows,
        title=f"AWS Emulator on port {c.port}",
        empty="The emulator is empty. (Use --all to list every service checked.)",
    )
