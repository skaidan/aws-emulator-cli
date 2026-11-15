# Referencia de comandos

> Generado automáticamente desde el código con `python scripts/gen_reference.py`.
> No lo edites a mano: cambia la ayuda del comando y vuelve a generarlo.

Opciones globales (van antes del comando): `--port/-p PUERTO` (por defecto 9297 o
`$AWSEMU_PORT`), `--plain` (texto plano), `--version/-V`, `--help/-h`.


- [`aws`](#awsemu-aws) — Run the AWS CLI against the emulator: 'awsemu aws s3 ls'.
- [`compose`](#awsemu-compose) — Print a Docker Compose service for the emulator (same setup as 'start --docker').
- [`config`](#awsemu-config) — Read or change the emulator's settings file (config.toml).
- [`describe`](#awsemu-describe) — Show any supported resource from its ARN.
- [`doctor`](#awsemu-doctor) — Check your setup and explain how to fix what's missing.
- [`down`](#awsemu-down) — Stop this project's emulator (same as 'awsemu stop').
- [`dynamodb`](#awsemu-dynamodb) — Tables and items (JSON in, JSON out).
- [`env`](#awsemu-env) — Print shell commands that point the AWS CLI and SDKs at the emulator.
- [`events`](#awsemu-events) — EventBridge: buses, rules and events.
- [`exec`](#awsemu-exec) — Run COMMAND with the environment pointed at the emulator.
- [`image`](#awsemu-image) — Build the Docker image (AWS doesn't publish a prebuilt one).
- [`init`](#awsemu-init) — Create awsemu.toml in this folder.
- [`kinesis`](#awsemu-kinesis) — Kinesis Data Streams.
- [`lambda`](#awsemu-lambda) — Deploy, invoke and inspect Lambda functions.
- [`logs`](#awsemu-logs) — Show the emulator's log, prettified (also after it stopped).
- [`overview`](#awsemu-overview) — What's inside the emulator, across common services.
- [`restart`](#awsemu-restart) — Restart the emulator.
- [`s3`](#awsemu-s3) — Buckets and objects.
- [`secrets`](#awsemu-secrets) — Secrets Manager: store and read secrets.
- [`seed`](#awsemu-seed) — Seed files: the same starting data after every start or reset.
- [`sfn`](#awsemu-sfn) — Step Functions: state machines and executions.
- [`shell`](#awsemu-shell) — Open a sub-shell already pointed at the emulator ('exit' to leave).
- [`sns`](#awsemu-sns) — Topics, publishing and subscriptions.
- [`sqs`](#awsemu-sqs) — Queues and messages.
- [`ssm`](#awsemu-ssm) — SSM Parameter Store: configuration parameters.
- [`start`](#awsemu-start) — Start an emulator in the background and wait until it's healthy.
- [`status`](#awsemu-status) — Show whether the emulator is running and healthy.
- [`stop`](#awsemu-stop) — Stop the emulator (clean stop: it deletes its files and in-memory state).
- [`up`](#awsemu-up) — Make sure this project's emulator is running and seeded.
- [`whoami`](#awsemu-whoami) — Check that requests reach the emulator (STS GetCallerIdentity).

## `awsemu aws`

Run the AWS CLI against the emulator: 'awsemu aws s3 ls'.

```
awsemu aws [OPTIONS] [ARGS]...
```

## `awsemu compose`

Print a Docker Compose service for the emulator (same setup as 'start --docker').

```bash
awsemu compose -o compose.emulator.yaml
docker compose -f compose.emulator.yaml up -d
```

```
awsemu compose [OPTIONS]
```

| Opción | Descripción |
| --- | --- |
| `-o, --output FILE` | Write to this file (default: stdout). |
| `--name TEXT` | Service name.  [default: aws-emulator] |
| `--no-build` | Omit the build section (image built with 'awsemu image build'). |
| `--auth / --no-auth` | [default: (auth)] |
| `--telemetry / --no-telemetry` |  |
| `--idle-timeout SECONDS` | [1<=x<=31536000] |

## `awsemu config`

Read or change the emulator's settings file (config.toml).

### `awsemu config path`

Print the settings file path.

```
awsemu config path [OPTIONS]
```

### `awsemu config show`

Show the emulator's settings file and this project's awsemu.toml.

```
awsemu config show [OPTIONS]
```

### `awsemu config telemetry`

Show or set telemetry ('awsemu config telemetry off').

```
awsemu config telemetry [OPTIONS] [on|off]
```

## `awsemu describe`

Show any supported resource from its ARN.

Works with S3, SQS, DynamoDB, SNS, Lambda, Secrets Manager, SSM, Kinesis,
EventBridge, Step Functions, CloudWatch Logs and IAM ARNs.

```
awsemu describe [OPTIONS] ARN
```

## `awsemu doctor`

Check your setup and explain how to fix what's missing.

```
awsemu doctor [OPTIONS]
```

## `awsemu down`

Stop this project's emulator (same as 'awsemu stop').

```
awsemu down [OPTIONS]
```

| Opción | Descripción |
| --- | --- |
| `--all` | Stop every instance awsemu knows about. |

## `awsemu dynamodb`

Tables and items (JSON in, JSON out). Alias: 'awsemu ddb'.

### `awsemu dynamodb create`

Create an on-demand table: 'awsemu ddb create users --pk id --sk created:N'.

```
awsemu dynamodb create [OPTIONS] TABLE
```

| Opción | Descripción |
| --- | --- |
| `--pk NAME[:S|N|B]` | Partition key (default type S).  [required] |
| `--sk NAME[:S|N|B]` | Sort key. |

### `awsemu dynamodb delete`

Delete one item by key.

```
awsemu dynamodb delete [OPTIONS] TABLE KEY_JSON
```

### `awsemu dynamodb describe`

Show a table's full description.

```
awsemu dynamodb describe [OPTIONS] TABLE
```

### `awsemu dynamodb drop`

Delete a table.

```
awsemu dynamodb drop [OPTIONS] TABLE
```

| Opción | Descripción |
| --- | --- |
| `-y, --yes` |  |

### `awsemu dynamodb get`

Get one item: 'awsemu ddb get users '{"id": "u1"}''.

```
awsemu dynamodb get [OPTIONS] TABLE KEY_JSON
```

### `awsemu dynamodb ls`

List tables with keys and item counts.

```
awsemu dynamodb ls [OPTIONS]
```

### `awsemu dynamodb put`

Write item(s): 'awsemu ddb put users '{"id": "u1", "age": 30}''.

```
awsemu dynamodb put [OPTIONS] TABLE [ITEM_JSON]
```

| Opción | Descripción |
| --- | --- |
| `--file FILENAME` | JSON object, or a JSON array of objects ('-' = stdin). |

### `awsemu dynamodb scan`

Show items in a table.

```
awsemu dynamodb scan [OPTIONS] TABLE
```

| Opción | Descripción |
| --- | --- |
| `-n, --limit INTEGER` | Max items (0 = all).  [default: 50] |
| `--json` | Print items as JSON. |

## `awsemu env`

Print shell commands that point the AWS CLI and SDKs at the emulator.

```bash
eval "$(awsemu env)"                      # bash / zsh
awsemu env --shell fish | source          # fish
awsemu env --shell powershell | iex       # PowerShell
awsemu env --shell dotenv > .env.emulator # for docker compose / IDEs
eval "$(awsemu env --unset)"              # back to real AWS
```

```
awsemu env [OPTIONS]
```

| Opción | Descripción |
| --- | --- |
| `--shell [bash|zsh|fish|powershell|dotenv|sh|pwsh]` | Syntax to print (default: detected from $SHELL). |
| `--sdk [node|java|rust|dotnet]` | Also trust the certificate for SDKs that ignore AWS_CA_BUNDLE. Repeatable. |
| `--unset` | Print the commands that undo 'awsemu env'. |
| `--keep-real-creds` | Don't unset AWS_ACCESS_KEY_ID & co. (requests will then fail auth). |

## `awsemu events`

EventBridge: buses, rules and events.

### `awsemu events buses`

List event buses.

```
awsemu events buses [OPTIONS]
```

### `awsemu events create-bus`

Create a custom event bus.

```
awsemu events create-bus [OPTIONS] NAME
```

### `awsemu events put`

Send an event: 'awsemu events put app.orders OrderCreated '{"id": 42}''.

```
awsemu events put [OPTIONS] SOURCE DETAIL_TYPE [DETAIL]
```

| Opción | Descripción |
| --- | --- |
| `--bus TEXT` | Event bus name.  [default: default] |

### `awsemu events rm`

Delete a rule (its targets are removed first).

```
awsemu events rm [OPTIONS] NAME
```

| Opción | Descripción |
| --- | --- |
| `--bus TEXT` | Event bus name.  [default: default] |
| `-y, --yes` |  |

### `awsemu events rule`

Create or update a rule and (optionally) its target in one step.

```bash
awsemu events rule orders-created --source app.orders --to-sqs order-events
awsemu events rule big-orders --pattern '{"detail": {"total": [{"numeric": [">", 100]}]}}' --to-lambda alert
```

```
awsemu events rule [OPTIONS] NAME
```

| Opción | Descripción |
| --- | --- |
| `--pattern JSON` | Event pattern, e.g. '{"source": ["app.orders"]}'. |
| `--source TEXT` | Shortcut for a pattern matching these sources. Repeatable. |
| `--schedule EXPR` | e.g. 'rate(5 minutes)' (instead of a pattern). |
| `--to-sqs QUEUE` | Send matches to this queue (sets its policy). |
| `--to-lambda FUNCTION` | Invoke this function (adds permission). |
| `--to-sns TOPIC` | Publish to this SNS topic. |
| `--bus TEXT` | Event bus name.  [default: default] |

### `awsemu events rules`

List rules on a bus with their pattern and targets.

```
awsemu events rules [OPTIONS]
```

| Opción | Descripción |
| --- | --- |
| `--bus TEXT` | Event bus name.  [default: default] |
| `--json` |  |

## `awsemu exec`

Run COMMAND with the environment pointed at the emulator.

```bash
awsemu exec -- pytest -k integration
awsemu exec -- terraform apply
awsemu exec --sdk node -- npm test
```

```
awsemu exec [OPTIONS] COMMAND...
```

| Opción | Descripción |
| --- | --- |
| `--sdk [node|java|rust|dotnet]` |  |

## `awsemu image`

Build the Docker image (AWS doesn't publish a prebuilt one).

### `awsemu image build`

Build the image from the official Dockerfile recipe.

```
awsemu image build [OPTIONS]
```

| Opción | Descripción |
| --- | --- |
| `--tag TEXT` | [default: aws-emulator] |
| `--arch [x86_64|aarch64]` | Package architecture (default: this machine's). |

### `awsemu image dockerfile`

Print the Dockerfile awsemu builds from.

```
awsemu image dockerfile [OPTIONS]
```

| Opción | Descripción |
| --- | --- |
| `--arch [x86_64|aarch64]` |  |

## `awsemu init`

Create awsemu.toml in this folder.

Without '--port', picks a port from the folder name (9300-9399), so
several projects can run their emulators side by side.

```
awsemu init [OPTIONS]
```

| Opción | Descripción |
| --- | --- |
| `--seed PATH` | Seed file to reference (default: auto-detect). |
| `--force` | Overwrite an existing awsemu.toml. |

## `awsemu kinesis`

Kinesis Data Streams.

### `awsemu kinesis create`

Create a stream and wait until it's active.

```
awsemu kinesis create [OPTIONS] NAME
```

| Opción | Descripción |
| --- | --- |
| `--shards INTEGER RANGE` | [default: 1; 1<=x<=64] |

### `awsemu kinesis ls`

List streams with status and shard count.

```
awsemu kinesis ls [OPTIONS]
```

### `awsemu kinesis put`

Put one record: 'awsemu kinesis put clicks '{"page": "/"}''.

```
awsemu kinesis put [OPTIONS] STREAM [DATA]
```

| Opción | Descripción |
| --- | --- |
| `--file FILENAME` | Record data from a file ('-' = stdin). |
| `-k, --key TEXT` | Partition key (default: random). |

### `awsemu kinesis read`

Read records from every shard.

```
awsemu kinesis read [OPTIONS] STREAM
```

| Opción | Descripción |
| --- | --- |
| `--from [start|latest]` | Read from the oldest record or only new ones.  [default: start] |
| `-n, --limit INTEGER` | Max records (0 = no limit).  [default: 100] |
| `-f, --follow` | Keep polling for new records. |
| `--json` | One JSON object per record. |

### `awsemu kinesis rm`

Delete a stream.

```
awsemu kinesis rm [OPTIONS] STREAM
```

| Opción | Descripción |
| --- | --- |
| `-y, --yes` |  |

## `awsemu lambda`

Deploy, invoke and inspect Lambda functions.

### `awsemu lambda deploy`

Create or update a function from a folder, a single file or a .zip.

```bash
awsemu lambda deploy hello ./hello.py
awsemu lambda deploy api ./src --handler app.handler -e STAGE=local
```

```
awsemu lambda deploy [OPTIONS] NAME SOURCE
```

| Opción | Descripción |
| --- | --- |
| `--handler TEXT` | e.g. app.handler (guessed from the code if omitted). |
| `--runtime TEXT` | e.g. python3.12, nodejs20.x (guessed if omitted). |
| `--role ARN` | Execution role (default: creates 'awsemu-lambda-role'). |
| `-e, --env KEY=VALUE` | Environment variable. Repeatable. |
| `--timeout INTEGER RANGE` | Seconds.  [1<=x<=900] |
| `--memory INTEGER RANGE` | MB.  [128<=x<=10240] |

### `awsemu lambda info`

Show a function's configuration.

```
awsemu lambda info [OPTIONS] NAME
```

### `awsemu lambda invoke`

Invoke a function with a JSON payload: 'awsemu lambda invoke hello '{"name": "Ana"}''.

```
awsemu lambda invoke [OPTIONS] NAME [PAYLOAD]
```

| Opción | Descripción |
| --- | --- |
| `--file FILENAME` | Payload from a file ('-' = stdin). |
| `--async` | Event invocation (don't wait for the result). |
| `--logs / --no-logs` | Show the log tail returned by Lambda.  [default: logs] |
| `--raw` | Print only the response payload. |

### `awsemu lambda logs`

Show the function's CloudWatch logs (/aws/lambda/NAME).

Note: AWS Emulator doesn't write Lambda output to CloudWatch Logs; use
'awsemu lambda invoke', which prints the log of that invocation.

```
awsemu lambda logs [OPTIONS] NAME
```

| Opción | Descripción |
| --- | --- |
| `-f, --follow` |  |
| `--since MINUTES` | [default: 60] |

### `awsemu lambda ls`

List functions.

```
awsemu lambda ls [OPTIONS]
```

### `awsemu lambda rm`

Delete a function.

```
awsemu lambda rm [OPTIONS] NAME
```

| Opción | Descripción |
| --- | --- |
| `-y, --yes` |  |

## `awsemu logs`

Show the emulator's log, prettified (also after it stopped).

```
awsemu logs [OPTIONS]
```

| Opción | Descripción |
| --- | --- |
| `-f, --follow` | Keep printing new lines. |
| `-n, --lines INTEGER` | Lines to show first.  [default: 50] |
| `--raw` | Print the JSON lines untouched. |
| `--grep TEXT` | Only lines containing TEXT (case-insensitive). |

## `awsemu overview`

What's inside the emulator, across common services. Alias: 'awsemu ls'.

```
awsemu overview [OPTIONS]
```

| Opción | Descripción |
| --- | --- |
| `-s, --service [s3|sqs|dynamodb|sns|lambda|secretsmanager|ssm|kinesis|events|stepfunctions|logs|iam]` | Only these services. Repeatable. |
| `--all` | Also list services with nothing in them. |
| `--json` |  |

## `awsemu restart`

Restart the emulator. The emulator keeps state in memory, so this also resets it.

Alias: 'awsemu reset'. With --seed, the seed is applied to the fresh emulator.

```
awsemu restart [OPTIONS] [EXTRA]...
```

| Opción | Descripción |
| --- | --- |
| `--docker` | Run in Docker even if the binary is installed. |
| `--native` | Run the installed 'aws-emulator' binary. |
| `--auth / --no-auth` | Require SigV4-signed requests (emulator '-a').  [default: (auth)] |
| `--telemetry / --no-telemetry` | Force telemetry on/off for this run (default: emulator settings). |
| `--idle-timeout SECONDS` | Stop automatically after this many seconds without API calls.  [1<=x<=31536000] |
| `--image TEXT` | Docker image to run.  [default: (aws-emulator)] |
| `--memory TEXT` | Docker memory limit.  [default: (2g)] |
| `--wait SECONDS` | How long to wait for the health check.  [default: 30] |
| `-f, --foreground` | Run attached to this terminal instead of in the background. |
| `--seed FILE` | Apply this seed file once the emulator is healthy. |

## `awsemu s3`

Buckets and objects.

### `awsemu s3 cat`

Print an object to stdout.

```
awsemu s3 cat [OPTIONS] SOURCE
```

### `awsemu s3 get`

Download BUCKET/KEY to DEST (default: file name in the current folder).

```
awsemu s3 get [OPTIONS] SOURCE [DEST]
```

### `awsemu s3 ls`

List buckets, or objects in BUCKET[/PREFIX].

```
awsemu s3 ls [OPTIONS] [TARGET]
```

| Opción | Descripción |
| --- | --- |
| `-r, --recursive` | List every key, not just one level. |
| `--json` |  |

### `awsemu s3 mb`

Create one or more buckets.

```
awsemu s3 mb [OPTIONS] BUCKETS...
```

### `awsemu s3 presign`

Print a presigned URL for BUCKET/KEY.

```
awsemu s3 presign [OPTIONS] TARGET
```

| Opción | Descripción |
| --- | --- |
| `--expires SECONDS` | [default: 3600] |
| `--put` | URL for uploading instead of downloading. |

### `awsemu s3 put`

Upload a file (or a folder, recursively) to BUCKET[/KEY].

If KEY is empty or ends with '/', the file name is appended.

```
awsemu s3 put [OPTIONS] SOURCE TARGET
```

| Opción | Descripción |
| --- | --- |
| `--content-type TEXT` | Content-Type for the object(s). |

### `awsemu s3 rb`

Delete a bucket.

```
awsemu s3 rb [OPTIONS] BUCKET
```

| Opción | Descripción |
| --- | --- |
| `--force` | Delete all objects first. |
| `-y, --yes` | Don't ask for confirmation. |

### `awsemu s3 rm`

Delete an object (or a whole prefix with -r).

```
awsemu s3 rm [OPTIONS] TARGET
```

| Opción | Descripción |
| --- | --- |
| `-r, --recursive` | Delete every key under the prefix. |
| `-y, --yes` |  |

## `awsemu secrets`

Secrets Manager: store and read secrets.

### `awsemu secrets get`

Print a secret's value (JSON values are pretty-printed).

```
awsemu secrets get [OPTIONS] NAME
```

| Opción | Descripción |
| --- | --- |
| `--stage TEXT` | Version stage.  [default: AWSCURRENT] |
| `--raw` | Print the value untouched (no JSON formatting). |

### `awsemu secrets info`

Show a secret's metadata and versions (not its value).

```
awsemu secrets info [OPTIONS] NAME
```

### `awsemu secrets ls`

List secrets (names only, never values).

```
awsemu secrets ls [OPTIONS]
```

| Opción | Descripción |
| --- | --- |
| `--json` |  |

### `awsemu secrets put`

Create a secret, or store a new version if it exists.

```bash
awsemu secrets put db/password 's3cr3t'
awsemu secrets put db/config '{"host": "localhost", "port": 5432}'
awsemu secrets put tls/key --file key.pem
```

```
awsemu secrets put [OPTIONS] NAME [VALUE]
```

| Opción | Descripción |
| --- | --- |
| `--file FILENAME` | Read the value from a file ('-' = stdin). |
| `--description TEXT` |  |

### `awsemu secrets rm`

Delete a secret (with a 7-day recovery window unless --now).

```
awsemu secrets rm [OPTIONS] NAME
```

| Opción | Descripción |
| --- | --- |
| `--now` | Delete immediately, without a recovery window. |
| `-y, --yes` |  |

## `awsemu seed`

Seed files: the same starting data after every start or reset.

### `awsemu seed apply`

Create what FILE describes. Safe to run again: existing things are updated or left alone.

```bash
awsemu seed apply seed.yaml
awsemu start --seed seed.yaml     # start and apply in one step
awsemu reset --seed seed.yaml     # empty state + seed
```

```
awsemu seed apply [OPTIONS] FILE
```

### `awsemu seed export`

Write what's in the emulator now as a seed file.

Secret values and SecureString parameters are exported in plain text
unless --no-secrets.

```
awsemu seed export [OPTIONS]
```

| Opción | Descripción |
| --- | --- |
| `-o, --output FILE` | Write to this file (default: stdout). |
| `--objects-dir DIRECTORY` | Save binary or large S3 objects here and reference them with 'from'. |
| `--no-secrets` | Leave out secrets and SecureString parameters. |
| `-s, --section [buckets|queues|tables|topics|secrets|parameters]` | Only these sections. Repeatable. |

### `awsemu seed validate`

Check FILE without touching the emulator (errors show line and field).

```
awsemu seed validate [OPTIONS] FILE
```

## `awsemu sfn`

Step Functions: state machines and executions.

### `awsemu sfn deploy`

Create or update a state machine from a file or inline JSON.

```bash
awsemu sfn deploy hello flow.asl.json
awsemu sfn deploy hello '{"StartAt": "Hi", "States": {"Hi": {"Type": "Pass", "End": true}}}'
```

```
awsemu sfn deploy [OPTIONS] NAME DEFINITION
```

| Opción | Descripción |
| --- | --- |
| `--express` | EXPRESS type (default STANDARD). |
| `--role ARN` | Execution role (default: creates 'awsemu-sfn-role'). |

### `awsemu sfn executions`

Recent executions of a state machine.

```
awsemu sfn executions [OPTIONS] NAME
```

| Opción | Descripción |
| --- | --- |
| `-n, --limit INTEGER` | [default: 20] |

### `awsemu sfn ls`

List state machines.

```
awsemu sfn ls [OPTIONS]
```

### `awsemu sfn rm`

Delete a state machine.

```
awsemu sfn rm [OPTIONS] NAME
```

| Opción | Descripción |
| --- | --- |
| `-y, --yes` |  |

### `awsemu sfn start`

Start an execution and (by default) wait for its result.

```
awsemu sfn start [OPTIONS] NAME [INPUT_JSON]
```

| Opción | Descripción |
| --- | --- |
| `--file FILENAME` | Input from a file ('-' = stdin). |
| `--no-wait` | Start and return without waiting for the result. |
| `--timeout SECONDS` | [default: 120] |
| `--raw` | Print only the output JSON. |

## `awsemu shell`

Open a sub-shell already pointed at the emulator ('exit' to leave).

```
awsemu shell [OPTIONS]
```

| Opción | Descripción |
| --- | --- |
| `--sdk [node|java|rust|dotnet]` |  |

## `awsemu sns`

Topics, publishing and subscriptions.

### `awsemu sns create`

Create a topic.

```
awsemu sns create [OPTIONS] NAME
```

| Opción | Descripción |
| --- | --- |
| `--fifo` | FIFO topic ('.fifo' is added if missing). |

### `awsemu sns ls`

List topics with their subscriptions.

```
awsemu sns ls [OPTIONS]
```

| Opción | Descripción |
| --- | --- |
| `--json` |  |

### `awsemu sns publish`

Publish a message to a topic.

```
awsemu sns publish [OPTIONS] TOPIC [MESSAGE]
```

| Opción | Descripción |
| --- | --- |
| `--file FILENAME` | Read the message from a file ('-' = stdin). |
| `--subject TEXT` |  |
| `-a, --attr KEY=VALUE` | String message attribute. Repeatable. |
| `--group TEXT` | MessageGroupId (FIFO). |
| `--dedup-id TEXT` | MessageDeduplicationId (FIFO). |

### `awsemu sns rm`

Delete a topic (and its subscriptions).

```
awsemu sns rm [OPTIONS] TOPIC
```

| Opción | Descripción |
| --- | --- |
| `-y, --yes` |  |

### `awsemu sns subs`

List subscriptions (of one topic, or all).

```
awsemu sns subs [OPTIONS] [TOPIC]
```

### `awsemu sns subscribe`

Subscribe a target to a topic.

```bash
awsemu sns subscribe orders --to-sqs order-events --raw
awsemu sns subscribe orders --to-lambda handle-order
```

```
awsemu sns subscribe [OPTIONS] TOPIC
```

| Opción | Descripción |
| --- | --- |
| `--to-sqs QUEUE` | Deliver to this SQS queue (name or URL). Sets the queue policy for you. |
| `--to-lambda FUNCTION` | Invoke this Lambda function. |
| `--endpoint PROTOCOL:ENDPOINT` | Any other target, e.g. 'https:https://example.test/hook'. |
| `--raw` | Raw message delivery (no SNS JSON envelope). |
| `--filter JSON` | Subscription filter policy. |

### `awsemu sns unsubscribe`

Remove a subscription by ARN.

```
awsemu sns unsubscribe [OPTIONS] SUBSCRIPTION_ARN
```

## `awsemu sqs`

Queues and messages.

### `awsemu sqs create`

Create a queue.

```
awsemu sqs create [OPTIONS] NAME
```

| Opción | Descripción |
| --- | --- |
| `--fifo` | FIFO queue ('.fifo' is added if missing). |
| `--dedup` | Content-based deduplication (FIFO only). |
| `--visibility-timeout SECONDS` |  |
| `--dlq QUEUE` | Dead-letter queue (name or URL). |
| `--max-receive INTEGER` | Receives before a message goes to the DLQ.  [default: 5] |

### `awsemu sqs info`

Show all attributes of a queue.

```
awsemu sqs info [OPTIONS] QUEUE
```

### `awsemu sqs ls`

List queues with their message counts.

```
awsemu sqs ls [OPTIONS]
```

| Opción | Descripción |
| --- | --- |
| `--prefix TEXT` | Only queues whose name starts with this. |
| `--json` |  |

### `awsemu sqs purge`

Delete every message in a queue.

```
awsemu sqs purge [OPTIONS] QUEUE
```

| Opción | Descripción |
| --- | --- |
| `-y, --yes` |  |

### `awsemu sqs receive`

Receive messages (they stay in the queue unless --delete).

```
awsemu sqs receive [OPTIONS] QUEUE
```

| Opción | Descripción |
| --- | --- |
| `-n, --max INTEGER RANGE` | [default: 10; 1<=x<=10] |
| `--wait SECONDS` | Long-poll time.  [default: 1; 0<=x<=20] |
| `--delete` | Delete messages after printing them. |
| `--json` |  |

### `awsemu sqs rm`

Delete a queue.

```
awsemu sqs rm [OPTIONS] QUEUE
```

| Opción | Descripción |
| --- | --- |
| `-y, --yes` |  |

### `awsemu sqs send`

Send a message. BODY can also come from --file or stdin.

```
awsemu sqs send [OPTIONS] QUEUE [BODY]
```

| Opción | Descripción |
| --- | --- |
| `--file FILENAME` | Read the body from a file ('-' = stdin). |
| `--group TEXT` | MessageGroupId (FIFO). |
| `--dedup-id TEXT` | MessageDeduplicationId (FIFO). |
| `--delay SECONDS` |  |
| `-a, --attr KEY=VALUE` | String message attribute. Repeatable. |

## `awsemu ssm`

SSM Parameter Store: configuration parameters.

### `awsemu ssm get`

Print a parameter's value.

```
awsemu ssm get [OPTIONS] NAME
```

| Opción | Descripción |
| --- | --- |
| `--no-decrypt` | Don't decrypt SecureString values. |

### `awsemu ssm ls`

List parameters, optionally under a PATH like /app/prod.

```
awsemu ssm ls [OPTIONS] [PATH]
```

| Opción | Descripción |
| --- | --- |
| `--values` | Also show values (SecureString shown as ****). |
| `--json` |  |

### `awsemu ssm put`

Create or overwrite a parameter: 'awsemu ssm put /app/db/host localhost'.

```
awsemu ssm put [OPTIONS] NAME [VALUE]
```

| Opción | Descripción |
| --- | --- |
| `--file FILENAME` | Read the value from a file ('-' = stdin). |
| `--secure` | Store as SecureString. |
| `--list` | Store as StringList (comma-separated). |
| `--description TEXT` |  |

### `awsemu ssm rm`

Delete one or more parameters.

```
awsemu ssm rm [OPTIONS] NAMES...
```

## `awsemu start`

Start an emulator in the background and wait until it's healthy.

Uses the 'aws-emulator' binary if it's on PATH (or $AWSEMU_BINARY),
otherwise Docker. '--port 0' lets the OS pick a free port (native only).
Anything after '--' is passed to the emulator as-is.

```
awsemu start [OPTIONS] [EXTRA]...
```

| Opción | Descripción |
| --- | --- |
| `--docker` | Run in Docker even if the binary is installed. |
| `--native` | Run the installed 'aws-emulator' binary. |
| `--auth / --no-auth` | Require SigV4-signed requests (emulator '-a').  [default: (auth)] |
| `--telemetry / --no-telemetry` | Force telemetry on/off for this run (default: emulator settings). |
| `--idle-timeout SECONDS` | Stop automatically after this many seconds without API calls.  [1<=x<=31536000] |
| `--image TEXT` | Docker image to run.  [default: (aws-emulator)] |
| `--memory TEXT` | Docker memory limit.  [default: (2g)] |
| `--wait SECONDS` | How long to wait for the health check.  [default: 30] |
| `-f, --foreground` | Run attached to this terminal instead of in the background. |
| `--seed FILE` | Apply this seed file once the emulator is healthy. |

## `awsemu status`

Show whether the emulator is running and healthy.

```
awsemu status [OPTIONS]
```

| Opción | Descripción |
| --- | --- |
| `--all` | Show every known port, not just the selected one. |
| `--json` | Machine-readable output. |

## `awsemu stop`

Stop the emulator (clean stop: it deletes its files and in-memory state).

```
awsemu stop [OPTIONS]
```

| Opción | Descripción |
| --- | --- |
| `--all` | Stop every instance awsemu knows about. |
| `--force` | SIGKILL / docker kill (loses the clean shutdown). |
| `--timeout SECONDS` | [default: 15] |

## `awsemu up`

Make sure this project's emulator is running and seeded.

Uses awsemu.toml (port, mode, auth, telemetry, idle_timeout, seed...).
Starts the emulator if it isn't running; either way, applies the seed,
which is safe to repeat.

```
awsemu up [OPTIONS]
```

| Opción | Descripción |
| --- | --- |
| `--seed FILE` | Seed to apply (default: 'seed' from awsemu.toml). |
| `--no-seed` | Don't apply any seed. |
| `--wait SECONDS` | [default: 30] |

## `awsemu whoami`

Check that requests reach the emulator (STS GetCallerIdentity).

```
awsemu whoami [OPTIONS]
```
