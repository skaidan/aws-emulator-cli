"""boto3 clients wired to one emulator instance.

Clients are configured explicitly (endpoint, CA, keys from the emulator's
credentials file) rather than through environment variables, so ``awsemu``
never touches real AWS even if the user's shell has real credentials.
"""

from __future__ import annotations

import configparser
from functools import lru_cache

from .paths import REGION, InstanceFiles
from .runtime import RuntimeErrorWithHint

# Used when the emulator runs with --auth off: it serves any request, but
# botocore still wants something to sign with.
_AUTH_OFF_KEYS = ("EMULATORAUTHOFF00000", "0" * 40)


def read_credentials(port: int) -> tuple[str, str]:
    files = InstanceFiles(port)
    if not files.credentials.exists():
        return _AUTH_OFF_KEYS
    parser = configparser.ConfigParser()
    parser.read(files.credentials, encoding="utf-8")
    section = "default" if parser.has_section("default") else (parser.sections() or [None])[0]
    if section is None:
        raise RuntimeErrorWithHint(f"No profile found in {files.credentials}.")
    return (parser.get(section, "aws_access_key_id"),
            parser.get(section, "aws_secret_access_key"))


def ensure_running(port: int) -> InstanceFiles:
    files = InstanceFiles(port)
    if not files.ca.exists():
        raise RuntimeErrorWithHint(
            f"No emulator files for port {port} ({files.dir}).",
            "Start one with 'awsemu start' (or pass --port).")
    return files


@lru_cache(maxsize=None)
def _session(port: int):
    try:
        import boto3
    except ImportError as exc:  # pragma: no cover
        raise RuntimeErrorWithHint("boto3 is not installed.",
                                   "pip install boto3  (or reinstall aws-emulator-cli)") from exc
    key, secret = read_credentials(port)
    return boto3.session.Session(aws_access_key_id=key, aws_secret_access_key=secret,
                                 region_name=REGION)


def client(service: str, port: int):
    files = ensure_running(port)
    from botocore.config import Config

    config = Config(
        inject_host_prefix=False,
        s3={"addressing_style": "path", "signature_version": "s3v4"},
        retries={"max_attempts": 2, "mode": "standard"},
        connect_timeout=3,
        read_timeout=30,
    )
    return _session(port).client(service, endpoint_url=files.endpoint_url,
                                 verify=str(files.ca), config=config)


def error_code(exc: Exception) -> tuple[str, str]:
    response = getattr(exc, "response", None)
    if isinstance(response, dict) and "Error" in response:
        err = response["Error"]
        return str(err.get("Code", "")), str(err.get("Message", ""))
    return "", str(exc)


def hint_for(exc: Exception) -> str | None:
    """A concrete next step for errors that have a known cause with the emulator.

    Based on "Credentials and authentication" in the AWS Emulator command reference.
    """
    code, message = error_code(exc)
    text = f"{type(exc).__name__} {code} {message}".lower()
    if "emulator credentials" in text or (code == "AccessDenied" and "sign the request" in text):
        return ("The request was signed with keys the emulator doesn't accept: real AWS keys or "
                "keys from an earlier run (they change on every start). Reload your shell with "
                "eval \"$(awsemu env)\", or use 'awsemu exec' / 'awsemu aws'.")
    if code == "SignatureDoesNotMatch":
        return ("The secret key doesn't match this run. Did the emulator restart? "
                "Re-run eval \"$(awsemu env)\" so your tools read the new credentials file.")
    if code in ("InvalidClientTokenId", "MissingAuthenticationToken", "IncompleteSignature"):
        return ("The request isn't signed. Point your tool at the emulator's credentials "
                "(eval \"$(awsemu env)\") or start it with 'awsemu start --no-auth'.")
    if code == "UnknownService" or "unknownservice" in text:
        return ("The emulator couldn't tell which service this is: usually an unsigned request, "
                "otherwise the service may not be emulated yet "
                "(see https://github.com/aws/aws-emulator/issues).")
    if code in ("RequestTimeTooSkewed", "SignatureExpired") or "signature expired" in text:
        return "Your clock is more than 15 minutes off. Sync it (e.g. enable NTP) and retry."
    if code in ("UnknownOperationException", "NotImplemented", "InvalidAction") or \
            "not implemented" in text:
        return ("This operation may not be emulated yet. Check the fidelity notes and open "
                "issues at https://github.com/aws/aws-emulator/issues.")
    if "certificate_verify_failed" in text or "sslerror" in text or "ssl:" in text:
        return ("TLS check failed. The emulator makes a new ca.pem on every start: make sure "
                "AWS_CA_BUNDLE points to ~/.aws/emulator/<port>/ca.pem (not a copy) and that "
                "the port belongs to the emulator ('awsemu status').")
    if "could not connect" in text or "endpointconnectionerror" in text or \
            "connectionclosederror" in text:
        return "Nothing answered. Is the emulator running? Try 'awsemu status'."
    return None


def describe_error(exc: Exception) -> str:
    """Short, readable text for botocore errors."""
    response = getattr(exc, "response", None)
    if isinstance(response, dict) and "Error" in response:
        err = response["Error"]
        code = err.get("Code", "Error")
        msg = err.get("Message", "")
        return f"{code}: {msg}" if msg else str(code)
    return str(exc)
