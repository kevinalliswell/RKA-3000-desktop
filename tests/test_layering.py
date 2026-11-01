"""Dependency direction guard: inner layers never import outer layers or I/O libraries."""

from __future__ import annotations

import ast
from pathlib import Path

SRC = Path(__file__).resolve().parents[1] / "src" / "rka_desktop"

FORBIDDEN = {
    "domain": ("rka_desktop.application", "rka_desktop.adapters", "rka_desktop.infrastructure", "rka_desktop.bootstrap",
               "serial", "pymodbus", "sqlite3", "http", "openpyxl", "threading"),
    "application": ("rka_desktop.adapters", "rka_desktop.bootstrap", "rka_desktop.infrastructure", "serial", "pymodbus",
                    "sqlite3", "http.server", "openpyxl"),
    "infrastructure": ("rka_desktop.adapters", "rka_desktop.bootstrap", "PySide6"),
}


def imports_of(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            names.add(node.module)
    return names


def test_layers_only_depend_inwards():
    violations = []
    for layer, forbidden in FORBIDDEN.items():
        for file in (SRC / layer).rglob("*.py"):
            if "_vendor" in file.parts:
                continue
            for name in imports_of(file):
                if any(name == item or name.startswith(item + ".") for item in forbidden):
                    violations.append(f"{file.relative_to(SRC)} imports {name}")
    assert not violations, "\n".join(violations)


def test_no_qt_anywhere():
    for file in SRC.rglob("*.py"):
        assert "PySide6" not in file.read_text(encoding="utf-8"), file
