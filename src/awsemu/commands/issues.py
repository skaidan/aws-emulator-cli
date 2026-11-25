"""``awsemu issues``: the emulator's own list of known gaps, searchable."""

from __future__ import annotations

import fnmatch

import click

from .. import issues as iss
from .. import ui
from ..context import handle_errors, json_option
from ..runtime import RuntimeErrorWithHint

LEVELS = ("CRITICAL", "HIGH", "MEDIUM", "LOW")


def _targets(args, mine: bool) -> list[tuple[str, str]]:
    """``[(service, operation glob)]`` from SERVICE[:Operation] arguments and --mine."""
    out = [(a.split(":", 1)[0].lower(), a.split(":", 1)[1] if ":" in a else "*") for a in args]
    if mine:
        from pathlib import Path

        from .. import scan as sc

        result = sc.scan([Path(".")], iss.known_services())
        out += [(s, "*") for s in sorted(result.code_services() | set(result.iac()))]
    return out


@click.command()
@click.argument("targets", nargs=-1, metavar="[SERVICE[:Operation]]...")
@click.option("--mine", is_flag=True, help="The services this project uses (found like 'awsemu check' does).")
@click.option("--fixed", is_flag=True,
              help="Fixed issues instead of open ones, marking those whose tests still fail in your release.")
@click.option("--severity", type=click.Choice(LEVELS, case_sensitive=False), metavar="LEVEL",
              help="Only this severity and worse (CRITICAL, HIGH, MEDIUM, LOW).")
@click.option("--search", metavar="TEXT", help="Only issues whose title contains TEXT.")
@click.option("-n", "--limit", type=int, default=30, show_default=True, help="How many to list (0 = all).")
@click.option("--show", "show", metavar="N|NAME",
              help="Print one issue in full: its row in the last listing, its file name (or a prefix), or its URL.")
@click.option("--release", metavar="VERSION", help="With --fixed: the release to compare with (default: yours).")
@click.option("--refresh", is_flag=True, help="List the issues again instead of using the 6-hour cache.")
@json_option
@handle_errors
def issues(targets, mine, fixed, severity, search, limit, show, release, refresh, as_json):
    """The emulator's known gaps, from AWS's own issue files.

    \b
      awsemu issues dynamodb                 # open issues about DynamoDB
      awsemu issues dynamodb:TransactWriteItems sqs
      awsemu issues --mine --severity high   # for the services this project uses
      awsemu issues lambda --fixed           # fixed ones; marks those your release still fails
      awsemu issues --show 3                 # row 3 of the last listing, in full

    AWS keeps them in https://github.com/aws/aws-emulator/tree/main/issues
    ('things-that-do-not-work' and 'things-that-now-work'). 'awsemu check' shows the
    one behind each known difference.
    """
    try:
        if show:
            _show(show, refresh, as_json)
            return
        wanted = _targets(targets, mine)
        if not wanted:
            raise click.UsageError("name one or more services (awsemu issues dynamodb), or use --mine")
        services = {s for s, _ in wanted}
        folder = iss.FIXED if fixed else iss.OPEN
        files = [f for f in iss.listing(folder, refresh) if services & set(f.services)]
        if len(files) > 200 and not as_json:
            ui.echo(f"Reading {len(files)} issue(s) (once; then they're cached)…", "muted")
        found = sorted(iss.load(files), key=lambda i: i.rank)
    except iss.IssueNotFound as exc:
        raise RuntimeErrorWithHint(str(exc), "List them with: awsemu issues SERVICE") from exc
    except iss.IssuesError as exc:
        raise RuntimeErrorWithHint(str(exc), "Check your connection, or set GITHUB_TOKEN if GitHub rate-limits you.") from exc

    def keep(issue) -> bool:
        if not any(svc in issue.file.services and (op == "*" or any(
                fnmatch.fnmatch(o.lower(), op.lower()) for o in issue.operations)) for svc, op in wanted):
            return False
        if severity:
            worst_allowed = LEVELS.index(severity.upper())
            if issue.severity not in LEVELS or LEVELS.index(issue.severity) > worst_allowed:
                return False
        return not search or search.lower() in issue.title.lower()

    found = [i for i in found if keep(i)]
    failing: set[str] = set()
    tag = None
    if fixed:
        from .fidelity import pick_release

        tag, scores, _ = pick_release(release)
        failing = {u["unitId"] for u in scores.get("units", []) if u.get("outcome") == "fail"}
        found.sort(key=lambda i: (not (i.tests & failing), i.rank))
    total = len(found)
    shown = found[:limit] if limit else found
    iss.remember(shown)

    if as_json:
        rows = []
        for i in shown:
            d = i.as_dict()
            if fixed:
                d["fails_in_release"] = bool(i.tests & failing)
            rows.append(d)
        ui.print_json(rows)
        return
    if not found:
        ui.success(f"No {'fixed' if fixed else 'open'} issues match.")
        return
    columns = ["#", "severity", "since", "operation", "title"] + ([f"fails in {tag}"] if fixed else [])
    rows = []
    for n, i in enumerate(shown, 1):
        row = [n, i.severity or "-", i.file.created, ", ".join(i.operations)[:28] or "-", i.title[:90]]
        if fixed:
            row.append(ui.styled("yes", "warn") if i.tests & failing else "no")
        rows.append(row)
    ui.table(columns, rows, title=f"{'Fixed' if fixed else 'Open'} issues: {', '.join(sorted(services))}")
    more = f" (showing {len(shown)}; -n 0 for all)" if len(shown) < total else ""
    ui.echo(f"{total} issue(s){more}. One in full: awsemu issues --show N (its row)", "muted")
    if fixed:
        n = sum(bool(i.tests & failing) for i in found)
        if n:
            ui.echo(f"{n} of them are fixed after {tag}: their tests still fail in that release "
                    "(awsemu fidelity --compare latest).", "warn")


def _show(name: str, refresh: bool, as_json: bool) -> None:
    file = iss.find(name, refresh)
    text = iss.fetch(file, full=True)
    issue = iss.parse(text, file)
    if as_json:
        ui.print_json({**issue.as_dict(), "text": text})
        return
    ui.kv([("issue", file.name), ("state", file.state), ("severity", issue.severity or "-"),
           ("services", ", ".join(file.services) or "-"), ("url", file.url)])
    ui.echo()
    body = text.partition("\n# ")[2]
    body = "# " + body if body else text
    try:
        from rich.markdown import Markdown

        if ui.rich_enabled():
            ui.console().print(Markdown(body))
            return
    except ImportError:
        pass
    click.echo(body)

