# Getting started

## 1. Install `awsemu`

You need Python 3.10 or later.

```bash
pipx install git+https://github.com/skaidan/aws-emulator-cli
# or a specific release (any tag from the Releases page):
pipx install git+https://github.com/skaidan/aws-emulator-cli@v0.11.0
```

Optional: shell completion (including the names of your buckets, queues, tables…) and the terminal UI:

```bash
echo 'eval "$(awsemu completion bash)"' >> ~/.bashrc    # zsh: completion zsh; fish: see docs/explore.md
pipx install --force 'aws-emulator-cli[ui] @ git+https://github.com/skaidan/aws-emulator-cli'
```

Check what you have and what's missing:

```bash
awsemu doctor
```

### A minimal install

Most of awsemu's size is the AWS SDK for Python (`boto3`, whose `botocore` is over 100 MB installed) and `cryptography`. If a machine or a CI image only needs to **start and stop the emulator and point other programs at it** (Node, Java, Go or Terraform code that brings its own SDK), it can do without them:

```bash
pip install --no-deps 'aws-emulator-cli @ git+https://github.com/skaidan/aws-emulator-cli' click rich pyyaml
# Python 3.10 also needs: tomli
```

What works then (tested with those packages blocked): `start`, `stop`, `restart`, `status`, `up`, `down`, `env`, `exec`, `logs`, `compose`, `doctor` and `config`. Commands that call AWS APIs (`s3`, `sqs`, `overview`, `seed`, `call`…) or run the proxy say what's missing and how to install it. `awsemu doctor` lists `boto3` as missing.

They stay regular dependencies of the package: pip can't install "optional by default" extras yet, and making them opt-in would leave the usual `pip install` without the service commands, seeds, the proxy and the pytest plugin's fault injection.

## 2. Choose how to run the emulator

`awsemu` doesn't include the emulator: it runs it. There are two ways, and `awsemu start` picks one by itself (the native binary first, otherwise Docker).

### Native (Linux)

Let `awsemu` install the official package (Debian/Ubuntu or RPM-based, x86_64 or ARM). It checks the package's GPG signature against AWS's key, shows what it will run, and asks:

```bash
awsemu install            # the latest version
awsemu install 1.0.385    # a specific one (awsemu install --list)
aws-emulator -v
```

To do it by hand instead, see the [official Linux installation guide](https://docs.aws.amazon.com/emulator/latest/userguide/getting-started-linux.html). To give a whole team the same version, pin it: [compatibility.md](compatibility.md#awsemu-install-and-emulator_version).

If the binary isn't on your `PATH`, tell `awsemu` where it is:

```bash
export AWSEMU_BINARY=/path/to/aws-emulator
```

### Docker (macOS, Windows or Linux)

AWS doesn't publish an image; `awsemu` builds one with the official recipe (it detects whether your machine is x86_64 or ARM):

```bash
awsemu image build                # or: awsemu install --docker [VERSION]
awsemu image dockerfile           # to see the Dockerfile it uses
```

Prefer Docker Compose? `awsemu compose -o compose.emulator.yaml` generates the service with the same setup (see [Testing and CI](testing.md#docker-compose)).

## 3. Start it

```bash
awsemu start
```

`awsemu` launches the emulator in the background, waits until it answers on `https://127.0.0.1:9297/__admin/health` and tells you what to do next. Useful options:

| I want to… | Command |
| --- | --- |
| Force Docker or native | `awsemu start --docker` / `--native` |
| Use another port | `awsemu --port 9300 start` |
| Let the OS pick the port | `awsemu --port 0 start` (native only) |
| Stop it automatically when idle | `awsemu start --idle-timeout 600` |
| Accept unsigned requests | `awsemu start --no-auth` |
| Turn telemetry off | `awsemu start --no-telemetry` or `awsemu config telemetry off` |
| See it in the foreground | `awsemu start -f` |
| Start with data | `awsemu start --seed seed.yaml` (see [Seeds](seeds.md)) |

```bash
awsemu status          # is it healthy?
awsemu logs -f         # its log, readable
awsemu stop            # clean stop
awsemu reset           # restart = empty state (the emulator keeps everything in memory)
awsemu reset --seed seed.yaml   # empty state + your starting data
```

## 4. Connect your tools

The emulator creates new keys and a new certificate on every start, in `~/.aws/emulator/<port>/`. `awsemu env` exports the variables that point to those files:

```bash
eval "$(awsemu env)"
aws sts get-caller-identity   # Account: 000000000000 → you're on the emulator
```

| Shell | Command |
| --- | --- |
| bash / zsh | `eval "$(awsemu env)"` |
| fish | `awsemu env --shell fish \| source` |
| PowerShell | `awsemu env --shell powershell \| iex` |
| `.env` file | `awsemu env --shell dotenv > .env.emulator` |
| undo | `eval "$(awsemu env --unset)"` |

`awsemu env` also removes `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`, `AWS_SESSION_TOKEN` and `AWS_PROFILE`: if they stayed, they'd take precedence and the emulator would reject the requests.

Some SDKs don't read `AWS_CA_BUNDLE`. Add what they need with `--sdk`:

```bash
eval "$(awsemu env --sdk node)"   # NODE_EXTRA_CA_CERTS
eval "$(awsemu env --sdk java)"   # JAVA_TOOL_OPTIONS with truststore.p12
eval "$(awsemu env --sdk rust)"   # SSL_CERT_FILE (also for .NET: --sdk dotnet)
```

Without touching your shell:

```bash
awsemu exec -- npm test          # a command with the environment already set
awsemu aws s3 ls                 # the AWS CLI pointed at the emulator
awsemu call s3 list-buckets      # any operation, through boto3 (no AWS CLI needed)
awsemu shell                     # a connected sub-shell
```

## 5. Explore

```bash
awsemu overview        # what's in S3, SQS, DynamoDB, SNS, Lambda, Secrets, SSM…
awsemu s3 mb photos
awsemu sqs create jobs
```

Continue with the [services guide](services.md), or explore with `awsemu ui`, `awsemu watch` and `awsemu fidelity` ([Exploring the emulator](explore.md)).

## In a project

If you always work with the same setup, save it in the project:

```bash
awsemu init      # creates awsemu.toml with a port of its own and your seed
awsemu up        # starts it (if needed) and applies the seed
awsemu down
```

See [Project settings](project-config.md).

Before you rely on the emulator for a project, check what it uses against the known differences:

```bash
awsemu check     # the AWS operations your code calls, and the fidelity tests that fail for them
```

See [Will my project work?](compatibility.md).

## Several instances

Each instance lives on its own port, with its own files and resources. Use `--port` (or `AWSEMU_PORT`) with any command:

```bash
awsemu --port 9300 start
AWSEMU_PORT=9300 awsemu overview
awsemu status --all
awsemu stop --all
```
