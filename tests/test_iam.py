"""``awsemu iam policy``: the policy a calls log needs."""

import json

from awsemu import iampolicy as ip
from awsemu import proxy as px
from awsemu.cli import cli


def c(service, operation, resource="", **extra):
    return {"service": service, "operation": operation, "resource": resource, "status": 200, "error": None, **extra}


CALLS = [
    c("dynamodb", "PutItem", "orders"),
    c("dynamodb", "GetItem", "orders"),
    c("dynamodb", "Query", "orders"),
    c("dynamodb", "PutItem", "users"),
    c("dynamodb", "ListTables"),
    c("s3", "PutObject", "photos/a.jpg"),
    c("s3", "HeadObject", "photos/b.jpg"),
    c("s3", "ListObjectsV2", "photos"),
    c("s3", "ListBuckets"),
    c("sqs", "SendMessageBatch", "jobs"),
    c("sqs", "ReceiveMessage", "jobs"),
    c("lambda", "Invoke", "resize"),
    c("ssm", "GetParameter", "/app/db/host"),
    c("secretsmanager", "GetSecretValue", "db/password"),
    c("stepfunctions", "StartExecution", "flow"),
    c("logs", "PutLogEvents", "/aws/lambda/x"),
    c("sts", "GetCallerIdentity"),
    c("", ""),
    c("sqs", "SendMessage", "jobs", error="ThrottlingException", fault="sqs=throttle"),  # still needs it
]


def test_actions_and_arns():
    policy = ip.build(CALLS, region="eu-west-1", account="123456789012")
    a = policy.actions
    assert a["dynamodb:PutItem"] == {
        "arn:aws:dynamodb:eu-west-1:123456789012:table/orders",
        "arn:aws:dynamodb:eu-west-1:123456789012:table/users",
    }
    assert a["dynamodb:ListTables"] == {"*"}
    assert a["s3:PutObject"] == {"arn:aws:s3:::photos/*"} and a["s3:GetObject"] == {"arn:aws:s3:::photos/*"}
    assert a["s3:ListBucket"] == {"arn:aws:s3:::photos"} and a["s3:ListAllMyBuckets"] == {"*"}
    assert "s3:HeadObject" not in a and "s3:ListObjectsV2" not in a
    assert a["sqs:SendMessage"] == {"arn:aws:sqs:eu-west-1:123456789012:jobs"}  # batch -> the single action
    assert "lambda:InvokeFunction" in a and "states:StartExecution" in a
    assert a["ssm:GetParameter"] == {"arn:aws:ssm:eu-west-1:123456789012:parameter/app/db/host"}
    assert a["secretsmanager:GetSecretValue"] == {"arn:aws:secretsmanager:eu-west-1:123456789012:secret:db/password-*"}
    assert a["logs:PutLogEvents"] == {"arn:aws:logs:eu-west-1:123456789012:log-group:/aws/lambda/x:*"}
    assert "sts:GetCallerIdentity" not in a and policy.skipped == ["sts:GetCallerIdentity"]


def test_document_groups_actions_by_resources():
    doc = ip.build(CALLS).document
    assert doc["Version"] == "2012-10-17"
    statements = doc["Statement"]
    orders = next(s for s in statements if s["Resource"] == "arn:aws:dynamodb:*:*:table/orders")
    assert orders["Action"] == ["dynamodb:GetItem", "dynamodb:Query"]  # PutItem has two tables: its own statement
    both = next(s for s in statements if s["Action"] == "dynamodb:PutItem")
    assert both["Resource"] == ["arn:aws:dynamodb:*:*:table/orders", "arn:aws:dynamodb:*:*:table/users"]
    stars = next(s for s in statements if s["Resource"] == "*")
    assert stars["Action"] == ["dynamodb:ListTables", "s3:ListAllMyBuckets"]
    assert len({s["Sid"] for s in statements}) == len(statements)
    tf = ip.terraform(ip.build(CALLS))
    assert 'data "aws_iam_policy_document" "awsemu"' in tf and '"dynamodb:GetItem", "dynamodb:Query"' in tf


def test_prefixes():
    assert ip.action("stepfunctions", "StartExecution") == "states:StartExecution"
    assert ip.action("cloudwatch", "PutMetricData") == "cloudwatch:PutMetricData"
    assert ip.action("sesv2", "SendEmail") == "ses:SendEmail"
    assert ip.action("dynamodbstreams", "GetRecords") == "dynamodb:GetRecords"


def test_command(runner, isolated_home, tmp_path):
    files = px.ProxyFiles(9297)
    files.dir.mkdir(parents=True)
    files.calls.write_text("".join(json.dumps(x) + "\n" for x in CALLS))
    result = runner.invoke(cli, ["iam", "policy", "--service", "dynamodb", "--account", "111122223333"])
    assert result.exit_code == 0, result.output
    doc = json.loads(result.output[: result.output.rindex("}") + 1])
    assert all(
        a.startswith("dynamodb:")
        for s in doc["Statement"]
        for a in (s["Action"] if isinstance(s["Action"], list) else [s["Action"]])
    )
    out = tmp_path / "policy.tf"
    assert runner.invoke(cli, ["iam", "policy", "--format", "terraform", "-o", str(out)]).exit_code == 0
    assert "aws_iam_policy_document" in out.read_text()
    files.calls.write_text(json.dumps(c("sts", "GetCallerIdentity")) + "\n")
    assert runner.invoke(cli, ["iam", "policy"]).exit_code == 1


# ---------------------------------------------------------------- check --iam

from awsemu import iamcheck as ic  # noqa: E402

TF = """
data "aws_iam_policy_document" "app" {
  statement {
    actions   = ["dynamodb:GetItem", "dynamodb:Query", "s3:Get*"]
    resources = ["*"]
  }
  statement {
    effect  = "Deny"
    actions = ["dynamodb:PutItem"]
    resources = ["*"]
  }
}
resource "aws_iam_role_policy" "inline" {
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{ Effect = "Allow", Action = ["sqs:SendMessage", "sqs:ReceiveMessage"], Resource = "*" }]
  })
}
resource "aws_iam_role_policy_attachment" "x" {
  policy_arn = "arn:aws:iam::aws:policy/AmazonS3ReadOnlyAccess"
}
"""

SAM = """
Transform: AWS::Serverless-2016-10-31
Resources:
  Fn:
    Type: AWS::Serverless::Function
    Properties:
      Policies:
        - DynamoDBCrudPolicy: {TableName: !Ref Table}
        - AWSLambdaBasicExecutionRole
  Role:
    Type: AWS::IAM::Role
    Properties:
      ManagedPolicyArns: [arn:aws:iam::aws:policy/CloudWatchLogsFullAccess]
      Policies:
        - PolicyName: p
          PolicyDocument:
            Statement:
              - Effect: Allow
                Action: lambda:InvokeFunction
                Resource: !GetAtt Fn.Arn
              - Effect: Deny
                Action: ["s3:DeleteObject"]
                Resource: "*"
"""


def test_granted_from_terraform_sam_and_cdk_out(tmp_path):
    (tmp_path / "main.tf").write_text(TF)
    (tmp_path / "template.yaml").write_text(SAM)
    (tmp_path / "cdk.out").mkdir()
    (tmp_path / "cdk.out" / "App.template.json").write_text(
        json.dumps(
            {
                "Resources": {
                    "P": {
                        "Type": "AWS::IAM::Policy",
                        "Properties": {
                            "PolicyDocument": {
                                "Statement": [{"Effect": "Allow", "Action": ["kinesis:PutRecord"], "Resource": "*"}]
                            }
                        },
                    }
                }
            }
        )
    )
    grants = ic.granted([tmp_path])
    patterns = {g.pattern for g in grants.actions}
    assert {
        "dynamodb:GetItem",
        "dynamodb:Query",
        "s3:Get*",
        "sqs:SendMessage",
        "sqs:ReceiveMessage",
        "lambda:InvokeFunction",
        "kinesis:PutRecord",
    } <= patterns
    assert "dynamodb:PutItem" not in patterns and "s3:DeleteObject" not in patterns  # Deny statements
    policies = {p for p, _ in grants.unexpanded}
    assert {
        "arn:aws:iam::aws:policy/AmazonS3ReadOnlyAccess",
        "DynamoDBCrudPolicy",
        "AWSLambdaBasicExecutionRole",
        "arn:aws:iam::aws:policy/CloudWatchLogsFullAccess",
    } <= policies
    assert grants.files == 3
    assert [g.pattern for g in grants.allows("s3:GetObject")] == ["s3:Get*"]


def test_compare_and_command(runner, isolated_home, tmp_path):
    (tmp_path / "main.tf").write_text(TF)
    needed = ic.needed_from_calls(
        [
            dict(c("dynamodb", "GetItem", "orders"), id=1),
            dict(c("dynamodb", "PutItem", "orders"), id=2),
            dict(c("s3", "HeadObject", "b/k"), id=3),
        ],
        "calls.jsonl",
    )
    result = ic.compare(needed, ic.granted([tmp_path]))
    assert result.missing == ["dynamodb:PutItem"]
    assert {g.pattern for g in result.unused} == {"dynamodb:Query", "sqs:SendMessage", "sqs:ReceiveMessage"}
    assert result.as_dict()["needed"][0]["used_in"] == ["calls.jsonl:1"]

    (tmp_path / "app.py").write_text(
        "import boto3\nddb = boto3.client('dynamodb')\nddb.put_item(TableName='t')\n"
        "ddb.get_item(TableName='t', Key={})\n"
    )
    data = json.loads(runner.invoke(cli, ["check", "--iam", str(tmp_path), "--json"]).output)
    assert data["missing"] == ["dynamodb:PutItem"]
    assert {n["action"] for n in data["needed"]} == {"dynamodb:GetItem", "dynamodb:PutItem"}
    assert runner.invoke(cli, ["check", "--iam", str(tmp_path), "--strict"]).exit_code == 1
    text = runner.invoke(cli, ["check", "--iam", str(tmp_path)]).output
    assert "missing" in text and "Not expanded" in text and "AmazonS3ReadOnlyAccess" in text
