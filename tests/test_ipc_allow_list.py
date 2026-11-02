"""The desktop shell forwards only allow-listed API paths; every page route must be on that list."""

from __future__ import annotations

import re
from pathlib import Path

from rka_desktop.adapters.api.server import ROUTES

MAIN_RS = Path(__file__).resolve().parents[1] / "src-tauri" / "src" / "main.rs"


def test_every_python_route_segment_is_named_in_the_rust_allow_list():
    source = MAIN_RS.read_text(encoding="utf-8")
    block = source[source.index("fn allowed("):source.index("#[tauri::command]")]
    literals = set(re.findall(r'"([a-z-]+)"', block))
    missing = []
    for pattern, _methods, _handler in ROUTES:
        segments = [segment for segment in pattern.pattern.strip("/").split("/") if not segment.startswith("(")]
        if segments == ["api", "shutdown"]:
            assert "shutdown" not in literals  # only the shell itself may stop the backend
            continue
        missing += [f"{pattern.pattern}:{segment}" for segment in segments if segment not in literals]
    assert not missing, f"routes missing from src-tauri allow-list: {missing}"
