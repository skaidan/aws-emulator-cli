# Command reference

> Generated from the code with `python scripts/gen_reference.py`.
> Don't edit it by hand: change the command's help text and regenerate it.

Global options (before the command): `--port/-p PORT` (default: `$AWSEMU_PORT`, else
`awsemu.toml`, else 9297), `--plain` (plain text), `--version/-V`, `--help/-h`.


- [`aws`](#awsemu-aws) — Run the AWS CLI against the emulator: 'awsemu aws s3 ls'.
- [`call`](#awsemu-call) — Call any operation of any service, and print the response as JSON.
- [`check`](#awsemu-check) — Find the AWS operations your project uses and the known emulator differences for them.
- [`completion`](#awsemu-completion) — Print the shell completion script (commands, options and resource names).
- [`compose`](#awsemu-compose) — Print a Docker Compose service for the emulator (same setup as 'start --docker').
- [`config`](#awsemu-config) — Read or change the emulator's settings file (config.toml).
- [`describe`](#awsemu-describe) — Show any supported resource from its ARN.
- [`doctor`](#awsemu-doctor) — Check your setup and explain how to fix what's missing.
- [`down`](#awsemu-down) — Stop this project's emulator (same as 'awsemu stop').
- [`dynamodb`](#awsemu-dynamodb) — DynamoDB: tables and items, with plain JSON in and out.
- [`env`](#awsemu-env) — Print shell commands that point the AWS CLI and SDKs at the emulator.
- [`events`](#awsemu-events) — EventBridge: buses, rules and events.
- [`exec`](#awsemu-exec) — Run COMMAND with the environment pointed at the emulator.
- [`explain`](#awsemu-explain) — Say whether a failed call is a known emulator difference or likely your code.
- [`fidelity`](#awsemu-fidelity) — How closely the emulator matches AWS: published scores, or the tests run here.
- [`iam`](#awsemu-iam) — IAM permissions your code needs, from the calls it made (the proxy's log).
- [`image`](#awsemu-image) — Build the Docker image (AWS doesn't publish a prebuilt one).
- [`init`](#awsemu-init) — Create awsemu.toml in this folder.
- [`install`](#awsemu-install) — Install a given emulator version: the Linux package, or a Docker image.
- [`issues`](#awsemu-issues) — The emulator's known gaps, from AWS's own issue files.
- [`kinesis`](#awsemu-kinesis) — Kinesis: data streams and records.
- [`lambda`](#awsemu-lambda) — Lambda: deploy, invoke and inspect functions.
- [`logs`](#awsemu-logs) — Show the emulator's log, prettified (also after it stopped).
- [`mcp`](#awsemu-mcp) — An MCP server, so coding agents test against the emulator, never AWS.
- [`overview`](#awsemu-overview) — What's inside the emulator, across common services.
- [`proxy`](#awsemu-proxy) — See every API call, and inject faults (throttling, errors, latency).
- [`report`](#awsemu-report) — Draft an issue for the emulator from a call the proxy logged.
- [`restart`](#awsemu-restart) — Restart the emulator, which empties its state (it's all in memory).
- [`s3`](#awsemu-s3) — S3: buckets and objects.
- [`secrets`](#awsemu-secrets) — Secrets Manager: store and read secrets.
- [`seed`](#awsemu-seed) — Seed files: the same starting data after every start or reset.
- [`sfn`](#awsemu-sfn) — Step Functions: state machines and executions.
- [`shell`](#awsemu-shell) — Open a sub-shell already pointed at the emulator ('exit' to leave).
- [`snapshot`](#awsemu-snapshot) — Save and restore a whole scenario (the emulator has no snapshots of its own).
- [`sns`](#awsemu-sns) — SNS: topics, publishing and subscriptions.
- [`sqs`](#awsemu-sqs) — SQS: queues and messages.
- [`ssm`](#awsemu-ssm) — SSM Parameter Store: configuration parameters.
- [`start`](#awsemu-start) — Start an emulator in the background and wait until it's healthy.
- [`status`](#awsemu-status) — Show whether the emulator is running and healthy.
- [`stop`](#awsemu-stop) — Stop the emulator (clean stop: it deletes its files and in-memory state).
- [`ui`](#awsemu-ui) — Browse the emulator in the terminal: services, resources and their details.
- [`up`](#awsemu-up) — Make sure this project's emulator is running and seeded.
- [`watch`](#awsemu-watch) — Show resources being created, deleted or changed, live (Ctrl+C to stop).
- [`whoami`](#awsemu-whoami) — Check that requests reach the emulator (STS GetCallerIdentity).

## `awsemu aws`

Run the AWS CLI against the emulator: 'awsemu aws s3 ls'.

Goes through the proxy when awsemu.toml has proxy = true and it's running.

```
awsemu aws [OPTIONS] [ARGS]...
```

## `awsemu call`

Call any operation of any service, and print the response as JSON.

```bash
awsemu call s3 list-buckets
awsemu call sqs SendMessage -p QueueUrl=https://… -p MessageBody=hi
awsemu call dynamodb query --params @query.json --query 'Items[].id.S'
awsemu call logs describe-log-groups --paginate
awsemu call ssm                       # the operations of a service
awsemu call                           # the services
```
An error from the service exits with 1 and prints its code and message.

```
awsemu call [OPTIONS] [SERVICE] [OPERATION]
```

| Option | Description |
| --- | --- |
| `--params JSON` | The request as JSON, '@file.json', or '-' for stdin. |
| `-p, --param KEY=VALUE` | One parameter (JSON values parsed, '@file' for bytes). Repeatable. |
| `--paginate` | Follow every page and merge them. |
| `--query JMESPATH` | Keep part of the response, like the AWS CLI's --query. |
| `--out FILE` | Write a streaming body (S3 GetObject…) to this file. |
| `--metadata` | Keep ResponseMetadata in the output. |

## `awsemu check`

Find the AWS operations your project uses and the known emulator differences for them.

```bash
awsemu check                    # this folder
awsemu check src infra          # just these
awsemu check --release latest   # would upgrading help?
awsemu check --strict           # exit 1 on known differences (CI)
awsemu check --from-calls       # what your tests really called, via the proxy
awsemu check --iam              # permissions your infrastructure doesn't grant
```
Reads code that uses boto3, the AWS SDKs for JavaScript, Java and Go, and
Terraform, CloudFormation/SAM and CDK files; nothing is run. Then it looks
the operations up in the fidelity tests of the release
(https://github.com/aws/aws-emulator-evaluation-suite): a test is listed when
it fails at an operation you call, or calls only operations you call.

With --from-calls it reads the proxy's calls log instead: only operations
your code really called (run your tests through 'awsemu exec --proxy' first).

```
awsemu check [OPTIONS] [PATHS]...
```

| Option | Description |
| --- | --- |
| `--release VERSION` | Emulator release to check against: 1.0.385 or latest (default: emulator_version in awsemu.toml, else your installed one). |
| `--manifest FILE|REF` | manifest.jsonl to use: a local file, or a tag/branch of the fidelity tests repository (default: the version the release names, else the newest one). |
| `--all` | List every known difference, not the first 3 per operation. |
| `--strict` | Exit with code 1 when an operation you use has known differences (for CI). |
| `--refresh` | Download scores and manifest again instead of using the cache. |
| `--no-explain` | Don't look up what explains each difference: the emulator's issue files and whether the latest release fixes it (no extra downloads). |
| `--from-calls` | Check the operations the proxy saw your code call (its calls log), instead of reading the code. |
| `--calls-file FILE` | A calls log to read with --from-calls (default: the proxy's, for --port). |
| `--iam` | Instead: the IAM actions your code needs that your Terraform/CloudFormation/CDK policies don't grant. |
| `--json` | Machine-readable JSON output (format: docs/scripting.md). |

## `awsemu completion`

Print the shell completion script (commands, options and resource names).

```bash
bash:  echo 'eval "$(awsemu completion bash)"' >> ~/.bashrc
zsh:   echo 'eval "$(awsemu completion zsh)"' >> ~/.zshrc
fish:  awsemu completion fish > ~/.config/fish/completions/awsemu.fish
```
Bucket, queue, table, topic, function, secret, parameter, stream, state
machine and rule names are completed from the running emulator.

```
awsemu completion [OPTIONS] [bash|zsh|fish]
```

## `awsemu compose`

Print a Docker Compose service for the emulator (same setup as 'start --docker').

```bash
awsemu compose -o compose.emulator.yaml
docker compose -f compose.emulator.yaml up -d
awsemu compose --proxy -o compose.emulator.yaml   # app containers via the proxy
```

```
awsemu compose [OPTIONS]
```

| Option | Description |
| --- | --- |
| `-o, --output FILE` | Write to this file (default: stdout). |
| `--name TEXT` | Service name.  [default: aws-emulator] |
| `--no-build` | Omit the build section (image built with 'awsemu image build'). |
| `--auth / --no-auth` | Require SigV4-signed requests (default: awsemu.toml, else auth).  [default: (auth)] |
| `--telemetry / --no-telemetry` | Force telemetry on/off (default: awsemu.toml, else emulator settings). |
| `--idle-timeout SECONDS` | Stop after this many seconds without API calls.  [1<=x<=31536000] |
| `--proxy` | Also write settings (x-aws-emulator-client) that send app containers through the awsemu proxy. |

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

Exits with 1 if something required is missing (warnings don't count).

```
awsemu doctor [OPTIONS]
```

| Option | Description |
| --- | --- |
| `--json` | Machine-readable JSON output (format: docs/scripting.md). |

## `awsemu down`

Stop this project's emulator (same as 'awsemu stop').

```
awsemu down [OPTIONS]
```

| Option | Description |
| --- | --- |
| `--all` | Stop every instance awsemu knows about. |

## `awsemu dynamodb`

DynamoDB: tables and items, with plain JSON in and out. Alias: 'awsemu ddb'.

### `awsemu dynamodb create`

Create an on-demand table: 'awsemu ddb create users --pk id --sk created:N'.

```
awsemu dynamodb create [OPTIONS] TABLE
```

| Option | Description |
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

| Option | Description |
| --- | --- |
| `-y, --yes` | Don't ask for confirmation (for scripts). |

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

| Option | Description |
| --- | --- |
| `--json` | Machine-readable JSON output (format: docs/scripting.md). |

### `awsemu dynamodb put`

Write item(s): 'awsemu ddb put users '{"id": "u1", "age": 30}''.

```
awsemu dynamodb put [OPTIONS] TABLE [ITEM_JSON]
```

| Option | Description |
| --- | --- |
| `--file FILENAME` | JSON object, or a JSON array of objects ('-' = stdin). |

### `awsemu dynamodb scan`

Show items in a table.

```
awsemu dynamodb scan [OPTIONS] TABLE
```

| Option | Description |
| --- | --- |
| `-n, --limit INTEGER` | Max items (0 = all).  [default: 50] |
| `--json` | Machine-readable JSON output (format: docs/scripting.md). |

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

| Option | Description |
| --- | --- |
| `--shell [bash|zsh|fish|powershell|dotenv|sh|pwsh]` | Syntax to print (default: detected from $SHELL). |
| `--sdk [node|java|rust|dotnet]` | Also trust the certificate for SDKs that ignore AWS_CA_BUNDLE. Repeatable. |
| `--unset` | Print the commands that undo 'awsemu env'. |
| `--keep-real-creds` | Don't unset AWS_ACCESS_KEY_ID & co. (requests will then fail auth). |
| `--proxy / --no-proxy` | Go through the running proxy (default: yes when awsemu.toml has proxy = true and it's running). |

## `awsemu events`

EventBridge: buses, rules and events. Alias: 'awsemu eb'.

### `awsemu events buses`

List event buses.

```
awsemu events buses [OPTIONS]
```

| Option | Description |
| --- | --- |
| `--json` | Machine-readable JSON output (format: docs/scripting.md). |

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

| Option | Description |
| --- | --- |
| `--bus TEXT` | Event bus name.  [default: default] |

### `awsemu events rm`

Delete a rule (its targets are removed first).

```
awsemu events rm [OPTIONS] NAME
```

| Option | Description |
| --- | --- |
| `--bus TEXT` | Event bus name.  [default: default] |
| `-y, --yes` | Don't ask for confirmation (for scripts). |

### `awsemu events rule`

Create or update a rule and (optionally) its target in one step.

```bash
awsemu events rule orders-created --source app.orders --to-sqs order-events
awsemu events rule big-orders --pattern '{"detail": {"total": [{"numeric": [">", 100]}]}}' --to-lambda alert
```

```
awsemu events rule [OPTIONS] NAME
```

| Option | Description |
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

| Option | Description |
| --- | --- |
| `--bus TEXT` | Event bus name.  [default: default] |
| `--json` | Machine-readable JSON output (format: docs/scripting.md). |

## `awsemu exec`

Run COMMAND with the environment pointed at the emulator.

```bash
awsemu exec -- pytest -k integration
awsemu exec -- terraform apply
awsemu exec --sdk node -- npm test
awsemu exec --proxy -- pytest       # through the proxy (calls log, faults)
```

```
awsemu exec [OPTIONS] COMMAND...
```

| Option | Description |
| --- | --- |
| `--sdk [node|java|rust|dotnet]` | Also trust the certificate in these SDKs (default: awsemu.toml 'sdk'). Repeatable. |
| `--proxy / --no-proxy` | Go through the running proxy (default: yes when awsemu.toml has proxy = true and it's running). |

## `awsemu explain`

Say whether a failed call is a known emulator difference or likely your code.

\b
```bash
awsemu explain            # the last failed call in the proxy's log
awsemu explain 42 --json
```
Compares the call with the fidelity tests of your emulator release (like
'awsemu check'): a test that fails at the same operation with the same
answer is a known difference; passing tests and a "bad request" error point
at the code under test. It's evidence, not proof.

```
awsemu explain [OPTIONS] CALL
```

| Option | Description |
| --- | --- |
| `--release VERSION` | Emulator release whose fidelity data to use (default: yours). |
| `--refresh` | Download the fidelity data again. |
| `--json` | Machine-readable JSON output (format: docs/scripting.md). |

## `awsemu fidelity`

How closely the emulator matches AWS: published scores, or the tests run here.

```bash
awsemu fidelity [SERVICES]...       # the published scores ('fidelity show')
awsemu fidelity s3 --failures       # which tests fail, and how
awsemu fidelity run dynamodb        # run AWS's fidelity tests against your emulator
```

### `awsemu fidelity run`

Run AWS's fidelity tests against the emulator installed here.

\b
```bash
awsemu fidelity run --test dynamodb.update-item-set-list-preserves-element-order
awsemu fidelity run sqs --failing          # reproduce the known differences
awsemu fidelity run s3 --limit 20
awsemu fidelity run lambda --json
```
Each test runs against its own fresh emulator, with the runner of the public
suite (https://github.com/aws/aws-emulator-evaluation-suite), fetched at the
version your release was scored with. Needs git, uv and the emulator binary
('awsemu install'). Exit code 1 if a test fails. Guide: docs/compatibility.md.

```
awsemu fidelity run [OPTIONS] [SERVICES]...
```

| Option | Description |
| --- | --- |
| `--test ID` | A test id (like dynamodb.update-item-...). Repeatable. |
| `--failing` | Only the tests that fail in the published scores (to reproduce them). |
| `--limit N` | Run at most N tests.  [x>=1] |
| `--release VERSION` | Compare with this release's scores (default: your installed one). |
| `--suite DIRECTORY` | A local clone of the evaluation suite to use instead of fetching it. |
| `--refresh` | Download the scores again (and the suite, if it's 'main'). |
| `--json` | Machine-readable JSON output (format: docs/scripting.md). |

### `awsemu fidelity show`

Fidelity scores published with each emulator release: tests passed per service.

```bash
awsemu fidelity                     # every service
awsemu fidelity s3 sqs dynamodb     # just these
awsemu fidelity lambda --failures   # which tests fail, and how
awsemu fidelity --release latest    # a newer release than yours?
awsemu fidelity --compare latest --mine   # what an upgrade changes for you
```
A score counts the tests that call only that service ("k of n", as AWS
publishes it). Data from https://github.com/aws/aws-emulator/releases.

```
awsemu fidelity show [OPTIONS] [SERVICES]...
```

| Option | Description |
| --- | --- |
| `--release VERSION` | Emulator release: 1.0.385, v1.0.385 or latest (default: your installed version). |
| `--failures` | List the failing tests of the given services. |
| `--sort [name|score]` | Order of the table (score: worst first).  [default: name] |
| `--compare VERSION` | Compare with another release: tests fixed, regressed and added, per service. |
| `--mine` | Only the services this project uses (found like 'awsemu check' does). |
| `--refresh` | Download again instead of using the cache. |
| `--json` | Machine-readable JSON output (format: docs/scripting.md). |

## `awsemu iam`

IAM permissions your code needs, from the calls it made (the proxy's log).

### `awsemu iam policy`

The least-privilege IAM policy for the calls your code made.

\b
```bash
awsemu proxy start -d && awsemu exec --proxy -- pytest
awsemu iam policy                                # JSON policy document
awsemu iam policy --account 123456789012 --region eu-west-1
awsemu iam policy --format terraform -o policy.tf
```
Each call becomes an action and, where the call names a resource, its ARN
(region and account '*' unless you give them). Review it: it covers only
the calls the proxy saw, and some calls need more (kms for encrypted data,
iam:PassRole). Guide: docs/iam.md.

```
awsemu iam policy [OPTIONS]
```

| Option | Description |
| --- | --- |
| `--calls-file FILE` | A calls log (default: the proxy's, for --port). |
| `--region TEXT` | Region in the ARNs.  [default: *] |
| `--account TEXT` | Account ID in the ARNs.  [default: *] |
| `--service NAME` | Only this service. Repeatable. |
| `--format [json|terraform]` | A policy document, or a Terraform aws_iam_policy_document.  [default: json] |
| `-o, --output FILE` | Write it to this file. |

## `awsemu image`

Build the Docker image (AWS doesn't publish a prebuilt one).

### `awsemu image build`

Build the image from the official Dockerfile recipe.

```
awsemu image build [OPTIONS]
```

| Option | Description |
| --- | --- |
| `--tag TEXT` | Image name to build.  [default: aws-emulator] |
| `--arch [x86_64|aarch64]` | Package architecture (default: this machine's). |
| `--version VERSION` | Emulator version to put in the image (default: latest). See 'awsemu install --docker'. |

### `awsemu image dockerfile`

Print the Dockerfile awsemu builds from.

```
awsemu image dockerfile [OPTIONS]
```

| Option | Description |
| --- | --- |
| `--arch [x86_64|aarch64]` | Package architecture (default: this machine's). |
| `--version VERSION` | Emulator version (default: latest). |

## `awsemu init`

Create awsemu.toml in this folder.

Without '--port', picks a port from the folder name (9300-9399), so
several projects can run their emulators side by side.

```
awsemu init [OPTIONS]
```

| Option | Description |
| --- | --- |
| `--seed PATH` | Seed file to reference (default: auto-detect). |
| `--force` | Overwrite an existing awsemu.toml. |

## `awsemu install`

Install a given emulator version: the Linux package, or a Docker image.

```bash
awsemu install --list            # published versions
awsemu install 1.0.385 --pin     # install it and pin it for the project
awsemu install                   # the project's pinned version, else latest
awsemu install --docker          # image aws-emulator:<version> (macOS/Windows)
```
On Linux it downloads the .deb/.rpm from downloads.aws.com, checks its
signature against AWS's key, and installs it with apt-get or rpm (sudo).
With a pinned emulator_version, 'awsemu start' warns when the installed
emulator differs, and uses the image aws-emulator:<version> in Docker mode.

```
awsemu install [OPTIONS] [VERSION]
```

| Option | Description |
| --- | --- |
| `--docker` | Build a Docker image of that version instead (macOS, Windows). |
| `--native` | Install the Linux package (the default on Linux with apt or rpm). |
| `--pin` | Also write emulator_version to the project file (awsemu.toml), so the team and CI use it. |
| `--list` | List the published versions, newest first. |
| `--no-verify` | Don't check the package signature with gpg (not recommended). |
| `--dry-run` | Show what would be downloaded and run, and stop. |
| `-y, --yes` | Don't ask for confirmation (for scripts). |
| `--json` | Machine-readable JSON output (format: docs/scripting.md). |

## `awsemu issues`

The emulator's known gaps, from AWS's own issue files.

```bash
awsemu issues dynamodb                 # open issues about DynamoDB
awsemu issues dynamodb:TransactWriteItems sqs
awsemu issues --mine --severity high   # for the services this project uses
awsemu issues lambda --fixed           # fixed ones; marks those your release still fails
awsemu issues --show 3                 # row 3 of the last listing, in full
```
AWS keeps them in https://github.com/aws/aws-emulator/tree/main/issues
('things-that-do-not-work' and 'things-that-now-work'). 'awsemu check' shows the
one behind each known difference.

```
awsemu issues [OPTIONS] [SERVICE[:Operation]]...
```

| Option | Description |
| --- | --- |
| `--mine` | The services this project uses (found like 'awsemu check' does). |
| `--fixed` | Fixed issues instead of open ones, marking those whose tests still fail in your release. |
| `--severity LEVEL` | Only this severity and worse (CRITICAL, HIGH, MEDIUM, LOW). |
| `--search TEXT` | Only issues whose title contains TEXT. |
| `-n, --limit INTEGER` | How many to list (0 = all).  [default: 30] |
| `--show N|NAME` | Print one issue in full: its row in the last listing, its file name (or a prefix), or its URL. |
| `--release VERSION` | With --fixed: the release to compare with (default: yours). |
| `--refresh` | List the issues again instead of using the 6-hour cache. |
| `--json` | Machine-readable JSON output (format: docs/scripting.md). |

## `awsemu kinesis`

Kinesis: data streams and records.

### `awsemu kinesis create`

Create a stream and wait until it's active.

```
awsemu kinesis create [OPTIONS] NAME
```

| Option | Description |
| --- | --- |
| `--shards INTEGER RANGE` | Number of shards.  [default: 1; 1<=x<=64] |

### `awsemu kinesis ls`

List streams with status and shard count.

```
awsemu kinesis ls [OPTIONS]
```

| Option | Description |
| --- | --- |
| `--json` | Machine-readable JSON output (format: docs/scripting.md). |

### `awsemu kinesis put`

Put one record: 'awsemu kinesis put clicks '{"page": "/"}''.

```
awsemu kinesis put [OPTIONS] STREAM [DATA]
```

| Option | Description |
| --- | --- |
| `--file FILENAME` | Record data from a file ('-' = stdin). |
| `-k, --key TEXT` | Partition key (default: random). |

### `awsemu kinesis read`

Read records from every shard.

```
awsemu kinesis read [OPTIONS] STREAM
```

| Option | Description |
| --- | --- |
| `--from [start|latest]` | Read from the oldest record or only new ones.  [default: start] |
| `-n, --limit INTEGER` | Max records (0 = no limit).  [default: 100] |
| `-f, --follow` | Keep polling for new records. |
| `--json` | Machine-readable JSON output (format: docs/scripting.md). |

### `awsemu kinesis rm`

Delete a stream.

```
awsemu kinesis rm [OPTIONS] STREAM
```

| Option | Description |
| --- | --- |
| `-y, --yes` | Don't ask for confirmation (for scripts). |

## `awsemu lambda`

Lambda: deploy, invoke and inspect functions. Alias: 'awsemu fn'.

### `awsemu lambda deploy`

Create or update a function from a folder, a single file or a .zip.

With only a path, the function is named after it (./orders -> orders).
--watch redeploys on every save, and --invoke runs it each time: the loop
of changing a function, without a zip and three commands.
```bash
awsemu lambda deploy hello ./hello.py
awsemu lambda deploy api ./src --handler app.handler -e STAGE=local
awsemu lambda deploy ./orders --watch --invoke '{"id": 1}'
```

```
awsemu lambda deploy [OPTIONS] [NAME] [SOURCE]
```

| Option | Description |
| --- | --- |
| `--handler TEXT` | e.g. app.handler (guessed from the code if omitted). |
| `--runtime TEXT` | e.g. python3.12, nodejs20.x (guessed if omitted). |
| `--role ARN` | Execution role (default: creates 'awsemu-lambda-role'). |
| `-e, --env KEY=VALUE` | Environment variable. Repeatable. |
| `--timeout INTEGER RANGE` | Seconds.  [1<=x<=900] |
| `--memory INTEGER RANGE` | MB.  [128<=x<=10240] |
| `--deps / --no-deps` | Install a folder's requirements.txt into the package (Python).  [default: deps] |
| `-w, --watch` | Keep running and redeploy when a file changes. |
| `--invoke JSON` | Invoke the function with this payload after each deploy. |

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

| Option | Description |
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

| Option | Description |
| --- | --- |
| `-f, --follow` | Keep printing new log events. |
| `--since MINUTES` | Start this many minutes ago.  [default: 60] |

### `awsemu lambda ls`

List functions.

```
awsemu lambda ls [OPTIONS]
```

| Option | Description |
| --- | --- |
| `--json` | Machine-readable JSON output (format: docs/scripting.md). |

### `awsemu lambda rm`

Delete a function.

```
awsemu lambda rm [OPTIONS] NAME
```

| Option | Description |
| --- | --- |
| `-y, --yes` | Don't ask for confirmation (for scripts). |

## `awsemu logs`

Show the emulator's log, prettified (also after it stopped).

```
awsemu logs [OPTIONS]
```

| Option | Description |
| --- | --- |
| `-f, --follow` | Keep printing new lines. |
| `-n, --lines INTEGER` | Lines to show first.  [default: 50] |
| `--raw` | Print the JSON lines untouched. |
| `--grep TEXT` | Only lines containing TEXT (case-insensitive). |

## `awsemu mcp`

An MCP server, so coding agents test against the emulator, never AWS.

\b
```bash
awsemu mcp                          # the server (on stdio; your agent starts it)
awsemu mcp config claude-code       # how to add it to your agent
```
Tools: start/stop the emulator and see its status, the environment for your
code, seeds, resources, any API call, fidelity, project checks, the proxy's
calls and faults, and explaining a failed call. They only work against the
emulator on 127.0.0.1, never with real credentials. Run it from your
project's folder (awsemu.toml applies). Guide: docs/agents.md.

### `awsemu mcp config`

Print how to add the server to an agent: claude-code, claude-desktop, cursor, vscode or json.

```
awsemu mcp config [OPTIONS] [claude-code|claude-desktop|cursor|vscode|json]
```

## `awsemu overview`

What's inside the emulator, across common services. Alias: 'awsemu ls'.

```
awsemu overview [OPTIONS]
```

| Option | Description |
| --- | --- |
| `-s, --service [s3|sqs|dynamodb|sns|lambda|secretsmanager|ssm|kinesis|events|stepfunctions|logs|iam]` | Only these services. Repeatable. |
| `--all` | Also list services with nothing in them. |
| `--json` | Machine-readable JSON output (format: docs/scripting.md). |

## `awsemu proxy`

See every API call, and inject faults (throttling, errors, latency).

```bash
awsemu proxy start -d                     # in the background
awsemu exec --proxy -- pytest             # your code goes through it
awsemu watch --calls                      # every call, live
awsemu proxy faults add 'dynamodb=throttle@10%'
awsemu proxy stop
```
The proxy listens on https://127.0.0.1:<emulator port + 1> with its own
certificate, and forwards everything to the emulator. Guide: docs/proxy.md.

### `awsemu proxy calls`

Calls that went through the proxy (same as 'awsemu watch --calls').

With --json: a list; with --follow --json, one JSON object per line.

```
awsemu proxy calls [OPTIONS]
```

| Option | Description |
| --- | --- |
| `-n, --last INTEGER` | How many of the latest calls to show.  [default: 20] |
| `-f, --follow` | Keep printing new calls (like tail -f). |
| `--service NAME` | Only this service. Repeatable. |
| `--errors` | Only calls that failed (including injected faults). |
| `--json` | Machine-readable JSON output (format: docs/scripting.md). |

### `awsemu proxy cost`

An estimate of what the logged calls would cost on AWS (requests only).

\b
```bash
awsemu proxy cost                 # this run
awsemu proxy cost --runs 3000     # 100 CI runs a day, for a month
awsemu proxy cost --json
```
From AWS's public us-east-1 list prices: no free tier, storage, data
transfer or discounts. An order of magnitude, not a quote. Guide: docs/proxy.md.

```
awsemu proxy cost [OPTIONS]
```

| Option | Description |
| --- | --- |
| `--runs N` | As if the logged calls happened N times (say, CI runs a month).  [default: 1; x>=1] |
| `--calls-file FILE` | A calls log (default: the proxy's, for --port). |
| `--prices FILE` | JSON with your own prices (USD per unit), like {"dynamodb.write": 0.0000007}. |
| `--json` | Machine-readable JSON output (format: docs/scripting.md). |

### `awsemu proxy faults`

List the fault rules of the running proxy (add, set, clear them).

```bash
awsemu proxy faults add 'dynamodb=throttle@10%' 's3=latency:500ms'
awsemu proxy faults set 'sqs:SendMessage=503@50%'   # replace them all
awsemu proxy faults clear
```
Rule syntax: TARGET[RESOURCE]=EFFECT[,EFFECT][@RATE][xTIMES][for DURATION];
see docs/proxy.md.

#### `awsemu proxy faults add`

Add fault rules (they apply to the next calls).

```
awsemu proxy faults add [OPTIONS] RULES...
```

#### `awsemu proxy faults clear`

Remove every fault rule.

```
awsemu proxy faults clear [OPTIONS]
```

#### `awsemu proxy faults set`

Replace every fault rule with these.

```
awsemu proxy faults set [OPTIONS] [RULES]...
```

### `awsemu proxy har`

The logged calls as a HAR file, to open in a browser's developer tools.

```bash
awsemu proxy har -o calls.har     # then: DevTools > Network > Import HAR
awsemu proxy har --errors --service dynamodb -o -
```
Headers and bodies are in it when the proxy ran with --bodies (masked).

```
awsemu proxy har [OPTIONS]
```

| Option | Description |
| --- | --- |
| `-o, --output FILE` | The file to write ('-' for stdout).  [default: awsemu-calls.har] |
| `-n, --last INTEGER` | Only the latest N calls (default: all logged). |
| `--service NAME` | Only this service. Repeatable. |
| `--errors` | Only calls that failed. |

### `awsemu proxy start`

Start the proxy in front of the emulator on --port.

In the foreground it prints each call until Ctrl-C; with -d it runs in the
background. Calls are logged in ~/.aws/emulator-cli/proxy/<port>/calls.jsonl.

```
awsemu proxy start [OPTIONS]
```

| Option | Description |
| --- | --- |
| `--listen PORT` | Port for the proxy (default: proxy_port in awsemu.toml, else the emulator's + 1; 0 = free). |
| `--fault RULE` | Fault rule, like 'dynamodb=throttle@10%' or 's3=latency:500ms'. Repeatable (default: faults in awsemu.toml). |
| `-d, --detach` | Run in the background ('awsemu proxy stop' stops it). |
| `--quiet` | Don't print each call (they're still logged). |
| `--no-tls` | Plain HTTP instead of HTTPS (no certificate to trust). |
| `--host ADDRESS` | Address to listen on. 0.0.0.0 lets containers reach it (at host.docker.internal), and anyone on your network: the emulator's keys and the admin token still apply.  [default: 127.0.0.1] |
| `--bodies` | Also log headers and bodies (up to 64 KB each), with secrets and credentials masked. |

### `awsemu proxy status`

Is the proxy running, where, and with which faults.

```
awsemu proxy status [OPTIONS]
```

| Option | Description |
| --- | --- |
| `--json` | Machine-readable JSON output (format: docs/scripting.md). |

### `awsemu proxy stop`

Stop the background proxy.

```
awsemu proxy stop [OPTIONS]
```

## `awsemu report`

Draft an issue for the emulator from a call the proxy logged.

```bash
awsemu proxy calls --errors          # find the call's id (first column with --json)
awsemu report 42                     # the draft, in Markdown
awsemu report last --open            # the last failed call, in the issue form
```
CALL is a call id, or 'last' for the last call that failed (injected faults
aren't the emulator's, so they're skipped). It follows the emulator's
"Behavior differs from AWS" form: what it answered, the request, the
version and its log around the call. Credentials are removed. What AWS
answers is for you to fill in. Start the proxy with --bodies so the draft
has the request and response.

```
awsemu report [OPTIONS] CALL
```

| Option | Description |
| --- | --- |
| `-o, --output FILE` | Write the draft (Markdown) to this file instead of printing it. |
| `--url` | Print a link to the emulator's issue form with the draft filled in, instead. |
| `--open` | Open that link in your browser. |

## `awsemu restart`

Restart the emulator, which empties its state (it's all in memory).

Alias: 'awsemu reset'. With --seed, the seed is applied to the fresh emulator.

```
awsemu restart [OPTIONS] [EXTRA]...
```

| Option | Description |
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

S3: buckets and objects.

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

| Option | Description |
| --- | --- |
| `-r, --recursive` | List every key, not just one level. |
| `--json` | Machine-readable JSON output (format: docs/scripting.md). |

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

| Option | Description |
| --- | --- |
| `--expires SECONDS` | How long the URL stays valid.  [default: 3600] |
| `--put` | URL for uploading instead of downloading. |

### `awsemu s3 put`

Upload a file (or a folder, recursively) to BUCKET[/KEY].

If KEY is empty or ends with '/', the file name is appended.

```
awsemu s3 put [OPTIONS] SOURCE TARGET
```

| Option | Description |
| --- | --- |
| `--content-type TEXT` | Content-Type for the object(s). |

### `awsemu s3 rb`

Delete a bucket.

```
awsemu s3 rb [OPTIONS] BUCKET
```

| Option | Description |
| --- | --- |
| `--force` | Delete all objects first. |
| `-y, --yes` | Don't ask for confirmation. |

### `awsemu s3 rm`

Delete an object (or a whole prefix with -r).

```
awsemu s3 rm [OPTIONS] TARGET
```

| Option | Description |
| --- | --- |
| `-r, --recursive` | Delete every key under the prefix. |
| `-y, --yes` | Don't ask for confirmation (for scripts). |

## `awsemu secrets`

Secrets Manager: store and read secrets.

### `awsemu secrets get`

Print a secret's value (JSON values are pretty-printed).

```
awsemu secrets get [OPTIONS] NAME
```

| Option | Description |
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

| Option | Description |
| --- | --- |
| `--json` | Machine-readable JSON output (format: docs/scripting.md). |

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

| Option | Description |
| --- | --- |
| `--file FILENAME` | Read the value from a file ('-' = stdin). |
| `--description TEXT` | Free text stored with it. |

### `awsemu secrets rm`

Delete a secret (with a 7-day recovery window unless --now).

```
awsemu secrets rm [OPTIONS] NAME
```

| Option | Description |
| --- | --- |
| `--now` | Delete immediately, without a recovery window. |
| `-y, --yes` | Don't ask for confirmation (for scripts). |

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

| Option | Description |
| --- | --- |
| `-o, --output FILE` | Write to this file (default: stdout). |
| `--objects-dir DIRECTORY` | Save binary or large S3 objects, and Lambda functions' code, here (referenced from the seed). |
| `--no-secrets` | Leave out secrets and SecureString parameters. |
| `-s, --section [buckets|queues|tables|topics|secrets|parameters|streams|functions|state_machines|rules]` | Only these sections. Repeatable. |

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

| Option | Description |
| --- | --- |
| `--express` | EXPRESS type (default STANDARD). |
| `--role ARN` | Execution role (default: creates 'awsemu-sfn-role'). |

### `awsemu sfn executions`

Recent executions of a state machine.

```
awsemu sfn executions [OPTIONS] NAME
```

| Option | Description |
| --- | --- |
| `-n, --limit INTEGER` | How many executions.  [default: 20] |
| `--json` | Machine-readable JSON output (format: docs/scripting.md). |

### `awsemu sfn ls`

List state machines.

```
awsemu sfn ls [OPTIONS]
```

| Option | Description |
| --- | --- |
| `--json` | Machine-readable JSON output (format: docs/scripting.md). |

### `awsemu sfn rm`

Delete a state machine.

```
awsemu sfn rm [OPTIONS] NAME
```

| Option | Description |
| --- | --- |
| `-y, --yes` | Don't ask for confirmation (for scripts). |

### `awsemu sfn start`

Start an execution and (by default) wait for its result.

```
awsemu sfn start [OPTIONS] NAME [INPUT_JSON]
```

| Option | Description |
| --- | --- |
| `--file FILENAME` | Input from a file ('-' = stdin). |
| `--no-wait` | Start and return without waiting for the result. |
| `--timeout SECONDS` | How long to wait for the execution to finish.  [default: 120] |
| `--raw` | Print only the output JSON. |

## `awsemu shell`

Open a sub-shell already pointed at the emulator ('exit' to leave).

```
awsemu shell [OPTIONS]
```

| Option | Description |
| --- | --- |
| `--sdk [node|java|rust|dotnet]` | Also trust the certificate in these SDKs (default: awsemu.toml 'sdk'). Repeatable. |
| `--proxy / --no-proxy` | Go through the running proxy (default: yes when awsemu.toml has proxy = true and it's running). |

## `awsemu snapshot`

Save and restore a whole scenario (the emulator has no snapshots of its own).

```bash
awsemu snapshot save checkout-ready     # everything in the emulator now
awsemu snapshot restore checkout-ready  # empty it and put that back
awsemu snapshot ls
```
A snapshot is a seed (see 'awsemu seed') with the files it needs: S3 objects
and Lambda code. It may contain secrets in plain text, so the default place
is your home folder; --no-secrets leaves them out.

### `awsemu snapshot ls`

List the saved snapshots.

```
awsemu snapshot ls [OPTIONS]
```

| Option | Description |
| --- | --- |
| `--dir DIR` | Where snapshots are kept (default: ~/.aws/emulator-cli/snapshots). |
| `--json` | Machine-readable JSON output (format: docs/scripting.md). |

### `awsemu snapshot restore`

Empty the emulator (a restart) and recreate snapshot NAME.

```
awsemu snapshot restore [OPTIONS] NAME
```

| Option | Description |
| --- | --- |
| `--dir DIR` | Where snapshots are kept (default: ~/.aws/emulator-cli/snapshots). |
| `--no-reset` | Apply it on top of what's there instead of emptying the emulator first. |

### `awsemu snapshot rm`

Delete snapshot NAME.

```
awsemu snapshot rm [OPTIONS] NAME
```

| Option | Description |
| --- | --- |
| `--dir DIR` | Where snapshots are kept (default: ~/.aws/emulator-cli/snapshots). |
| `-y, --yes` | Don't ask for confirmation (for scripts). |

### `awsemu snapshot save`

Save everything in the emulator as snapshot NAME.

```
awsemu snapshot save [OPTIONS] NAME
```

| Option | Description |
| --- | --- |
| `--dir DIR` | Where snapshots are kept (default: ~/.aws/emulator-cli/snapshots). |
| `--no-secrets` | Leave out secrets and SecureString parameters. |
| `--force` | Replace a snapshot with the same name. |

## `awsemu sns`

SNS: topics, publishing and subscriptions.

### `awsemu sns create`

Create a topic.

```
awsemu sns create [OPTIONS] NAME
```

| Option | Description |
| --- | --- |
| `--fifo` | FIFO topic ('.fifo' is added if missing). |

### `awsemu sns ls`

List topics with their subscriptions.

```
awsemu sns ls [OPTIONS]
```

| Option | Description |
| --- | --- |
| `--json` | Machine-readable JSON output (format: docs/scripting.md). |

### `awsemu sns publish`

Publish a message to a topic.

```
awsemu sns publish [OPTIONS] TOPIC [MESSAGE]
```

| Option | Description |
| --- | --- |
| `--file FILENAME` | Read the message from a file ('-' = stdin). |
| `--subject TEXT` | Subject (used by email subscriptions). |
| `-a, --attr KEY=VALUE` | String message attribute. Repeatable. |
| `--group TEXT` | MessageGroupId (FIFO). |
| `--dedup-id TEXT` | MessageDeduplicationId (FIFO). |

### `awsemu sns rm`

Delete a topic (and its subscriptions).

```
awsemu sns rm [OPTIONS] TOPIC
```

| Option | Description |
| --- | --- |
| `-y, --yes` | Don't ask for confirmation (for scripts). |

### `awsemu sns subs`

List subscriptions (of one topic, or all).

```
awsemu sns subs [OPTIONS] [TOPIC]
```

| Option | Description |
| --- | --- |
| `--json` | Machine-readable JSON output (format: docs/scripting.md). |

### `awsemu sns subscribe`

Subscribe a target to a topic.

```bash
awsemu sns subscribe orders --to-sqs order-events --raw
awsemu sns subscribe orders --to-lambda handle-order
```

```
awsemu sns subscribe [OPTIONS] TOPIC
```

| Option | Description |
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

SQS: queues and messages.

### `awsemu sqs create`

Create a queue.

```
awsemu sqs create [OPTIONS] NAME
```

| Option | Description |
| --- | --- |
| `--fifo` | FIFO queue ('.fifo' is added if missing). |
| `--dedup` | Content-based deduplication (FIFO only). |
| `--visibility-timeout SECONDS` | How long a received message stays hidden. |
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

| Option | Description |
| --- | --- |
| `--prefix TEXT` | Only queues whose name starts with this. |
| `--json` | Machine-readable JSON output (format: docs/scripting.md). |

### `awsemu sqs purge`

Delete every message in a queue.

```
awsemu sqs purge [OPTIONS] QUEUE
```

| Option | Description |
| --- | --- |
| `-y, --yes` | Don't ask for confirmation (for scripts). |

### `awsemu sqs receive`

Receive messages (they stay in the queue unless --delete).

```
awsemu sqs receive [OPTIONS] QUEUE
```

| Option | Description |
| --- | --- |
| `-n, --max INTEGER RANGE` | Maximum number of messages.  [default: 10; 1<=x<=10] |
| `--wait SECONDS` | Long-poll time.  [default: 1; 0<=x<=20] |
| `--delete` | Delete messages after printing them. |
| `--json` | Machine-readable JSON output (format: docs/scripting.md). |

### `awsemu sqs rm`

Delete a queue.

```
awsemu sqs rm [OPTIONS] QUEUE
```

| Option | Description |
| --- | --- |
| `-y, --yes` | Don't ask for confirmation (for scripts). |

### `awsemu sqs send`

Send a message. BODY can also come from --file or stdin.

```
awsemu sqs send [OPTIONS] QUEUE [BODY]
```

| Option | Description |
| --- | --- |
| `--file FILENAME` | Read the body from a file ('-' = stdin). |
| `--group TEXT` | MessageGroupId (FIFO). |
| `--dedup-id TEXT` | MessageDeduplicationId (FIFO). |
| `--delay SECONDS` | Delay before the message becomes visible. |
| `-a, --attr KEY=VALUE` | String message attribute. Repeatable. |

## `awsemu ssm`

SSM Parameter Store: configuration parameters.

### `awsemu ssm get`

Print a parameter's value.

```
awsemu ssm get [OPTIONS] NAME
```

| Option | Description |
| --- | --- |
| `--no-decrypt` | Don't decrypt SecureString values. |

### `awsemu ssm ls`

List parameters, optionally under a PATH like /app/prod.

```
awsemu ssm ls [OPTIONS] [PATH]
```

| Option | Description |
| --- | --- |
| `--values` | Also show values (SecureString shown as ****). |
| `--json` | Machine-readable JSON output (format: docs/scripting.md). |

### `awsemu ssm put`

Create or overwrite a parameter: 'awsemu ssm put /app/db/host localhost'.

```
awsemu ssm put [OPTIONS] NAME [VALUE]
```

| Option | Description |
| --- | --- |
| `--file FILENAME` | Read the value from a file ('-' = stdin). |
| `--secure` | Store as SecureString. |
| `--list` | Store as StringList (comma-separated). |
| `--description TEXT` | Free text stored with it. |

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

| Option | Description |
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

| Option | Description |
| --- | --- |
| `--all` | Show every known port, not just the selected one. |
| `--json` | Machine-readable JSON output (format: docs/scripting.md). |

## `awsemu stop`

Stop the emulator (clean stop: it deletes its files and in-memory state).

```
awsemu stop [OPTIONS]
```

| Option | Description |
| --- | --- |
| `--all` | Stop every instance awsemu knows about. |
| `--force` | SIGKILL / docker kill (loses the clean shutdown). |
| `--timeout SECONDS` | How long to wait for a clean stop.  [default: 15] |

## `awsemu ui`

Browse the emulator in the terminal: services, resources and their details.

Keys: arrows/enter to navigate, r refresh, w auto-refresh, q quit.
Needs the 'ui' extra (Textual); if it's missing, this command says how to install it.

```
awsemu ui [OPTIONS]
```

## `awsemu up`

Make sure this project's emulator is running and seeded.

Uses awsemu.toml (port, mode, auth, telemetry, idle_timeout, seed...).
Starts the emulator if it isn't running; either way, applies the seed,
which is safe to repeat.

```
awsemu up [OPTIONS]
```

| Option | Description |
| --- | --- |
| `--seed FILE` | Seed to apply (default: 'seed' from awsemu.toml). |
| `--no-seed` | Don't apply any seed. |
| `--wait SECONDS` | How long to wait for the health check.  [default: 30] |

## `awsemu watch`

Show resources being created, deleted or changed, live (Ctrl+C to stop).

Buckets show their object count, queues their visible messages and tables
their items, so you can see your app working.
```bash
awsemu watch
awsemu watch -s sqs -s dynamodb -i 1
awsemu watch --calls            # API calls, through 'awsemu proxy'
awsemu watch --calls --errors -s dynamodb
```
The emulator doesn't log API calls, so --calls needs the proxy
('awsemu proxy start -d', and your code going through it).

```
awsemu watch [OPTIONS]
```

| Option | Description |
| --- | --- |
| `-s, --service NAME` | Only these services. Repeatable (default: all; resources: dynamodb, events, kinesis, lambda, s3, secrets, sfn, sns, sqs, ssm). |
| `-i, --interval SECONDS` | Time between looks.  [default: 2; 0.5<=x<=3600] |
| `--once` | Print the current state and exit. |
| `--calls` | Show every API call instead (service, operation, result, latency), through the proxy. |
| `--errors` | With --calls: only failed calls. |

## `awsemu whoami`

Check that requests reach the emulator (STS GetCallerIdentity).

```
awsemu whoami [OPTIONS]
```
