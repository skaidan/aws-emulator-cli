"""``awsemu doctor``: check the machine, the install and the instance (``awsemu.diagnosis``)."""

from __future__ import annotations

import sys

import click

from .. import diagnosis, exitcodes, ui
from ..context import Ctx, json_option, pass_ctx

RESULT_STYLE = {"ok": "ok", "warn": "warn", "fail": "error"}


@click.command()
@json_option
@pass_ctx
def doctor(c: Ctx, as_json: bool):
    """Check your setup and explain how to fix what's missing.

    Exits with 1 if something required is missing (warnings don't count).
    """
    diag = diagnosis.run(c.port)
    if as_json:
        ui.print_json(diag.as_dict())
    else:
        sep = "\n→ " if ui.rich_enabled() else "  → "
        rows = [
            [x.check, ui.styled(x.result, RESULT_STYLE[x.result]), x.detail + (f"{sep}{x.fix}" if x.fix else "")]
            for x in diag.checks
        ]
        ui.table(["check", "result", "detail"], rows)
    if diag.problems:
        if not as_json:
            ui.error(f"{diag.problems} problem(s) found.")
        sys.exit(exitcodes.FAILED)
    if not as_json:
        ui.success("Looks good.")
