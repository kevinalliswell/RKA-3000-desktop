from __future__ import annotations

import argparse
import re
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
INIT_PATH = ROOT / "src/rka_desktop/__init__.py"
CHANGELOG_PATH = ROOT / "CHANGELOG.md"
MANIFESTS = [ROOT / "package.json", ROOT / "frontend/package.json", ROOT / "src-tauri/tauri.conf.json",
             ROOT / "package-lock.json", ROOT / "frontend/package-lock.json"]
CARGO = [ROOT / "src-tauri/Cargo.toml", ROOT / "src-tauri/Cargo.lock"]


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
    for manifest in MANIFESTS:
        if not manifest.is_file():
            continue
        text = manifest.read_text(encoding="utf-8")
        text = re.sub(r'("version":\s*")[^"]+(")', rf"\g<1>{new_version}\g<2>", text, count=1)
        if manifest.name == "package-lock.json":
            text = re.sub(r'("":\s*\{\s*"name":\s*"[^"]+",\s*"version":\s*")[^"]+(")', rf"\g<1>{new_version}\g<2>", text, count=1)
        manifest.write_text(text, encoding="utf-8")
    cargo_toml = CARGO[0].read_text(encoding="utf-8")
    cargo_toml = re.sub(r'^(version\s*=\s*")[^"]+(")', rf"\g<1>{new_version}\g<2>", cargo_toml, count=1, flags=re.MULTILINE)
    CARGO[0].write_text(cargo_toml, encoding="utf-8")
    if CARGO[1].is_file():
        lock = CARGO[1].read_text(encoding="utf-8")
        lock = re.sub(r'(\[\[package\]\]\nname = "rka3000-desktop"\nversion = ")[^"]+(")', rf"\g<1>{new_version}\g<2>", lock, count=1)
        CARGO[1].write_text(lock, encoding="utf-8")


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
    # CHANGELOG is UTF-8 with Chinese text; the Windows console default (cp1252) cannot print it.
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description="RKA-3000 release helper: bumps every manifest and promotes CHANGELOG Unreleased")
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
