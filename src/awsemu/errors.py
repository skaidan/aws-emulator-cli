"""awsemu's errors: one base class, a message, an optional hint and an exit code.

Every error that awsemu raises on purpose derives from ``AwsemuError``. The
commands' error handler (``context.handle_errors``) prints the message and the
hint and exits with ``exit_code``, so a new error type needs no new handling.
"""

from __future__ import annotations

from . import exitcodes


class AwsemuError(Exception):
    """An expected failure: printed as one line plus a hint, never as a traceback."""

    exit_code = exitcodes.FAILED

    def __init__(self, message: str = "", hint: str | None = None):
        super().__init__(message)
        self.hint = hint


class UsageError(AwsemuError):
    """Nothing was done: bad input (a setting, a seed, a fault rule…)."""

    exit_code = exitcodes.USAGE


class RuntimeErrorWithHint(AwsemuError, RuntimeError):
    """Something failed while running (kept under this name: it's used everywhere)."""
