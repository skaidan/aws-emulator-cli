# Changelog

## Unreleased

### Breaking

- **Python 3.11 or later** is now required: Python 3.10 reached its end of life in October 2026. pip keeps installing awsemu 0.13.0 on Python 3.10. `tomli` is no longer a dependency (awsemu uses the standard library's `tomllib`). The policy for Python versions is now in [docs/deprecations.md](docs/deprecations.md).

### Dependencies

- Testcontainers module for Node: Testcontainers 12, which needs **Node 22.22 or later** (was Node 20). The module sets its own wait strategy, so Testcontainers 12's new default doesn't change it.
- Testcontainers module for Java: Testcontainers 2.0.5 and AWS SDK 2.59.7; its own tests run on JUnit 6 (test scope only: your project can keep JUnit 5).
- CI and release workflows: `actions/checkout` 7, `actions/setup-python` 7, `actions/cache` 6, `hashicorp/setup-terraform` 4.

## 0.13.0 — 2026-11-26

Everything planned for 0.12 and 0.13. Going from local to AWS: the IAM policy your calls need and what your infrastructure misses (`awsemu iam policy`, `awsemu check --iam`), AWS's fidelity tests run on your machine (`awsemu fidelity run`), a cost estimate, and read-only bridges to a real account (`awsemu seed import`, the proxy's shadow mode). Hardening before 1.0: a tested minimum emulator version (1.0.290), update notices, JSON Schemas for every `--json` output, a deprecation policy, and the first release with signed provenance, an SBOM and checksums.

### From local to AWS

- `awsemu iam policy`: the least-privilege IAM policy for the calls in the proxy's log: actions (with S3, Lambda and batch exceptions mapped) and resource ARNs where the calls name them; `--account`, `--region`, `--service`, `--format terraform`.
- `awsemu fidelity run SERVICES|--test ID [--failing] [--limit N]`: AWS's fidelity tests against your installed emulator, each with its own fresh emulator and the suite's own runner (fetched at the version your release was scored with, prepared with uv), with the verdicts compared to the published scores. `awsemu fidelity` is now a group: `fidelity [SERVICES]` still shows the scores (`fidelity show`). Tested in CI against the real emulator.
- `awsemu seed import --profile NAME [--region R]`: a seed from a real account's configuration (buckets without objects, queues, tables without items, topics, parameters, streams, state machines, rules; secret values replaced), read-only: only the named profile, `AWS_ENDPOINT_URL` ignored, and anything but a configuration read refused before it's sent. Asks first.
- Shadow mode: `awsemu proxy start --shadow PROFILE` also sends read-only configuration calls to that real account in the background and logs where the status, error code or response shape differ; `awsemu proxy shadow` lists them. Writes and data reads are never sent, at most `--shadow-max` calls, AWS's responses aren't stored.
- `awsemu proxy cost [--runs N] [--prices FILE]`: an estimate of the request charges the logged calls would have on AWS (us-east-1 list prices, no free tier or storage), clearly labelled as one.
- `awsemu check --iam`: the IAM actions your code needs (from the static scan, or `--from-calls`) that no `Allow` in your Terraform, CloudFormation/SAM or synthesized CDK policies grants; managed policies and SAM templates are listed as not expanded. `--strict` for CI. Guide: `docs/iam.md`.

### Safer to depend on

- A minimal install, documented and tested: without `boto3` and `cryptography`, the emulator's lifecycle and the environment commands work; commands that need them say what to install instead of failing with an import error. They stay dependencies of the package (see `docs/getting-started.md`).
- A deprecation policy (`docs/deprecations.md`): renamed options, settings and JSON fields keep working for at least two minor releases and three months, with a warning; the code has the helpers to do it (`awsemu.deprecation`).
- JSON Schemas for every `--json` output in `docs/schemas/` (generated from `src/awsemu/schemas.py`; the contract tests validate real outputs against them).
- `awsemu doctor` shows whether your emulator is supported (from 1.0.290, the oldest release CI tests awsemu with: earlier ones don't log the startup line random ports need) and whether a newer emulator or awsemu is out; `awsemu start` mentions newer releases at most once a day, on a terminal, never in CI or with `AWSEMU_NO_UPDATE_CHECK=1`.

### Releases and the project

- Releases come with signed build provenance (Sigstore, GitHub attestations), a CycloneDX SBOM and SHA-256 checksums; `SECURITY.md` says how to verify them. GitHub Actions are pinned to commit SHAs, and Dependabot proposes updates for Python, Actions, npm and Maven dependencies.
- Project health: `SECURITY.md` (private vulnerability reports, scope), a code of conduct, issue forms (bugs, ideas, links to the emulator's own issues) and a pull request template.
- Development: ruff (lint and format) and mypy run in CI, the code is formatted and type-checked, and tests have a coverage minimum (65%; 69% today). The proxy now closes every socket and upstream connection when it stops, and the suite runs without resource warnings.

## 0.11.0 — 2026-11-26

Everything planned for 0.10 and 0.11, in one release. Coding agents get an MCP server with guard rails (`awsemu mcp`, guide: `docs/agents.md`) and can ask whether a failure is the emulator or the code (`awsemu explain`). The proxy logs bodies, exports HAR, takes faults per resource and over time, serves containers and drafts emulator issues (`awsemu report`). Node, Java, Go, Terraform and CDK are tested in CI, with Testcontainers modules for Python, Java and Node. Plus `awsemu call`, `lambda deploy --watch`, snapshots, four new seed sections, `awsemu issues` and setup-trap detection in `doctor`.

### AI coding agents

- `awsemu mcp`: an MCP server (stdio, no extra dependency) so coding agents test against the emulator: status, start/stop, the environment for the code, seeds, resources, any API call, fidelity, project checks, the proxy's calls and faults, and explaining a failure. Guard rails: no real credentials or endpoint overrides reach the commands, tools refuse an emulator that isn't on 127.0.0.1, no tool takes an endpoint, region or keys, and every answer says it ran on the emulator, not AWS. `awsemu mcp config claude-code|claude-desktop|cursor|vscode` prints how to add it. Guide: `docs/agents.md`.
- `awsemu explain [CALL]`: whether a failed call from the proxy's log is a known emulator difference, maybe one, an emulator gap, probably the code under test, or unknown, with the fidelity tests that back it.

### The proxy

- Proxy fault rules for one resource (`dynamodb:PutItem[orders]=throttle`, `s3[uploads-*]=503`) and for a while (`s3=503 for 30s`, an outage that recovers). `awsemu proxy faults` shows each rule's state and time left; its `--json` adds `active` and `remaining_s`.
- `awsemu proxy start --bodies` (or `proxy_bodies = true`): the calls log also keeps headers and bodies (64 KB each), with secrets and credentials masked: auth headers, presigned signatures, values of secret-like keys in JSON, XML and form bodies, SSM `SecureString` values. Presigned signatures are now masked in every call's `path`.
- `awsemu proxy har`: the logged calls as a HAR file, for a browser's developer tools.
- `awsemu report CALL` (or `last`): a draft issue for the emulator from a call in the proxy's log, following its "Behavior differs from AWS" form: the response, the emulator's log around it, the request without signing headers, earlier calls on the same resource, an `awsemu call` line to send it again, and the version. `--url`/`--open` fill in the form.
- Containers through the proxy: `awsemu proxy start --host 0.0.0.0` (its certificate now includes `host.docker.internal` and the `--host` name), and `awsemu compose --proxy` writes an `x-aws-emulator-client` block for app services (endpoint, certificate and credentials mounted read-only). Tested in CI with the AWS CLI image.
- The proxy's admin API needs a token, made on each start and kept in its state file (readable only by you), so other local processes or the network can't change the faults or read the calls.
- `--sdk java` with the proxy builds a truststore with the proxy's certificate too, instead of asking you to import it.
- `awsemu check --from-calls` (and `--calls-file FILE`): check the operations the proxy saw your tests call, instead of scanning the code.

### Other languages, infrastructure and test frameworks

- Other languages and infrastructure tools, tested in CI against the real emulator: `examples/sdks/node` (AWS SDK for JavaScript v3), `examples/sdks/java` (SDK for Java v2), `examples/sdks/go` (SDK for Go v2), `examples/terraform` and `examples/cdk`, and a guide, `docs/languages.md`, with what each needs.
- `--sdk java` no longer makes the JVM trust only the emulator, which broke every other HTTPS connection of the process (Maven, Gradle). It builds a truststore with what Java already trusted (your truststore, or the JDK's `cacerts`) plus the emulator's certificate, with `keytool`, and keeps your other `JAVA_TOOL_OPTIONS` (proxy settings, memory), which it used to replace.
- Testcontainers modules: `AwsEmulatorContainer` for Python (`awsemu.containers`, extra `testcontainers`), Java (`testcontainers/java`) and Node (`testcontainers/node`). They run the image from `awsemu image build` on a random port, read the certificate and keys from the container, and give the endpoint, credentials and a way to trust the certificate only in your clients. Tested in CI against the image; not published yet.
- Terraform: AWS provider 6.23+ can't read S3 bucket tags from a local emulator (S3 Control puts the account ID in the host name); the example pins `< 6.23`, and the guide and troubleshooting explain it.
- GitHub Action: new `sdk` input (`node`, `java`…) to export the certificate settings those SDKs need.

### Working with services

- `awsemu call SERVICE OPERATION [-p Key=value] [--params JSON]`: any operation of any service through boto3, for the services without their own commands and machines without the AWS CLI. Operations in any spelling (`ListBuckets`, `list_buckets`, `list-buckets`) with suggestions for typos, `--paginate`, `--query` (JMESPath), `--out` for streaming bodies, `-p Body=@file` for bytes, and shell completion of services and operations.
- A fast Lambda loop: `awsemu lambda deploy ./folder --watch [--invoke JSON]` redeploys the code on every save and runs it, and keeps watching when a deploy fails. `deploy` with only a path names the function after it, and a Python folder's `requirements.txt` is installed into the package (cached until it changes; `--no-deps` to skip, `deps: false` in seeds).
- `awsemu snapshot save NAME`, `restore NAME [--no-reset]`, `ls [--json]`, `rm NAME`: save everything in the emulator and come back to it later. A snapshot is a seed export of every section with the files it needs, kept in `~/.aws/emulator-cli/snapshots/` (or `--dir`). `restore` empties the emulator and applies it, and warns when it was saved with another emulator version.
- Seeds: four new sections. `streams` (Kinesis: shards, retention), `functions` (Lambda from local code: handler and runtime guessed as in `lambda deploy`, `env`, `timeout`, `memory`, and `triggers` from SQS queues and Kinesis streams), `state_machines` (Step Functions, a definition file or inline) and `rules` (EventBridge: a pattern or a schedule, any bus, up to 5 targets among SQS, Lambda, SNS, Step Functions and Kinesis, with the permissions they need). `apply` is still repeatable: a function is only redeployed when its code changed. `seed export` writes them too, and saves functions' code with `--objects-dir`.
- `awsemu lambda deploy` builds reproducible packages (same files, same zip), so the code's SHA-256 says whether it changed.

### Knowing what to trust

- `awsemu doctor` finds the setup traps that quietly break SDK calls in your shell: an `AWS_ENDPOINT_URL` where nothing answers (or with `http://`), an `AWS_CA_BUNDLE` that's missing, for another port or not the emulator's, an HTTP(S) proxy without `127.0.0.1` in `NO_PROXY`, and settings of your own `~/.aws/config` that the emulator's `AWS_CONFIG_FILE` hides (with the environment variables that do the same). The `localhost` warning now says why.
- `awsemu env`, `exec` and `shell` add `127.0.0.1,localhost` to `NO_PROXY` when `HTTPS_PROXY`/`HTTP_PROXY` is set, so a company proxy never gets the emulator's calls. `env --unset` leaves your `NO_PROXY` alone.
- CI: a daily `Emulator watch` workflow tests every new AWS Emulator release as soon as it's published (installed with `awsemu install`, signature checked). A failure opens an `emulator-compat` issue, and the next release that passes closes it.
- `awsemu check` explains each known difference. `↳ fixed in vX` means the test passes in the latest release (one more scores download). `↳ known issue (SEVERITY): …` links to the emulator's own issue file that explains it (`issues/` in aws/aws-emulator). The summary counts both. `--no-explain` skips these lookups. JSON: each difference gains `issues` and `fixed_in`; the summary gains `explained_by_issues`, `fixed_in_latest` and `latest`.
- `awsemu issues [SERVICE[:Operation]]... [--mine] [--fixed] [--severity LEVEL] [--search TEXT] [--show N|NAME] [--json]`: search AWS's list of known emulator gaps (about 3,800 open, 20,000 fixed). Only the start of each file is downloaded, and it's cached by its content. `--fixed` marks the fixes your release doesn't have yet.

### Fixes

- Fixed: with the emulator's auth off (`--no-auth`, `auth = false`), `awsemu env`, `exec`, `shell` and the pytest plugin set no credentials, because the emulator writes no credentials file then. The SDKs failed with "unable to locate credentials", or signed with your real default profile from `~/.aws/credentials`. They now set placeholder keys (`EMULATORAUTHOFF00000`), as awsemu's own clients already did.
- Fixed: the `check` summary counted a failing test once per operation it affects. `differences` (and "N failing test(s)") now counts distinct tests.

## 0.9.0 — 2026-11-25

The proxy: see every API call, and inject faults. Guide: `docs/proxy.md`.

- `awsemu proxy start [-d] [--listen PORT] [--fault RULE]... [--no-tls]`, `stop`, `status`: a local HTTPS proxy in front of the emulator (port + 1 by default) with its own certificate, which stays the same across restarts. It forwards every request untouched (SigV4 signatures and Host-based URLs keep working) and logs each call: service, operation, resource, status, AWS error code, latency, request id. Calls are recognised from botocore's service models, for every protocol.
- `awsemu proxy calls [-n N] [--follow] [--service S] [--errors] [--json]` and `awsemu watch --calls [--errors]`: the calls, from `~/.aws/emulator-cli/proxy/<port>/calls.jsonl`. `awsemu ui`: press `c` for a live calls view.
- Fault injection: rules `TARGET=EFFECT[,EFFECT][@RATE][xTIMES]` with latency, `throttle` (the right throttling error per API), any error code, HTTP 4xx/5xx and `reset`. Set them with `--fault`, `awsemu proxy faults add/set/clear` while the proxy runs, or `faults` in `awsemu.toml`. Injected errors use each API's protocol, so SDKs raise the real exception and retry as they would against AWS.
- `awsemu env`, `exec`, `shell`: `--proxy/--no-proxy`. `awsemu.toml`: `proxy = true` (`up` starts the proxy, `env`/`exec`/`shell`/`aws` use it, `down`/`stop` stop it), `proxy_port`, `faults`.
- pytest plugin: `aws_faults` and `aws_calls` fixtures (calls of one test through an in-process proxy, with `.add()`, `.calls`, `.operations()`, `.errors()`, `.client()`), `aws_proxy`, and `--awsemu-proxy` / `awsemu_proxy = true` for every test.
- `cryptography` is now a dependency (the proxy's certificate).

## 0.8.1 — 2026-11-16

Fixes found by running v0.8.0 against AWS's real data in CI.

- `awsemu install --list` now reads AWS's `versions.json`, whose versions have four parts (`1.0.471.1`, the last being the package release). Before, it always fell back to the GitHub releases list.
- `awsemu check`: emulator releases don't name the fidelity tests version in their notes, so `check` used the tests repository's `main`. It now uses the newest published version of the fidelity tests (today `v1.0.0`), and `main` only if that can't be looked up.

## 0.8.0 — 2026-11-16

Will my project work with the emulator? Answers before you start, and upgrades without surprises. Guide: `docs/compatibility.md`.

- `awsemu check [PATHS]`: finds the AWS operations your code calls (boto3, AWS SDK for JavaScript v2/v3, Java, Go) and the services your infrastructure defines (Terraform, CloudFormation/SAM, CDK), and lists the known emulator differences for them from the release's fidelity tests: tests that fail at an operation you call, or that call only operations you call. Uses `manifest.jsonl` from the fidelity tests repository, at the version the release was scored with (cached; `--manifest` for another version or a local file). `--all`, `--strict` (exit 1 on known differences, for CI), `--json`.
- `awsemu fidelity --compare VERSION`: tests fixed, regressed, added and removed between two releases, per service. `--mine` limits `fidelity` (with or without `--compare`) to the services the project in the current folder uses.
- `awsemu install [VERSION]`: installs a given emulator version. On Linux, the `.deb`/`.rpm` from downloads.aws.com with its GPG signature and AWS's key fingerprint checked, through `apt-get`/`rpm` (downgrades allowed); elsewhere, a Docker image `aws-emulator:<version>`. `--list` (published versions), `--pin`, `--dry-run`, `--no-verify`, `-y`.
- `emulator_version` in `awsemu.toml`/`[tool.awsemu]`: `start`, `up` and `doctor` warn when the installed emulator differs; Docker mode runs `aws-emulator:<version>`; `check` and `fidelity` default to that release.
- GitHub Action: new `emulator-version` input (default: `emulator_version` from `awsemu.toml`, else latest) and `emulator-version` output.
- `awsemu image build --version` and `awsemu image dockerfile --version`.
- Fixed: `awsemu fidelity stepfunctions` (and `events`, `logs`, `cognito-idp`…) didn't find the service: the boto3 names are now mapped to the names in the scores file.
- New: `examples/check-demo`, a tiny project to try `awsemu check`.

## 0.7.0 — 2026-11-16

Getting ready to publish: English, a stable scripting interface, and an easy rename.

**Breaking** (JSON output; see `docs/scripting.md`):

- `overview --json`: each service is now `{"label", "items", "error"}` (it was a list of names, or `{"error"}`).
- `sqs ls --json`: `{"name", "url", "visible", "in_flight", "delayed"}` with integer counts (it had AWS attribute names with string values).
- `fidelity --json`: `scoredAt`, `multiServicePassed` and `multiServiceTotal` are now `scored_at`, `multi_service_passed` and `multi_service_total`.
- `status --json`: `uptime` is now `uptime_seconds`; `status --json` exits with 3 when the emulator isn't healthy, like `status`.
- Dates in every `--json` output are ISO 8601 (`2026-11-16T12:00:00+00:00`) instead of Python's default format.

Added and changed:

- English is the project's official language: documentation, ROADMAP, CHANGELOG, examples, test data and release notes (code, help and messages already were). See "Language" in `CONTRIBUTING.md`.
- `--json` on `ddb ls`, `lambda ls`, `kinesis ls`, `sfn ls`, `sfn executions`, `sns subs`, `events buses` and `doctor`; `sns ls --json` includes each topic's `name`.
- `docs/scripting.md`: exit codes, JSON conventions and every format, with a stability promise; `tests/test_json_contract.py` pins them.
- Exit codes in one place (`exitcodes.py`): 0 OK, 1 failed, 2 usage, 3 not healthy.
- `doctor` reports a missing emulator runtime as a check of its own.
- Every command and option has help text; service groups have consistent summaries.
- `scripts/rename.py` and `_meta.py`: the package and repository names in one place, renamed everywhere in one go.
- Install instructions use git tags instead of wheel URLs.

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
