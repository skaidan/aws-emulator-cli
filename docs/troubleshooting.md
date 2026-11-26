# Troubleshooting

Always start with:

```bash
awsemu doctor
```

It checks Python, the binary, Docker and the image, the AWS CLI, boto3, the emulator's state and telemetry. It also looks for the setup traps that quietly break SDK calls in your own shell. Every problem comes with its fix.

| Trap | Why it breaks |
| --- | --- |
| Real credentials or `AWS_PROFILE` in the shell | Your scripts sign with them. `awsemu env`/`exec` unset them, but your own scripts must too. |
| `AWS_ENDPOINT_URL` with `localhost` | The JavaScript, Java and Go SDKs then put the S3 bucket in the host name, which the emulator doesn't serve. Use `127.0.0.1`. |
| `AWS_ENDPOINT_URL` pointing where nothing answers | Usually left from an earlier start on another port. |
| `AWS_CA_BUNDLE` missing, for another port, or not the emulator's | The emulator makes a new certificate on every start, and each port has its own. |
| `HTTPS_PROXY` without `127.0.0.1` in `NO_PROXY` | The SDKs send the emulator's calls to your company proxy. `awsemu env`/`exec` add `127.0.0.1,localhost` to `NO_PROXY` for you. |
| Settings in your `~/.aws/config` (`retry_mode`, `max_attempts`, `s3`…) | While `AWS_CONFIG_FILE` points at the emulator's config, the SDKs don't read yours. `doctor` gives the environment variables that do the same (`AWS_RETRY_MODE`, `AWS_MAX_ATTEMPTS`…), which still apply. |

## Errors when starting

| Message | Cause | Fix |
| --- | --- | --- |
| `Neither the 'aws-emulator' binary nor Docker was found` | There's no way to run the emulator. | Install the package (Linux), set `AWSEMU_BINARY`, or install Docker and run `awsemu image build`. |
| `Docker image 'aws-emulator' not found` | AWS doesn't publish an image. | `awsemu image build` |
| `Something is already listening on 127.0.0.1:9297` | There's already an emulator (or something else) on that port. | `awsemu status --all`, or use `--port`. |
| `The emulator did not become healthy: emulator exited with code N` | The emulator closed while starting. `awsemu` shows the end of its log. | Read those lines. Code 137 in Docker = out of memory: raise `--memory`. |
| `Port 0 doesn't work with Docker` | Docker can't forward a port chosen at startup. | Use a fixed port or `--native`. |
| `An emulator is listening on port N but wasn't started by awsemu` | You started it by hand. | Stop it where it runs (Ctrl+C or SIGTERM). |
| `pid N is still running after 15s` | The emulator doesn't respond to the clean stop. | `awsemu stop --force` (it also deletes the files left behind). |

## Errors when talking to the emulator

`awsemu` adds a specific hint to these errors; here's why they happen.

| Error | Cause | Fix |
| --- | --- | --- |
| `AccessDenied: Sign the request with the emulator credentials` | The request was signed with keys the emulator doesn't accept: your real AWS keys, or those of an earlier run (they change on every start). | `eval "$(awsemu env)"` again, or use `awsemu exec` / `awsemu aws`. Make sure `AWS_ACCESS_KEY_ID` isn't set. |
| `SignatureDoesNotMatch` | The secret key isn't this run's. | The emulator restarted: reload the environment. |
| `InvalidClientTokenId`, `MissingAuthenticationToken` | Unsigned request. | Configure the emulator's credentials, or start it with `--no-auth`. |
| `Unable to locate credentials` with `--no-auth` (awsemu 0.9 and earlier) | The emulator writes no credentials file with auth off, and `awsemu env` set no keys. | Upgrade awsemu: `env`/`exec`/`shell` now set placeholder keys with auth off. |
| `UnknownService` (HTTP 404) | The emulator can't tell which service the request is for: almost always because it isn't signed; otherwise the service isn't emulated. | Sign the request; check [the emulator's issues](https://github.com/aws/aws-emulator/issues). |
| `RequestTimeTooSkewed`, `Signature expired` | Your clock is more than 15 minutes off. | Sync the time (NTP). |
| `UnknownOperationException`, `NotImplemented` | That operation isn't emulated yet. | `awsemu fidelity SERVICE --failures`, and the emulator's release notes. |
| `CERTIFICATE_VERIFY_FAILED` | The emulator creates a new `ca.pem` on every start. | `AWS_CA_BUNDLE` must point to `~/.aws/emulator/<port>/ca.pem` (the path, not a copy). Check the port belongs to the emulator. |
| `Could not connect to the endpoint URL` | Nothing is listening. | `awsemu status`, `awsemu start`. |

## Project settings and tests

| Message | Cause | Fix |
| --- | --- | --- |
| `…/awsemu.toml: unknown setting 'X'` or `'port' must be int` | Error in `awsemu.toml` or `[tool.awsemu]`; it affects every command in that folder. | Fix it (the message suggests the right name) or use `AWSEMU_CONFIG` to point to another file. |
| `awsemu: --awsemu-reuse but no healthy emulator on port N` | The pytest plugin was told to use an emulator that's already running. | `awsemu up` before `pytest`, or drop `--awsemu-reuse`. |
| `awsemu: invalid seed` in pytest | The plugin's seed has errors; nothing is started. | `awsemu seed validate` with the same file. |
| `This action needs a Linux runner` | The GitHub Action only works on Linux. | `runs-on: ubuntu-latest`. |
| Commands use a different port than you expect | An `awsemu.toml` in this folder or a parent, or `AWSEMU_PORT`. | `awsemu config show` tells you which file is used; `--port` always wins. |

## Exploring

| Message / symptom | Cause | Fix |
| --- | --- | --- |
| `The terminal UI needs Textual` | The `ui` extra is missing. | `pipx install --force 'aws-emulator-cli[ui] @ git+https://github.com/skaidan/aws-emulator-cli'` |
| `couldn't reach GitHub` / `rate limit?` in `fidelity` | No connection, or GitHub's limit on anonymous requests. | Retry, or set `GITHUB_TOKEN`. What was already downloaded stays cached. |
| `these scores are for vX, your emulator is vY` | You asked for another release, or there's no binary installed and the latest was used. | `--release` with your version (`aws-emulator -v`). |
| `no proxy is running in front of port N` | `--proxy`, `watch --calls` or `proxy faults` need the proxy. | `awsemu proxy start -d` (same `--port` as the emulator). |
| Calls through the proxy fail with `EmulatorUnreachable` (502) | The proxy is up but the emulator on its port isn't. | `awsemu up`, or check `awsemu --port N proxy …` matches the emulator's port. |
| `certificate verify failed` through the proxy | The SDK trusts the emulator's certificate, not the proxy's. | Use `awsemu exec --proxy` / `env --proxy` (they set `AWS_CA_BUNDLE`); Node: `--sdk node`; Java: `keytool -importcert` or `proxy start --no-tls`. |
| `watch --calls` shows nothing | Your code goes to the emulator directly. | Run it with `awsemu exec --proxy -- …`, or set `proxy = true` in `awsemu.toml`. Calls the emulator makes internally (an S3 event to Lambda) never pass through the proxy. |
| `aws_faults` has no effect | The client was created before the test (at import time or in a session fixture), so it points at the emulator. | Create clients in the code under test, or use `aws_faults.client("…")`. |
| `couldn't list the emulator's issues` in `check` or `issues` | No connection to GitHub, or its API rate limit (60 calls an hour without a token). | Set `GITHUB_TOKEN`; `check --no-explain` skips the lookup. |
| `no manifest.jsonl at '…'` in `check` | That version of the fidelity tests doesn't exist, or GitHub can't be reached and there's no cached copy. | `--manifest main`, or `--manifest path/to/manifest.jsonl` from a clone of the tests repository. |
| `check` finds no operations | It only reads boto3, the JavaScript/Java/Go SDKs, Terraform, CloudFormation/SAM and CDK, and skips `node_modules`, virtual environments and build folders. | Point it at your code (`awsemu check src`). See [what it reads](compatibility.md#what-it-reads). |
| `this project pins emulator X, but Y is installed` | `emulator_version` in `awsemu.toml` differs from `aws-emulator -v`. | `awsemu install` (installs the pinned version), or update the pin with `awsemu install Y --pin`. |
| `gpg isn't installed` in `install` | The package signature can't be checked without GnuPG. | Install `gnupg` (`apt-get install gnupg` / `dnf install gnupg2`). |
| `… doesn't exist` in `install` | No package for that version (or processor). | `awsemu install --list`. |
| `this machine can't install the emulator's Linux packages` | Not Linux, or no `apt`/`rpm`. | `awsemu install --docker`. |
| `watch` doesn't show the API calls | The emulator doesn't log them; `watch` shows their effect on resources. | That's by design; see [Exploring the emulator](explore.md#awsemu-watch-live-changes). |
| Completion doesn't suggest names | The emulator isn't running on that port, or the script isn't loaded. | `awsemu status`; open a new shell after adding `awsemu completion` to your `~/.bashrc`/`~/.zshrc`. |

## Common problems

**My tests reach real AWS.** `AWS_ENDPOINT_URL` wasn't set in the shell running the tests. Use `awsemu exec -- <command>`, or run `awsemu whoami` at the start of the script: it fails if the account isn't `000000000000`.

**S3 fails with `localhost`.** With `localhost`, the JavaScript, Java and Go SDKs put the bucket name in the host (`photos.localhost`) and the emulator doesn't accept it. Use `127.0.0.1`, which is what `awsemu env` exports.

**Operations going to `data-127.0.0.1`.** Some SDKs add a prefix to the host (Cloud Map, synchronous Step Functions, CloudWatch Logs Live Tail). `awsemu env` exports `AWS_DISABLE_HOST_PREFIX_INJECTION=true` (AWS CLI and boto3); in other SDKs you have to turn it off in the client.

**S3 Control doesn't work.** The SDK always puts the account ID in the host. It's a known emulator limitation.

**Node, Java, Rust or .NET don't trust the certificate.** They don't read `AWS_CA_BUNDLE`: `eval "$(awsemu env --sdk node)"` (or `java`, `rust`, `dotnet`).

**My process has to talk to the emulator and to real AWS at the same time.** `AWS_CA_BUNDLE` replaces the trusted certificates. Build a bundle with the system certificates plus `ca.pem`, and rebuild it after every start. `NODE_EXTRA_CA_CERTS` is the exception: it adds instead of replacing.

**`lambda logs` finds nothing.** The emulator doesn't send function output to CloudWatch Logs. Use `awsemu lambda invoke`, which shows the log of that invocation.

**`ParameterPatternMismatchException` in SSM.** Parameter names can't start with `aws` or `ssm` (`/awsapp/...` included), just like in AWS.

**Resources disappear.** That's by design: the emulator keeps everything in memory. Stopping or restarting loses it. Use a [seed](seeds.md): `awsemu start --seed seed.yaml`.

**`seed apply`: "exists with a different key".** The table already exists with another partition or sort key. `apply` never deletes: use `awsemu reset --seed seed.yaml` to start from scratch.

**`seed apply` exits with code 1.** Some resource failed (a `failed` row with the reason); the rest was applied. Fix it and apply again: what was already created will show as `unchanged`.

**The seed has errors.** `awsemu seed validate seed.yaml` shows all of them with their line and field, without touching the emulator.

**Windows: files are left in `~/.aws/emulator/<port>/` after stopping.** `awsemu` tries a clean stop with Ctrl+Break and, if the emulator doesn't handle it, deletes those files itself. `awsemu stop` on a port with no emulator cleans them up too.

**Docker on Linux: the files belong to root.** It happens if `~/.aws/emulator` didn't exist before mounting the volume. `awsemu` creates it and runs the container with your UID; if it's already wrong, `sudo chown -R $USER ~/.aws/emulator`.

## Information for an issue

```bash
awsemu --version
awsemu --plain doctor
awsemu status --json
awsemu logs -n 100 --raw
```
