"""Recognising AWS error answers without importing botocore up front."""

from __future__ import annotations


def error_code(exc: Exception) -> str:
    """The AWS error code of a botocore error (or the class name)."""
    response = getattr(exc, "response", None)
    if isinstance(response, dict):
        code = response.get("Error", {}).get("Code")
        if code:
            return str(code)
    return type(exc).__name__


def client_error() -> type[Exception]:
    """botocore's ``ClientError`` (an error answer from AWS), imported only when an error happens.

    Use it as ``except client_error() as exc:`` where only an AWS error answer is expected,
    so a bug or a lost connection isn't mistaken for "not found".
    """
    from botocore.exceptions import ClientError

    return ClientError


def is_error(exc: Exception, *codes: str) -> bool:
    code = error_code(exc)
    return any(c in code or c in type(exc).__name__ for c in codes)
