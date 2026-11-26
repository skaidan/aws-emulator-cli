# Deprecation policy

What happens when awsemu renames or removes something you may depend on: a command, an option, a setting in `awsemu.toml`, a field of a `--json` output, an exit code, a fixture of the pytest plugin, an input of the GitHub Action.

## The rule

1. **Nothing disappears without a warning first.** When something is replaced, the old name keeps working for **at least two minor releases and three months**, whichever is longer. Using it prints a warning saying what to use instead and from which release the old name stops working:

   ```
   ⚠ '--wait-seconds' is deprecated, use --timeout; it stops working in awsemu 1.2
   ```

2. **The CHANGELOG lists it twice**: under **Deprecated** in the release that starts the period, and under **Breaking** in the release that removes it.
3. **JSON fields are kept, not renamed.** When a field of a `--json` output is replaced, the new field is added and the old one keeps being printed, with the same meaning, until its removal release. Adding a field is never breaking ([scripting.md](scripting.md#stability-promise)); the schemas in [`schemas/`](schemas/README.md) list both while they coexist.
4. **Exit codes don't get new meanings.** A code may be added for a new situation; an existing one isn't reused for something else.
5. **Before 1.0**, a release can break things when there's no reasonable way to keep the old behaviour, and says so under **Breaking**. **From 1.0**, removals happen only in a major release, after the deprecation period.

## How it looks in each place

| What | While deprecated | Removed in |
| --- | --- | --- |
| Command or option | Still accepted (hidden from `--help`), with a warning on standard error | A later release, at least two minors and three months after |
| `awsemu.toml` / `[tool.awsemu]` setting | Read under its old name too (the new name wins if both are set), with a warning | Same |
| `--json` field | Printed alongside the new one, documented as deprecated in [scripting.md](scripting.md) | Same, listed under **Breaking** |
| pytest fixture or option | Still works, with a `DeprecationWarning` | Same |
| GitHub Action input | Still read, with a workflow warning | Same |

Warnings go to standard error, so they never mix with `--json` output on standard output. To find deprecated uses in CI, look for `is deprecated` in the job's output.

## Python versions

awsemu supports the Python versions that still get security fixes from the Python core team. When a version reaches its end of life, the next minor release of awsemu stops supporting it, listed under **Breaking** in the changelog; pip then keeps installing the last release that supported it, so nothing breaks for those who don't upgrade Python. Today: Python 3.11 and later (3.10 reached its end of life in October 2026).

## Deprecated today

Nothing.
