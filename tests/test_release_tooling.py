import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_changelog_top_version_matches_package():
    import rka_desktop

    text = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
    versions = re.findall(r"^##\s*\[(\d+\.\d+\.\d+(?:-[0-9A-Za-z.]+)?)\]", text, re.MULTILINE)
    assert versions, "no released version section found in CHANGELOG"
    assert versions[0] == rka_desktop.__version__


def test_check_version_passes_and_rejects_wrong_tag():
    ok = subprocess.run([sys.executable, "scripts/check_version.py"], capture_output=True, text=True, cwd=ROOT)
    assert ok.returncode == 0, ok.stderr
    bad = subprocess.run([sys.executable, "scripts/check_version.py", "--tag", "v0.0.0"], capture_output=True, text=True, cwd=ROOT)
    assert bad.returncode == 1 and "does not match" in bad.stderr


def test_release_script_extract_notes():
    result = subprocess.run([sys.executable, "scripts/release.py", "notes", "0.2.0"], capture_output=True, text=True, cwd=ROOT)
    assert result.returncode == 0, result.stderr
    assert "multi-device" in result.stdout.lower()
