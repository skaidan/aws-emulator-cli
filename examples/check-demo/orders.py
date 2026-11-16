"""A tiny order service, to try 'awsemu check examples/check-demo'."""

import boto3

ddb = boto3.client("dynamodb")
sqs = boto3.client("sqs")


def place_order(order_id: str, queue_url: str) -> None:
    ddb.transact_write_items(TransactItems=[{
        "Put": {"TableName": "orders", "Item": {"id": {"S": order_id}},
                "ConditionExpression": "attribute_not_exists(id)"},
    }])
    sqs.send_message(QueueUrl=queue_url, MessageBody=order_id)


def get_order(order_id: str) -> dict | None:
    return ddb.get_item(TableName="orders", Key={"id": {"S": order_id}}).get("Item")
