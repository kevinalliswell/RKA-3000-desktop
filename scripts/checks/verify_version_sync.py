from __future__ import annotations

import re
import sys
from pathlib import Path


def read_package_version() -> str:
    content = Path("src/rka_desktop/__init__.py").read_text(encoding="utf-8")
    match = re.search(r'^__version__\s*=\s*"([^"]+)"', content, re.MULTILINE)
    if not match:
        raise RuntimeError("Could not find __version__ in src/rka_desktop/__init__.py")
    return match.group(1)


def read_changelog_top_version() -> str:
    content = Path("CHANGELOG.md").read_text(encoding="utf-8")
    versions = re.findall(r"^##\s*\[(\d+\.\d+\.\d+)\]", content, re.MULTILINE)
    if not versions:
        raise RuntimeError("No released version section found in CHANGELOG.md")
    return versions[0]


def main() -> int:
    package = read_package_version()
    changelog = read_changelog_top_version()
    if package != changelog:
        raise RuntimeError(
            f"Version mismatch: __version__={package} but CHANGELOG top={changelog}"
        )
    print(f"version sync ok: package={package}, changelog={changelog}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:  # noqa: BLE001
        print(str(exc), file=sys.stderr)
        raise SystemExit(1)
