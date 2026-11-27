"""Amazon EventBridge: event buses and rules."""

from __future__ import annotations

import json

from .. import clients
from .. import realaccount
from .. import seed as seedlib
from ..grants import allow_lambda, allow_queue, arn, ensure_service_role
from ..awserrors import client_error, is_error
from . import COMPLETE_MAX, Service, clean, names_snapshot, pages


def buses(c) -> list[str]:
    return [b["Name"] for b in c.list_event_buses().get("EventBuses", [])]


def rules(c) -> list[str]:
    return pages(c, "list_rules", "Rules", "Name")


def details(port, name):
    """``name`` is an event bus (that's what overview lists): the bus and its rules."""
    ev = clients.client("events", port)
    found = ev.list_rules(EventBusName=name).get("Rules", [])
    return {"Bus": clean(ev.describe_event_bus(Name=name)), "Rules": found}


def describe(a, port, full):
    ev = clients.client("events", port)
    if a.kind == "event-bus":
        return clean(ev.describe_event_bus(Name=a.rest))
    bus, _, name = a.rest.rpartition("/")
    rule = clean(ev.describe_rule(Name=name, EventBusName=bus or "default"))
    rule["Targets"] = ev.list_targets_by_rule(Rule=name, EventBusName=bus or "default").get("Targets", [])
    return rule


def _target(kind: str, name: str, rule_arn: str, port: int) -> dict:
    sid = f"awsemu-events-{rule_arn.rsplit('/', 1)[-1]}"
    if kind == "sqs":
        return {"Arn": allow_queue(clients.client("sqs", port), name, "events.amazonaws.com", rule_arn, sid)}
    if kind == "lambda":
        return {"Arn": allow_lambda(clients.client("lambda", port), name, "events.amazonaws.com", rule_arn, sid)}
    if kind == "sns":
        return {"Arn": arn("sns", name)}
    role = ensure_service_role(
        clients.client("iam", port),
        "awsemu-events-role",
        "events.amazonaws.com",
        "Created by awsemu for EventBridge targets",
    )
    if kind == "stepfunctions":
        return {"Arn": arn("states", f"stateMachine:{name}"), "RoleArn": role}
    return {"Arn": arn("kinesis", f"stream/{name}"), "RoleArn": role}


def apply(seed, port, report):
    ev = clients.client("events", port)
    for r in seed.section("rules"):
        name, bus = r["name"], r.get("bus", "default")
        try:
            if bus != "default":
                try:
                    ev.describe_event_bus(Name=bus)
                except client_error() as exc:
                    if not is_error(exc, "ResourceNotFound"):
                        raise
                    ev.create_event_bus(Name=bus)
            wanted = {"Name": name, "EventBusName": bus, "State": "ENABLED" if r.get("enabled", True) else "DISABLED"}
            if "pattern" in r:
                wanted["EventPattern"] = json.dumps(r["pattern"])
            else:
                wanted["ScheduleExpression"] = r["schedule"]
            if r.get("description"):
                wanted["Description"] = r["description"]
            try:
                current = ev.describe_rule(Name=name, EventBusName=bus)
                same = (
                    current.get("State") == wanted["State"]
                    and current.get("ScheduleExpression") == wanted.get("ScheduleExpression")
                    and (json.loads(current["EventPattern"]) if current.get("EventPattern") else None)
                    == r.get("pattern")
                    and (not r.get("description") or current.get("Description") == r["description"])
                )
                result = "unchanged"
                if not same:
                    ev.put_rule(**wanted)
                    result = "updated"
                rule_arn = current["Arn"]
            except client_error() as exc:
                if not is_error(exc, "ResourceNotFound"):
                    raise
                rule_arn = ev.put_rule(**wanted)["RuleArn"]
                result = "created"
            existing: dict[str, dict] = {}
            for page in ev.get_paginator("list_targets_by_rule").paginate(Rule=name, EventBusName=bus):
                existing |= {t["Id"]: t for t in page.get("Targets", [])}
            desired, labels = [], []
            for t in r.get("targets") or []:
                kind = next(k for k in seedlib.TARGET_KINDS if k in t)
                target = {"Id": f"seed-{kind}-{t[kind]}"[:64], **_target(kind, t[kind], rule_arn, port)}
                if t.get("input") is not None:
                    target["Input"] = json.dumps(t["input"])
                desired.append(target)
                labels.append(f"→ {kind}:{t[kind]}")
            changed = [t for t in desired if any(existing.get(t["Id"], {}).get(k) != v for k, v in t.items())]
            stale = [i for i in existing if i not in {t["Id"] for t in desired}]
            if changed:
                resp = ev.put_targets(Rule=name, EventBusName=bus, Targets=changed)
                if resp.get("FailedEntryCount"):
                    e = resp["FailedEntries"][0]
                    raise RuntimeError(f"target rejected: {e.get('ErrorCode')}: {e.get('ErrorMessage')}")
            if stale:
                ev.remove_targets(Rule=name, EventBusName=bus, Ids=stale)
            if (changed or stale) and result == "unchanged":
                result = "updated"
            report.add("rule", name, result, ", ".join(labels))
        except Exception as exc:
            report.add("rule", name, "failed", clients.describe_error(exc))


def target_from_arn(value: str) -> dict | None:
    parts = value.split(":", 5)
    if len(parts) < 6:
        return None
    service, resource = parts[2], parts[5]
    if service == "sqs":
        return {"sqs": resource}
    if service == "sns":
        return {"sns": resource}
    if service == "lambda" and resource.startswith("function:"):
        return {"lambda": resource.split(":")[1]}
    if service == "states" and resource.startswith("stateMachine:"):
        return {"stepfunctions": resource.split(":", 1)[1]}
    if service == "kinesis" and resource.startswith("stream/"):
        return {"kinesis": resource.split("/", 1)[1]}
    return None


def export(port: int, opts: seedlib.ExportOptions) -> list[dict]:
    ev = clients.client("events", port)
    rules = []
    buses = [b["Name"] for b in ev.list_event_buses().get("EventBuses", [])] or ["default"]
    for bus in buses:
        for page in ev.get_paginator("list_rules").paginate(EventBusName=bus):
            for r in page.get("Rules", []):
                if r.get("ManagedBy"):
                    continue
                entry = {"name": r["Name"]}
                if bus != "default":
                    entry["bus"] = bus
                if r.get("EventPattern"):
                    entry["pattern"] = json.loads(r["EventPattern"])
                elif r.get("ScheduleExpression"):
                    entry["schedule"] = r["ScheduleExpression"]
                if r.get("State") == "DISABLED":
                    entry["enabled"] = False
                if r.get("Description"):
                    entry["description"] = r["Description"]
                targets = []
                for tp in ev.get_paginator("list_targets_by_rule").paginate(Rule=r["Name"], EventBusName=bus):
                    for t in tp.get("Targets", []):
                        target = target_from_arn(t["Arn"])
                        if target is None:
                            opts.notes.append(f"skipped target {t['Arn']} of rule {r['Name']}")
                            continue
                        if t.get("Input"):
                            target["input"] = json.loads(t["Input"])
                        targets.append(target)
                if targets:
                    entry["targets"] = targets
                rules.append(entry)
    return rules


def seed_import(sess, opts: seedlib.ImportOptions) -> list[dict]:
    """``rules`` of a real account (read-only), for ``awsemu seed import``."""
    ev = realaccount.client(sess, "events")
    local_targets = {
        "sqs": {q["name"] for q in opts.data.get("queues", [])},
        "sns": {t["name"] for t in opts.data.get("topics", [])},
        "stepfunctions": {m["name"] for m in opts.data.get("state_machines", [])},
        "kinesis": {s["name"] for s in opts.data.get("streams", [])},
    }
    rules = []
    for page in ev.get_paginator("list_rules").paginate():
        for r in page.get("Rules", []):
            if r.get("ManagedBy"):
                continue
            rule: dict = {"name": r["Name"]}
            if r.get("EventPattern"):
                rule["pattern"] = json.loads(r["EventPattern"])
            elif r.get("ScheduleExpression"):
                rule["schedule"] = r["ScheduleExpression"]
            if r.get("State") == "DISABLED":
                rule["enabled"] = False
            if r.get("Description"):
                rule["description"] = r["Description"]
            targets = []
            for tp in ev.get_paginator("list_targets_by_rule").paginate(Rule=r["Name"]):
                for t in tp.get("Targets", []):
                    from .services.events import target_from_arn

                    target = target_from_arn(t["Arn"])
                    kind = next(iter(target)) if target else ""
                    if not target or target[kind] not in local_targets.get(kind, set()):
                        opts.notes.append(
                            f"rule {r['Name']}: left out target {t['Arn'].split(':')[2]}:{t['Arn'].rsplit(':', 1)[-1]}"
                        )
                        continue
                    if t.get("Input"):
                        target["input"] = json.loads(t["Input"])
                    targets.append(target)
            if targets:
                rule["targets"] = targets
            rules.append(rule)
    return rules


def cost(call) -> list[tuple[str, float]]:
    return [("events.put", 1)] if call["operation"] == "PutEvents" else []


SERVICE = Service(
    name="events",
    label="EventBridge buses",
    names=buses,
    details=details,
    describe=describe,
    watch=names_snapshot("rule", rules),  # rules come and go; buses rarely do
    completions={"rule": lambda c, i: pages(c, "list_rules", "Rules", "Name", cap=COMPLETE_MAX)},
    seed_section="rules",
    apply=apply,
    export=export,
    seed_import=seed_import,
    cost=cost,
)
