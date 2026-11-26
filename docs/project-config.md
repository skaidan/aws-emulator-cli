# Project settings (`awsemu.toml`)

An `awsemu.toml` file in your project records how you want the emulator: port, mode, seed and so on. Every `awsemu` command run in that folder (or a subfolder) uses it, and so does the [pytest plugin](testing.md#pytest-plugin).

```bash
awsemu init     # creates awsemu.toml
awsemu up       # starts the project's emulator (if it isn't running) and applies its seed
awsemu down     # stops it
```

## The file

```toml
# awsemu.toml
port = 9343                # each project on its own port: several at once without clashing
mode = "auto"              # auto | native | docker
auth = true                # false = accept unsigned requests
telemetry = false
idle_timeout = 3600        # stops by itself after an hour without calls
seed = "tests/seed.yaml"   # relative to this file
sdk = ["node"]             # node | java | rust | dotnet: trust the certificate in those SDKs
image = "aws-emulator"     # Docker image
memory = "2g"              # Docker memory limit
emulator_version = "1.0.385"  # the emulator version the team and CI use (awsemu install)
proxy = true               # awsemu up also starts the proxy; env/exec/shell go through it
faults = ["dynamodb=throttle@5%"]  # fault rules for that proxy
```

Every key is optional.

| Key | Type | What for | Default |
| --- | --- | --- | --- |
| `port` | integer | The instance's port; every command uses it | 9297 |
| `mode` | `auto` / `native` / `docker` | How to start it | `auto` (the binary if installed, otherwise Docker) |
| `auth` | boolean | Require signed requests. With `false`, `env`, `exec` and `shell` set placeholder keys (`AWS_ACCESS_KEY_ID=EMULATORAUTHOFF00000`), so the SDKs have something to sign with and never use your real profile | `true` |
| `telemetry` | boolean | The emulator's telemetry for this instance | whatever the emulator's `config.toml` says |
| `idle_timeout` | integer (seconds) | Automatic stop when idle | no limit |
| `seed` | path | Seed applied by `awsemu up` and the pytest plugin | none |
| `sdk` | list | Certificate extras in `env`, `exec` and `shell` | none |
| `image` | text | Docker image | `aws-emulator` |
| `memory` | text | Docker memory limit | `2g` |
| `proxy` | true/false | `awsemu up` also starts [the proxy](proxy.md) (calls log, faults); `env`, `exec`, `shell` and `aws` go through it when it's running; `down`/`stop` stop it; pytest sends every test through one | `false` |
| `proxy_port` | number | The proxy's port (0 = any free one) | the emulator's + 1 |
| `proxy_bodies` | true/false | The proxy also logs headers and bodies, with secrets masked (like `awsemu proxy start --bodies`) | `false` |
| `faults` | list of rules | [Fault rules](proxy.md#fault-rules) for that proxy and for pytest with `proxy = true` | none |
| `emulator_version` | text (`1.0.385`) | The emulator version for this project: `start`/`up` warn if the installed one differs, Docker mode uses `aws-emulator:<version>`, `check`/`fidelity` use its data, the GitHub Action installs it. Set it with `awsemu install VERSION --pin`; see [compatibility.md](compatibility.md#awsemu-install-and-emulator_version) | none |

### In `pyproject.toml`

In Python projects you can use a `[tool.awsemu]` table instead of a separate file:

```toml
[tool.awsemu]
port = 9343
seed = "tests/seed.yaml"
telemetry = false
```

## Where it's looked up

From the current folder upwards, `awsemu` uses the first `awsemu.toml` it finds, or the first `pyproject.toml` with a `[tool.awsemu]` table. To use another file: `AWSEMU_CONFIG=/path/to/file.toml`.

```bash
awsemu config show      # which file is in use and with which values
awsemu doctor           # includes a "project" row
```

## Precedence

From highest to lowest:

1. What you pass on the command line (`--port 9400`, `--no-auth`, `--docker`, `--seed …`, `--sdk …`).
2. Environment variables (`AWSEMU_PORT`).
3. `awsemu.toml` / `[tool.awsemu]`.
4. Defaults.

## `awsemu init`

Creates `awsemu.toml` in the current folder with sensible values (`telemetry = false`, `idle_timeout = 3600`) and comments for the rest.

- **Port:** without `--port`, it picks one between 9300 and 9399 from the folder name, so several projects can have their emulators running at once. With `awsemu --port 9400 init` it uses that one.
- **Seed:** if `tests/seed.yaml`, `seed.yaml` or `awsemu-seed.yaml` exists, it references it. Also with `--seed PATH`.
- It doesn't overwrite an existing file unless you pass `--force`.

## `awsemu up` and `awsemu down`

`up` gets the project's emulator ready:

- If it isn't running, it starts it with the project's settings.
- It applies the seed (the project's, the one from `--seed`, or none with `--no-seed`). Since [`seed apply`](seeds.md#what-apply-does) is repeatable, running `up` with the emulator already running only adds or updates what's missing.

`down` stops it (like `awsemu stop`; `--all` for every instance).

A typical workflow:

```bash
cd my-project
awsemu up
eval "$(awsemu env)"
npm run dev                  # or whatever: it already talks to the emulator
awsemu reset --seed tests/seed.yaml   # back to the initial state whenever you like
awsemu down
```

## Errors

An `awsemu.toml` with errors stops every command (exit code 2) with a specific message:

```
✗ /home/ana/my-project/awsemu.toml: 'port' must be int; unknown setting 'mdoe' (did you mean 'mode'?)
  Fix the file, or set AWSEMU_CONFIG to another one.
```

There's an example in [`examples/awsemu.toml`](../examples/awsemu.toml).
