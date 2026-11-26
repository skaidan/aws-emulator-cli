"""Masking secrets before calls are stored."""

import json

from awsemu import redact


def test_secret_keys_but_not_their_names_or_page_tokens():
    for key in (
        "SecretString",
        "SecretBinary",
        "Password",
        "MasterUserPassword",
        "SessionToken",
        "SecretAccessKey",
        "aws_secret_access_key",
        "Credentials",
        "PrivateKey",
        "Attributes.1.Token",
    ):
        assert redact.sensitive_key(key), key
    for key in (
        "SecretId",
        "SecretArn",
        "Name",
        "NextToken",
        "ContinuationToken",
        "ClientRequestToken",
        "KeyName",
        "TableName",
        "SecretVersionId",
        "TokenType",
        "AccessKeyId",
    ):
        assert not redact.sensitive_key(key), key


def test_json_bodies():
    body = json.dumps(
        {
            "SecretId": "db",
            "SecretString": "s3cr3t",
            "Credentials": {"AccessKeyId": "AK", "SecretAccessKey": "SK"},
            "Items": [{"Password": "p"}],
            "NextToken": "page2",
            "Parameter": {"Name": "/db/pass", "Type": "SecureString", "Value": "hunter2"},
            "Other": {"Name": "/db/host", "Type": "String", "Value": "localhost"},
        }
    )
    masked = json.loads(redact.text_body(body, "application/x-amz-json-1.1"))
    assert masked["SecretId"] == "db" and masked["SecretString"] == "***"
    assert masked["Credentials"] == "***" and masked["Items"][0]["Password"] == "***"
    assert masked["NextToken"] == "page2"
    assert masked["Parameter"]["Value"] == "***" and masked["Other"]["Value"] == "localhost"


def test_xml_and_form_bodies():
    xml = (
        "<AssumeRoleResponse><Credentials><AccessKeyId>AK</AccessKeyId><SecretAccessKey>SK</SecretAccessKey>"
        "<SessionToken>T</SessionToken><Expiration>2026</Expiration></Credentials></AssumeRoleResponse>"
    )
    masked = redact.text_body(xml)
    assert "SK" not in masked and ">T<" not in masked and "<Expiration>2026</Expiration>" in masked
    form = "Action=CreateUser&UserName=ana&Password=p%40ss&Version=2010-05-08"
    assert (
        redact.text_body(form, "application/x-www-form-urlencoded")
        == "Action=CreateUser&UserName=ana&Password=%2A%2A%2A&Version=2010-05-08"
    )
    assert redact.text_body("just text") == "just text"


def test_headers_and_presigned_urls():
    assert redact.headers([("Authorization", "AWS4-HMAC-SHA256 Credential=AK/..."), ("Host", "h")]) == [
        ("Authorization", "***"),
        ("Host", "h"),
    ]
    url = redact.url("/b/k?X-Amz-Algorithm=AWS4&X-Amz-Credential=AK%2F2026&X-Amz-Signature=abc&partNumber=1")
    assert "AK" not in url and "abc" not in url and "partNumber=1" in url and "X-Amz-Algorithm=AWS4" in url
    assert redact.url("/b/k") == "/b/k"
