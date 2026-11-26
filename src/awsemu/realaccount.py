"""Reading a real AWS account, read-only, for ``seed import`` and the proxy's shadow mode.

Everything that touches a real account goes through :func:`session`, which:

* needs a profile you name (``--profile``): never the default credentials or the
  ``AWS_*`` key variables, and never the emulator's;
* ignores ``AWS_ENDPOINT_URL`` and endpoints in your config, so the calls go to AWS
  and nowhere else;
* refuses, before anything is sent, any operation that isn't a read (``Describe*``,
  ``List*``, ``Get*``, ``Head*``) and the reads that return data or secrets rather than
  configuration (``GetSecretValue``, ``GetObject``, ``GetItem``, ``Scan``…).
"""

from __future__ import annotations

import re

READ_PREFIXES = ("Describe", "List", "Get", "Head")
DATA_READS = {
    "GetSecretValue", "BatchGetSecretValue", "GetObject", "GetObjectTorrent", "SelectObjectContent",
    "GetItem", "BatchGetItem", "Query", "Scan", "ExecuteStatement", "BatchExecuteStatement",
    "GetRecords", "GetShardIterator", "ReceiveMessage", "GetParameter", "GetParameters",
    "GetParametersByPath", "GetParameterHistory", "GetLogEvents", "FilterLogEvents", "GetQueryResults",
    "GetFunction", "GetLayerVersion", "GetExecutionHistory", "GetMetricData", "GetMetricStatistics",
    "Decrypt", "GenerateDataKey", "GetCredentialsForIdentity", "GetSessionToken", "GetFederationToken",
    "GetAuthorizationToken", "GetPasswordData", "GetConsoleOutput", "GetLoginProfile",
}
ARN_RE = re.compile(r"arn:aws:([a-z0-9-]+):([a-z0-9-]*):(\d{12}):")


class NotReadOnly(Exception):
    pass


PLAIN_PARAMETER_READS = {"GetParameter", "GetParameters"}  # allowed without decryption


def allowed(operation: str, params: dict | None = None, data_reads: bool = False) -> bool:
    """Is ``operation`` a configuration read (or any read, with ``data_reads``)?"""
    if not operation.startswith(READ_PREFIXES):
        return False
    if operation in PLAIN_PARAMETER_READS and not (params or {}).get("WithDecryption"):
        return True  # String/StringList values are configuration; SecureString stays encrypted
    return data_reads or operation not in DATA_READS


def guard(data_reads: bool = False):
    """A botocore ``before-parameter-build`` handler (it runs before anything is sent)
    that refuses anything but reads."""
    def check(params, model, **_):
        if not allowed(model.name, params, data_reads):
            raise NotReadOnly(f"refusing {model.service_model.service_name}:{model.name} against a real AWS "
                              "account: awsemu only reads configuration there")
    return check


def session(profile: str, region: str | None = None, data_reads: bool = False):
    """A boto3 session for the named profile, guarded read-only."""
    import boto3

    if not profile:
        raise NotReadOnly("a real account is only read with a profile you name (--profile)")
    s = boto3.session.Session(profile_name=profile, region_name=region)
    s.events.register("before-parameter-build.*.*", guard(data_reads))
    return s


def client(sess, service: str):
    from botocore.config import Config

    return sess.client(service, config=Config(ignore_configured_endpoint_urls=True,
                                              retries={"max_attempts": 3, "mode": "standard"}))


def localize(value, account: str, emulator_account: str = "000000000000", emulator_region: str = "us-east-1"):
    """Rewrite the real account's ARNs (in strings, dicts, lists) to the emulator's account and Region."""
    if isinstance(value, str):
        return ARN_RE.sub(lambda m: f"arn:aws:{m.group(1)}:{emulator_region if m.group(2) else ''}:"
                                    f"{emulator_account if m.group(3) == account else m.group(3)}:", value)
    if isinstance(value, dict):
        return {k: localize(v, account, emulator_account, emulator_region) for k, v in value.items()}
    if isinstance(value, list):
        return [localize(v, account, emulator_account, emulator_region) for v in value]
    return value


PLACEHOLDER = "change-me (awsemu seed import doesn't read secret values)"


def import_seed(sess, sections: set[str]) -> tuple[dict, list[str]]:
    """The configuration of the account in the session's Region, as seed data.

    Buckets without objects, tables without items, secrets and SecureString parameters
    with a placeholder value, no functions (their code isn't read)."""
    from . import seed as seedlib

    region = sess.region_name
    account = client(sess, "sts").get_caller_identity()["Account"]
    data: dict = {"version": seedlib.VERSION}
    notes: list[str] = []

    if "buckets" in sections:
        s3 = client(sess, "s3")
        buckets = []
        for b in s3.list_buckets().get("Buckets", []):
            try:
                where = s3.get_bucket_location(Bucket=b["Name"]).get("LocationConstraint") or "us-east-1"
            except Exception:  # noqa: BLE001 - a bucket we can't read the location of is skipped
                notes.append(f"skipped bucket {b['Name']} (couldn't read its Region)")
                continue
            if where == region:
                buckets.append({"name": b["Name"]})
        if buckets:
            data["buckets"] = buckets

    if "queues" in sections:
        sqs = client(sess, "sqs")
        queues = []
        for page in sqs.get_paginator("list_queues").paginate():
            for url in page.get("QueueUrls", []):
                a = sqs.get_queue_attributes(QueueUrl=url, AttributeNames=["All"])["Attributes"]
                entry: dict = {"name": url.rsplit("/", 1)[-1]}
                if a.get("FifoQueue") == "true":
                    entry["fifo"] = True
                    if a.get("ContentBasedDeduplication") == "true":
                        entry["content_dedup"] = True
                if a.get("VisibilityTimeout", "30") != "30":
                    entry["visibility_timeout"] = int(a["VisibilityTimeout"])
                if a.get("DelaySeconds", "0") != "0":
                    entry["delay"] = int(a["DelaySeconds"])
                if a.get("RedrivePolicy"):
                    import json

                    rp = json.loads(a["RedrivePolicy"])
                    entry["dlq"] = rp["deadLetterTargetArn"].rsplit(":", 1)[-1]
                    entry["max_receive"] = int(rp.get("maxReceiveCount", 5))
                queues.append(entry)
        names = {q["name"] for q in queues}
        for q in queues:
            if q.get("dlq") and q["dlq"] not in names:
                notes.append(f"queue {q['name']}: its dead-letter queue {q['dlq']} is elsewhere; left out")
                q.pop("dlq"), q.pop("max_receive", None)
        if queues:
            data["queues"] = queues

    if "tables" in sections:
        ddb = client(sess, "dynamodb")
        tables = []
        for page in ddb.get_paginator("list_tables").paginate():
            for name in page.get("TableNames", []):
                t = ddb.describe_table(TableName=name)["Table"]
                types = {d["AttributeName"]: d["AttributeType"] for d in t["AttributeDefinitions"]}
                entry = {"name": name}
                for k in t["KeySchema"]:
                    spec = k["AttributeName"] + ("" if types[k["AttributeName"]] == "S" else f":{types[k['AttributeName']]}")
                    entry["pk" if k["KeyType"] == "HASH" else "sk"] = spec
                if t.get("GlobalSecondaryIndexes") or t.get("LocalSecondaryIndexes"):
                    notes.append(f"table {name}: its secondary indexes aren't in seeds yet; left out")
                tables.append(entry)
        if tables:
            data["tables"] = tables

    queue_names = {q["name"] for q in data.get("queues", [])}
    if "topics" in sections:
        sns = client(sess, "sns")
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
                            notes.append(f"topic {entry['name']}: left out its {s['Protocol']} subscription")
                            continue
                        sub: dict = {"sqs": target}
                        attrs = sns.get_subscription_attributes(SubscriptionArn=s["SubscriptionArn"])["Attributes"]
                        if attrs.get("RawMessageDelivery") == "true":
                            sub["raw"] = True
                        if attrs.get("FilterPolicy"):
                            import json

                            sub["filter"] = json.loads(attrs["FilterPolicy"])
                        subs.append(sub)
                if subs:
                    entry["subscriptions"] = subs
                topics.append(entry)
        if topics:
            data["topics"] = topics

    if "secrets" in sections:
        sm = client(sess, "secretsmanager")
        secrets = []
        for page in sm.get_paginator("list_secrets").paginate():
            for s in page.get("SecretList", []):
                entry = {"name": s["Name"], "value": PLACEHOLDER}
                if s.get("Description"):
                    entry["description"] = s["Description"]
                secrets.append(entry)
        if secrets:
            data["secrets"] = secrets
            notes.append(f"{len(secrets)} secret(s) with a placeholder value: set real test values locally")

    if "parameters" in sections:
        ssm = client(sess, "ssm")
        params = []
        for page in ssm.get_paginator("describe_parameters").paginate():
            for d in page.get("Parameters", []):
                entry = {"name": d["Name"]}
                if d.get("Type") == "SecureString":
                    entry.update(value=PLACEHOLDER, type="SecureString")
                else:
                    entry["value"] = None  # filled below, without decryption
                    if d.get("Type") == "StringList":
                        entry["type"] = "StringList"
                if d.get("Description"):
                    entry["description"] = d["Description"]
                params.append(entry)
        plain = [p for p in params if p["value"] is None]
        for i in range(0, len(plain), 10):
            batch = {p["name"]: p for p in plain[i:i + 10]}
            # DescribeParameters doesn't return values; GetParameters without decryption is allowed
            for p in ssm.get_parameters(Names=list(batch), WithDecryption=False).get("Parameters", []):
                if p["Type"] in ("String", "StringList") and p["Name"] in batch:
                    batch[p["Name"]]["value"] = p["Value"].split(",") if p["Type"] == "StringList" else p["Value"]
                    batch[p["Name"]].pop("type", None)
        params = [p for p in params if p["value"] is not None]
        if params:
            data["parameters"] = params

    if "streams" in sections:
        k = client(sess, "kinesis")
        streams = []
        for page in k.get_paginator("list_streams").paginate():
            for name in page.get("StreamNames", []):
                summary = k.describe_stream_summary(StreamName=name)["StreamDescriptionSummary"]
                entry = {"name": name}
                if summary.get("OpenShardCount", 1) != 1:
                    entry["shards"] = summary["OpenShardCount"]
                if summary.get("RetentionPeriodHours", 24) != 24:
                    entry["retention_hours"] = summary["RetentionPeriodHours"]
                streams.append(entry)
        if streams:
            data["streams"] = streams

    if "state_machines" in sections:
        import json

        sf = client(sess, "stepfunctions")
        machines = []
        for page in sf.get_paginator("list_state_machines").paginate():
            for m in page.get("stateMachines", []):
                d = sf.describe_state_machine(stateMachineArn=m["stateMachineArn"])
                entry = {"name": m["name"], "definition": localize(json.loads(d["definition"]), account)}
                if d.get("type") == "EXPRESS":
                    entry["express"] = True
                machines.append(entry)
        if machines:
            data["state_machines"] = machines
            notes.append("state machine definitions point at the emulator's account and Region now; "
                         "the resources they use must exist locally")

    if "rules" in sections:
        import json

        ev = client(sess, "events")
        local_targets = {"sqs": queue_names, "sns": {t["name"] for t in data.get("topics", [])},
                         "stepfunctions": {m["name"] for m in data.get("state_machines", [])},
                         "kinesis": {s["name"] for s in data.get("streams", [])}}
        rules = []
        for page in ev.get_paginator("list_rules").paginate():
            for r in page.get("Rules", []):
                if r.get("ManagedBy"):
                    continue
                entry: dict = {"name": r["Name"]}
                if r.get("EventPattern"):
                    entry["pattern"] = json.loads(r["EventPattern"])
                elif r.get("ScheduleExpression"):
                    entry["schedule"] = r["ScheduleExpression"]
                if r.get("State") == "DISABLED":
                    entry["enabled"] = False
                if r.get("Description"):
                    entry["description"] = r["Description"]
                targets = []
                for tp in ev.get_paginator("list_targets_by_rule").paginate(Rule=r["Name"]):
                    for t in tp.get("Targets", []):
                        from .commands.seed import _target_from_arn

                        target = _target_from_arn(t["Arn"])
                        kind = next(iter(target)) if target else None
                        if not target or target[kind] not in local_targets.get(kind, set()):
                            notes.append(f"rule {r['Name']}: left out target {t['Arn'].split(':')[2]}:"
                                         f"{t['Arn'].rsplit(':', 1)[-1]}")
                            continue
                        if t.get("Input"):
                            target["input"] = json.loads(t["Input"])
                        targets.append(target)
                if targets:
                    entry["targets"] = targets
                rules.append(entry)
        if rules:
            data["rules"] = rules

    if "functions" in sections:
        notes.append("functions aren't imported: their code isn't read from the account")
    return data, notes

