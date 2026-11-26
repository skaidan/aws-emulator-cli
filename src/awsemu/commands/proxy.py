"""``awsemu proxy``: see every API call, and inject faults."""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import click

from .. import exitcodes, faults, health, project, ui
from .. import proxy as px
from ..context import Ctx, handle_errors, json_option, pass_ctx
from ..runtime import RuntimeErrorWithHint


def default_listen(emulator_port: int) -> int:
    proj = _project()
    if proj and proj.proxy_port is not None:
        return proj.proxy_port
    return emulator_port + 1 if emulator_port else 0


def _project():
    try:
        return project.load()
    except project.ProjectError:
        return None


def _parse_rules(specs) -> list[faults.Fault]:
    try:
        return [faults.parse(s) for s in specs]
    except faults.FaultError as exc:
        raise click.BadParameter(str(exc), param_hint="'--fault'") from exc


def _need(port: int) -> dict:
    state = px.running(port)
    if not state:
        raise RuntimeErrorWithHint(f"no proxy is running in front of the emulator on port {port}",
                                   "Start one with: awsemu proxy start -d")
    return state


def format_call(call: dict) -> str:
    """One line per call: time, service, operation, resource, result, latency, fault."""
    when = call["time"][11:23]
    what = f"{call['service'] or '?'} {call['operation'] or call['method'] + ' ' + call['path'][:40]}"
    result = call["error"] or str(call["status"])
    line = f"{when}  {what:<40} {call['resource'][:32]:<32} {result:<28} {call['latency_ms']:>7.1f} ms"
    if call.get("fault"):
        line += f"  ⚡ {call['fault']}"
    return line


def print_call(call: dict) -> None:
    style = "warn" if call.get("fault") else "error" if call["error"] else None
    ui.echo(format_call(call), style)


@click.group()
def proxy():
    """See every API call, and inject faults (throttling, errors, latency).

    \b
      awsemu proxy start -d                     # in the background
      awsemu exec --proxy -- pytest             # your code goes through it
      awsemu watch --calls                      # every call, live
      awsemu proxy faults add 'dynamodb=throttle@10%'
      awsemu proxy stop

    The proxy listens on https://127.0.0.1:<emulator port + 1> with its own
    certificate, and forwards everything to the emulator. Guide: docs/proxy.md.
    """


@proxy.command()
@click.option("--listen", "listen", type=int, metavar="PORT",
              help="Port for the proxy (default: proxy_port in awsemu.toml, else the emulator's + 1; 0 = free).")
@click.option("--fault", "specs", multiple=True, metavar="RULE",
              help="Fault rule, like 'dynamodb=throttle@10%' or 's3=latency:500ms'. Repeatable "
                   "(default: faults in awsemu.toml).")
@click.option("-d", "--detach", is_flag=True, help="Run in the background ('awsemu proxy stop' stops it).")
@click.option("--quiet", is_flag=True, help="Don't print each call (they're still logged).")
@click.option("--no-tls", is_flag=True, help="Plain HTTP instead of HTTPS (no certificate to trust).")
@click.option("--host", default="127.0.0.1", show_default=True, metavar="ADDRESS",
              help="Address to listen on. 0.0.0.0 lets containers reach it (at host.docker.internal), "
                   "and anyone on your network: the emulator's keys and the admin token still apply.")
@click.option("--bodies", is_flag=True,
              help="Also log headers and bodies (up to 64 KB each), with secrets and credentials masked.")
@click.option("--foreground", is_flag=True, hidden=True)
@pass_ctx
@handle_errors
def start(c: Ctx, listen, specs, detach, quiet, no_tls, host, bodies, foreground):
    """Start the proxy in front of the emulator on --port.

    In the foreground it prints each call until Ctrl-C; with -d it runs in the
    background. Calls are logged in ~/.aws/emulator-cli/proxy/<port>/calls.jsonl.
    """
    proj = _project()
    specs = list(specs) or (proj.faults if proj else [])
    bodies = bodies or bool(proj and proj.proxy_bodies)
    rules = _parse_rules(specs)
    listen = default_listen(c.port) if listen is None else listen
    if px.running(c.port):
        state = px.read_state(c.port)
        raise RuntimeErrorWithHint(f"a proxy is already running in front of port {c.port}: {state['endpoint_url']}",
                                   "Stop it first: awsemu proxy stop")
    if not foreground and not health.check(c.port).healthy:
        ui.warn(f"no emulator answers on port {c.port} yet; calls will get a 502 until it does")
    if detach:
        state = px.start_detached(c.port, listen, specs, tls=not no_tls, bodies=bodies, host=host)
        _started(state, rules)
        return

    def ready(state):
        if quiet:
            return
        _started(state, rules)
        ui.echo("Calls (Ctrl-C to stop):", "muted")

    try:
        px.serve(c.port, listen, rules, tls=not no_tls, on_call=None if quiet else print_call, on_ready=ready,
                 bodies=bodies, host=host)
    except OSError as exc:
        raise RuntimeErrorWithHint(f"the proxy can't listen on port {listen}: {exc}",
                                   "Pick another with --listen PORT (0 = any free port).") from exc


def _started(state: dict, rules: list[faults.Fault]) -> None:
    ui.success(f"Proxy listening on {state['endpoint_url']} -> emulator on port {state['emulator_port']}")
    if state.get("container_endpoint_url"):
        ui.echo(f"Containers: {state['container_endpoint_url']} (awsemu compose --proxy writes their settings)",
                "muted")
    ui.kv([("use it", "awsemu exec --proxy -- COMMAND   ·   eval \"$(awsemu env --proxy)\""),
           ("watch", "awsemu watch --calls"),
           ("faults", ", ".join(r.spec for r in rules) or "none (awsemu proxy faults add RULE)")])


@proxy.command()
@pass_ctx
@handle_errors
def stop(c: Ctx):
    """Stop the background proxy."""
    if px.stop(c.port):
        ui.success(f"Proxy in front of port {c.port} stopped.")
    else:
        ui.echo(f"No proxy running in front of port {c.port}.", "muted")


@proxy.command()
@json_option
@pass_ctx
@handle_errors
def status(c: Ctx, as_json):
    """Is the proxy running, where, and with which faults."""
    state = px.running(c.port)
    if not state:
        if as_json:
            ui.print_json({"running": False, "emulator_port": c.port})
        else:
            ui.echo(f"No proxy running in front of port {c.port}.", "muted")
        sys.exit(exitcodes.NOT_HEALTHY)
    health_data = px.admin(state, "GET", "health")
    rules = px.admin(state, "GET", "faults")["rules"]
    data = {"running": True, "emulator_port": c.port, "port": state["port"],
            "endpoint_url": state["endpoint_url"], "pid": state["pid"], "ca": state.get("ca"),
            "calls": health_data["calls"], "faults": [r["spec"] for r in rules],
            "calls_file": state["calls"]}
    if as_json:
        ui.print_json(data)
        return
    ui.kv([("endpoint", data["endpoint_url"]), ("emulator", f"port {c.port}"), ("pid", str(data["pid"])),
           ("calls", str(data["calls"])), ("faults", ", ".join(data["faults"]) or "none"),
           ("certificate", data["ca"] or "none (--no-tls)"), ("log", data["calls_file"])])


# --------------------------------------------------------------------------- faults


@proxy.group(name="faults", invoke_without_command=True)
@json_option
@pass_ctx
@click.pass_context
@handle_errors
def faults_(ctx, c: Ctx, as_json):
    """List the fault rules of the running proxy (add, set, clear them).

    \b
      awsemu proxy faults add 'dynamodb=throttle@10%' 's3=latency:500ms'
      awsemu proxy faults set 'sqs:SendMessage=503@50%'   # replace them all
      awsemu proxy faults clear

    Rule syntax: TARGET[RESOURCE]=EFFECT[,EFFECT][@RATE][xTIMES][for DURATION];
    see docs/proxy.md.
    """
    if ctx.invoked_subcommand:
        return
    _show_rules(px.admin(_need(c.port), "GET", "faults")["rules"], as_json)


def _rule_state(r: dict) -> str:
    if r.get("times") is not None and r["hits"] >= r["times"]:
        return "used up"
    remaining = r.get("remaining_s")
    if remaining is None:
        return "active"
    return "ended" if remaining == 0 else f"active, {ui.human_duration(remaining)} left"


def _show_rules(rules: list[dict], as_json: bool) -> None:
    if as_json:
        ui.print_json([{"rule": r["spec"], "hits": r["hits"], "active": r.get("active", True),
                        "remaining_s": r.get("remaining_s")} for r in rules])
        return
    if not rules:
        ui.echo("No fault rules: every call goes through unchanged.", "muted")
        return
    ui.table(["rule", "fired", "state"], [[r["spec"], r["hits"], _rule_state(r)] for r in rules])


@faults_.command(name="add")
@click.argument("rules", nargs=-1, required=True)
@pass_ctx
@handle_errors
def faults_add(c: Ctx, rules):
    """Add fault rules (they apply to the next calls)."""
    _parse_rules(rules)
    data = px.admin(_need(c.port), "POST", "faults", {"rules": list(rules)})
    _show_rules(data["rules"], False)


@faults_.command(name="set")
@click.argument("rules", nargs=-1)
@pass_ctx
@handle_errors
def faults_set(c: Ctx, rules):
    """Replace every fault rule with these."""
    _parse_rules(rules)
    data = px.admin(_need(c.port), "PUT", "faults", {"rules": list(rules)})
    _show_rules(data["rules"], False)


@faults_.command(name="clear")
@pass_ctx
@handle_errors
def faults_clear(c: Ctx):
    """Remove every fault rule."""
    px.admin(_need(c.port), "DELETE", "faults")
    ui.success("No fault rules: every call goes through unchanged.")



# --------------------------------------------------------------------------- calls


def read_calls(path: Path, last: int | None = None) -> list[dict]:
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return []
    out = []
    for line in lines[-last:] if last else lines:
        try:
            out.append(json.loads(line))
        except ValueError:
            continue
    return out


def _keep(call: dict, services, errors_only: bool) -> bool:
    if services and call["service"] not in services:
        return False
    return not errors_only or bool(call["error"])


def show_calls(port: int, last: int, follow: bool, services, errors_only: bool, as_json: bool) -> None:
    path = px.ProxyFiles(port).calls
    if not follow:
        logged = read_calls(path)
        calls = [c for c in logged if _keep(c, services, errors_only)][-last:] if last else []
        if as_json:
            ui.print_json(calls)
            return
        if not calls and logged:
            ui.echo(f"None of the {len(logged)} logged call(s) match.", "muted")
            return
        if not calls:
            ui.echo(f"No calls logged for the proxy in front of port {port} yet ({path}).", "muted")
            if not px.running(port):
                ui.echo("Start it with 'awsemu proxy start -d' and send your code through it "
                        "('awsemu exec --proxy -- …').", "muted")
            return
        for call in calls:
            print_call(call)
        return
    if not px.running(port):
        raise RuntimeErrorWithHint(f"no proxy is running in front of port {port}",
                                   "Start one with: awsemu proxy start -d")
    for call in [c for c in read_calls(path) if _keep(c, services, errors_only)][-last:] if last else []:
        _emit(call, as_json)
    position = path.stat().st_size if path.exists() else 0
    if not as_json:
        ui.echo("Waiting for calls (Ctrl-C to stop)…", "muted")
    try:
        while True:
            time.sleep(0.3)
            try:
                size = path.stat().st_size
            except OSError:
                continue
            if size < position:  # rotated
                position = 0
            if size == position:
                continue
            with path.open("r", encoding="utf-8") as fh:
                fh.seek(position)
                chunk = fh.read()
                position = fh.tell()
            for line in chunk.splitlines():
                try:
                    call = json.loads(line)
                except ValueError:
                    continue
                if _keep(call, services, errors_only):
                    _emit(call, as_json)
    except KeyboardInterrupt:
        pass


def _emit(call: dict, as_json: bool) -> None:
    if as_json:
        click.echo(json.dumps(call))  # one object per line, for jq
    else:
        print_call(call)


@proxy.command()
@click.option("-n", "--last", type=int, default=20, show_default=True, help="How many of the latest calls to show.")
@click.option("-f", "--follow", is_flag=True, help="Keep printing new calls (like tail -f).")
@click.option("--service", "services", multiple=True, metavar="NAME", help="Only this service. Repeatable.")
@click.option("--errors", "errors_only", is_flag=True, help="Only calls that failed (including injected faults).")
@json_option
@pass_ctx
@handle_errors
def calls(c: Ctx, last, follow, services, errors_only, as_json):
    """Calls that went through the proxy (same as 'awsemu watch --calls').

    With --json: a list; with --follow --json, one JSON object per line.
    """
    show_calls(c.port, last, follow, set(services), errors_only, as_json)


@proxy.command(name="har")
@click.option("-o", "--output", type=click.Path(dir_okay=False, path_type=Path), default="awsemu-calls.har",
              show_default=True, help="The file to write ('-' for stdout).")
@click.option("-n", "--last", type=int, default=0, help="Only the latest N calls (default: all logged).")
@click.option("--service", "services", multiple=True, metavar="NAME", help="Only this service. Repeatable.")
@click.option("--errors", "errors_only", is_flag=True, help="Only calls that failed.")
@pass_ctx
@handle_errors
def har_cmd(c: Ctx, output, last, services, errors_only):
    """The logged calls as a HAR file, to open in a browser's developer tools.

    \b
      awsemu proxy har -o calls.har     # then: DevTools > Network > Import HAR
      awsemu proxy har --errors --service dynamodb -o -

    Headers and bodies are in it when the proxy ran with --bodies (masked).
    """
    from .. import har

    calls = [x for x in read_calls(px.ProxyFiles(c.port).calls) if _keep(x, set(services), errors_only)]
    if last:
        calls = calls[-last:]
    state = px.read_state(c.port)
    base = state["endpoint_url"] if state else f"https://127.0.0.1:{default_listen(c.port)}"
    text = json.dumps(har.har(calls, base), indent=2)
    if str(output) == "-":
        click.echo(text)
        return
    output.write_text(text, encoding="utf-8")
    with_bodies = sum(1 for x in calls if "request" in x)
    ui.success(f"{len(calls)} call(s) in {output}"
               + ("" if with_bodies or not calls else " (no headers or bodies: start the proxy with --bodies)"))
