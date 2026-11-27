"""The service registry: every service implements every hook, or says why not."""

from __future__ import annotations

import pkgutil

import pytest

import awsemu.services as services_pkg
from awsemu.services import HOOKS, ORDER, all_services, get

SERVICES = all_services()


def test_every_module_is_registered_once():
    modules = {m.name for m in pkgutil.iter_modules(services_pkg.__path__)}
    assert modules == set(ORDER)
    names = [s.name for s in SERVICES]
    assert len(names) == len(set(names))
    assert len({s.alias for s in SERVICES}) == len(SERVICES)


@pytest.mark.parametrize("service", SERVICES, ids=lambda s: s.name)
def test_each_hook_is_there_or_explained(service):
    for hook in HOOKS:
        value = getattr(service, hook)
        present = bool(value) if hook == "completions" else value is not None
        if present:
            assert hook not in service.missing, f"{service.name}.{hook} exists but is listed as missing"
        else:
            assert service.missing.get(hook), f"{service.name} has no '{hook}' and doesn't say why (missing=...)"
    assert set(service.missing) <= set(HOOKS)


def test_lookup_by_any_name():
    assert get("stepfunctions") is get("sfn") is get("states")
    assert get("secrets").name == "secretsmanager"
    with pytest.raises(KeyError):
        get("ec2")


def test_the_commands_see_what_they_saw_before_the_registry():
    from awsemu.browse import DETAILS
    from awsemu.commands.describe import HANDLERS
    from awsemu.commands.overview import SERVICES as OVERVIEW
    from awsemu.commands.watch import COLLECTORS
    from awsemu.completion import _listers

    common = ["s3", "sqs", "dynamodb", "sns", "lambda", "secretsmanager", "ssm", "kinesis", "events", "stepfunctions"]
    assert [s[1] for s in OVERVIEW] == [*common, "logs", "iam"]  # also the keys of `overview --json`
    assert list(DETAILS) == [*common, "logs", "iam"]
    assert list(COLLECTORS) == ["s3", "sqs", "dynamodb", "sns", "lambda", "secrets", "ssm", "kinesis", "events", "sfn"]
    assert set(HANDLERS) == {*common[:-1], "states", "logs", "iam"}
    assert set(_listers()) == {
        "s3path",
        "queue",
        "table",
        "topic",
        "function",
        "secret",
        "parameter",
        "stream",
        "rule",
        "statemachine",
    }


def test_every_seed_section_has_one_service():
    from awsemu import seed as seedlib
    from awsemu.seeding import APPLY_ORDER
    from awsemu.services import seed_sections

    assert sorted(seed_sections()) == sorted(seedlib.SECTIONS) == sorted(APPLY_ORDER)
    assert len([s for s in SERVICES if s.seed_section]) == len(seedlib.SECTIONS)


@pytest.mark.parametrize("service", SERVICES, ids=lambda s: s.name)
def test_iam_policy_knows_each_services_arns(service):
    # IAM tables stay in iampolicy.py (they also cover services outside the registry);
    # this keeps a new service from silently getting Resource "*" in `awsemu iam policy`.
    from awsemu.iampolicy import resource_arn

    arn = resource_arn(service.name, f"{service.arn}:SomeAction", "name", "us-east-1", "123456789012")
    assert arn.startswith(f"arn:aws:{service.arn}:"), f"add {service.name} to iampolicy.resource_arn's templates"
