"""Amazon DynamoDB: tables and items."""

from __future__ import annotations


from .. import clients
from ..runtime import RuntimeErrorWithHint
from .. import realaccount
from .. import seed as seedlib
from ..awserrors import client_error, is_error
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


def _to_item(data):
    from ..commands.dynamodb import to_item

    return to_item(data)


def _from_item(item):
    from ..commands.dynamodb import from_item

    return from_item(item)


def apply(seed, port, report):
    ddb = clients.client("dynamodb", port)
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
            except client_error() as exc:
                if not is_error(exc, "ResourceNotFound"):
                    raise
                ddb.create_table(
                    TableName=name,
                    BillingMode="PAY_PER_REQUEST",
                    AttributeDefinitions=[{"AttributeName": n, "AttributeType": k} for (n, k), _ in keys],
                    KeySchema=wanted_schema,
                )
                ddb.get_waiter("table_exists").wait(TableName=name, WaiterConfig={"Delay": 1, "MaxAttempts": 30})
                result = "created"
            items = seedlib.load_items(t, seed.base_dir)
            for i in range(0, len(items), 25):
                pending: dict | None = {name: [{"PutRequest": {"Item": _to_item(it)}} for it in items[i : i + 25]]}
                while pending:
                    pending = ddb.batch_write_item(RequestItems=pending).get("UnprocessedItems") or None
            if items and result == "unchanged":
                result = "updated"
            report.add("table", name, result, f"{len(items)} item(s) written" if items else "")
        except Exception as exc:
            report.add("table", name, "failed", clients.describe_error(exc))


def export(port: int, opts: seedlib.ExportOptions) -> list[dict]:
    ddb = clients.client("dynamodb", port)
    tables = []
    for page in ddb.get_paginator("list_tables").paginate():
        for name in page.get("TableNames", []):
            t = ddb.describe_table(TableName=name)["Table"]
            types = {d["AttributeName"]: d["AttributeType"] for d in t["AttributeDefinitions"]}
            entry = {"name": name}
            for k in t["KeySchema"]:
                spec = k["AttributeName"] + (
                    "" if types[k["AttributeName"]] == "S" else f":{types[k['AttributeName']]}"
                )
                entry["pk" if k["KeyType"] == "HASH" else "sk"] = spec
            items = []
            for p in ddb.get_paginator("scan").paginate(TableName=name):
                items += [_from_item(i) for i in p.get("Items", [])]
            if items:
                entry["items"] = items
            tables.append(entry)
    return tables


def seed_import(sess, opts: seedlib.ImportOptions) -> list[dict]:
    """``tables`` of a real account (read-only), for ``awsemu seed import``."""
    ddb = realaccount.client(sess, "dynamodb")
    tables = []
    for page in ddb.get_paginator("list_tables").paginate():
        for name in page.get("TableNames", []):
            t = ddb.describe_table(TableName=name)["Table"]
            types = {d["AttributeName"]: d["AttributeType"] for d in t["AttributeDefinitions"]}
            entry = {"name": name}
            for k in t["KeySchema"]:
                spec = k["AttributeName"] + (
                    "" if types[k["AttributeName"]] == "S" else f":{types[k['AttributeName']]}"
                )
                entry["pk" if k["KeyType"] == "HASH" else "sk"] = spec
            if t.get("GlobalSecondaryIndexes") or t.get("LocalSecondaryIndexes"):
                opts.notes.append(f"table {name}: its secondary indexes aren't in seeds yet; left out")
            tables.append(entry)
    return tables


WRITES = {"PutItem", "UpdateItem", "DeleteItem", "BatchWriteItem"}
READS = {"GetItem", "Query", "Scan", "BatchGetItem"}


def cost(call) -> list[tuple[str, float]]:
    """One request unit per call, two for transactions (big items take more: awsemu.cost)."""
    op = call["operation"]
    if op in WRITES or op == "TransactWriteItems":
        return [("dynamodb.write", 2 if op.startswith("Transact") else 1)]
    if op in READS or op == "TransactGetItems":
        return [("dynamodb.read", 2 if op.startswith("Transact") else 1)]
    return []


SERVICE = Service(
    name="dynamodb",
    label="DynamoDB tables",
    names=tables,
    details=details,
    describe=describe,
    watch=watch,
    completions={"table": lambda c, i: pages(c, "list_tables", "TableNames", cap=COMPLETE_MAX)},
    seed_section="tables",
    apply=apply,
    export=export,
    seed_import=seed_import,
    cost=cost,
)
