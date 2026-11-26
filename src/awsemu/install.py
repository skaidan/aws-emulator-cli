"""Install a given AWS Emulator version: the Linux package, or a Docker image.

Packages come from AWS (https://downloads.aws.com/aws-emulator/packages/aws-emulator/LTS/),
where every release is published by version and ``latest/`` holds the newest one.
Each package has a ``.sig`` next to it; awsemu checks it with GnuPG against AWS's
signing key (fingerprint below) before installing, as AWS's guide describes.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path

from . import fidelity as fid
from .runtime import IS_WINDOWS, RuntimeErrorWithHint, detect_arch

LTS = "https://downloads.aws.com/aws-emulator/packages/aws-emulator/LTS"
VERSIONS_URL = f"{LTS}/versions.json"
KEY_URL = "https://downloads.aws.com/keys/gpg/current.asc"
KEY_UID = "ssm-publishing@amazon.com"
KEY_FINGERPRINT = "98BCF336A3BE53B734E967C52E5BF49BD940F624"
VERSION_RE = re.compile(r"^\d+\.\d+\.\d+$")
LISTED_RE = re.compile(r"^v?(\d+\.\d+\.\d+)(?:\.\d+)?$")  # versions.json says "1.0.471.1"

DEB_ARCH = {"x86_64": "amd64", "aarch64": "arm64"}


class InstallError(RuntimeErrorWithHint):
    pass


def normalize(version: str | None) -> str | None:
    """``v1.0.385`` -> ``1.0.385``; ``latest``/None -> None. Rejects anything else."""
    if version is None or version == "latest":
        return None
    v = version.lstrip("v")
    if not VERSION_RE.match(v):
        raise InstallError(f"'{version}' isn't a version", "Use a version like 1.0.385, or 'latest'.")
    return v


def package_file(kind: str, arch: str, version: str | None) -> str:
    if kind == "deb":
        a = DEB_ARCH[arch]
        return f"aws-emulator_{version}-1_{a}.deb" if version else f"aws-emulator_{a}.deb"
    return f"aws-emulator-{version}-1-{arch}.rpm" if version else f"aws-emulator-{arch}.rpm"


def package_url(kind: str, arch: str, version: str | None) -> str:
    folder = LTS if version else f"{LTS}/latest"
    return f"{folder}/{package_file(kind, arch, version)}"


def package_kind() -> str | None:
    """``deb`` or ``rpm`` for this machine, None if it can't install either."""
    if IS_WINDOWS or os.uname().sysname != "Linux":
        return None
    if shutil.which("dpkg") and shutil.which("apt-get"):
        return "deb"
    if shutil.which("rpm"):
        return "rpm"
    return None


# --------------------------------------------------------------------------- versions


def parse_versions(data: bytes) -> list[str]:
    """Versions in ``versions.json``, newest first.

    Today it is ``{"versions": [{"productId": "aws-emulator", "releaseStream": "LTS",
    "version": "1.0.191.1"}, ...]}``, the last number being the package release (the
    ``-1`` in the file names); any other shape with version strings works too.
    """
    try:
        doc = json.loads(data)
    except ValueError as exc:
        raise InstallError(f"versions.json isn't JSON: {exc}") from exc
    found: set[str] = set()

    def walk(x) -> None:
        if isinstance(x, str):
            m = LISTED_RE.match(x)
            if m:
                found.add(m.group(1))
        elif isinstance(x, dict):
            for k, v in x.items():
                walk(k)
                walk(v)
        elif isinstance(x, list):
            for v in x:
                walk(v)

    walk(doc)
    return sorted(found, key=lambda v: tuple(map(int, v.split("."))), reverse=True)


def list_versions() -> list[str]:
    """Published versions, newest first (AWS's list, else the GitHub releases)."""
    try:
        versions = parse_versions(fid._get(VERSIONS_URL, accept="application/json"))
        if versions:
            return versions
    except (fid.FidelityError, InstallError):
        pass
    try:
        return [t.lstrip("v") for t in fid.list_releases(100) if VERSION_RE.match(t.lstrip("v"))]
    except fid.FidelityError as exc:
        raise InstallError(f"couldn't list versions: {exc}", "Check your connection.") from exc


# --------------------------------------------------------------------------- native


@dataclass
class Plan:
    kind: str
    arch: str
    version: str | None
    url: str
    verify: bool
    command: list[str]

    def describe(self) -> list[tuple[str, str]]:
        return [
            ("version", self.version or "latest"),
            ("package", self.url),
            ("signature", f"{self.url}.sig, key {KEY_FINGERPRINT}" if self.verify else "not checked (--no-verify)"),
            ("install with", " ".join(self.command)),
        ]


def _sudo() -> list[str]:
    if IS_WINDOWS or os.geteuid() == 0:
        return []
    if shutil.which("sudo"):
        return ["sudo"]
    raise InstallError(
        "installing a system package needs root, and sudo isn't available", "Run awsemu install as root."
    )


def install_command(kind: str, path: str) -> list[str]:
    if kind == "deb":
        return [*_sudo(), "apt-get", "install", "-y", "--allow-downgrades", path]
    return [*_sudo(), "rpm", "-U", "--oldpackage", "--replacepkgs", path]


def native_plan(version: str | None, verify: bool = True, arch: str | None = None, kind: str | None = None) -> Plan:
    kind = kind or package_kind()
    if kind is None:
        raise InstallError(
            "this machine can't install the emulator's Linux packages (deb or rpm)",
            "Use 'awsemu install --docker' (macOS, Windows, other Linux).",
        )
    arch = arch or detect_arch()
    url = package_url(kind, arch, version)
    return Plan(
        kind=kind,
        arch=arch,
        version=version,
        url=url,
        verify=verify,
        command=install_command(kind, f"./{package_file(kind, arch, version)}"),
    )


def _download(url: str, dest: Path) -> None:
    try:
        dest.write_bytes(fid._get(url, accept="application/octet-stream"))
    except fid.FidelityError as exc:
        if "not found" in str(exc):
            raise InstallError(f"{url} doesn't exist", "Check the version: awsemu install --list") from exc
        raise InstallError(str(exc)) from exc


def verify_signature(package: Path, signature: Path, workdir: Path) -> str:
    """Check ``signature`` with AWS's key in a throwaway keyring. Returns the gpg output."""
    gpg = shutil.which("gpg")
    if not gpg:
        raise InstallError(
            "gpg isn't installed, so the package signature can't be checked",
            "Install gnupg, or pass --no-verify to skip the check.",
        )
    home = workdir / "gnupg"
    home.mkdir(mode=0o700)
    env = {**os.environ, "GNUPGHOME": str(home)}
    key = workdir / "key.asc"
    _download(KEY_URL, key)
    subprocess.run([gpg, "--batch", "--quiet", "--import", str(key)], env=env, check=True, capture_output=True)
    out = subprocess.run(
        [gpg, "--batch", "--with-colons", "--fingerprint", KEY_UID], env=env, capture_output=True, text=True
    ).stdout
    fingerprints = [line.split(":")[9] for line in out.splitlines() if line.startswith("fpr:")]
    if KEY_FINGERPRINT not in fingerprints:
        raise InstallError(
            f"AWS's signing key has an unexpected fingerprint ({', '.join(fingerprints) or 'none'})",
            f"Expected {KEY_FINGERPRINT}. Don't install; check AWS's documentation.",
        )
    result = subprocess.run(
        [gpg, "--batch", "--verify", str(signature), str(package)], env=env, capture_output=True, text=True
    )
    if result.returncode != 0:
        raise InstallError("the package signature is NOT valid", result.stderr.strip()[-300:])
    return result.stderr


def run_native(plan: Plan) -> int:
    with tempfile.TemporaryDirectory(prefix="awsemu-install-") as tmp:
        work = Path(tmp)
        name = package_file(plan.kind, plan.arch, plan.version)
        package = work / name
        _download(plan.url, package)
        if plan.verify:
            signature = work / f"{name}.sig"
            _download(f"{plan.url}.sig", signature)
            verify_signature(package, signature, work)
        command = [str(package) if part == f"./{name}" else part for part in plan.command]
        return subprocess.call(command, cwd=tmp)


# --------------------------------------------------------------------------- docker


def image_tag(version: str | None, base: str = "aws-emulator") -> str:
    return f"{base}:{version}" if version else base
