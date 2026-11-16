# Testing and CI

The emulator is ideal for integration tests: no AWS account needed, it starts in moments and every restart begins empty. `awsemu` offers three ways to use it, depending on where your tests run:

| Where | How |
| --- | --- |
| pytest | [Plugin](#pytest-plugin): `aws_emulator` fixture, no setup |
| GitHub Actions | [Action](#github-actions): `uses: skaidan/aws-emulator-cli@v0.8.0` |
| Anywhere else | [Scripts](#scripts) with `awsemu start`/`exec`/`stop`, or [Docker Compose](#docker-compose) |

In every case, starting data goes in a [seed](seeds.md).

## pytest plugin

It's installed with `awsemu` and does nothing until a test asks for one of its fixtures.

```python
import boto3


def test_upload(aws_emulator):
    s3 = boto3.client("s3")                      # already points at the emulator
    s3.create_bucket(Bucket="demo")
    assert "demo" in [b["Name"] for b in s3.list_buckets()["Buckets"]]


def test_with_clean_state(aws_emulator_fresh):
    # restarted and re-seeded: whatever another test did is gone
    names = [b["Name"] for b in aws_emulator_fresh.client("s3").list_buckets()["Buckets"]]
    assert "demo" not in names
```

```bash
pytest --awsemu-seed tests/seed.yaml
```

### What `aws_emulator` does

Once per pytest session:

1. Validates the seed (if any) **before** starting anything.
2. Starts an emulator on a **free port** (so it doesn't clash with the one you have open or with other pytest processes, e.g. with `pytest-xdist`), with a 30-minute `idle_timeout` as a safety net.
3. Applies the seed.
4. Points `os.environ` at the emulator (the same variables as `awsemu env`) and removes your real credentials: boto3, the AWS CLI or your own code use it with no setup.
5. At the end of the session it restores the environment and stops the emulator.

The fixture returns an object with:

| Attribute / method | What for |
| --- | --- |
| `port`, `endpoint_url` | Where it listens |
| `env` | The variables it put in the environment |
| `client("s3")` | A boto3 client connected to this emulator |
| `apply_seed(path=None)` | Apply another seed (or the same one again) |
| `reset()` | Restart (empty state) and re-apply the seed |

`aws_emulator_fresh` is the same emulator, restarted before each test that asks for it. It's slower (a few seconds per test), so use it only where you need to start from scratch.

### Options

| Command line | `pytest.ini` / `[tool.pytest.ini_options]` | What for |
| --- | --- | --- |
| `--awsemu-seed FILE` | `awsemu_seed = tests/seed.yaml` | Seed (relative to the pytest root) |
| `--awsemu-port N` | `awsemu_port = 9350` | A fixed port instead of a free one |
| `--awsemu-reuse` | `awsemu_reuse = true` | Use an emulator that's already running (`awsemu up`) instead of starting one; it isn't stopped at the end |
| `--awsemu-docker` | `awsemu_mode = docker` | Run it in Docker |

If you don't set anything, whatever is in [`awsemu.toml`](project-config.md) is used (`seed`, `mode`, `auth`, `telemetry`, `sdk`…).

`--awsemu-reuse` is handy while developing: keep the emulator running with `awsemu up` and your tests start instantly.

## GitHub Actions

```yaml
jobs:
  integration:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: skaidan/aws-emulator-cli@v0.8.0
        with:
          seed: tests/seed.yaml
      - run: pytest tests/integration      # AWS_ENDPOINT_URL & co. are already set
```

The Action:

1. Downloads the official emulator package (the version in `emulator-version`, else `emulator_version` from your `awsemu.toml`, else the latest), **verifies its GPG signature** (and the key fingerprint) and installs it.
2. Installs `awsemu` (the Action's own version).
3. Starts the emulator (`--no-telemetry` by default, a one-hour `idle_timeout`) and applies the seed.
4. Exports the emulator's variables for the following steps (`AWS_ENDPOINT_URL`, `AWS_CA_BUNDLE`, `AWS_CONFIG_FILE`, `AWS_SHARED_CREDENTIALS_FILE`, region…) and `AWSEMU_PORT`, so `awsemu` and the AWS CLI work without `--port` too.

| Input | Default | |
| --- | --- | --- |
| `emulator-version` | — | Emulator version, like `1.0.385`. Empty: `emulator_version` from `awsemu.toml`, else the latest |
| `seed` | — | Path of the seed in your repository |
| `port` | `9297` | |
| `auth` | `true` | `false` accepts unsigned requests |
| `telemetry` | `false` | |
| `idle-timeout` | `3600` | Seconds without calls before it stops |
| `export-env` | `true` | `false` to only start it |

| Output | |
| --- | --- |
| `emulator-version` | The version installed |
| `port` | Port |
| `endpoint-url` | `https://127.0.0.1:PORT` |
| `ca-bundle` | Path of the certificate |

Notes:

- It needs a **Linux** runner (x64 or ARM64): the emulator ships as a Linux package.
- Don't use real AWS credentials in the same job: they'd take precedence over the emulator's (the Action warns if it detects them). If you need them, run the commands meant for the emulator with `awsemu exec -- …`.
- To see what happened when something fails:

  ```yaml
      - if: failure()
        run: awsemu logs -n 200
  ```

To also check that your code doesn't rely on known emulator differences, add `- run: awsemu check --strict` ([details](compatibility.md#in-ci)).

The `action` job in [`.github/workflows/ci.yml`](../.github/workflows/ci.yml) tests the Action on every change, including installing a pinned version.

## Scripts

```bash
awsemu start --idle-timeout 900 --seed tests/seed.yaml
awsemu exec -- pytest tests/integration      # or npm test, go test, terraform…
code=$?
awsemu stop
exit $code
```

`awsemu exec` runs the command with the emulator's variables and **without** your real credentials, so a misconfigured test can't reach AWS by accident.

### Clean state between suites

The emulator keeps everything in memory and has no route to empty it. Restart it; with a seed, it also comes back with your starting data:

```bash
awsemu reset --seed tests/seed.yaml
```

To build that seed, create the scenario by hand or with your application and export it: `awsemu seed export -o tests/seed.yaml --no-secrets`.

### Several suites in parallel

Each one on its own port:

```bash
awsemu --port 9301 start && AWSEMU_PORT=9301 awsemu exec -- pytest tests/a &
awsemu --port 9302 start && AWSEMU_PORT=9302 awsemu exec -- pytest tests/b &
wait
awsemu stop --all
```

## Docker Compose

`awsemu compose` generates the emulator's service with the same setup as `awsemu start --docker`: AWS's official recipe, the port published on `127.0.0.1` only, limited memory, and the credentials folder mounted at the same path as on your machine.

```bash
awsemu compose -o compose.emulator.yaml
docker compose -f compose.emulator.yaml up -d
awsemu status                                 # wait until it's healthy
eval "$(awsemu env)"
```

It uses the project's settings (`port`, `auth`, `telemetry`, `idle_timeout`, `image`, `memory`) and accepts `--no-auth`, `--no-telemetry`, `--idle-timeout`, `--name` and `--no-build` (if you already built the image with `awsemu image build`).

For **other containers** to talk to the emulator: on Linux, `network_mode: host` and the variables from `awsemu env --shell dotenv`, mounting `~/.aws/emulator` at the same path so `AWS_CA_BUNDLE` exists inside the container. The emulator's certificate is for `127.0.0.1`, so going through the service name would fail TLS verification.

The `docker` job in CI builds the image, tests `awsemu start --docker` and brings up the file `awsemu compose` generates.

## Checking you're talking to the emulator

```bash
awsemu whoami                              # fails if the account isn't 000000000000
awsemu exec -- aws sts get-caller-identity
```

Use it as the first step of any script that creates or deletes resources.

## Machine-readable output

Every listing has `--json`, results have `--raw`, and exit codes are documented: see [Scripting: JSON output and exit codes](scripting.md). Those formats are stable; the tables are for humans and may change.
