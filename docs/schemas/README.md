# JSON Schemas of `--json` outputs

Generated from `src/awsemu/schemas.py` by `scripts/gen_schemas.py`; the contract tests validate real
outputs against them. JSON Schema draft 2020-12. Objects allow fields that aren't listed: new fields
can be added without notice (docs/scripting.md), so don't set `additionalProperties: false` on top.

| Output | Schema |
| --- | --- |
| `lists of AWS resources as AWS returns them (s3 ls, lambda ls, sfn ls, secrets ls, ssm ls…)` | [aws-list.schema.json](aws-list.schema.json) |
| `awsemu check --json` | [check.schema.json](check.schema.json) |
| `awsemu check --iam --json` | [check-iam.schema.json](check-iam.schema.json) |
| `awsemu ddb ls --json` | [ddb-ls.schema.json](ddb-ls.schema.json) |
| `awsemu doctor --json` | [doctor.schema.json](doctor.schema.json) |
| `awsemu explain [CALL] --json` | [explain.schema.json](explain.schema.json) |
| `awsemu fidelity --json` | [fidelity.schema.json](fidelity.schema.json) |
| `awsemu fidelity --compare VERSION --json` | [fidelity-compare.schema.json](fidelity-compare.schema.json) |
| `awsemu fidelity run … --json` | [fidelity-run.schema.json](fidelity-run.schema.json) |
| `awsemu install --list --json` | [install-list.schema.json](install-list.schema.json) |
| `awsemu issues SERVICE --json` | [issues.schema.json](issues.schema.json) |
| `awsemu kinesis read --json (each line)` | [kinesis-read-line.schema.json](kinesis-read-line.schema.json) |
| `awsemu overview --json` | [overview.schema.json](overview.schema.json) |
| `awsemu proxy calls --json` | [proxy-calls.schema.json](proxy-calls.schema.json) |
| `awsemu proxy cost --json` | [proxy-cost.schema.json](proxy-cost.schema.json) |
| `awsemu proxy faults --json` | [proxy-faults.schema.json](proxy-faults.schema.json) |
| `awsemu proxy shadow --json` | [proxy-shadow.schema.json](proxy-shadow.schema.json) |
| `awsemu proxy status --json` | [proxy-status.schema.json](proxy-status.schema.json) |
| `awsemu snapshot ls --json` | [snapshot-ls.schema.json](snapshot-ls.schema.json) |
| `awsemu sns ls --json` | [sns-ls.schema.json](sns-ls.schema.json) |
| `awsemu sqs ls --json` | [sqs-ls.schema.json](sqs-ls.schema.json) |
| `awsemu status --json` | [status.schema.json](status.schema.json) |
| `awsemu status --all --json` | [status-all.schema.json](status-all.schema.json) |

Validate in a script, with [check-jsonschema](https://github.com/python-jsonschema/check-jsonschema):

```bash
awsemu status --json > status.json
check-jsonschema --schemafile https://raw.githubusercontent.com/skaidan/aws-emulator-cli/main/docs/schemas/status.schema.json status.json
```
