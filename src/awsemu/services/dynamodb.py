"""Amazon DynamoDB: tables and items."""

from __future__ import annotations

from ..awserrors import client_error, is_error
from .. import clients
from . import COMPLETE_MAX, Service, Snapshot, pages

UI_ITEMS = 20  # items shown by `awsemu ui`
WATCH_CAP = 10000  # items counted per table by `awsemu watch`


def tables(c) -> list[str]:
    names: list[str] = []
    kwargs: dict = {}
    while True:
        page = c.list_tables(**kwargs)
        names += page.get("TableNames", [])
        if not page.get("LastEvaluatedTableName"):
            return names
        kwargs["ExclusiveStartTableName"] = page["LastEvaluatedTableName"]


def details(port, name):
    from ..commands.dynamodb import from_item

    d = clients.client("dynamodb", port)
    table = d.describe_table(TableName=name)["Table"]
    items = [from_item(i) for i in d.scan(TableName=name, Limit=UI_ITEMS).get("Items", [])]
    return {"Table": table, f"Items (first {UI_ITEMS})": items}


def describe(a, port, full):
    return clients.client("dynamodb", port).describe_table(TableName=a.rest.split("/", 1)[0])["Table"]


def watch(c) -> Snapshot:
    out: Snapshot = {}
    for page in c.get_paginator("list_tables").paginate():
        for name in page.get("TableNames", []):
            count, kwargs = 0, {"TableName": name, "Select": "COUNT"}
            try:
                while count < WATCH_CAP:
                    resp = c.scan(**kwargs)
                    count += resp.get("Count", 0)
                    if "LastEvaluatedKey" not in resp:
                        break
                    kwargs["ExclusiveStartKey"] = resp["LastEvaluatedKey"]
            except client_error() as exc:
                if not is_error(exc, "ResourceNotFound"):
                    raise
                continue
            out[("table", name)] = count
    return out


SERVICE = Service(
    name="dynamodb",
    label="DynamoDB tables",
    names=tables,
    details=details,
    describe=describe,
    watch=watch,
    completions={"table": lambda c, i: pages(c, "list_tables", "TableNames", cap=COMPLETE_MAX)},
)
