import re
from pathlib import Path

import rka_desktop


def test_package_version_is_bumped():
    assert rka_desktop.__version__ == "0.2.0"


def test_pyproject_uses_dynamic_version():
    text = Path("pyproject.toml").read_text(encoding="utf-8")
    assert 'dynamic = ["version"]' in text
    assert 'version = {attr = "rka_desktop.__version__"}' in text
    # No hardcoded literal project version remains.
    assert not re.search(r'^version\s*=\s*"\d', text, re.MULTILINE)
