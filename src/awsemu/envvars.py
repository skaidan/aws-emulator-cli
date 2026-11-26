"""Environment variables that point the AWS CLI and SDKs at the emulator.

Mirrors "Pointing your AWS SDK at AWS Emulator" from the official docs.
"""

from __future__ import annotations

import os
import shlex
from collections.abc import Iterable, Mapping

from .paths import REGION, InstanceFiles

# Variables that could supply real credentials. They take precedence over the
# credentials file, so they must be removed or the emulator rejects requests.
REAL_CREDENTIAL_VARS = (
    "AWS_ACCESS_KEY_ID",
    "AWS_SECRET_ACCESS_KEY",
    "AWS_SESSION_TOKEN",
    "AWS_PROFILE",
)

# With --auth off the emulator writes no credentials file and accepts any signature,
# but the SDKs still need keys to sign with: without these they fail ("unable to locate
# credentials") or, worse, pick up your real default profile from ~/.aws/credentials.
AUTH_OFF_KEYS = ("EMULATORAUTHOFF00000", "0" * 40)

SHELLS = ("bash", "zsh", "fish", "powershell", "dotenv")

EXTRAS = ("node", "java", "rust", "dotnet")


def emulator_env(port: int, extras: Iterable[str] = ()) -> dict[str, str]:
    """Variables to set for an emulator on ``port``.

    ``extras`` adds the certificate setting for SDKs that don't read
    ``AWS_CA_BUNDLE`` (node, java, rust, dotnet).
    """
    from .traps import no_proxy_value

    files = InstanceFiles(port)
    env = {
        "AWS_ENDPOINT_URL": files.endpoint_url,
        "AWS_CONFIG_FILE": str(files.config),
        "AWS_CA_BUNDLE": str(files.ca),
        "AWS_EC2_METADATA_DISABLED": "true",
        "AWS_DISABLE_HOST_PREFIX_INJECTION": "true",
        "AWS_REGION": REGION,
        "AWS_DEFAULT_REGION": REGION,
    }
    # The emulator only writes a credentials file when auth is on. If the
    # instance isn't running yet we assume the default (auth on).
    if files.auth_enabled() or not files.exists():
        env["AWS_SHARED_CREDENTIALS_FILE"] = str(files.credentials)
    else:
        env["AWS_ACCESS_KEY_ID"], env["AWS_SECRET_ACCESS_KEY"] = AUTH_OFF_KEYS

    extras = {e.lower() for e in extras}
    unknown = extras - set(EXTRAS)
    if unknown:
        raise ValueError(f"unknown extra(s): {', '.join(sorted(unknown))}")
    if "node" in extras:
        env["NODE_EXTRA_CA_CERTS"] = str(files.ca)
    if "java" in extras:
        env["JAVA_TOOL_OPTIONS"] = (
            f"-Djavax.net.ssl.trustStore={files.truststore} "
            "-Djavax.net.ssl.trustStoreType=PKCS12"
        )
    if "rust" in extras or "dotnet" in extras:
        env["SSL_CERT_FILE"] = str(files.ca)
    bypass = no_proxy_value(os.environ)  # an HTTP(S) proxy must not get the emulator's calls
    if bypass:
        env["NO_PROXY"] = env["no_proxy"] = bypass
    return env


def child_env(port: int, base: Mapping[str, str] | None = None,
              extras: Iterable[str] = ()) -> dict[str, str]:
    """A full process environment for running a command against the emulator."""
    env = dict(os.environ if base is None else base)
    for var in REAL_CREDENTIAL_VARS:
        env.pop(var, None)
    env.update(emulator_env(port, extras))
    return env


def _ps_quote(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def _fish_quote(value: str) -> str:
    return "'" + value.replace("\\", "\\\\").replace("'", "\\'") + "'"


def render(env: Mapping[str, str], shell: str = "bash", unset_real: bool = True) -> str:
    """Render ``env`` as a script for ``shell`` (for ``eval "$(awsemu env)"``)."""
    shell = shell.lower()
    lines: list[str] = []
    if shell in ("bash", "zsh", "sh"):
        if unset_real:
            lines.append("unset " + " ".join(REAL_CREDENTIAL_VARS))
        lines += [f"export {k}={shlex.quote(v)}" for k, v in env.items()]
    elif shell == "fish":
        if unset_real:
            lines += [f"set -e {v}" for v in REAL_CREDENTIAL_VARS]
        lines += [f"set -gx {k} {_fish_quote(v)}" for k, v in env.items()]
    elif shell in ("powershell", "pwsh"):
        if unset_real:
            names = ", ".join(f"Env:{v}" for v in REAL_CREDENTIAL_VARS)
            lines.append(f"Remove-Item {names} -ErrorAction SilentlyContinue")
        lines += [f"$env:{k} = {_ps_quote(v)}" for k, v in env.items()]
    elif shell == "dotenv":
        lines += [f"{k}={v}" for k, v in env.items()]
    else:
        raise ValueError(f"unsupported shell: {shell}")
    return "\n".join(lines) + "\n"


def render_unset(env_names: Iterable[str], shell: str = "bash") -> str:
    """Script that undoes :func:`render` (for ``eval "$(awsemu env --unset)"``)."""
    names = list(env_names)
    shell = shell.lower()
    if shell in ("bash", "zsh", "sh"):
        return "unset " + " ".join(names) + "\n"
    if shell == "fish":
        return "\n".join(f"set -e {n}" for n in names) + "\n"
    if shell in ("powershell", "pwsh"):
        joined = ", ".join(f"Env:{n}" for n in names)
        return f"Remove-Item {joined} -ErrorAction SilentlyContinue\n"
    raise ValueError(f"unsupported shell for --unset: {shell}")


def detect_shell() -> str:
    if os.name == "nt":
        return "powershell"
    name = os.path.basename(os.environ.get("SHELL", "bash"))
    return name if name in ("bash", "zsh", "fish") else "bash"
