"""``awsemu s3``: buckets and objects."""

from __future__ import annotations

import sys
from pathlib import Path

import click

from .. import ui
from ..clients import client
from ..completion import complete
from ..context import Ctx, handle_errors, pass_ctx, json_option, yes_option


def split_uri(uri: str) -> tuple[str, str]:
    """``s3://bucket/a/b`` or ``bucket/a/b`` -> ``("bucket", "a/b")``."""
    if uri.startswith("s3://"):
        uri = uri[5:]
    bucket, _, key = uri.partition("/")
    if not bucket:
        raise click.BadParameter(f"no bucket in '{uri}'")
    return bucket, key


def _fmt_time(value) -> str:
    return value.strftime("%Y-%m-%d %H:%M:%S") if hasattr(value, "strftime") else str(value or "")


@click.group()
def s3():
    """S3: buckets and objects."""


@s3.command(name="ls")
@click.argument("target", required=False, shell_complete=complete("s3path"))
@click.option("-r", "--recursive", is_flag=True, help="List every key, not just one level.")
@json_option
@pass_ctx
@handle_errors
def ls(c: Ctx, target: str | None, recursive: bool, as_json: bool):
    """List buckets, or objects in BUCKET[/PREFIX]."""
    s3c = client("s3", c.port)
    if not target:
        buckets = s3c.list_buckets().get("Buckets", [])
        if as_json:
            ui.print_json(buckets)
            return
        ui.table(
            ["bucket", "created"],
            [[b["Name"], _fmt_time(b.get("CreationDate"))] for b in buckets],
            empty="No buckets. Try 'awsemu s3 mb NAME'.",
        )
        return

    bucket, prefix = split_uri(target)
    kwargs = {"Bucket": bucket, "Prefix": prefix}
    if not recursive:
        kwargs["Delimiter"] = "/"
    dirs, objects = [], []
    for page in s3c.get_paginator("list_objects_v2").paginate(**kwargs):
        dirs += [p["Prefix"] for p in page.get("CommonPrefixes", [])]
        objects += page.get("Contents", [])
    if as_json:
        ui.print_json({"prefixes": dirs, "objects": objects})
        return
    rows = [[ui.styled(d, "info"), "", "PRE"] for d in dirs]
    rows += [[o["Key"], _fmt_time(o.get("LastModified")), ui.human_size(o.get("Size"))] for o in objects]
    ui.table(["key", "modified", "size"], rows, title=f"s3://{bucket}/{prefix}", empty="No objects.")
    if objects:
        total = sum(o.get("Size", 0) for o in objects)
        ui.echo(f"{len(objects)} object(s), {ui.human_size(total)}", "muted")


@s3.command(name="mb")
@click.argument("buckets", nargs=-1, required=True)
@pass_ctx
@handle_errors
def mb(c: Ctx, buckets):
    """Create one or more buckets."""
    s3c = client("s3", c.port)
    for name in buckets:
        bucket, _ = split_uri(name)
        s3c.create_bucket(Bucket=bucket)
        ui.success(f"created s3://{bucket}")


@s3.command(name="rb")
@click.argument("bucket", shell_complete=complete("s3path"))
@click.option("--force", is_flag=True, help="Delete all objects first.")
@click.option("-y", "--yes", is_flag=True, help="Don't ask for confirmation.")
@pass_ctx
@handle_errors
def rb(c: Ctx, bucket: str, force: bool, yes: bool):
    """Delete a bucket."""
    bucket, _ = split_uri(bucket)
    s3c = client("s3", c.port)
    if force:
        if not yes:
            click.confirm(f"Delete s3://{bucket} and everything in it?", abort=True)
        deleted = _delete_prefix(s3c, bucket, "")
        if deleted:
            ui.echo(f"deleted {deleted} object(s)", "muted")
    s3c.delete_bucket(Bucket=bucket)
    ui.success(f"removed s3://{bucket}")


def _delete_prefix(s3c, bucket: str, prefix: str) -> int:
    count = 0
    for page in s3c.get_paginator("list_objects_v2").paginate(Bucket=bucket, Prefix=prefix):
        keys = [{"Key": o["Key"]} for o in page.get("Contents", [])]
        if keys:
            s3c.delete_objects(Bucket=bucket, Delete={"Objects": keys, "Quiet": True})
            count += len(keys)
    return count


@s3.command(name="put")
@click.argument("source", type=click.Path(exists=True, dir_okay=True, path_type=Path))
@click.argument("target", shell_complete=complete("s3path"))
@click.option("--content-type", help="Content-Type for the object(s).")
@pass_ctx
@handle_errors
def put(c: Ctx, source: Path, target: str, content_type: str | None):
    """Upload a file (or a folder, recursively) to BUCKET[/KEY].

    If KEY is empty or ends with '/', the file name is appended.
    """
    bucket, key = split_uri(target)
    s3c = client("s3", c.port)
    extra = {"ContentType": content_type} if content_type else None
    if source.is_dir():
        files = [p for p in sorted(source.rglob("*")) if p.is_file()]
        base = key if (not key or key.endswith("/")) else key + "/"
        for f in files:
            dest = base + f.relative_to(source).as_posix()
            s3c.upload_file(str(f), bucket, dest, ExtraArgs=extra)
            ui.echo(f"  {f} → s3://{bucket}/{dest}", "muted")
        ui.success(f"uploaded {len(files)} file(s)")
        return
    if not key or key.endswith("/"):
        key += source.name
    s3c.upload_file(str(source), bucket, key, ExtraArgs=extra)
    ui.success(f"{source} → s3://{bucket}/{key}")


@s3.command(name="get")
@click.argument("source", shell_complete=complete("s3path"))
@click.argument("dest", required=False, type=click.Path(path_type=Path))
@pass_ctx
@handle_errors
def get(c: Ctx, source: str, dest: Path | None):
    """Download BUCKET/KEY to DEST (default: file name in the current folder)."""
    bucket, key = split_uri(source)
    if not key:
        raise click.BadParameter("give a key: BUCKET/KEY")
    dest = dest or Path(key.rsplit("/", 1)[-1])
    if dest.is_dir():
        dest = dest / key.rsplit("/", 1)[-1]
    client("s3", c.port).download_file(bucket, key, str(dest))
    ui.success(f"s3://{bucket}/{key} → {dest}")


@s3.command(name="cat")
@click.argument("source", shell_complete=complete("s3path"))
@pass_ctx
@handle_errors
def cat(c: Ctx, source: str):
    """Print an object to stdout."""
    bucket, key = split_uri(source)
    body = client("s3", c.port).get_object(Bucket=bucket, Key=key)["Body"]
    for chunk in iter(lambda: body.read(64 * 1024), b""):
        sys.stdout.buffer.write(chunk)
    sys.stdout.flush()


@s3.command(name="rm")
@click.argument("target", shell_complete=complete("s3path"))
@click.option("-r", "--recursive", is_flag=True, help="Delete every key under the prefix.")
@yes_option
@pass_ctx
@handle_errors
def rm(c: Ctx, target: str, recursive: bool, yes: bool):
    """Delete an object (or a whole prefix with -r)."""
    bucket, key = split_uri(target)
    s3c = client("s3", c.port)
    if recursive:
        if not yes:
            click.confirm(f"Delete everything under s3://{bucket}/{key}?", abort=True)
        n = _delete_prefix(s3c, bucket, key)
        ui.success(f"deleted {n} object(s)")
        return
    if not key:
        raise click.BadParameter("give a key, or use -r to empty a prefix")
    s3c.delete_object(Bucket=bucket, Key=key)
    ui.success(f"deleted s3://{bucket}/{key}")


@s3.command(name="presign")
@click.argument("target", shell_complete=complete("s3path"))
@click.option(
    "--expires", type=int, default=3600, show_default=True, metavar="SECONDS", help="How long the URL stays valid."
)
@click.option("--put", "for_put", is_flag=True, help="URL for uploading instead of downloading.")
@pass_ctx
@handle_errors
def presign(c: Ctx, target: str, expires: int, for_put: bool):
    """Print a presigned URL for BUCKET/KEY."""
    bucket, key = split_uri(target)
    op = "put_object" if for_put else "get_object"
    url = client("s3", c.port).generate_presigned_url(op, Params={"Bucket": bucket, "Key": key}, ExpiresIn=expires)
    click.echo(url)
