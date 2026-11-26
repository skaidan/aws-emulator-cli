# Roadmap

How `awsemu` will evolve. Each version has a clear goal; within each, tasks are ordered by priority. It's a living document: it changes as we learn from using the CLI against the real emulator.

Legend: ✅ done · 🚧 in progress · ⬜ to do

---

## v0.1 — Foundation ✅

Goal: one command each to start, connect to and explore the emulator.

- ✅ `start` / `stop` / `restart` / `status` / `logs` with the native binary or Docker
- ✅ `env` (bash, zsh, fish, PowerShell, dotenv), `exec`, `shell`, `aws`, `whoami`
- ✅ `overview` of several services on one screen
- ✅ S3, SQS and DynamoDB commands (with plain JSON)
- ✅ `doctor`, `image build`, `config telemetry`
- ✅ Tests with a fake emulator and fake boto3 clients; CI on Linux

---

## v0.2 — Validated against the real emulator ✅

Goal: trust that everything works against the actual emulator, on every OS.

- ✅ **Real integration tests in CI**: the `real-emulator` job downloads the official `.deb`, verifies its GPG signature and runs `tests/test_real.py` (S3, SQS, DynamoDB, `overview`, `exec`, `restart`). Locally: `AWSEMU_REAL_TESTS=1 pytest -m real`.
- ✅ **Clean stop on Windows**: Ctrl+Break is sent to the emulator's process group. If files are left in `~/.aws/emulator/<port>/` after a forced stop (or on Windows), `awsemu` deletes them.
- ✅ **CI on Linux, macOS and Windows**: the fake emulator generates its certificate with `cryptography`.
- ✅ **`--port 0` support**: the real port is read from the startup line.
- ✅ **Persistent logs**: in Docker too, and readable after stopping.
- ✅ **Better errors**: specific hints for `AccessDenied`, `SignatureDoesNotMatch`, unsigned requests, `UnknownService`, clock skew, unemulated operations and TLS.
- ✅ `AWSEMU_BINARY` to use a binary that isn't on the `PATH`.

## v0.3 — More services ✅

Goal: cover the services most used in application tests. All tested against the real emulator in CI.

- ✅ **SNS**: `ls`, `create`, `publish`, `subscribe` (with `--to-sqs QUEUE`, which creates the subscription and the queue policy, and `--to-lambda`).
- ✅ **Lambda**: `ls`, `deploy` (from a folder, file or zip; guesses handler and runtime), `invoke` with a JSON payload and its log, `logs`, `info`, `rm`.
- ✅ **Secrets Manager and SSM Parameter Store**: `put`, `get`, `ls`, `rm` (and `info` for secrets).
- ✅ **EventBridge**: `rule` with its target and permissions in one step (`--to-sqs`, `--to-lambda`, `--to-sns`), `put`, `rules`, `buses`, `rm`.
- ✅ **Kinesis**: `create`, `put`, `read` (all shards, `--follow`), `ls`, `rm`.
- ✅ **Step Functions**: `deploy`, `start` (waits and shows the output or the failure's cause), `executions`, `rm`.
- ✅ **`awsemu describe <ARN>`** for 12 services.

Learned in CI: the emulator doesn't send Lambda output to CloudWatch Logs; `lambda invoke` shows the log of each invocation.

## v0.4 — Reproducible state (seeds) ✅

Goal: always start with the same data. The emulator keeps everything in memory and has no reset route, so the CLI solves this.

- ✅ **`awsemu seed apply seed.yaml`**: a declarative file with buckets (and objects inline, as JSON or from local folders), queues with their DLQs, tables with items (inline or from a file), topics with subscriptions, secrets and parameters. Idempotent: creates, updates or leaves as is, and never deletes.
- ✅ **`awsemu start --seed`** and **`awsemu reset --seed`**: the seed is validated before starting or stopping anything.
- ✅ **`awsemu seed export`**: dumps the current state to a seed (secrets optional, binaries to a folder).
- ✅ **Validation** with exact line and field, suggestions for misspelled fields, and `awsemu seed validate`.
- ✅ A full example in `examples/seed.yaml`, validated in the tests and applied against the real emulator in CI.

Not in this version: Lambda functions, EventBridge rules, Kinesis streams and Step Functions state machines in seeds.

## v0.5 — Projects and CI integration ✅

Goal: a project declares its emulator and anyone brings it up with `awsemu up`.

- ✅ **Per-project `awsemu.toml`** (or `[tool.awsemu]` in `pyproject.toml`): port, mode, auth, telemetry, `idle_timeout`, seed, SDK extras, image and memory. `awsemu init` creates it (with a port of the project's own), `awsemu up` starts and applies the seed, `awsemu down` stops it. Precedence: flag > environment > project > default.
- ✅ **pytest plugin**: `aws_emulator` (session, free port, seed, environment) and `aws_emulator_fresh` (restart per test) fixtures, with `--awsemu-*` and ini options.
- ✅ **GitHub Action** (`uses: skaidan/aws-emulator-cli@v0.6.0`): installs the verified package and `awsemu`, starts the emulator, applies the seed and exports the variables.
- ✅ **`awsemu compose`**: generates the Docker Compose service with the safe setup.
- ✅ CI with the real Docker mode (`image build`, `start --docker`, `compose`) and with the Action itself.

Learned in CI: Docker mode worked first time; the plugin had an ordering bug with `HOME` that only showed up with the real emulator (fixed and covered by a test).

## v0.6 — Interactive experience ✅

Goal: explore the emulator without remembering commands.

- ✅ **Shell completion** (`awsemu completion bash|zsh|fish`), with the real names of buckets (and paths), queues, tables, topics, functions, secrets, parameters, streams, state machines and rules.
- ✅ **Terminal UI** (`awsemu ui`, with Textual, `ui` extra): a tree of services and resources, details of each one (never showing secret values), manual and automatic refresh.
- ✅ **`awsemu watch`**: live resource changes (created, deleted, messages, items, objects).
- ✅ **`awsemu fidelity`**: per-service scores published with each emulator release, for your installed version, and details of the failing tests.

Learned in CI: the emulator doesn't log API calls (not even with `RUST_LOG=debug`), so `watch` shows the effect on resources rather than the calls. The scores are in a `scores.json.gz` attached to each release, with each test's result and the services it calls.

## v0.7 — Getting ready to publish ✅

Goal: settle what's hard to change once others install and use `awsemu`.

- ✅ **English as the official language**: code, comments, help, documentation, ROADMAP, CHANGELOG, examples, test data and commits.
- ✅ **Rename-ready** (the name itself is decided at the end, in v1.0): the package and repository names live in `_meta.py`, and `scripts/rename.py` changes them everywhere in one go (CHANGELOG excepted), with `--check` and `--dry-run`, and verifies nothing old is left. Install instructions no longer depend on wheel file names.
- ✅ **Stable output**: exit codes 0–3 in one module; one JSON encoder (ISO dates); `snake_case` for awsemu's own summaries and AWS's names for AWS resources; `--json` on every listing (and `doctor`); every format documented in `docs/scripting.md` and pinned by contract tests. Stability promise: changes only as **Breaking** in the CHANGELOG.
- ✅ **Help review**: every command and option has help text (enforced by a test); consistent summaries for service groups.

## v0.8 — Will my project work with the emulator? ✅

Goal: answer before you start, and upgrade the emulator without surprises.

- ✅ **`awsemu check`**: finds the AWS operations your code and infrastructure use (boto3, JavaScript v2/v3, Java and Go SDKs, Terraform, CloudFormation/SAM, CDK) and cross-references them with the fidelity tests, using the release's scores file and the `manifest.jsonl` of the tests version the release was scored with. Lists a failing test when it fails at an operation you call or calls only operations you call; counts the rest. Services defined as infrastructure get their score and, with CloudFormation/SAM/CDK, the score of the tests that deploy them through CloudFormation. `--strict` for CI, `--json`, and a runnable example in `examples/check-demo`.
- ✅ **`awsemu fidelity --compare VERSION`**: tests fixed, regressed, added and removed between two releases, per service; `--mine` for the services your project uses.
- ✅ **`awsemu install [VERSION]`**: the Linux package of any published version (GPG signature and key fingerprint checked, downgrades allowed), or a Docker image `aws-emulator:<version>`; `--list`, `--dry-run`, `--pin`. `emulator_version` in `awsemu.toml`: `start`, `up` and `doctor` warn on a different installed version, Docker mode uses the matching image, `check`/`fidelity` use its data, and the GitHub Action installs it (or its new `emulator-version` input).

## v0.9 — Proxy: see the calls and inject faults ✅

Goal: what the emulator doesn't provide. It doesn't log API calls (checked in CI, v0.6) and, according to analysts, doesn't simulate throttling or outages.

- ✅ **`awsemu proxy`**: a local HTTPS proxy between your code and the emulator, with its own stable certificate, logging every call (service, operation, resource, status, AWS error code, latency) to `calls.jsonl`. Calls are recognised from botocore's service models (every protocol: JSON, REST-JSON, REST-XML, query, EC2, CBOR). `start [-d]`, `stop`, `status`, `calls`; `env`/`exec`/`shell` `--proxy`; `proxy = true` in `awsemu.toml` makes `up` start it and the other commands use it.
- ✅ **`awsemu watch --calls`** and a calls view in `awsemu ui` (key `c`), fed by the proxy.
- ✅ **Fault injection**: rules like `dynamodb=throttle@10%`, `s3=latency:500ms`, `sqs:SendMessage=503@5%x3`, `reset`; per command (`--fault`, `awsemu proxy faults add/set/clear` while it runs) and in `awsemu.toml` (`faults`). Errors are written in each API's protocol, so SDKs raise the real exception and retry as they would against AWS (checked against botocore's parsers and retry rules).
- ✅ pytest plugin integration: `aws_faults` (faults for one test, removed after it), `aws_calls` (assert on the calls your code made), `aws_proxy`, and `--awsemu-proxy` for a whole session.

## v0.10 — Completing what exists ✅ (released in 0.11.0)

Goal: close the known gaps in what's already done.

- ✅ **CI against every new emulator release**: a scheduled job (daily) that installs the latest emulator and runs the real-emulator tests, opening an issue when something breaks. Done: the `Emulator watch` workflow, which uses `awsemu install` and only runs when there's an untested release; a failure opens an `emulator-compat` issue, and the next passing release closes it. The emulator ships very often (1.0.471 to 1.0.611 in nine days), and today we only find out on our next commit.
- ✅ **Emulator with auth off**: `awsemu env`/`exec` don't set any credentials when `auth = false` (the emulator writes no credentials file), so the SDKs either fail with "unable to locate credentials" or sign with your real default profile from `~/.aws/credentials`. Set placeholder keys in that case, as `awsemu`'s own clients already do. Done: `env`, `exec`, `shell` (and the pytest plugin) set them, checked against the real emulator with a real-looking profile in `~/.aws/credentials`.
- ✅ **Explain known differences with AWS's own issue files.** The emulator repository tracks every gap it knows in `issues/` (about 3,800 open in `things-that-do-not-work/`, 20,000 fixed in `things-that-now-work/`), each with its severity, the operation, the failing test ids, what AWS does, what the emulator does and the expected fix. Use them:
  - `awsemu check` shows, for each known difference, the issue that explains it, and whether the latest release already fixes it (from its scores);
  - `awsemu issues [SERVICE[:Operation]] [--fixed] [--severity] [--search] [--show N]` to search them, and see which fixes came after your emulator version.
- ✅ **Common setup traps in `awsemu doctor`**: `AWS_ENDPOINT_URL` with `localhost` instead of `127.0.0.1` (the JavaScript, Java and Go SDKs then put the S3 bucket in the host name), real credentials or `AWS_PROFILE` in the environment, a stale `AWS_CA_BUNDLE` from an earlier start, and settings of your own `~/.aws/config` (retries, S3 options) that `AWS_CONFIG_FILE` hides while you use the emulator. Done, plus an HTTP(S) proxy without `127.0.0.1` in `NO_PROXY` (which `env`/`exec` now add themselves).
- ✅ **Seeds with more services**: Lambda functions (from local code), EventBridge rules, Kinesis streams and Step Functions state machines, in `seed export` too. Done, with Lambda triggers from SQS and Kinesis, and rule targets to SQS, Lambda, SNS, Step Functions and Kinesis; functions are only redeployed when their code changed.
- ✅ **`awsemu snapshot save/restore`**: save and restore a whole scenario (the emulator has no snapshots), built on `seed export` and `reset --seed`. Done: `save`, `restore` (or `--no-reset`), `ls`, `rm`, kept in your home folder or `--dir`.
- ✅ **Infrastructure tools and other languages, tested in CI**: Terraform, CDK, and the Node, Java and Go SDKs against the emulator, with guides and examples. Done: `examples/sdks/{node,java,go}`, `examples/terraform`, `examples/cdk`, a CI job per tool, and `docs/languages.md`.
- ✅ **Java without a truststore trap**: `--sdk java` makes the JVM trust only the emulator, so Maven or Gradle can't download anything in the same process. Build a truststore with the JDK's own certificates plus the emulator's (with `keytool`, which every JDK has) and point the JVM at that one. Done (it starts from your own truststore if `JAVA_TOOL_OPTIONS` names one).
- ✅ **A fast Lambda loop**: `awsemu lambda deploy PATH [--watch]` packages local code (Python, Node), creates or updates the function and redeploys on save, so changing a function doesn't mean a zip and three commands. Done, with `--invoke JSON` to run it after each deploy and `requirements.txt` installed into the package.
- ✅ **`awsemu call SERVICE OPERATION [--params JSON]`**: any API call through boto3, for the services without their own commands and for machines without the AWS CLI (`awsemu aws` needs it). Done, with `-p Key=value`, `--paginate`, `--query` and `--out`.
- ✅ **Testcontainers modules** (Python, Java, Node): an `AwsEmulatorContainer` built on the Docker image, for teams that start their dependencies with Testcontainers rather than pytest fixtures. Done, in `awsemu.containers`, `testcontainers/java` and `testcontainers/node`, tested in CI; they're published with the rest at v1.0.
- ✅ **Proxy, the next step**:
  - ✅ fault rules per resource (`dynamodb:PutItem[orders]=throttle`) and over time (`s3=503 for 30s`, an outage that recovers);
  - ✅ optional request and response bodies in the calls log (`--bodies`), with secrets and credentials masked;
  - ✅ export the calls as HAR, to open them in a browser's developer tools;
  - ✅ `awsemu check --from-calls`: check the operations your tests really called (the proxy's log) instead of the static scan, which can miss calls or match a method by its name;
  - ✅ `--host 0.0.0.0` and `awsemu compose --proxy`, so containers can go through it too;
  - ✅ a token for the admin API (before it, any local process could change the faults), and a Java truststore for the proxy's certificate;
  - ✅ `awsemu report CALL_ID`: a draft GitHub issue for the emulator with what AWS asks for (the request, the emulator's response and what AWS answers), built from the proxy's log, with credentials removed. What AWS answers is left for whoever files it, with a link to the operation's reference: awsemu doesn't call AWS.

## v0.11 — AI agents ✅ (0.11.0)

Goal: a coding agent tests its code against the emulator without touching AWS.

- ✅ **`awsemu` MCP server**: tools to start and stop the emulator, apply seeds, query resources, check a service's fidelity and read the proxy's calls. Done: `awsemu mcp`, over stdio without extra dependencies, tested in CI against the real emulator.
- ✅ A guide to use it with agents, alongside the `aws-emulator` *skill* mentioned in AWS's documentation.
- ✅ **Guard rails for agents**: the MCP tools never use real credentials or a real AWS endpoint, refuse anything that isn't `127.0.0.1`, and say so in their answers, so an agent can't test against a production account by mistake.
- ✅ **Explain a failure**: given a failing call (from the proxy's log), say whether it matches a known emulator difference (`awsemu check` data) or is probably a bug in the code under test.

## v0.12 — From local to AWS ✅ (released in 0.13.0)

Goal: what works locally should work on AWS too. The emulator can't promise that for permissions and costs, and it doesn't check IAM like AWS does: some services evaluate policies differently, a request signed with a key it created is never denied, and KMS key policies and S3 bucket policies aren't checked. A missing permission only shows up after deploying.

- ✅ **Least-privilege IAM from your calls**: `awsemu iam policy` turns the proxy's log of a test run into the IAM policy those calls need (actions, and resource ARNs where they can be known), to compare with what you grant.
- ✅ **Permissions your infrastructure is missing**: `awsemu check --iam` compares those calls (or the static scan) with the roles and policies in your Terraform/CloudFormation/CDK, and lists actions your code needs that no policy grants. Local tests can't show that today.
- ✅ **Run the fidelity tests yourself**: `awsemu fidelity run SERVICE [--test ID]` runs tests of the public suite against your local emulator. That reproduces a known difference on your machine, checks a new emulator version before the scores are published, or confirms a fix.
- ✅ **What it would cost on AWS**: `awsemu proxy cost` estimates, from the calls log and AWS's public prices, what a test run or a workload would cost against a real account (requests, not storage over time). It's an order of magnitude, clearly labelled as an estimate.
- ✅ **Shadow mode** in the proxy: send read-only calls to both the emulator and a real AWS account you name explicitly, and report where the answers differ. That's your own fidelity test, built from your traffic. Opt-in and read-only, with great care for credentials and costs.
- ✅ **A seed from a real account**: `awsemu seed import --profile NAME` reads the configuration of an account (tables, queues, topics, buckets without their objects, parameters without SecureString values), read-only and only with a profile you name, and writes a seed, to start locally from something close to your environment.

## v0.13 — Hardening before 1.0 ✅ (0.13.0)

Goal: what a project people depend on needs, beyond features.

- ✅ **A compatibility matrix**: the oldest emulator version each awsemu release works with, tested in CI with `awsemu install VERSION`, and shown by `awsemu doctor`.
- ✅ **Static checks in CI**: ruff (lint and format) and mypy on `src/`, and test coverage with a minimum. Fix the warnings that exist today (`tests/test_watch.py`).
- ✅ **Update notices**: `awsemu doctor` (and, at most once a day, `awsemu start`) says when there's a newer emulator release, or a newer awsemu, without getting in the way in CI.
- ✅ **Supply chain**: Dependabot for Python dependencies and Actions, pinned Action versions, signed release artifacts with provenance (Sigstore / GitHub attestations), and an SBOM.
- ✅ **Project health**: `SECURITY.md` (how to report a vulnerability, e.g. in the proxy), issue and pull request templates, a code of conduct, and labels for "good first issue".
- ✅ **JSON Schemas** for every `--json` output (generated from the contract tests and published with the docs), so scripts can validate what they read.
- ✅ **A deprecation policy**: how long a flag, setting or JSON field keeps working after it's replaced, and warnings when it's used, written down before 1.0 promises stability.
- ✅ **Lighter installs**: check whether `boto3` and `cryptography` can become extras (for example, `awsemu start`/`env` without them) without making the common case worse. Checked: they stay dependencies (pip has no default extras, so making them optional would make the usual install worse); a minimal install without them is documented and tested, and commands that need them say what to install. Revisit if default extras (PEP 771) land.

## v0.14 — Deep refactor: architecture and performance

Goal: before adding dozens of services (v0.15 to v0.18), make adding one cheap and safe, and make the code faster and easier to change. **No change in behaviour**: every `--json` output is already checked against its JSON Schema, the reference is generated from the code and the real-emulator tests run in CI, so they are the safety net. Small pull requests, each one green; a benchmark before and after for the performance items.

Where we are (measured on 0.13.0): 18,400 lines in 73 modules; `cli.py` has 1,167 lines and imports all 26 command modules (and with them the proxy, `check`, `http.client`, `urllib.request` and `yaml`) even for `awsemu --version`, so importing the CLI takes about 90–150 ms before any command runs; what awsemu knows about one service is spread over many files (Secrets Manager appears in 14 modules: `overview`, `describe`, `watch`, seeds, snapshots, completion, `check`, cost, IAM, the MCP server, `seed import`, the UI…); boto3 clients are created in 5 different places; there are 57 `except Exception` and 44 direct `subprocess` calls.

**Architecture**

- ⬜ **A service registry**: one module per service under `awsemu/services/` that declares, in one place, how to list its resources, describe one, seed and snapshot it, watch it, complete its names, estimate its cost, which IAM actions it needs, what `seed import` reads and which MCP tools it exposes. `overview`, `describe`, `watch`, the UI, `seed`, `snapshot`, `completion`, `check`, `cost`, `iam policy`, `realaccount` and `mcp` read the registry instead of having their own `if service == ...` code. A new service becomes one file plus its tests, and a test checks every registered service implements every hook (or says why not).
- ⬜ **Layers**: a core with no Click and no Rich (pure logic that returns dataclasses), adapters for the outside world (boto3, processes, Docker, files, the network) and a presentation layer (Click commands, Rich tables, JSON). The same core result feeds the table, `--json`, the MCP server and the pytest plugin, so they can't drift apart.
- ⬜ **JSON Schemas from the types**: generate `schemas.py` from the core's dataclasses instead of writing the schemas by hand, so an output and its schema can't disagree.
- ⬜ **A public Python API** (`awsemu.api`): start, stop, env, seed, snapshot, proxy, faults and calls as plain functions, documented and covered by the stability promise. The CLI, the pytest plugin, the Testcontainers module and the MCP server all use it; today each has part of that logic.
- ✅ **One client factory**: one place that creates boto3 clients for the emulator, the proxy or a real account (CA, endpoint, region, retries, timeouts, the read-only guard), with a cache per process.
- ⬜ **One runtime interface** for native and Docker modes (start, stop, health, logs, version, files), with a fake implementation for tests, instead of `subprocess` calls spread across modules.
- ⬜ **One configuration model**: `settings`, `project`, `envvars` and command-line options merged into one layered object that knows where each value came from; `awsemu config --explain` prints it ("port 4566 from awsemu.toml, line 3").
- ✅ **Errors**: a small hierarchy of awsemu errors mapped to exit codes in one place (`awsemu.errors`); the 18 "not found" checks only catch AWS error answers. The other 39 `except Exception` are deliberate (one failing resource or service mustn't stop the others, a notice must never break a command) and stay, each with its reason.
- ⬜ **Split the big modules** along those lines: ~~`cli.py` (1,167 lines)~~ (done: 128 lines, its commands are in `commands/`), `commands/seed.py` (1,124), `proxy.py` (890), `commands/proxy.py` (663), `runtime.py` (567), `seed.py` (568), `commands/lambda_.py` (565).
- ⬜ **The proxy as a pipeline**: parse → match faults → forward → record → shadow → cost, each step a small class with its own tests, so new steps (IAM enforcement, tracing in v0.20) plug in without touching the others.
- ⬜ Keep old import paths working through the deprecation policy (the pytest plugin and `awsemu.containers` are imported by users).

**Performance**

- ✅ **Lazy commands**: a command's module loads only when it runs (`LAZY_COMMANDS` in `cli.py`), and the root group imports Rich, the runtime and the project file only when a command runs: `awsemu --version` went from about 170 ms to 40 ms. ⬜ Still to do: keep boto3, cryptography and YAML out of `env` and completion, so they feel instant too.
- ⬜ **Proxy throughput**: reuse upstream connections (a pool per thread), stream large bodies instead of reading them into memory, and write the call log in batches; measure calls per second and added latency with `awsemu bench` (moved here from the ideas list) before and after.
- ✅ **One wait helper**: the 18 `time.sleep` loops (health checks, waiting for resources, `--follow`) become one helper with a deadline, backoff and a clear timeout message.
- ⬜ **Caching**: botocore's service models and the fidelity scores loaded once per process; `check` and `scan` reuse one parsed index.
- ⬜ Profile `seed apply`, `snapshot save/restore`, `overview` and `check` on a large project (thousands of objects and items) and fix what shows up.

**Quality**

- ⬜ mypy `strict` on the core and the adapters; coverage target from 65% to 80%.
- ⬜ Property-based tests (Hypothesis) for the parsers: fault rules, durations, seeds and redaction.
- ⬜ Mutation testing (mutmut) on the core once, to find tests that don't really check anything.
- ⬜ An architecture test (import-linter) that stops the core importing Click or Rich, and commands importing each other.
- ⬜ Update `docs/architecture.md` with the new layers and the service registry, and a "how to add a service" guide in CONTRIBUTING.md.

## v0.15 — More services

Goal: the services people use next to the ten awsemu already covers get the same treatment (their own commands, seed sections, `overview`, `describe`, `watch`, the UI, completion and `check`). Today they only work through `awsemu call` and `describe`.

Evidence: the emulator has 438 service models, and the public fidelity suite has behavioural tests for 351. The scores below are single-service tests passed for emulator v1.0.629 (the "open" count is the emulator repository's own `issues/things-that-do-not-work` for that service, as of 2026-11-26). Order is by how often the service sits next to the ones we cover, and by how much awsemu can add over `call`.

**First: the web and auth layer of a serverless app**

- ⬜ **API Gateway** (REST 97.0%, HTTP APIs 75.6%; WebSocket data plane not served yet): `awsemu api ls` (APIs, stages, routes and their integrations), `awsemu api invoke API [STAGE] METHOD PATH` (call a deployed stage locally without working out the invoke host by hand; the emulator routes `{api}.execute-api.{region}.amazonaws.com`, so awsemu sets that host), the invoke URL in `env`/`overview`, and APIs in seeds. Pairs with `lambda deploy --watch` for a local edit-and-call loop. For WebSocket APIs, `api ws send CONNECTION 'msg'` through the **API Gateway Management API** (97.0%), to test code that pushes to connected clients.
- ⬜ **Cognito user pools** (94.4%, 53 open; Lambda triggers are among the known gaps): `awsemu cognito pool create`, `user add EMAIL --password` (confirmed, no email step), `token USER` (InitiateAuth, printing ID/access tokens, or `--export` as variables for curl and tests), and pools, clients and users in seeds. A pytest fixture that returns a signed-in user. Say clearly which triggers the emulator does not invoke yet. **Identity pools** (Cognito Identity, 94.1%) too: `cognito credentials USER` exchanges the user's token for temporary AWS credentials, the way web and mobile apps get them.
- ⬜ **CloudWatch Logs** (95.1%, 190 open): `awsemu logs ls`, `awsemu logs tail GROUP [--follow] [--filter PATTERN]`, and `awsemu lambda logs NAME` on top of it. Also a "logs" pane in the UI and log groups in `overview`.

**Next: services that are configuration people seed**

- ⬜ **KMS** (95.8%) keys and aliases in seeds (so `alias/my-app` exists before the app starts), and `awsemu kms ls`. `seed import --profile` reads aliases and key policies (never key material).
- ⬜ **EventBridge Scheduler** (94.6%) and **Pipes** (93.9%) under `awsemu events`: `schedules ls`, `pipes ls`, and both in seeds, `describe` and `check`.
- ⬜ **SES v2** (81.0%) and **SES** (93.0%): verified identities in seeds, and `awsemu ses sent [--to ADDR] [--follow]` to see the mail your code sent, if the emulator keeps sent messages in a readable form (check first; otherwise the proxy log can show them).
- ⬜ **AppConfig** (98.1%, data plane 100%): applications, profiles and hosted versions in seeds, and `awsemu appconfig get APP ENV PROFILE` to read what the app would see.
- ⬜ **Firehose** (95.3%): delivery streams in seeds and `overview`, and `awsemu firehose put` with `--file`, like `kinesis put`.

**Then: data, containers and infrastructure, by demand**

- ⬜ **CloudFormation**: `awsemu stack deploy TEMPLATE`, `stack events NAME --follow`, `stack outputs NAME`. Its score is low (18.9% single-service, 715 open issues, and several "stack reports completion but provisions nothing" cases), so the command must check what a stack really created and say so, and `check` should warn about resource types known to be missing. Until it's better, seeds stay the recommended way to create state.
- ⬜ **ECR** (90.4%) and **ECS** (86.2%): `awsemu ecr login` (Docker credentials for the local registry, if the emulator serves the registry API) and `ecs ls`.
- ⬜ **Athena** (91.5%) and **Glue** (86.1%): `awsemu athena query SQL` with results as a table, and Glue databases and tables in seeds.
- ⬜ **RDS** (73.8%) and **RDS Data API** (82.2%), **ElastiCache** (85.7%): only `overview`/`describe` support until the scores improve; say in `check` what doesn't work.
- ⬜ **ACM** (97.3%), **Route 53** (90.0%), **CloudWatch metrics and alarms** (95.8%), **X-Ray** (93.4%), **S3 Tables** (98.5%) and **S3 Vectors** (98.8%): seed sections and `overview`/`describe`, no new commands unless asked.
- ⬜ **Bedrock runtime** (64.7%) and **Bedrock Agent runtime** (94.3%): find out what the emulator answers to InvokeModel and Converse (no real model runs locally), and document what you can test with it (request shapes, errors, throttling via proxy faults) and what you can't.

**For every new service**

- ⬜ `check` knows its operations' fidelity, the proxy's cost estimate has its prices, `iam policy` covers it, `seed import --profile` reads it (read-only, with the same care for secrets), and the MCP server exposes it.
- ⬜ Real-emulator tests for each command in CI, like the existing services.
- ⬜ A `docs/services.md` section per service, with what the emulator does not support yet and a link to the score.

## v0.16 — More services: APIs, search, streaming and AI

Goal: the next group of services, taken from the "ideas" list, with the same treatment as v0.15 (commands, seeds, `overview`, `describe`, `watch`, the UI, completion, `check`, IAM, cost, `seed import`, MCP, real-emulator tests and docs). Scores are single-service tests passed for emulator v1.0.629.

- ⬜ **AppSync** (88.4%): `awsemu appsync ls` and `appsync query API 'GRAPHQL' [--vars JSON]` to run a query or mutation against the local API, with the API key or a Cognito token from v0.15. APIs, schemas and resolvers in seeds.
- ⬜ **OpenSearch** (83.8%) and **OpenSearch Serverless** (97.6%): domains and collections in seeds and `overview`. Find out whether the emulator serves the search data plane (index, search) or only the control plane, and say so; only then add `awsemu search query`.
- ⬜ **MSK (Kafka)** (80.3%) and **MSK Connect** (100%): clusters in `overview`/`describe`. Find out whether brokers really run (bootstrap brokers you can connect to); if they do, `awsemu kafka produce/consume`.
- ⬜ **IoT Core** (69.2%; data plane 96.2%, jobs 94.4%): things, policies and certificates in seeds, and `awsemu iot publish TOPIC` / `iot subscribe TOPIC --follow` on the data plane. The low control-plane score goes into `check`.
- ⬜ **Step Functions activities** (sfn is 93.9%, already covered): `awsemu sfn activity work ARN --run CMD`, a local activity worker that runs a command per task, to test activity-based state machines without writing a worker.
- ⬜ **Lex v2** (models 84.6%, runtime 100%): `awsemu lex say BOT 'text'` to talk to a bot from the terminal.
- ⬜ **AI services**: Polly (96.9%), Comprehend (81.0%), Rekognition (77.4%), Textract (66.7%), Translate (60.0%). No real models run locally, so first document what each answers (fixed or shaped responses, errors) and what you can test with it (request shapes, error handling, retries with proxy faults). Commands only if there's demand.

## v0.17 — More services: the rest of a typical account

Goal: the services found in a typical AWS account that v0.15 and v0.16 don't cover, mostly as seed sections and `overview`/`describe`/`check` support, with new commands only where awsemu adds something over `call`. Same evidence as above.

**Cross-service views (most value first)**

- ⬜ **Cloud Control API** (94.1%): try using it as a generic backend for `describe` and `overview`, so any resource type it knows gets listed without per-service code.
- ⬜ **Resource Groups Tagging API** (85.2%) and **Resource Groups** (100%): `awsemu tags [KEY=VALUE]`, every resource with a tag across services, and tags checked by `seed apply`.
- ⬜ **STS** (90.9%): `awsemu whoami`, and `awsemu assume ROLE` that exports temporary credentials, to test code that assumes roles (the emulator doesn't enforce IAM, so say what that does and doesn't prove).
- ⬜ **CloudTrail** (95.0%): `awsemu trail` to show the management events the emulator records, next to the proxy's calls.

**Networking, compute and edge**

- ⬜ **EC2 networking** (EC2 70.9%): VPCs, subnets, security groups and endpoints in seeds, because Terraform and CDK projects create them before anything else. Instances only in `overview`; the low score goes into `check`.
- ⬜ **Elastic Load Balancing v2** (90.7%), **Auto Scaling** (88.3%), **EKS** (84.3%), **Batch** (92.3%), **Elastic Beanstalk** (83.0%): `overview`/`describe` and seeds.
- ⬜ **CloudFront** (88.8%; KeyValueStore 0%), **WAFv2** (93.1%), **Route 53 Resolver** (96.1%), **Cloud Map** (98.9%): seeds and `describe`; `awsemu dns ls` for Route 53 (v0.15) and Cloud Map together.

**CI/CD**

- ⬜ **CodeBuild** (95.3%), **CodePipeline** (95.1%), **CodeDeploy** (96.9%), **CodeCommit** (85.9%), **CodeArtifact** (86.0%): seeds and `describe`, and `awsemu pipeline runs NAME` with the stage status. Check first whether builds and pipeline runs actually execute.

**Identity and authorization**

- ⬜ **Verified Permissions** (100%): `awsemu avp check --principal --action --resource`, to test Cedar policies locally. Policy stores and policies in seeds.
- ⬜ **IAM Identity Center** (SSO admin 92.1%, Identity Store 100%) and **Private CA** (99.3%): seeds and `describe`.

**Data, analytics and databases**

- ⬜ **DynamoDB Streams** (93.3%): `awsemu ddb stream TABLE --follow`, to see the change records a table emits (part of the existing `ddb` group).
- ⬜ **Redshift** (94.9%) and the **Redshift Data API** (100%): `awsemu redshift query SQL`, like Athena's in v0.15.
- ⬜ **EMR** (90.2%), **EMR Serverless** (90.6%; job runs are recorded but not executed), **Managed Flink** (96.9%), **MWAA** (100%), **Kinesis Video** (100%): `overview`/`describe` and seeds.
- ⬜ **Keyspaces** (83.3%), **DocumentDB Elastic** (95.7%), **Neptune Analytics** (97.7%), **MemoryDB** (73.0%), **Amazon MQ** (77.1%): `overview`/`describe`; find out which of them run a real data plane.
- ⬜ **SageMaker** (85.1%): `overview`/`describe` only.

**Storage, governance and observability**

- ⬜ **EFS** (94.9%), **EBS direct APIs** (100%), **Backup** (69.4%), **Data Lifecycle Manager** (97.1%): seeds and `describe`.
- ⬜ **Config** (90.9%), **GuardDuty** (96.4%), **Security Hub** (82.8%), **CloudWatch Synthetics** (87.1%), **RUM** (90.8%), **Budgets** (94.4%): `overview`/`describe`.

**Wait until the scores improve**

- ⬜ Service Quotas (25.3%), Lake Formation (31.2%), Database Migration Service (35.0%), Redshift Serverless (46.7%), CloudFront KeyValueStore (0%): no commands yet; `check` warns when a project uses them. Look again with each new scores release (`awsemu fidelity --compare`).

## v0.18 — More services: recommended gaps

Goal: services that a review of all 438 service models in the emulator (and the 351 with fidelity tests) found commonly used, worth having, and not planned in v0.15 to v0.17. Same treatment and same evidence as above.

- ⬜ **Application Auto Scaling** (98.6%): scalable targets and policies for DynamoDB, Lambda concurrency and ECS in seeds and `describe`, so infrastructure that sets them up applies cleanly.
- ⬜ **Transfer Family** (81.4%): SFTP servers and users in seeds. Find out whether the emulator serves the SFTP endpoint itself; if it does, `awsemu sftp USER` to test file drops into S3 from the terminal.
- ⬜ **Aurora DSQL** (78.7%) and **DAX** (92.6%): clusters in `overview`/`describe`; find out whether they serve a data plane you can connect to.
- ⬜ **IAM Access Analyzer** (85.7%): use its policy validation in `awsemu iam policy --validate` and `check --iam`, so the policies we generate are checked the way AWS checks them.
- ⬜ **Price List API** (92.7%): find out whether it returns usable prices; if it does, `proxy cost` stops shipping its own price table.
- ⬜ **Resource Explorer** (92.6%): try it as another backend for a cross-service `awsemu find TEXT`, next to the Cloud Control and tagging work in v0.17.
- ⬜ **Organizations** and **IAM Identity Center** login (SSO OIDC, 90.9%): find out how far the emulator goes, for code that reads the account structure or signs in with SSO.
- ⬜ **ECR Public** (95.1%), **Signer** (91.8%, Lambda code signing), **IAM Roles Anywhere** (97.2%), **Network Firewall** (88.1%), **Image Builder** (88.9%), **Lightsail** (89.2%), **Amplify** (83.3%), **Serverless Application Repository** (71.4%), **SWF** (94.7%): seeds and `overview`/`describe`.
- ⬜ **Location Service** (places 96.3%, routes 86.5%, maps 64.3%): `awsemu geo search 'text'` and `geo route A B` to see what the emulator answers.
- ⬜ **Transcribe** (91.2%), **SageMaker runtime** (90.4%), **Personalize runtime** (100%), **Bedrock Data Automation** (100%) and **Bedrock AgentCore** (control 83.6%, runtime 75.0%): like the AI services in v0.16, first document what they answer without real models, then commands by demand. AgentCore matters for people building agents, who are also the MCP server's users.
- ⬜ **IoT SiteWise** (99.1%), **Greengrass v2** (97.5%) and **IoT TwinMaker** (100%): seeds and `describe`, after IoT Core in v0.16.
- ⬜ Watch list, not ready (score under 40%): S3 Control and access points (34.8%), Route 53 Global Resolver (37.5%), Storage Gateway (0%), Transcribe streaming (0%), Application Insights (27.3%). `check` warns when a project uses them.

## v0.19 — Features: the local development loop

Goal: make the daily loop (edit, run, look, fix) faster than against a real account.

- ⬜ **`awsemu dev`**: one command, configured in `awsemu.toml`, that starts the emulator, applies the seed, starts the proxy, watches Lambda folders and state machine and rule files, and shows calls and logs in one screen; Ctrl+C stops everything.
- ⬜ **Partial reset**: `awsemu reset [SERVICE|RESOURCE]` empties queues, buckets or tables (and reapplies the seed for them) without restarting the emulator, in well under a second.
- ⬜ **Sample events**: `awsemu event sample s3-put|sqs|ddb-stream|api-gw|eventbridge|sns|cognito-trigger [--set key=value]` prints a realistic event, and `lambda invoke NAME --event s3-put` uses it.
- ⬜ **Lambda**: Node, Java and Go packaging in `lambda deploy` (today Python), layers, container-image functions, environment from `.env`, and `lambda deploy --debug` to attach a debugger (debugpy, Node inspector).
- ⬜ **Hot reload** for Step Functions definitions (`sfn deploy FILE --watch`), EventBridge rules and API Gateway OpenAPI files.
- ⬜ **`awsemu s3 sync DIR s3://bucket --watch`**, for static sites and front ends served from S3.
- ⬜ **Follow a request across services**: `awsemu trace` joins the proxy's calls, CloudWatch Logs and Step Functions history into one timeline (S3 upload → event → Lambda → queue → consumer), from the "event sourcing" idea.
- ⬜ **Fake data**: `seed generate TABLE --rows 1000 --from-schema FILE` fills tables, buckets and queues with realistic fake data, for UI work and load tests.
- ⬜ **DynamoDB**: `ddb import/export` (CSV and JSON lines), `ddb query` with key conditions written in a simple syntax, and an item editor in the UI.
- ⬜ **A web UI**: `awsemu ui --web` serves the same views as the terminal UI on localhost (resources, calls, logs, faults), for people who prefer a browser.
- ⬜ **Infrastructure as code**: `awsemu tf` and `awsemu cdk` wrappers that point Terraform and CDK at the emulator (provider and endpoint overrides, bootstrap), and `seed from-terraform STATE`, `seed from-cdk cdk.out` and `seed from-sam template.yaml` to start from what your IaC describes.
- ⬜ **Examples when something goes wrong**. Today an error is one line plus a hint, and only `call`, settings and seeds suggest close names. Built on the error hierarchy of v0.14:
  - **Usage errors** (a missing argument, an unknown option, a bad value) print two or three examples of that command right under the error. The examples live once, in each command's docstring, and are also shown in `--help` and the generated reference; CI runs them against the real emulator so they never go stale.
  - **Runtime errors** come with an example that fixes them: emulator not running → `awsemu start`; a missing bucket, queue or table → the `ls` that shows what exists and the command that creates it; a wrong seed section → a correct YAML snippet for that section; a bad fault rule → valid rules close to what was typed; an AWS validation error from `call` → a skeleton of the right parameters built from the service model (also as `awsemu call SERVICE OPERATION --example`).
  - **"Did you mean"** everywhere: commands, options, service names, and the names of resources that exist in the emulator ("no queue 'order', did you mean 'orders'?").
  - **`awsemu examples [COMMAND|TOPIC]`**: browse examples and short recipes from the terminal ("seed a table", "inject throttling", "test a Lambda").
  - **For scripts and agents**: errors in `--json` mode carry an `examples` field (in the JSON Schema) and a stable error code (`AWSEMU-E012`) that links to its entry in `docs/troubleshooting.md`; the MCP server returns the same, so an agent can fix its own call.
  - Examples go to standard error, never mix with `--json` output, and can be turned off (`AWSEMU_NO_HINTS=1` or `hints = false` in the settings). A test checks every error type has at least one example.
- ⬜ **Other ways to run it**: Podman as well as Docker; a remote emulator (`awsemu connect HOST:PORT` for one running on another machine or in a cluster); a Helm chart and a `kind` guide for Kubernetes.

## v0.20 — Features: testing, CI and safety

Goal: tests that catch more, CI that explains failures, and fewer surprises when moving to AWS.

- ⬜ **IAM enforcement in the proxy**: `proxy start --enforce-iam POLICY.json` denies the calls a policy wouldn't allow (`AccessDenied`, like AWS), evaluated locally (actions, resources, conditions we can evaluate), so you find missing permissions before deploying. The emulator itself doesn't enforce IAM.
- ⬜ **API coverage**: `awsemu coverage` lists which AWS operations your test suite used (from the proxy log), and which of the operations your code calls (from `check`) no test exercises.
- ⬜ **Parallel tests**: pytest-xdist support (one emulator per worker, or one shared emulator with a resource prefix per worker) and a guide for parallel Jest and JUnit.
- ⬜ **Snapshots between tests**, from the ideas list: restore a snapshot instead of restarting (`aws_emulator_fresh` takes seconds), and `awsemu snapshot diff A B` to see what a test changed.
- ⬜ **Chaos profiles**: `proxy start --chaos light|heavy` adds random throttling, timeouts and 5xx answers at a rate you choose, with a seed to replay the same run.
- ⬜ **Latency profiles**: add the latency of a real region (or a slow network) to every call, to test timeouts.
- ⬜ **Record on AWS, replay locally**: record a session against a real account with shadow mode, then replay it against the emulator as a regression test (`proxy calls --as-pytest`, from the ideas list).
- ⬜ **A CI report**: the GitHub Action writes a job summary with the calls, the faults injected, the operations covered and the emulator's errors, and uploads the HAR file when a job fails.
- ⬜ **Bug reports upstream**: `awsemu issue draft CALL` writes a minimal reproduction (the request, the emulator's answer, what AWS answers, versions) for an issue in AWS Emulator's repository.
- ⬜ **A reproduction bundle**: `awsemu bundle` packs the seed, a snapshot, the settings and the proxy log into one file a teammate opens with `awsemu bundle open`.
- ⬜ **Secrets in seeds**: warn when a seed, snapshot or HAR file holds what looks like a real secret or real account ID before it's committed (and a pre-commit hook).
- ⬜ **Observability**: export proxy calls as OpenTelemetry spans, a Prometheus endpoint with per-operation counts and latencies, and `awsemu top` for live rates.
- ⬜ **More for agents**: MCP resources (seeds, snapshots, the call log) and prompts ("why does this call fail?"), and one emulator per agent session so agents don't step on each other.

## v0.21 — Coming from LocalStack

Goal: someone with a LocalStack setup moves to AWS Emulator in minutes, without rewriting scripts.

- ⬜ **Drop-in commands**: `awslocal`, `tflocal` and `cdklocal` equivalents (installed as `awsemu-awslocal` and friends, or as the original names with `awsemu shims install`) that point the AWS CLI, Terraform and CDK at the emulator.
- ⬜ **`awsemu migrate localstack`**: reads `docker-compose.yml`, `LOCALSTACK_*` and `SERVICES`/`PERSISTENCE` variables and init hooks (`/etc/localstack/init/ready.d`), and writes `awsemu.toml`, a seed and the matching `compose` service; it prints what has no equivalent.
- ⬜ **Compatible environment**: honour `LOCALSTACK_HOST`, `AWS_ENDPOINT_URL` and `localhost.localstack.cloud`-style hostnames where it is cheap to do, with a warning that says the awsemu way.
- ⬜ **A migration guide** in the docs: a table of services and features with their equivalent (or "not yet"), from the fidelity scores, and the differences in behaviour that matter (ports, TLS, persistence, IAM).

## v1.0 — Stable distribution

Goal: install and upgrade anywhere with one command.

- ⬜ **Final name, right before publishing.** "aws-emulator-cli" uses the AWS trademark; for an unofficial project on PyPI and Homebrew it may cause problems or be mistaken for something official. Choose the name, check it's free on PyPI, Homebrew and GitHub, apply it with the v0.7 script and publish straight away, so nobody takes it in between.
- ✅ Automatic GitHub releases from `CHANGELOG.md` (wheel and sdist attached).
- ⬜ Publishing on **PyPI** (`pipx install <name>`).
- ⬜ Publishing the **Testcontainers modules** on Maven Central and npm, with the final name (today `io.github.skaidan:aws-emulator-testcontainers` and `aws-emulator-testcontainers`, which `scripts/rename.py` doesn't change: they don't carry the package name).
- ⬜ A **Homebrew tap** and standalone binaries (PyInstaller) for those without Python.
- ⬜ A **prebuilt Docker image** (multi-arch, on GitHub Container Registry), one tag per emulator version, so macOS and Windows users don't build it themselves. The emulator's source is CC0 (Apache 2.0 in `vendor/`); check the license and notice files in AWS's package before redistributing it.
- ⬜ **Upgrade notes** for each release in the docs, and a "what changed for me" summary when upgrading awsemu itself.
- ⬜ Semantic versioning and a stability promise (the output is fixed in v0.7).
- ✅ Documentation in `docs/`: getting started, services, testing and CI, troubleshooting, architecture and a reference generated from the code.
- ⬜ **Security of awsemu itself**: a threat model for the proxy, its admin token, `--host`, shadow mode and `seed import` against real accounts (in SECURITY.md); fuzzing of the parsers and of requests to the proxy; `pip-audit`/OSV in CI; releases signed with Sigstore on top of the build attestation.
- ⬜ **Hard environments**: install without network from a downloaded bundle (wheels plus the emulator), corporate proxies with their own CA (`HTTPS_PROXY`, `SSL_CERT_FILE`, `--ca-bundle`), Linux ARM and Windows ARM in the CI matrix, and rootless containers (Docker rootless, Podman).
- ⬜ **Performance budgets in CI**: fail the build when startup, `awsemu --version`, `env` or the proxy's added latency get more than 10% worse than the last release, so what v0.14 gains isn't lost.
- ⬜ A documentation website (MkDocs) with guides: "integration tests with pytest", "CI with GitHub Actions" and "Node and Java against the emulator".

---

## Ideas without a version

- Several regions: the emulator supports one region per instance, so `awsemu` could manage a group of instances, one per region.
- A named AWS CLI profile (`--profile emulator`) as an alternative to exporting variables.
- **Editor integration**: a VS Code extension (start/stop, resources, calls) on top of the JSON output and the MCP server.
- **A dev container feature** that installs the emulator and awsemu, for Codespaces and dev containers.
- **More services after v0.18**, by demand, with the fidelity scores to decide.
- **Shell integration**: a prompt segment (Starship, Oh My Zsh) showing whether the emulator is running and on which port, and man pages.
- **Output formats**: `--output yaml|csv` next to the table and `--json`.
- **Time travel**: a fake clock (if the emulator gets one) to test TTLs, schedules, retention and expirations without waiting.
- **Teams**: shared presets in a company repository (`awsemu preset use acme/web`) with seeds, settings and fault profiles.
- **Example apps**: a repository of small apps tested with awsemu in CI (a serverless API with Cognito, an S3 → Lambda → SQS event pipeline, a Terraform project), and short recipes in the docs ("test an SQS consumer", "test a Lambda fed by DynamoDB Streams").
- **After 1.0**: a fixed release rhythm, how long each minor gets fixes, which emulator versions are supported and for how long, and a written privacy promise (awsemu sends no telemetry).
- **Community**: a maintainers' guide, "good first issue" labels tied to the service registry (adding a service as the typical first contribution), roadmap voting with issue reactions, and GitHub Discussions.
- **Accessibility of the terminal UI**: a high-contrast theme, full use without colours (`NO_COLOR`), and checking it with screen readers.
- **Plugins**: let other packages add `awsemu` commands (entry points), for company-specific workflows.
- **Docs in other languages**, starting with Spanish, once the English docs are stable.
- **Other local emulators as backends**: run the same commands, seeds, proxy and pytest fixtures against LocalStack, Floci, MiniStack or moto, and compare how they answer your own calls. It would only be worth it if people ask; the project is built around AWS Emulator.
- **Rust embedded mode**: AWS's emulator can also run inside a Rust test binary. A guide on when to use it and when awsemu (other languages, Docker, shared instances) fits better.

Have an idea or need something sooner? Open an issue.
