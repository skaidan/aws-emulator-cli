"""Project identity, in one place.

The package and repository names are expected to change before v1.0 (see
ROADMAP). Code reads them from here; ``scripts/rename.py`` changes them here
and everywhere else in one go.
"""

DIST_NAME = "aws-emulator-cli"          # name on PyPI / pip
REPO = "skaidan/aws-emulator-cli"       # GitHub owner/name
COMMAND = "awsemu"                      # the command people type

REPO_URL = f"https://github.com/{REPO}"
DOCS_URL = f"{REPO_URL}/blob/main/docs"


def install_hint(extra: str | None = None) -> str:
    """How to (re)install, optionally with an extra, e.g. ``pip install 'x[ui]'``."""
    return f"pip install '{DIST_NAME}[{extra}]'" if extra else f"pip install {DIST_NAME}"
