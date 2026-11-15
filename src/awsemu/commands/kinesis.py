"""``awsemu kinesis``: data streams."""

from __future__ import annotations

import json
import time
import uuid

import click

from .. import ui
from ..clients import client
from ..context import Ctx, handle_errors, pass_ctx


def decode(data: bytes) -> str:
    """Records as readable text: compact JSON if it parses, UTF-8 if possible, else hex."""
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        return "0x" + data.hex()
    try:
        return json.dumps(json.loads(text), ensure_ascii=False, separators=(", ", ": "))
    except ValueError:
        return text


@click.group()
def kinesis():
    """Kinesis Data Streams."""


@kinesis.command(name="ls")
@pass_ctx
@handle_errors
def ls(c: Ctx):
    """List streams with status and shard count."""
    k = client("kinesis", c.port)
    names = []
    for page in k.get_paginator("list_streams").paginate():
        names += page.get("StreamNames", [])
    rows = []
    for name in names:
        s = k.describe_stream_summary(StreamName=name)["StreamDescriptionSummary"]
        rows.append([name, s.get("StreamStatus", ""), s.get("OpenShardCount", ""),
                     s.get("RetentionPeriodHours", "")])
    ui.table(["stream", "status", "shards", "retention h"], rows,
             empty="No streams. Try 'awsemu kinesis create NAME'.")


@kinesis.command(name="create")
@click.argument("name")
@click.option("--shards", type=click.IntRange(1, 64), default=1, show_default=True)
@pass_ctx
@handle_errors
def create(c: Ctx, name: str, shards: int):
    """Create a stream and wait until it's active."""
    k = client("kinesis", c.port)
    k.create_stream(StreamName=name, ShardCount=shards)
    k.get_waiter("stream_exists").wait(StreamName=name, WaiterConfig={"Delay": 1, "MaxAttempts": 60})
    ui.success(f"created stream {name} ({shards} shard{'s' if shards != 1 else ''})")


@kinesis.command(name="put")
@click.argument("stream")
@click.argument("data", required=False)
@click.option("--file", "file_", type=click.File("rb"), help="Record data from a file ('-' = stdin).")
@click.option("-k", "--key", help="Partition key (default: random).")
@pass_ctx
@handle_errors
def put(c: Ctx, stream: str, data: str | None, file_, key: str | None):
    """Put one record: 'awsemu kinesis put clicks '{"page": "/"}''."""
    if data is None:
        if file_ is None:
            raise click.UsageError("give DATA or --file")
        payload = file_.read()
    else:
        payload = data.encode("utf-8")
    resp = client("kinesis", c.port).put_record(StreamName=stream, Data=payload,
                                                PartitionKey=key or uuid.uuid4().hex)
    ui.success(f"{resp['ShardId']} seq {resp['SequenceNumber']}")


@kinesis.command(name="read")
@click.argument("stream")
@click.option("--from", "start", type=click.Choice(["start", "latest"]), default="start",
              show_default=True, help="Read from the oldest record or only new ones.")
@click.option("-n", "--limit", type=int, default=100, show_default=True, help="Max records (0 = no limit).")
@click.option("-f", "--follow", is_flag=True, help="Keep polling for new records.")
@click.option("--json", "as_json", is_flag=True, help="One JSON object per record.")
@pass_ctx
@handle_errors
def read(c: Ctx, stream: str, start: str, limit: int, follow: bool, as_json: bool):
    """Read records from every shard."""
    k = client("kinesis", c.port)
    shards = []
    for page in k.get_paginator("list_shards").paginate(StreamName=stream):
        shards += [s["ShardId"] for s in page.get("Shards", [])]
    iterator_type = "TRIM_HORIZON" if start == "start" else "LATEST"
    iterators = {s: k.get_shard_iterator(StreamName=stream, ShardId=s,
                                         ShardIteratorType=iterator_type)["ShardIterator"]
                 for s in shards}
    count = 0
    empty_polls = {s: 0 for s in iterators}

    def emit(shard: str, r: dict) -> None:
        if as_json:
            click.echo(json.dumps({"shard": shard, "sequence": r["SequenceNumber"],
                                   "key": r["PartitionKey"], "data": decode(r["Data"]),
                                   "arrived": str(r.get("ApproximateArrivalTimestamp", ""))}))
        else:
            ui.echo(f"{r['PartitionKey'][:12]:<12}  {decode(r['Data'])}")

    try:
        while iterators:
            got_any = False
            for shard, it in list(iterators.items()):
                resp = k.get_records(ShardIterator=it, Limit=min(1000, limit or 1000))
                records = resp.get("Records", [])
                for r in records:
                    emit(shard, r)
                    count += 1
                    if limit and count >= limit:
                        return
                got_any = got_any or bool(records)
                nxt = resp.get("NextShardIterator")
                if not nxt:  # shard closed
                    del iterators[shard]
                    continue
                iterators[shard] = nxt
                if records:
                    empty_polls[shard] = 0
                elif not follow:
                    empty_polls[shard] += 1
                    caught_up = not resp.get("MillisBehindLatest")
                    if caught_up or empty_polls[shard] >= 20:
                        del iterators[shard]
            if follow and not got_any:
                time.sleep(1)
    except KeyboardInterrupt:
        pass
    finally:
        if not as_json and not follow:
            ui.echo(f"{count} record(s)", "muted")


@kinesis.command(name="rm")
@click.argument("stream")
@click.option("-y", "--yes", is_flag=True)
@pass_ctx
@handle_errors
def rm(c: Ctx, stream: str, yes: bool):
    """Delete a stream."""
    if not yes:
        click.confirm(f"Delete stream {stream}?", abort=True)
    client("kinesis", c.port).delete_stream(StreamName=stream, EnforceConsumerDeletion=True)
    ui.success(f"deleted {stream}")
