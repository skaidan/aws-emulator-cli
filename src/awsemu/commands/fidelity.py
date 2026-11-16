"""``awsemu fidelity``: how closely the emulator matches AWS, per service."""

from __future__ import annotations

import click

from .. import fidelity as fid
from .. import project
from .. import ui
from ..context import handle_errors, json_option
from ..runtime import RuntimeErrorWithHint


def _score_style(pct: float | None) -> str | None:
    if pct is None:
        return None
    return "ok" if pct >= 90 else "warn" if pct >= 60 else "error"


def pick_release(release: str | None, refresh: bool = False) -> tuple[str, dict, str | None]:
    """``(tag, scores, installed)``: --release, else the project's pin, else installed, else latest."""
    installed = fid.installed_version()
    pinned = None
    try:
        proj = project.load()
        pinned = proj.emulator_version if proj else None
    except project.ProjectError:
        pass
    wanted = release or pinned or installed or "latest"
    try:
        tag, scores = fid.fetch(wanted, refresh=refresh)
    except fid.FidelityError as exc:
        raise RuntimeErrorWithHint(str(exc), "Check your connection, or pass --release.") from exc
    return tag, scores, installed


@click.command()
@click.argument("services", nargs=-1)
@click.option("--release", metavar="VERSION",
              help="Emulator release: 1.0.385, v1.0.385 or latest (default: your installed version).")
@click.option("--failures", is_flag=True, help="List the failing tests of the given services.")
@click.option("--sort", type=click.Choice(["name", "score"]), default="name", show_default=True,
              help="Order of the table (score: worst first).")
@click.option("--compare", "compare_to", metavar="VERSION",
              help="Compare with another release: tests fixed, regressed and added, per service.")
@click.option("--mine", is_flag=True,
              help="Only the services this project uses (found like 'awsemu check' does).")
@click.option("--refresh", is_flag=True, help="Download again instead of using the cache.")
@json_option
@handle_errors
def fidelity(services, release, failures, sort, compare_to, mine, refresh, as_json):
    """Fidelity scores published with each emulator release: tests passed per service.

    \b
      awsemu fidelity                     # every service
      awsemu fidelity s3 sqs dynamodb     # just these
      awsemu fidelity lambda --failures   # which tests fail, and how
      awsemu fidelity --release latest    # a newer release than yours?
      awsemu fidelity --compare latest --mine   # what an upgrade changes for you

    A score counts the tests that call only that service ("k of n", as AWS
    publishes it). Data from https://github.com/aws/aws-emulator/releases.
    """
    tag, scores, installed = pick_release(release, refresh)
    table = fid.summarize(scores)

    if mine:
        services = (*services, *_project_services(sorted(table)))
        if not services:
            raise RuntimeErrorWithHint("found no AWS services used in this folder",
                                       "Run it in your project, or name the SERVICES.")
    names = sorted(table)
    if services:
        names, unknown = fid.match_services(list(services), sorted(table))
        if unknown and not mine:
            raise RuntimeErrorWithHint(f"no fidelity tests for: {', '.join(unknown)}",
                                       "Run 'awsemu fidelity' to see every service name.")
    if failures and not services:
        raise click.UsageError("--failures needs one or more SERVICES")
    if compare_to:
        if failures:
            raise click.UsageError("--failures and --compare don't go together")
        _compare(tag, scores, compare_to, names if services else None, refresh, as_json)
        return

    if as_json:
        ui.print_json({
            "release": tag, "commit": scores.get("commit"), "scored_at": scores.get("scoredAt"),
            "installed": installed,
            "services": {n: {"passed": table[n].passed, "total": table[n].total,
                             "multi_service_passed": table[n].multi_passed,
                             "multi_service_total": table[n].multi_total,
                             **({"failures": [fid.describe_failure(u) for u in table[n].failures]}
                                if failures else {})}
                         for n in names},
        })
        return

    ui.kv([("release", tag), ("emulator commit", (scores.get("commit") or "")[:12]),
           ("scored", (scores.get("scoredAt") or "")[:19].replace("T", " ")),
           ("your emulator", installed or "not installed here")])
    if installed and fid.tag_for(installed) != tag:
        ui.warn(f"these scores are for {tag}, your emulator is v{installed}")
    ui.echo()

    if failures:
        for n in names:
            s = table[n]
            rows = [[f["test"], f["operation"], f["mismatch"], f["expected"], f["actual"]]
                    for f in map(fid.describe_failure, s.failures)]
            ui.table(["test", "operation", "mismatch", "expected", "got"], rows,
                     title=f"{n}: {s.total - s.passed} failing of {s.total}",
                     empty="no failing tests")
            ui.echo()
        ui.echo("Tests: https://github.com/aws/aws-emulator-evaluation-suite (behavioral/<service>/)",
                "muted")
        return

    if sort == "score":
        names.sort(key=lambda n: (table[n].percent if table[n].percent is not None else -1, n))
    rows = []
    for n in names:
        s = table[n]
        pct = s.percent
        rows.append([n, f"{s.passed}/{s.total}" if s.total else "-",
                     ui.styled(f"{pct:.0f}%", _score_style(pct)) if pct is not None else "",
                     f"{s.multi_passed}/{s.multi_total}" if s.multi_total else ""])
    ui.table(["service", "passed", "score", "multi-service"], rows)
    passed = sum(table[n].passed for n in names)
    total = sum(table[n].total for n in names)
    if total:
        ui.echo(f"{len(names)} service(s): {passed} of {total} single-service tests pass "
                f"({100 * passed / total:.0f}%). See failures with: awsemu fidelity SERVICE --failures",
                "muted")


def _project_services(score_names: list[str]) -> list[str]:
    """Score-file names of the services the code and infrastructure in this folder use."""
    from pathlib import Path

    from .. import scan as sc

    known = {sc.SCORE_TO_BOTO.get(n, n) for n in score_names}
    result = sc.scan([Path(".")], known)
    used = result.code_services() | set(result.iac())
    return sorted({sc.score_name(s) for s in used})


def _compare(tag: str, scores: dict, other: str, names: list[str] | None, refresh: bool,
             as_json: bool) -> None:
    try:
        other_tag, other_scores = fid.fetch(other, refresh=refresh)
    except fid.FidelityError as exc:
        raise RuntimeErrorWithHint(str(exc), "Check the version ('awsemu install --list').") from exc
    changes = fid.compare(scores, other_scores)
    shown = [changes[n] for n in sorted(changes) if (names is None and changes[n].changed)
             or (names is not None and n in names)]
    suites = (fid.suite_version(tag), fid.suite_version(other_tag))

    if as_json:
        ui.print_json({
            "from": {"release": tag, "suite": suites[0]}, "to": {"release": other_tag, "suite": suites[1]},
            "services": {c.service: {
                "from": {"passed": c.before[0], "total": c.before[1]},
                "to": {"passed": c.after[0], "total": c.after[1]},
                "fixed": c.fixed, "regressed": c.regressed, "added_passing": c.added_passing,
                "added_failing": c.added_failing, "removed": c.removed,
            } for c in shown},
        })
        return

    ui.kv([("from", f"{tag}" + (f" (fidelity tests {suites[0]})" if suites[0] else "")),
           ("to", f"{other_tag}" + (f" (fidelity tests {suites[1]})" if suites[1] else ""))])
    if all(suites) and suites[0] != suites[1]:
        ui.warn("the releases were scored with different fidelity tests versions; "
                "new and removed tests explain part of the change")
    ui.echo()
    if not shown:
        ui.success("No changes" + (" for these services." if names is not None else "."))
        return

    def score(passed_total: tuple[int, int]) -> str:
        return f"{passed_total[0]}/{passed_total[1]}" if passed_total[1] else "-"

    rows = [[c.service, score(c.before), score(c.after),
             ui.styled(f"+{len(c.fixed)}", "ok") if c.fixed else "",
             ui.styled(f"-{len(c.regressed)}", "error") if c.regressed else "",
             f"{len(c.added_passing)} pass / {len(c.added_failing)} fail" if c.added_passing or c.added_failing else "",
             len(c.removed) or ""]
            for c in shown]
    ui.table(["service", tag, other_tag, "fixed", "regressed", "new tests", "removed"], rows)
    for label, attr, style in (("Regressed (passed before, fail now)", "regressed", "error"),
                               ("Fixed (failed before, pass now)", "fixed", "ok")):
        items = [(c.service, uid) for c in shown for uid in getattr(c, attr)]
        if items:
            ui.echo()
            ui.echo(f"{label}: {len(items)}", style)
            for service, uid in items[:15]:
                ui.echo(f"  {service}  {uid}")
            if len(items) > 15:
                ui.echo(f"  … {len(items) - 15} more (--json lists them all)", "muted")
