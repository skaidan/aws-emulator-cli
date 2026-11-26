# Scripting: JSON output and exit codes

Everything on this page is a stable interface: scripts can rely on it.

## Stability promise

- From 0.7.0, the exit codes and the `--json` formats below only change in a release whose CHANGELOG lists the change under **Breaking**. Until 1.0, that can happen in a minor release (0.x); from 1.0, only in a major one.
- **Adding** a field to a JSON object, or a new command or option, isn't a breaking change: parse JSON by key and ignore keys you don't know.
- Human-readable output (tables, colours, messages) is **not** part of the interface and may change at any time. Use `--json`, `--raw` or exit codes in scripts, never the tables.
- Each format is pinned by `tests/test_json_contract.py`; a change that breaks it fails CI.
- Renamed options, settings and fields go through a deprecation period with warnings before they stop working: see [deprecations.md](deprecations.md).

## Exit codes

| Code | Name | Meaning |
| --- | --- | --- |
| `0` | OK | The command did what was asked. |
| `1` | FAILED | It ran, but something failed: an AWS error, a Lambda function or Step Functions execution that failed, a resource not found (`ddb get`, `ssm rm`), a seed resource that couldn't be applied, the emulator not starting, `doctor` finding a problem, `check --strict` finding known differences. |
| `2` | USAGE | Nothing was done: wrong arguments or options, invalid JSON in an argument, an invalid seed or `awsemu.toml`. |
| `3` | NOT_HEALTHY | Only `awsemu status` (the emulator isn't running or isn't healthy) and `awsemu proxy status` (no proxy running). |

Commands that run another program return **that program's** exit code: `exec`, `aws`, `shell`, `start -f` (the emulator in the foreground) and `image build` (Docker).

```bash
awsemu status >/dev/null || awsemu up        # 3 → start it
awsemu lambda invoke fn "$payload" --raw > out.json || echo "the function failed"
awsemu seed validate seed.yaml; [ $? -eq 2 ] && echo "fix the seed"
```

## JSON conventions

Every `--json` output has a **JSON Schema** in [`docs/schemas/`](schemas/README.md), and the tests validate real outputs against them, so scripts can check what they read.

- `--json` prints one JSON document to standard output (`kinesis read --json` prints one object per line, see below). Warnings and errors go to standard error.
- **awsemu's own summaries** (`status`, `overview`, `doctor`, `fidelity`, `check`, `install --list`, `issues`, `snapshot ls`, `proxy status`, `proxy calls`, `proxy faults`, `sqs ls`, `sns ls`, `ddb ls`, `kinesis read`) use `snake_case` keys.
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

### `awsemu fidelity --compare VERSION --json`

```json
{
  "from": {"release": "v1.0.385", "suite": "v1.0.0"},   // suite: fidelity tests version, null if unknown
  "to": {"release": "v1.0.390", "suite": "v1.0.0"},
  "services": {
    "sqs": {
      "from": {"passed": 284, "total": 335}, "to": {"passed": 285, "total": 336},
      "fixed": ["..."], "regressed": ["sqs-send-1"],       // test ids
      "added_passing": [], "added_failing": ["..."], "removed": []
    }
  }
}
```

### `awsemu check --json`

```json
{
  "release": "v1.0.385",
  "suite": "v1.0.0",                // fidelity tests version, "main", or the --manifest file name
  "scanned_files": 42,
  "sources": ["python", "terraform"],
  "operations": [
    {
      "operation": "dynamodb:TransactWriteItems", "service": "dynamodb",
      "locations": [{"file": "app/orders.py", "line": 41, "source": "python"}],
      "tests": 104, "passed": 94,
      "differences": [              // the first 3, or all with --all
        {"test": "...", "kind": "wire",            // wire | behavioral
         "operation": "TransactWriteItems", "mismatch": "status",
         "expected": "400 ValidationException", "actual": "200", "step": "6/15",
         "at_operation": true, "matches_usage": false,
         "url": null,               // link to the test file, when known
         "issues": [{"title": "…", "severity": "HIGH", "state": "open", "url": "https://github.com/aws/aws-emulator/blob/main/issues/…"}],
         "fixed_in": "v1.0.611"}    // a newer release where the test passes, else null
      ],
      "other_failing": 8
    }
  ],
  "uncovered": ["dynamodb:DescribeTimeToLive"],   // operations with no fidelity tests
  "services": [
    {"service": "dynamodb", "sources": ["python", "terraform"], "tests": 1481, "passed": 1172,
     "resources": [{"type": "aws_dynamodb_table", "file": "main.tf", "line": 1, "source": "terraform"}],
     "cloudformation": null}        // {"tests", "passed", "failing": [ids]} with CloudFormation/SAM/CDK
  ],
  "summary": {"operations": 3, "services": 2, "operations_with_differences": 3,
              "differences": 14,            // distinct failing tests
              "explained_by_issues": 5,     // null with --no-explain
              "fixed_in_latest": 10,        // null when not compared (--no-explain, --release latest)
              "latest": "v1.0.611"}
}
```

With `--strict`, the exit code is 1 when `operations_with_differences` isn't 0.

### `awsemu proxy calls --json`

A list of calls, oldest first (`--follow --json`: one object per line, as they happen):

```json
[
  {"id": 12, "time": "2026-11-25T10:42:01.140+00:00",
   "service": "dynamodb", "operation": "PutItem", "resource": "orders",   // "" when unknown
   "method": "POST", "path": "/", "status": 400,
   "error": "ThrottlingException",          // AWS error code, null when it succeeded
   "latency_ms": 1.1, "request_id": "…",
   "fault": "dynamodb=throttle@10%",        // the fault rule(s) that changed it, else null
   "bytes_in": 52, "bytes_out": 98}
]
```

The same objects are in `~/.aws/emulator-cli/proxy/<port>/calls.jsonl`, and in `.calls` of the pytest fixtures.

### `awsemu proxy status --json`

```json
{"running": true, "emulator_port": 9297, "port": 9298, "endpoint_url": "https://127.0.0.1:9298",
 "pid": 4242, "ca": "/home/me/.aws/emulator-cli/proxy/ca.pem", "calls": 12,
 "faults": ["dynamodb=throttle@10%"], "calls_file": "…/calls.jsonl"}
```

Not running: `{"running": false, "emulator_port": 9297}` and exit code 3.

`awsemu proxy faults --json`: `[{"rule": "dynamodb=throttle@10%", "hits": 3, "active": true, "remaining_s": null}]` (`remaining_s` for rules with `for DURATION`; `active` is false once a rule ran out).

### `awsemu issues SERVICE --json`

```json
[
  {"title": "DynamoDB ValidationException envelope diverges: …", "severity": "HIGH",   // CRITICAL|HIGH|MEDIUM|LOW|null
   "state": "open",                       // open | fixed
   "services": ["dynamodb"], "operations": ["GetItem"], "tests": ["…fidelity test ids…"],
   "kind": "wire", "created": "2026-11-20", "name": "20261120T225636Z-dynamodb-….md",
   "url": "https://github.com/aws/aws-emulator/blob/main/issues/things-that-do-not-work/…"}
]
```

With `--fixed`, each one also has `"fails_in_release": true|false`. `--show NAME --json` returns one object with the whole file in `"text"`.

### `awsemu install --list --json`

```json
{"versions": ["1.0.390", "1.0.385"], "installed": "1.0.385", "pinned": null}
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
