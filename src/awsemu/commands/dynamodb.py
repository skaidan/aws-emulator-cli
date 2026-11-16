"""``awsemu dynamodb``: tables and items, with plain JSON in and out.

Items are typed as plain JSON (``{"id": "a", "n": 3}``) and converted to and
from DynamoDB's attribute-value format, so you never write ``{"S": ...}`` by hand.
"""

from __future__ import annotations

import base64
import json
from decimal import Decimal
from typing import Any

import click

from .. import exitcodes
from .. import ui
from ..clients import client
from ..completion import complete
from ..context import Ctx, handle_errors, pass_ctx, json_option, yes_option

TYPES = {"S": "S", "N": "N", "B": "B", "STRING": "S", "NUMBER": "N", "BINARY": "B"}


# --------------------------------------------------------------------------- conversion


def to_attr(value: Any) -> dict:
    if value is None:
        return {"NULL": True}
    if isinstance(value, bool):
        return {"BOOL": value}
    if isinstance(value, (int, float, Decimal)):
        return {"N": str(value)}
    if isinstance(value, str):
        return {"S": value}
    if isinstance(value, (bytes, bytearray)):
        return {"B": bytes(value)}
    if isinstance(value, (list, tuple)):
        return {"L": [to_attr(v) for v in value]}
    if isinstance(value, set):
        items = list(value)
        if all(isinstance(v, str) for v in items):
            return {"SS": items}
        if all(isinstance(v, (int, float, Decimal)) and not isinstance(v, bool) for v in items):
            return {"NS": [str(v) for v in items]}
        raise TypeError("sets must be all strings or all numbers")
    if isinstance(value, dict):
        return {"M": {k: to_attr(v) for k, v in value.items()}}
    raise TypeError(f"can't store {type(value).__name__} in DynamoDB")


def to_item(data: dict) -> dict:
    if not isinstance(data, dict):
        raise click.BadParameter("an item must be a JSON object")
    return {k: to_attr(v) for k, v in data.items()}


def _num(text: str):
    d = Decimal(text)
    return int(d) if d == d.to_integral_value() and "e" not in text.lower() and "." not in text else float(d)


def from_attr(attr: dict) -> Any:
    (kind, value), = attr.items()
    if kind == "S":
        return value
    if kind == "N":
        return _num(value)
    if kind == "BOOL":
        return value
    if kind == "NULL":
        return None
    if kind == "B":
        return base64.b64encode(value if isinstance(value, bytes) else str(value).encode()).decode()
    if kind == "L":
        return [from_attr(v) for v in value]
    if kind == "M":
        return {k: from_attr(v) for k, v in value.items()}
    if kind == "SS":
        return sorted(value)
    if kind == "NS":
        return sorted(_num(v) for v in value)
    if kind == "BS":
        return [base64.b64encode(v).decode() for v in value]
    raise ValueError(f"unknown attribute type {kind}")


def from_item(item: dict) -> dict:
    return {k: from_attr(v) for k, v in item.items()}


def parse_key_spec(spec: str) -> tuple[str, str]:
    """``id``, ``id:S``, ``ts:N`` -> ``(name, type)``."""
    name, _, kind = spec.partition(":")
    kind = TYPES.get((kind or "S").upper())
    if not name or not kind:
        raise click.BadParameter(f"'{spec}' should look like NAME or NAME:S|N|B")
    return name, kind


def _load_json(text: str) -> dict:
    try:
        return json.loads(text, parse_float=Decimal)
    except json.JSONDecodeError as exc:
        raise click.BadParameter(f"invalid JSON: {exc}") from exc


# --------------------------------------------------------------------------- commands


@click.group()
def dynamodb():
    """DynamoDB: tables and items, with plain JSON in and out. Alias: 'awsemu ddb'."""


@dynamodb.command(name="ls")
@json_option
@pass_ctx
@handle_errors
def ls(c: Ctx, as_json: bool):
    """List tables with keys and item counts."""
    d = client("dynamodb", c.port)
    names = []
    for page in d.get_paginator("list_tables").paginate():
        names += page.get("TableNames", [])
    rows, data = [], []
    for name in names:
        t = d.describe_table(TableName=name)["Table"]
        types = {a["AttributeName"]: a["AttributeType"] for a in t.get("AttributeDefinitions", [])}
        key = {k["KeyType"]: k["AttributeName"] for k in t["KeySchema"]}
        data.append({
            "name": name,
            "partition_key": {"name": key.get("HASH"), "type": types.get(key.get("HASH"))},
            "sort_key": {"name": key["RANGE"], "type": types.get(key["RANGE"])} if "RANGE" in key else None,
            "item_count": t.get("ItemCount"),
            "status": t.get("TableStatus"),
        })
        keys = " / ".join(f"{k['AttributeName']} ({k['KeyType'].lower()})" for k in t["KeySchema"])
        rows.append([name, keys, t.get("ItemCount", ""), t.get("TableStatus", "")])
    if as_json:
        ui.print_json(data)
        return
    ui.table(["table", "key", "items", "status"], rows,
             empty="No tables. Try 'awsemu dynamodb create NAME --pk id'.")


@dynamodb.command(name="describe")
@click.argument("table", shell_complete=complete("table"))
@pass_ctx
@handle_errors
def describe(c: Ctx, table: str):
    """Show a table's full description."""
    ui.print_json(client("dynamodb", c.port).describe_table(TableName=table)["Table"])


@dynamodb.command(name="create")
@click.argument("table", shell_complete=complete("table"))
@click.option("--pk", required=True, metavar="NAME[:S|N|B]", help="Partition key (default type S).")
@click.option("--sk", metavar="NAME[:S|N|B]", help="Sort key.")
@pass_ctx
@handle_errors
def create(c: Ctx, table: str, pk: str, sk: str | None):
    """Create an on-demand table: 'awsemu ddb create users --pk id --sk created:N'."""
    keys = [(parse_key_spec(pk), "HASH")]
    if sk:
        keys.append((parse_key_spec(sk), "RANGE"))
    d = client("dynamodb", c.port)
    d.create_table(
        TableName=table,
        BillingMode="PAY_PER_REQUEST",
        AttributeDefinitions=[{"AttributeName": n, "AttributeType": t} for (n, t), _ in keys],
        KeySchema=[{"AttributeName": n, "KeyType": kt} for (n, _), kt in keys],
    )
    d.get_waiter("table_exists").wait(TableName=table, WaiterConfig={"Delay": 1, "MaxAttempts": 30})
    ui.success(f"created table {table}")


@dynamodb.command(name="scan")
@click.argument("table", shell_complete=complete("table"))
@click.option("-n", "--limit", type=int, default=50, show_default=True, help="Max items (0 = all).")
@json_option
@pass_ctx
@handle_errors
def scan(c: Ctx, table: str, limit: int, as_json: bool):
    """Show items in a table."""
    d = client("dynamodb", c.port)
    items: list[dict] = []
    for page in d.get_paginator("scan").paginate(TableName=table):
        items += [from_item(i) for i in page.get("Items", [])]
        if limit and len(items) >= limit:
            items = items[:limit]
            break
    if as_json:
        ui.print_json(items)
        return
    key_names = [k["AttributeName"] for k in d.describe_table(TableName=table)["Table"]["KeySchema"]]
    columns = list(key_names)
    for item in items:
        for k in item:
            if k not in columns:
                columns.append(k)
    columns = columns[:8]

    def cell(v):
        if v is None:
            return ""
        text = v if isinstance(v, str) else json.dumps(v, ensure_ascii=False, default=str)
        return text if len(text) <= 60 else text[:57] + "…"

    ui.table(columns, [[cell(i.get(col)) for col in columns] for i in items],
             title=f"{table} ({len(items)} item(s){' shown' if limit else ''})", empty="No items.")


@dynamodb.command(name="get")
@click.argument("table", shell_complete=complete("table"))
@click.argument("key_json")
@pass_ctx
@handle_errors
def get(c: Ctx, table: str, key_json: str):
    """Get one item: 'awsemu ddb get users '{"id": "u1"}''."""
    resp = client("dynamodb", c.port).get_item(TableName=table, Key=to_item(_load_json(key_json)))
    if "Item" not in resp:
        ui.warn("not found")
        raise SystemExit(exitcodes.FAILED)
    ui.print_json(from_item(resp["Item"]))


@dynamodb.command(name="put")
@click.argument("table", shell_complete=complete("table"))
@click.argument("item_json", required=False)
@click.option("--file", "file_", type=click.File("r"),
              help="JSON object, or a JSON array of objects ('-' = stdin).")
@pass_ctx
@handle_errors
def put(c: Ctx, table: str, item_json: str | None, file_):
    """Write item(s): 'awsemu ddb put users '{"id": "u1", "age": 30}''."""
    if item_json is None and file_ is None:
        raise click.UsageError("give ITEM_JSON or --file")
    data = _load_json(item_json if item_json is not None else file_.read())
    items = data if isinstance(data, list) else [data]
    d = client("dynamodb", c.port)
    for start in range(0, len(items), 25):
        chunk = items[start:start + 25]
        if len(chunk) == 1:
            d.put_item(TableName=table, Item=to_item(chunk[0]))
        else:
            requests = [{"PutRequest": {"Item": to_item(i)}} for i in chunk]
            pending = {table: requests}
            while pending:
                pending = d.batch_write_item(RequestItems=pending).get("UnprocessedItems") or None
    ui.success(f"wrote {len(items)} item(s) to {table}")


@dynamodb.command(name="delete")
@click.argument("table", shell_complete=complete("table"))
@click.argument("key_json")
@pass_ctx
@handle_errors
def delete(c: Ctx, table: str, key_json: str):
    """Delete one item by key."""
    client("dynamodb", c.port).delete_item(TableName=table, Key=to_item(_load_json(key_json)))
    ui.success("deleted")


@dynamodb.command(name="drop")
@click.argument("table", shell_complete=complete("table"))
@yes_option
@pass_ctx
@handle_errors
def drop(c: Ctx, table: str, yes: bool):
    """Delete a table."""
    if not yes:
        click.confirm(f"Delete table {table} and all its items?", abort=True)
    client("dynamodb", c.port).delete_table(TableName=table)
    ui.success(f"dropped {table}")
