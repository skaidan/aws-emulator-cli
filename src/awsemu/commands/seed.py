"""``awsemu seed``: apply, validate and export seed files (see ``awsemu.seed``)."""

from __future__ import annotations

import base64
import hashlib
import json
import os
import ssl
import time
import urllib.request
from datetime import datetime
from pathlib import Path

import click

from .. import exitcodes
from .. import seed as seedlib
from .. import ui
from ..clients import client
from ..context import Ctx, handle_errors, pass_ctx
from ..runtime import RuntimeErrorWithHint
from ._common import allow_lambda, allow_queue, arn, ensure_service_role, is_error
from .dynamodb import from_item, to_item

INLINE_LIMIT = 64 * 1024


class Report:
    def __init__(self):
        self.rows: list[list] = []
        self.failures = 0

    def add(self, kind: str, name: str, result: str, detail: str = "") -> None:
        style = {"created": "ok", "updated": "info", "unchanged": "muted", "failed": "error"}.get(result)
        if result == "failed":
            self.failures += 1
        self.rows.append([kind, name, ui.styled(result, style), detail])


# =========================================================================== apply


def _apply_buckets(seed, port, report):
    s3 = client("s3", port)
    for b in seed.section("buckets"):
        name = b["name"]
        try:
            try:
                s3.head_bucket(Bucket=name)
                result = "unchanged"
            except Exception as exc:
                if not is_error(exc, "404", "NoSuchBucket", "NotFound"):
                    raise
                s3.create_bucket(Bucket=name)
                result = "created"
            written = 0
            for obj in b.get("objects") or []:
                for key, payload in seedlib.object_payloads(obj, seed.base_dir):
                    if isinstance(payload, Path):
                        s3.upload_file(str(payload), name, key)
                    else:
                        s3.put_object(Bucket=name, Key=key, Body=payload)
                    written += 1
            if written and result == "unchanged":
                result = "updated"
            report.add("bucket", name, result, f"{written} object(s) written" if written else "")
        except Exception as exc:
            report.add("bucket", name, "failed", _err(exc))


def _queue_attrs(q: dict) -> dict[str, str]:
    attrs = {}
    if q.get("fifo"):
        attrs["FifoQueue"] = "true"
    if "content_dedup" in q:
        attrs["ContentBasedDeduplication"] = "true" if q["content_dedup"] else "false"
    if "visibility_timeout" in q:
        attrs["VisibilityTimeout"] = str(q["visibility_timeout"])
    if "delay" in q:
        attrs["DelaySeconds"] = str(q["delay"])
    return attrs


def _apply_queues(seed, port, report):
    sqs = client("sqs", port)
    urls: dict[str, str] = {}
    results: dict[str, str] = {}
    for q in seed.section("queues"):
        name = q["name"]
        attrs = _queue_attrs(q)
        try:
            try:
                url = sqs.get_queue_url(QueueName=name)["QueueUrl"]
                current = sqs.get_queue_attributes(QueueUrl=url, AttributeNames=["All"])["Attributes"]
                changes = {k: v for k, v in attrs.items() if k != "FifoQueue" and current.get(k) != v}
                if changes:
                    sqs.set_queue_attributes(QueueUrl=url, Attributes=changes)
                results[name] = "updated" if changes else "unchanged"
            except Exception as exc:
                if not is_error(exc, "NonExistentQueue", "QueueDoesNotExist"):
                    raise
                url = sqs.create_queue(QueueName=name, Attributes=attrs)["QueueUrl"]
                results[name] = "created"
            urls[name] = url
        except Exception as exc:
            report.add("queue", name, "failed", _err(exc))
    # Dead-letter queues once every queue exists.
    for q in seed.section("queues"):
        name = q["name"]
        if name not in urls:
            continue
        detail = ""
        if q.get("dlq"):
            try:
                dlq_url = urls.get(q["dlq"]) or sqs.get_queue_url(QueueName=q["dlq"])["QueueUrl"]
                dlq_arn = sqs.get_queue_attributes(QueueUrl=dlq_url, AttributeNames=["QueueArn"])["Attributes"]["QueueArn"]
                wanted = {"deadLetterTargetArn": dlq_arn, "maxReceiveCount": int(q.get("max_receive", 5))}
                current = sqs.get_queue_attributes(QueueUrl=urls[name], AttributeNames=["RedrivePolicy"]
                                                   ).get("Attributes", {}).get("RedrivePolicy")
                current_policy = json.loads(current) if current else {}
                if {k: str(v) for k, v in current_policy.items()} != {k: str(v) for k, v in wanted.items()}:
                    sqs.set_queue_attributes(QueueUrl=urls[name], Attributes={"RedrivePolicy": json.dumps(wanted)})
                    if results[name] == "unchanged":
                        results[name] = "updated"
                detail = f"dlq → {q['dlq']}"
            except Exception as exc:
                report.add("queue", name, "failed", f"dlq: {_err(exc)}")
                continue
        report.add("queue", name, results[name], detail)


def _apply_tables(seed, port, report):
    ddb = client("dynamodb", port)
    for t in seed.section("tables"):
        name = t["name"]
        keys = [(seedlib.key_spec(t["pk"]), "HASH")]
        if t.get("sk"):
            keys.append((seedlib.key_spec(t["sk"]), "RANGE"))
        wanted_schema = [{"AttributeName": n, "KeyType": kt} for (n, _), kt in keys]
        try:
            try:
                current = ddb.describe_table(TableName=name)["Table"]
                if current["KeySchema"] != wanted_schema:
                    have = ", ".join(f"{k['AttributeName']} ({k['KeyType'].lower()})" for k in current["KeySchema"])
                    raise RuntimeErrorWithHint(f"exists with a different key: {have}")
                result = "unchanged"
            except RuntimeErrorWithHint:
                raise
            except Exception as exc:
                if not is_error(exc, "ResourceNotFound"):
                    raise
                ddb.create_table(TableName=name, BillingMode="PAY_PER_REQUEST",
                                 AttributeDefinitions=[{"AttributeName": n, "AttributeType": k}
                                                       for (n, k), _ in keys],
                                 KeySchema=wanted_schema)
                ddb.get_waiter("table_exists").wait(TableName=name,
                                                    WaiterConfig={"Delay": 1, "MaxAttempts": 30})
                result = "created"
            items = seedlib.load_items(t, seed.base_dir)
            for i in range(0, len(items), 25):
                pending = {name: [{"PutRequest": {"Item": to_item(it)}} for it in items[i:i + 25]]}
                while pending:
                    pending = ddb.batch_write_item(RequestItems=pending).get("UnprocessedItems") or None
            if items and result == "unchanged":
                result = "updated"
            report.add("table", name, result, f"{len(items)} item(s) written" if items else "")
        except Exception as exc:
            report.add("table", name, "failed", _err(exc))


def _apply_topics(seed, port, report):
    sns = client("sns", port)
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
                    target = allow_queue(client("sqs", port), sub["sqs"], "sns.amazonaws.com", topic, sid)
                else:
                    protocol = "lambda"
                    target = allow_lambda(client("lambda", port), sub["lambda"], "sns.amazonaws.com", topic, sid)
                wanted = {"RawMessageDelivery": "true" if sub.get("raw") else "false"}
                if sub.get("filter") is not None:
                    wanted["FilterPolicy"] = json.dumps(sub["filter"])
                match = next((s for s in subs if s["Protocol"] == protocol and s["Endpoint"] == target), None)
                if match is None:
                    sns.subscribe(TopicArn=topic, Protocol=protocol, Endpoint=target,
                                  Attributes=wanted, ReturnSubscriptionArn=True)
                    result = "updated" if result == "unchanged" else result
                else:
                    current = sns.get_subscription_attributes(SubscriptionArn=match["SubscriptionArn"])["Attributes"]
                    for k, val in wanted.items():
                        same = (json.loads(current[k]) == json.loads(val)) if k == "FilterPolicy" and current.get(k) \
                            else current.get(k, "false" if k == "RawMessageDelivery" else None) == val
                        if not same:
                            sns.set_subscription_attributes(SubscriptionArn=match["SubscriptionArn"],
                                                            AttributeName=k, AttributeValue=val)
                            result = "updated" if result == "unchanged" else result
                details.append(f"→ {protocol}:{sub.get('sqs') or sub.get('lambda')}")
            report.add("topic", name, result, ", ".join(details))
        except Exception as exc:
            report.add("topic", name, "failed", _err(exc))


def _apply_secrets(seed, port, report):
    sm = client("secretsmanager", port)
    for s in seed.section("secrets"):
        name = s["name"]
        value = seedlib.secret_string(s["value"])
        try:
            try:
                current = sm.get_secret_value(SecretId=name).get("SecretString")
                if current == value:
                    result = "unchanged"
                else:
                    sm.put_secret_value(SecretId=name, SecretString=value)
                    result = "updated"
                if s.get("description"):
                    sm.update_secret(SecretId=name, Description=s["description"])
            except Exception as exc:
                if not is_error(exc, "ResourceNotFound"):
                    raise
                kwargs = {"Name": name, "SecretString": value}
                if s.get("description"):
                    kwargs["Description"] = s["description"]
                sm.create_secret(**kwargs)
                result = "created"
            report.add("secret", name, result)
        except Exception as exc:
            report.add("secret", name, "failed", _err(exc))


def _apply_parameters(seed, port, report):
    ssm = client("ssm", port)
    for p in seed.section("parameters"):
        name = p["name"]
        value, kind = seedlib.parameter_value(p)
        try:
            try:
                cur = ssm.get_parameter(Name=name, WithDecryption=True)["Parameter"]
                if cur.get("Value") == value and cur.get("Type") == kind:
                    report.add("parameter", name, "unchanged")
                    continue
                result = "updated"
            except Exception as exc:
                if not is_error(exc, "ParameterNotFound"):
                    raise
                result = "created"
            kwargs = {"Name": name, "Value": value, "Type": kind, "Overwrite": True}
            if p.get("description"):
                kwargs["Description"] = p["description"]
            ssm.put_parameter(**kwargs)
            report.add("parameter", name, result, kind if kind != "String" else "")
        except Exception as exc:
            report.add("parameter", name, "failed", _err(exc))


def _apply_streams(seed, port, report):
    k = client("kinesis", port)
    for st in seed.section("streams"):
        name, shards = st["name"], st.get("shards", 1)
        try:
            changes = []
            try:
                summary = k.describe_stream_summary(StreamName=name)["StreamDescriptionSummary"]
                result = "unchanged"
            except Exception as exc:
                if not is_error(exc, "ResourceNotFound"):
                    raise
                k.create_stream(StreamName=name, ShardCount=shards)
                k.get_waiter("stream_exists").wait(StreamName=name, WaiterConfig={"Delay": 1, "MaxAttempts": 60})
                summary = k.describe_stream_summary(StreamName=name)["StreamDescriptionSummary"]
                result = "created"
            if result == "unchanged" and summary.get("OpenShardCount") != shards:
                k.update_shard_count(StreamName=name, TargetShardCount=shards, ScalingType="UNIFORM_SCALING")
                k.get_waiter("stream_exists").wait(StreamName=name, WaiterConfig={"Delay": 1, "MaxAttempts": 60})
                changes.append(f"{shards} shard(s)")
            hours = st.get("retention_hours")
            if hours and summary.get("RetentionPeriodHours") != hours:
                if hours > summary.get("RetentionPeriodHours", 24):
                    k.increase_stream_retention_period(StreamName=name, RetentionPeriodHours=hours)
                else:
                    k.decrease_stream_retention_period(StreamName=name, RetentionPeriodHours=hours)
                changes.append(f"retention {hours} h")
            if changes and result == "unchanged":
                result = "updated"
            report.add("stream", name, result, ", ".join(changes))
        except Exception as exc:
            report.add("stream", name, "failed", _err(exc))


def _function_config(fn: dict, handler: str | None, runtime: str | None) -> dict:
    config: dict = {}
    if handler:
        config["Handler"] = handler
    if runtime:
        config["Runtime"] = runtime
    for key, field in (("timeout", "Timeout"), ("memory", "MemorySize"), ("description", "Description")):
        if key in fn:
            config[field] = fn[key]
    if "env" in fn:
        config["Environment"] = {"Variables": {k: str(v) for k, v in (fn["env"] or {}).items()}}
    return config


def _config_changes(current: dict, wanted: dict) -> dict:
    changed = {}
    for key, value in wanted.items():
        if key == "Environment":
            if (current.get("Environment") or {}).get("Variables", {}) != value["Variables"]:
                changed[key] = value
        elif current.get(key) != value:
            changed[key] = value
    return changed


def _apply_triggers(fn: dict, lam, port: int) -> list[str]:
    """Event source mappings from SQS queues and Kinesis streams to the function."""
    wanted = fn.get("triggers") or []
    if not wanted:
        return []
    current = {}
    for page in lam.get_paginator("list_event_source_mappings").paginate(FunctionName=fn["name"]):
        for m in page.get("EventSourceMappings", []):
            current[m["EventSourceArn"]] = m
    changes = []
    for tr in wanted:
        if "sqs" in tr:
            source = arn("sqs", tr["sqs"])
            label = f"sqs:{tr['sqs']}"
        else:
            source = arn("kinesis", f"stream/{tr['kinesis']}")
            label = f"kinesis:{tr['kinesis']}"
        enabled = tr.get("enabled", True)
        mapping = current.get(source)
        if mapping is None:
            kwargs = {"EventSourceArn": source, "FunctionName": fn["name"], "Enabled": enabled}
            if "batch_size" in tr:
                kwargs["BatchSize"] = tr["batch_size"]
            if "kinesis" in tr:
                kwargs["StartingPosition"] = tr.get("starting_position", "TRIM_HORIZON")
            lam.create_event_source_mapping(**kwargs)
            changes.append(f"trigger {label}")
            continue
        update = {}
        if "batch_size" in tr and mapping.get("BatchSize") != tr["batch_size"]:
            update["BatchSize"] = tr["batch_size"]
        state = mapping.get("State", "Enabled")
        if enabled != (state in ("Enabled", "Enabling", "Creating", "Updating")):
            update["Enabled"] = enabled
        if update:
            lam.update_event_source_mapping(UUID=mapping["UUID"], **update)
            changes.append(f"trigger {label}")
    return changes


def _apply_functions(seed, port, report):
    from .lambda_ import _exists, _wait, build_zip, ensure_role, guess_handler_and_runtime

    lam = client("lambda", port)
    for fn in seed.section("functions"):
        name = fn["name"]
        try:
            source = seed.base_dir / fn["code"]
            guessed_handler, guessed_runtime = guess_handler_and_runtime(source)
            handler = fn.get("handler") or guessed_handler
            runtime = fn.get("runtime") or guessed_runtime
            code = build_zip(source)
            sha = base64.b64encode(hashlib.sha256(code).digest()).decode()
            exists = _exists(lam, name)
            # An existing function keeps its handler/runtime unless the seed sets them
            wanted = _function_config(fn, fn.get("handler") or (None if exists else handler),
                                      fn.get("runtime") or (None if exists else runtime))
            changes = []
            if exists:
                current = lam.get_function_configuration(FunctionName=name)
                if current.get("CodeSha256") != sha:
                    lam.update_function_code(FunctionName=name, ZipFile=code)
                    _wait(lam, "function_updated_v2", name)
                    changes.append("code")
                diff = _config_changes(current, wanted)
                if diff:
                    lam.update_function_configuration(FunctionName=name, **diff)
                    _wait(lam, "function_updated_v2", name)
                    changes += [k.lower() for k in diff]
                result = "updated" if changes else "unchanged"
            else:
                if not handler or not runtime:
                    report.add("function", name, "failed",
                               "couldn't guess the handler/runtime from the code; set 'handler' and 'runtime'")
                    continue
                lam.create_function(FunctionName=name, Code={"ZipFile": code},
                                    Role=ensure_role(client("iam", port)), **wanted)
                _wait(lam, "function_active_v2", name)
                result = "created"
            triggers = _apply_triggers(fn, lam, port)
            if triggers and result == "unchanged":
                result = "updated"
            detail = ", ".join(([f"{runtime} {handler}"] if result == "created" else changes) + triggers)
            report.add("function", name, result, detail)
        except Exception as exc:
            report.add("function", name, "failed", _err(exc))


def _apply_state_machines(seed, port, report):
    from .sfn import DEFAULT_ROLE_NAME

    sf = client("stepfunctions", port)
    for sm in seed.section("state_machines"):
        name = sm["name"]
        try:
            definition = seedlib.read_definition(sm, seed.base_dir)
            kind = "EXPRESS" if sm.get("express") else "STANDARD"
            target = arn("states", f"stateMachine:{name}")
            try:
                current = sf.describe_state_machine(stateMachineArn=target)
            except Exception as exc:
                if not is_error(exc, "StateMachineDoesNotExist", "ResourceNotFound"):
                    raise
                role = ensure_service_role(client("iam", port), DEFAULT_ROLE_NAME, "states.amazonaws.com",
                                           "Created by awsemu for Step Functions")
                sf.create_state_machine(name=name, definition=json.dumps(definition), roleArn=role, type=kind)
                report.add("state_machine", name, "created", kind.lower())
                continue
            if current.get("type", "STANDARD") != kind:
                report.add("state_machine", name, "failed",
                           f"it's {current.get('type')} and the seed says {kind}: the type can't change; "
                           "delete it first (awsemu sfn rm)")
                continue
            if json.loads(current["definition"]) != definition:
                sf.update_state_machine(stateMachineArn=target, definition=json.dumps(definition))
                report.add("state_machine", name, "updated", "definition")
            else:
                report.add("state_machine", name, "unchanged")
        except Exception as exc:
            report.add("state_machine", name, "failed", _err(exc))


def _target(kind: str, name: str, rule_arn: str, port: int) -> dict:
    sid = f"awsemu-events-{rule_arn.rsplit('/', 1)[-1]}"
    if kind == "sqs":
        return {"Arn": allow_queue(client("sqs", port), name, "events.amazonaws.com", rule_arn, sid)}
    if kind == "lambda":
        return {"Arn": allow_lambda(client("lambda", port), name, "events.amazonaws.com", rule_arn, sid)}
    if kind == "sns":
        return {"Arn": arn("sns", name)}
    role = ensure_service_role(client("iam", port), "awsemu-events-role", "events.amazonaws.com",
                               "Created by awsemu for EventBridge targets")
    if kind == "stepfunctions":
        return {"Arn": arn("states", f"stateMachine:{name}"), "RoleArn": role}
    return {"Arn": arn("kinesis", f"stream/{name}"), "RoleArn": role}


def _apply_rules(seed, port, report):
    ev = client("events", port)
    for r in seed.section("rules"):
        name, bus = r["name"], r.get("bus", "default")
        try:
            if bus != "default":
                try:
                    ev.describe_event_bus(Name=bus)
                except Exception as exc:
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
                same = (current.get("State") == wanted["State"]
                        and current.get("ScheduleExpression") == wanted.get("ScheduleExpression")
                        and (json.loads(current["EventPattern"]) if current.get("EventPattern") else None)
                        == r.get("pattern")
                        and (not r.get("description") or current.get("Description") == r["description"]))
                result = "unchanged"
                if not same:
                    ev.put_rule(**wanted)
                    result = "updated"
                rule_arn = current["Arn"]
            except Exception as exc:
                if not is_error(exc, "ResourceNotFound"):
                    raise
                rule_arn = ev.put_rule(**wanted)["RuleArn"]
                result = "created"
            existing = {}
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
            report.add("rule", name, "failed", _err(exc))


def _err(exc: Exception) -> str:
    response = getattr(exc, "response", None)
    if isinstance(response, dict) and "Error" in response:
        e = response["Error"]
        return f"{e.get('Code')}: {e.get('Message', '')}".strip(": ")
    return str(exc)


APPLY_ORDER = [  # what others point at first: queues and streams, then functions, then the wiring
    ("buckets", _apply_buckets), ("queues", _apply_queues), ("tables", _apply_tables),
    ("streams", _apply_streams), ("secrets", _apply_secrets), ("parameters", _apply_parameters),
    ("functions", _apply_functions), ("state_machines", _apply_state_machines),
    ("topics", _apply_topics), ("rules", _apply_rules),
]


def apply_seed(seed: seedlib.Seed, port: int) -> Report:
    report = Report()
    for section, fn in APPLY_ORDER:
        if seed.section(section):
            fn(seed, port, report)
    return report


def load_or_fail(path: str) -> seedlib.Seed:
    try:
        seed = seedlib.load_file(path)
    except seedlib.SeedError as exc:
        for p in exc.problems:
            ui.error(p.format(exc.source))
        raise SystemExit(exitcodes.USAGE)
    for w in seed.warnings:
        ui.warn(w)
    return seed


def run_apply(seed: seedlib.Seed, port: int) -> None:
    """Apply and print the report; exits 1 if anything failed."""
    started = time.monotonic()
    report = apply_seed(seed, port)
    ui.table(["kind", "name", "result", "detail"], report.rows, title=f"seed {seed.source}")
    counts: dict[str, int] = {}
    for row in report.rows:
        key = str(row[2])
        counts[key] = counts.get(key, 0) + 1
    summary = ", ".join(f"{n} {k}" for k, n in counts.items())
    if report.failures:
        ui.error(f"seed applied with errors ({summary})")
        raise SystemExit(exitcodes.FAILED)
    ui.success(f"seed applied in {time.monotonic() - started:.1f}s ({summary})")


# =========================================================================== export


def _export(port: int, sections: set[str], objects_dir: Path | None, out_dir: Path,
            include_secrets: bool) -> tuple[dict, list[str]]:
    data: dict = {"version": seedlib.VERSION}
    notes: list[str] = []

    if "buckets" in sections:
        s3 = client("s3", port)
        buckets = []
        for b in s3.list_buckets().get("Buckets", []):
            entry: dict = {"name": b["Name"]}
            objects = []
            for page in s3.get_paginator("list_objects_v2").paginate(Bucket=b["Name"]):
                for o in page.get("Contents", []):
                    key = o["Key"]
                    body = None
                    if o.get("Size", 0) <= INLINE_LIMIT:
                        raw = s3.get_object(Bucket=b["Name"], Key=key)["Body"].read()
                        try:
                            body = raw.decode("utf-8")
                        except UnicodeDecodeError:
                            body = None
                    if body is not None:
                        objects.append({"key": key, "content": body})
                    elif objects_dir is not None:
                        dest = objects_dir / b["Name"] / key
                        dest.parent.mkdir(parents=True, exist_ok=True)
                        s3.download_file(b["Name"], key, str(dest))
                        objects.append({"key": key, "from": os.path.relpath(dest, out_dir)})
                    else:
                        notes.append(f"skipped s3://{b['Name']}/{key} (binary or > 64 KiB; use --objects-dir)")
            if objects:
                entry["objects"] = objects
            buckets.append(entry)
        if buckets:
            data["buckets"] = buckets

    if "queues" in sections:
        sqs = client("sqs", port)
        queues = []
        for url in sqs.list_queues().get("QueueUrls", []):
            a = sqs.get_queue_attributes(QueueUrl=url, AttributeNames=["All"])["Attributes"]
            entry = {"name": url.rsplit("/", 1)[-1]}
            if a.get("FifoQueue") == "true":
                entry["fifo"] = True
                if a.get("ContentBasedDeduplication") == "true":
                    entry["content_dedup"] = True
            if a.get("VisibilityTimeout", "30") != "30":
                entry["visibility_timeout"] = int(a["VisibilityTimeout"])
            if a.get("DelaySeconds", "0") != "0":
                entry["delay"] = int(a["DelaySeconds"])
            if a.get("RedrivePolicy"):
                rp = json.loads(a["RedrivePolicy"])
                entry["dlq"] = rp["deadLetterTargetArn"].rsplit(":", 1)[-1]
                entry["max_receive"] = int(rp.get("maxReceiveCount", 5))
            queues.append(entry)
        # DLQs first, for readability (apply doesn't care).
        dlqs = {q.get("dlq") for q in queues}
        queues.sort(key=lambda q: (q["name"] not in dlqs, q["name"]))
        if queues:
            data["queues"] = queues

    if "tables" in sections:
        ddb = client("dynamodb", port)
        tables = []
        for page in ddb.get_paginator("list_tables").paginate():
            for name in page.get("TableNames", []):
                t = ddb.describe_table(TableName=name)["Table"]
                types = {d["AttributeName"]: d["AttributeType"] for d in t["AttributeDefinitions"]}
                entry = {"name": name}
                for k in t["KeySchema"]:
                    spec = k["AttributeName"] + ("" if types[k["AttributeName"]] == "S" else f":{types[k['AttributeName']]}")
                    entry["pk" if k["KeyType"] == "HASH" else "sk"] = spec
                items = []
                for p in ddb.get_paginator("scan").paginate(TableName=name):
                    items += [from_item(i) for i in p.get("Items", [])]
                if items:
                    entry["items"] = items
                tables.append(entry)
        if tables:
            data["tables"] = tables

    if "topics" in sections:
        sns = client("sns", port)
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
                            notes.append(f"skipped {s['Protocol']} subscription on {entry['name']}")
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
        if topics:
            data["topics"] = topics

    if "secrets" in sections and include_secrets:
        sm = client("secretsmanager", port)
        secrets = []
        for page in sm.get_paginator("list_secrets").paginate():
            for s in page.get("SecretList", []):
                value = sm.get_secret_value(SecretId=s["Name"]).get("SecretString")
                if value is None:
                    notes.append(f"skipped binary secret {s['Name']}")
                    continue
                try:
                    parsed = json.loads(value)
                    value = parsed if isinstance(parsed, (dict, list)) else value
                except ValueError:
                    pass
                entry = {"name": s["Name"], "value": value}
                if s.get("Description"):
                    entry["description"] = s["Description"]
                secrets.append(entry)
        if secrets:
            data["secrets"] = secrets

    if "parameters" in sections:
        ssm = client("ssm", port)
        params = []
        described = []
        for page in ssm.get_paginator("describe_parameters").paginate():
            described += page.get("Parameters", [])
        values = {}
        names = [p["Name"] for p in described]
        for i in range(0, len(names), 10):
            for p in ssm.get_parameters(Names=names[i:i + 10], WithDecryption=True).get("Parameters", []):
                values[p["Name"]] = p
        for d in described:
            p = values.get(d["Name"])
            if p is None:
                continue
            if p["Type"] == "SecureString" and not include_secrets:
                continue
            entry = {"name": d["Name"]}
            if p["Type"] == "StringList":
                entry["value"] = p["Value"].split(",")
            else:
                entry["value"] = p["Value"]
                if p["Type"] != "String":
                    entry["type"] = p["Type"]
            if d.get("Description"):
                entry["description"] = d["Description"]
            params.append(entry)
        if params:
            data["parameters"] = params

    if "streams" in sections:
        k = client("kinesis", port)
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

    if "functions" in sections:
        lam = client("lambda", port)
        functions = []
        for page in lam.get_paginator("list_functions").paginate():
            for f in page.get("Functions", []):
                name = f["FunctionName"]
                if objects_dir is None:
                    notes.append(f"skipped function {name} (its code needs a place: use --objects-dir)")
                    continue
                dest = objects_dir / "functions" / f"{name}.zip"
                try:
                    _download_code(lam.get_function(FunctionName=name)["Code"]["Location"], dest, port)
                except Exception as exc:  # noqa: BLE001
                    notes.append(f"skipped function {name}: couldn't download its code ({exc})")
                    continue
                entry = {"name": name, "code": os.path.relpath(dest, out_dir)}
                for key, field in (("handler", "Handler"), ("runtime", "Runtime")):
                    if f.get(field):
                        entry[key] = f[field]
                if f.get("Timeout", 3) != 3:
                    entry["timeout"] = f["Timeout"]
                if f.get("MemorySize", 128) != 128:
                    entry["memory"] = f["MemorySize"]
                if f.get("Description"):
                    entry["description"] = f["Description"]
                variables = (f.get("Environment") or {}).get("Variables")
                if variables:
                    entry["env"] = variables
                triggers = []
                for mp in lam.get_paginator("list_event_source_mappings").paginate(FunctionName=name):
                    for m in mp.get("EventSourceMappings", []):
                        source = m["EventSourceArn"]
                        if ":sqs:" in source:
                            tr = {"sqs": source.rsplit(":", 1)[-1]}
                            default_batch = 10
                        elif ":kinesis:" in source:
                            tr = {"kinesis": source.rsplit("/", 1)[-1]}
                            default_batch = 100
                            if m.get("StartingPosition", "TRIM_HORIZON") != "TRIM_HORIZON":
                                tr["starting_position"] = m["StartingPosition"]
                        else:
                            notes.append(f"skipped trigger {source} of {name} (only SQS and Kinesis)")
                            continue
                        if m.get("BatchSize", default_batch) != default_batch:
                            tr["batch_size"] = m["BatchSize"]
                        if m.get("State") in ("Disabled", "Disabling"):
                            tr["enabled"] = False
                        triggers.append(tr)
                if triggers:
                    entry["triggers"] = triggers
                functions.append(entry)
        if functions:
            data["functions"] = functions

    if "state_machines" in sections:
        sf = client("stepfunctions", port)
        machines = []
        for page in sf.get_paginator("list_state_machines").paginate():
            for m in page.get("stateMachines", []):
                d = sf.describe_state_machine(stateMachineArn=m["stateMachineArn"])
                entry = {"name": m["name"], "definition": json.loads(d["definition"])}
                if d.get("type") == "EXPRESS":
                    entry["express"] = True
                machines.append(entry)
        if machines:
            data["state_machines"] = machines

    if "rules" in sections:
        ev = client("events", port)
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
                            target = _target_from_arn(t["Arn"])
                            if target is None:
                                notes.append(f"skipped target {t['Arn']} of rule {r['Name']}")
                                continue
                            if t.get("Input"):
                                target["input"] = json.loads(t["Input"])
                            targets.append(target)
                    if targets:
                        entry["targets"] = targets
                    rules.append(entry)
        if rules:
            data["rules"] = rules

    return data, notes


def _target_from_arn(value: str) -> dict | None:
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


def _download_code(location: str, dest: Path, port: int) -> None:
    """Fetch a function's code zip from the URL Lambda returns (served by the emulator)."""
    from ..paths import InstanceFiles

    ctx = ssl.create_default_context(cafile=str(InstanceFiles(port).ca))
    with urllib.request.urlopen(location, context=ctx, timeout=60) as resp:  # noqa: S310 - the emulator's URL
        data = resp.read()
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(data)


# =========================================================================== commands


@click.group()
def seed():
    """Seed files: the same starting data after every start or reset."""


@seed.command(name="apply")
@click.argument("file", type=click.Path(dir_okay=False))
@pass_ctx
@handle_errors
def apply_cmd(c: Ctx, file: str):
    """Create what FILE describes. Safe to run again: existing things are updated or left alone.

    \b
      awsemu seed apply seed.yaml
      awsemu start --seed seed.yaml     # start and apply in one step
      awsemu reset --seed seed.yaml     # empty state + seed
    """
    run_apply(load_or_fail(file), c.port)


@seed.command(name="validate")
@click.argument("file", type=click.Path(dir_okay=False))
def validate_cmd(file: str):
    """Check FILE without touching the emulator (errors show line and field)."""
    s = load_or_fail(file)
    counts = ", ".join(f"{n} {k}" for k, n in s.count().items()) or "nothing"
    ui.success(f"{file} is valid: {counts}")


@seed.command(name="export")
@click.option("-o", "--output", type=click.Path(dir_okay=False, path_type=Path),
              help="Write to this file (default: stdout).")
@click.option("--objects-dir", type=click.Path(file_okay=False, path_type=Path),
              help="Save binary or large S3 objects, and Lambda functions' code, here (referenced from the seed).")
@click.option("--no-secrets", is_flag=True, help="Leave out secrets and SecureString parameters.")
@click.option("-s", "--section", "sections", multiple=True, type=click.Choice(seedlib.SECTIONS),
              help="Only these sections. Repeatable.")
@pass_ctx
@handle_errors
def export_cmd(c: Ctx, output: Path | None, objects_dir: Path | None, no_secrets: bool, sections):
    """Write what's in the emulator now as a seed file.

    Secret values and SecureString parameters are exported in plain text
    unless --no-secrets.
    """
    out_dir = (output.parent if output else Path(".")).resolve()
    data, notes = _export(c.port, set(sections) or set(seedlib.SECTIONS),
                          objects_dir.resolve() if objects_dir else None, out_dir, not no_secrets)
    header = (f"# Seed exported by awsemu from port {c.port} on "
              f"{datetime.now().strftime('%Y-%m-%d %H:%M')}.\n"
              "# Apply it with: awsemu seed apply <this file>\n")
    text = header + seedlib.dump(data)
    for n in notes:
        ui.warn(n)
    if output:
        output.write_text(text, encoding="utf-8")
        counts = ", ".join(f"{len(v)} {k}" for k, v in data.items() if isinstance(v, list)) or "nothing"
        ui.success(f"wrote {output} ({counts})")
        if not no_secrets and (data.get("secrets") or any(p.get("type") == "SecureString"
                                                          for p in data.get("parameters", []))):
            ui.warn(f"{output} contains secret values in plain text")
    else:
        click.echo(text, nl=False)
