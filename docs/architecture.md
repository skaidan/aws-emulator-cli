# Architecture

`awsemu` is a thin layer over the emulator: it doesn't reimplement anything from AWS, it only automates what the official documentation asks you to do by hand.

## What the emulator does and what `awsemu` does

| The emulator (`aws-emulator`) | `awsemu` |
| --- | --- |
| Runs in the foreground; has no subcommands. | Launches it in the background and remembers its PID or container. |
| Writes `config`, `emulator_credentials`, `ca.pem` and `truststore.p12` to `~/.aws/emulator/<port>/` and deletes them on a clean stop. | Reads them (never writes there) and, if they're left behind after a forced stop, deletes them. |
| Exposes `GET /__admin/health`. | Uses it to wait for startup and for `status`. |
| Writes its log as JSON (`tracing` format, with the message under `fields`). | Saves it to disk and shows it readable. Uses the `emulator server information` line to learn the real port with `-p 0`. |
| Accepts SIGTERM / Ctrl+C as a clean stop. | Sends SIGTERM (Ctrl+Break on Windows) and waits. |
| Generates new keys and a new certificate on every start. | Doesn't cache keys across starts; `env` exports paths, not values. |

## Files

```
~/.aws/emulator/                  ← the emulator's
  config.toml                     ← its settings (awsemu config)
  <port>/config, emulator_credentials, ca.pem, truststore.p12

~/.aws/emulator-cli/              ← awsemu's ($AWSEMU_HOME)
  <port>/state.json               ← mode, pid or container, command, log path
  <port>/emulator.log             ← log (native and Docker), kept after stopping
  pending/<n>.log                 ← temporary log of a --port 0 start
  fidelity/<tag>.json.gz          ← cached fidelity scores per emulator release
```

## Modules

```
src/awsemu/
  _meta.py          project identity (package, repository, command): the one place to rename
  exitcodes.py      exit codes 0-3, part of the stable interface
  errors.py         AwsemuError (message, hint, exit code) and its subclasses; context.handle_errors prints them
  cli.py            the root command: global options, aliases and prefixes, and the list of
                    commands (LAZY_COMMANDS), each imported only when it runs or --help lists it
  context.py        global --port and error handling (botocore → message + hint)
  runtime.py        start/stop/status: native, Docker, --port 0, cleanup, Dockerfile
  health.py         /__admin/health check with the instance's ca.pem; waiting for health or a closed port
  waiting.py        poll(check, timeout=...): the one polling loop with a deadline
  envvars.py        environment variables and their syntax per shell
  clients.py        explicit boto3 clients per port; the client configuration for the emulator and for
                    real accounts; error hints (hint_for)
  logs.py           parsing of the emulator's JSON log
  settings.py       editing config.toml while keeping comments
  seed.py           seed format: YAML parsing with a line map, and validation (no AWS calls)
  project.py        awsemu.toml / [tool.awsemu]: upward lookup, validation, per-file cache
  pytest_plugin.py  pytest plugin (pytest11 entry point): aws_emulator and aws_emulator_fresh
  fidelity.py       download and cache of scores.json.gz from emulator releases; per-service
                    scores; compare (test by test between two releases)
  scan.py           static scan of a project: SDK calls (Python, JS, Java, Go) and Terraform,
                    CloudFormation/SAM and CDK resources; service name mapping
  _service_names.py boto3 name -> score-file name, where they differ by more than hyphens
  check.py          manifest.jsonl download and cache; index of fidelity tests by operation;
                    the report of known differences, with issues and fixes in the latest release
  issues.py         the emulator's issue files (issues/ in aws/aws-emulator): listing, parsing,
                    partial downloads cached by blob id
  install.py        versioned packages, versions.json, GPG verification, apt/rpm install plan
  awscalls.py       recognise an AWS call from its HTTP request (service, operation, resource,
                    error code), from botocore's service models
  faults.py         fault rules (parse, decide) and AWS errors in each protocol's format
  proxy.py          the HTTPS proxy: certificates, forwarding, calls log, admin API, background
                    process (state.json), client environment
  completion.py     resource-name completion (silent and fast when the emulator doesn't answer)
  browse.py         data for awsemu ui (list and describe), with no Textual dependency
  tui.py            the Textual app (optional 'ui' extra)
  paths.py          paths and constants (port, region, account 000000000000)
  ui.py             output with Rich, or plain text if it's missing or with --plain
  commands/         one module per command group: lifecycle (start, stop, restart, up, down,
                    init, status), env (env, exec, shell, aws, whoami), logs_, doctor, image,
                    config, ui, completion_; one per service: overview, s3, sqs, dynamodb, sns,
                    lambda_, secrets (secrets + ssm), events, kinesis, sfn, describe, call;
                    and seed, snapshot, compose, fidelity, watch, check, issues, install, proxy,
                    report, explain, iam, mcp
  services/         the service registry: one module per service (s3, sqs, dynamodb, sns, lambda_,
                    secretsmanager, ssm, kinesis, events, stepfunctions, logs, iam), each a Service
                    with its hooks (names, details, describe, watch, completions)
  arns.py           parse ARNs (used by describe)
  awserrors.py      recognise AWS error answers (error_code, is_error, client_error)
  commands/_common.py  AliasedGroup, service roles, queue policies, Lambda permissions, error codes
action.yml          composite GitHub Action (verified package, awsemu, seed, variables)
scripts/            gen_reference.py (docs/reference.md), rename.py (package/repository rename)
```

## Design decisions

**Explicit clients, not environment variables.** Service commands build boto3 clients with the chosen port's endpoint, certificate and keys. That way `awsemu` never uses real credentials even if they're in the shell, and it can talk to several instances.

**`env` exports paths.** Keys and certificate change on every start, but their paths don't: an `eval "$(awsemu env)"` still works after a restart for the certificate and the `config`. (Tools that cache keys in memory do need to reload them.)

**Click instead of Typer.** Typer is built on Click; using Click directly saves a dependency and lets everything be tested with `CliRunner`.

**Rich optional at runtime.** If it's missing, the output is plain text. Useful in minimal images and in CI.

**Expected errors without a traceback.** `handle_errors` turns `RuntimeErrorWithHint` and any botocore error (including the subclasses it generates per code, such as `NoSuchBucket`) into one error line and a hint. Anything else does show a traceback: it's a bug.

**Idempotent seeds that never delete.** `seed apply` compares before writing (secrets, parameters, queue attributes and subscriptions) so repeating it doesn't create needless versions or changes, and it removes nothing that isn't in the seed: `reset --seed` is there to start from scratch. Validation is a separate layer (`seed.py`) that runs in full before touching the emulator.

**One precedence order.** Flag > environment variable > `awsemu.toml` > default, in every command. That's why `start`'s options have no Click default: `None` means "you didn't say" and lets the project setting through.

**The pytest plugin does nothing unless used.** It's registered for everyone who installs `awsemu`, so it only adds options and fixtures; the emulator starts only when a test asks for `aws_emulator`, and on a free port so it doesn't interfere with anything.

**`watch` polls instead of listening.** The emulator doesn't log requests (checked in CI, also with `RUST_LOG=debug`), so `watch` compares snapshots of the state. It keeps state per service so a one-off failure of one isn't read as its resources having disappeared.

**Fidelity of your version, not the latest.** `fidelity` reads the version from `aws-emulator -v` and downloads that release's scores, because comparing against another version would lead to wrong conclusions.

**The UI is optional.** Textual is a big dependency for those who don't use it, so it lives in the `ui` extra; the data logic (`browse.py`) doesn't depend on it and is always tested.

**A stable scripting interface.** Exit codes live in `exitcodes.py` and every `--json` output goes through one encoder (ISO dates, Decimal as numbers). awsemu's own summaries use `snake_case`; AWS resources keep AWS's field names. `tests/test_json_contract.py` pins every format, so a change can't slip in unnoticed.

**Rename-ready.** The package and repository names live in `_meta.py`; `scripts/rename.py` changes them there and in the docs, `pyproject.toml` and the Action references in one go, and checks nothing is left (CHANGELOG excepted).

**Don't write in the emulator's folder.** awsemu's own state lives in `~/.aws/emulator-cli/`. The only exception is deleting, after checking the port is free, the documented files the emulator left behind when it couldn't stop cleanly.

## How it's tested

- `tests/fake_emulator.py` mimics the binary's documented behaviour: options, `-p 0`, files, certificate, health check, `tracing`-format log and cleanup on stop. It lets the lifecycle be tested on Linux, macOS and Windows without the emulator.
- Service commands are tested with a fake boto3 client (`tests/test_services.py`).
- `tests/test_real.py` runs against the real emulator (`AWSEMU_REAL_TESTS=1`), in the `real-emulator` CI job.
- The `docker` job tests `image build`, `start --docker` and `compose` with the real emulator, the `testcontainers` job the Python, Java and Node modules against the image, and the `action` job uses the repository's own GitHub Action.

More details in [CONTRIBUTING.md](../CONTRIBUTING.md).
