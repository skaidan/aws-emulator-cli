# Services guide

[Overview](#overview) · [S3](#s3) · [SQS](#sqs) · [DynamoDB](#dynamodb) · [SNS](#sns) · [Lambda](#lambda) · [Secrets Manager](#secrets-manager) · [SSM](#ssm-parameter-store) · [EventBridge](#eventbridge) · [Kinesis](#kinesis) · [Step Functions](#step-functions) · [describe](#any-resource-by-its-arn)

Every service command talks to the emulator on the selected port (`--port`, default 9297), with its endpoint, certificate and keys set explicitly. Even if your shell has real AWS credentials, **these commands never call AWS**.

Most accept `--json` for scripts, and the ones that delete ask for confirmation unless you pass `--yes`.

For operations `awsemu` doesn't cover, use the AWS CLI pointed at the emulator: `awsemu aws <service> <operation> ...`.

## Overview

```bash
awsemu overview                 # only services with something in them
awsemu overview --all           # empty ones too
awsemu overview -s s3 -s sqs    # just some
awsemu overview --json
```

It checks S3, SQS, DynamoDB, SNS, Lambda, Secrets Manager, SSM, Kinesis, EventBridge, Step Functions, CloudWatch Logs and IAM. If a service fails, it says so in its row and carries on with the rest.

## S3

```bash
awsemu s3 mb photos                        # create bucket(s)
awsemu s3 put ./cat.jpg photos/            # upload; a trailing / uses the file name
awsemu s3 put ./web photos/site/           # upload a whole folder
awsemu s3 ls                               # buckets
awsemu s3 ls photos                        # one level, with "folders"
awsemu s3 ls photos -r                     # everything, recursively
awsemu s3 cat photos/notes.txt             # to standard output
awsemu s3 get photos/cat.jpg ./downloads/
awsemu s3 presign photos/cat.jpg --expires 600
awsemu s3 rm photos/cat.jpg
awsemu s3 rm -r photos/site/ --yes         # a whole prefix
awsemu s3 rb photos --force --yes          # empty and delete the bucket
```

Buckets can be written as `photos/key` or `s3://photos/key`.

## SQS

```bash
awsemu sqs create jobs-dlq
awsemu sqs create jobs --dlq jobs-dlq --max-receive 3 --visibility-timeout 30
awsemu sqs create orders --fifo --dedup    # adds .fifo if missing

awsemu sqs send jobs '{"id": 1}' -a kind=new
echo '{"id": 2}' | awsemu sqs send jobs --file -
awsemu sqs send orders.fifo '{"id": 3}' --group customer-7

awsemu sqs ls                              # queues with visible / in-flight / delayed messages
awsemu sqs receive jobs                    # messages stay in the queue…
awsemu sqs receive jobs --delete           # …unless --delete
awsemu sqs info jobs                       # all attributes
awsemu sqs purge jobs --yes
awsemu sqs rm jobs --yes
```

Queues can be given by name or URL.

## DynamoDB

Items are written and shown as plain JSON. `awsemu` converts to and from DynamoDB's format (`{"S": ...}`, `{"N": ...}`) for you.

```bash
awsemu ddb create users --pk id                        # partition key of type S
awsemu ddb create events --pk user --sk date:N         # with a numeric sort key

awsemu ddb put users '{"id": "u1", "name": "Ana", "age": 30, "tags": ["admin"]}'
awsemu ddb put users --file users.json                 # one object or a list (batches of 25)

awsemu ddb get users '{"id": "u1"}'
awsemu ddb scan users                                  # readable table
awsemu ddb scan users -n 0 --json                      # everything, as JSON
awsemu ddb delete users '{"id": "u1"}'
awsemu ddb ls
awsemu ddb describe users
awsemu ddb drop users --yes
```

Types: text → `S`, number → `N`, `true/false` → `BOOL`, `null` → `NULL`, list → `L`, object → `M`. Decimal numbers are stored without losing precision.

## SNS

```bash
awsemu sns create orders
awsemu sns create orders.fifo --fifo

# Deliver to an SQS queue: awsemu creates the subscription AND the queue policy.
awsemu sqs create order-events
awsemu sns subscribe orders --to-sqs order-events --raw   # --raw: without the SNS JSON envelope

# Deliver to a Lambda function: adds the invoke permission.
awsemu sns subscribe orders --to-lambda process-order

# With a filter
awsemu sns subscribe orders --to-sqs new-only --filter '{"kind": ["new"]}'

awsemu sns publish orders '{"order": 42}' --subject created -a kind=new
awsemu sns ls                    # topics with their targets
awsemu sns subs orders
awsemu sns unsubscribe arn:aws:sns:us-east-1:000000000000:orders:...
awsemu sns rm orders --yes
```

End to end, SNS → SQS:

```bash
awsemu sns create orders
awsemu sqs create events
awsemu sns subscribe orders --to-sqs events --raw
awsemu sns publish orders '{"order": 42}'
awsemu sqs receive events --delete      # → {"order": 42}
```

## Lambda

```bash
# hello.py
# def handler(event, context):
#     return {"greeting": f"hello {event.get('name', 'world')}"}

awsemu lambda deploy hello ./hello.py                  # creates the function
awsemu lambda invoke hello '{"name": "Ana"}'           # response + log
awsemu lambda invoke hello '{"name": "Ana"}' --raw     # just the response (for scripts)
awsemu lambda deploy hello ./hello.py                  # the second time, updates the code
```

`deploy` accepts a folder (its contents are packaged, without `__pycache__`, `.git`, `.venv`…), a single file or a ready-made `.zip`. If you don't pass `--handler` and `--runtime`, it guesses them:

| Code | Handler | Runtime |
| --- | --- | --- |
| `app.py` with `def handler(...)` | `app.handler` | `python3.12` |
| `lambda_function.py` with `def lambda_handler(...)` | `lambda_function.lambda_handler` | `python3.12` |
| `index.mjs` with `export const handler` | `index.handler` | `nodejs20.x` |
| `index.js` with `exports.handler` | `index.handler` | `nodejs20.x` |

If you don't pass `--role`, it creates (once) the `awsemu-lambda-role` role with Lambda's trust policy.

```bash
awsemu lambda deploy api ./src --handler app.main --runtime python3.13 \
    -e STAGE=local -e TABLE=users --timeout 30 --memory 512
awsemu lambda invoke api --file event.json
awsemu lambda invoke api '{}' --async          # without waiting for the result
awsemu lambda logs api -f                      # CloudWatch logs (/aws/lambda/api), see the note
awsemu lambda info api
awsemu lambda ls
awsemu lambda rm api --yes
```

`invoke` exits with code 1 if the function raises an error, so scripts can detect it.

> **Where to see what a function prints.** The emulator doesn't send Lambda output to CloudWatch Logs (checked in CI), so `lambda logs` finds nothing. `lambda invoke` does show the log of each invocation: `START`, whatever the function prints and `REPORT` with the duration. `--async` invocations and those triggered by SNS or EventBridge are accepted, but their output isn't visible.

## Secrets Manager

```bash
awsemu secrets put db/password 's3cr3t'                         # creates the secret
awsemu secrets put db/config '{"host": "db", "port": 5432}'     # JSON
awsemu secrets put db/password 'new-value'                      # if it exists, stores a new version
awsemu secrets put tls/key --file key.pem
awsemu secrets get db/config                                    # formatted JSON
awsemu secrets get db/config --raw                              # as-is (for scripts)
awsemu secrets get db/password --stage AWSPREVIOUS              # previous version
awsemu secrets ls                                               # names, never values
awsemu secrets info db/password                                 # metadata and versions
awsemu secrets rm db/password --yes                             # recoverable for 7 days
awsemu secrets rm db/password --now --yes                       # no recovery
```

## SSM Parameter Store

```bash
awsemu ssm put /app/db/host localhost
awsemu ssm put /app/db/password s3cr3t --secure     # SecureString (shown as ****)
awsemu ssm put /app/hosts a,b,c --list              # StringList
awsemu ssm get /app/db/password                     # decrypted
awsemu ssm ls                                       # all of them
awsemu ssm ls /app --values                         # under a path, with values
awsemu ssm rm /app/db/host /app/db/password
```

`put` overwrites if it exists (and bumps the version). As in AWS, names can't start with `aws` or `ssm`: `/awsapp/x` is rejected too.

## EventBridge

`events rule` creates the rule and its target in one step, with the permissions needed (the SQS queue policy or the Lambda invoke permission):

```bash
awsemu sqs create order-events
awsemu events rule orders-created --source app.orders --to-sqs order-events
awsemu events put app.orders OrderCreated '{"id": 42, "total": 120}'
awsemu sqs receive order-events --delete               # the full event, with "detail"

awsemu events rule big-orders \
    --pattern '{"source": ["app.orders"], "detail": {"total": [{"numeric": [">", 100]}]}}' \
    --to-lambda alert
awsemu events rule every-5-min --schedule 'rate(5 minutes)' --to-sns reminders

awsemu events rules                    # rules on the default bus with pattern and targets
awsemu events buses
awsemu events create-bus orders        # a bus of your own; then --bus orders in rule/put/rules/rm
awsemu events rm orders-created --yes  # removes the targets and deletes the rule
```

## Kinesis

```bash
awsemu kinesis create clicks --shards 2        # waits until it's active
awsemu kinesis put clicks '{"page": "/"}' -k user-1
cat event.bin | awsemu kinesis put clicks --file -
awsemu kinesis read clicks                     # from the start, all shards
awsemu kinesis read clicks --from latest -f    # only new records, non-stop (Ctrl+C)
awsemu kinesis read clicks --json -n 0         # one JSON object per record, no limit
awsemu kinesis ls
awsemu kinesis rm clicks --yes
```

`read` shows the data as compact JSON if it is JSON, as text if it's UTF-8, and in hex otherwise.

## Step Functions

```bash
# flow.asl.json
# {"StartAt": "Greet",
#  "States": {"Greet": {"Type": "Pass",
#                       "Parameters": {"greeting.$": "States.Format('hello {}', $.name)"},
#                       "End": true}}}

awsemu sfn deploy greeter flow.asl.json        # creates it (and the awsemu-sfn-role role) or updates it
awsemu sfn start greeter '{"name": "Ana"}'     # waits and shows the output
awsemu sfn start greeter --raw                 # just the output JSON; exit code 1 if it fails
awsemu sfn start greeter --no-wait
awsemu sfn executions greeter
awsemu sfn ls
awsemu sfn rm greeter --yes
```

If the execution fails, `start` shows the error and its cause (or looks them up in the history) and exits with code 1. The definition can be a file or inline JSON; it's validated before being sent.

## Any resource by its ARN

```bash
awsemu describe arn:aws:dynamodb:us-east-1:000000000000:table/users
awsemu describe arn:aws:sqs:us-east-1:000000000000:jobs
awsemu describe arn:aws:s3:::photos/cat.jpg
awsemu describe arn:aws:states:us-east-1:000000000000:execution:greeter:awsemu-1a2b3c
```

Works with ARNs of S3, SQS, DynamoDB, SNS (topics and subscriptions), Lambda, Secrets Manager, SSM, Kinesis, EventBridge (rules and buses), Step Functions (state machines and executions), CloudWatch Logs and IAM (roles, users and policies). The output is JSON.

## Emulator settings

```bash
awsemu config show                 # contents of ~/.aws/emulator/config.toml (or $EMULATOR_CONFIG)
awsemu config telemetry            # current setting
awsemu config telemetry off        # [telemetry] enabled = false
awsemu config path
```

`awsemu` edits the file without losing your comments or other settings.
