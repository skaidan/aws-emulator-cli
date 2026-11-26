"""The IAM policy a set of API calls needs, from the proxy's calls log.

Each call becomes an IAM action (``dynamodb:PutItem``) and, where the call names a
resource, a resource ARN (``arn:aws:dynamodb:*:*:table/orders``). Most actions are
``<service prefix>:<Operation>``; the exceptions that matter in practice are mapped
(S3's ``ListObjectsV2`` is ``s3:ListBucket``, Lambda's ``Invoke`` is
``lambda:InvokeFunction``, batch calls need the single action…). Actions that don't
support resource-level permissions, or calls without a resource, get ``"*"``.

It's a starting point to review, not a guarantee: AWS's Service Authorization
Reference is the source of truth, some calls need more than one action (KMS for an
encrypted object, ``iam:PassRole`` when creating a function), and only calls that
went through the proxy are seen.
"""

from __future__ import annotations

from dataclasses import dataclass, field

# IAM prefix when the botocore signing name/endpoint prefix isn't it
PREFIX_OVERRIDES = {"monitoring": "cloudwatch", "email": "ses", "streams.dynamodb": "dynamodb",
                    "execute-api": "execute-api"}
NO_PERMISSION = {("sts", "GetCallerIdentity")}  # always allowed

S3_ACTIONS = {
    "ListObjects": "ListBucket", "ListObjectsV2": "ListBucket", "HeadBucket": "ListBucket",
    "ListObjectVersions": "ListBucketVersions", "ListMultipartUploads": "ListBucketMultipartUploads",
    "ListParts": "ListMultipartUploadParts", "ListBuckets": "ListAllMyBuckets",
    "HeadObject": "GetObject", "CreateMultipartUpload": "PutObject", "UploadPart": "PutObject",
    "CompleteMultipartUpload": "PutObject", "UploadPartCopy": "PutObject", "CopyObject": "PutObject",
    "DeleteObjects": "DeleteObject",
    "PutBucketNotificationConfiguration": "PutBucketNotification",
    "GetBucketNotificationConfiguration": "GetBucketNotification",
    "PutBucketCors": "PutBucketCORS", "GetBucketCors": "GetBucketCORS", "DeleteBucketCors": "PutBucketCORS",
    "PutBucketLifecycleConfiguration": "PutLifecycleConfiguration",
    "GetBucketLifecycleConfiguration": "GetLifecycleConfiguration",
    "DeleteBucketLifecycle": "PutLifecycleConfiguration",
    "PutBucketEncryption": "PutEncryptionConfiguration", "GetBucketEncryption": "GetEncryptionConfiguration",
    "DeleteBucketEncryption": "PutEncryptionConfiguration",
    "PutBucketTagging": "PutBucketTagging", "DeleteBucketTagging": "PutBucketTagging",
}
S3_OBJECT_ACTIONS = {"GetObject", "PutObject", "DeleteObject", "GetObjectTagging", "PutObjectTagging",
                     "DeleteObjectTagging", "GetObjectAcl", "PutObjectAcl", "AbortMultipartUpload",
                     "ListMultipartUploadParts", "RestoreObject", "GetObjectAttributes", "GetObjectVersion",
                     "GetObjectRetention", "PutObjectRetention", "GetObjectLegalHold", "PutObjectLegalHold"}
OTHER_ACTIONS = {
    ("lambda", "Invoke"): "InvokeFunction", ("lambda", "InvokeWithResponseStream"): "InvokeFunction",
    ("sqs", "SendMessageBatch"): "SendMessage", ("sqs", "DeleteMessageBatch"): "DeleteMessage",
    ("sqs", "ChangeMessageVisibilityBatch"): "ChangeMessageVisibility",
    ("sns", "PublishBatch"): "Publish",
}
# Actions without resource-level permissions: always "*"
STAR_ONLY = {"s3:ListAllMyBuckets", "dynamodb:ListTables", "sqs:ListQueues", "sns:ListTopics",
             "lambda:ListFunctions", "kinesis:ListStreams", "secretsmanager:ListSecrets",
             "ssm:DescribeParameters", "states:ListStateMachines", "logs:DescribeLogGroups",
             "events:ListRules", "events:ListEventBuses", "iam:ListRoles", "kms:ListKeys", "kms:ListAliases",
             "cloudwatch:PutMetricData", "cloudwatch:GetMetricData", "cloudwatch:ListMetrics",
             "sns:ListSubscriptions", "lambda:ListEventSourceMappings", "secretsmanager:GetRandomPassword",
             "kms:CreateKey"}


def prefix(service: str) -> str:
    try:
        import botocore.session

        meta = botocore.session.get_session().get_service_model(service).metadata
        name = meta.get("signingName") or meta.get("endpointPrefix") or service
    except Exception:  # noqa: BLE001 - a service botocore doesn't know keeps its own name
        name = service
    return PREFIX_OVERRIDES.get(name, name)


def action(service: str, operation: str) -> str | None:
    if (service, operation) in NO_PERMISSION or not operation:
        return None
    if service == "s3":
        return f"s3:{S3_ACTIONS.get(operation, operation)}"
    return f"{prefix(service)}:{OTHER_ACTIONS.get((service, operation), operation)}"


def resource_arn(service: str, act: str, resource: str, region: str, account: str) -> str:
    """The ARN an action applies to, from the call's resource ("" -> "*")."""
    if not resource or act in STAR_ONLY:
        return "*"
    if resource.startswith("arn:"):
        return resource
    r, a = region, account
    name = act.split(":", 1)[1]
    if service == "s3":
        bucket = resource.split("/", 1)[0]
        return f"arn:aws:s3:::{bucket}/*" if name in S3_OBJECT_ACTIONS else f"arn:aws:s3:::{bucket}"
    templates = {
        "dynamodb": f"arn:aws:dynamodb:{r}:{a}:table/{resource}",
        "sqs": f"arn:aws:sqs:{r}:{a}:{resource}",
        "sns": f"arn:aws:sns:{r}:{a}:{resource}",
        "lambda": f"arn:aws:lambda:{r}:{a}:function:{resource}",
        "kinesis": f"arn:aws:kinesis:{r}:{a}:stream/{resource}",
        "secretsmanager": f"arn:aws:secretsmanager:{r}:{a}:secret:{resource}-*",
        "ssm": f"arn:aws:ssm:{r}:{a}:parameter/{resource.lstrip('/')}",
        "stepfunctions": f"arn:aws:states:{r}:{a}:stateMachine:{resource}",
        "logs": f"arn:aws:logs:{r}:{a}:log-group:{resource}:*",
        "events": f"arn:aws:events:{r}:{a}:rule/{resource}",
        "iam": f"arn:aws:iam::{a}:role/{resource}",
        "kms": f"arn:aws:kms:{r}:{a}:key/{resource}",
    }
    if service == "events" and name == "PutEvents":
        return f"arn:aws:events:{r}:{a}:event-bus/{resource}"
    if service == "stepfunctions" and name in ("DescribeExecution", "StopExecution", "GetExecutionHistory"):
        return f"arn:aws:states:{r}:{a}:execution:*"  # the log only has the execution's name
    return templates.get(service, "*")


@dataclass
class Policy:
    document: dict
    actions: dict[str, set[str]] = field(default_factory=dict)  # action -> resources
    skipped: list[str] = field(default_factory=list)  # operations that need no permission or are unknown
    calls: int = 0


def build(calls: list[dict], region: str = "*", account: str = "*", services: set[str] | None = None) -> Policy:
    """The policy for ``calls``. Calls that failed, injected faults included, count too:
    the code made them, so it needs the permission."""
    actions: dict[str, set[str]] = {}
    skipped: set[str] = set()
    used = 0
    for call in calls:
        service, operation = call.get("service") or "", call.get("operation") or ""
        if services and service not in services:
            continue
        act = action(service, operation)
        if not act:
            if service:
                skipped.add(f"{service}:{operation or '?'}")
            continue
        used += 1
        actions.setdefault(act, set()).add(resource_arn(service, act, call.get("resource") or "", region, account))
    for act, res in actions.items():
        if "*" in res:
            actions[act] = {"*"}
    # One statement per set of resources, actions sorted: easy to read and to diff
    groups: dict[tuple[str, ...], list[str]] = {}
    for act, res in sorted(actions.items()):
        groups.setdefault(tuple(sorted(res)), []).append(act)
    statements = []
    for i, (res, acts) in enumerate(sorted(groups.items(), key=lambda kv: (kv[1][0], kv[0])), 1):
        statements.append({"Sid": f"Awsemu{i}", "Effect": "Allow", "Action": acts if len(acts) > 1 else acts[0],
                           "Resource": list(res) if len(res) > 1 else res[0]})
    return Policy({"Version": "2012-10-17", "Statement": statements}, actions, sorted(skipped), used)


def terraform(policy: Policy, name: str = "awsemu") -> str:
    """The same policy as a Terraform ``aws_iam_policy_document`` data source."""
    lines = [f'data "aws_iam_policy_document" "{name}" {{']
    for st in policy.document["Statement"]:
        acts = st["Action"] if isinstance(st["Action"], list) else [st["Action"]]
        res = st["Resource"] if isinstance(st["Resource"], list) else [st["Resource"]]
        lines += ["  statement {", f'    sid       = "{st["Sid"]}"',
                  "    actions   = [" + ", ".join(f'"{a}"' for a in acts) + "]",
                  "    resources = [" + ", ".join(f'"{r}"' for r in res) + "]", "  }"]
    lines.append("}")
    return "\n".join(lines) + "\n"
