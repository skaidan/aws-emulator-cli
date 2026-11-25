# Exploring the emulator

Tools to see what's inside the emulator, what's happening, and how far you can trust it for a given service.

| I want to… | Command |
| --- | --- |
| Get a snapshot of what's there | `awsemu overview` |
| Browse services and resources | `awsemu ui` |
| See every API call as it happens | `awsemu watch --calls` ([the proxy](proxy.md)) |
| See live changes while my app works | `awsemu watch` |
| Know how well a service is emulated | `awsemu fidelity` |
| Know whether my project will work, or what an upgrade changes | `awsemu check`, `awsemu fidelity --compare` ([guide](compatibility.md)) |
| See one specific resource | `awsemu describe ARN` |
| Type less | `awsemu completion` |

## `awsemu ui`: terminal UI

An interface to browse the emulator without remembering commands: services and their resources on the left, details of the one you select on the right.

```bash
pipx install 'aws-emulator-cli[ui] @ git+https://github.com/skaidan/aws-emulator-cli'
awsemu ui
```

| Key | Action |
| --- | --- |
| Arrows, Enter | Move, open a service, show a resource |
| `r` | Refresh |
| `w` | Turn auto-refresh on or off (every 5 s) |
| `c` | API calls through [the proxy](proxy.md), live (`e` only errors, `c`/Esc back) |
| `q` | Quit |

What each resource shows:

| Service | Details |
| --- | --- |
| S3 | The first 50 objects (key, size, date) |
| SQS | Every attribute (visible and in-flight messages, DLQ…) |
| DynamoDB | The table description and the first 20 items as plain JSON |
| SNS | Attributes and subscriptions |
| Lambda | The function's configuration |
| Secrets Manager | Metadata and versions; **never the value** |
| SSM | The parameter; `SecureString` values show as `****` |
| Kinesis | Stream summary |
| EventBridge | The bus and its rules |
| Step Functions | The state machine and its latest executions |
| CloudWatch Logs, IAM | The log group, the role |

The UI uses [Textual](https://textual.textualize.io/), installed separately through the `ui` extra so it doesn't add weight for those who don't use it. Without it, `awsemu ui` explains how to install it.

## `awsemu watch`: live changes

Shows what gets created, deleted or changed while your application or your tests work. For example:

```
$ awsemu watch -s sqs -s dynamodb
kind   name    count
queue  orders  0 message(s)
table  users   2 item(s)
Watching dynamodb, sqs every 2s. Ctrl+C to stop.
10:42:03  + queue         orders-dlq
10:42:05  ~ queue         orders  0 → 3 message(s) (+3)
10:42:07  ~ table         users  2 → 5 item(s) (+3)
10:42:09  - queue         temporary
```

- `+` created, `-` deleted, `~` changed. Buckets show their object count (up to 1000), queues their visible messages and tables their items (up to 10,000).
- It watches S3, SQS, DynamoDB, SNS, Lambda, Secrets Manager, SSM, Kinesis, EventBridge (rules) and Step Functions. Choose which with `-s`, the interval with `-i` (default 2 s), and just the initial snapshot with `--once`.
- If a service fails during one look, its last state is kept: a one-off failure doesn't show up as "everything deleted".

**Why it polls instead of showing the calls:** the emulator doesn't log the requests it receives. We checked in CI: even with `RUST_LOG=debug`, its log only shows startup, shutdown and the TLS handshake. So `watch` compares the state every few seconds: you see the effect of the calls, not the calls.

To see the calls themselves, send your code through [the proxy](proxy.md) and use `awsemu watch --calls`:

```bash
awsemu proxy start -d
awsemu exec --proxy -- python app.py
awsemu watch --calls                    # --errors, -s dynamodb, --once
```

## `awsemu fidelity`: how far you can trust each service

With each emulator version, AWS publishes its *fidelity scores*: how many fidelity tests each service passes (tests that compare the emulator's behaviour with real AWS: results, state and exact errors). `awsemu` downloads them **for the version you have installed** and shows them to you:

```bash
awsemu fidelity                       # every service
awsemu fidelity s3 sqs dynamodb       # the ones you use
awsemu fidelity --sort score          # worst to best
awsemu fidelity lambda --failures     # which tests fail and how
awsemu fidelity --release latest      # is the latest version better?
awsemu fidelity --compare latest --mine   # test by test, for the services your project uses
awsemu fidelity s3 --json
```

Sample output (real format; the numbers are illustrative, check yours with the command):

```
release          v1.0.385
emulator commit  813af480bf7f
scored           2026-11-14 18:34:58
your emulator    1.0.385

service   passed   score  multi-service
dynamodb  412/431  96%    37/41
s3        603/688  88%    55/63
```

- **passed / score:** tests that call only that service, the same "k of n" AWS publishes. Tests combining several services are shown separately under **multi-service**.
- **`--failures`:** for each failing test, the operation, what differs (`status`, `errorCode`…), what AWS returned and what the emulator returned. The tests live in the [aws-emulator-evaluation-suite](https://github.com/aws/aws-emulator-evaluation-suite) repository, under `behavioral/<service>/`.
- The release is `--release`, else the `emulator_version` pinned in your `awsemu.toml`, else the installed one (`aws-emulator -v`), else the latest.
- The data is downloaded from the [emulator's GitHub releases](https://github.com/aws/aws-emulator/releases) (`scores.json.gz`, ~1 MB) and cached in `~/.aws/emulator-cli/fidelity/`; `--refresh` downloads it again. If GitHub rate-limits you, set `GITHUB_TOKEN`.
- Compare scores only between releases measured with the same version of the tests: AWS adds new tests and the total grows.

Useful before you start using a service with the emulator, and to know whether a failing test of yours may be due to a known difference. To go from services to the exact operations your code calls, use [`awsemu check`](compatibility.md#awsemu-check); to compare two releases, [`--compare`](compatibility.md#awsemu-fidelity---compare).

## Shell completion

```bash
# bash
echo 'eval "$(awsemu completion bash)"' >> ~/.bashrc
# zsh
echo 'eval "$(awsemu completion zsh)"' >> ~/.zshrc
# fish
awsemu completion fish > ~/.config/fish/completions/awsemu.fish
```

It completes commands and options and, on top of that, **the names of what's in the emulator**:

```bash
awsemu sqs send <TAB>            # your queues
awsemu s3 cat photos/<TAB>       # folders and objects in the bucket
awsemu ddb scan <TAB>            # your tables
awsemu sns subscribe orders --to-sqs <TAB>
```

It works with buckets (and paths inside them), queues, tables, topics, functions, secrets, parameters, streams, state machines and rules, and honours `--port` and `awsemu.toml`. If the emulator isn't running, it simply doesn't suggest names. PowerShell isn't supported.
