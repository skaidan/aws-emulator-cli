"""``awsemu ui``: the terminal UI."""

from __future__ import annotations

import click

from .. import _meta, runtime
from ..context import Ctx, handle_errors, pass_ctx
from .env import _require_healthy


@click.command(name="ui")
@pass_ctx
@handle_errors
def ui_cmd(c: Ctx):
    """Browse the emulator in the terminal: services, resources and their details.

    Keys: arrows/enter to navigate, r refresh, w auto-refresh, q quit.
    Needs the 'ui' extra (Textual); if it's missing, this command says how to install it.
    """
    try:
        from .. import tui
    except ImportError as exc:
        raise runtime.RuntimeErrorWithHint(
            "The terminal UI needs Textual, which isn't installed.",
            f"{_meta.install_hint('ui')}  (or: pip install textual)",
        ) from exc
    _require_healthy(c.port)
    tui.run(c.port)
