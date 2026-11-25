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

## v0.10 — Completing what exists

Goal: close the known gaps in what's already done.

- ⬜ **CI against every new emulator release**: a scheduled job (daily) that installs the latest emulator and runs the real-emulator tests, opening an issue when something breaks. The emulator ships very often (1.0.471 to 1.0.611 in nine days), and today we only find out on our next commit.
- ⬜ **Emulator with auth off**: `awsemu env`/`exec` don't set any credentials when `auth = false` (the emulator writes no credentials file), so the SDKs either fail with "unable to locate credentials" or sign with your real default profile from `~/.aws/credentials`. Set placeholder keys in that case, as `awsemu`'s own clients already do.
- ⬜ **Explain known differences with AWS's own issue files.** The emulator repository tracks every gap it knows in `issues/` (about 3,800 open in `things-that-do-not-work/`, 20,000 fixed in `things-that-now-work/`), each with its severity, the operation, the failing test ids, what AWS does, what the emulator does and the expected fix. Use them:
  - `awsemu check` shows, for each known difference, the issue that explains it, instead of only "fails here";
  - `awsemu issues [SERVICE[:Operation]] [--fixed-since VERSION]` to search them, and to see what was fixed since your emulator version (a reason to upgrade).
- ⬜ **Common setup traps in `awsemu doctor`**: `AWS_ENDPOINT_URL` with `localhost` instead of `127.0.0.1` (the JavaScript, Java and Go SDKs then put the S3 bucket in the host name), real credentials or `AWS_PROFILE` in the environment, a stale `AWS_CA_BUNDLE` from an earlier start, and settings of your own `~/.aws/config` (retries, S3 options) that `AWS_CONFIG_FILE` hides while you use the emulator.
- ⬜ **Seeds with more services**: Lambda functions (from local code), EventBridge rules, Kinesis streams and Step Functions state machines, in `seed export` too.
- ⬜ **`awsemu snapshot save/restore`**: save and restore a whole scenario (the emulator has no snapshots), built on `seed export` and `reset --seed`.
- ⬜ **Infrastructure tools and other languages, tested in CI**: Terraform, CDK, and the Node, Java and Go SDKs against the emulator, with guides and examples. Today only Python is tested.
- ⬜ **A fast Lambda loop**: `awsemu lambda deploy PATH [--watch]` packages local code (Python, Node), creates or updates the function and redeploys on save, so changing a function doesn't mean a zip and three commands.
- ⬜ **`awsemu call SERVICE OPERATION [--params JSON]`**: any API call through boto3, for the services without their own commands and for machines without the AWS CLI (`awsemu aws` needs it).
- ⬜ **Testcontainers modules** (Python, Java, Node): an `AwsEmulatorContainer` built on the Docker image, for teams that start their dependencies with Testcontainers rather than pytest fixtures.
- ⬜ **Proxy, the next step**:
  - fault rules per resource (`dynamodb:PutItem[orders]=throttle`) and over time (`s3=503 for 30s`, an outage that recovers);
  - optional request and response bodies in the calls log (`--bodies`), with secrets and credentials masked;
  - export the calls as HAR, to open them in a browser's developer tools;
  - `awsemu check --from-calls`: check the operations your tests really called (the proxy's log) instead of the static scan, which can miss calls or match a method by its name;
  - `--host 0.0.0.0` and `awsemu compose --proxy`, so containers can go through it too;
  - a token for the admin API (today any local process can change the faults), and a Java truststore for the proxy's certificate;
  - `awsemu report CALL_ID`: a draft GitHub issue for the emulator with what AWS asks for (the request, the emulator's response and what AWS answers), built from the proxy's log, with credentials removed.

## v0.11 — AI agents

Goal: a coding agent tests its code against the emulator without touching AWS.

- ⬜ **`awsemu` MCP server**: tools to start and stop the emulator, apply seeds, query resources, check a service's fidelity and read the proxy's calls.
- ⬜ A guide to use it with agents, alongside the `aws-emulator` *skill* mentioned in AWS's documentation.
- ⬜ **Guard rails for agents**: the MCP tools never use real credentials or a real AWS endpoint, refuse anything that isn't `127.0.0.1`, and say so in their answers, so an agent can't test against a production account by mistake.
- ⬜ **Explain a failure**: given a failing call (from the proxy's log), say whether it matches a known emulator difference (`awsemu check` data) or is probably a bug in the code under test.

## v0.12 — From local to AWS

Goal: what works locally should work on AWS too. The emulator can't promise that for permissions and costs, and it doesn't check IAM like AWS does: some services evaluate policies differently, a request signed with a key it created is never denied, and KMS key policies and S3 bucket policies aren't checked. A missing permission only shows up after deploying.

- ⬜ **Least-privilege IAM from your calls**: `awsemu iam policy` turns the proxy's log of a test run into the IAM policy those calls need (actions, and resource ARNs where they can be known), to compare with what you grant.
- ⬜ **Permissions your infrastructure is missing**: `awsemu check --iam` compares those calls (or the static scan) with the roles and policies in your Terraform/CloudFormation/CDK, and lists actions your code needs that no policy grants. Local tests can't show that today.
- ⬜ **Run the fidelity tests yourself**: `awsemu fidelity run SERVICE [--test ID]` runs tests of the public suite against your local emulator. That reproduces a known difference on your machine, checks a new emulator version before the scores are published, or confirms a fix.
- ⬜ **What it would cost on AWS**: `awsemu proxy cost` estimates, from the calls log and AWS's public prices, what a test run or a workload would cost against a real account (requests, not storage over time). It's an order of magnitude, clearly labelled as an estimate.
- ⬜ **Shadow mode** in the proxy: send read-only calls to both the emulator and a real AWS account you name explicitly, and report where the answers differ. That's your own fidelity test, built from your traffic. Opt-in and read-only, with great care for credentials and costs.
- ⬜ **A seed from a real account**: `awsemu seed import --profile NAME` reads the configuration of an account (tables, queues, topics, buckets without their objects, parameters without SecureString values), read-only and only with a profile you name, and writes a seed, to start locally from something close to your environment.

## v0.13 — Hardening before 1.0

Goal: what a project people depend on needs, beyond features.

- ⬜ **A compatibility matrix**: the oldest emulator version each awsemu release works with, tested in CI with `awsemu install VERSION`, and shown by `awsemu doctor`.
- ⬜ **Static checks in CI**: ruff (lint and format) and mypy on `src/`, and test coverage with a minimum. Fix the warnings that exist today (`tests/test_watch.py`).
- ⬜ **Update notices**: `awsemu doctor` (and, at most once a day, `awsemu start`) says when there's a newer emulator release, or a newer awsemu, without getting in the way in CI.
- ⬜ **Supply chain**: Dependabot for Python dependencies and Actions, pinned Action versions, signed release artifacts with provenance (Sigstore / GitHub attestations), and an SBOM.
- ⬜ **Project health**: `SECURITY.md` (how to report a vulnerability, e.g. in the proxy), issue and pull request templates, a code of conduct, and labels for "good first issue".
- ⬜ **JSON Schemas** for every `--json` output (generated from the contract tests and published with the docs), so scripts can validate what they read.
- ⬜ **A deprecation policy**: how long a flag, setting or JSON field keeps working after it's replaced, and warnings when it's used, written down before 1.0 promises stability.
- ⬜ **Lighter installs**: check whether `boto3` and `cryptography` can become extras (for example, `awsemu start`/`env` without them) without making the common case worse.

## v1.0 — Stable distribution

Goal: install and upgrade anywhere with one command.

- ⬜ **Final name, right before publishing.** "aws-emulator-cli" uses the AWS trademark; for an unofficial project on PyPI and Homebrew it may cause problems or be mistaken for something official. Choose the name, check it's free on PyPI, Homebrew and GitHub, apply it with the v0.7 script and publish straight away, so nobody takes it in between.
- ✅ Automatic GitHub releases from `CHANGELOG.md` (wheel and sdist attached).
- ⬜ Publishing on **PyPI** (`pipx install <name>`).
- ⬜ A **Homebrew tap** and standalone binaries (PyInstaller) for those without Python.
- ⬜ A **prebuilt Docker image** (multi-arch, on GitHub Container Registry), one tag per emulator version, so macOS and Windows users don't build it themselves. The emulator's source is CC0 (Apache 2.0 in `vendor/`); check the license and notice files in AWS's package before redistributing it.
- ⬜ **Upgrade notes** for each release in the docs, and a "what changed for me" summary when upgrading awsemu itself.
- ⬜ Semantic versioning and a stability promise (the output is fixed in v0.7).
- ✅ Documentation in `docs/`: getting started, services, testing and CI, troubleshooting, architecture and a reference generated from the code.
- ⬜ A documentation website (MkDocs) with guides: "integration tests with pytest", "CI with GitHub Actions" and "Node and Java against the emulator".

---

## Ideas without a version

- Several regions: the emulator supports one region per instance, so `awsemu` could manage a group of instances, one per region.
- A named AWS CLI profile (`--profile emulator`) as an alternative to exporting variables.
- **Snapshots per test**: once `snapshot save/restore` exists, restore a snapshot between tests instead of restarting the emulator (`aws_emulator_fresh` takes a few seconds per test).
- **Load and timing**: `awsemu bench` to measure the emulator's latency and throughput on your machine, to size test suites and timeouts.
- **Editor integration**: a VS Code extension (start/stop, resources, calls) on top of the JSON output and the MCP server.
- **A dev container feature** that installs the emulator and awsemu, for Codespaces and dev containers.
- **More services with their own commands**, by demand: API Gateway (call an API locally), Cognito (create test users and tokens), ECS/ECR.
- **Plugins**: let other packages add `awsemu` commands (entry points), for company-specific workflows.
- **Docs in other languages**, starting with Spanish, once the English docs are stable.
- **Tests from your calls**: `awsemu proxy calls --as-pytest` writes a regression test that replays a recorded session (the calls and the answers they got) and checks the emulator still answers the same way, to catch behaviour changes when upgrading.
- **Other local emulators as backends**: run the same commands, seeds, proxy and pytest fixtures against LocalStack, Floci, MiniStack or moto, and compare how they answer your own calls. It would only be worth it if people ask; the project is built around AWS Emulator.
- **Rust embedded mode**: AWS's emulator can also run inside a Rust test binary. A guide on when to use it and when awsemu (other languages, Docker, shared instances) fits better.
- **Event sourcing for debugging**: keep the proxy's log as the sequence of what your code did, and show it as a timeline per resource ("this queue was created by test X, filled by Y, drained by Z").

Have an idea or need something sooner? Open an issue.
