"""``awsemu check``: which known emulator differences affect this project."""

from __future__ import annotations

from pathlib import Path

import click

from .. import check as chk
from .. import exitcodes
from .. import fidelity as fid
from .. import scan as sc
from .. import ui
from ..context import Ctx, handle_errors, json_option, pass_ctx
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


def load_index(release: str | None, manifest_ref: str | None = None, refresh: bool = False):
    """``(release tag, tests version, Index, installed version)`` for check and explain."""
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
        raise RuntimeErrorWithHint(
            str(exc),
            "Check your connection, or pass --manifest FILE (manifest.jsonl from a clone of the tests repository).",
        ) from exc
    return tag, suite, chk.Index(scores, manifest), installed


@click.command()
@click.argument("paths", nargs=-1, type=click.Path(exists=True, path_type=Path))
@click.option(
    "--release",
    metavar="VERSION",
    help="Emulator release to check against: 1.0.385 or latest "
    "(default: emulator_version in awsemu.toml, else your installed one).",
)
@click.option(
    "--manifest",
    "manifest_ref",
    metavar="FILE|REF",
    help="manifest.jsonl to use: a local file, or a tag/branch of the fidelity tests "
    "repository (default: the version the release names, else the newest one).",
)
@click.option("--all", "show_all", is_flag=True, help="List every known difference, not the first 3 per operation.")
@click.option(
    "--strict", is_flag=True, help="Exit with code 1 when an operation you use has known differences (for CI)."
)
@click.option("--refresh", is_flag=True, help="Download scores and manifest again instead of using the cache.")
@click.option(
    "--no-explain",
    is_flag=True,
    help="Don't look up what explains each difference: the emulator's issue files and whether "
    "the latest release fixes it (no extra downloads).",
)
@click.option(
    "--from-calls",
    "from_calls",
    is_flag=True,
    help="Check the operations the proxy saw your code call (its calls log), instead of reading the code.",
)
@click.option(
    "--calls-file",
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
    metavar="FILE",
    help="A calls log to read with --from-calls (default: the proxy's, for --port).",
)
@click.option(
    "--iam",
    "iam_mode",
    is_flag=True,
    help="Instead: the IAM actions your code needs that your Terraform/CloudFormation/CDK policies don't grant.",
)
@json_option
@pass_ctx
@handle_errors
def check(
    c: Ctx,
    paths,
    release,
    manifest_ref,
    show_all,
    strict,
    refresh,
    no_explain,
    from_calls,
    calls_file,
    iam_mode,
    as_json,
):
    """Find the AWS operations your project uses and the known emulator differences for them.

    \b
      awsemu check                    # this folder
      awsemu check src infra          # just these
      awsemu check --release latest   # would upgrading help?
      awsemu check --strict           # exit 1 on known differences (CI)
      awsemu check --from-calls       # what your tests really called, via the proxy
      awsemu check --iam              # permissions your infrastructure doesn't grant

    Reads code that uses boto3, the AWS SDKs for JavaScript, Java and Go, and
    Terraform, CloudFormation/SAM and CDK files; nothing is run. Then it looks
    the operations up in the fidelity tests of the release
    (https://github.com/aws/aws-emulator-evaluation-suite): a test is listed when
    it fails at an operation you call, or calls only operations you call.

    With --from-calls it reads the proxy's calls log instead: only operations
    your code really called (run your tests through 'awsemu exec --proxy' first).
    """
    if calls_file and not from_calls:
        from_calls = True
    if iam_mode:
        return _check_iam(c, list(paths) or [Path(".")], from_calls, calls_file, strict, as_json)
    if from_calls and paths:
        raise click.UsageError("--from-calls reads the proxy's log, not files: drop the paths")
    tag, suite, index, installed = load_index(release, manifest_ref, refresh)
    unknown_ops: list[str] = []
    if from_calls:
        from .. import proxy as px
        from .proxy import read_calls

        log = calls_file or px.ProxyFiles(c.port).calls
        calls = read_calls(log)
        if not calls:
            raise RuntimeErrorWithHint(
                f"no calls in {log}",
                "Run your tests through the proxy first: awsemu proxy start -d, "
                "then awsemu exec --proxy -- pytest (or proxy = true in awsemu.toml).",
            )
        result, unknown_ops = chk.scan_from_calls(calls, index, log.name)
    else:
        result = sc.scan(list(paths) or [Path(".")], index.known_services)
    report = chk.analyze(result, index, tag, suite)
    report.uncovered = sorted(set(report.uncovered) | set(unknown_ops))
    if not no_explain and report.with_differences:
        from .. import issues as iss

        try:
            chk.attach_issues(report, refresh=refresh)
        except iss.IssuesError as exc:
            if not as_json:
                ui.warn(f"{exc} (the differences are listed without explanations; --no-explain skips this)")
        if release != "latest":
            try:
                latest_tag, latest_scores = fid.fetch("latest", refresh=refresh)
                chk.attach_fixes(report, latest_tag, latest_scores)
            except fid.FidelityError as exc:
                if not as_json:
                    ui.warn(f"couldn't compare with the latest release: {exc}")
    limit = None if show_all else 3
    failed = strict and bool(report.with_differences)

    if as_json:
        ui.print_json(report.as_dict(limit=limit))
        if failed:
            raise SystemExit(exitcodes.FAILED)
        return

    ui.kv(
        [
            ("release", tag + (f" (yours: v{installed})" if installed and fid.tag_for(installed) != tag else "")),
            ("fidelity tests", suite),
            (
                "calls" if from_calls else "scanned",
                f"{result.files} call(s) in {result.root}"
                if from_calls
                else f"{result.files} file(s)" + (f": {', '.join(report.sources)}" if report.sources else ""),
            ),
        ]
    )
    ui.echo()
    if from_calls and not report.operations and not report.services:
        ui.warn("none of the logged calls named an operation the proxy recognised")
        return
    if not report.operations and not report.services:
        ui.warn("found no AWS SDK calls or AWS infrastructure here")
        ui.echo(
            "Looked for boto3, AWS SDK for JavaScript/Java/Go, Terraform, CloudFormation/SAM "
            "and CDK. Point it at your code: awsemu check PATH",
            "muted",
        )
        return

    if report.operations:
        rows = []
        for o in report.operations:
            diffs = len(o.differences)
            rows.append(
                [
                    o.operation,
                    o.tests,
                    o.passed,
                    ui.styled(diffs, "error") if diffs else ui.styled("0", "ok"),
                    o.other_failing or "",
                    _where(o.locations),
                ]
            )
        ui.table(
            ["operation", "tests", "passed", "differences", "other failing", "used in"],
            rows,
            title="Operations your code calls",
        )
    if report.uncovered:
        ui.echo(f"No fidelity tests yet for: {', '.join(report.uncovered)}", "muted")
    ui.echo()

    for o in report.with_differences:
        ui.echo(f"{o.operation}: {len(o.differences)} known difference(s)", "warn")
        for d in o.differences[:limit]:
            ui.echo(f"  ✗ {_difference_line(d)}")
            if d.fixed_in:
                ui.echo(f"      ↳ fixed in {d.fixed_in}: awsemu install latest", "ok")
            for issue in d.issues[:1]:
                ui.echo(
                    f"      ↳ known issue{f' ({issue.severity})' if issue.severity else ''}: {issue.title[:140]}",
                    "muted",
                )
                ui.echo(f"        {issue.file.url}", "muted")
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
        ui.table(
            ["service", "found in", "service tests", "via CloudFormation", "infrastructure"], rows, title="Services"
        )
        ui.echo()

    summary = report.as_dict()["summary"]
    if report.with_differences:
        ui.warn(
            f"{summary['operations_with_differences']} of {summary['operations']} operation(s) "
            f"you use have known differences ({summary['differences']} failing test(s))."
        )
        if summary["fixed_in_latest"]:
            ui.echo(
                f"{summary['fixed_in_latest']} of them pass in the latest release, {summary['latest']}: "
                "upgrading fixes them (awsemu fidelity --compare latest --mine).",
                "ok",
            )
        if summary["explained_by_issues"] is not None:
            ui.echo(
                f"{summary['explained_by_issues']} of them are explained by an open issue of the emulator "
                "(awsemu issues SERVICE to browse them).",
                "muted",
            )
    elif report.operations:
        ui.success(f"No known differences for the {summary['operations']} operation(s) you use.")
    ui.echo(
        f"Tests: {chk.SUITE_URL} · details: awsemu fidelity SERVICE --failures"
        + ("" if show_all else " · every difference: --all"),
        "muted",
    )
    if failed:
        raise SystemExit(exitcodes.FAILED)


def _check_iam(c: Ctx, paths: list[Path], from_calls: bool, calls_file, strict: bool, as_json: bool) -> None:
    """``check --iam``: needed actions (calls or code) against the policies in the infrastructure."""
    from .. import iamcheck as ic

    if from_calls:
        from .iam import load_calls

        calls, log = load_calls(c.port, calls_file)
        needed, source = ic.needed_from_calls(calls, log.name), f"{len(calls)} call(s) in {log.name}"
    else:
        needed, source = ic.needed_from_code(paths), "the code (static scan)"
    grants = ic.granted(paths)
    result = ic.compare(needed, grants)
    failed = strict and bool(result.missing)
    if as_json:
        ui.print_json(result.as_dict())
        if failed:
            raise SystemExit(exitcodes.FAILED)
        return
    ui.kv([("actions from", source), ("policies", f"{grants.files} file(s), {len(grants.actions)} allowed action(s)")])
    ui.echo()
    if not needed:
        ui.warn("found no AWS calls that need a permission")
        return
    if not grants.actions and not grants.unexpanded:
        ui.warn("found no IAM policies here (Terraform, CloudFormation/SAM, or cdk.out after 'cdk synth')")
        ui.echo("Point it at your infrastructure: awsemu check --iam infra/", "muted")
        return
    rows = []
    for act, where in sorted(needed.items()):
        allowed = grants.allows(act)
        rows.append(
            [
                act,
                ui.styled("missing", "error") if not allowed else ui.styled(allowed[0].pattern, "ok"),
                where[0] + (f" (+{len(where) - 1})" if len(where) > 1 else ""),
            ]
        )
    ui.table(["action", "granted by", "used in"], rows, title="Actions your code needs")
    if grants.unexpanded:
        ui.echo("Not expanded (they may grant more): " + ", ".join(sorted({p for p, _ in grants.unexpanded})), "muted")
    if result.unused:
        ui.echo(
            f"Granted but not used by these calls: {', '.join(sorted({g.pattern for g in result.unused}))}", "muted"
        )
    ui.echo()
    if result.missing:
        ui.warn(
            f"{len(result.missing)} action(s) your code needs aren't allowed by any policy here: "
            + ", ".join(result.missing)
        )
        ui.echo(
            "It compares actions only, across every policy in the project (not per role); see docs/iam.md.", "muted"
        )
    else:
        ui.success(f"Every one of the {len(needed)} action(s) is allowed by a policy here.")
    if failed:
        raise SystemExit(exitcodes.FAILED)
