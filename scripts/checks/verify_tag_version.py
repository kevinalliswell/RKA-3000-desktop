from __future__ import annotations

import os
import re
import sys
from pathlib import Path


def read_project_version(_pyproject_path: Path) -> str:
    init_path = Path("src/rka_desktop/__init__.py")
    content = init_path.read_text(encoding="utf-8")
    match = re.search(r'^__version__\s*=\s*"([^"]+)"', content, re.MULTILINE)
    if not match:
        raise RuntimeError("Could not find __version__ in src/rka_desktop/__init__.py")
    return match.group(1)


def main() -> int:
    ref_name = os.environ.get("GITHUB_REF_NAME", "").strip()
    if not ref_name:
        raise RuntimeError("GITHUB_REF_NAME is required")

    tag_version = ref_name[1:] if ref_name.startswith("v") else ref_name
    project_version = read_project_version(Path("pyproject.toml"))

    if tag_version != project_version:
        raise RuntimeError(
            f"Tag version '{tag_version}' does not match pyproject.toml version '{project_version}'"
        )

    print(f"version check ok: tag={tag_version}, pyproject={project_version}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(str(exc), file=sys.stderr)
        raise SystemExit(1)

