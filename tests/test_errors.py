"""Every error awsemu raises on purpose is an AwsemuError with an exit code."""

from __future__ import annotations

import click
import pytest
from click.testing import CliRunner

from awsemu import exitcodes
from awsemu.context import handle_errors
from awsemu.errors import AwsemuError, RuntimeErrorWithHint, UsageError
from awsemu.faults import FaultError
from awsemu.fidelity import FidelityError
from awsemu.fidelityrun import RunError
from awsemu.install import InstallError
from awsemu.issues import IssuesError
from awsemu.mcp import GuardError
from awsemu.project import ProjectError
from awsemu.proxy import ProxyError
from awsemu.realaccount import NotReadOnly
from awsemu.report import ReportError
from awsemu.runtime import RuntimeErrorWithHint as FromRuntime
from awsemu.seed import SeedError


@pytest.mark.parametrize(
    ("cls", "code"),
    [
        (RuntimeErrorWithHint, exitcodes.FAILED),
        (InstallError, exitcodes.FAILED),
        (ProxyError, exitcodes.FAILED),
        (ReportError, exitcodes.FAILED),
        (FidelityError, exitcodes.FAILED),
        (IssuesError, exitcodes.FAILED),
        (RunError, exitcodes.FAILED),
        (GuardError, exitcodes.FAILED),
        (NotReadOnly, exitcodes.FAILED),
        (ProjectError, exitcodes.USAGE),
        (FaultError, exitcodes.USAGE),
        (SeedError, exitcodes.USAGE),
    ],
)
def test_errors_share_one_base_and_have_an_exit_code(cls, code):
    assert issubclass(cls, AwsemuError)
    assert cls.exit_code == code


def test_old_names_keep_working():
    assert FromRuntime is RuntimeErrorWithHint
    assert issubclass(RuntimeErrorWithHint, RuntimeError)  # callers that catch RuntimeError
    assert issubclass(FaultError, ValueError)  # callers that catch ValueError


@pytest.mark.parametrize(
    ("exc", "code"),
    [(AwsemuError("broke", "do this"), 1), (UsageError("bad input", "like this"), 2), (ProxyError("no proxy"), 1)],
)
def test_handler_prints_message_and_hint_and_exits_with_the_code(exc, code):
    @click.command()
    @handle_errors
    def boom():
        raise exc

    result = CliRunner().invoke(boom)
    assert result.exit_code == code
    assert str(exc) in result.output
    if exc.hint:
        assert exc.hint in result.output
