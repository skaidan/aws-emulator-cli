# Will my project work with the emulator?

The emulator doesn't behave exactly like AWS everywhere yet, and AWS publishes where it doesn't: every release comes with the results of its [fidelity tests](https://github.com/aws/aws-emulator-evaluation-suite), including the ones that fail. These commands use that data to answer three questions before they cost you a debugging session:

| Question | Command |
| --- | --- |
| Which known differences affect the code I have? | `awsemu check` |
| What would upgrading the emulator change for me? | `awsemu fidelity --compare VERSION --mine` |
| How does my whole team (and CI) use the same version? | `awsemu install VERSION --pin` |
| What does AWS already know is wrong in a service? | `awsemu issues SERVICE` |

## `awsemu check`

Reads your project, finds the AWS operations it calls and the infrastructure it defines, and looks them up in the fidelity tests of your emulator version:

```bash
awsemu check                    # this folder
awsemu check src infra          # just these
awsemu check --release latest   # would the latest release be better?
awsemu check --all              # every known difference, not the first 3 per operation
awsemu check --strict           # exit code 1 if there are known differences (CI)
awsemu check --json             # for scripts (format: scripting.md)
awsemu check --from-calls       # what your tests really called, from the proxy's log
awsemu check --iam              # IAM actions your code needs that your policies don't grant (iam.md)
```

Try it with the example in this repository: `awsemu check examples/check-demo`. Real output, for release v1.0.471, the fidelity tests v1.0.0, and v1.0.611 as the latest release (the tests and numbers change with each release):

```
release         v1.0.471
fidelity tests  v1.0.0
scanned         2 file(s): python, terraform

Operations your code calls
operation                    tests  passed  differences  other failing  used in
---------------------------  -----  ------  -----------  -------------  ------------
dynamodb:GetItem             925    696     11           218            orders.py:18
dynamodb:TransactWriteItems  104    94      2            8              orders.py:10
sqs:SendMessage              527    410     1            116            orders.py:14

dynamodb:GetItem: 11 known difference(s)
  ✗ ddbval-nesting-depth-over-32-levels-rejected  fails here (step 7/15): AWS 200, emulator 400 ValidationException
      ↳ fixed in v1.0.611: awsemu install latest
  ✗ ddbval-reserved-keyword-in-projection-rejected  fails here (step 7/9): AWS 200, emulator 400 ValidationException
      ↳ fixed in v1.0.611: awsemu install latest
  ✗ dynamodb-attributes-to-get-duplicate-or-empty-rejected-on-reads  fails here (step 6/13): same 400 ValidationException, different response body
      ↳ known issue (HIGH): DynamoDB ValidationException envelope diverges: member paths, value rendering and error aggregation
        https://github.com/aws/aws-emulator/blob/main/issues/things-that-do-not-work/20261120T225636Z-dynamodb-validationexception-envelope-diverges-member-paths-value-rendering.md
  … 8 more (--all)
dynamodb:TransactWriteItems: 2 known difference(s)
  ✗ dynamodb-transact-duplicate-set-members-rejected  fails here (step 6/15): same 400 ValidationException, different response body
      ↳ fixed in v1.0.611: awsemu install latest
  ✗ dynamodb-transact-write-items-rejects-exponent-overflow-number  fails here (step 4/16): same 400 ValidationException, different response body
      ↳ fixed in v1.0.611: awsemu install latest
sqs:SendMessage: 1 known difference(s)
  ✗ sqs-message-send-receive-delete  fails here (step 7/11): same 400 QueueDoesNotExist, different response body
      ↳ fixed in v1.0.611: awsemu install latest

Services
service   found in           service tests  via CloudFormation  infrastructure
--------  -----------------  -------------  ------------------  ----------------------------
dynamodb  python, terraform  1172/1481                          aws_dynamodb_table (main.tf)
sqs       python, terraform  284/335                            aws_sqs_queue (main.tf)

! 3 of 3 operation(s) you use have known differences (14 failing test(s)).
10 of them pass in the latest release, v1.0.611: upgrading fixes them (awsemu fidelity --compare latest --mine).
5 of them are explained by an open issue of the emulator (awsemu issues SERVICE to browse them).
Tests: https://github.com/aws/aws-emulator-evaluation-suite · details: awsemu fidelity SERVICE --failures · every difference: --all
```

### What it reads

Nothing is run: it reads the files.

| Source | What it recognises |
| --- | --- |
| Python | `boto3`/`aioboto3` clients and resources (`client("dynamodb")`), method calls (`put_item(...)`), `get_paginator("query")` |
| JavaScript / TypeScript | SDK v3 (`@aws-sdk/client-*`, `new PutItemCommand(...)`, `@aws-sdk/lib-dynamodb`), SDK v2 (`new AWS.DynamoDB()`, `DocumentClient`) |
| Java / Kotlin | SDK v2 and v1 imports, `PutItemRequest`, `putItem(...)` |
| Go | SDK v2 and v1 imports, `client.PutItem(...)`, `PutItemInput` |
| Terraform | `resource` and `data` blocks `aws_*` |
| CloudFormation / SAM | `Type: AWS::...` in `.yaml`, `.yml`, `.json` and `.template` files |
| CDK | `aws-cdk-lib`/`aws_cdk` modules (Python, TypeScript, Java, Go) |

It skips `node_modules`, virtual environments, `.terraform`, `cdk.out`, build folders and files over 2 MB.

A method name only counts when it's a real operation of a service the file uses. If a file calls methods on a client created somewhere else (`self.table.put_item(...)`), it's matched against the services the rest of your code in that language uses. That's a heuristic: it can miss a call made in an unusual way, or count a method that happens to share its name with an operation. `--json` gives the file and line of each one, so you can check.

### From the calls your tests made

`--from-calls` skips the scan and reads what the [proxy](proxy.md) logged instead: only the operations your code really sent, whatever language made them and however it built the client. Run the tests through the proxy first, then check:

```bash
awsemu proxy start -d
awsemu exec --proxy -- pytest            # or npm test, mvn test… (or proxy = true in awsemu.toml)
awsemu check --from-calls                # the proxy's log for --port
awsemu check --calls-file calls.jsonl    # a log copied from elsewhere (a CI artifact, say)
```

Each operation's "used in" says `calls.jsonl:<id>`, the first call to it in the log. Operations that were called but that no fidelity test knows are listed as having no tests. It finds only what the tests exercised: a code path they don't run isn't checked, which the static scan would have found. Infrastructure (Terraform, CloudFormation) is seen as the API calls it makes, if it went through the proxy.

### What counts as a known difference

For each operation your code calls, `check` looks at every fidelity test that calls it, and **lists** a failing test when either:

- **it fails at that operation** ("fails here"): the test's results say which call didn't match AWS, and it's yours. You also see what AWS answered and what the emulator answered;
- **it only calls operations you call too** ("calls only operations you use"): it's close to what your code does, even if the results don't say which step failed.

Other failing tests that merely include the operation, often to set something up, are only **counted** (`other failing`). Tests passing the operation many times are the reassuring part: `tests` and `passed`.

Operations with no fidelity tests yet are listed at the end: nothing is known about them, good or bad.

For infrastructure, the **Services** table gives each service's score and, when you deploy with CloudFormation, SAM or CDK, how the tests that deploy that service **through CloudFormation** do. Terraform has no fidelity tests of its own: use the service score.

### What explains each difference

Under each known difference, `check` adds what it can find out:

- **`↳ fixed in v1.0.611`**: the test passes in the latest release. Upgrading fixes it (`awsemu install latest`, or `--pin` it for the team). With release v1.0.471, 10 of the 14 differences in the example are fixed in v1.0.611.
- **`↳ known issue (HIGH): …`**: the emulator's own issue that explains it. AWS keeps one file per known gap in the [emulator repository](https://github.com/aws/aws-emulator/tree/main/issues). Each says what AWS does, what the emulator does and how it should be fixed. Follow the link, or open it with `awsemu issues --show`.

The summary counts both. A difference with neither is new or untracked: worth [reporting](https://github.com/aws/aws-emulator/issues), with the request you sent, the response you got and the one AWS returns.

These lookups download the latest release's scores (once) and the first part of the issue files of the services involved, which are cached by their content. `--no-explain` skips them, for example offline or in a CI job where you only need `--strict`.

### Where the data comes from

- The test results: `scores.json.gz` of the release, as in `awsemu fidelity`.
- Which operations each test calls: `manifest.jsonl` of the [fidelity tests repository](https://github.com/aws/aws-emulator-evaluation-suite), at the version the release names in its notes; when it doesn't name one (the case so far), the newest published version (a `vX.Y.Z` tag, today `v1.0.0`), and `main` if that can't be looked up. Tests added since only show up in later releases, so the newest version is the closest match. Pick another with `--manifest v1.0.0`, or use a file from a clone with `--manifest path/to/manifest.jsonl`.
- Both are cached in `~/.aws/emulator-cli/fidelity/` (`main` is refreshed once a day; `--refresh` forces it).
- The release: `--release`, else `emulator_version` in your `awsemu.toml`, else the emulator you have installed, else the latest.

### In CI

```yaml
- run: awsemu check --strict
```

`--strict` makes known differences fail the job (exit code 1). Without it, `check` only reports and exits 0. A good moment to run it: when you add a new AWS operation, or before you upgrade the emulator.

## `awsemu issues`

The emulator's own list of known gaps, from [AWS's issue files](https://github.com/aws/aws-emulator/tree/main/issues): about 3,800 open (`things-that-do-not-work`) and 20,000 fixed (`things-that-now-work`).

```bash
awsemu issues dynamodb                          # open issues about DynamoDB, most severe first
awsemu issues dynamodb:TransactWriteItems sqs   # one operation (globs work: dynamodb:Transact*)
awsemu issues --mine --severity high            # the services this project uses; HIGH and CRITICAL
awsemu issues s3 --search multipart
awsemu issues --show 3                          # row 3 of the last listing, in full
awsemu issues lambda --fixed                    # fixed issues, marking those your release still fails
awsemu issues dynamodb --json
```

```
Open issues: sqs
#  severity  since       operation    title
-  --------  ----------  -----------  ------------------------------------------------------------------------------------------
1  HIGH      2026-11-12  SendMessage  lambda__scheduler__sqs: 2 net-new causes — a Scheduler dead-letter message carries the bar
2  HIGH      2026-11-21  SendMessage  3 causes left open by the SQS protocol-layer fix: an anonymous SendMessage never reaches a
```

- An issue is about the services in its file name (`…-lambda-scheduler-sqs-…` is about all three), and its operations come from its `## Operation` section.
- `--fixed` lists fixed issues. Those whose tests still fail in your release (`fails in v1.0.471: yes`) were fixed after it, so upgrading brings the fix.
- `--show` takes the row number of the last listing, a file name or its first characters, or its GitHub URL. It prints the whole issue (rendered Markdown in a terminal).
- The list of files is cached for 6 hours (`--refresh` reads it again). The files are read once and cached by their content. Listing uses two GitHub API calls, so with many runs from one IP, set `GITHUB_TOKEN`.

## `awsemu fidelity run`

The scores are what AWS measured. `awsemu fidelity run` runs the same tests on your machine, against the emulator you have installed: to reproduce a known difference, to check a new emulator version before its scores are published, or to confirm a fix.

```bash
awsemu fidelity run --test dynamodb.update-item-set-list-preserves-element-order
awsemu fidelity run sqs --failing          # the SQS tests that fail in the published scores
awsemu fidelity run s3 --limit 20
awsemu fidelity run lambda --json
```

```
evaluation suite v1.0.1 (scores of v1.0.611)
[1/2] ✓ dynamodb.update-item-set-list-preserves-element-order  passed
[2/2] ✗ sqs.add-permission-over-limit-rejected  failed  (published: pass)
      expected OverLimit, got 200

1 passed, 1 failed, 0 error(s) against your emulator (v1.0.611).
⚠ 1 differ from the published scores of v1.0.611: sqs.add-permission-over-limit-rejected
```

How it runs them, as the [evaluation suite](https://github.com/aws/aws-emulator-evaluation-suite) says to:

- It fetches the suite at the version your release was scored with (a shallow `git clone`, cached in `~/.aws/emulator-cli/fidelity/suite/<version>`), or uses yours with `--suite PATH`.
- It prepares the suite's environment with `uv sync --locked`, the first time; when a selected test imports one of the heavier test packages (CDK, Kafka, OpenSearch…), it adds the suite's `checks` extra, once.
- Each test runs against **its own, fresh emulator** (its own `HOME` and a free port), started from the installed binary and stopped afterwards, with the suite's runner. The runner accepts only a loopback endpoint, signs with the keys that emulator minted and leaves your AWS credentials out; awsemu removes them from its environment too.
- Each verdict is compared with the published score for that test. `(published: pass)` next to a failure means your emulator or your machine differs from AWS's run.

It needs `git`, [`uv`](https://docs.astral.sh/uv/) and the emulator binary (`awsemu install`; Docker isn't supported here). Name services or `--test` ids: the whole suite has tens of thousands of tests and takes hours. Some tests start tools or containers of their own; the runner reports a missing tool as an `error`. The exit code is 1 if a test fails or errors.

## `awsemu fidelity --compare`

What changes between two releases, test by test:

```bash
awsemu fidelity --compare latest --mine        # from your version to the latest, for your services
awsemu fidelity --release 1.0.385 --compare 1.0.390 dynamodb sqs
awsemu fidelity --compare latest --json
```

```
from  v1.0.385 (fidelity tests v1.0.0)
to    v1.0.390 (fidelity tests v1.0.0)

service   v1.0.385   v1.0.390   fixed  regressed  new tests        removed
dynamodb  1172/1481  1190/1481  +32    -6
sqs       284/335    285/336    +11    -2         0 pass / 1 fail

Regressed (passed before, fail now): 8
  dynamodb  dynamodb-create-table-table-throughput-mode-member
  …
Fixed (failed before, pass now): 43
  …
```

- **fixed / regressed:** the same test, failing before and passing now, or the other way round.
- **new tests / removed:** AWS adds tests with each version of the fidelity tests, and retires outdated ones. A new failing test usually isn't a regression: it found a difference that was already there.
- `--mine` picks the services your project uses, found as `awsemu check` does. Without `--mine` or service names, it shows every service that changed.
- The scores of both releases are cached like everything else, so comparing again is instant.

AWS's advice: compare scores only between releases measured with the same version of the fidelity tests. `--compare` warns you when they differ.

## Supported emulator versions

Each awsemu release works with emulator releases from `MIN_EMULATOR` on: today **1.0.290**. Earlier ones, back to the first public release (1.0.250), work too except for one thing: they don't log the `emulator server information` line, which `awsemu start --port 0` (a free port) and the pytest plugin's random ports rely on. A CI job installs exactly that release with `awsemu install` and runs the tests of what awsemu does itself against it (lifecycle, environment, services, proxy, seeds), so the minimum is tested, not guessed. The `real-emulator` job does the same with the latest release.

`awsemu doctor` shows where you stand:

```
emulator support  warn  1.0.400 (supported from 1.0.290); 1.0.629 is out
                        → awsemu install latest
awsemu            ok    0.13.0, the latest
```

It fails if your emulator is older than the minimum. `awsemu start` (with the native binary) says when there's a newer emulator or awsemu, at most once a day, and only on a terminal: never in CI (when `CI` is set), and never with `AWSEMU_NO_UPDATE_CHECK=1`. The answers come from GitHub's releases, cached for a day in `~/.aws/emulator-cli/updates.json`; with `AWSEMU_NO_UPDATE_CHECK=1`, `doctor` uses only that cache and nothing is looked up.

## `awsemu install` and `emulator_version`

AWS publishes every release of the Linux packages by version, and recommends pinning one if new releases change your test results: then a new release only changes them when you decide to upgrade.

```bash
awsemu install --list            # published versions, marking the installed and pinned ones
awsemu install 1.0.385           # install that version
awsemu install 1.0.385 --pin     # … and write emulator_version = "1.0.385" to awsemu.toml
awsemu install                   # the project's pinned version (or the latest)
awsemu install --docker 1.0.385  # build the Docker image aws-emulator:1.0.385 instead
awsemu install 1.0.385 --dry-run # what it would download and run
```

On Linux with `apt` or `rpm`, `install`:

1. downloads the package for your processor from `downloads.aws.com`, and its `.sig`;
2. checks the signature with GnuPG against AWS's signing key, in a throwaway keyring, after checking the key's fingerprint (`98BCF336A3BE53B734E967C52E5BF49BD940F624`). If `gpg` is missing it stops (`--no-verify` skips the check; not recommended);
3. shows what it will run and asks; `-y` skips the question;
4. installs it with `sudo apt-get install --allow-downgrades` or `sudo rpm -U --oldpackage`, so going back to an older version works too.

On macOS, Windows or a Linux without `apt`/`rpm`, it builds the Docker image with that version (the same official recipe as `awsemu image build`, which also takes `--version`).

### What the pin does

With `emulator_version` in `awsemu.toml` (or `[tool.awsemu]`):

- `awsemu start` and `awsemu up` **warn** when the installed emulator is a different version, and `awsemu doctor` shows it with the fix.
- In Docker mode they run the image `aws-emulator:<version>` (unless you set `image`).
- `awsemu fidelity` and `awsemu check` use that release's data by default.
- The [GitHub Action](testing.md#github-actions) installs that version (or the one in its `emulator-version` input).

```toml
# awsemu.toml
emulator_version = "1.0.385"
```

Upgrading as a team then becomes a reviewed change: `awsemu fidelity --compare latest --mine` to see what changes, `awsemu install latest --pin`, run your tests, commit `awsemu.toml`.
