"""Write docs/schemas/*.schema.json from awsemu.schemas (``--check``: fail if they're stale)."""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from awsemu import _meta, schemas  # noqa: E402

OUT = ROOT / "docs" / "schemas"
BASE_URL = f"https://raw.githubusercontent.com/{_meta.REPO}/main/docs/schemas"


def render() -> dict[str, str]:
    files = {
        f"{name}.schema.json": json.dumps(schemas.document(name, BASE_URL), indent=2) + "\n"
        for name in sorted(schemas.SCHEMAS)
    }
    rows = "\n".join(
        f"| `{schemas.COMMANDS[n]}` | [{n}.schema.json]({n}.schema.json) |" for n in sorted(schemas.SCHEMAS)
    )
    files["README.md"] = f"""# JSON Schemas of `--json` outputs

Generated from `src/awsemu/schemas.py` by `scripts/gen_schemas.py`; the contract tests validate real
outputs against them. JSON Schema draft 2020-12. Objects allow fields that aren't listed: new fields
can be added without notice (docs/scripting.md), so don't set `additionalProperties: false` on top.

| Output | Schema |
| --- | --- |
{rows}

Validate in a script, with [check-jsonschema](https://github.com/python-jsonschema/check-jsonschema):

```bash
awsemu status --json > status.json
check-jsonschema --schemafile {BASE_URL}/status.schema.json status.json
```
"""
    return files


def main() -> int:
    check = "--check" in sys.argv
    files = render()
    stale = []
    for name, text in files.items():
        path = OUT / name
        if path.exists() and path.read_text(encoding="utf-8") == text:
            continue
        stale.append(name)
        if not check:
            OUT.mkdir(parents=True, exist_ok=True)
            path.write_text(text, encoding="utf-8")
    extra = sorted(p.name for p in OUT.glob("*.json") if p.name not in files) if OUT.exists() else []
    if check:
        if stale or extra:
            print(f"docs/schemas is out of date ({', '.join(stale + extra)}): run python scripts/gen_schemas.py")
            return 1
        print("docs/schemas is up to date")
        return 0
    for name in extra:
        (OUT / name).unlink()
    print(f"wrote {len(files)} file(s) in docs/schemas" if stale or extra else "docs/schemas is up to date")
    return 0


if __name__ == "__main__":
    sys.exit(main())
