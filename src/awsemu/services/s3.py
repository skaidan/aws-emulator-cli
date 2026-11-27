"""Amazon S3: buckets and objects."""

from __future__ import annotations

import os
from pathlib import Path

from .. import clients
from .. import seed as seedlib
from ..awserrors import client_error, is_error
from . import COMPLETE_MAX, Service, Snapshot, clean

UI_OBJECTS = 50  # objects shown by `awsemu ui`
WATCH_CAP = 1000  # objects counted per bucket by `awsemu watch`


def buckets(c) -> list[str]:
    return [b["Name"] for b in c.list_buckets().get("Buckets", [])]


def details(port, name):
    s3 = clients.client("s3", port)
    resp = s3.list_objects_v2(Bucket=name, MaxKeys=UI_OBJECTS)
    objects = [
        {"Key": o["Key"], "Size": o.get("Size"), "LastModified": o.get("LastModified")}
        for o in resp.get("Contents", [])
    ]
    return {"Bucket": name, f"Objects (first {UI_OBJECTS})": objects, "More": bool(resp.get("IsTruncated"))}


def describe(a, port, full):
    bucket, _, key = a.resource.partition("/")
    s3 = clients.client("s3", port)
    if key:
        return {"Bucket": bucket, "Key": key, **clean(s3.head_object(Bucket=bucket, Key=key))}
    s3.head_bucket(Bucket=bucket)
    count = s3.list_objects_v2(Bucket=bucket, MaxKeys=1000).get("KeyCount", 0)
    return {"Bucket": bucket, "Objects (first 1000)": count, **clean(s3.get_bucket_location(Bucket=bucket))}


def watch(c) -> Snapshot:
    out: Snapshot = {}
    for b in c.list_buckets().get("Buckets", []):
        try:
            out[("bucket", b["Name"])] = c.list_objects_v2(Bucket=b["Name"], MaxKeys=WATCH_CAP).get("KeyCount", 0)
        except client_error() as exc:
            if not is_error(exc, "NoSuchBucket"):
                raise
    return out


def s3_paths(c, incomplete: str) -> list[str]:
    scheme = "s3://" if incomplete.startswith("s3://") else ""
    text = incomplete[len(scheme) :]
    if "/" not in text:
        return [f"{scheme}{b['Name']}/" for b in c.list_buckets().get("Buckets", [])]
    bucket, prefix = text.split("/", 1)
    resp = c.list_objects_v2(Bucket=bucket, Prefix=prefix, Delimiter="/", MaxKeys=COMPLETE_MAX)
    keys = [p["Prefix"] for p in resp.get("CommonPrefixes", [])] + [o["Key"] for o in resp.get("Contents", [])]
    return [f"{scheme}{bucket}/{k}" for k in keys]


INLINE_LIMIT = 64 * 1024


def apply(seed, port, report):
    s3 = clients.client("s3", port)
    for b in seed.section("buckets"):
        name = b["name"]
        try:
            try:
                s3.head_bucket(Bucket=name)
                result = "unchanged"
            except client_error() as exc:
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
            report.add("bucket", name, "failed", clients.describe_error(exc))


def export(port: int, opts: seedlib.ExportOptions) -> list[dict]:
    s3 = clients.client("s3", port)
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
                elif opts.objects_dir is not None:
                    dest = opts.objects_dir / b["Name"] / key
                    dest.parent.mkdir(parents=True, exist_ok=True)
                    s3.download_file(b["Name"], key, str(dest))
                    objects.append({"key": key, "from": os.path.relpath(dest, opts.out_dir)})
                else:
                    opts.notes.append(f"skipped s3://{b['Name']}/{key} (binary or > 64 KiB; use --objects-dir)")
        if objects:
            entry["objects"] = objects
        buckets.append(entry)
    return buckets


SERVICE = Service(
    name="s3",
    label="S3 buckets",
    names=buckets,
    details=details,
    describe=describe,
    watch=watch,
    completions={"s3path": s3_paths},
    seed_section="buckets",
    apply=apply,
    export=export,
)
