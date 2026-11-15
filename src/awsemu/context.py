"""Shared Click plumbing: the global ``--port`` and friendly error handling."""

from __future__ import annotations

import functools
import sys

import click

from . import ui
from .runtime import RuntimeErrorWithHint


class Ctx:
    def __init__(self, port: int):
        self.port = port


pass_ctx = click.make_pass_decorator(Ctx)


BOTOCORE_BASES = {"ClientError", "BotoCoreError"}


def _is_botocore_error(exc: Exception) -> bool:
    """True for botocore errors, including the per-code subclasses it generates
    at runtime (``AccessDenied``, ``NoSuchBucket``, ``QueueDoesNotExist``...)."""
    return any(cls.__name__ in BOTOCORE_BASES and cls.__module__.startswith("botocore")
               for cls in type(exc).__mro__) or type(exc).__name__ in BOTOCORE_BASES


def handle_errors(fn):
    """Turn expected failures into a one-line message plus a hint, exit code 1."""

    @functools.wraps(fn)
    def wrapper(*args, **kwargs):
        try:
            return fn(*args, **kwargs)
        except RuntimeErrorWithHint as exc:
            ui.error(str(exc), exc.hint)
            sys.exit(1)
        except Exception as exc:  # botocore errors without importing botocore here
            if _is_botocore_error(exc):
                from .clients import describe_error, hint_for

                ui.error(describe_error(exc), hint_for(exc))
                sys.exit(1)
            raise

    return wrapper
