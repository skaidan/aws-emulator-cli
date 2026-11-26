# aws-emulator-cli (`awsemu`)

A friendly CLI for [AWS Emulator](https://github.com/aws/aws-emulator), the local emulator of the AWS APIs.

The emulator itself is a single binary with no subcommands: it runs in the foreground, writes its credentials and certificate to `~/.aws/emulator/<port>/`, and expects you to set several environment variables by hand. `awsemu` takes care of all that:

- **Start and stop** the emulator in the background, with the native binary or Docker, waiting until it's healthy.
- **Point your shell at it** with one command (`eval "$(awsemu env)"`), without touching your real credentials.
- **See what's inside**: buckets, queues, tables, functions, secrets… on one screen.
- **Work with S3, SQS, DynamoDB, SNS, Lambda, Secrets Manager, SSM, EventBridge, Kinesis and Step Functions** through short commands and readable tables: DynamoDB with plain JSON, `lambda deploy` from a folder, EventBridge rules with their target and permissions in one step, and `describe` for any ARN.
- **Always start with the same data** using a YAML *seed*: `awsemu start --seed seed.yaml`, `awsemu reset --seed seed.yaml`, and `seed export` to save the current state.
- **Configure it per project** with `awsemu.toml` (`awsemu init`, `awsemu up`, `awsemu down`): its own port, mode, seed…
- **Use it in tests and CI**: a pytest plugin (`aws_emulator` fixture), a GitHub Action (`uses: skaidan/aws-emulator-cli@v0.13.0`) and `awsemu compose` for Docker Compose.
- **Explore it**: a terminal UI (`awsemu ui`), live changes (`awsemu watch`), completion of your resource names, and the **per-service fidelity** of your emulator version (`awsemu fidelity`).
- **See every API call and inject faults**: `awsemu proxy` sits between your code and the emulator, logs each call (`awsemu watch --calls`) and can throttle, fail or slow down the services you pick, to test retries and error handling (also as pytest fixtures: `aws_faults`, `aws_calls`).
- **Know whether your project will work** before you start: `awsemu check` finds the AWS operations your code and infrastructure use and lists the known emulator differences for them, each with the emulator issue that explains it and whether the latest release fixes it; `awsemu issues` searches AWS's own list of known gaps; `awsemu fidelity --compare` shows what an upgrade changes; `awsemu install VERSION --pin` gives your team and CI the same emulator version.
- **Diagnose** common problems (`awsemu doctor`).

```
$ awsemu start
Starting AWS Emulator (native) on port 9297…
✓ AWS Emulator is up at https://127.0.0.1:9297

$ awsemu s3 mb photos && awsemu s3 put ./cat.jpg photos/
$ awsemu sqs create jobs && awsemu sqs send jobs '{"id": 1}'
$ awsemu ddb create users --pk id
$ awsemu ddb put users '{"id": "u1", "name": "Ana", "age": 30}'

$ awsemu overview
AWS Emulator on port 9297
resource         count  names
S3 buckets       1      photos
SQS queues       1      jobs
DynamoDB tables  1      users
```

## Documentation

- [Getting started](docs/getting-started.md): install, start the emulator and connect your tools.
- [Exploring the emulator](docs/explore.md): `ui`, `watch`, `fidelity` and shell completion.
- [Other languages and IaC tools](docs/languages.md): JavaScript, Java, Go, Terraform and CDK, with examples tested in CI.
- [The proxy](docs/proxy.md): every call logged, fault injection, `aws_faults` in pytest.
- [Will my project work?](docs/compatibility.md): `check`, `fidelity --compare`, `install` and the version pin.
- [Project settings](docs/project-config.md): `awsemu.toml`, `init`, `up` and `down`.
- [Seeds](docs/seeds.md): reproducible starting data (format, validation, `apply` and `export`), and snapshots.
- [Services guide](docs/services.md): S3, SQS, DynamoDB, SNS, Lambda, Secrets Manager, SSM, EventBridge, Kinesis, Step Functions and `describe`, with examples.
- [Testing and CI](docs/testing.md): pytest plugin, GitHub Action, Testcontainers (Python, Java, Node), scripts and Docker Compose.
- [IAM](docs/iam.md): the least-privilege policy your calls need, and what your infrastructure doesn't grant.
- [AI coding agents](docs/agents.md): an MCP server (`awsemu mcp`) so agents test against the emulator, never AWS.
- [Scripting](docs/scripting.md): stable JSON output and exit codes.
- [Troubleshooting](docs/troubleshooting.md): what each error means.
- [Command reference](docs/reference.md): every command and option.
- [Architecture](docs/architecture.md), [contributing](CONTRIBUTING.md), [security](SECURITY.md) and the [code of conduct](CODE_OF_CONDUCT.md).

## Installation

Requirements: Python 3.11+ and **one** of these two ways to run the emulator:

- **Linux**: the AWS Emulator `.rpm` or `.deb` package (puts `aws-emulator` on your `PATH`). Once `awsemu` is installed, `awsemu install` installs it for you, signature checked.
- **macOS, Windows or Linux**: Docker. AWS doesn't publish an image, but `awsemu image build` (or `awsemu install --docker`) builds one with the official recipe.

```bash
pipx install git+https://github.com/skaidan/aws-emulator-cli
# or a specific release (any tag from the Releases page):
pipx install git+https://github.com/skaidan/aws-emulator-cli@v0.13.0
```

All versions: [Releases](https://github.com/skaidan/aws-emulator-cli/releases). For the terminal UI (`awsemu ui`), install the `ui` extra: `pipx install 'aws-emulator-cli[ui] @ git+https://github.com/skaidan/aws-emulator-cli'`.

Then:

```bash
awsemu doctor          # checks what you have and what's missing
awsemu install         # the emulator: Linux package (verified), or a Docker image elsewhere
```

## Usage

### Lifecycle

| Command | What it does |
| --- | --- |
| `awsemu start` | Starts in the background and waits for the health check. Uses the binary if installed, otherwise Docker. |
| `awsemu start --docker` / `--native` | Forces the mode. |
| `awsemu up` / `awsemu down` | Starts (if needed) and applies the project's seed / stops it. |
| `awsemu start --no-auth` | No SigV4 signing (the emulator accepts any request). |
| `awsemu start --idle-timeout 600` | Stops by itself after 10 minutes without calls (handy in CI). |
| `awsemu --port 0 start` | The OS picks a free port (native mode only); `awsemu` tells you which. |
| `awsemu start -f` | In the foreground, like the original binary (Ctrl+C to stop). |
| `awsemu start -- <options>` | Passes extra options to the emulator as-is. |
| `awsemu status` / `awsemu ps` | Status, mode, PID or container, uptime. `--all` for every port, `--json` for scripts. |
| `awsemu logs [-f] [--grep TEXT]` | The emulator's JSON log, readable, also after it stopped and also in Docker. `--raw` for the original lines. |
| `awsemu stop [--all]` | Clean stop (SIGTERM; Ctrl+Break on Windows): the emulator deletes its files. |
| `awsemu stop --force` | If it doesn't respond. `awsemu` deletes the files the emulator couldn't clean up. |
| `awsemu restart` / `awsemu reset` | Restarts. The emulator keeps everything in memory, so this **empties its state**. |

Several instances at once: use `--port` (or the `AWSEMU_PORT` variable) with any command.

```bash
awsemu --port 9300 start
awsemu --port 9300 overview
```

If the binary isn't on your `PATH`, point to it with `AWSEMU_BINARY` (arguments allowed):

```bash
export AWSEMU_BINARY=/opt/aws-emulator/bin/aws-emulator
```

### Connecting your tools

```bash
eval "$(awsemu env)"                       # bash / zsh
awsemu env --shell fish | source           # fish
awsemu env --shell powershell | iex        # PowerShell
awsemu env --shell dotenv > .env.emulator  # docker compose, IDEs…
awsemu env --sdk node --sdk java           # adds NODE_EXTRA_CA_CERTS / JAVA_TOOL_OPTIONS
eval "$(awsemu env --unset)"               # back to real AWS
```

`awsemu env` exports the variables the official documentation lists (`AWS_ENDPOINT_URL`, `AWS_CA_BUNDLE`, `AWS_CONFIG_FILE`, `AWS_SHARED_CREDENTIALS_FILE`, `AWS_DISABLE_HOST_PREFIX_INJECTION`…) and also **unsets** `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`, `AWS_SESSION_TOKEN` and `AWS_PROFILE`, which would otherwise take precedence and make authentication fail.

If you'd rather not touch your current shell:

```bash
awsemu exec -- pytest -k integration       # any command, already pointed at the emulator
awsemu aws s3 ls                           # the AWS CLI, pointed at the emulator
awsemu call s3 list-buckets                # any operation, without the AWS CLI
awsemu report last                         # a draft emulator issue from the last failed call (proxy)
awsemu explain                             # was that failure the emulator or your code?
awsemu mcp config claude-code              # tools for your coding agent
awsemu shell                               # a connected sub-shell ('exit' to leave)
awsemu whoami                              # checks you're talking to account 000000000000
```

### Services

```bash
awsemu overview [--all] [-s s3 -s sqs] [--json]   # alias: awsemu ls

awsemu s3 ls [BUCKET[/PREFIX]] [-r]
awsemu s3 mb BUCKET...
awsemu s3 put FILE_OR_FOLDER BUCKET[/KEY]
awsemu s3 get BUCKET/KEY [DEST]
awsemu s3 cat BUCKET/KEY
awsemu s3 rm BUCKET/KEY   |   awsemu s3 rm -r BUCKET/PREFIX
awsemu s3 rb BUCKET [--force]
awsemu s3 presign BUCKET/KEY [--put] [--expires 600]

awsemu sqs ls
awsemu sqs create NAME [--fifo] [--dlq OTHER_QUEUE]
awsemu sqs send QUEUE 'body' [-a key=value] [--group G]
awsemu sqs receive QUEUE [-n 10] [--delete]
awsemu sqs info QUEUE
awsemu sqs purge QUEUE   |   awsemu sqs rm QUEUE

awsemu ddb ls                                      # ddb = dynamodb
awsemu ddb create TABLE --pk id [--sk date:N]
awsemu ddb put TABLE '{"id": "u1", "age": 30}'     # or --file items.json (object or list)
awsemu ddb get TABLE '{"id": "u1"}'
awsemu ddb scan TABLE [-n 50] [--json]
awsemu ddb delete TABLE '{"id": "u1"}'
awsemu ddb drop TABLE

awsemu sns ls
awsemu sns create TOPIC [--fifo]
awsemu sns subscribe TOPIC --to-sqs QUEUE [--raw]  # sets the queue policy
awsemu sns subscribe TOPIC --to-lambda FUNCTION
awsemu sns publish TOPIC 'message' [--subject S] [-a key=value]
awsemu sns subs [TOPIC]   |   awsemu sns rm TOPIC

awsemu lambda deploy NAME ./folder|file.py|code.zip [-e KEY=value]   # alias: fn
awsemu lambda deploy ./folder --watch [--invoke '{}']               # redeploy on every save
awsemu lambda invoke NAME '{"name": "Ana"}' [--raw] [--async]
awsemu lambda logs NAME [-f]
awsemu lambda ls   |   awsemu lambda info NAME   |   awsemu lambda rm NAME
```

`lambda deploy` guesses the handler and runtime from the code (`def handler(...)` in Python, `exports.handler` / `export const handler` in Node), creates an execution role if you don't pass `--role` and, if the function already exists, updates it. A folder's `requirements.txt` is installed into the package, and `--watch` redeploys each time you save.

There's also `awsemu secrets`, `ssm`, `events`, `kinesis`, `sfn` and `describe ARN`: examples of all of them in the [services guide](docs/services.md).

For any other service or operation: `awsemu call <service> <operation> -p Key=value` (through boto3, nothing else to install) or `awsemu aws <service> <operation> ...` (the AWS CLI).

### Exploring

```bash
awsemu ui                          # terminal UI ('ui' extra)
awsemu watch                       # live changes while your app works
awsemu fidelity s3 sqs dynamodb    # how closely it matches AWS, for your version
awsemu fidelity lambda --failures  # which tests fail and why
eval "$(awsemu completion bash)"   # completion, including resource names
```

More in [docs/explore.md](docs/explore.md).

### See every call, and inject faults

```bash
awsemu proxy start -d                              # a proxy in front of the emulator
awsemu exec --proxy -- pytest                      # your code goes through it
awsemu watch --calls                               # every API call, live
awsemu proxy faults add 'dynamodb=throttle@10%'    # 10% of DynamoDB calls throttled
```

```python
def test_retries(aws_faults):                      # pytest
    aws_faults.add("dynamodb:PutItem=throttle x2")
    save_order(...)
    assert aws_faults.operations().count("dynamodb:PutItem") == 3
```

More in [docs/proxy.md](docs/proxy.md).

### Will my project work?

```bash
awsemu check                              # operations you use + known differences for them
awsemu check --strict                     # the same, failing the CI job if there are any
awsemu issues dynamodb                    # what AWS already knows is wrong in a service
awsemu fidelity --compare latest --mine   # what upgrading changes for your services
awsemu install 1.0.385 --pin              # install a version and pin it in awsemu.toml
```

More in [docs/compatibility.md](docs/compatibility.md).

### Per project

```bash
awsemu init        # creates awsemu.toml (a port of its own, seed detected)
awsemu up          # starts it if needed and applies the seed
awsemu down
```

Every command uses the `awsemu.toml` in the current folder (or a parent). Details in [docs/project-config.md](docs/project-config.md).

### Testing and CI

```python
def test_upload(aws_emulator):           # pytest plugin: own emulator, seed and environment ready
    boto3.client("s3").create_bucket(Bucket="demo")
```

```yaml
- uses: skaidan/aws-emulator-cli@v0.13.0   # GitHub Actions: verified package, seed and variables
  with:
    seed: tests/seed.yaml
```

More in [docs/testing.md](docs/testing.md).

### Seeds

```bash
awsemu seed validate seed.yaml     # errors with line and field
awsemu start --seed seed.yaml      # start + apply
awsemu seed apply seed.yaml        # repeatable: creates, updates or leaves as is
awsemu reset --seed seed.yaml      # empty state + seed
awsemu seed export -o seed.yaml    # the current state, as a seed
```

Save a whole scenario and come back to it with `awsemu snapshot save NAME` and `awsemu snapshot restore NAME`.

Format and details in [docs/seeds.md](docs/seeds.md); a full example in [examples/seed.yaml](examples/seed.yaml).

### Emulator settings

```bash
awsemu config show                 # ~/.aws/emulator/config.toml (or $EMULATOR_CONFIG)
awsemu config telemetry off        # writes [telemetry] enabled = false
awsemu start --no-telemetry        # just for this run
```

### Other options

- `--plain` or `NO_COLOR=1`: plain-text output, no colours or boxes.
- Prefixes and aliases: `awsemu stat` → `status`; aliases `ps`, `reset`, `ddb`, `fn`, `eb`, `ls`.
- For scripts: every listing has `--json`, and exit codes are fixed (0 OK, 1 failed, 2 usage, 3 not healthy). Both are a stable interface: [docs/scripting.md](docs/scripting.md).

## How it works

- The emulator writes `config`, `emulator_credentials`, `ca.pem` and `truststore.p12` to `~/.aws/emulator/<port>/` and deletes them on a clean stop. `awsemu` reads them, but never writes there.
- `awsemu` keeps its own state (PID or container, and the log) in `~/.aws/emulator-cli/<port>/`. Change it with `AWSEMU_HOME`.
- To know when the emulator is ready it uses `GET /__admin/health`, the only admin route the emulator offers.
- In Docker it follows the official recipe: publishes the port on `127.0.0.1` **only**, limits memory to 2 GiB, mounts `~/.aws/emulator` and, on Linux, uses your UID so the files are yours.
- Service commands use boto3 with the emulator's endpoint, certificate and keys set explicitly. Even if your shell has real credentials, `awsemu` never calls AWS.

## Limitations

- `--port 0` only works in native mode: Docker can't forward a port chosen at startup.
- On Windows, the clean stop uses Ctrl+Break. If the emulator doesn't handle it, `awsemu` still deletes its files, but the emulator doesn't get to send its last telemetry batch.
- The emulator doesn't persist data: stopping or restarting loses everything. That's by design; [seeds and snapshots](docs/seeds.md) solve it.
- S3 Control doesn't work against the emulator (the SDK always puts the account ID in the host name). That's an emulator limitation.

## Roadmap

Done: native and Docker lifecycle, validation against the real emulator on Linux, macOS and Windows (v0.2), 10 services with their own commands plus `describe` (v0.3), seeds for reproducible starting data (v0.4), `awsemu.toml`, pytest plugin, GitHub Action and Docker Compose (v0.5), `ui`, `watch`, `fidelity` and completion (v0.6), getting ready to publish: English, stable output and an easy rename (v0.7), `awsemu check`, `fidelity --compare` and version pinning to know whether your project will work and upgrade safely (v0.8), a proxy that logs every call and injects faults (v0.9), more seed coverage, snapshots and other languages (v0.10), an MCP server for agents (v0.11), from local to AWS: least-privilege IAM, running the fidelity tests yourself, shadow mode and seeds from a real account (v0.12), and hardening: static checks, compatibility matrix, supply chain (v0.13). Coming next: a deep refactor for architecture and performance (v0.14), more services with their own commands (API Gateway, Cognito, CloudWatch Logs and others, v0.15; AppSync, OpenSearch, IoT and AI services, v0.16; the rest of a typical account, v0.17; recommended gaps, v0.18), new features for the development loop (v0.19) and for testing, CI and safety (v0.20), and the final name with PyPI, Homebrew and standalone binaries (v1.0). Details in [ROADMAP.md](ROADMAP.md), changes per version in [CHANGELOG.md](CHANGELOG.md).

## Development

```bash
git clone https://github.com/skaidan/aws-emulator-cli && cd aws-emulator-cli
python -m venv .venv && . .venv/bin/activate
pip install -e '.[dev,ui]'
pytest
```

Full guide (tests, adding a service, documentation and releases) in [CONTRIBUTING.md](CONTRIBUTING.md).

The regular tests don't need the real emulator: `tests/fake_emulator.py` mimics its documented behaviour (options, `-p 0`, files, health check, JSON log and cleanup on stop), and service commands are tested with a fake boto3 client. They run on Linux, macOS and Windows.

Tests against the real emulator (`tests/test_real.py`) are enabled separately:

```bash
AWSEMU_REAL_TESTS=1 pytest -m real -v
```

In CI, the `real-emulator` job downloads the official `.deb`, verifies its GPG signature and runs them.

## License

MIT. This project is not official and not affiliated with AWS.
