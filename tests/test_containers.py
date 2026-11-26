"""``awsemu.containers.AwsEmulatorContainer`` against the real image.

Skipped unless ``AWSEMU_TESTCONTAINERS=1``: needs Docker, the image from
``awsemu image build`` and ``pip install testcontainers``.
"""

import os
import subprocess
import sys

import pytest

pytestmark = pytest.mark.skipif(os.environ.get("AWSEMU_TESTCONTAINERS") != "1",
                                reason="set AWSEMU_TESTCONTAINERS=1 (needs Docker and the image)")


@pytest.fixture(scope="module")
def emulator():
    pytest.importorskip("testcontainers")
    from awsemu.containers import AwsEmulatorContainer

    with AwsEmulatorContainer() as container:
        yield container


def test_endpoint_and_files(emulator):
    from awsemu.containers import PORT

    assert emulator.endpoint_url == f"https://127.0.0.1:{emulator.get_exposed_port(PORT)}"
    assert "BEGIN CERTIFICATE" in open(emulator.ca_path).read()
    assert emulator.access_key_id and emulator.secret_access_key


def test_s3_and_sqs(emulator):
    s3 = emulator.client("s3")
    s3.create_bucket(Bucket="tc-python")
    s3.put_object(Bucket="tc-python", Key="hello.txt", Body=b"hello")
    assert s3.get_object(Bucket="tc-python", Key="hello.txt")["Body"].read() == b"hello"

    sqs = emulator.client("sqs")
    url = sqs.create_queue(QueueName="tc-python")["QueueUrl"]
    sqs.send_message(QueueUrl=url, MessageBody="job-1")
    messages = sqs.receive_message(QueueUrl=url, WaitTimeSeconds=5).get("Messages", [])
    assert [m["Body"] for m in messages] == ["job-1"]


def test_env_points_a_child_process_at_it(emulator):
    code = "import boto3; print(boto3.client('sts').get_caller_identity()['Account'])"
    env = {k: v for k, v in os.environ.items() if not k.startswith("AWS_")}
    out = subprocess.run([sys.executable, "-c", code], env={**env, **emulator.aws_env()},
                         capture_output=True, text=True, check=True).stdout
    assert out.strip() == "000000000000"


def test_auth_off():
    pytest.importorskip("testcontainers")
    from awsemu.containers import AwsEmulatorContainer

    with AwsEmulatorContainer(auth=False) as container:
        assert container.access_key_id == "EMULATORAUTHOFF00000"
        assert container.client("s3").list_buckets()["Buckets"] == []
