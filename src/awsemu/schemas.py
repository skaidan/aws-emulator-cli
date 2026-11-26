"""JSON Schemas (draft 2020-12) of awsemu's ``--json`` outputs.

The source of truth: ``scripts/gen_schemas.py`` writes them to ``docs/schemas/`` and the
contract tests (``tests/test_json_contract.py``) validate real outputs against them, so a
schema can't drift from what the command prints. Objects allow extra fields: adding a
field isn't a breaking change (docs/scripting.md); removing or renaming one is.

``COMMANDS`` maps each schema to the command that prints it.
"""

from __future__ import annotations

from typing import Any

DRAFT = "https://json-schema.org/draft/2020-12/schema"

S: dict = {"type": "string"}
S_NULL: dict = {"type": ["string", "null"]}
INT: dict = {"type": "integer"}
INT_NULL: dict = {"type": ["integer", "null"]}
N: dict = {"type": "number"}
N_NULL: dict = {"type": ["number", "null"]}
B: dict = {"type": "boolean"}
B_NULL: dict = {"type": ["boolean", "null"]}
STRINGS: dict = {"type": "array", "items": S}
AWS_OBJECTS: dict = {"type": "array", "items": {"type": "object"}}


def obj(required: dict[str, Any], optional: dict[str, Any] | None = None, **extra) -> dict:
    """An object with these fields (all required, plus optional ones); extra fields allowed."""
    return {"type": "object", "required": sorted(required), "properties": {**required, **(optional or {})}, **extra}


def array(items: dict) -> dict:
    return {"type": "array", "items": items}


STATUS = obj(
    {
        "port": INT,
        "status": {"enum": ["healthy", "unhealthy", "stopped"]},
        "detail": S,
        "endpoint": S,
        "mode": S,
        "pid": INT_NULL,
        "container": S_NULL,
        "uptime_seconds": N_NULL,
        "auth": B_NULL,
        "files": S,
        "log": S_NULL,
    }
)

CALL = obj(
    {
        "id": INT,
        "time": S,
        "service": S,
        "operation": S,
        "resource": S,
        "method": S,
        "path": S,
        "status": INT,
        "error": S_NULL,
        "latency_ms": N,
        "request_id": S_NULL,
        "fault": S_NULL,
        "bytes_in": INT,
        "bytes_out": INT,
    },
    {"request": {"type": "object"}, "response": {"type": "object"}},
)

DIFFERENCE = obj(
    {
        "test": S,
        "kind": S,
        "operation": S_NULL,
        "mismatch": S_NULL,
        "expected": S_NULL,
        "actual": S_NULL,
        "step": S_NULL,
        "at_operation": B,
        "matches_usage": B,
        "url": S_NULL,
        "issues": array(obj({"title": S, "severity": S_NULL, "state": S, "url": S})),
        "fixed_in": S_NULL,
    }
)

LOCATION = obj({"file": S, "line": INT, "source": S})

SCHEMAS: dict[str, dict] = {
    "status": STATUS,
    "status-all": array(STATUS),
    "overview": {
        "type": "object",
        "additionalProperties": obj({"label": S, "items": STRINGS, "error": S_NULL}),
    },
    "doctor": obj(
        {
            "ok": B,
            "problems": INT,
            "checks": array(obj({"check": S, "result": {"enum": ["ok", "warn", "fail"]}, "detail": S, "fix": S_NULL})),
        }
    ),
    "fidelity": obj(
        {
            "release": S,
            "commit": S_NULL,
            "scored_at": S_NULL,
            "installed": S_NULL,
            "services": {
                "type": "object",
                "additionalProperties": obj(
                    {"passed": INT, "total": INT, "multi_service_passed": INT, "multi_service_total": INT},
                    {"failures": array(obj({"test": S, "operation": S, "mismatch": S, "expected": S, "actual": S}))},
                ),
            },
        }
    ),
    "fidelity-compare": obj(
        {
            "from": obj({"release": S, "suite": S_NULL}),
            "to": obj({"release": S, "suite": S_NULL}),
            "services": {
                "type": "object",
                "additionalProperties": obj(
                    {
                        "from": obj({"passed": INT, "total": INT}),
                        "to": obj({"passed": INT, "total": INT}),
                        "fixed": STRINGS,
                        "regressed": STRINGS,
                        "added_passing": STRINGS,
                        "added_failing": STRINGS,
                        "removed": STRINGS,
                    }
                ),
            },
        }
    ),
    "fidelity-run": obj(
        {
            "release": S,
            "installed": S_NULL,
            "suite": S,
            "tests": array(
                obj(
                    {
                        "test": S,
                        "path": S,
                        "verdict": {"enum": ["passed", "failed", "error"]},
                        "kind": S,
                        "detail": S,
                        "duration_ms": INT,
                        "published": {"enum": ["pass", "fail", None]},
                        "same_as_published": B_NULL,
                    }
                )
            ),
            "summary": obj({"passed": INT, "failed": INT, "error": INT, "differ_from_published": STRINGS}),
        }
    ),
    "check": obj(
        {
            "release": S,
            "suite": S,
            "scanned_files": INT,
            "sources": STRINGS,
            "operations": array(
                obj(
                    {
                        "operation": S,
                        "service": S,
                        "locations": array(LOCATION),
                        "tests": INT,
                        "passed": INT,
                        "differences": array(DIFFERENCE),
                        "other_failing": INT,
                    }
                )
            ),
            "uncovered": STRINGS,
            "services": array(
                obj(
                    {
                        "service": S,
                        "sources": STRINGS,
                        "tests": INT,
                        "passed": INT,
                        "resources": array(obj({"type": S, "file": S, "line": INT, "source": S})),
                        "cloudformation": {
                            "oneOf": [{"type": "null"}, obj({"tests": INT, "passed": INT, "failing": STRINGS})]
                        },
                    }
                )
            ),
            "summary": obj(
                {
                    "operations": INT,
                    "services": INT,
                    "operations_with_differences": INT,
                    "differences": INT,
                    "explained_by_issues": INT_NULL,
                    "fixed_in_latest": INT_NULL,
                    "latest": S_NULL,
                }
            ),
        }
    ),
    "check-iam": obj(
        {
            "needed": array(obj({"action": S, "used_in": STRINGS, "granted_by": STRINGS})),
            "missing": STRINGS,
            "unused_grants": array(obj({"action": S, "file": S, "line": INT})),
            "not_expanded": array(obj({"policy": S, "file": S})),
            "policy_files": INT,
        }
    ),
    "explain": obj(
        {
            "call": {"type": "object"},
            "release": S,
            "fidelity_tests": S,
            "operation": S_NULL,
            "tests": INT,
            "passed": INT,
            "differences": array(DIFFERENCE),
            "matching": STRINGS,
            "verdict": {
                "enum": [
                    "injected",
                    "known_difference",
                    "possible_difference",
                    "emulator_gap",
                    "likely_your_code",
                    "unknown",
                    "succeeded",
                ]
            },
            "advice": S,
        }
    ),
    "proxy-calls": array(CALL),
    "proxy-status": {
        "oneOf": [
            obj(
                {
                    "running": {"const": True},
                    "emulator_port": INT,
                    "port": INT,
                    "endpoint_url": S,
                    "pid": INT,
                    "ca": S_NULL,
                    "calls": INT,
                    "faults": STRINGS,
                    "calls_file": S,
                }
            ),
            obj({"running": {"const": False}, "emulator_port": INT}),
        ]
    },
    "proxy-faults": array(obj({"rule": S, "hits": INT, "active": B, "remaining_s": N_NULL})),
    "proxy-shadow": obj({"compared": INT, "differ": INT, "failed": INT, "calls": AWS_OBJECTS}),
    "proxy-cost": obj(
        {
            "estimate": {"const": True},
            "region": S,
            "prices_as_of": S,
            "calls": INT,
            "runs": INT,
            "total_usd": N,
            "lines": array(obj({"service": S, "item": S, "units": N, "usd_per_unit": N, "unit": S, "usd": N})),
            "not_priced": {"type": "object", "additionalProperties": INT},
            "excludes": STRINGS,
        }
    ),
    "issues": array(
        obj(
            {
                "title": S,
                "severity": S_NULL,
                "state": {"enum": ["open", "fixed"]},
                "services": STRINGS,
                "operations": STRINGS,
                "tests": STRINGS,
                "kind": S_NULL,
                "created": S,
                "name": S,
                "url": S,
            },
            {"fails_in_release": B},
        )
    ),
    "install-list": obj({"versions": STRINGS, "installed": S_NULL, "pinned": S_NULL}),
    "snapshot-ls": array(
        obj(
            {
                "name": S,
                "created_at": S,
                "port": INT_NULL,
                "emulator_version": S_NULL,
                "counts": {"type": "object", "additionalProperties": INT},
                "secrets": B,
                "path": S,
            }
        )
    ),
    "sqs-ls": array(obj({"name": S, "url": S, "visible": INT_NULL, "in_flight": INT_NULL, "delayed": INT_NULL})),
    "sns-ls": array(obj({"name": S, "arn": S, "subscriptions": AWS_OBJECTS})),
    "ddb-ls": array(
        obj(
            {
                "name": S,
                "partition_key": obj({"name": S, "type": S}),
                "sort_key": {"oneOf": [{"type": "null"}, obj({"name": S, "type": S})]},
                "item_count": INT_NULL,
                "status": S_NULL,
            }
        )
    ),
    "kinesis-read-line": obj({"shard": S, "sequence": S, "key": S, "data": S, "arrived": S_NULL}),
    "aws-list": AWS_OBJECTS,
}

COMMANDS: dict[str, str] = {
    "status": "awsemu status --json",
    "status-all": "awsemu status --all --json",
    "overview": "awsemu overview --json",
    "doctor": "awsemu doctor --json",
    "fidelity": "awsemu fidelity --json",
    "fidelity-compare": "awsemu fidelity --compare VERSION --json",
    "fidelity-run": "awsemu fidelity run … --json",
    "check": "awsemu check --json",
    "check-iam": "awsemu check --iam --json",
    "explain": "awsemu explain [CALL] --json",
    "proxy-calls": "awsemu proxy calls --json",
    "proxy-status": "awsemu proxy status --json",
    "proxy-faults": "awsemu proxy faults --json",
    "proxy-shadow": "awsemu proxy shadow --json",
    "proxy-cost": "awsemu proxy cost --json",
    "issues": "awsemu issues SERVICE --json",
    "install-list": "awsemu install --list --json",
    "snapshot-ls": "awsemu snapshot ls --json",
    "sqs-ls": "awsemu sqs ls --json",
    "sns-ls": "awsemu sns ls --json",
    "ddb-ls": "awsemu ddb ls --json",
    "kinesis-read-line": "awsemu kinesis read --json (each line)",
    "aws-list": "lists of AWS resources as AWS returns them (s3 ls, lambda ls, sfn ls, secrets ls, ssm ls…)",
}


def document(name: str, base_url: str) -> dict:
    """The published schema: ``$schema``, ``$id`` and a title around :data:`SCHEMAS` [name]."""
    return {"$schema": DRAFT, "$id": f"{base_url}/{name}.schema.json", "title": COMMANDS[name], **SCHEMAS[name]}
