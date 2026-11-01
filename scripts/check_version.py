"""Keep release versions identical across Python, Rust, npm manifests and the CHANGELOG."""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _toml_version(path: Path, table: str) -> str:
    text = path.read_text(encoding="utf-8")
    match = re.search(rf"^\[{re.escape(table)}\]\n(?:.*\n)*?version\s*=\s*\"([^\"]+)\"", text, re.MULTILINE)
    if not match:
        raise SystemExit(f"no version in {path} [{table}]")
    return match.group(1)


def collect_versions() -> dict[str, str]:
    versions: dict[str, str] = {}
    for name in ["package.json", "frontend/package.json", "src-tauri/tauri.conf.json"]:
        versions[name] = json.loads((ROOT / name).read_text(encoding="utf-8"))["version"]
    for name in ["package-lock.json", "frontend/package-lock.json"]:
        path = ROOT / name
        if path.is_file():
            data = json.loads(path.read_text(encoding="utf-8"))
            versions[name] = data["version"]
            versions[f"{name} root package"] = data["packages"][""]["version"]
    versions["src-tauri/Cargo.toml"] = _toml_version(ROOT / "src-tauri/Cargo.toml", "package")
    lock = ROOT / "src-tauri/Cargo.lock"
    if lock.is_file():
        text = lock.read_text(encoding="utf-8")
        match = re.search(r'\[\[package\]\]\nname = "rka3000-desktop"\nversion = "([^"]+)"', text)
        if not match:
            raise SystemExit("Cargo.lock has no rka3000-desktop package")
        versions["src-tauri/Cargo.lock"] = match.group(1)
    module = (ROOT / "src/rka_desktop/__init__.py").read_text(encoding="utf-8")
    versions["Python __version__"] = re.search(r'__version__ = "([^"]+)"', module)[1]
    changelog = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
    released = re.findall(r"^##\s*\[(\d+\.\d+\.\d+(?:-[0-9A-Za-z.]+)?)\]", changelog, re.MULTILINE)
    if not released:
        raise SystemExit("CHANGELOG.md has no released version section")
    versions["CHANGELOG.md top section"] = released[0]
    return versions


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--tag", help="Release tag; must equal v<version>")
    args = parser.parse_args()
    versions = collect_versions()
    expected = versions["Python __version__"]
    mismatches = [f"{name}={version}" for name, version in versions.items() if version != expected]
    if mismatches:
        print(f"Version mismatch (expected {expected}): " + ", ".join(mismatches), file=sys.stderr)
        return 1
    if args.tag and args.tag != f"v{expected}":
        print(f"Tag {args.tag} does not match v{expected}", file=sys.stderr)
        return 1
    print(f"All manifest versions match: {expected}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
