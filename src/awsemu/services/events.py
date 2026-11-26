"""Amazon EventBridge: event buses and rules."""

from __future__ import annotations

from .. import clients
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


SERVICE = Service(
    name="events",
    label="EventBridge buses",
    names=buses,
    details=details,
    describe=describe,
    watch=names_snapshot("rule", rules),  # rules come and go; buses rarely do
    completions={"rule": lambda c, i: pages(c, "list_rules", "Rules", "Name", cap=COMPLETE_MAX)},
)
