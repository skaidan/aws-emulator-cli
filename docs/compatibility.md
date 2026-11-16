# Will my project work with the emulator?

The emulator doesn't behave exactly like AWS everywhere yet, and AWS publishes where it doesn't: every release comes with the results of its [fidelity tests](https://github.com/aws/aws-emulator-evaluation-suite), including the ones that fail. These commands use that data to answer three questions before they cost you a debugging session:

| Question | Command |
| --- | --- |
| Which known differences affect the code I have? | `awsemu check` |
| What would upgrading the emulator change for me? | `awsemu fidelity --compare VERSION --mine` |
| How does my whole team (and CI) use the same version? | `awsemu install VERSION --pin` |

## `awsemu check`

Reads your project, finds the AWS operations it calls and the infrastructure it defines, and looks them up in the fidelity tests of your emulator version:

```bash
awsemu check                    # this folder
awsemu check src infra          # just these
awsemu check --release latest   # would the latest release be better?
awsemu check --all              # every known difference, not the first 3 per operation
awsemu check --strict           # exit code 1 if there are known differences (CI)
awsemu check --json             # for scripts (format: scripting.md)
```

Try it with the example in this repository: `awsemu check examples/check-demo`. Real output, for release v1.0.471 and the fidelity tests v1.0.0 (the tests and numbers change with each release):

```
release         v1.0.471
fidelity tests  v1.0.0
scanned         2 file(s): python, terraform

Operations your code calls
operation                    tests  passed  differences  other failing  used in
dynamodb:GetItem             925    696     11           218            orders.py:18
dynamodb:TransactWriteItems  104    94      2            8              orders.py:10
sqs:SendMessage              527    410     1            116            orders.py:14

dynamodb:GetItem: 11 known difference(s)
  ✗ ddbval-nesting-depth-over-32-levels-rejected  fails here (step 7/15): AWS 200, emulator 400 ValidationException
  ✗ ddbval-reserved-keyword-in-projection-rejected  fails here (step 7/9): AWS 200, emulator 400 ValidationException
  ✗ dynamodb-attributes-to-get-duplicate-or-empty-rejected-on-reads  fails here (step 6/13): same 400 ValidationException, different response body
  … 8 more (--all)
dynamodb:TransactWriteItems: 2 known difference(s)
  ✗ dynamodb-transact-duplicate-set-members-rejected  fails here (step 6/15): same 400 ValidationException, different response body
  ✗ dynamodb-transact-write-items-rejects-exponent-overflow-number  fails here (step 4/16): same 400 ValidationException, different response body
sqs:SendMessage: 1 known difference(s)
  ✗ sqs-message-send-receive-delete  fails here (step 7/11): same 400 QueueDoesNotExist, different response body

Services
service   found in           service tests  via CloudFormation  infrastructure
dynamodb  python, terraform  1172/1481                          aws_dynamodb_table (main.tf)
sqs       python, terraform  284/335                            aws_sqs_queue (main.tf)

! 3 of 3 operation(s) you use have known differences (14 failing test(s)).
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

### What counts as a known difference

For each operation your code calls, `check` looks at every fidelity test that calls it, and **lists** a failing test when either:

- **it fails at that operation** ("fails here"): the test's results say which call didn't match AWS, and it's yours. You also see what AWS answered and what the emulator answered;
- **it only calls operations you call too** ("calls only operations you use"): it's close to what your code does, even if the results don't say which step failed.

Other failing tests that merely include the operation, often to set something up, are only **counted** (`other failing`). Tests passing the operation many times are the reassuring part: `tests` and `passed`.

Operations with no fidelity tests yet are listed at the end: nothing is known about them, good or bad.

For infrastructure, the **Services** table gives each service's score and, when you deploy with CloudFormation, SAM or CDK, how the tests that deploy that service **through CloudFormation** do. Terraform has no fidelity tests of its own: use the service score.

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
