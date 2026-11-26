"""A Java truststore that trusts the emulator *and* everything Java already trusted.

The emulator writes ``truststore.p12`` with only its own certificate. Pointing the JVM
at it (``-Djavax.net.ssl.trustStore``) makes every other HTTPS connection of that
process fail: Maven or Gradle downloading dependencies, a call to a real service.
So with ``keytool`` (part of every JDK) awsemu builds a copy of the truststore Java
was using (yours, from ``JAVA_TOOL_OPTIONS``, or the JDK's ``cacerts``) with the
emulator's certificate added. It's rebuilt when either of them changes (the emulator
makes a new certificate on every start).
"""

from __future__ import annotations

import os
import shlex
import shutil
import subprocess
from pathlib import Path

from .paths import InstanceFiles, cli_root

PASSWORD = "awsemu-truststore"  # protects nothing: a truststore holds only public certificates
DEFAULT_PASSWORD = "changeit"  # the JDK's cacerts


def _option(options: list[str], name: str) -> str | None:
    prefix = f"-D{name}="
    return next((o[len(prefix):] for o in reversed(options) if o.startswith(prefix)), None)


def keytool() -> str | None:
    found = shutil.which("keytool")
    if found:
        return found
    home = os.environ.get("JAVA_HOME")
    if home and Path(home, "bin", "keytool").exists():
        return str(Path(home, "bin", "keytool"))
    if home and Path(home, "bin", "keytool.exe").exists():
        return str(Path(home, "bin", "keytool.exe"))
    return None


def jdk_cacerts(tool: str) -> Path | None:
    """``cacerts`` of the JDK the keytool belongs to (or of JAVA_HOME)."""
    candidates = []
    if os.environ.get("JAVA_HOME"):
        candidates.append(Path(os.environ["JAVA_HOME"], "lib", "security", "cacerts"))
    try:
        home = Path(tool).resolve().parent.parent
        candidates += [home / "lib" / "security" / "cacerts", home / "jre" / "lib" / "security" / "cacerts"]
    except OSError:  # pragma: no cover
        pass
    return next((c for c in candidates if c.is_file()), None)


def source_store(current_options: str, tool: str) -> tuple[Path, str] | None:
    """The truststore Java uses now, and its password."""
    options = shlex.split(current_options)
    path = _option(options, "javax.net.ssl.trustStore")
    if path and Path(path).is_file():
        return Path(path), _option(options, "javax.net.ssl.trustStorePassword") or DEFAULT_PASSWORD
    cacerts = jdk_cacerts(tool)
    return (cacerts, DEFAULT_PASSWORD) if cacerts else None


def combined(port: int, current_options: str = "", also: Path | None = None) -> tuple[Path, str | None]:
    """``(truststore, password)`` for ``--sdk java``.

    The combined one when keytool and a source truststore are found, else the
    emulator's own (``password`` None: it has none). ``also`` adds another
    certificate (the proxy's), in a separate truststore.
    """
    files = InstanceFiles(port)
    tool = keytool()
    if not tool or not files.ca.exists():
        return files.truststore, None
    source = source_store(current_options, tool)
    if not source:
        return files.truststore, None
    src, src_password = source
    out = cli_root() / "java" / (f"truststore-{port}-proxy.p12" if also else f"truststore-{port}.p12")
    try:
        newest = max(files.ca.stat().st_mtime, src.stat().st_mtime, also.stat().st_mtime if also else 0)
        if out.exists() and out.stat().st_mtime >= newest:
            return out, PASSWORD
    except OSError:
        return files.truststore, None
    out.parent.mkdir(parents=True, exist_ok=True)
    tmp = out.with_suffix(".tmp.p12")
    tmp.unlink(missing_ok=True)
    try:
        subprocess.run([tool, "-importkeystore", "-noprompt", "-srckeystore", str(src), "-srcstorepass", src_password,
                        "-destkeystore", str(tmp), "-deststoretype", "PKCS12", "-deststorepass", PASSWORD],
                       check=True, capture_output=True, timeout=60)
        subprocess.run([tool, "-importcert", "-noprompt", "-alias", f"awsemu-emulator-{port}", "-file", str(files.ca),
                        "-keystore", str(tmp), "-storetype", "PKCS12", "-storepass", PASSWORD],
                       check=True, capture_output=True, timeout=60)
        if also:
            subprocess.run([tool, "-importcert", "-noprompt", "-alias", "awsemu-proxy", "-file", str(also),
                            "-keystore", str(tmp), "-storetype", "PKCS12", "-storepass", PASSWORD],
                           check=True, capture_output=True, timeout=60)
        tmp.replace(out)
    except (OSError, subprocess.SubprocessError):
        tmp.unlink(missing_ok=True)
        return files.truststore, None
    return out, PASSWORD
