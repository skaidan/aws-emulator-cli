"""Reading a real account: the read-only guard, and seed import (with fake clients)."""

import pytest

from awsemu import realaccount as ra
from awsemu import seed as seedlib
from awsemu.cli import cli
from tests.test_services import FakeClient, FakePaginator  # noqa: F401

boto3 = pytest.importorskip("boto3")


@pytest.mark.parametrize("op, params, ok", [
    ("DescribeTable", {}, True), ("ListQueues", {}, True), ("GetQueueAttributes", {}, True),
    ("HeadBucket", {}, True), ("PutItem", {}, False), ("CreateQueue", {}, False), ("DeleteTable", {}, False),
    ("GetSecretValue", {}, False), ("GetObject", {}, False), ("Scan", {}, False), ("Query", {}, False),
    ("GetParameters", {"WithDecryption": False}, True), ("GetParameters", {"WithDecryption": True}, False),
    ("GetParametersByPath", {}, False), ("Decrypt", {}, False),
])
def test_only_configuration_reads(op, params, ok):
    assert ra.allowed(op, params) is ok


@pytest.fixture
def profile(tmp_path, monkeypatch):
    cfg = tmp_path / "config"
    cfg.write_text("[profile dev]\nregion = eu-west-1\naws_access_key_id = AKIDEV\naws_secret_access_key = s\n")
    monkeypatch.setenv("AWS_CONFIG_FILE", str(cfg))
    monkeypatch.setenv("AWS_SHARED_CREDENTIALS_FILE", str(tmp_path / "none"))
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "AKIAENVIRONMENT")  # must not be used
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "x")
    monkeypatch.setenv("AWS_ENDPOINT_URL", "https://127.0.0.1:9")  # must be ignored
    return "dev"


def test_session_is_guarded_and_uses_the_profile(profile):
    sess = ra.session(profile)
    assert sess.region_name == "eu-west-1"
    assert sess.get_credentials().access_key == "AKIDEV"  # not the environment's
    sqs = ra.client(sess, "sqs")
    assert sqs.meta.endpoint_url.startswith("https://sqs.eu-west-1.amazonaws.com")  # not AWS_ENDPOINT_URL
    with pytest.raises(ra.NotReadOnly, match="refusing sqs:CreateQueue"):
        sqs.create_queue(QueueName="x")  # refused before anything is sent
    with pytest.raises(ra.NotReadOnly):
        ra.client(sess, "secretsmanager").get_secret_value(SecretId="db")
    with pytest.raises(ra.NotReadOnly):
        ra.session("")


def test_localize_rewrites_only_this_account():
    definition = {"States": {"A": {"Resource": "arn:aws:lambda:eu-west-1:123456789012:function:f"},
                             "B": {"Resource": "arn:aws:states:::sqs:sendMessage"},
                             "C": {"Resource": "arn:aws:sns:eu-west-1:999999999999:other"}}}
    out = ra.localize(definition, "123456789012")
    assert out["States"]["A"]["Resource"] == "arn:aws:lambda:us-east-1:000000000000:function:f"
    assert out["States"]["B"]["Resource"] == "arn:aws:states:::sqs:sendMessage"
    assert out["States"]["C"]["Resource"] == "arn:aws:sns:us-east-1:999999999999:other"


class FakeSession:
    region_name = "eu-west-1"

    def __init__(self, clients):
        self.clients = clients

    def client(self, service, config=None):
        return self.clients[service]


def test_import_reads_configuration_not_data():
    def location(Bucket):
        return {"LocationConstraint": "eu-west-1" if Bucket == "here" else "us-west-2"}

    clients = {
        "sts": FakeClient(get_caller_identity={"Account": "123456789012"}),
        "s3": FakeClient(list_buckets={"Buckets": [{"Name": "here"}, {"Name": "there"}]},
                         get_bucket_location=location),
        "sqs": FakeClient(list_queues=[{"QueueUrls": ["https://sqs/123/jobs", "https://sqs/123/jobs-dlq"]}],
                          get_queue_attributes=lambda QueueUrl, AttributeNames: {"Attributes": (
                              {"RedrivePolicy": '{"deadLetterTargetArn": "arn:aws:sqs:eu-west-1:123:jobs-dlq", '
                                                '"maxReceiveCount": 3}', "VisibilityTimeout": "60"}
                              if QueueUrl.endswith("/jobs") else {})}),
        "dynamodb": FakeClient(list_tables=[{"TableNames": ["orders"]}], describe_table={"Table": {
            "AttributeDefinitions": [{"AttributeName": "id", "AttributeType": "S"},
                                     {"AttributeName": "n", "AttributeType": "N"}],
            "KeySchema": [{"AttributeName": "id", "KeyType": "HASH"}, {"AttributeName": "n", "KeyType": "RANGE"}]}}),
        "sns": FakeClient(list_topics=[{"Topics": [{"TopicArn": "arn:aws:sns:eu-west-1:123:events"}]}],
                          list_subscriptions_by_topic=[{"Subscriptions": [
                              {"Protocol": "sqs", "Endpoint": "arn:aws:sqs:eu-west-1:123:jobs", "SubscriptionArn": "s1"},
                              {"Protocol": "email", "Endpoint": "a@b.c", "SubscriptionArn": "s2"}]}],
                          get_subscription_attributes={"Attributes": {"RawMessageDelivery": "true"}}),
        "secretsmanager": FakeClient(list_secrets=[{"SecretList": [{"Name": "db/password"}]}]),
        "ssm": FakeClient(describe_parameters=[{"Parameters": [{"Name": "/app/host", "Type": "String"},
                                                               {"Name": "/app/key", "Type": "SecureString"}]}],
                          get_parameters={"Parameters": [{"Name": "/app/host", "Type": "String", "Value": "db"}]}),
        "kinesis": FakeClient(list_streams=[{"StreamNames": []}]),
        "stepfunctions": FakeClient(list_state_machines=[{"stateMachines": []}]),
        "events": FakeClient(list_rules=[{"Rules": []}]),
    }
    data, notes = ra.import_seed(FakeSession(clients), set(seedlib.SECTIONS))
    assert data["buckets"] == [{"name": "here"}]
    assert data["queues"][0] == {"name": "jobs", "visibility_timeout": 60, "dlq": "jobs-dlq", "max_receive": 3}
    assert data["tables"] == [{"name": "orders", "pk": "id", "sk": "n:N"}]
    assert data["topics"] == [{"name": "events", "subscriptions": [{"sqs": "jobs", "raw": True}]}]
    assert data["secrets"] == [{"name": "db/password", "value": ra.PLACEHOLDER}]
    assert {"name": "/app/key", "value": ra.PLACEHOLDER, "type": "SecureString"} in data["parameters"]
    assert {"name": "/app/host", "value": "db"} in data["parameters"]
    ops = [op for c in clients.values() for op, _ in c.calls]
    assert "get_secret_value" not in ops and "scan" not in ops and "get_object" not in ops
    assert dict(clients["ssm"].calls)["get_parameters"]["WithDecryption"] is False
    assert any("email" in n for n in notes) and any("functions" in n for n in notes)
    seedlib.load_text(seedlib.dump(data))  # a valid seed


def test_command_needs_a_profile_and_asks(runner):
    assert runner.invoke(cli, ["seed", "import"]).exit_code == 2
