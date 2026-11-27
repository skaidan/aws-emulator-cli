"""Helpers shared by the commands: KEY=VALUE and JSON arguments, error codes, the root group."""

from __future__ import annotations

import json

import click

from ..awserrors import client_error, error_code, is_error  # noqa: F401  (re-exported for the commands)


def parse_kv(pairs, option: str = "--attr") -> dict[str, str]:
    out = {}
    for pair in pairs:
        k, sep, v = pair.partition("=")
        if not sep or not k:
            raise click.BadParameter(f"'{pair}' is not KEY=VALUE", param_hint=option)
        out[k] = v
    return out


def load_json_arg(value: str, what: str = "value"):
    try:
        return json.loads(value)
    except json.JSONDecodeError as exc:
        raise click.BadParameter(f"{what} is not valid JSON: {exc}") from exc


class AliasedGroup(click.Group):
    """Lets users type unambiguous prefixes (``awsemu st`` -> status) and a few aliases."""

    ALIASES = {
        "ps": "status",
        "reset": "restart",
        "ddb": "dynamodb",
        "ls": "overview",
        "fn": "lambda",
        "eb": "events",
        "stepfunctions": "sfn",
        "secretsmanager": "secrets",
    }

    def lookup(self, ctx, cmd_name):
        """Find a command by its exact name (subclasses can load it on demand)."""
        return super().get_command(ctx, cmd_name)

    def get_command(self, ctx, cmd_name):
        cmd_name = self.ALIASES.get(cmd_name, cmd_name)
        rv = self.lookup(ctx, cmd_name)
        if rv is not None:
            return rv
        matches = [n for n in self.list_commands(ctx) if n.startswith(cmd_name)]
        if len(matches) == 1:
            return self.lookup(ctx, matches[0])
        if len(matches) > 1:
            ctx.fail(f"'{cmd_name}' is ambiguous: {', '.join(sorted(matches))}")
        return None

    def resolve_command(self, ctx, args):
        _, cmd, args = super().resolve_command(ctx, args)
        return cmd.name if cmd else None, cmd, args
