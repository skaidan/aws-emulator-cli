"""Amazon SNS: topics and subscriptions."""

from __future__ import annotations

import json

from .. import clients
from .. import realaccount
from .. import seed as seedlib
from ..commands._common import allow_lambda, allow_queue

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


def apply(seed, port, report):
    sns = clients.client("sns", port)
    existing = set()
    for page in sns.get_paginator("list_topics").paginate():
        existing |= {t["TopicArn"] for t in page.get("Topics", [])}
    for tp in seed.section("topics"):
        name = tp["name"]
        try:
            attrs = {"FifoTopic": "true"} if tp.get("fifo") else {}
            topic = sns.create_topic(Name=name, Attributes=attrs)["TopicArn"]
            result = "unchanged" if topic in existing else "created"
            subs = []
            for page in sns.get_paginator("list_subscriptions_by_topic").paginate(TopicArn=topic):
                subs += page.get("Subscriptions", [])
            details = []
            for sub in tp.get("subscriptions") or []:
                sid = f"awsemu-sns-{name}"
                if "sqs" in sub:
                    protocol = "sqs"
                    target = allow_queue(clients.client("sqs", port), sub["sqs"], "sns.amazonaws.com", topic, sid)
                else:
                    protocol = "lambda"
                    target = allow_lambda(
                        clients.client("lambda", port), sub["lambda"], "sns.amazonaws.com", topic, sid
                    )
                wanted = {"RawMessageDelivery": "true" if sub.get("raw") else "false"}
                if sub.get("filter") is not None:
                    wanted["FilterPolicy"] = json.dumps(sub["filter"])
                match = next((s for s in subs if s["Protocol"] == protocol and s["Endpoint"] == target), None)
                if match is None:
                    sns.subscribe(
                        TopicArn=topic,
                        Protocol=protocol,
                        Endpoint=target,
                        Attributes=wanted,
                        ReturnSubscriptionArn=True,
                    )
                    result = "updated" if result == "unchanged" else result
                else:
                    current = sns.get_subscription_attributes(SubscriptionArn=match["SubscriptionArn"])["Attributes"]
                    for k, val in wanted.items():
                        same = (
                            (json.loads(current[k]) == json.loads(val))
                            if k == "FilterPolicy" and current.get(k)
                            else current.get(k, "false" if k == "RawMessageDelivery" else None) == val
                        )
                        if not same:
                            sns.set_subscription_attributes(
                                SubscriptionArn=match["SubscriptionArn"], AttributeName=k, AttributeValue=val
                            )
                            result = "updated" if result == "unchanged" else result
                details.append(f"→ {protocol}:{sub.get('sqs') or sub.get('lambda')}")
            report.add("topic", name, result, ", ".join(details))
        except Exception as exc:
            report.add("topic", name, "failed", clients.describe_error(exc))


def export(port: int, opts: seedlib.ExportOptions) -> list[dict]:
    sns = clients.client("sns", port)
    topics = []
    for page in sns.get_paginator("list_topics").paginate():
        for t in page.get("Topics", []):
            arn = t["TopicArn"]
            entry = {"name": arn.rsplit(":", 1)[-1]}
            if entry["name"].endswith(".fifo"):
                entry["fifo"] = True
            subs = []
            for sp in sns.get_paginator("list_subscriptions_by_topic").paginate(TopicArn=arn):
                for s in sp.get("Subscriptions", []):
                    if s["Protocol"] not in ("sqs", "lambda"):
                        opts.notes.append(f"skipped {s['Protocol']} subscription on {entry['name']}")
                        continue
                    sub = {s["Protocol"]: s["Endpoint"].rsplit(":", 1)[-1]}
                    attrs = sns.get_subscription_attributes(SubscriptionArn=s["SubscriptionArn"])["Attributes"]
                    if attrs.get("RawMessageDelivery") == "true":
                        sub["raw"] = True
                    if attrs.get("FilterPolicy"):
                        sub["filter"] = json.loads(attrs["FilterPolicy"])
                    subs.append(sub)
            if subs:
                entry["subscriptions"] = subs
            topics.append(entry)
    return topics


def seed_import(sess, opts: seedlib.ImportOptions) -> list[dict]:
    """``topics`` of a real account (read-only), for ``awsemu seed import``."""
    queue_names = {q["name"] for q in opts.data.get("queues", [])}
    sns = realaccount.client(sess, "sns")
    topics = []
    for page in sns.get_paginator("list_topics").paginate():
        for t in page.get("Topics", []):
            arn = t["TopicArn"]
            entry = {"name": arn.rsplit(":", 1)[-1]}
            if entry["name"].endswith(".fifo"):
                entry["fifo"] = True
            subs = []
            for sp in sns.get_paginator("list_subscriptions_by_topic").paginate(TopicArn=arn):
                for s in sp.get("Subscriptions", []):
                    target = s["Endpoint"].rsplit(":", 1)[-1]
                    if s["Protocol"] != "sqs" or target not in queue_names:
                        opts.notes.append(f"topic {entry['name']}: left out its {s['Protocol']} subscription")
                        continue
                    sub: dict = {"sqs": target}
                    attrs = sns.get_subscription_attributes(SubscriptionArn=s["SubscriptionArn"])["Attributes"]
                    if attrs.get("RawMessageDelivery") == "true":
                        sub["raw"] = True
                    if attrs.get("FilterPolicy"):
                        sub["filter"] = json.loads(attrs["FilterPolicy"])
                    subs.append(sub)
            if subs:
                entry["subscriptions"] = subs
            topics.append(entry)
    return topics


def cost(call) -> list[tuple[str, float]]:
    return [("sns.publish", 1)] if call["operation"] in ("Publish", "PublishBatch") else []


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
    seed_section="topics",
    apply=apply,
    export=export,
    seed_import=seed_import,
    cost=cost,
)
