"""The pytest plugin, run in real pytest sessions (pytester) against the fake emulator."""

import importlib.metadata
import os

import pytest

pytest.importorskip("cryptography", reason="the fake emulator needs cryptography")

SRC = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src")


def _installed_as_plugin() -> bool:
    eps = importlib.metadata.entry_points()
    group = eps.select(group="pytest11") if hasattr(eps, "select") else eps.get("pytest11", [])
    return any(ep.value == "awsemu.pytest_plugin" for ep in group)


@pytest.fixture(autouse=True)
def _src_on_path(monkeypatch):
    env_path = os.environ.get("PYTHONPATH", "")
    monkeypatch.setenv("PYTHONPATH", SRC + (os.pathsep + env_path if env_path else ""))


def run(pytester, *args):
    plugin = [] if _installed_as_plugin() else ["-p", "awsemu.pytest_plugin"]
    return pytester.runpytest_subprocess(*plugin, "-p", "no:cacheprovider", *args)


def test_fixture_starts_points_env_and_stops(pytester, fake_binary, monkeypatch):
    pytester.makepyfile(test_inner="""
        import os, json, pathlib
        from awsemu import health

        def test_a(aws_emulator):
            assert health.check(aws_emulator.port).healthy
            assert os.environ["AWS_ENDPOINT_URL"] == aws_emulator.endpoint_url
            assert "AWS_ACCESS_KEY_ID" not in os.environ
            pathlib.Path("port.txt").write_text(str(aws_emulator.port))

        def test_same_instance(aws_emulator):
            assert pathlib.Path("port.txt").read_text() == str(aws_emulator.port)
    """)
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "AKIAREALKEY")
    result = run(pytester, "-v")
    result.assert_outcomes(passed=2)
    port = int((pytester.path / "port.txt").read_text())
    from awsemu import health
    from awsemu.paths import InstanceFiles

    assert not health.port_open(port), "the fixture should stop the emulator it started"
    assert not InstanceFiles(port).ca.exists()


def test_fresh_restarts(pytester, fake_binary):
    pytester.makepyfile(test_inner="""
        from awsemu import runtime
        pids = []

        def test_one(aws_emulator_fresh):
            pids.append(runtime.State.load(aws_emulator_fresh.port).pid)

        def test_two(aws_emulator_fresh):
            pids.append(runtime.State.load(aws_emulator_fresh.port).pid)
            assert pids[0] != pids[1]
    """)
    run(pytester).assert_outcomes(passed=2)


def test_invalid_seed_fails_before_starting(pytester, fake_binary):
    pytester.makefile(".yaml", seed="tables:\n  - {name: t}\n")
    pytester.makepyfile(test_inner="def test_a(aws_emulator):\n    pass\n")
    result = run(pytester, "--awsemu-seed", "seed.yaml")
    result.assert_outcomes(errors=1)
    result.stdout.fnmatch_lines(["*awsemu: invalid seed*", "*'pk' is required*"])


def test_reuse_needs_a_running_emulator(pytester, free_port):
    pytester.makepyfile(test_inner="def test_a(aws_emulator):\n    pass\n")
    result = run(pytester, "--awsemu-reuse", "--awsemu-port", str(free_port))
    result.assert_outcomes(errors=1)
    result.stdout.fnmatch_lines([f"*no healthy emulator on port {free_port}*awsemu up*"])


def test_unused_plugin_does_nothing(pytester):
    pytester.makepyfile(test_inner="def test_a():\n    assert True\n")
    result = run(pytester, "--help")
    result.stdout.fnmatch_lines(["*--awsemu-seed*", "*--awsemu-reuse*"])
    run(pytester).assert_outcomes(passed=1)
