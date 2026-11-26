"""``awsemu mcp``: the MCP server for coding agents, and how to add it to one."""

from __future__ import annotations

import json
import shutil
import sys

import click

from ..context import Ctx, pass_ctx

CLIENTS = ("claude-code", "claude-desktop", "cursor", "vscode", "json")


def _command() -> list[str]:
    exe = shutil.which("awsemu")
    return [exe, "mcp"] if exe else [sys.executable, "-m", "awsemu", "mcp"]


def config_text(client: str, port: int | None = None) -> str:
    cmd = _command()
    if port:
        cmd = [cmd[0], *cmd[1:-1], "--port", str(port), "mcp"]
    server = {"command": cmd[0], "args": cmd[1:]}
    if client == "claude-code":
        return "claude mcp add awsemu -- " + " ".join(cmd)
    if client == "vscode":  # .vscode/mcp.json
        return json.dumps({"servers": {"awsemu": {"type": "stdio", **server}}}, indent=2)
    # Claude Desktop (claude_desktop_config.json), Cursor (.cursor/mcp.json) and most others
    return json.dumps({"mcpServers": {"awsemu": server}}, indent=2)


@click.group(invoke_without_command=True)
@pass_ctx
@click.pass_context
def mcp(ctx, c: Ctx):
    """An MCP server, so coding agents test against the emulator, never AWS.

    \\b
      awsemu mcp                          # the server (on stdio; your agent starts it)
      awsemu mcp config claude-code       # how to add it to your agent

    Tools: start/stop the emulator and see its status, the environment for your
    code, seeds, resources, any API call, fidelity, project checks, the proxy's
    calls and faults, and explaining a failed call. They only work against the
    emulator on 127.0.0.1, never with real credentials. Run it from your
    project's folder (awsemu.toml applies). Guide: docs/agents.md.
    """
    if ctx.invoked_subcommand:
        return
    from .. import mcp as server

    server.Server(c.port).serve()


@mcp.command()
@click.argument("client", type=click.Choice(CLIENTS), default="json")
@pass_ctx
def config(c: Ctx, client: str):
    """Print how to add the server to an agent: claude-code, claude-desktop, cursor, vscode or json."""
    from ..paths import default_port

    click.echo(config_text(client, c.port if c.port != default_port() else None))
