"""Shared Click plumbing: the global ``--port`` and friendly error handling."""

from __future__ import annotations

import functools
import sys

import click

from . import exitcodes
from . import ui
from .errors import AwsemuError


json_option = click.option(
    "--json", "as_json", is_flag=True, help="Machine-readable JSON output (format: docs/scripting.md)."
)


yes_option = click.option("-y", "--yes", is_flag=True, help="Don't ask for confirmation (for scripts).")


class Ctx:
    def __init__(self, port: int):
        self.port = port


pass_ctx = click.make_pass_decorator(Ctx)


BOTOCORE_BASES = {"ClientError", "BotoCoreError"}


def _is_botocore_error(exc: Exception) -> bool:
    """True for botocore errors, including the per-code subclasses it generates
    at runtime (``AccessDenied``, ``NoSuchBucket``, ``QueueDoesNotExist``...)."""
    return (
        any(cls.__name__ in BOTOCORE_BASES and cls.__module__.startswith("botocore") for cls in type(exc).__mro__)
        or type(exc).__name__ in BOTOCORE_BASES
    )


# Packages some commands need, and what for (a minimal install can leave them out).
OPTIONAL_PACKAGES = {
    "boto3": "the AWS SDK for Python",
    "botocore": "the AWS SDK for Python",
    "s3transfer": "the AWS SDK for Python",
    "cryptography": "cryptography (the proxy's certificate)",
    "textual": "Textual (the terminal UI)",
    "testcontainers": "Testcontainers",
}


def handle_errors(fn):
    """Turn expected failures into a one-line message plus a hint, and the error's exit code."""

    @functools.wraps(fn)
    def wrapper(*args, **kwargs):
        try:
            return fn(*args, **kwargs)
        except AwsemuError as exc:
            ui.error(str(exc), exc.hint)
            sys.exit(exc.exit_code)
        except ImportError as exc:
            missing = (exc.name or "").split(".")[0]
            if missing not in OPTIONAL_PACKAGES:
                raise
            from . import _meta

            ui.error(
                f"this command needs {OPTIONAL_PACKAGES[missing]}, which isn't installed ({missing})",
                f"pip install {'boto3' if missing in ('botocore', 's3transfer') else missing}, "
                f"or reinstall awsemu with its dependencies: {_meta.install_hint()}",
            )
            sys.exit(exitcodes.FAILED)
        except Exception as exc:  # botocore errors without importing botocore here
            if _is_botocore_error(exc):
                from .clients import describe_error, hint_for

                ui.error(describe_error(exc), hint_for(exc))
                sys.exit(exitcodes.FAILED)
            raise

    return wrapper


def proxy_option(fn):
    """``--proxy/--no-proxy`` for commands that point a program at the emulator."""
    return click.option(
        "--proxy/--no-proxy",
        "use_proxy",
        default=None,
        help="Go through the running proxy (default: yes when awsemu.toml has proxy = true and it's running).",
    )(fn)
