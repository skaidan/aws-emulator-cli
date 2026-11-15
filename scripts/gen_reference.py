#!/usr/bin/env python3
"""Generate docs/reference.md from the Click command tree.

    python scripts/gen_reference.py           # write docs/reference.md
    python scripts/gen_reference.py --check   # exit 1 if it's out of date (used in CI)
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import click  # noqa: E402

from awsemu.cli import cli  # noqa: E402

OUT = ROOT / "docs" / "reference.md"

HEADER = """# Referencia de comandos

> Generado automáticamente desde el código con `python scripts/gen_reference.py`.
> No lo edites a mano: cambia la ayuda del comando y vuelve a generarlo.

Opciones globales (van antes del comando): `--port/-p PUERTO` (por defecto 9297 o
`$AWSEMU_PORT`), `--plain` (texto plano), `--version/-V`, `--help/-h`.

"""


def _option_rows(cmd: click.Command, ctx: click.Context) -> list[tuple[str, str]]:
    rows = []
    for param in cmd.get_params(ctx):
        record = param.get_help_record(ctx)
        if record and not record[0].startswith(("-h", "--help")):
            rows.append(record)
    return rows


def _usage(cmd: click.Command, ctx: click.Context) -> str:
    return " ".join(cmd.collect_usage_pieces(ctx))


def _section(cmd: click.Command, path: list[str], parent: click.Context, out: list[str]) -> None:
    ctx = click.Context(cmd, info_name=path[-1], parent=parent)
    level = "#" * min(len(path), 4)
    out.append(f"{level} `{' '.join(path)}`\n")
    if cmd.help:
        text = cmd.help.replace("\b\n", "")
        lines = text.strip().splitlines()
        out.append(lines[0].strip() + "\n")
        rest = "\n".join(lines[1:]).strip("\n")
        if rest:
            # Indented example blocks become code blocks.
            blocks, buf, in_code = [], [], False
            for line in rest.splitlines():
                code = line.startswith("  ") and line.strip()
                if code and not in_code:
                    if buf:
                        blocks.append("\n".join(buf).strip())
                        buf = []
                    blocks.append("```bash")
                    in_code = True
                elif not code and in_code and line.strip():
                    blocks.append("```")
                    in_code = False
                if in_code:
                    if line.strip():
                        blocks.append(line.strip())
                else:
                    buf.append(line.strip())
            if buf:
                blocks.append("\n".join(buf).strip())
            if in_code:
                blocks.append("```")
            out.append("\n".join(b for b in blocks if b) + "\n")
    if not isinstance(cmd, click.Group):
        usage = _usage(cmd, ctx)
        out.append(f"```\n{' '.join(['awsemu', *path[1:]])} {usage}\n```\n")
        rows = _option_rows(cmd, ctx)
        if rows:
            out.append("| Opción | Descripción |\n| --- | --- |")
            for opt, desc in rows:
                desc = desc.replace("|", "\\|").replace("\n", " ")
                out.append(f"| `{opt}` | {desc} |")
            out.append("")
        return
    for name in cmd.list_commands(ctx):
        sub = cmd.get_command(ctx, name)
        if sub is not None and not sub.hidden:
            _section(sub, [*path, name], ctx, out)


def render() -> str:
    root = click.Context(cli, info_name="awsemu")
    out = [HEADER]
    toc = []
    for name in cli.list_commands(root):
        sub = cli.get_command(root, name)
        summary = sub.get_short_help_str(100)
        toc.append(f"- [`{name}`](#awsemu-{name}) — {summary}")
    out.append("\n".join(toc) + "\n")
    for name in cli.list_commands(root):
        _section(cli.get_command(root, name), ["awsemu", name], root, out)
    return "\n".join(out).rstrip() + "\n"


def main() -> int:
    text = render()
    if "--check" in sys.argv:
        current = OUT.read_text(encoding="utf-8") if OUT.exists() else ""
        if current != text:
            import difflib

            print("docs/reference.md is out of date: run python scripts/gen_reference.py")
            sys.stdout.writelines(difflib.unified_diff(
                current.splitlines(True), text.splitlines(True), "committed", "generated", n=1))
            return 1
        print("docs/reference.md is up to date")
        return 0
    OUT.parent.mkdir(exist_ok=True)
    OUT.write_text(text, encoding="utf-8")
    print(f"wrote {OUT.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
