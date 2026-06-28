from __future__ import annotations

import argparse
import re
import sys
from datetime import date
from pathlib import Path

INIT_PATH = Path("src/rka_desktop/__init__.py")
CHANGELOG_PATH = Path("CHANGELOG.md")


def read_version() -> str:
    content = INIT_PATH.read_text(encoding="utf-8")
    match = re.search(r'^__version__\s*=\s*"([^"]+)"', content, re.MULTILINE)
    if not match:
        raise RuntimeError("Could not find __version__")
    return match.group(1)


def write_version(new_version: str) -> None:
    content = INIT_PATH.read_text(encoding="utf-8")
    content = re.sub(
        r'^__version__\s*=\s*"[^"]+"',
        f'__version__ = "{new_version}"',
        content,
        flags=re.MULTILINE,
    )
    INIT_PATH.write_text(content, encoding="utf-8")


def extract_notes(version: str) -> str:
    content = CHANGELOG_PATH.read_text(encoding="utf-8")
    pattern = re.compile(
        rf"^##\s*\[{re.escape(version)}\][^\n]*\n(.*?)(?=^##\s*\[|\Z)",
        re.MULTILINE | re.DOTALL,
    )
    match = pattern.search(content)
    if not match:
        raise RuntimeError(f"No CHANGELOG section for version {version}")
    return match.group(1).strip()


def promote_unreleased(version: str) -> None:
    """Move [Unreleased] content into a new dated [version] section."""
    content = CHANGELOG_PATH.read_text(encoding="utf-8")
    today = date.today().isoformat()
    new_block = f"## [Unreleased]\n\n## [{version}] - {today}\n"
    content = re.sub(r"^##\s*\[Unreleased\]\s*\n", new_block, content, count=1, flags=re.MULTILINE)
    CHANGELOG_PATH.write_text(content, encoding="utf-8")


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description="RKA release helper")
    sub = parser.add_subparsers(dest="command", required=True)

    bump = sub.add_parser("bump", help="set version and promote Unreleased")
    bump.add_argument("version")

    notes = sub.add_parser("notes", help="print CHANGELOG notes for a version")
    notes.add_argument("version")

    sub.add_parser("current", help="print the current version")

    args = parser.parse_args(argv)

    if args.command == "current":
        print(read_version())
    elif args.command == "notes":
        print(extract_notes(args.version))
    elif args.command == "bump":
        write_version(args.version)
        promote_unreleased(args.version)
        print(f"bumped to {args.version}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
