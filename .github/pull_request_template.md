## What and why

<!-- What this changes, and the problem it solves (link the issue: Fixes #123). -->

## Checklist

- [ ] Tests for the change (`pytest`), and `AWSEMU_REAL_TESTS=1 pytest -m real` if it touches how awsemu talks to the emulator
- [ ] `ruff check`, `ruff format` and `mypy` pass (see CONTRIBUTING.md)
- [ ] Docs updated (`docs/`, `python scripts/gen_reference.py` for commands and options)
- [ ] A line in `CHANGELOG.md` under "Unreleased"
- [ ] `--json` output changes are additive, or noted as breaking
