# Contributing

## Language

English is the project's official language. Everything is written in English: code, comments, docstrings, command help and messages, documentation, the ROADMAP and CHANGELOG, examples and test data, commit messages, pull requests and issues.

## Setup

```bash
git clone https://github.com/skaidan/aws-emulator-cli && cd aws-emulator-cli
python -m venv .venv && . .venv/bin/activate      # Windows: .venv\Scripts\activate
pip install -e ".[dev,ui]"
pytest
```

`[dev]` installs pytest and `cryptography` (the fake emulator uses it to generate its certificate); `[ui]` installs Textual to test `awsemu ui` (without it, those tests are skipped).

## Tests

| Kind | Where | How to run |
| --- | --- | --- |
| Unit | `tests/test_units.py`, `tests/test_seed.py`, `tests/test_project.py` | `pytest` |
| pytest plugin | `tests/test_pytest_plugin.py` (real sessions with `pytester`) | `pytest` |
| Exploring | `tests/test_fidelity.py`, `tests/test_watch.py`, `tests/test_completion.py`, `tests/test_browse_ui.py` (with Textual: the app driven by its pilot) | `pytest` |
| Lifecycle with the fake emulator | `tests/test_lifecycle.py` | `pytest` (Linux, macOS and Windows) |
| Services with a fake client | `tests/test_services.py`, `tests/test_sns_lambda.py`, `tests/test_more_services.py` | `pytest` |
| Against the real emulator | `tests/test_real.py` | `AWSEMU_REAL_TESTS=1 pytest -m real -v` |

Real tests need the `aws-emulator` binary on your `PATH` (or `AWSEMU_BINARY`) and boto3. In CI they run in the `real-emulator` job, which installs the official `.deb` and verifies its signature.

CI jobs: `tests` (Linux, macOS and Windows; Python 3.10 and 3.13), `real-emulator`, `docker` (Docker mode and `compose` with the real emulator) and `action` (the GitHub Action in `action.yml`).

Don't put `[tool.awsemu]` in this repository's `pyproject.toml`: the tests would pick it up as project settings.

Every test runs with its own temporary `HOME`, so it never touches your `~/.aws`.

### The fake emulator

`tests/fake_emulator.py` mimics what `awsemu` uses from the real binary. If you find the real emulator behaves differently (as happened with the log format), first change the fake one to reproduce it, add a failing test, and then fix `awsemu`.

Variables to trigger odd cases: `FAKE_EMULATOR_CRASH=1` (exits with code 1) and `FAKE_EMULATOR_IGNORE_STOP=1` (ignores the clean stop).

## Adding a service

1. Create `src/awsemu/commands/<service>.py` with a `click.group()`. Follow the structure of `sns.py` or `sqs.py`:
   - get the client with `client("<service>", c.port)`;
   - decorate each command with `@pass_ctx` and `@handle_errors`;
   - use `ui.table`, `ui.kv`, `ui.success` and `ui.print_json` for output;
   - offer `--json` on listings (`@json_option`) and `--yes` on anything that deletes (`@yes_option`), and give every option a `help` text (a test checks it);
   - JSON: `snake_case` for awsemu's own summaries, AWS's field names for AWS resources; add the format to `docs/scripting.md` and a test to `tests/test_json_contract.py`;
   - exit with the constants in `exitcodes.py`, never bare numbers;
   - add `shell_complete=complete("<kind>")` to arguments that take resource names (see `completion.py`);
   - for roles, queue policies, Lambda permissions or expected errors (`is_error(exc, "ResourceNotFound")`), use `commands/_common.py`.
2. Register it in `cli.py` (`cli.add_command(...)`).
3. If it has resources to list, add it to `SERVICES` in `commands/overview.py`, to `DETAILS` in `browse.py` and, if useful, to `COLLECTORS` in `commands/watch.py`.
4. Tests with `FakeClient` (see `tests/test_services.py`) and, if you can, a test in `tests/test_real.py`.
5. If it makes sense in a seed, add the section in `seed.py` (fields and validation), its `_apply_*` and its export in `commands/seed.py`, and extend `examples/seed.yaml`.
6. Document it: a section in `docs/services.md` (and `docs/seeds.md` if relevant), a line in the README, and regenerate the reference (below).

## Documentation

- `docs/reference.md` is generated from the commands' help. After changing a command or option:

  ```bash
  python scripts/gen_reference.py
  ```

  CI fails if it's out of date (`python scripts/gen_reference.py --check`).
- The guides (`docs/*.md`), README, ROADMAP and CHANGELOG are written by hand.

## Changing the JSON output or exit codes

They're a stable interface (`docs/scripting.md`). Adding a field is fine. Renaming, removing or changing the type of one, or changing an exit code, is a breaking change: update `tests/test_json_contract.py` and `docs/scripting.md`, and list it under **Breaking** in the CHANGELOG.

## Renaming the package

The name is decided right before publishing (ROADMAP, v1.0). When it is:

```bash
python scripts/rename.py --check                                  # where the current names appear
python scripts/rename.py --package NEW-NAME --dry-run             # what would change
python scripts/rename.py --package NEW-NAME [--repo OWNER/NAME]   # do it, and verify
```

Then rename the GitHub repository (GitHub redirects the old URLs), update your git remote, run the tests and add a CHANGELOG entry. The command (`awsemu`), the Python package, `AWSEMU_*` variables and `awsemu.toml` don't change.

## Releasing a version

1. Move the `## Unreleased` entries in `CHANGELOG.md` to `## X.Y.Z — YYYY-MM-DD`.
2. Bump the version in `pyproject.toml` and `src/awsemu/__init__.py`.
3. Update the ROADMAP.
4. Push to `main`. When CI passes (including the tests against the real emulator), the `Release` workflow creates the `vX.Y.Z` tag and the GitHub release with the wheel and sdist, using the CHANGELOG section as notes. If CI fails, nothing is published.

## Style

- Error messages come with a specific hint (`RuntimeErrorWithHint(message, hint)`).
- No calls to real AWS: clients are always created against the emulator's port.
- Don't write in `~/.aws/emulator/`, which belongs to the emulator.
