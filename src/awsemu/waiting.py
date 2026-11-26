"""Waiting for something to happen: one polling loop with a deadline, used everywhere.

``poll(check, timeout=...)`` calls ``check()`` until it returns something other
than ``None`` (that value is returned) or the deadline passes (``None`` is
returned). ``check`` is always called at least once, and once more right at the
deadline, so a slow machine never loses the last chance. To stop early with an
error, raise from ``check``.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from typing import TypeVar

T = TypeVar("T")


def poll(
    check: Callable[[], T | None],
    *,
    timeout: float,
    interval: float = 0.2,
    factor: float = 1.0,
    max_interval: float | None = None,
    sleep: Callable[[float], None] | None = None,
    clock: Callable[[], float] | None = None,
) -> T | None:
    """Call ``check`` every ``interval`` seconds (times ``factor`` after each try) until it answers."""
    sleep = sleep or time.sleep  # looked up at call time, so tests can patch time.sleep
    clock = clock or time.monotonic
    deadline = clock() + timeout
    delay = interval
    while True:
        result = check()
        if result is not None:
            return result
        left = deadline - clock()
        if left <= 0:
            return None
        sleep(min(delay, left))
        delay *= factor
        if max_interval is not None:
            delay = min(delay, max_interval)


def until(condition: Callable[[], bool], *, timeout: float, interval: float = 0.2, **kwargs) -> bool:
    """``poll`` for a yes/no condition: True as soon as it holds, False on timeout."""
    return bool(poll(lambda: True if condition() else None, timeout=timeout, interval=interval, **kwargs))
