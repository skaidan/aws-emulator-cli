"""Amazon SNS: topics and subscriptions."""

from __future__ import annotations

from .. import clients
from . import COMPLETE_MAX, Service, names_snapshot, pages


def topics(c) -> list[str]:
    return [t["TopicArn"].rsplit(":", 1)[-1] for t in pages(c, "list_topics", "Topics")]


def details(port, name):
    from ..commands.sns import topic_arn

    s = clients.client("sns", port)
    arn = topic_arn(name)
    subs = s.list_subscriptions_by_topic(TopicArn=arn).get("Subscriptions", [])
    return {"Attributes": s.get_topic_attributes(TopicArn=arn)["Attributes"], "Subscriptions": subs}


def describe(a, port, full):
    s = clients.client("sns", port)
    if ":" in a.resource:  # topic:subscription-id
        return s.get_subscription_attributes(SubscriptionArn=full)["Attributes"]
    return s.get_topic_attributes(TopicArn=full)["Attributes"]


SERVICE = Service(
    name="sns",
    label="SNS topics",
    names=topics,
    details=details,
    describe=describe,
    watch=names_snapshot("topic", topics),
    completions={
        "topic": lambda c, i: [
            t.rsplit(":", 1)[-1] for t in pages(c, "list_topics", "Topics", "TopicArn", cap=COMPLETE_MAX)
        ]
    },
)
