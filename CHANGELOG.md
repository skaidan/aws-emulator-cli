# Changelog

## Unreleased

- English is now the project's official language: documentation, ROADMAP, CHANGELOG, examples and test data have been translated (code, help and messages were already in English). See "Language" in `CONTRIBUTING.md`.

## 0.6.0 — 2026-11-16

Exploring the emulator.

- `awsemu fidelity [SERVICE...]`: per-service fidelity scores for the release you have installed (`--release` for another), `--failures` with the operation and the difference for each failing test, `--sort score`, `--json`. Downloads `scores.json.gz` from the emulator's releases and caches it.
- `awsemu watch`: resources created, deleted and changed, live (objects, messages, items), with `-s`, `-i` and `--once`.
- `awsemu completion bash|zsh|fish`, which also completes resource names from the running emulator.
- `awsemu ui`: a terminal UI built with Textual (optional `ui` extra).
- New guide: `docs/explore.md`.

## 0.5.0 — 2026-11-15

Projects and CI integration.

- `awsemu.toml` (or `[tool.awsemu]` in `pyproject.toml`), looked up from the current folder upwards (or `AWSEMU_CONFIG`): `port`, `mode`, `auth`, `telemetry`, `idle_timeout`, `seed`, `sdk`, `image`, `memory`. Every command honours it; flags and `AWSEMU_PORT` still take precedence.
- `awsemu init`, `awsemu up` (starts if needed and applies the seed) and `awsemu down`. `up` and `down` are no longer aliases of `start` and `stop`.
- pytest plugin (installed with awsemu): `aws_emulator` and `aws_emulator_fresh` fixtures; `--awsemu-seed`, `--awsemu-port`, `--awsemu-reuse`, `--awsemu-docker` options and their ini equivalents.
- GitHub Action in `action.yml`: the emulator package with its signature verified, `awsemu`, seed and variables for the following steps.
- `awsemu compose`: a Docker Compose service with the official recipe.
- `doctor` and `config show` show the active project.
- CI: jobs for Docker mode with the real emulator and for the Action itself.

## 0.4.0 — 2026-11-15

Seeds: the same starting state after every start or restart.

- `awsemu seed apply FILE`: creates buckets (with objects as text, JSON or from local folders), queues with DLQs, tables with items, topics with SQS/Lambda subscriptions (with filters and raw delivery), secrets and parameters. Repeatable: reports what was created, updated or unchanged, and never deletes.
- `awsemu start --seed FILE` and `awsemu reset --seed FILE`, which validate the seed before starting or stopping.
- `awsemu seed validate FILE`: errors with line and field, and suggestions for misspelled fields.
- `awsemu seed export`: the current state as a seed (`--no-secrets`, `--objects-dir`, `-s SECTION`).
- `examples/seed.yaml` and the `docs/seeds.md` guide.
- New dependency: PyYAML.

## 0.3.0 — 2026-11-15

More services, all tested against the real emulator.

- `awsemu sns`: `ls`, `create`, `publish`, `subscribe` (`--to-sqs` sets the queue policy; `--to-lambda` adds the permission), `subs`, `unsubscribe`, `rm`.
- `awsemu lambda` (alias `fn`): `deploy` from a folder, file or `.zip` (guesses handler and runtime, creates the role if needed, updates if it exists), `invoke` with a JSON payload and log, `logs`, `info`, `ls`, `rm`.
- `awsemu secrets` (Secrets Manager) and `awsemu ssm` (Parameter Store): `put` creates or versions, `get` formats JSON, `ls` never shows secret values.
- `awsemu events` (alias `eb`): `rule` creates the rule and its target (`--to-sqs`, `--to-lambda`, `--to-sns`) with the permissions; `put`, `rules`, `buses`, `create-bus`, `rm`.
- `awsemu kinesis`: `create`, `put`, `read` (all shards, JSON/text/hex, `--follow`), `ls`, `rm`.
- `awsemu sfn`: `deploy` (creates the role), `start` (waits; shows the output or the error and cause; exit code 1 if it fails), `executions`, `rm`.
- `awsemu describe ARN` for S3, SQS, DynamoDB, SNS, Lambda, Secrets Manager, SSM, Kinesis, EventBridge, Step Functions, CloudWatch Logs and IAM.
- `lambda logs` explains that the emulator doesn't send Lambda output to CloudWatch Logs and points to `lambda invoke`.
- Full documentation in `docs/` and `CONTRIBUTING.md`; `docs/reference.md` is generated from the code and CI checks it's up to date.
- Release workflow: each new version in `pyproject.toml` is published to GitHub automatically with its wheel.

## 0.2.0 — 2026-11-15

Validation against the real emulator, and robustness.

- Integration tests against the real AWS Emulator (`pytest -m real`) and a CI job that installs the official `.deb` after verifying its signature.
- CI on Linux, macOS and Windows.
- `--port 0`: the OS picks a free port and `awsemu` reads it from the startup line.
- Clean stop on Windows (Ctrl+Break). After a forced stop or a crash, `awsemu stop` deletes the files the emulator left in `~/.aws/emulator/<port>/`.
- Logs are kept on disk in Docker too and can be read after stopping.
- Errors with specific hints (credentials from another run, unsigned requests, `UnknownService`, clock skew, TLS…).
- `AWSEMU_BINARY` to point to the emulator binary.

## 0.1.0 — 2026-11-15

First version: `start`/`stop`/`restart`/`status`/`logs`, `env`/`exec`/`shell`/`aws`/`whoami`, `overview`, S3, SQS and DynamoDB commands, `doctor`, `image build` and `config telemetry`.
