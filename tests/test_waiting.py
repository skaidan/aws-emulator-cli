"""The polling helper used by every wait in awsemu."""

from __future__ import annotations

import pytest

from awsemu.waiting import poll, until


class FakeClock:
    def __init__(self):
        self.now = 0.0
        self.sleeps: list[float] = []

    def __call__(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.sleeps.append(round(seconds, 6))
        self.now += seconds


def test_returns_the_first_answer():
    clock = FakeClock()
    answers = iter([None, None, "ready"])
    assert poll(lambda: next(answers), timeout=5, sleep=clock.sleep, clock=clock) == "ready"
    assert clock.sleeps == [0.2, 0.2]


def test_falsy_answers_other_than_none_count():
    assert poll(lambda: 0, timeout=1) == 0
    assert poll(dict, timeout=1) == {}


def test_times_out_with_none_after_a_last_try_at_the_deadline():
    clock = FakeClock()
    calls = []
    assert poll(lambda: calls.append(clock.now), timeout=0.5, sleep=clock.sleep, clock=clock) is None
    assert calls == [0.0, 0.2, 0.4, 0.5]
    assert clock.sleeps == [0.2, 0.2, 0.1]


def test_checks_once_even_with_no_time():
    calls = []
    assert poll(lambda: calls.append(1), timeout=0) is None
    assert calls == [1]


def test_backoff_is_capped():
    clock = FakeClock()
    poll(lambda: None, timeout=10, interval=1, factor=2, max_interval=3, sleep=clock.sleep, clock=clock)
    assert clock.sleeps[:4] == [1, 2, 3, 3]


def test_errors_from_the_check_stop_the_wait():
    def check():
        raise RuntimeError("it exited")

    with pytest.raises(RuntimeError, match="it exited"):
        poll(check, timeout=5)


def test_until():
    clock = FakeClock()
    values = iter([False, True])
    assert until(lambda: next(values), timeout=1, sleep=clock.sleep, clock=clock) is True
    assert until(lambda: False, timeout=0.3, sleep=clock.sleep, clock=clock) is False
