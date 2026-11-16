"""awsemu install and the emulator_version pin (nothing is really installed)."""

import json
import os
import subprocess

import pytest

from awsemu import fidelity as fid
from awsemu import install as inst
from awsemu import project, runtime
from awsemu.cli import cli

LTS = "https://downloads.aws.com/aws-emulator/packages/aws-emulator/LTS"


def test_package_urls_follow_aws_naming():
    assert inst.package_url("deb", "x86_64", None) == f"{LTS}/latest/aws-emulator_amd64.deb"
    assert inst.package_url("deb", "aarch64", "1.0.385") == f"{LTS}/aws-emulator_1.0.385-1_arm64.deb"
    assert inst.package_url("rpm", "x86_64", None) == f"{LTS}/latest/aws-emulator-x86_64.rpm"
    assert inst.package_url("rpm", "aarch64", "1.0.385") == f"{LTS}/aws-emulator-1.0.385-1-aarch64.rpm"
    assert runtime.dockerfile("x86_64", "1.0.385").split()[3] == f"{LTS}/aws-emulator-1.0.385-1-x86_64.rpm"
    assert inst.image_tag("1.0.385") == "aws-emulator:1.0.385"


def test_normalize():
    assert inst.normalize("v1.0.385") == inst.normalize("1.0.385") == "1.0.385"
    assert inst.normalize("latest") is None and inst.normalize(None) is None
    with pytest.raises(inst.InstallError):
        inst.normalize("1.0")


@pytest.mark.parametrize("doc", [
    ["1.0.2", "1.0.10", "1.0.3"],
    {"versions": ["v1.0.2", "1.0.10", "1.0.3"]},
    {"versions": [{"version": "1.0.2", "date": "2026-11-01"}, {"version": "1.0.10"}, {"version": "1.0.3"}]},
    {"1.0.2": {}, "1.0.10": {}, "1.0.3": {}, "latest": "1.0.10"},
])
def test_parse_versions_any_shape(doc):
    assert inst.parse_versions(json.dumps(doc).encode()) == ["1.0.10", "1.0.3", "1.0.2"]


def test_list_versions_falls_back_to_github(monkeypatch):
    def fake_get(url, accept="", gzip_ok=False):
        if url == inst.VERSIONS_URL:
            raise fid.FidelityError("not found: versions.json")
        return json.dumps([{"tag_name": "v1.0.390"}, {"tag_name": "v1.0.385"},
                           {"tag_name": "nightly", "draft": False}]).encode()

    monkeypatch.setattr(fid, "_get", fake_get)
    assert inst.list_versions() == ["1.0.390", "1.0.385"]


@pytest.mark.skipif(os.name == "nt", reason="Linux packages")
def test_native_plan(monkeypatch):
    monkeypatch.setattr(os, "geteuid", lambda: 1000)
    monkeypatch.setattr(inst.shutil, "which", lambda name: f"/usr/bin/{name}")
    plan = inst.native_plan("1.0.385", kind="deb", arch="x86_64")
    assert plan.command == ["sudo", "apt-get", "install", "-y", "--allow-downgrades",
                            "./aws-emulator_1.0.385-1_amd64.deb"]
    rpm = inst.native_plan(None, kind="rpm", arch="aarch64", verify=False)
    assert rpm.command[:4] == ["sudo", "rpm", "-U", "--oldpackage"]
    assert dict(rpm.describe())["signature"] == "not checked (--no-verify)"
    monkeypatch.setattr(os, "geteuid", lambda: 0)
    assert inst.native_plan("1.0.385", kind="deb", arch="x86_64").command[0] == "apt-get"


def test_no_package_manager_points_to_docker(monkeypatch):
    monkeypatch.setattr(inst, "package_kind", lambda: None)
    with pytest.raises(inst.InstallError, match="deb or rpm") as exc:
        inst.native_plan("1.0.385")
    assert "--docker" in exc.value.hint


@pytest.mark.skipif(os.name == "nt", reason="Linux packages")
def test_run_native_verifies_then_installs(monkeypatch, tmp_path):
    downloads, ran = [], []
    monkeypatch.setattr(inst, "_download", lambda url, dest: (downloads.append(url), dest.write_text("x")))
    monkeypatch.setattr(inst, "verify_signature", lambda pkg, sig, work: ran.append(("verify", pkg.name, sig.name)))
    monkeypatch.setattr(subprocess, "call", lambda cmd, cwd=None: ran.append(cmd) or 0)
    plan = inst.Plan(kind="deb", arch="x86_64", version="1.0.385",
                     url=inst.package_url("deb", "x86_64", "1.0.385"), verify=True,
                     command=["apt-get", "install", "-y", "./aws-emulator_1.0.385-1_amd64.deb"])
    assert inst.run_native(plan) == 0
    assert downloads == [plan.url, plan.url + ".sig"]
    assert ran[0] == ("verify", "aws-emulator_1.0.385-1_amd64.deb", "aws-emulator_1.0.385-1_amd64.deb.sig")
    assert ran[1][:3] == ["apt-get", "install", "-y"] and ran[1][3].endswith("aws-emulator_1.0.385-1_amd64.deb")


def test_verify_needs_gpg(monkeypatch, tmp_path):
    monkeypatch.setattr(inst.shutil, "which", lambda name: None)
    with pytest.raises(inst.InstallError, match="gpg"):
        inst.verify_signature(tmp_path / "p", tmp_path / "s", tmp_path)


def test_install_dry_run(runner, monkeypatch):
    monkeypatch.setattr(inst, "package_kind", lambda: "deb")
    result = runner.invoke(cli, ["install", "1.0.385", "--native", "--dry-run"])
    assert result.exit_code == 0, result.output
    assert f"{LTS}/aws-emulator_1.0.385-1_" in result.output
    assert ".sig, key 98BCF336A3BE53B734E967C52E5BF49BD940F624" in result.output

    docker = runner.invoke(cli, ["install", "1.0.385", "--docker", "--dry-run"])
    assert docker.exit_code == 0, docker.output
    assert "aws-emulator:1.0.385" in docker.output

    assert runner.invoke(cli, ["install", "1.0", "--dry-run"]).exit_code == 1
    assert runner.invoke(cli, ["install", "--json"]).exit_code == 2
    assert runner.invoke(cli, ["install", "--docker", "--native"]).exit_code == 2


def test_install_uses_the_pin_and_pins(runner, monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "awsemu.toml").write_text('# team settings\nport = 9400\nemulator_version = "1.0.385"\n')
    monkeypatch.setattr(inst, "package_kind", lambda: "deb")
    monkeypatch.setattr(inst, "run_native", lambda plan: 0)
    monkeypatch.setattr(fid, "installed_version", lambda binary=None: "1.0.385")

    dry = runner.invoke(cli, ["install", "--dry-run"])
    assert "1.0.385" in dry.output

    monkeypatch.setattr(fid, "installed_version", lambda binary=None: "1.0.390")
    result = runner.invoke(cli, ["install", "1.0.390", "--pin", "--yes"])
    assert result.exit_code == 0, result.output
    text = (tmp_path / "awsemu.toml").read_text()
    assert text == '# team settings\nport = 9400\nemulator_version = "1.0.390"\n'


def test_pin_latest_resolves_a_version(runner, monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(inst, "list_versions", lambda: ["1.0.390", "1.0.385"])
    monkeypatch.setattr(runtime, "docker_available", lambda: True)
    monkeypatch.setattr(runtime, "build_image", lambda tag, arch, version: 0)
    result = runner.invoke(cli, ["install", "--docker", "--pin"])
    assert result.exit_code == 0, result.output
    assert project.parse(tmp_path / "awsemu.toml").emulator_version == "1.0.390"
    assert "awsemu start --docker" in result.output


def test_pin_in_pyproject(tmp_path):
    path = tmp_path / "pyproject.toml"
    path.write_text('[project]\nname = "x"\n\n[tool.awsemu]\nport = 9400\n')
    project.set_value("emulator_version", "1.0.385", path)
    assert project.parse(path).emulator_version == "1.0.385"
    assert path.read_text().startswith('[project]\nname = "x"\n')


def test_bad_pin_is_rejected(tmp_path):
    path = tmp_path / "awsemu.toml"
    path.write_text('emulator_version = "latest"\n')
    with pytest.raises(project.ProjectError, match="emulator_version"):
        project.parse(path)


def test_list(runner, monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "awsemu.toml").write_text('emulator_version = "v1.0.385"\n')
    monkeypatch.setattr(inst, "list_versions", lambda: ["1.0.390", "1.0.385"])
    monkeypatch.setattr(fid, "installed_version", lambda binary=None: "1.0.390")
    result = runner.invoke(cli, ["install", "--list"])
    assert "1.0.390  (installed)" in result.output and "1.0.385  (pinned)" in result.output
    data = json.loads(runner.invoke(cli, ["install", "--list", "--json"]).output)
    assert data == {"versions": ["1.0.390", "1.0.385"], "installed": "1.0.390", "pinned": "1.0.385"}


def test_pin_picks_the_docker_image(monkeypatch, tmp_path):
    from awsemu import cli as cli_mod

    monkeypatch.chdir(tmp_path)
    (tmp_path / "awsemu.toml").write_text('emulator_version = "1.0.385"\n')
    project.clear_cache()
    opts = cli_mod._start_options(9297, True, False, None, None, None, None, None, ())
    assert opts.image == "aws-emulator:1.0.385"
    opts = cli_mod._start_options(9297, True, False, None, None, None, "mine", None, ())
    assert opts.image == "mine"


def test_start_and_doctor_warn_about_a_different_version(runner, fake_binary, monkeypatch, tmp_path, free_port):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "awsemu.toml").write_text('emulator_version = "1.0.1"\n')
    project.clear_cache()
    monkeypatch.setattr(fid, "installed_version", lambda binary=None: "1.0.385")
    started = runner.invoke(cli, ["--port", str(free_port), "start", "--native"])
    try:
        assert "pins emulator 1.0.1, but 1.0.385 is installed" in started.output
        doctor = json.loads(runner.invoke(cli, ["--port", str(free_port), "doctor", "--json"]).output)
        check = {c["check"]: c for c in doctor["checks"]}["emulator version"]
        assert check["result"] == "warn" and check["fix"] == "awsemu install 1.0.1"
    finally:
        runner.invoke(cli, ["--port", str(free_port), "stop"])
