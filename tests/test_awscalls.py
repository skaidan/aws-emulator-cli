"""Recognising AWS calls from the requests botocore really sends."""

from urllib.parse import urlsplit

import pytest

boto3 = pytest.importorskip("boto3")

from awsemu import awscalls as ac  # noqa: E402


class _Stop(Exception):
    pass


def request_of(service, operation, **params):
    """The HTTP request botocore would send, as (method, path, headers, body)."""
    sent = []

    def capture(request, **_):
        sent.append(request)
        raise _Stop

    client = boto3.client(service, region_name="us-east-1", endpoint_url="https://127.0.0.1:9000",
                          aws_access_key_id="test", aws_secret_access_key="test")
    client.meta.events.register("before-send", capture)
    with pytest.raises(_Stop):
        getattr(client, operation)(**params)
    r = sent[0]
    headers = {k.lower(): v.decode() if isinstance(v, bytes) else v for k, v in r.headers.items()}
    url = urlsplit(r.url)
    body = r.body
    if hasattr(body, "read"):
        body = body.read()
    if isinstance(body, str):
        body = body.encode()
    return r.method, url.path + (f"?{url.query}" if url.query else ""), headers, body or b""


def identify(service, operation, **params):
    i = ac.identify(*request_of(service, operation, **params))
    return i.service, i.operation, i.resource, i.protocol


@pytest.fixture(autouse=True)
def _cache(isolated_home):
    pass


@pytest.mark.parametrize("service, operation, params, expected", [
    ("dynamodb", "put_item", {"TableName": "orders", "Item": {"id": {"S": "1"}}},
     ("dynamodb", "PutItem", "orders", "json")),
    ("dynamodbstreams", "list_streams", {}, ("dynamodbstreams", "ListStreams", "", "json")),
    ("sqs", "send_message", {"QueueUrl": "https://127.0.0.1:9000/000000000000/jobs", "MessageBody": "x"},
     ("sqs", "SendMessage", "jobs", "json")),
    ("sns", "publish", {"TopicArn": "arn:aws:sns:us-east-1:000000000000:alerts", "Message": "x"},
     ("sns", "Publish", "alerts", "query")),
    ("s3", "put_object", {"Bucket": "b1", "Key": "dir/k.txt", "Body": b"x"},
     ("s3", "PutObject", "b1/dir/k.txt", "rest-xml")),
    ("s3", "copy_object", {"Bucket": "b1", "Key": "k2", "CopySource": "b1/k"},
     ("s3", "CopyObject", "b1/k2", "rest-xml")),
    ("s3", "upload_part", {"Bucket": "b1", "Key": "k", "UploadId": "u", "PartNumber": 1, "Body": b"x"},
     ("s3", "UploadPart", "b1/k", "rest-xml")),
    ("s3", "list_objects_v2", {"Bucket": "b1"}, ("s3", "ListObjectsV2", "b1", "rest-xml")),
    ("s3", "list_objects", {"Bucket": "b1"}, ("s3", "ListObjects", "b1", "rest-xml")),
    ("s3", "list_buckets", {}, ("s3", "ListBuckets", "", "rest-xml")),
    ("s3", "head_object", {"Bucket": "b1", "Key": "a b+c"}, ("s3", "HeadObject", "b1/a b+c", "rest-xml")),
    ("s3", "delete_objects", {"Bucket": "b1", "Delete": {"Objects": [{"Key": "a"}]}},
     ("s3", "DeleteObjects", "b1", "rest-xml")),
    ("lambda", "invoke", {"FunctionName": "fn1"}, ("lambda", "Invoke", "fn1", "rest-json")),
    ("lambda", "list_functions", {}, ("lambda", "ListFunctions", "", "rest-json")),
    ("stepfunctions", "start_execution", {"stateMachineArn": "arn:aws:states:us-east-1:0:stateMachine:flow"},
     ("stepfunctions", "StartExecution", "flow", "json")),
    ("logs", "create_log_group", {"logGroupName": "app"}, ("logs", "CreateLogGroup", "app", "json")),
    ("events", "list_rules", {"EventBusName": "default"}, ("events", "ListRules", "default", "json")),
    ("kinesis", "put_record", {"StreamName": "st", "Data": b"x", "PartitionKey": "p"},
     ("kinesis", "PutRecord", "st", "json")),
    ("sts", "get_caller_identity", {}, ("sts", "GetCallerIdentity", "", "query")),
    ("iam", "create_role", {"RoleName": "r", "AssumeRolePolicyDocument": "{}"},
     ("iam", "CreateRole", "r", "query")),
    ("ec2", "describe_instances", {}, ("ec2", "DescribeInstances", "", "ec2")),
    ("secretsmanager", "get_secret_value", {"SecretId": "db/pass"},
     ("secretsmanager", "GetSecretValue", "db/pass", "json")),
    ("apigateway", "get_rest_apis", {}, ("apigateway", "GetRestApis", "", "rest-json")),
    ("apigatewayv2", "get_apis", {}, ("apigatewayv2", "GetApis", "", "rest-json")),
    ("ssm", "get_parameter", {"Name": "/a/b"}, ("ssm", "GetParameter", "/a/b", "json")),
])
def test_identify(service, operation, params, expected):
    assert identify(service, operation, **params) == expected


def test_cloudwatch_cbor_or_other_protocol():
    service, op, _, protocol = identify("cloudwatch", "list_metrics")
    assert (service, op) == ("cloudwatch", "ListMetrics")
    assert protocol in ("smithy-rpc-v2-cbor", "json", "query")


def test_presigned_url():
    s3 = boto3.client("s3", region_name="us-east-1", endpoint_url="https://127.0.0.1:9000",
                      aws_access_key_id="test", aws_secret_access_key="test")
    url = urlsplit(s3.generate_presigned_url("get_object", Params={"Bucket": "b1", "Key": "k"}))
    i = ac.identify("GET", f"{url.path}?{url.query}", {}, b"")
    assert (i.service, i.operation, i.resource) == ("s3", "GetObject", "b1/k")


def test_tables_are_cached(monkeypatch):
    ac._tables = None
    ac.tables()
    assert ac._cache_file().exists()
    ac._tables = None
    monkeypatch.setattr(ac, "_loader", lambda: (_ for _ in ()).throw(AssertionError("not cached")))
    assert "dynamodb" in ac.tables().signing


def test_unsigned_request_is_unknown_but_harmless():
    i = ac.identify("GET", "/__admin/health", {}, b"")
    assert (i.service, i.operation) == ("", "")


@pytest.mark.parametrize("status, headers, body, code", [
    (200, {}, b"{}", None),
    (400, {"x-amzn-errortype": "ResourceNotFoundException:http://internal"}, b"", "ResourceNotFoundException"),
    (400, {}, b'{"__type":"com.amazonaws.dynamodb.v20120810#ConditionalCheckFailedException"}',
     "ConditionalCheckFailedException"),
    (404, {}, b"<Error><Code>NoSuchKey</Code><Message>x</Message></Error>", "NoSuchKey"),
    (400, {}, b"<ErrorResponse><Error><Type>Sender</Type><Code>Throttling</Code></Error></ErrorResponse>",
     "Throttling"),
    (403, {"x-amzn-query-error": "AWS.SimpleQueueService.NonExistentQueue;Sender"}, b"",
     "AWS.SimpleQueueService.NonExistentQueue"),
    (500, {}, b"", "HTTP500"),
])
def test_error_code(status, headers, body, code):
    assert ac.error_code(status, headers, body) == code
