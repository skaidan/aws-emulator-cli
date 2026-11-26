"""Validate a --json output against its published schema (awsemu.schemas)."""

import pytest

from awsemu import schemas


def validate(name: str, data) -> None:
    jsonschema = pytest.importorskip("jsonschema")
    jsonschema.validate(data, {"$schema": schemas.DRAFT, **schemas.SCHEMAS[name]})


def schema_for(args: tuple) -> str | None:
    """The schema of ``awsemu ARGS --json``, from the command line."""
    words = [a for a in args if not a.startswith("-") and not a.isdigit()]
    flags = set(args)
    key = " ".join(words[:2])
    if words[:1] == ["status"]:
        return "status-all" if "--all" in flags else "status"
    if words[:1] == ["fidelity"]:
        return "fidelity-compare" if "--compare" in flags else "fidelity"
    if words[:1] == ["check"]:
        return "check-iam" if "--iam" in flags else "check"
    if words[:1] == ["install"]:
        return "install-list"
    return {
        "overview": "overview",
        "doctor": "doctor",
        "explain": "explain",
        "proxy calls": "proxy-calls",
        "proxy status": "proxy-status",
        "proxy faults": "proxy-faults",
        "proxy shadow": "proxy-shadow",
        "proxy cost": "proxy-cost",
        "snapshot ls": "snapshot-ls",
        "sqs ls": "sqs-ls",
        "sns ls": "sns-ls",
        "ddb ls": "ddb-ls",
        "dynamodb ls": "ddb-ls",
        "issues": "issues",
    }.get(key) or {"overview": "overview", "doctor": "doctor", "explain": "explain", "issues": "issues"}.get(
        words[0] if words else ""
    )
