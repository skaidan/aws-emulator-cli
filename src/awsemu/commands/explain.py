"""``awsemu explain CALL``: is a failed call an emulator difference or a bug in your code?"""

from __future__ import annotations

import click

from .. import explain as ex
from .. import proxy as px
from .. import ui
from ..context import Ctx, handle_errors, json_option, pass_ctx
from ..runtime import RuntimeErrorWithHint

VERDICTS = {
    "injected": ("injected by the proxy", "warn"),
    "known_difference": ("a known emulator difference", "warn"),
    "possible_difference": ("maybe an emulator difference", "warn"),
    "emulator_gap": ("probably the emulator", "warn"),
    "likely_your_code": ("probably the code under test", "info"),
    "unknown": ("no evidence either way", "muted"),
    "succeeded": ("the call succeeded", "ok"),
}


def pick_call(calls: list[dict], call_id: str) -> dict:
    """A call by id, or ``last``: the last one that failed (injected faults included)."""
    if call_id == "last":
        failed = [x for x in calls if x.get("error")]
        if not failed:
            raise RuntimeErrorWithHint("none of the logged calls failed")
        return failed[-1]
    if not call_id.isdigit():
        raise click.BadParameter("a call id (a number) or 'last'", param_hint="CALL")
    found = [x for x in calls if x.get("id") == int(call_id)]
    if not found:
        raise RuntimeErrorWithHint(f"no call {call_id} in the proxy's log")
    return found[-1]


@click.command()
@click.argument("call_id", metavar="CALL", default="last")
@click.option("--release", metavar="VERSION", help="Emulator release whose fidelity data to use (default: yours).")
@click.option("--refresh", is_flag=True, help="Download the fidelity data again.")
@json_option
@pass_ctx
@handle_errors
def explain(c: Ctx, call_id: str, release, refresh, as_json):
    """Say whether a failed call is a known emulator difference or likely your code.

    \\b
      awsemu explain            # the last failed call in the proxy's log
      awsemu explain 42 --json

    Compares the call with the fidelity tests of your emulator release (like
    'awsemu check'): a test that fails at the same operation with the same
    answer is a known difference; passing tests and a "bad request" error point
    at the code under test. It's evidence, not proof.
    """
    from .check import load_index
    from .proxy import read_calls

    calls = read_calls(px.ProxyFiles(c.port).calls)
    if not calls:
        raise RuntimeErrorWithHint(f"no calls logged by the proxy in front of port {c.port}",
                                   "Run your code through it: awsemu proxy start -d, then awsemu exec --proxy -- …")
    call = pick_call(calls, call_id)
    tag, suite, index, _installed = load_index(release, None, refresh)
    data = ex.explain(call, index, tag, suite)
    if as_json:
        ui.print_json(data)
        return
    label, style = VERDICTS[data["verdict"]]
    who = f"{call['service']} {call['operation']}" + (f" on {call['resource']}" if call.get("resource") else "")
    ui.echo(f"Call {call['id']}: {who} → {call.get('error') or call['status']}")
    ui.echo(f"Verdict: {label}", style)
    if data["tests"]:
        ui.echo(f"Fidelity tests for {data['operation']} ({tag}): {data['passed']}/{data['tests']} pass", "muted")
    for d in data["differences"][:5]:
        mark = "=" if d["test"] in data["matching"] else "·"
        ui.echo(f"  {mark} {d['test']}: AWS {d['expected'] or '?'}, emulator {d['actual'] or '?'}")
        for issue in d["issues"][:1]:
            ui.echo(f"      known issue: {issue['title'][:120]}  {issue['url']}", "muted")
    ui.echo(data["advice"])
