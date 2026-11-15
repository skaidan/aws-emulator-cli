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
            name = type(exc).__name__
            if name in ("ClientError", "EndpointConnectionError", "SSLError",
                        "NoCredentialsError", "ParamValidationError", "ConnectionClosedError"):
                from .clients import describe_error

                hint = None
                if name in ("EndpointConnectionError", "SSLError", "ConnectionClosedError"):
                    hint = "Is the emulator running? Try 'awsemu status'."
                ui.error(describe_error(exc), hint)
                sys.exit(1)
            raise

    return wrapper
