#!/usr/bin/env python3
"""Rename the package (and repository) everywhere in one go.

    python scripts/rename.py --check
        List every place the current names appear.

    python scripts/rename.py --package NEW-NAME [--repo OWNER/NEW-REPO] [--dry-run]
        Replace the distribution name (``aws-emulator-cli``), its wheel form
        (``aws_emulator_cli``) and the repository slug in every tracked text file,
        then verify nothing old is left. CHANGELOG.md is left alone: it's history.

The command name (``awsemu``), the Python package (``awsemu``), environment
variables (``AWSEMU_*``) and ``awsemu.toml`` don't change.
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
META = ROOT / "src" / "awsemu" / "_meta.py"
KEEP = {"CHANGELOG.md"}  # historical record: old names stay
NAME_RE = re.compile(r"^[a-z0-9][a-z0-9-]*[a-z0-9]$")
REPO_RE = re.compile(r"^[A-Za-z0-9-]+/[A-Za-z0-9._-]+$")


def current() -> tuple[str, str]:
    text = META.read_text(encoding="utf-8")
    dist = re.search(r'^DIST_NAME = "([^"]+)"', text, re.M).group(1)
    repo = re.search(r'^REPO = "([^"]+)"', text, re.M).group(1)
    return dist, repo


def tracked_files() -> list[Path]:
    try:
        out = subprocess.run(
            ["git", "ls-files", "--cached", "--others", "--exclude-standard"],
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=True,
        ).stdout
        files = [ROOT / line for line in out.splitlines() if line]
    except (OSError, subprocess.CalledProcessError):  # not a git checkout: walk the tree
        files = [p for p in ROOT.rglob("*") if p.is_file() and ".git" not in p.parts]
    out_files = []
    for f in files:
        if not f.is_file() or f.name in KEEP or f.suffix in (".gz", ".png", ".jpg", ".zip"):
            continue
        try:
            f.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        out_files.append(f)
    return out_files


def patterns(dist: str, repo: str) -> list[str]:
    return [repo, dist, dist.replace("-", "_")]


def occurrences(dist: str, repo: str) -> dict[Path, list[tuple[int, str]]]:
    found: dict[Path, list[tuple[int, str]]] = {}
    pats = patterns(dist, repo)
    for f in tracked_files():
        for n, line in enumerate(f.read_text(encoding="utf-8").splitlines(), 1):
            if any(p in line for p in pats):
                found.setdefault(f, []).append((n, line.strip()))
    return found


def rename(new_dist: str, new_repo: str, dry_run: bool) -> int:
    old_dist, old_repo = current()
    pairs = [(old_repo, new_repo), (old_dist, new_dist), (old_dist.replace("-", "_"), new_dist.replace("-", "_"))]
    changed = 0
    for f in tracked_files():
        text = f.read_text(encoding="utf-8")
        new = text
        for old, rep in pairs:  # repository first: it contains the package name
            new = new.replace(old, rep)
        if new != text:
            changed += 1
            print(f"  {'would change' if dry_run else 'changed'} {f.relative_to(ROOT).as_posix()}")
            if not dry_run:
                f.write_text(new, encoding="utf-8")
    if dry_run:
        print(f"{changed} file(s) would change.")
        return 0
    left = occurrences(old_dist, old_repo)
    if left:
        print("Old names still present:", file=sys.stderr)
        for f, lines in left.items():
            for n, line in lines:
                print(f"  {f.relative_to(ROOT).as_posix()}:{n}: {line}", file=sys.stderr)
        return 1
    dist, repo = current()
    assert (dist, repo) == (new_dist, new_repo), (dist, repo)
    print(f"Renamed {old_dist} -> {new_dist}, {old_repo} -> {new_repo} in {changed} file(s).")
    print("Next: rename the GitHub repository, update your git remote, run the tests and add a CHANGELOG entry.")
    return 0


def main(argv: list[str] | None = None) -> int:
    # Files contain non-ASCII text (e.g. emoji in ROADMAP.md); Windows consoles
    # default to a legacy code page that can't print it.
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--check", action="store_true", help="List where the current names appear.")
    ap.add_argument("--package", help="New distribution name, e.g. my-emu-cli.")
    ap.add_argument("--repo", help="New GitHub OWNER/NAME (default: same owner, NAME = --package).")
    ap.add_argument("--dry-run", action="store_true", help="Show what would change without writing.")
    args = ap.parse_args(argv)

    dist, repo = current()
    if args.check or not args.package:
        found = occurrences(dist, repo)
        total = sum(len(v) for v in found.values())
        for f, lines in found.items():
            for n, line in lines:
                print(f"{f.relative_to(ROOT).as_posix()}:{n}: {line[:120]}")
        print(f"\n'{dist}' / '{repo}': {total} line(s) in {len(found)} file(s) (CHANGELOG.md not counted).")
        return 0

    new_dist = args.package.lower()
    if not NAME_RE.match(new_dist):
        ap.error("--package must be lowercase letters, digits and hyphens")
    new_repo = args.repo or f"{repo.split('/')[0]}/{new_dist}"
    if not REPO_RE.match(new_repo):
        ap.error("--repo must look like OWNER/NAME")
    if (new_dist, new_repo) == (dist, repo):
        print("Nothing to do: those are the current names.")
        return 0
    return rename(new_dist, new_repo, args.dry_run)


if __name__ == "__main__":
    sys.exit(main())
