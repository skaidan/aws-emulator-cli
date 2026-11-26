"""Renamed options and settings keep working, with one warning."""

import click
from click.testing import CliRunner

from awsemu import deprecation, project


def test_renamed_setting_keeps_working(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(deprecation, "RENAMED_SETTINGS", {"emulator_port": ("port", "1.2")})
    monkeypatch.setattr(deprecation, "_warned", set())
    (tmp_path / "awsemu.toml").write_text("emulator_port = 9400\n")
    proj = project.parse(tmp_path / "awsemu.toml")
    assert proj.port == 9400
    err = capsys.readouterr()
    text = err.out + err.err
    assert "'emulator_port'" in text and "use 'port'" in text and "awsemu 1.2" in text
    (tmp_path / "awsemu.toml").write_text("emulator_port = 9400\nport = 9500\n")
    assert project.parse(tmp_path / "awsemu.toml").port == 9500  # the new name wins


def test_option_alias(monkeypatch):
    monkeypatch.setattr(deprecation, "_warned", set())

    @click.command()
    @click.option("--timeout", type=int)
    @deprecation.option_alias("--wait-seconds", "timeout", "--timeout", "1.2", type=int)
    def cmd(timeout):
        click.echo(f"timeout={timeout}")

    runner = CliRunner()
    old = runner.invoke(cmd, ["--wait-seconds", "5"])
    assert old.exit_code == 0 and "timeout=5" in old.output and "--wait-seconds is deprecated" in old.output
    assert runner.invoke(cmd, ["--timeout", "7"]).output.strip() == "timeout=7"
    both = runner.invoke(cmd, ["--timeout", "7", "--wait-seconds", "5"])
    assert "timeout=7" in both.output  # the new option wins
    assert "--wait-seconds" not in runner.invoke(cmd, ["--help"]).output  # hidden
