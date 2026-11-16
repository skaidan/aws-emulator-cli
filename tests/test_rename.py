"""scripts/rename.py, run on a copy of the repository."""

import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def repo_copy(tmp_path):
    try:
        files = subprocess.run(["git", "ls-files", "--cached", "--others", "--exclude-standard"], cwd=ROOT, capture_output=True, text=True,
                               check=True).stdout.splitlines()
    except (OSError, subprocess.CalledProcessError):
        pytest.skip("needs a git checkout")
    dest = tmp_path / "repo"
    for rel in files:
        src = ROOT / rel
        if src.is_file():
            (dest / rel).parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dest / rel)
    return dest


def names(repo):
    meta = (repo / "src" / "awsemu" / "_meta.py").read_text()
    dist = meta.split('DIST_NAME = "', 1)[1].split('"', 1)[0]
    slug = meta.split('REPO = "', 1)[1].split('"', 1)[0]
    return dist, slug


def run(repo, *args):
    return subprocess.run([sys.executable, str(repo / "scripts" / "rename.py"), *args],
                          cwd=repo, capture_output=True, text=True)


def test_check_lists_occurrences(repo_copy):
    out = run(repo_copy, "--check")
    assert out.returncode == 0
    assert "pyproject.toml:" in out.stdout and "src/awsemu/_meta.py:" in out.stdout
    assert not any(line.startswith("CHANGELOG.md:") for line in out.stdout.splitlines())


def test_rename_everywhere(repo_copy):
    old_dist, _ = names(repo_copy)
    before_changelog = (repo_copy / "CHANGELOG.md").read_text()
    out = run(repo_copy, "--package", "emu-pal", "--repo", "someone/emu-pal")
    assert out.returncode == 0, out.stderr
    assert f"Renamed {old_dist} -> emu-pal" in out.stdout
    assert names(repo_copy) == ("emu-pal", "someone/emu-pal")
    assert 'name = "emu-pal"' in (repo_copy / "pyproject.toml").read_text()
    meta = (repo_copy / "src" / "awsemu" / "_meta.py").read_text()
    assert 'DIST_NAME = "emu-pal"' in meta and 'REPO = "someone/emu-pal"' in meta
    assert "uses: someone/emu-pal@" in (repo_copy / "README.md").read_text()
    assert (repo_copy / "CHANGELOG.md").read_text() == before_changelog
    left = subprocess.run(["grep", "-rIl", "--exclude=CHANGELOG.md", "-e", old_dist,
                           "-e", old_dist.replace("-", "_"), str(repo_copy)], capture_output=True, text=True)
    assert left.stdout == "", left.stdout


def test_dry_run_changes_nothing(repo_copy):
    before = (repo_copy / "pyproject.toml").read_text()
    out = run(repo_copy, "--package", "emu-pal", "--dry-run")
    assert out.returncode == 0 and "would change pyproject.toml" in out.stdout
    assert (repo_copy / "pyproject.toml").read_text() == before


@pytest.mark.parametrize("args", [["--package", "Bad Name"], ["--package", "ok", "--repo", "no-slash"]])
def test_rejects_bad_names(repo_copy, args):
    assert run(repo_copy, *args).returncode == 2
