#!/usr/bin/env bash
# A CycloneDX SBOM of the built wheel and what it installs: the wheel goes into a clean
# virtual environment, and cyclonedx-py (installed elsewhere) describes that environment.
# Usage: scripts/sbom.sh OUTPUT.json   (after python -m build)
set -euo pipefail
out="$1"
env_dir="$(mktemp -d)/env"
python -m venv "$env_dir"
"$env_dir/bin/pip" install -q dist/*.whl
python -m pip install -q "cyclonedx-bom>=5,<8"
python -m cyclonedx_py environment "$env_dir/bin/python" --pyproject pyproject.toml \
  --output-format JSON --output-file "$out"
