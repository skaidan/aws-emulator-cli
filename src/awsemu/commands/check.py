"""``awsemu check``: which known emulator differences affect this project."""

from __future__ import annotations

from pathlib import Path

import click

from .. import check as chk
from .. import exitcodes
from .. import fidelity as fid
from .. import scan as sc
from .. import ui
from ..context import handle_errors, json_option
from ..runtime import RuntimeErrorWithHint
from .fidelity import pick_release


def _where(locations: list[sc.Location]) -> str:
    first = f"{locations[0].file}:{locations[0].line}"
    return first + (f" (+{len(locations) - 1})" if len(locations) > 1 else "")


def _difference_line(d: chk.Difference) -> str:
    info = d.as_dict("")
    if d.at_operation:
        what = f"fails here (step {info['step']})" if info["step"] else "fails here"
        if info["mismatch"] == "body" and info["expected"] == info["actual"]:
            what += f": same {info['expected'] or 'status'}, different response body"
        elif info["expected"] or info["actual"]:
            what += f": AWS {info['expected'] or '?'}, emulator {info['actual'] or '?'}"
        elif info["mismatch"]:
            what += f": {info['mismatch']} differs"
    elif info["operation"]:
        what = f"fails at {info['operation']}"
    else:
        what = "fails"
    if d.matches_usage:
        what += "; calls only operations you use"
    return f"{d.test.id}  {what}"


@click.command()
@click.argument("paths", nargs=-1, type=click.Path(exists=True, path_type=Path))
@click.option("--release", metavar="VERSION",
              help="Emulator release to check against: 1.0.385 or latest "
                   "(default: emulator_version in awsemu.toml, else your installed one).")
@click.option("--manifest", "manifest_ref", metavar="FILE|REF",
              help="manifest.jsonl to use: a local file, or a tag/branch of the fidelity tests "
                   "repository (default: the version the release names, else the newest one).")
@click.option("--all", "show_all", is_flag=True, help="List every known difference, not the first 3 per operation.")
@click.option("--strict", is_flag=True,
              help="Exit with code 1 when an operation you use has known differences (for CI).")
@click.option("--refresh", is_flag=True, help="Download scores and manifest again instead of using the cache.")
@json_option
@handle_errors
def check(paths, release, manifest_ref, show_all, strict, refresh, as_json):
    """Find the AWS operations your project uses and the known emulator differences for them.

    \b
      awsemu check                    # this folder
      awsemu check src infra          # just these
      awsemu check --release latest   # would upgrading help?
      awsemu check --strict           # exit 1 on known differences (CI)

    Reads code that uses boto3, the AWS SDKs for JavaScript, Java and Go, and
    Terraform, CloudFormation/SAM and CDK files; nothing is run. Then it looks
    the operations up in the fidelity tests of the release
    (https://github.com/aws/aws-emulator-evaluation-suite): a test is listed when
    it fails at an operation you call, or calls only operations you call.
    """
    tag, scores, installed = pick_release(release, refresh)
    suite = fid.suite_version(tag) or (None if manifest_ref else chk.latest_suite_version()) or "main"
    try:
        if manifest_ref and Path(manifest_ref).is_file():
            manifest = chk.read_manifest_file(Path(manifest_ref))
            suite = Path(manifest_ref).name
        else:
            suite = manifest_ref or suite
            manifest = chk.load_manifest(suite, refresh=refresh)
    except fid.FidelityError as exc:
        raise RuntimeErrorWithHint(str(exc), "Check your connection, or pass --manifest FILE "
                                   "(manifest.jsonl from a clone of the tests repository).") from exc

    index = chk.Index(scores, manifest)
    result = sc.scan(list(paths) or [Path(".")], index.known_services)
    report = chk.analyze(result, index, tag, suite)
    limit = None if show_all else 3
    failed = strict and bool(report.with_differences)

    if as_json:
        ui.print_json(report.as_dict(limit=limit))
        if failed:
            raise SystemExit(exitcodes.FAILED)
        return

    ui.kv([("release", tag + (f" (yours: v{installed})" if installed and fid.tag_for(installed) != tag else "")),
           ("fidelity tests", suite),
           ("scanned", f"{result.files} file(s)" + (f": {', '.join(report.sources)}" if report.sources else ""))])
    ui.echo()
    if not report.operations and not report.services:
        ui.warn("found no AWS SDK calls or AWS infrastructure here")
        ui.echo("Looked for boto3, AWS SDK for JavaScript/Java/Go, Terraform, CloudFormation/SAM "
                "and CDK. Point it at your code: awsemu check PATH", "muted")
        return

    if report.operations:
        rows = []
        for o in report.operations:
            diffs = len(o.differences)
            rows.append([o.operation, o.tests, o.passed,
                         ui.styled(diffs, "error") if diffs else ui.styled("0", "ok"),
                         o.other_failing or "", _where(o.locations)])
        ui.table(["operation", "tests", "passed", "differences", "other failing", "used in"], rows,
                 title="Operations your code calls")
    if report.uncovered:
        ui.echo(f"No fidelity tests yet for: {', '.join(report.uncovered)}", "muted")
    ui.echo()

    for o in report.with_differences:
        ui.echo(f"{o.operation}: {len(o.differences)} known difference(s)", "warn")
        for d in o.differences[:limit]:
            ui.echo(f"  ✗ {_difference_line(d)}")
        if limit and len(o.differences) > limit:
            ui.echo(f"  … {len(o.differences) - limit} more (--all)", "muted")
    if report.with_differences:
        ui.echo()

    if report.services:
        rows = []
        for s in report.services:
            score = f"{s.passed}/{s.tests}" if s.tests else "-"
            cfn = f"{s.cfn_passed}/{s.cfn_tests}" if s.cfn_tests else ""
            defined = ""
            if s.resources:
                rtype, loc = s.resources[0]
                defined = f"{rtype} ({loc.file})" + (f" +{len(s.resources) - 1}" if len(s.resources) > 1 else "")
            rows.append([s.service, ", ".join(s.sources), score, cfn, defined])
        ui.table(["service", "found in", "service tests", "via CloudFormation", "infrastructure"], rows,
                 title="Services")
        ui.echo()

    summary = report.as_dict()["summary"]
    if report.with_differences:
        ui.warn(f"{summary['operations_with_differences']} of {summary['operations']} operation(s) "
                f"you use have known differences ({summary['differences']} failing test(s)).")
    elif report.operations:
        ui.success(f"No known differences for the {summary['operations']} operation(s) you use.")
    ui.echo(f"Tests: {chk.SUITE_URL} · details: awsemu fidelity SERVICE --failures"
            + ("" if show_all else " · every difference: --all"), "muted")
    if failed:
        raise SystemExit(exitcodes.FAILED)
