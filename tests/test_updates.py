"""Update notices and the oldest supported emulator."""

import json
import time

import pytest

from awsemu import __version__, updates
from awsemu.cli import cli


def test_versions():
    assert updates.parse("v1.0.250") == (1, 0, 250) and updates.parse("nope") is None
    assert updates.older("1.0.99", "1.0.250") and not updates.older("1.0.250", "1.0.250")
    assert not updates.older(None, "1.0.1")


@pytest.fixture
def online(isolated_home, monkeypatch):
    monkeypatch.delenv("AWSEMU_NO_UPDATE_CHECK", raising=False)
    calls = []

    def fake(repo):
        calls.append(repo)
        return {"aws/aws-emulator": "1.0.700", updates._meta.REPO: "99.0.0"}[repo]

    monkeypatch.setattr(updates, "_fetch_latest_tag", fake)
    return calls


def test_latest_is_cached_for_a_day(online, monkeypatch):
    first = updates.latest()
    assert (first.emulator, first.awsemu) == ("1.0.700", "99.0.0") and len(online) == 2
    updates.latest()
    assert len(online) == 2  # from the cache
    data = json.loads(updates._path().read_text())
    data["checked_at"] = time.time() - updates.CACHE_SECONDS - 1
    updates._path().write_text(json.dumps(data))
    updates.latest()
    assert len(online) == 4
    monkeypatch.setenv("AWSEMU_NO_UPDATE_CHECK", "1")
    data["checked_at"] = 0
    updates._path().write_text(json.dumps(data))
    assert updates.latest().emulator == "1.0.700" and len(online) == 4  # offline: the cache, however old


def test_notices_once_a_day_and_never_in_ci(online, monkeypatch):
    monkeypatch.delenv("CI", raising=False)
    monkeypatch.setattr(updates.sys.stderr, "isatty", lambda: True, raising=False)
    found = updates.notify_once_a_day("1.0.300")
    assert any("AWS Emulator 1.0.700 is out (you have 1.0.300)" in n for n in found)
    assert any(f"awsemu 99.0.0 is out (you have {__version__})" in n for n in found)
    assert updates.notify_once_a_day("1.0.300") == []  # already said today
    monkeypatch.setenv("CI", "true")
    assert updates.quiet()


def test_doctor_shows_support_and_newer_releases(runner, online, monkeypatch, fake_binary):
    monkeypatch.setattr("awsemu.fidelity.installed_version", lambda binary=None: "1.0.100")
    out = json.loads(runner.invoke(cli, ["doctor", "--json"]).output)
    checks = {c["check"]: c for c in out["checks"]}
    assert (
        checks["emulator support"]["result"] == "fail" and "older than 1.0.250" in checks["emulator support"]["detail"]
    )
    assert checks["awsemu"]["result"] == "warn" and "99.0.0 is out" in checks["awsemu"]["detail"]
    monkeypatch.setattr("awsemu.fidelity.installed_version", lambda binary=None: "1.0.700")
    out = json.loads(runner.invoke(cli, ["doctor", "--json"]).output)
    assert {c["check"]: c for c in out["checks"]}["emulator support"]["result"] == "ok"
