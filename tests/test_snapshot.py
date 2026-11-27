"""awsemu snapshot: save, list, restore, delete (the emulator is simulated)."""

import json

import pytest

from awsemu.commands import lifecycle as cli_mod
from awsemu import runtime
from awsemu.cli import cli
from awsemu.commands import seed as seed_cmd

DATA = {"version": 1, "queues": [{"name": "jobs"}], "secrets": [{"name": "db", "value": "x"}]}


@pytest.fixture
def exported(monkeypatch):
    calls = []

    def fake_export(port, sections, objects_dir, out_dir, include_secrets):
        calls.append((port, include_secrets, objects_dir))
        data = dict(DATA) if include_secrets else {"version": 1, "queues": DATA["queues"]}
        return data, ["skipped something"]

    monkeypatch.setattr("awsemu.seeding.export", fake_export)
    monkeypatch.setattr("awsemu.fidelity.installed_version", lambda binary=None: "1.0.611")
    return calls


def test_save_list_and_delete(runner, exported, isolated_home):
    result = runner.invoke(cli, ["--port", "9400", "snapshot", "save", "ready"])
    assert result.exit_code == 0, result.output
    assert "Saved snapshot 'ready': 1 queues, 1 secrets" in result.output
    assert "secret values in plain text" in result.output and "skipped something" in result.output
    folder = isolated_home / ".aws" / "emulator-cli" / "snapshots" / "ready"
    assert (folder / "seed.yaml").read_text().startswith("# awsemu snapshot 'ready', saved from port 9400")
    meta = json.loads((folder / "snapshot.json").read_text())
    assert meta["port"] == 9400 and meta["emulator_version"] == "1.0.611" and meta["secrets"] is True
    assert exported[0][2] == folder.with_name(".ready.saving") / "files"
    assert not folder.with_name(".ready.saving").exists()

    again = runner.invoke(cli, ["snapshot", "save", "ready"])
    assert again.exit_code == 1 and "already exists" in again.output
    assert runner.invoke(cli, ["snapshot", "save", "ready", "--force", "--no-secrets"]).exit_code == 0
    assert json.loads((folder / "snapshot.json").read_text())["secrets"] is False

    listed = json.loads(runner.invoke(cli, ["snapshot", "ls", "--json"]).output)
    assert [(s["name"], s["counts"]) for s in listed] == [("ready", {"queues": 1})]
    assert "ready" in runner.invoke(cli, ["snapshot", "ls"]).output
    assert runner.invoke(cli, ["snapshot", "rm", "ready", "-y"]).exit_code == 0
    assert "No snapshots" in runner.invoke(cli, ["snapshot", "ls"]).output
    assert runner.invoke(cli, ["snapshot", "rm", "ready", "-y"]).exit_code == 1


def test_bad_names_and_custom_dir(runner, exported, tmp_path):
    assert runner.invoke(cli, ["snapshot", "save", "../evil"]).exit_code == 2
    assert runner.invoke(cli, ["snapshot", "save", "a b"]).exit_code == 2
    result = runner.invoke(cli, ["snapshot", "save", "team", "--dir", str(tmp_path / "snaps")])
    assert result.exit_code == 0, result.output
    assert (tmp_path / "snaps" / "team" / "seed.yaml").is_file()
    assert "team" in runner.invoke(cli, ["snapshot", "ls", "--dir", str(tmp_path / "snaps")]).output


def test_a_failed_save_leaves_nothing(runner, monkeypatch, isolated_home):
    def broken(*a, **k):
        raise RuntimeError("emulator went away")

    monkeypatch.setattr("awsemu.seeding.export", broken)
    assert runner.invoke(cli, ["snapshot", "save", "x"]).exit_code != 0
    root = isolated_home / ".aws" / "emulator-cli" / "snapshots"
    assert not any(root.iterdir()) if root.exists() else True


def test_restore_resets_with_the_seed(runner, exported, monkeypatch):
    runner.invoke(cli, ["--port", "9400", "snapshot", "save", "ready"])
    started = []
    monkeypatch.setattr(runtime, "stop", lambda port, **k: "not running")
    monkeypatch.setattr(cli_mod.health, "port_open", lambda port: False)
    monkeypatch.setattr(cli_mod, "_do_start", lambda port, **kw: started.append((port, kw)))
    monkeypatch.setattr("awsemu.fidelity.installed_version", lambda binary=None: "1.0.700")

    result = runner.invoke(cli, ["--port", "9400", "snapshot", "restore", "ready"])
    assert result.exit_code == 0, result.output
    assert "saved with emulator 1.0.611, restoring into 1.0.700" in result.output
    port, kwargs = started[0]
    assert port == 9400 and kwargs["seed"].section("queues") == [{"name": "jobs"}]

    applied = []
    monkeypatch.setattr(seed_cmd, "run_apply", lambda seed, port: applied.append((seed.count(), port)))
    assert runner.invoke(cli, ["--port", "9400", "snapshot", "restore", "ready", "--no-reset"]).exit_code == 0
    assert applied == [({"queues": 1, "secrets": 1}, 9400)]
    missing = runner.invoke(cli, ["snapshot", "restore", "nope"])
    assert missing.exit_code == 1 and "no snapshot 'nope'" in missing.output
