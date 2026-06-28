import re
from pathlib import Path

import rka_desktop


def test_package_version_is_valid_semver():
    # Version-agnostic: the single source must be a valid SemVer string. The exact
    # value is validated against the CHANGELOG by scripts/checks/verify_version_sync.py.
    assert re.fullmatch(r"\d+\.\d+\.\d+", rka_desktop.__version__)


def test_package_version_matches_changelog_top():
    text = Path("CHANGELOG.md").read_text(encoding="utf-8")
    versions = re.findall(r"^##\s*\[(\d+\.\d+\.\d+)\]", text, re.MULTILINE)
    assert versions and versions[0] == rka_desktop.__version__


def test_pyproject_uses_dynamic_version():
    text = Path("pyproject.toml").read_text(encoding="utf-8")
    assert 'dynamic = ["version"]' in text
    assert 'version = {attr = "rka_desktop.__version__"}' in text
    # No hardcoded literal project version remains.
    assert not re.search(r'^version\s*=\s*"\d', text, re.MULTILINE)
