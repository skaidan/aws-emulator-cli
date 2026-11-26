"""Renamed options and settings keep working for a while, with a warning (docs/deprecations.md).

* :func:`option_alias` keeps an old option name working: ``--old`` sets the new option
  and warns once per run.
* :data:`RENAMED_SETTINGS` maps an old ``awsemu.toml`` key to its new name; :func:`settings`
  rewrites the keys and warns.
* :func:`warn` is the one message for both: what changed, what to use, and from which
  release the old name stops working.

A JSON field that's replaced keeps being printed next to the new one until its removal
release; the contract tests and schemas list both.
"""

from __future__ import annotations

import click

from . import ui

# old setting -> (new setting, the release that removes the old one). Empty today.
RENAMED_SETTINGS: dict[str, tuple[str, str]] = {}

_warned: set[str] = set()


def warn(old: str, new: str, removed_in: str, where: str = "") -> None:
    """Warn once per run that ``old`` is deprecated in favour of ``new``."""
    key = f"{where}:{old}"
    if key in _warned:
        return
    _warned.add(key)
    place = f" in {where}" if where else ""
    ui.warn(f"{old}{place} is deprecated, use {new}; it stops working in awsemu {removed_in}")


def settings(data: dict, where: str) -> dict:
    """``awsemu.toml`` data with renamed keys moved to their new names (the new one wins)."""
    out = dict(data)
    for old, (new, removed_in) in RENAMED_SETTINGS.items():
        if old in out:
            warn(f"'{old}'", f"'{new}'", removed_in, where)
            value = out.pop(old)
            out.setdefault(new, value)
    return out


def option_alias(old: str, new_param: str, new_flag: str, removed_in: str, **option_kwargs):
    """A hidden ``old`` option that fills ``new_param`` and warns. Use it below the real option:

    \b
        @click.option("--timeout", "timeout", type=int)
        @deprecation.option_alias("--wait-seconds", "timeout", "--timeout", "1.2", type=int)
    """

    def callback(ctx: click.Context, param: click.Parameter, value):
        if value is None or value == () or value is False:
            return None
        warn(old, new_flag, removed_in)
        if ctx.params.get(new_param) in (None, (), False):
            ctx.params[new_param] = value
        return None

    def decorator(fn):
        return click.option(
            old,
            f"_deprecated_{new_param}",
            hidden=True,
            expose_value=False,
            callback=callback,
            is_eager=False,
            **option_kwargs,
        )(fn)

    return decorator
