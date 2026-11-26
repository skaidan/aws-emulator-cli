"""Fault rules, and error responses the SDK reads as the real thing."""

import random

import pytest

from awsemu import faults as f


@pytest.mark.parametrize(
    "spec, expected",
    [
        ("dynamodb=throttle@10%", dict(service="dynamodb", operation="*", error="throttle", rate=0.1)),
        ("s3=latency:500ms", dict(service="s3", latency_ms=500, rate=1.0)),
        ("s3=2s", dict(latency_ms=2000)),
        ("s3:GetObject=503@50%", dict(operation="GetObject", status=503, rate=0.5)),
        ("sqs:Send*=reset@0.05", dict(operation="Send*", reset=True, rate=0.05)),
        (
            "lambda:Invoke=latency:2s,TooManyRequestsException@20%x3",
            dict(latency_ms=2000, error="TooManyRequestsException", rate=0.2, times=3),
        ),
        ("*=InternalFailure:500@1%", dict(service="*", error="InternalFailure", status=500, rate=0.01)),
        ("sqs=AWS.SimpleQueueService.NonExistentQueue", dict(error="AWS.SimpleQueueService.NonExistentQueue")),
        ("s3 = 503 x2", dict(status=503, times=2)),
        ("dynamodb:PutItem[orders]=throttle", dict(operation="PutItem", resource="orders", error="throttle")),
        ("s3[uploads-*]=503 for 30s", dict(service="s3", operation="*", resource="uploads-*", duration_s=30)),
        ("sqs=throttle for 2m @50%", dict(duration_s=120, rate=0.5)),
        ("sqs=throttle@50%x3for500ms", dict(duration_s=0.5, rate=0.5, times=3)),
    ],
)
def test_parse(spec, expected):
    fault = f.parse(spec)
    for key, value in expected.items():
        assert getattr(fault, key) == value, key


@pytest.mark.parametrize(
    "spec",
    [
        "dynamodb",
        "dynamodb=",
        "dynamodb=@10%",
        "s3=200",
        "s3=latency:fast",
        "s3=503@150%",
        "s3=503@0%",
        "s3=bad code!",
        "s3[=503",
        "s3:Get[a]x=503",
        "s3=503 for 0s",
    ],
)
def test_parse_rejects(spec):
    with pytest.raises(f.FaultError):
        f.parse(spec)


def test_matching_is_case_insensitive_with_globs():
    rule = f.parse("DynamoDB:put*=throttle")
    assert rule.matches("dynamodb", "PutItem")
    assert not rule.matches("dynamodb", "GetItem")
    assert not rule.matches("s3", "PutObject")


def test_decide_rates_times_and_first_error_wins():
    rules = [f.parse("s3=latency:100ms"), f.parse("s3=503x2"), f.parse("s3=InternalError"), f.parse("sqs=throttle@50%")]
    faults = f.FaultSet(rules, rng=random.Random(7))
    first = faults.decide("s3", "GetObject")
    assert first.latency_ms == 100 and first.error.spec == "s3=503x2"
    assert first.label == "s3=latency:100ms + s3=503x2"
    faults.decide("s3", "GetObject")
    third = faults.decide("s3", "GetObject")  # the 503 rule ran out
    assert third.error.spec == "s3=InternalError"
    hits = sum(bool(faults.decide("sqs", "SendMessage").error) for _ in range(1000))
    assert 400 < hits < 600
    assert faults.decide("dynamodb", "PutItem").label is None


@pytest.mark.parametrize(
    "spec, service, protocol, code, status",
    [
        ("x=throttle", "dynamodb", "json", "ThrottlingException", 400),
        ("x=throttle", "s3", "rest-xml", "SlowDown", 503),
        ("x=throttle", "lambda", "rest-json", "TooManyRequestsException", 429),
        ("x=throttle", "sns", "query", "Throttling", 400),
        ("x=throttle", "ec2", "ec2", "RequestLimitExceeded", 503),
        ("x=500", "s3", "rest-xml", "InternalError", 500),
        ("x=503", "dynamodb", "json", "ServiceUnavailable", 503),
        ("x=InternalFailure", "sqs", "json", "InternalFailure", 500),
        ("x=ConditionalCheckFailedException", "dynamodb", "json", "ConditionalCheckFailedException", 400),
        ("x=Custom:418", "dynamodb", "json", "Custom", 418),
    ],
)
def test_code_and_status(spec, service, protocol, code, status):
    assert f.code_and_status(f.parse(spec), service, protocol) == (code, status)


def test_cbor_map():
    assert f.cbor_map({"a": "b"}) == bytes([0xA1, 0x61, ord("a"), 0x61, ord("b")])
    long = "x" * 30
    assert f.cbor_map({"k": long})[3:5] == bytes([0x78, 30])


botocore = pytest.importorskip("botocore")


@pytest.mark.parametrize(
    "service, operation, protocol",
    [
        ("dynamodb", "PutItem", "json"),
        ("sqs", "SendMessage", "json"),
        ("lambda", "Invoke", "rest-json"),
        ("sns", "Publish", "query"),
        ("ec2", "DescribeInstances", "ec2"),
        ("s3", "GetObject", "rest-xml"),
        ("cloudwatch", "ListMetrics", "smithy-rpc-v2-cbor"),
    ],
)
def test_botocore_reads_the_injected_error_and_retries_throttling(service, operation, protocol):
    import botocore.session
    from botocore.parsers import create_parser
    from botocore.retries.standard import ThrottledRetryableChecker

    model = botocore.session.get_session().get_service_model(service)
    shape = model.operation_model(operation).output_shape
    code, status = f.code_and_status(f.parse("x=throttle"), service, protocol)
    status, headers, body = f.error_response(
        code, status, protocol, "Injected by awsemu proxy", "application/x-amz-json-1.0"
    )
    response = {"status_code": status, "headers": {k.lower(): v for k, v in headers.items()}, "body": body}
    parsed = create_parser(protocol).parse(response, shape)
    assert parsed["Error"]["Code"] == code
    assert code in ThrottledRetryableChecker._THROTTLED_ERROR_CODES or status in (500, 502, 503, 504)


def test_resource_rules_match_the_named_resource():
    rule = f.parse("dynamodb:PutItem[orders]=throttle")
    assert rule.matches("dynamodb", "PutItem", "orders")
    assert not rule.matches("dynamodb", "PutItem", "users")
    assert not rule.matches("dynamodb", "PutItem", "")
    bucket = f.parse("s3[uploads-*]=503")
    assert bucket.matches("s3", "PutObject", "uploads-2026/cat.jpg")  # the bucket of bucket/key
    assert bucket.matches("s3", "ListObjectsV2", "uploads-2026")
    assert not bucket.matches("s3", "PutObject", "photos/uploads-1")
    assert f.parse("s3[photos/raw/*]=503").matches("s3", "GetObject", "photos/raw/a.jpg")
    faults = f.FaultSet([rule])
    assert faults.decide("dynamodb", "PutItem", "users").error is None
    assert faults.decide("dynamodb", "PutItem", "orders").error is rule


def test_a_timed_rule_stops_and_says_how_long_is_left(monkeypatch):
    now = [1000.0]
    monkeypatch.setattr(f.time, "time", lambda: now[0])
    rule = f.parse("s3=503 for 30s")
    faults = f.FaultSet([rule])
    assert faults.decide("s3", "GetObject").error is rule
    now[0] += 10
    assert rule.as_dict()["remaining_s"] == 20 and rule.as_dict()["active"]
    now[0] += 21
    assert faults.decide("s3", "GetObject").error is None  # the outage is over
    assert rule.as_dict()["active"] is False and rule.as_dict()["remaining_s"] == 0
