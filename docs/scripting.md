# Scripting: JSON output and exit codes

Everything on this page is a stable interface: scripts can rely on it.

## Stability promise

- From 0.7.0, the exit codes and the `--json` formats below only change in a release whose CHANGELOG lists the change under **Breaking**. Until 1.0, that can happen in a minor release (0.x); from 1.0, only in a major one.
- **Adding** a field to a JSON object, or a new command or option, isn't a breaking change: parse JSON by key and ignore keys you don't know.
- Human-readable output (tables, colours, messages) is **not** part of the interface and may change at any time. Use `--json`, `--raw` or exit codes in scripts, never the tables.
- Each format is pinned by `tests/test_json_contract.py`; a change that breaks it fails CI.

## Exit codes

| Code | Name | Meaning |
| --- | --- | --- |
| `0` | OK | The command did what was asked. |
| `1` | FAILED | It ran, but something failed: an AWS error, a Lambda function or Step Functions execution that failed, a resource not found (`ddb get`, `ssm rm`), a seed resource that couldn't be applied, the emulator not starting, `doctor` finding a problem. |
| `2` | USAGE | Nothing was done: wrong arguments or options, invalid JSON in an argument, an invalid seed or `awsemu.toml`. |
| `3` | NOT_HEALTHY | Only `awsemu status`: the emulator isn't running or isn't healthy. |

Commands that run another program return **that program's** exit code: `exec`, `aws`, `shell`, `start -f` (the emulator in the foreground) and `image build` (Docker).

```bash
awsemu status >/dev/null || awsemu up        # 3 → start it
awsemu lambda invoke fn "$payload" --raw > out.json || echo "the function failed"
awsemu seed validate seed.yaml; [ $? -eq 2 ] && echo "fix the seed"
```

## JSON conventions

- `--json` prints one JSON document to standard output (`kinesis read --json` prints one object per line, see below). Warnings and errors go to standard error.
- **awsemu's own summaries** (`status`, `overview`, `doctor`, `fidelity`, `sqs ls`, `sns ls`, `ddb ls`, `kinesis read`) use `snake_case` keys.
- **AWS resources passed through** keep AWS's own field names (`PascalCase` or `camelCase`, as the AWS API returns them): buckets, objects, messages, functions, state machines, executions, rules, buses, subscriptions, secrets, parameters, streams.
- Dates are ISO 8601 strings (`2026-11-16T12:00:00+00:00`). Numbers stored by DynamoDB come out as JSON numbers; binary data as base64.
- `null` means "not known" or "doesn't apply" (for example `pid` when awsemu didn't start the emulator).

## Formats

### `awsemu status --json`

```json
{
  "port": 9297,
  "status": "healthy",              // healthy | unhealthy | stopped
  "detail": "ok",
  "endpoint": "https://127.0.0.1:9297",
  "mode": "native",                 // native | docker | external | -
  "pid": 12345,                     // null in Docker or when not started by awsemu
  "container": null,                // the container name in Docker
  "uptime_seconds": 42.5,
  "auth": true,                     // null when the emulator isn't running
  "files": "/home/ana/.aws/emulator/9297",
  "log": "/home/ana/.aws/emulator-cli/9297/emulator.log"
}
```

`status --all --json` returns a list of these. Exit code 3 if the instance isn't healthy (without `--all`).

### `awsemu overview --json`

An object keyed by AWS service name (`s3`, `sqs`, `dynamodb`, `sns`, `lambda`, `secretsmanager`, `ssm`, `kinesis`, `events`, `stepfunctions`, `logs`, `iam`):

```json
{
  "s3":  {"label": "S3 buckets", "items": ["photos"], "error": null},
  "sqs": {"label": "SQS queues", "items": [], "error": "InternalFailure: ..."}
}
```

### `awsemu doctor --json`

```json
{
  "ok": false,
  "problems": 1,
  "checks": [
    {"check": "python", "result": "ok", "detail": "3.12.4", "fix": null},
    {"check": "boto3", "result": "fail", "detail": "not installed", "fix": "pip install boto3"}
  ]
}
```

`result` is `ok`, `warn` or `fail`; `problems` counts the `fail` ones, and the exit code is 1 when there's any.

### `awsemu fidelity --json`

```json
{
  "release": "v1.0.385",
  "commit": "813af480bf7f...",
  "scored_at": "2026-11-14T18:34:58.642796+00:00",
  "installed": "1.0.385",           // null if the binary isn't installed here
  "services": {
    "s3": {
      "passed": 3, "total": 4,
      "multi_service_passed": 1, "multi_service_total": 1,
      "failures": [                 // only with --failures
        {"test": "...", "operation": "PutObject", "mismatch": "status",
         "expected": "400 InvalidArgument", "actual": "200", "step": "2/3"}
      ]
    }
  }
}
```

### `awsemu sqs ls --json`

```json
[{"name": "jobs", "url": "https://127.0.0.1:9297/000000000000/jobs",
  "visible": 3, "in_flight": 1, "delayed": 0}]
```

### `awsemu sns ls --json`

```json
[{"name": "orders", "arn": "arn:aws:sns:us-east-1:000000000000:orders",
  "subscriptions": [ /* AWS Subscription objects: SubscriptionArn, Protocol, Endpoint, TopicArn, Owner */ ]}]
```

### `awsemu ddb ls --json`

```json
[{"name": "events",
  "partition_key": {"name": "user", "type": "S"},
  "sort_key": {"name": "at", "type": "N"},      // null without a sort key
  "item_count": 2,
  "status": "ACTIVE"}]
```

### `awsemu kinesis read --json`

One JSON object **per line** (JSON Lines), so you can stream it:

```json
{"shard": "shardId-000000000000", "sequence": "4959...", "key": "user-1", "data": "{\"page\": \"/\"}", "arrived": "2026-11-16T12:00:00+00:00"}
```

`data` is the record as text: compact JSON if it was JSON, UTF-8 text, or `0x…` hex for binary data.

### AWS resources, as AWS returns them

| Command | Output |
| --- | --- |
| `s3 ls --json` | List of buckets (`Name`, `CreationDate`) |
| `s3 ls BUCKET[/PREFIX] --json` | `{"prefixes": ["a/"], "objects": [ {Key, Size, LastModified, ETag, …} ]}` |
| `sqs receive --json` | List of messages (`MessageId`, `Body`, `Attributes`, `MessageAttributes`, `ReceiptHandle`, …) |
| `ddb scan --json` | List of items as plain JSON (`{"id": "u1", "age": 30}`) |
| `lambda ls --json` | List of function configurations (`FunctionName`, `Runtime`, `Handler`, …) |
| `sfn ls --json`, `sfn executions NAME --json` | Lists of state machines / executions |
| `kinesis ls --json` | List of stream summaries (`StreamName`, `StreamStatus`, `OpenShardCount`, …) |
| `events rules --json` | List of rules, each with an added `Targets` list |
| `events buses --json` | List of event buses |
| `sns subs --json` | List of subscriptions |
| `secrets ls --json` | List of secret metadata (never values) |
| `ssm ls --json` | List of parameters, with `Value` when available |
| `describe ARN`, `ddb describe` | The AWS description of the resource |

### `--raw`

`lambda invoke --raw`, `sfn start --raw` and `secrets get --raw` print only the result, untouched, and exit with 1 if it's a failure. `logs --raw` prints the emulator's log lines as they are.

### Other machine-readable outputs

- `awsemu env --shell dotenv`: `KEY=value` lines.
- `awsemu seed export`: YAML in the [seed format](seeds.md).
- `awsemu completion SHELL`: the completion script.
