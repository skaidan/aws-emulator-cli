"""Reading a real AWS account, read-only, for ``seed import`` and the proxy's shadow mode.

Everything that touches a real account goes through :func:`session`, which:

* needs a profile you name (``--profile``): never the default credentials or the
  ``AWS_*`` key variables, and never the emulator's;
* ignores ``AWS_ENDPOINT_URL`` and endpoints in your config, so the calls go to AWS
  and nowhere else;
* refuses, before anything is sent, any operation that isn't a read (``Describe*``,
  ``List*``, ``Get*``, ``Head*``) and the reads that return data or secrets rather than
  configuration (``GetSecretValue``, ``GetObject``, ``GetItem``, ``Scan``…).
"""

from __future__ import annotations

import re
from . import errors

READ_PREFIXES = ("Describe", "List", "Get", "Head")
DATA_READS = {
    "GetSecretValue",
    "BatchGetSecretValue",
    "GetObject",
    "GetObjectTorrent",
    "SelectObjectContent",
    "GetItem",
    "BatchGetItem",
    "Query",
    "Scan",
    "ExecuteStatement",
    "BatchExecuteStatement",
    "GetRecords",
    "GetShardIterator",
    "ReceiveMessage",
    "GetParameter",
    "GetParameters",
    "GetParametersByPath",
    "GetParameterHistory",
    "GetLogEvents",
    "FilterLogEvents",
    "GetQueryResults",
    "GetFunction",
    "GetLayerVersion",
    "GetExecutionHistory",
    "GetMetricData",
    "GetMetricStatistics",
    "Decrypt",
    "GenerateDataKey",
    "GetCredentialsForIdentity",
    "GetSessionToken",
    "GetFederationToken",
    "GetAuthorizationToken",
    "GetPasswordData",
    "GetConsoleOutput",
    "GetLoginProfile",
}
ARN_RE = re.compile(r"arn:aws:([a-z0-9-]+):([a-z0-9-]*):(\d{12}):")


class NotReadOnly(errors.AwsemuError):
    pass


PLAIN_PARAMETER_READS = {"GetParameter", "GetParameters"}  # allowed without decryption


def allowed(operation: str, params: dict | None = None, data_reads: bool = False) -> bool:
    """Is ``operation`` a configuration read (or any read, with ``data_reads``)?"""
    if not operation.startswith(READ_PREFIXES):
        return False
    if operation in PLAIN_PARAMETER_READS and not (params or {}).get("WithDecryption"):
        return True  # String/StringList values are configuration; SecureString stays encrypted
    return data_reads or operation not in DATA_READS


def guard(data_reads: bool = False):
    """A botocore ``before-parameter-build`` handler (it runs before anything is sent)
    that refuses anything but reads."""

    def check(params, model, **_):
        if not allowed(model.name, params, data_reads):
            raise NotReadOnly(
                f"refusing {model.service_model.service_name}:{model.name} against a real AWS "
                "account: awsemu only reads configuration there"
            )

    return check


def session(profile: str, region: str | None = None, data_reads: bool = False):
    """A boto3 session for the named profile, guarded read-only."""
    import boto3

    if not profile:
        raise NotReadOnly("a real account is only read with a profile you name (--profile)")
    s = boto3.session.Session(profile_name=profile, region_name=region)
    s.events.register("before-parameter-build.*.*", guard(data_reads))
    return s


def client(sess, service: str):
    from .clients import real_account_config

    return sess.client(service, config=real_account_config())


def localize(value, account: str, emulator_account: str = "000000000000", emulator_region: str = "us-east-1"):
    """Rewrite the real account's ARNs (in strings, dicts, lists) to the emulator's account and Region."""
    if isinstance(value, str):
        return ARN_RE.sub(
            lambda m: (
                f"arn:aws:{m.group(1)}:{emulator_region if m.group(2) else ''}:"
                f"{emulator_account if m.group(3) == account else m.group(3)}:"
            ),
            value,
        )
    if isinstance(value, dict):
        return {k: localize(v, account, emulator_account, emulator_region) for k, v in value.items()}
    if isinstance(value, list):
        return [localize(v, account, emulator_account, emulator_region) for v in value]
    return value


PLACEHOLDER = "change-me (awsemu seed import doesn't read secret values)"


def import_seed(sess, sections: set[str]) -> tuple[dict, list[str]]:
    """The configuration of the account in the session's Region, as seed data.

    Buckets without objects, tables without items, secrets and SecureString parameters
    with a placeholder value, no functions (their code isn't read)."""
    from . import seed as seedlib
    from . import services

    account = client(sess, "sts").get_caller_identity()["Account"]

    data: dict = {"version": seedlib.VERSION}
    opts = seedlib.ImportOptions(region=sess.region_name, account=account, data=data)
    by_section = services.seed_sections()
    for section in seedlib.SECTIONS:  # in order: topics and rules only keep targets imported before them
        hook = by_section[section].seed_import
        if section in sections and hook:
            items = hook(sess, opts)
            if items:
                data[section] = items
    return data, opts.notes
