import re
from pathlib import Path

import rka_desktop

ROOT = Path(__file__).resolve().parents[1]


def test_package_version_is_valid_semver():
    assert re.fullmatch(r"\d+\.\d+\.\d+(?:-[0-9A-Za-z.]+)?", rka_desktop.__version__)


def test_pyproject_uses_dynamic_version():
    text = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    assert 'dynamic = ["version"]' in text
    assert 'version = {attr = "rka_desktop.__version__"}' in text
    assert not re.search(r'^version\s*=\s*"\d', text, re.MULTILINE)


def test_frozen_entry_point_imports_only_the_api_adapter():
    text = (ROOT / "scripts" / "backend_entry.py").read_text(encoding="utf-8")
    assert "rka_desktop.adapters.api.server" in text
    assert "PySide6" not in text
