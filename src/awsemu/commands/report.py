"""``awsemu report CALL``: a draft emulator issue from a call in the proxy's log."""

from __future__ import annotations

from pathlib import Path

import click

from .. import proxy as px
from .. import report as rp
from .. import ui
from ..context import Ctx, handle_errors, pass_ctx
from ..runtime import RuntimeErrorWithHint


def _emulator_log(port: int) -> list[str]:
    from ..runtime import log_path

    try:
        return log_path(port).read_text(encoding="utf-8", errors="replace").splitlines()[-5000:]
    except OSError:
        return []


@click.command()
@click.argument("call_id", metavar="CALL", default="last")
@click.option("-o", "--output", type=click.Path(dir_okay=False, path_type=Path),
              help="Write the draft (Markdown) to this file instead of printing it.")
@click.option("--url", "show_url", is_flag=True,
              help="Print a link to the emulator's issue form with the draft filled in, instead.")
@click.option("--open", "open_browser", is_flag=True, help="Open that link in your browser.")
@pass_ctx
@handle_errors
def report(c: Ctx, call_id: str, output, show_url, open_browser):
    """Draft an issue for the emulator from a call the proxy logged.

    \b
      awsemu proxy calls --errors          # find the call's id (first column with --json)
      awsemu report 42                     # the draft, in Markdown
      awsemu report last --open            # the last failed call, in the issue form

    CALL is a call id, or 'last' for the last call that failed (injected faults
    aren't the emulator's, so they're skipped). It follows the emulator's
    "Behavior differs from AWS" form: what it answered, the request, the
    version and its log around the call. Credentials are removed. What AWS
    answers is for you to fill in. Start the proxy with --bodies so the draft
    has the request and response.
    """
    from ..fidelity import installed_version
    from .proxy import read_calls

    calls = read_calls(px.ProxyFiles(c.port).calls)
    if not calls:
        raise RuntimeErrorWithHint(f"no calls logged by the proxy in front of port {c.port}",
                                   "Start it with 'awsemu proxy start -d --bodies' and run the call through it.")
    if call_id == "last":
        failed = [x for x in calls if x.get("error") and not x.get("fault")]
        if not failed:
            raise RuntimeErrorWithHint("none of the logged calls failed (injected faults don't count)",
                                       "Pass the id of the call to report: awsemu proxy calls --json")
        call = failed[-1]
    else:
        if not call_id.isdigit():
            raise click.BadParameter("a call id (a number) or 'last'", param_hint="CALL")
        matches = [x for x in calls if x.get("id") == int(call_id)]
        if not matches:
            raise RuntimeErrorWithHint(f"no call {call_id} in the log (it has {calls[0]['id']}–{calls[-1]['id']}; "
                                       "the ids start again when the proxy restarts)")
        call = matches[-1]
    earlier = calls[:calls.index(call)]
    version = installed_version()
    try:
        draft = rp.build(call, earlier, f"aws-emulator {version}" if version else None, _emulator_log(c.port))
    except rp.ReportError as exc:
        raise RuntimeErrorWithHint(str(exc)) from exc
    if "request" not in call:
        ui.warn("this call was logged without its request and response: "
                "start the proxy with --bodies and run it again for a complete report")
    if show_url or open_browser:
        url = draft.url()
        if open_browser:
            import webbrowser

            webbrowser.open(url)
            ui.success("Opened the emulator's issue form; fill in what AWS answers before submitting.")
        else:
            click.echo(url)
        return
    if output:
        output.write_text(draft.markdown(), encoding="utf-8")
        ui.success(f"Draft in {output}: fill in what AWS answers, then file it at {rp.ISSUE_FORM}?template={rp.TEMPLATE}")
        return
    click.echo(draft.markdown())
