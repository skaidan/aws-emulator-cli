# IAM: the permissions your code needs

The emulator doesn't check IAM the way AWS does: a request signed with the emulator's keys is never denied for a missing permission, and resource policies (KMS key policies, S3 bucket policies) aren't evaluated. So tests pass locally and the first `AccessDenied` shows up after deploying. awsemu can't make the emulator enforce IAM, but it can tell you, from what your code does, which permissions it needs and which ones your infrastructure doesn't grant.

## The policy your calls need

Run your tests through the [proxy](proxy.md), then turn its log into a policy:

```bash
awsemu proxy start -d
awsemu exec --proxy -- pytest
awsemu iam policy                                     # an IAM policy document (JSON)
awsemu iam policy --account 123456789012 --region eu-west-1
awsemu iam policy --service dynamodb --service s3
awsemu iam policy --format terraform -o policy.tf     # an aws_iam_policy_document
```

Each call becomes an action and, when the call names a resource, that resource's ARN:

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {"Sid": "Awsemu1", "Effect": "Allow", "Action": ["dynamodb:GetItem", "dynamodb:Query"],
     "Resource": "arn:aws:dynamodb:eu-west-1:123456789012:table/orders"},
    {"Sid": "Awsemu2", "Effect": "Allow", "Action": "s3:PutObject", "Resource": "arn:aws:s3:::photos/*"},
    {"Sid": "Awsemu3", "Effect": "Allow", "Action": "dynamodb:ListTables", "Resource": "*"}
  ]
}
```

- **Actions** are `<service prefix>:<Operation>` (`dynamodb:PutItem`, `states:StartExecution` for Step Functions), with the usual exceptions mapped: S3's `ListObjectsV2` and `HeadBucket` need `s3:ListBucket`, `HeadObject` needs `s3:GetObject`, multipart uploads and `CopyObject` need `s3:PutObject`, Lambda's `Invoke` is `lambda:InvokeFunction`, SQS and SNS batch calls need the single action. `sts:GetCallerIdentity` needs no permission and is left out.
- **Resources**: tables, queues, topics, functions, streams, secrets (`secret:NAME-*`, for the suffix AWS adds), parameters, state machines, log groups, rules and roles get their ARN; S3 object actions get `bucket/*`, bucket actions the bucket. Actions that don't support resource-level permissions (`ListTables`, `ListAllMyBuckets`, `PutMetricData`…) and calls without a resource get `"*"`, and the command lists them. Region and account are `*` unless you pass `--region` and `--account`.
- Calls that failed count too, injected faults included: the code made them, so it needs the permission.

Review it before you use it. It only has what the proxy saw, so a code path your tests don't run isn't in it. Some calls need permissions they don't name: KMS for encrypted objects, queues and secrets (`kms:Decrypt`, `kms:GenerateDataKey`), `iam:PassRole` when creating a function or a state machine with a role. Batch calls across tables (`BatchWriteItem`) name no single table, so they get `"*"`. AWS's [Service Authorization Reference](https://docs.aws.amazon.com/service-authorization/latest/reference/reference_policies_actions-resources-contextkeys.html) is the source of truth.

## Permissions your infrastructure is missing

`awsemu check --iam` compares the actions your code needs with the `Allow` actions in the policies of your infrastructure, and lists what no policy grants:

```bash
awsemu check --iam                    # the code (static scan) against the policies in this folder
awsemu check --iam --from-calls infra # what the tests called (the proxy's log) against infra/
awsemu check --iam --strict           # exit code 1 if an action is missing (CI)
awsemu check --iam --json
```

```
actions from  12 call(s) in calls.jsonl
policies      2 file(s), 9 allowed action(s)

 action                 granted by         used in
 dynamodb:GetItem       dynamodb:GetItem   calls.jsonl:3
 dynamodb:PutItem       missing            calls.jsonl:1 (+4)
 s3:GetObject           s3:Get*            calls.jsonl:7

Not expanded (they may grant more): AWSLambdaBasicExecutionRole, DynamoDBCrudPolicy
Granted but not used by these calls: sqs:DeleteMessage

⚠ 1 action(s) your code needs aren't allowed by any policy here: dynamodb:PutItem
```

Where the needed actions come from: with `--from-calls` (or `--calls-file FILE`), the calls the proxy logged; otherwise the operations the static scan of `awsemu check` finds in the code, resolved with botocore's models, offline.

Where the granted ones come from:

| Source | What it reads |
| --- | --- |
| Terraform | `aws_iam_policy_document` statements (`actions = [...]`), and JSON policies with `Action`, inline in `jsonencode({...})` or heredocs |
| CloudFormation / SAM | every policy statement with `Action` (roles, managed and inline policies, queue and topic policies) |
| CDK | the synthesized templates in `cdk.out/` (run `cdk synth` first) |

Wildcards work as in IAM (`dynamodb:*`, `s3:Get*`). `Deny` statements are skipped. Managed policies (`arn:aws:iam::aws:policy/...`, `ManagedPolicyArns`) and SAM policy templates (`DynamoDBCrudPolicy`) are listed as not expanded: awsemu doesn't know what they grant, so an action they cover can show as missing. "Granted but not used" lists allowed actions none of the needed ones use, a hint for tightening a policy.

What it doesn't do: it compares actions, not resources or conditions, and across every policy in the project rather than the one role your code runs as. Permission boundaries, SCPs and resource policies aren't considered. A clean result means "nothing obviously missing", not "this will work on AWS".
