"""``awsemu fidelity``: how closely the emulator matches AWS, per service."""

from __future__ import annotations

import click

from .. import fidelity as fid
from .. import ui
from ..context import handle_errors
from ..runtime import RuntimeErrorWithHint


def _score_style(pct: float | None) -> str | None:
    if pct is None:
        return None
    return "ok" if pct >= 90 else "warn" if pct >= 60 else "error"


@click.command()
@click.argument("services", nargs=-1)
@click.option("--release", metavar="VERSION",
              help="Emulator release: 1.0.385, v1.0.385 or latest (default: your installed version).")
@click.option("--failures", is_flag=True, help="List the failing tests of the given services.")
@click.option("--sort", type=click.Choice(["name", "score"]), default="name", show_default=True)
@click.option("--refresh", is_flag=True, help="Download again instead of using the cache.")
@click.option("--json", "as_json", is_flag=True)
@handle_errors
def fidelity(services, release, failures, sort, refresh, as_json):
    """Fidelity scores published with each emulator release: tests passed per service.

    \b
      awsemu fidelity                     # every service
      awsemu fidelity s3 sqs dynamodb     # just these
      awsemu fidelity lambda --failures   # which tests fail, and how
      awsemu fidelity --release latest    # a newer release than yours?

    A score counts the tests that call only that service ("k of n", as AWS
    publishes it). Data from https://github.com/aws/aws-emulator/releases.
    """
    installed = fid.installed_version()
    wanted = release or installed or "latest"
    try:
        tag, scores = fid.fetch(wanted, refresh=refresh)
    except fid.FidelityError as exc:
        raise RuntimeErrorWithHint(str(exc), "Check your connection, or pass --release.") from exc
    table = fid.summarize(scores)

    names = sorted(table)
    if services:
        names, unknown = fid.match_services(list(services), sorted(table))
        if unknown:
            raise RuntimeErrorWithHint(f"no fidelity tests for: {', '.join(unknown)}",
                                       "Run 'awsemu fidelity' to see every service name.")
    if failures and not services:
        raise click.UsageError("--failures needs one or more SERVICES")

    if as_json:
        ui.print_json({
            "release": tag, "commit": scores.get("commit"), "scoredAt": scores.get("scoredAt"),
            "installed": installed,
            "services": {n: {"passed": table[n].passed, "total": table[n].total,
                             "multiServicePassed": table[n].multi_passed,
                             "multiServiceTotal": table[n].multi_total,
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
