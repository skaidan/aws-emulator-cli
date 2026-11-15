"""Project settings (awsemu.toml / [tool.awsemu]) and up/down/init."""

import json

import pytest

from awsemu import project, runtime
from awsemu.cli import cli
from awsemu.paths import default_port


@pytest.fixture
def proj_dir(tmp_path, monkeypatch):
    root = tmp_path / "myapp"
    (root / "src" / "deep").mkdir(parents=True)
    monkeypatch.chdir(root)
    return root


def test_found_from_subfolders(proj_dir, monkeypatch):
    (proj_dir / "awsemu.toml").write_text('port = 9311\nmode = "native"\nseed = "tests/seed.yaml"\nsdk = ["node"]\n')
    monkeypatch.chdir(proj_dir / "src" / "deep")
    p = project.load()
    assert p.path == proj_dir / "awsemu.toml"
    assert (p.port, p.mode, p.sdk) == (9311, "native", ["node"])
    assert p.seed == proj_dir / "tests" / "seed.yaml"  # relative to the file, not the cwd


def test_pyproject_tool_table(proj_dir):
    (proj_dir / "pyproject.toml").write_text('[project]\nname = "x"\n\n[tool.awsemu]\nport = 9322\n')
    assert project.load().port == 9322


def test_pyproject_without_table_is_ignored(proj_dir):
    (proj_dir / "pyproject.toml").write_text('[project]\nname = "x"\n')
    assert project.load() is None


def test_awsemu_config_env(tmp_path, monkeypatch):
    cfg = tmp_path / "elsewhere.toml"
    cfg.write_text("port = 9333\n")
    monkeypatch.setenv("AWSEMU_CONFIG", str(cfg))
    assert project.load().port == 9333


@pytest.mark.parametrize("text,needle", [
    ('port = "9297"\n', "'port' must be int"),
    ("prot = 1\n", "did you mean 'port'?"),
    ('mode = "podman"\n', "'mode' must be one of auto, native, docker"),
    ('sdk = ["go"]\n', "'sdk' accepts"),
    ("port = 70000\n", "between 1 and 65535"),
    ("port = [\n", "invalid TOML"),
])
def test_errors(proj_dir, text, needle):
    (proj_dir / "awsemu.toml").write_text(text)
    with pytest.raises(project.ProjectError, match=None) as info:
        project.load()
    assert needle in str(info.value)


def test_cli_reports_bad_project(runner, proj_dir):
    (proj_dir / "awsemu.toml").write_text("mdoe = 1\n")
    result = runner.invoke(cli, ["status"])
    assert result.exit_code == 2 and "did you mean 'mode'?" in result.output


def test_port_precedence(proj_dir, monkeypatch):
    assert default_port() == 9297
    (proj_dir / "awsemu.toml").write_text("port = 9344\n")
    assert default_port() == 9344
    monkeypatch.setenv("AWSEMU_PORT", "9355")
    assert default_port() == 9355


def test_env_uses_project_port_and_sdk(runner, proj_dir):
    (proj_dir / "awsemu.toml").write_text('port = 9345\nsdk = ["node"]\n')
    out = runner.invoke(cli, ["env", "--shell", "bash"]).output
    assert "AWS_ENDPOINT_URL=https://127.0.0.1:9345" in out and "NODE_EXTRA_CA_CERTS" in out
    out = runner.invoke(cli, ["--port", "9346", "env", "--shell", "bash"]).output
    assert "127.0.0.1:9346" in out  # the flag wins


def test_init_writes_template(runner, proj_dir):
    (proj_dir / "tests").mkdir()
    (proj_dir / "tests" / "seed.yaml").write_text("version: 1\n")
    result = runner.invoke(cli, ["init"])
    assert result.exit_code == 0, result.output
    p = project.parse(proj_dir / "awsemu.toml")
    assert 9300 <= p.port <= 9399 and p.seed == proj_dir / "tests" / "seed.yaml"
    assert p.telemetry is False and p.idle_timeout == 3600
    assert runner.invoke(cli, ["init"]).exit_code == 1  # exists
    result = runner.invoke(cli, ["--port", "9400", "init", "--force"])
    assert result.exit_code == 0 and project.parse(proj_dir / "awsemu.toml").port == 9400


def test_up_down_with_project(runner, fake_binary, free_port, proj_dir):
    (proj_dir / "awsemu.toml").write_text(
        f'port = {free_port}\nmode = "native"\nauth = false\ntelemetry = false\nidle_timeout = 600\n')
    result = runner.invoke(cli, ["up"])
    assert result.exit_code == 0, result.output
    assert "project:" in result.output and f"127.0.0.1:{free_port}" in result.output
    try:
        cmd = runtime.State.load(free_port).command
        assert cmd[-7:] == ["-p", str(free_port), "-a", "off", "-t", "off", "--idle-timeout", "600"][-7:]
        assert "--idle-timeout" in cmd and "-a" in cmd
        again = runner.invoke(cli, ["up"])
        assert again.exit_code == 0 and "already running" in again.output
        info = json.loads(runner.invoke(cli, ["status", "--json"]).output)
        assert info["port"] == free_port and info["status"] == "healthy"
    finally:
        result = runner.invoke(cli, ["down"])
    assert result.exit_code == 0 and "stopped pid" in result.output


def test_example_project_file_is_valid():
    from pathlib import Path

    example = Path(__file__).resolve().parents[1] / "examples" / "awsemu.toml"
    p = project.parse(example)
    assert p.port == 9343 and p.seed == example.parent / "seed.yaml" and p.seed.is_file()
