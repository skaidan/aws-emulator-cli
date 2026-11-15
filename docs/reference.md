# Referencia de comandos

> Generado automáticamente desde el código con `python scripts/gen_reference.py`.
> No lo edites a mano: cambia la ayuda del comando y vuelve a generarlo.

Opciones globales (van antes del comando): `--port/-p PUERTO` (por defecto 9297 o
`$AWSEMU_PORT`), `--plain` (texto plano), `--version/-V`, `--help/-h`.


- [`aws`](#awsemu-aws) — Run the AWS CLI against the emulator: 'awsemu aws s3 ls'.
- [`config`](#awsemu-config) — Read or change the emulator's settings file (config.toml).
- [`doctor`](#awsemu-doctor) — Check your setup and explain how to fix what's missing.
- [`dynamodb`](#awsemu-dynamodb) — Tables and items (JSON in, JSON out).
- [`env`](#awsemu-env) — Print shell commands that point the AWS CLI and SDKs at the emulator.
- [`exec`](#awsemu-exec) — Run COMMAND with the environment pointed at the emulator.
- [`image`](#awsemu-image) — Build the Docker image (AWS doesn't publish a prebuilt one).
- [`lambda`](#awsemu-lambda) — Deploy, invoke and inspect Lambda functions.
- [`logs`](#awsemu-logs) — Show the emulator's log, prettified (also after it stopped).
- [`overview`](#awsemu-overview) — What's inside the emulator, across common services.
- [`restart`](#awsemu-restart) — Restart the emulator.
- [`s3`](#awsemu-s3) — Buckets and objects.
- [`shell`](#awsemu-shell) — Open a sub-shell already pointed at the emulator ('exit' to leave).
- [`sns`](#awsemu-sns) — Topics, publishing and subscriptions.
- [`sqs`](#awsemu-sqs) — Queues and messages.
- [`start`](#awsemu-start) — Start an emulator in the background and wait until it's healthy.
- [`status`](#awsemu-status) — Show whether the emulator is running and healthy.
- [`stop`](#awsemu-stop) — Stop the emulator (clean stop: it deletes its files and in-memory state).
- [`whoami`](#awsemu-whoami) — Check that requests reach the emulator (STS GetCallerIdentity).

## `awsemu aws`

Run the AWS CLI against the emulator: 'awsemu aws s3 ls'.

```
awsemu aws [OPTIONS] [ARGS]...
```

## `awsemu config`

Read or change the emulator's settings file (config.toml).

### `awsemu config path`

Print the settings file path.

```
awsemu config path [OPTIONS]
```

### `awsemu config show`

Show the settings file and effective telemetry setting.

```
awsemu config show [OPTIONS]
```

### `awsemu config telemetry`

Show or set telemetry ('awsemu config telemetry off').

```
awsemu config telemetry [OPTIONS] [on|off]
```

## `awsemu doctor`

Check your setup and explain how to fix what's missing.

```
awsemu doctor [OPTIONS]
```

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

Alias: 'awsemu reset'.

```
awsemu restart [OPTIONS] [EXTRA]...
```

| Opción | Descripción |
| --- | --- |
| `--docker` | Run in Docker even if the binary is installed. |
| `--native` | Run the installed 'aws-emulator' binary. |
| `--auth / --no-auth` | Require SigV4-signed requests (emulator '-a').  [default: auth] |
| `--telemetry / --no-telemetry` | Force telemetry on/off for this run (default: emulator settings). |
| `--idle-timeout SECONDS` | Stop automatically after this many seconds without API calls.  [1<=x<=31536000] |
| `--image TEXT` | Docker image to run.  [default: aws-emulator] |
| `--memory TEXT` | Docker memory limit.  [default: 2g] |
| `--wait SECONDS` | How long to wait for the health check.  [default: 30] |
| `-f, --foreground` | Run attached to this terminal instead of in the background. |

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
| `--auth / --no-auth` | Require SigV4-signed requests (emulator '-a').  [default: auth] |
| `--telemetry / --no-telemetry` | Force telemetry on/off for this run (default: emulator settings). |
| `--idle-timeout SECONDS` | Stop automatically after this many seconds without API calls.  [1<=x<=31536000] |
| `--image TEXT` | Docker image to run.  [default: aws-emulator] |
| `--memory TEXT` | Docker memory limit.  [default: 2g] |
| `--wait SECONDS` | How long to wait for the health check.  [default: 30] |
| `-f, --foreground` | Run attached to this terminal instead of in the background. |

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

## `awsemu whoami`

Check that requests reach the emulator (STS GetCallerIdentity).

```
awsemu whoami [OPTIONS]
```
