import subprocess
import sys
from pathlib import Path


def test_changelog_top_version_matches_package():
    import rka_desktop

    text = Path("CHANGELOG.md").read_text(encoding="utf-8")
    # First "## [x.y.z]" heading after Unreleased must equal the package version.
    import re

    versions = re.findall(r"^##\s*\[(\d+\.\d+\.\d+)\]", text, re.MULTILINE)
    assert versions, "no released version section found in CHANGELOG"
    assert versions[0] == rka_desktop.__version__


def test_verify_version_sync_passes():
    result = subprocess.run(
        [sys.executable, "scripts/checks/verify_version_sync.py"],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr


def test_release_script_extract_notes():
    result = subprocess.run(
        [sys.executable, "scripts/release.py", "notes", "0.2.0"],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    assert "multi-device" in result.stdout.lower()
