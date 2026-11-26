"""Amazon S3: buckets and objects."""

from __future__ import annotations

from ..awserrors import client_error, is_error
from .. import clients
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


SERVICE = Service(
    name="s3",
    label="S3 buckets",
    names=buckets,
    details=details,
    describe=describe,
    watch=watch,
    completions={"s3path": s3_paths},
)
